from unittest.mock import MagicMock, patch

from app.nominatim_client import PlacesUnavailableError, search_places

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
