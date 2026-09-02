from unittest.mock import MagicMock, patch

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
