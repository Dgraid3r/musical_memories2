from unittest.mock import MagicMock, patch

from app.spotify_client import SEARCH_MIN_INTERVAL_SECONDS, reset_throttle, search_playlists


def _fake_search_response(name="Chill Vibes"):
    return {
        "playlists": {
            "items": [
                {
                    "id": "abc123",
                    "name": name,
                    "external_urls": {"spotify": "https://open.spotify.com/playlist/abc123"},
                    "images": [],
                    "owner": {"display_name": "spotify"},
                    "tracks": {"total": 1},
                }
            ]
        }
    }


def test_single_request_is_not_delayed():
    """The throttle must never add latency to an isolated, normal
    request - only back-to-back calls should ever wait."""
    reset_throttle()
    fake_client = MagicMock()
    fake_client.search.return_value = _fake_search_response()

    with (
        patch("app.spotify_client.get_spotify_client", return_value=fake_client),
        patch("app.spotify_client.time.sleep") as mock_sleep,
    ):
        search_playlists("solo query")

    mock_sleep.assert_not_called()


def test_rapid_back_to_back_calls_are_throttled():
    reset_throttle()
    fake_client = MagicMock()
    fake_client.search.side_effect = [_fake_search_response("first"), _fake_search_response("second")]

    with (
        patch("app.spotify_client.get_spotify_client", return_value=fake_client),
        patch("app.spotify_client.time.sleep") as mock_sleep,
    ):
        search_playlists("throttle query one")
        search_playlists("throttle query two")

    mock_sleep.assert_called_once()
    waited = mock_sleep.call_args[0][0]
    # A tiny floating-point epsilon above SEARCH_MIN_INTERVAL_SECONDS is
    # expected here (real time.monotonic() calls, mocked-out sleep) - what
    # matters is that it's a small, positive, roughly-the-interval wait,
    # not that it's exactly bounded to the nanosecond.
    assert 0 < waited <= SEARCH_MIN_INTERVAL_SECONDS + 0.01


def test_a_cache_hit_never_waits_on_the_throttle():
    """The throttle only guards the actual outbound call - a cached
    result must return instantly regardless of how recently the client
    called Spotify."""
    reset_throttle()
    fake_client = MagicMock()
    fake_client.search.return_value = _fake_search_response()

    with patch("app.spotify_client.get_spotify_client", return_value=fake_client):
        search_playlists("cached throttle query")

    with (
        patch("app.spotify_client.get_spotify_client", return_value=fake_client),
        patch("app.spotify_client.time.sleep") as mock_sleep,
    ):
        search_playlists("cached throttle query")

    mock_sleep.assert_not_called()
