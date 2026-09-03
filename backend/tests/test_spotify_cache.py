import time
from unittest.mock import MagicMock, patch

from cachetools import TTLCache

import app.spotify_client as spotify_client_module
from app.spotify_client import search_playlists


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
                }
            ]
        }
    }


def test_repeated_search_within_ttl_hits_cache_not_spotify(monkeypatch):
    fake_client = MagicMock()
    fake_client.search.return_value = _fake_search_response()

    with patch("app.spotify_client.get_spotify_client", return_value=fake_client):
        search_playlists("chill")
        search_playlists("chill")
        search_playlists("chill")

    assert fake_client.search.call_count == 1


def test_cache_hit_returns_equivalent_results(monkeypatch):
    fake_client = MagicMock()
    fake_client.search.return_value = _fake_search_response()

    with patch("app.spotify_client.get_spotify_client", return_value=fake_client):
        first = search_playlists("chill")
        second = search_playlists("chill")

    assert first == second
    assert first[0].id == "abc123"


def test_different_queries_are_cached_separately(monkeypatch):
    fake_client = MagicMock()
    fake_client.search.return_value = _fake_search_response()

    with patch("app.spotify_client.get_spotify_client", return_value=fake_client):
        search_playlists("chill")
        search_playlists("jazz")

    assert fake_client.search.call_count == 2


def test_different_limits_are_cached_separately(monkeypatch):
    fake_client = MagicMock()
    fake_client.search.return_value = _fake_search_response()

    with patch("app.spotify_client.get_spotify_client", return_value=fake_client):
        search_playlists("chill", limit=10)
        search_playlists("chill", limit=5)

    assert fake_client.search.call_count == 2


def test_cache_expires_after_ttl(monkeypatch):
    # A short-lived cache swapped in just for this test, rather than
    # sleeping 10 minutes against the real module-level TTL.
    monkeypatch.setattr(spotify_client_module, "_search_cache", TTLCache(maxsize=8, ttl=0.05))

    fake_client = MagicMock()
    fake_client.search.return_value = _fake_search_response()

    with patch("app.spotify_client.get_spotify_client", return_value=fake_client):
        search_playlists("chill")
        time.sleep(0.1)
        search_playlists("chill")

    assert fake_client.search.call_count == 2


def test_cache_is_cleared_between_tests_by_the_autouse_fixture():
    """Sanity check for the conftest.py fixture itself: if the previous
    test's cache entry for "chill" leaked in here, this would see a
    call_count of 0 instead of 1."""
    fake_client = MagicMock()
    fake_client.search.return_value = _fake_search_response()

    with patch("app.spotify_client.get_spotify_client", return_value=fake_client):
        search_playlists("chill")

    assert fake_client.search.call_count == 1
