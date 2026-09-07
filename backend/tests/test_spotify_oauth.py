from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from spotipy.oauth2 import SpotifyOauthError

from app import auth
from app.schemas import PlaylistResult


# --- /api/spotify/connect ----------------------------------------------------


def test_connect_requires_auth(client):
    res = client.get("/api/spotify/connect")
    assert res.status_code == 401


def test_connect_returns_authorize_url(client, make_user):
    alice = make_user("alice")
    with patch("app.routers.spotify.build_authorize_url", return_value="https://accounts.spotify.com/authorize?x=1"):
        res = client.get("/api/spotify/connect", headers=alice["headers"])
    assert res.status_code == 200
    assert res.json()["authorize_url"] == "https://accounts.spotify.com/authorize?x=1"


def test_connect_state_encodes_calling_user(client, make_user):
    alice = make_user("alice")
    captured = {}

    def fake_build_authorize_url(state):
        captured["state"] = state
        return "https://accounts.spotify.com/authorize"

    with patch("app.routers.spotify.build_authorize_url", side_effect=fake_build_authorize_url):
        res = client.get("/api/spotify/connect", headers=alice["headers"])
    assert res.status_code == 200
    assert auth.verify_oauth_state(captured["state"]) == alice["id"]


# --- /api/spotify/callback ---------------------------------------------------


def _fake_token_info(access="access-1", refresh="refresh-1", expires_in=3600):
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": expires_in,
        "scope": "playlist-read-private",
        "token_type": "Bearer",
    }


def test_callback_missing_code_or_state_rejected(client):
    res = client.get("/api/spotify/callback")
    assert res.status_code == 400

    res = client.get("/api/spotify/callback?code=abc")
    assert res.status_code == 400


def test_callback_invalid_state_rejected(client):
    res = client.get("/api/spotify/callback?code=abc&state=not-a-real-token", follow_redirects=False)
    assert res.status_code == 400


def test_callback_expired_state_rejected(client, make_user):
    alice = make_user("alice")
    with patch("app.auth.datetime") as mock_dt:
        mock_dt.now.return_value = datetime.now(auth.timezone.utc) - timedelta(minutes=20)
        state = auth.create_oauth_state(alice["id"])

    res = client.get(f"/api/spotify/callback?code=abc&state={state}", follow_redirects=False)
    assert res.status_code == 400


def test_callback_rejects_state_from_a_different_kind_of_token(client, make_user):
    alice = make_user("alice")
    # A regular access token is a validly-signed JWT too, but was never
    # meant to authorize the oauth callback - the "purpose" claim must gate it.
    access_token = auth.create_access_token(alice["id"])

    res = client.get(f"/api/spotify/callback?code=abc&state={access_token}", follow_redirects=False)
    assert res.status_code == 400


def test_callback_success_stores_tokens_and_redirects(client, make_user, db_session):
    from app.models import SpotifyToken

    alice = make_user("alice")
    state = auth.create_oauth_state(alice["id"])

    with patch("app.routers.spotify.exchange_code_for_tokens", return_value=_fake_token_info()):
        res = client.get(f"/api/spotify/callback?code=abc123&state={state}", follow_redirects=False)

    assert res.status_code in (302, 307)
    assert "spotify=connected" in res.headers["location"]

    token = db_session.query(SpotifyToken).filter_by(user_id=alice["id"]).one()
    assert token.access_token == "access-1"
    assert token.refresh_token == "refresh-1"


def test_callback_encrypts_tokens_at_rest(client, make_user, db_session):
    """The ORM round-trip (as in the test above) would pass even if
    EncryptedString were accidentally a no-op, since it decrypts on the way
    back out too - so this reads the raw column value with a plain SQL
    query, bypassing the ORM's TypeDecorator entirely, to prove the bytes
    actually stored in Postgres are not the plaintext token."""
    from sqlalchemy import text

    alice = make_user("alice")
    state = auth.create_oauth_state(alice["id"])

    with patch("app.routers.spotify.exchange_code_for_tokens", return_value=_fake_token_info(access="raw-secret-access")):
        client.get(f"/api/spotify/callback?code=abc123&state={state}", follow_redirects=False)

    raw_access_token = db_session.execute(
        text("SELECT access_token FROM spotify_tokens WHERE user_id = :user_id"), {"user_id": alice["id"]}
    ).scalar_one()

    assert raw_access_token != "raw-secret-access"
    assert "raw-secret-access" not in raw_access_token


def test_callback_upserts_existing_token(client, make_user, db_session):
    from app.models import SpotifyToken

    alice = make_user("alice")

    state1 = auth.create_oauth_state(alice["id"])
    with patch("app.routers.spotify.exchange_code_for_tokens", return_value=_fake_token_info(access="access-1")):
        client.get(f"/api/spotify/callback?code=abc&state={state1}", follow_redirects=False)

    state2 = auth.create_oauth_state(alice["id"])
    with patch("app.routers.spotify.exchange_code_for_tokens", return_value=_fake_token_info(access="access-2")):
        client.get(f"/api/spotify/callback?code=def&state={state2}", follow_redirects=False)

    tokens = db_session.query(SpotifyToken).filter_by(user_id=alice["id"]).all()
    assert len(tokens) == 1
    assert tokens[0].access_token == "access-2"


def test_callback_rate_limit_exhausted_redirects_with_unavailable_flag(client, make_user, db_session):
    from app.models import SpotifyToken
    from app.spotify_retry import SpotifyUnavailableError

    alice = make_user("alice")
    state = auth.create_oauth_state(alice["id"])

    with patch(
        "app.routers.spotify.exchange_code_for_tokens",
        side_effect=SpotifyUnavailableError("Spotify is temporarily unavailable, try again shortly."),
    ):
        res = client.get(f"/api/spotify/callback?code=abc123&state={state}", follow_redirects=False)

    assert res.status_code in (302, 307)
    assert "spotify=unavailable" in res.headers["location"]
    assert db_session.query(SpotifyToken).filter_by(user_id=alice["id"]).first() is None


def test_callback_denied_redirects_without_storing_token(client, make_user, db_session):
    from app.models import SpotifyToken

    alice = make_user("alice")
    res = client.get("/api/spotify/callback?error=access_denied", follow_redirects=False)
    assert res.status_code in (302, 307)
    assert "spotify=denied" in res.headers["location"]
    assert db_session.query(SpotifyToken).filter_by(user_id=alice["id"]).first() is None


def test_callback_response_never_contains_tokens(client, make_user):
    alice = make_user("alice")
    state = auth.create_oauth_state(alice["id"])
    with patch("app.routers.spotify.exchange_code_for_tokens", return_value=_fake_token_info(access="super-secret")):
        res = client.get(f"/api/spotify/callback?code=abc&state={state}", follow_redirects=False)
    assert "super-secret" not in res.text


# --- /api/spotify/status ------------------------------------------------------


def test_status_requires_auth(client):
    res = client.get("/api/spotify/status")
    assert res.status_code == 401


def test_status_reports_not_connected(client, make_user):
    alice = make_user("alice")
    res = client.get("/api/spotify/status", headers=alice["headers"])
    assert res.status_code == 200
    assert res.json() == {"connected": False}


def test_status_reports_connected(client, make_user, db_session):
    from app.models import SpotifyToken

    alice = make_user("alice")
    db_session.add(
        SpotifyToken(
            user_id=alice["id"],
            access_token="a",
            refresh_token="r",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
    )
    db_session.commit()

    res = client.get("/api/spotify/status", headers=alice["headers"])
    assert res.status_code == 200
    assert res.json() == {"connected": True}


def test_status_response_never_contains_tokens(client, make_user, db_session):
    from app.models import SpotifyToken

    alice = make_user("alice")
    db_session.add(
        SpotifyToken(
            user_id=alice["id"],
            access_token="super-secret-access",
            refresh_token="super-secret-refresh",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
    )
    db_session.commit()

    res = client.get("/api/spotify/status", headers=alice["headers"])
    assert "super-secret" not in res.text


# --- /api/spotify/me/playlists ------------------------------------------------


def test_my_playlists_requires_auth(client):
    res = client.get("/api/spotify/me/playlists")
    assert res.status_code == 401


def test_my_playlists_requires_connection(client, make_user):
    alice = make_user("alice")
    res = client.get("/api/spotify/me/playlists", headers=alice["headers"])
    assert res.status_code == 404


def test_my_playlists_returns_results_for_connected_user(client, make_user, db_session):
    from app.models import SpotifyToken

    alice = make_user("alice")
    db_session.add(
        SpotifyToken(
            user_id=alice["id"],
            access_token="valid-access",
            refresh_token="r",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
    )
    db_session.commit()

    fake_playlists = [
        PlaylistResult(id="p1", name="My Playlist", url="https://open.spotify.com/playlist/p1",
                        image_url=None, owner="alice", track_count=5)
    ]
    with patch("app.routers.spotify.get_user_playlists", return_value=fake_playlists) as mock_get:
        res = client.get("/api/spotify/me/playlists", headers=alice["headers"])

    assert res.status_code == 200
    assert res.json()[0]["id"] == "p1"
    mock_get.assert_called_once_with("valid-access")


def test_my_playlists_refreshes_expired_token(client, make_user, db_session):
    from app.models import SpotifyToken

    alice = make_user("alice")
    db_session.add(
        SpotifyToken(
            user_id=alice["id"],
            access_token="stale-access",
            refresh_token="my-refresh-token",
            expires_at=datetime.utcnow() - timedelta(minutes=5),
        )
    )
    db_session.commit()

    refreshed_info = {"access_token": "fresh-access", "expires_in": 3600, "scope": "playlist-read-private"}
    with (
        patch("app.spotify_oauth._oauth_manager") as mock_manager_factory,
        patch("app.routers.spotify.get_user_playlists", return_value=[]) as mock_get,
    ):
        mock_manager, mock_session = MagicMock(), MagicMock()
        mock_manager.refresh_access_token.return_value = refreshed_info
        mock_manager_factory.return_value = (mock_manager, mock_session)
        res = client.get("/api/spotify/me/playlists", headers=alice["headers"])

    assert res.status_code == 200
    mock_get.assert_called_once_with("fresh-access")

    token = db_session.query(SpotifyToken).filter_by(user_id=alice["id"]).one()
    assert token.access_token == "fresh-access"
    assert token.refresh_token == "my-refresh-token"  # unchanged: refresh response didn't rotate it


def test_my_playlists_does_not_refresh_unexpired_token(client, make_user, db_session):
    from app.models import SpotifyToken

    alice = make_user("alice")
    db_session.add(
        SpotifyToken(
            user_id=alice["id"],
            access_token="still-good-access",
            refresh_token="r",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
    )
    db_session.commit()

    with (
        patch("app.spotify_oauth._oauth_manager") as mock_manager_factory,
        patch("app.routers.spotify.get_user_playlists", return_value=[]) as mock_get,
    ):
        mock_manager, mock_session = MagicMock(), MagicMock()
        mock_manager_factory.return_value = (mock_manager, mock_session)
        res = client.get("/api/spotify/me/playlists", headers=alice["headers"])

    assert res.status_code == 200
    mock_manager.refresh_access_token.assert_not_called()
    mock_get.assert_called_once_with("still-good-access")


def test_my_playlists_never_leaks_tokens_in_response(client, make_user, db_session):
    from app.models import SpotifyToken

    alice = make_user("alice")
    db_session.add(
        SpotifyToken(
            user_id=alice["id"],
            access_token="super-secret-access",
            refresh_token="r",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
    )
    db_session.commit()

    with patch("app.routers.spotify.get_user_playlists", return_value=[]):
        res = client.get("/api/spotify/me/playlists", headers=alice["headers"])

    assert "super-secret" not in res.text


# --- 429 handling: per-user OAuth calls and token refresh -------------------


def test_my_playlists_retries_after_a_429_and_succeeds(client, make_user, db_session):
    from spotipy.exceptions import SpotifyException

    from app.models import SpotifyToken

    alice = make_user("alice")
    db_session.add(
        SpotifyToken(
            user_id=alice["id"],
            access_token="valid-access",
            refresh_token="r",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
    )
    db_session.commit()

    fake_sp = MagicMock()
    fake_sp.current_user_playlists.side_effect = [
        SpotifyException(429, -1, "rate limited", headers={"Retry-After": "1"}),
        {"items": []},
    ]

    with (
        patch("app.spotify_oauth.spotipy.Spotify", return_value=fake_sp),
        patch("app.spotify_retry.time.sleep"),
    ):
        res = client.get("/api/spotify/me/playlists", headers=alice["headers"])

    assert res.status_code == 200
    assert fake_sp.current_user_playlists.call_count == 2


def test_my_playlists_rate_limit_exhausted_returns_clean_503(client, make_user, db_session):
    from spotipy.exceptions import SpotifyException

    from app.models import SpotifyToken

    alice = make_user("alice")
    db_session.add(
        SpotifyToken(
            user_id=alice["id"],
            access_token="valid-access",
            refresh_token="r",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
    )
    db_session.commit()

    fake_sp = MagicMock()
    fake_sp.current_user_playlists.side_effect = SpotifyException(429, -1, "rate limited", headers={})

    with (
        patch("app.spotify_oauth.spotipy.Spotify", return_value=fake_sp),
        patch("app.spotify_retry.time.sleep"),
    ):
        res = client.get("/api/spotify/me/playlists", headers=alice["headers"])

    assert res.status_code == 503
    assert res.json() == {"detail": "Spotify is temporarily unavailable, try again shortly."}


def test_token_refresh_retries_after_a_429_and_succeeds(client, make_user, db_session):
    from app.models import SpotifyToken

    alice = make_user("alice")
    db_session.add(
        SpotifyToken(
            user_id=alice["id"],
            access_token="stale-access",
            refresh_token="my-refresh-token",
            expires_at=datetime.utcnow() - timedelta(minutes=5),
        )
    )
    db_session.commit()

    with (
        patch("app.spotify_oauth._oauth_manager") as mock_manager_factory,
        patch("app.routers.spotify.get_user_playlists", return_value=[]) as mock_get,
        patch("app.spotify_retry.time.sleep"),
    ):
        mock_manager, mock_session = MagicMock(), MagicMock()
        mock_session.last_status = 429
        mock_session.last_headers = {"Retry-After": "1"}
        mock_manager.refresh_access_token.side_effect = [
            SpotifyOauthError("rate limited"),
            {"access_token": "fresh-access", "expires_in": 3600, "scope": "playlist-read-private"},
        ]
        mock_manager_factory.return_value = (mock_manager, mock_session)
        res = client.get("/api/spotify/me/playlists", headers=alice["headers"])

    assert res.status_code == 200
    mock_get.assert_called_once_with("fresh-access")
    assert mock_manager.refresh_access_token.call_count == 2
