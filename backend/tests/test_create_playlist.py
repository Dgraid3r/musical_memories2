"""Create-a-playlist from the entry picker: catalog track search, creating a
playlist on the user's linked account (with scope detection), and the
dormant "Generate from a prompt" path. Never calls real Spotify or Anthropic
- every outbound client is mocked."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic
import httpx
import pytest
from spotipy.exceptions import SpotifyException

from app import playlist_generator
from app.schemas import PlaylistResult, SuggestedTrack, TrackResult
from app.spotify_client import search_tracks
from app.spotify_oauth import SCOPE, create_user_playlist

WRITE_SCOPE = "playlist-read-private playlist-read-collaborative playlist-modify-private"
OLD_SCOPE = "playlist-read-private playlist-read-collaborative"

URI_A = "spotify:track:" + "A" * 22
URI_B = "spotify:track:" + "B" * 22


def _track(track_id: str, name: str = "Song") -> TrackResult:
    return TrackResult(id=track_id, uri=f"spotify:track:{track_id}", name=name, artists="Artist")


def _link_spotify(db_session, user_id: int, scope: str | None) -> None:
    from app.models import SpotifyToken

    db_session.add(
        SpotifyToken(
            user_id=user_id,
            access_token="valid-access",
            refresh_token="r",
            expires_at=datetime.utcnow() + timedelta(hours=1),
            scope=scope,
        )
    )
    db_session.commit()


# --- scope ---------------------------------------------------------------


def test_oauth_scope_requests_private_playlist_write_only():
    scopes = SCOPE.split()
    assert "playlist-modify-private" in scopes
    assert "playlist-modify-public" not in scopes


def test_status_reports_create_capability_by_scope(client, make_user, db_session):
    alice = make_user("alice")
    bob = make_user("bob")
    _link_spotify(db_session, alice["id"], WRITE_SCOPE)
    _link_spotify(db_session, bob["id"], OLD_SCOPE)

    assert client.get("/api/spotify/status", headers=alice["headers"]).json() == {
        "connected": True, "can_create_playlists": True,
    }
    assert client.get("/api/spotify/status", headers=bob["headers"]).json() == {
        "connected": True, "can_create_playlists": False,
    }


# --- search_tracks / GET /api/spotify/tracks ---------------------------------


def _fake_track_search_response():
    return {
        "tracks": {
            "items": [
                {
                    "id": "t1",
                    "uri": "spotify:track:t1",
                    "name": "Mr. Brightside",
                    "artists": [{"name": "The Killers"}, {"name": "Guest"}],
                    "album": {"name": "Hot Fuss", "images": [{"url": "big.jpg"}, {"url": "small.jpg"}]},
                    "external_urls": {"spotify": "https://open.spotify.com/track/t1"},
                    "duration_ms": 222000,
                },
                None,
            ]
        }
    }


def test_search_tracks_parses_and_caches():
    fake = MagicMock()
    fake.search.return_value = _fake_track_search_response()
    with patch("app.spotify_client.get_spotify_client", return_value=fake):
        first = search_tracks("brightside")
        second = search_tracks("brightside")

    assert fake.search.call_count == 1
    assert first == second
    assert len(first) == 1
    t = first[0]
    assert (t.id, t.uri, t.name, t.artists, t.album) == (
        "t1", "spotify:track:t1", "Mr. Brightside", "The Killers, Guest", "Hot Fuss",
    )
    assert t.image_url == "small.jpg"
    assert fake.search.call_args.kwargs["type"] == "track"


def test_search_tracks_clamps_limit_to_spotify_max():
    fake = MagicMock()
    fake.search.return_value = {"tracks": {"items": []}}
    with patch("app.spotify_client.get_spotify_client", return_value=fake):
        search_tracks("anything", limit=50)
    assert fake.search.call_args.kwargs["limit"] == 10


def test_track_search_endpoint(client):
    with patch("app.routers.spotify.search_tracks", return_value=[_track("t1")]) as mock_search:
        res = client.get("/api/spotify/tracks", params={"q": "brightside"})
    assert res.status_code == 200
    assert res.json()[0]["uri"] == "spotify:track:t1"
    mock_search.assert_called_once_with("brightside")


def test_track_search_endpoint_requires_query(client):
    assert client.get("/api/spotify/tracks").status_code == 422


# --- create_user_playlist (Spotify calls) ----------------------------------


def test_create_user_playlist_uses_current_spotify_endpoints():
    fake_sp = MagicMock()
    fake_sp._post.side_effect = [
        {"id": "newpl", "name": "Rainy", "external_urls": {"spotify": "https://open.spotify.com/playlist/newpl"},
         "images": [], "owner": {"display_name": "alice"}},
        {"snapshot_id": "s1"},
    ]
    with patch("app.spotify_oauth.spotipy.Spotify", return_value=fake_sp):
        result = create_user_playlist("tok", "Rainy", [URI_A, URI_B])

    create_call, add_call = fake_sp._post.call_args_list
    assert create_call.args == ("me/playlists",)
    assert create_call.kwargs["payload"]["name"] == "Rainy"
    assert create_call.kwargs["payload"]["public"] is False
    assert add_call.args == ("playlists/newpl/items",)
    assert add_call.kwargs["payload"] == {"uris": [URI_A, URI_B]}
    assert result == PlaylistResult(
        id="newpl", name="Rainy", url="https://open.spotify.com/playlist/newpl",
        image_url=None, owner="alice", track_count=2,
    )


# --- POST /api/spotify/playlists ------------------------------------------


def test_create_playlist_requires_auth(client):
    res = client.post("/api/spotify/playlists", json={"name": "x", "track_uris": [URI_A]})
    assert res.status_code == 401


def test_create_playlist_without_linked_account_prompts_connect(client, make_user):
    alice = make_user("alice")
    res = client.post("/api/spotify/playlists", headers=alice["headers"],
                      json={"name": "x", "track_uris": [URI_A]})
    assert res.status_code == 409
    assert res.json()["detail"] == "Connect Spotify to create playlists."


@pytest.mark.parametrize("scope", [OLD_SCOPE, None])
def test_create_playlist_with_read_only_token_prompts_reconnect(client, make_user, db_session, scope):
    alice = make_user("alice")
    _link_spotify(db_session, alice["id"], scope)
    with patch("app.routers.spotify.create_user_playlist") as mock_create:
        res = client.post("/api/spotify/playlists", headers=alice["headers"],
                          json={"name": "x", "track_uris": [URI_A]})
    assert res.status_code == 403
    assert res.json()["detail"] == "Reconnect Spotify to create playlists."
    mock_create.assert_not_called()


def test_create_playlist_happy_path(client, make_user, db_session):
    alice = make_user("alice")
    _link_spotify(db_session, alice["id"], WRITE_SCOPE)
    created = PlaylistResult(id="newpl", name="Rainy", url="https://open.spotify.com/playlist/newpl",
                             image_url=None, owner="alice", track_count=2)
    with patch("app.routers.spotify.create_user_playlist", return_value=created) as mock_create:
        res = client.post("/api/spotify/playlists", headers=alice["headers"],
                          json={"name": "  Rainy  ", "track_uris": [URI_A, URI_B, URI_A]})
    assert res.status_code == 201
    assert res.json() == created.model_dump()
    mock_create.assert_called_once_with("valid-access", "Rainy", [URI_A, URI_B])


def test_create_playlist_spotify_rejecting_token_prompts_reconnect(client, make_user, db_session):
    alice = make_user("alice")
    _link_spotify(db_session, alice["id"], WRITE_SCOPE)
    with patch("app.routers.spotify.create_user_playlist",
               side_effect=SpotifyException(403, -1, "Insufficient client scope")):
        res = client.post("/api/spotify/playlists", headers=alice["headers"],
                          json={"name": "x", "track_uris": [URI_A]})
    assert res.status_code == 403
    assert res.json()["detail"] == "Reconnect Spotify to create playlists."


@pytest.mark.parametrize(
    "body",
    [
        {"name": "", "track_uris": [URI_A]},
        {"name": "   ", "track_uris": [URI_A]},
        {"name": "x", "track_uris": []},
        {"name": "x", "track_uris": ["spotify:album:" + "A" * 22]},
        {"name": "x", "track_uris": ["not-a-uri"]},
        {"name": "x" * 101, "track_uris": [URI_A]},
    ],
)
def test_create_playlist_validates_input(client, make_user, db_session, body):
    alice = make_user("alice")
    _link_spotify(db_session, alice["id"], WRITE_SCOPE)
    res = client.post("/api/spotify/playlists", headers=alice["headers"], json=body)
    assert res.status_code == 422


# --- "Generate from a prompt" ----------------------------------------------


def _fake_message(stop_reason="end_turn", text='{"tracks": []}'):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=text)],
    )


@pytest.fixture
def fake_anthropic(monkeypatch):
    """Configures a (fake) key and swaps the module-level client factory for
    a mock - no real Anthropic client is ever built."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    fake_client = MagicMock()
    monkeypatch.setattr(playlist_generator, "get_client", lambda: fake_client)
    return fake_client


@pytest.fixture
def no_anthropic_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_generator_status_unavailable_without_key(client, no_anthropic_key):
    assert client.get("/api/spotify/generate/status").json() == {"available": False}


def test_generator_status_available_with_key(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    assert client.get("/api/spotify/generate/status").json() == {"available": True}


def test_generate_unavailable_returns_503_without_calling_claude(client, make_user, no_anthropic_key):
    alice = make_user("alice")
    with patch.object(playlist_generator, "get_client") as factory:
        res = client.post("/api/spotify/generate", headers=alice["headers"], json={"prompt": "rainy drive"})
    assert res.status_code == 503
    factory.assert_not_called()


def test_generate_requires_auth(client, fake_anthropic):
    assert client.post("/api/spotify/generate", json={"prompt": "rainy drive"}).status_code == 401


def test_generate_happy_path_splits_matched_and_unmatched(client, make_user, fake_anthropic):
    alice = make_user("alice")
    fake_anthropic.beta.messages.create.return_value = _fake_message(text=(
        '{"tracks": ['
        '{"title": "Mr. Brightside", "artist": "The Killers"},'
        '{"title": "Nonexistent Song", "artist": "Nobody"},'
        '{"title": "Float On", "artist": "Modest Mouse"}'
        ']}'
    ))

    def fake_search(query, limit=10):
        if "Brightside" in query:
            return [_track("t1", "Mr. Brightside")]
        if "Float On" in query:
            return [_track("t2", "Float On")]
        return []

    with patch("app.routers.spotify.search_tracks", side_effect=fake_search) as mock_search:
        res = client.post("/api/spotify/generate", headers=alice["headers"],
                          json={"prompt": "  rainy late-night drive, 2000s indie "})

    assert res.status_code == 200, res.text
    body = res.json()
    assert [t["id"] for t in body["matched"]] == ["t1", "t2"]
    assert body["unmatched"] == [{"title": "Nonexistent Song", "artist": "Nobody"}]
    # The unmatched one got a strict field-filter search and one looser retry.
    unmatched_queries = [c.args[0] for c in mock_search.call_args_list if "Nonexistent" in c.args[0]]
    assert len(unmatched_queries) == 2

    kwargs = fake_anthropic.beta.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-opus-5"
    assert kwargs["max_tokens"] == 4000
    assert kwargs["betas"] == ["server-side-fallback-2026-07-01"]
    assert kwargs["fallbacks"] == "default"
    assert kwargs["output_config"]["format"]["type"] == "json_schema"
    assert kwargs["output_config"]["effort"] == "low"
    assert kwargs["messages"] == [{"role": "user", "content": "rainy late-night drive, 2000s indie"}]
    assert "rainy" not in kwargs["system"]
    for forbidden in ("temperature", "top_p", "thinking"):
        assert forbidden not in kwargs


def test_generate_caps_suggestion_count(client, make_user, fake_anthropic):
    alice = make_user("alice")
    many = ",".join(f'{{"title": "Song {i}", "artist": "Artist {i}"}}' for i in range(40))
    fake_anthropic.beta.messages.create.return_value = _fake_message(text=f'{{"tracks": [{many}]}}')
    with patch("app.routers.spotify.search_tracks", return_value=[]):
        res = client.post("/api/spotify/generate", headers=alice["headers"], json={"prompt": "anything"})
    assert res.status_code == 200
    assert len(res.json()["unmatched"]) == playlist_generator.MAX_SUGGESTIONS


def test_generate_refusal_returns_422(client, make_user, fake_anthropic):
    alice = make_user("alice")
    fake_anthropic.beta.messages.create.return_value = _fake_message(stop_reason="refusal", text="")
    with patch("app.routers.spotify.search_tracks") as mock_search:
        res = client.post("/api/spotify/generate", headers=alice["headers"], json={"prompt": "something"})
    assert res.status_code == 422
    assert "Couldn't generate a playlist" in res.json()["detail"]
    mock_search.assert_not_called()


def test_generate_max_tokens_is_a_failure(client, make_user, fake_anthropic):
    alice = make_user("alice")
    fake_anthropic.beta.messages.create.return_value = _fake_message(stop_reason="max_tokens", text='{"tra')
    res = client.post("/api/spotify/generate", headers=alice["headers"], json={"prompt": "something"})
    assert res.status_code == 503


def test_generate_unparseable_output_returns_422(client, make_user, fake_anthropic):
    alice = make_user("alice")
    fake_anthropic.beta.messages.create.return_value = _fake_message(text="not json")
    res = client.post("/api/spotify/generate", headers=alice["headers"], json={"prompt": "something"})
    assert res.status_code == 422


@pytest.mark.parametrize("prompt", ["", "   ", "x" * 301])
def test_generate_rejects_malformed_prompt(client, make_user, fake_anthropic, prompt):
    alice = make_user("alice")
    res = client.post("/api/spotify/generate", headers=alice["headers"], json={"prompt": prompt})
    assert res.status_code == 422
    fake_anthropic.beta.messages.create.assert_not_called()


def _status_error(cls, status):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status, request=request, json={"error": {"message": "upstream secret detail"}})
    return cls("upstream secret detail", response=response, body=None)


@pytest.mark.parametrize(
    "exc, expected",
    [
        (_status_error(anthropic.AuthenticationError, 401), 503),
        (_status_error(anthropic.RateLimitError, 429), 429),
        (_status_error(anthropic.InternalServerError, 500), 503),
        (anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com")), 503),
    ],
)
def test_generate_maps_sdk_errors_without_leaking_detail(client, make_user, fake_anthropic, exc, expected):
    alice = make_user("alice")
    fake_anthropic.beta.messages.create.side_effect = exc
    res = client.post("/api/spotify/generate", headers=alice["headers"], json={"prompt": "something"})
    assert res.status_code == expected
    assert "upstream secret detail" not in res.text


def test_generate_is_rate_limited_per_user(client, make_user, fake_anthropic):
    alice = make_user("alice")
    bob = make_user("bob")
    fake_anthropic.beta.messages.create.return_value = _fake_message(
        text='{"tracks": [{"title": "Song", "artist": "Artist"}]}'
    )
    with patch("app.routers.spotify.search_tracks", return_value=[]):
        for _ in range(10):
            res = client.post("/api/spotify/generate", headers=alice["headers"], json={"prompt": "x"})
            assert res.status_code == 200
        res = client.post("/api/spotify/generate", headers=alice["headers"], json={"prompt": "x"})
        assert res.status_code == 429
        # Same IP (the test client), different user - separate budget.
        res = client.post("/api/spotify/generate", headers=bob["headers"], json={"prompt": "x"})
        assert res.status_code == 200
    assert fake_anthropic.beta.messages.create.call_count == 11


def test_parse_suggestions_drops_blank_and_duplicate_entries():
    parsed = playlist_generator._parse_suggestions(
        '{"tracks": [{"title": "A", "artist": "X"}, {"title": "a", "artist": "x"},'
        ' {"title": "", "artist": "Y"}, {"title": "B", "artist": "Z"}]}'
    )
    assert parsed == [SuggestedTrack(title="A", artist="X"), SuggestedTrack(title="B", artist="Z")]
