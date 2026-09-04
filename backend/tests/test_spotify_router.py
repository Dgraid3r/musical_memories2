from unittest.mock import patch

from app.schemas import PlaylistResult
from app.spotify_retry import SpotifyUnavailableError


def test_search_requires_query_param(client):
    res = client.get("/api/spotify/playlists")
    assert res.status_code == 422


def test_search_returns_results_from_search_playlists(client):
    fake_results = [
        PlaylistResult(
            id="abc",
            name="Chill Vibes",
            url="https://open.spotify.com/playlist/abc",
            image_url=None,
            owner="spotify",
            track_count=42,
        )
    ]
    with patch("app.routers.spotify.search_playlists", return_value=fake_results):
        res = client.get("/api/spotify/playlists?q=chill")

    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["id"] == "abc"
    assert body[0]["name"] == "Chill Vibes"


def test_search_missing_credentials_returns_503(client):
    with patch(
        "app.routers.spotify.search_playlists",
        side_effect=RuntimeError("SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET are not set."),
    ):
        res = client.get("/api/spotify/playlists?q=chill")

    assert res.status_code == 503


def test_search_does_not_require_auth(client):
    with patch("app.routers.spotify.search_playlists", return_value=[]):
        res = client.get("/api/spotify/playlists?q=chill")

    assert res.status_code == 200


def test_search_rate_limit_exhausted_returns_clean_503_not_a_raw_error(client):
    with patch(
        "app.routers.spotify.search_playlists",
        side_effect=SpotifyUnavailableError("Spotify is temporarily unavailable, try again shortly."),
    ):
        res = client.get("/api/spotify/playlists?q=chill")

    assert res.status_code == 503
    assert res.json() == {"detail": "Spotify is temporarily unavailable, try again shortly."}
