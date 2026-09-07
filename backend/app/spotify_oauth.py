"""Spotify Authorization Code flow - a per-user linked account, distinct
from spotify_client.py's app-only client-credentials client (which stays
unchanged and keeps powering public catalog search for everyone, logged in
or not).

This flow lets a user grant this app access to *their own* Spotify data
(their playlists). It requires:
  - SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET (same app registration as the
    app-only client)
  - SPOTIFY_REDIRECT_URI, registered exactly in the Spotify developer
    dashboard for that app

Tokens are persisted per-user in the spotify_tokens table (see models.py)
and are never returned in any API response - only a connected/not-connected
boolean ever leaves the server.

Concurrency note: unlike spotify_client.py's shared search client, nothing
here is module-level or shared across calls - _oauth_manager() builds a
fresh SpotifyOAuth + StatusCapturingSession per call, and get_user_playlists
builds a fresh spotipy.Spotify per call, so there's no mutable global state
that concurrent requests from different users could race on. No throttle
or lock is needed on this path for that reason (each user's own calls are
already naturally independent of every other user's).
"""

import logging
import os
from datetime import datetime, timedelta, timezone

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.cache_handler import MemoryCacheHandler

from .models import SpotifyToken
from .schemas import PlaylistResult
from .spotify_retry import SpotifyUnavailableError, StatusCapturingSession, call_with_retry

logger = logging.getLogger(__name__)

SCOPE = "playlist-read-private playlist-read-collaborative"


class SpotifyOAuthNotConfigured(RuntimeError):
    pass


def _oauth_manager() -> tuple[SpotifyOAuth, StatusCapturingSession]:
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    redirect_uri = os.environ.get("SPOTIFY_REDIRECT_URI")
    if not client_id or not client_secret or not redirect_uri:
        raise SpotifyOAuthNotConfigured(
            "SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET / SPOTIFY_REDIRECT_URI are not set. "
            "Copy backend/.env.example to backend/.env and fill them in, and register the "
            "redirect URI in the Spotify developer dashboard."
        )
    # MemoryCacheHandler (not spotipy's default file cache) - token storage
    # is our own spotify_tokens table, one row per app user, not a single
    # file on disk shared by whoever last authorized.
    #
    # StatusCapturingSession: spotipy's OAuth error path (SpotifyOauthError)
    # discards the response status/headers, so call_with_retry reads them
    # back off this session instead to detect a 429 - see spotify_retry.py.
    session = StatusCapturingSession()
    manager = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=SCOPE,
        cache_handler=MemoryCacheHandler(),
        requests_session=session,
    )
    return manager, session


def build_authorize_url(state: str) -> str:
    manager, _ = _oauth_manager()
    return manager.get_authorize_url(state=state)


def exchange_code_for_tokens(code: str) -> dict:
    """Returns spotipy's token-info dict: access_token, refresh_token,
    expires_in/expires_at, scope, token_type."""
    manager, session = _oauth_manager()
    try:
        token_info = call_with_retry(
            manager.get_access_token, code, as_dict=True, check_cache=False,
            log_label="oauth_exchange", session=session,
        )
    except SpotifyUnavailableError:
        logger.warning("spotify.oauth_exchange unavailable_after_retries")
        raise
    except Exception:
        logger.exception("spotify.oauth_exchange failed")
        raise
    logger.info("spotify.oauth_exchange succeeded scope=%r", token_info.get("scope"))
    return token_info


def _token_expiry_from_token_info(token_info: dict) -> datetime:
    if "expires_at" in token_info and token_info["expires_at"]:
        return datetime.fromtimestamp(token_info["expires_at"], tz=timezone.utc).replace(tzinfo=None)
    expires_in = token_info.get("expires_in", 3600)
    return datetime.utcnow() + timedelta(seconds=expires_in)


def token_info_to_fields(token_info: dict) -> dict:
    return {
        "access_token": token_info["access_token"],
        "refresh_token": token_info["refresh_token"],
        "expires_at": _token_expiry_from_token_info(token_info),
        "scope": token_info.get("scope"),
    }


def ensure_fresh_access_token(token: SpotifyToken) -> str:
    """Returns a valid access token for this user, refreshing (and
    persisting the refresh) first if the stored one has expired. The caller
    is responsible for committing the session afterward - this only mutates
    the passed-in ORM object."""
    now = datetime.utcnow()
    if token.expires_at > now + timedelta(seconds=30):
        logger.info("spotify.token_refresh user_id=%s needed=false", token.user_id)
        return token.access_token

    logger.info("spotify.token_refresh user_id=%s needed=true", token.user_id)
    manager, session = _oauth_manager()
    try:
        refreshed = call_with_retry(
            manager.refresh_access_token, token.refresh_token,
            log_label="token_refresh", session=session,
        )
    except SpotifyUnavailableError:
        logger.warning("spotify.token_refresh user_id=%s unavailable_after_retries", token.user_id)
        raise
    except Exception:
        logger.exception("spotify.token_refresh user_id=%s failed", token.user_id)
        raise
    token.access_token = refreshed["access_token"]
    # Spotify doesn't always rotate the refresh token - keep the old one if
    # a new one wasn't issued.
    if refreshed.get("refresh_token"):
        token.refresh_token = refreshed["refresh_token"]
    token.expires_at = _token_expiry_from_token_info(refreshed)
    if refreshed.get("scope"):
        token.scope = refreshed["scope"]
    return token.access_token


def get_user_playlists(access_token: str) -> list[PlaylistResult]:
    """A separate spotipy.Spotify instance from the app-only client in
    spotify_client.py, authorized with this specific user's access token
    rather than app-only client credentials."""
    # Excludes 429 from spotipy/urllib3's own retry-on-status-code list -
    # call_with_retry below owns 429 retry/backoff itself instead, the same
    # reasoning as spotify_client.get_spotify_client().
    sp = spotipy.Spotify(auth=access_token, status_forcelist=(500, 502, 503, 504))
    try:
        results = call_with_retry(sp.current_user_playlists, limit=50, log_label="my_playlists")
    except SpotifyUnavailableError:
        logger.warning("spotify.my_playlists unavailable_after_retries")
        raise
    except Exception:
        logger.exception("spotify.my_playlists failed")
        raise
    items = results.get("items", []) if results else []

    playlists: list[PlaylistResult] = []
    for item in items:
        if not item:
            continue
        images = item.get("images") or []
        playlists.append(
            PlaylistResult(
                id=item["id"],
                name=item["name"],
                url=item["external_urls"]["spotify"],
                image_url=images[0]["url"] if images else None,
                owner=(item.get("owner") or {}).get("display_name", "Unknown"),
                track_count=(item.get("tracks") or {}).get("total", 0),
            )
        )
    logger.info("spotify.my_playlists succeeded results=%d", len(playlists))
    return playlists
