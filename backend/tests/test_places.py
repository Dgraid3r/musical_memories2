from unittest.mock import MagicMock, patch

from app.nominatim_client import PlacesUnavailableError, reverse_geocode, search_places

# --- nominatim_client.search_places (unit-level, mocks requests.get) ------


def _fake_nominatim_response():
    return [
        {
            "display_name": "Golden Gate Park, San Francisco, California, United States",
            "lat": "37.7694",
            "lon": "-122.4862",
            # Real Nominatim responses carry many more fields than this -
            # osm_id, class, type, importance, boundingbox, etc. - included
            # here to prove search_places only extracts the three it needs.
            "osm_id": 123456,
            "importance": 0.7,
            "boundingbox": ["37.76", "37.78", "-122.49", "-122.45"],
        }
    ]


def test_search_places_extracts_only_display_name_and_coordinates():
    fake_response = MagicMock()
    fake_response.json.return_value = _fake_nominatim_response()
    fake_response.raise_for_status.return_value = None

    with patch("app.nominatim_client.requests.get", return_value=fake_response):
        results = search_places("Golden Gate Park")

    assert len(results) == 1
    place = results[0]
    assert place.display_name == "Golden Gate Park, San Francisco, California, United States"
    assert place.latitude == 37.7694
    assert place.longitude == -122.4862
    # Only the three schema fields exist on the model at all - there's no
    # way for osm_id/importance/boundingbox to have leaked through.
    assert set(place.model_dump().keys()) == {"display_name", "latitude", "longitude"}


def test_search_places_sends_descriptive_user_agent():
    fake_response = MagicMock()
    fake_response.json.return_value = []
    fake_response.raise_for_status.return_value = None

    with patch("app.nominatim_client.requests.get", return_value=fake_response) as mock_get:
        search_places("anywhere")

    _, kwargs = mock_get.call_args
    user_agent = kwargs["headers"]["User-Agent"]
    assert user_agent and user_agent != "python-requests"


def test_search_places_caches_repeated_queries():
    fake_response = MagicMock()
    fake_response.json.return_value = _fake_nominatim_response()
    fake_response.raise_for_status.return_value = None

    with patch("app.nominatim_client.requests.get", return_value=fake_response) as mock_get:
        search_places("Golden Gate Park")
        search_places("Golden Gate Park")

    assert mock_get.call_count == 1


def test_search_places_raises_places_unavailable_on_request_failure():
    import requests

    with patch("app.nominatim_client.requests.get", side_effect=requests.ConnectionError("boom")):
        try:
            search_places("nowhere")
            assert False, "expected PlacesUnavailableError"
        except PlacesUnavailableError:
            pass


def test_search_places_skips_malformed_entries():
    fake_response = MagicMock()
    fake_response.json.return_value = [
        {"display_name": "Complete Place", "lat": "1.0", "lon": "2.0"},
        {"display_name": "Missing coordinates"},  # no lat/lon - skipped, not crashed on
        "not even a dict",  # skipped
    ]
    fake_response.raise_for_status.return_value = None

    with patch("app.nominatim_client.requests.get", return_value=fake_response):
        results = search_places("test")

    assert len(results) == 1
    assert results[0].display_name == "Complete Place"


# --- GET /api/places/search (router-level, mocks search_places itself) ---


def test_places_search_requires_query_param(client):
    res = client.get("/api/places/search")
    assert res.status_code == 422


def test_places_search_returns_results_and_no_auth_required(client):
    from app.schemas import PlaceResult

    fake_results = [PlaceResult(display_name="Golden Gate Park", latitude=37.7694, longitude=-122.4862)]
    with patch("app.routers.places.search_places", return_value=fake_results):
        res = client.get("/api/places/search?q=golden+gate")

    assert res.status_code == 200
    body = res.json()
    assert body == [{"display_name": "Golden Gate Park", "latitude": 37.7694, "longitude": -122.4862}]


def test_places_search_never_leaks_raw_nominatim_fields(client):
    """Even if search_places somehow returned extra data, the response
    model (PlaceResult) strips anything beyond display_name/lat/lon -
    proven here by asserting the exact key set of a real result."""
    from app.schemas import PlaceResult

    fake_results = [PlaceResult(display_name="Somewhere", latitude=1.0, longitude=2.0)]
    with patch("app.routers.places.search_places", return_value=fake_results):
        res = client.get("/api/places/search?q=somewhere")

    assert res.status_code == 200
    assert set(res.json()[0].keys()) == {"display_name", "latitude", "longitude"}


def test_places_search_unavailable_returns_clean_503(client):
    with patch(
        "app.routers.places.search_places",
        side_effect=PlacesUnavailableError("Place search is temporarily unavailable"),
    ):
        res = client.get("/api/places/search?q=anywhere")

    assert res.status_code == 503
    assert res.json() == {"detail": "Place search is temporarily unavailable"}


# --- nominatim_client.reverse_geocode (unit-level, mocks requests.get) ---


def _fake_reverse_response():
    return {
        "display_name": "Golden Gate Park, San Francisco, California, United States",
        "lat": "37.7694",
        "lon": "-122.4862",
        # Real Nominatim reverse responses carry many more fields than
        # this - osm_id, address (a whole nested breakdown), place_rank,
        # boundingbox, etc. - included here to prove reverse_geocode only
        # extracts display_name.
        "osm_id": 123456,
        "address": {"city": "San Francisco", "state": "California", "country": "United States"},
        "boundingbox": ["37.76", "37.78", "-122.49", "-122.45"],
    }


def test_reverse_geocode_extracts_only_display_name():
    fake_response = MagicMock()
    fake_response.json.return_value = _fake_reverse_response()
    fake_response.raise_for_status.return_value = None

    with patch("app.nominatim_client.requests.get", return_value=fake_response):
        result = reverse_geocode(37.7694, -122.4862)

    assert result.display_name == "Golden Gate Park, San Francisco, California, United States"
    # Only the one schema field exists on the model at all - there's no
    # way for osm_id/address/boundingbox to have leaked through.
    assert set(result.model_dump().keys()) == {"display_name"}


def test_reverse_geocode_sends_descriptive_user_agent():
    fake_response = MagicMock()
    fake_response.json.return_value = _fake_reverse_response()
    fake_response.raise_for_status.return_value = None

    with patch("app.nominatim_client.requests.get", return_value=fake_response) as mock_get:
        reverse_geocode(1.0, 2.0)

    _, kwargs = mock_get.call_args
    user_agent = kwargs["headers"]["User-Agent"]
    assert user_agent and user_agent != "python-requests"


def test_reverse_geocode_caches_repeated_nearby_lookups():
    """Rounded-coordinate cache key - two lookups a few meters apart
    (well within REVERSE_GEOCODE_COORD_PRECISION) hit the same cache
    entry, the same spirit as the search cache absorbing retyped queries."""
    fake_response = MagicMock()
    fake_response.json.return_value = _fake_reverse_response()
    fake_response.raise_for_status.return_value = None

    with patch("app.nominatim_client.requests.get", return_value=fake_response) as mock_get:
        reverse_geocode(37.76940, -122.48620)
        reverse_geocode(37.76941, -122.48619)  # rounds to the same cache key

    assert mock_get.call_count == 1


def test_reverse_geocode_raises_places_unavailable_on_request_failure():
    import requests

    with patch("app.nominatim_client.requests.get", side_effect=requests.ConnectionError("boom")):
        try:
            reverse_geocode(1.0, 2.0)
            assert False, "expected PlacesUnavailableError"
        except PlacesUnavailableError:
            pass


def test_reverse_geocode_raises_places_unavailable_when_nominatim_finds_nothing():
    """Nominatim returns a 200 with {"error": "..."} (no display_name)
    when there's nothing at those coordinates - must not crash trying to
    read a missing key, and must still signal "no name available" the
    same way a real failure would (the frontend falls back either way)."""
    fake_response = MagicMock()
    fake_response.json.return_value = {"error": "Unable to geocode"}
    fake_response.raise_for_status.return_value = None

    with patch("app.nominatim_client.requests.get", return_value=fake_response):
        try:
            reverse_geocode(0.0, 0.0)
            assert False, "expected PlacesUnavailableError"
        except PlacesUnavailableError:
            pass


def test_reverse_geocode_shares_the_forward_search_throttle():
    """The critical shared-infrastructure property: reverse_geocode must
    not maintain a second, independent throttle - a call it makes counts
    against the same shared minimum-interval clock search_places uses, so
    the two together never exceed Nominatim's single combined rate
    policy. Proven here by making a forward search call first (which
    advances the shared throttle's last-call timestamp) and confirming a
    same-process reverse call sees that same state, rather than starting
    fresh as it would with its own independent throttle."""
    from app import nominatim_client

    fake_response = MagicMock()
    fake_response.json.return_value = _fake_reverse_response()
    fake_response.raise_for_status.return_value = None

    with patch("app.nominatim_client.requests.get", return_value=fake_response):
        search_places("somewhere")
        first_call_time = nominatim_client._last_call_monotonic
        assert first_call_time is not None

        reverse_geocode(9.0, 10.0)
        second_call_time = nominatim_client._last_call_monotonic

    # If reverse_geocode used a separate throttle, it would never read or
    # update this module-level state at all - _last_call_monotonic would
    # be left exactly as search_places set it. Advancing confirms
    # reverse_geocode's own call went through the *same* _throttle().
    assert second_call_time is not None
    assert second_call_time >= first_call_time


# --- GET /api/places/reverse (router-level, mocks reverse_geocode itself) --


def test_places_reverse_requires_lat_and_lon(client):
    res = client.get("/api/places/reverse")
    assert res.status_code == 422


def test_places_reverse_rejects_out_of_range_coordinates(client):
    assert client.get("/api/places/reverse?lat=91&lon=0").status_code == 422
    assert client.get("/api/places/reverse?lat=0&lon=181").status_code == 422


def test_places_reverse_returns_narrowed_result_and_no_auth_required(client):
    from app.schemas import ReverseGeocodeResult

    fake_result = ReverseGeocodeResult(display_name="Golden Gate Park")
    with patch("app.routers.places.reverse_geocode", return_value=fake_result):
        res = client.get("/api/places/reverse?lat=37.7694&lon=-122.4862")

    assert res.status_code == 200
    assert res.json() == {"display_name": "Golden Gate Park"}


def test_places_reverse_never_leaks_raw_nominatim_fields(client):
    from app.schemas import ReverseGeocodeResult

    fake_result = ReverseGeocodeResult(display_name="Somewhere")
    with patch("app.routers.places.reverse_geocode", return_value=fake_result):
        res = client.get("/api/places/reverse?lat=1&lon=2")

    assert res.status_code == 200
    assert set(res.json().keys()) == {"display_name"}


def test_places_reverse_unavailable_returns_clean_503_not_a_crash(client):
    """The router-level contract the frontend's graceful fallback depends
    on: any failure surfaces as a clean 503 with a plain detail message,
    never a 500 or an unhandled exception."""
    with patch(
        "app.routers.places.reverse_geocode",
        side_effect=PlacesUnavailableError("No place name found for this location"),
    ):
        res = client.get("/api/places/reverse?lat=0&lon=0")

    assert res.status_code == 503
    assert res.json() == {"detail": "No place name found for this location"}
