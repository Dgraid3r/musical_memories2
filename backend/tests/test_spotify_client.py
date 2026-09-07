from unittest.mock import MagicMock, patch

import pytest
from spotipy.exceptions import SpotifyException

from app.spotify_client import search_playlists
from app.spotify_retry import SpotifyUnavailableError


def _fake_search_response():
    return {
        "playlists": {
            "items": [
                {
                    "id": "abc123",
                    "name": "Chill Vibes",
                    "external_urls": {"spotify": "https://open.spotify.com/playlist/abc123"},
                    "images": [{"url": "https://example.com/cover.jpg"}],
                    "owner": {"display_name": "spotify"},
                    "tracks": {"total": 42},
                },
                # Spotify's search API can return null slots in the items array.
                None,
            ]
        }
    }


def test_search_playlists_parses_response():
    fake_client = MagicMock()
    fake_client.search.return_value = _fake_search_response()

    with patch("app.spotify_client.get_spotify_client", return_value=fake_client):
        results = search_playlists("chill")

    assert len(results) == 1
    result = results[0]
    assert result.id == "abc123"
    assert result.name == "Chill Vibes"
    assert result.url == "https://open.spotify.com/playlist/abc123"
    assert result.image_url == "https://example.com/cover.jpg"
    assert result.owner == "spotify"
    assert result.track_count == 42


def test_search_playlists_handles_missing_image():
    response = _fake_search_response()
    response["playlists"]["items"][0]["images"] = []
    fake_client = MagicMock()
    fake_client.search.return_value = response

    with patch("app.spotify_client.get_spotify_client", return_value=fake_client):
        results = search_playlists("chill")

    assert results[0].image_url is None


def test_search_playlists_handles_missing_owner_name():
    response = _fake_search_response()
    response["playlists"]["items"][0]["owner"] = {}
    fake_client = MagicMock()
    fake_client.search.return_value = response

    with patch("app.spotify_client.get_spotify_client", return_value=fake_client):
        results = search_playlists("chill")

    assert results[0].owner == "Unknown"


def test_search_playlists_handles_empty_results():
    fake_client = MagicMock()
    fake_client.search.return_value = {"playlists": {"items": []}}

    with patch("app.spotify_client.get_spotify_client", return_value=fake_client):
        results = search_playlists("nonexistent-query-xyz")

    assert results == []


# --- 429 handling --------------------------------------------------------


def test_search_retries_after_a_429_and_succeeds():
    fake_client = MagicMock()
    fake_client.search.side_effect = [
        SpotifyException(429, -1, "rate limited", headers={"Retry-After": "1"}),
        _fake_search_response(),
    ]

    with (
        patch("app.spotify_client.get_spotify_client", return_value=fake_client),
        patch("app.spotify_retry.time.sleep"),
    ):
        results = search_playlists("chill retry query")

    assert len(results) == 1
    assert fake_client.search.call_count == 2


def test_search_raises_clean_error_once_retries_are_exhausted():
    fake_client = MagicMock()
    fake_client.search.side_effect = SpotifyException(429, -1, "rate limited", headers={})

    with (
        patch("app.spotify_client.get_spotify_client", return_value=fake_client),
        patch("app.spotify_retry.time.sleep"),
    ):
        with pytest.raises(SpotifyUnavailableError) as exc_info:
            search_playlists("chill exhausted query")

    assert "temporarily unavailable" in str(exc_info.value)


def test_search_does_not_cache_a_failed_call():
    """A 429 that exhausts retries must not poison the cache with a
    failure - the next call should still try Spotify again, not return a
    cached error."""
    fake_client = MagicMock()
    fake_client.search.side_effect = SpotifyException(429, -1, "rate limited", headers={})

    with (
        patch("app.spotify_client.get_spotify_client", return_value=fake_client),
        patch("app.spotify_retry.time.sleep"),
    ):
        with pytest.raises(SpotifyUnavailableError):
            search_playlists("chill uncached query")

        fake_client.search.side_effect = None
        fake_client.search.return_value = _fake_search_response()
        results = search_playlists("chill uncached query")

    assert len(results) == 1
