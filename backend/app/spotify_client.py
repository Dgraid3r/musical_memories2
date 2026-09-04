import logging
import os
import threading
import time
from functools import lru_cache

import spotipy
from cachetools import TTLCache
from spotipy.oauth2 import SpotifyClientCredentials

from .schemas import PlaylistResult
from .spotify_retry import SpotifyUnavailableError, call_with_retry

logger = logging.getLogger(__name__)

# This is a single-process local app, not a distributed service - an
# in-memory TTL cache is the right tool here, not Redis or any other
# external infra. Keyed by (query, limit) so a repeated search for the same
# text within the window skips the network call to Spotify entirely.
# 10 minutes: search results for a given query string don't need to be any
# fresher than that for a personal journal app, and it's long enough to
# absorb the retyping/backspacing a user does while composing a query.
SEARCH_CACHE_TTL_SECONDS = 600
SEARCH_CACHE_MAXSIZE = 256

_search_cache: TTLCache = TTLCache(maxsize=SEARCH_CACHE_MAXSIZE, ttl=SEARCH_CACHE_TTL_SECONDS)


def clear_search_cache() -> None:
    """Exposed mainly for tests, which must not let one test's cached
    result leak into the next test's assertions about a fresh call."""
    _search_cache.clear()


# --- Outbound-call throttle -------------------------------------------
#
# This client is shared across every user's searches (unlike the per-user
# OAuth client in spotify_oauth.py), so a burst of near-simultaneous
# searches from different users hits Spotify's rate limit as one shared
# budget. A simple minimum-interval throttle - stdlib only, no new
# dependency - smooths that out before it ever becomes a 429, rather than
# only reacting to one after the fact via call_with_retry.
SEARCH_MIN_INTERVAL_SECONDS = 0.1  # generous headroom (10 req/s ceiling), just enough to prevent bursts

_throttle_lock = threading.Lock()
_last_call_monotonic: float | None = None


def reset_throttle() -> None:
    """Test-only: same reasoning as clear_search_cache - one test's recent
    call shouldn't make a later test's first call wait."""
    global _last_call_monotonic
    with _throttle_lock:
        _last_call_monotonic = None


def _throttle() -> None:
    global _last_call_monotonic
    with _throttle_lock:
        now = time.monotonic()
        wait = 0.0
        if _last_call_monotonic is not None:
            wait = _last_call_monotonic + SEARCH_MIN_INTERVAL_SECONDS - now
        if wait > 0:
            time.sleep(wait)
        _last_call_monotonic = time.monotonic()


@lru_cache
def get_spotify_client() -> spotipy.Spotify:
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError(
            "SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET are not set. "
            "Copy backend/.env.example to backend/.env and fill them in."
        )
    auth_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
    # Excludes 429 from spotipy/urllib3's own retry-on-status-code list -
    # call_with_retry below owns 429 retry/backoff itself instead (see
    # spotify_retry.py for why), so this client should raise immediately
    # on a 429 rather than have urllib3 silently sleep on it first.
    return spotipy.Spotify(auth_manager=auth_manager, status_forcelist=(500, 502, 503, 504))


def search_playlists(query: str, limit: int = 10) -> list[PlaylistResult]:
    cache_key = (query, limit)
    cached = _search_cache.get(cache_key)
    if cached is not None:
        logger.info("spotify.search cache=hit query=%r limit=%d results=%d", query, limit, len(cached))
        return cached

    _throttle()
    try:
        sp = get_spotify_client()
        results = call_with_retry(sp.search, q=query, type="playlist", limit=limit, log_label="search")
    except SpotifyUnavailableError:
        logger.warning("spotify.search cache=miss query=%r limit=%d unavailable_after_retries", query, limit)
        raise
    except Exception:
        logger.exception("spotify.search cache=miss query=%r limit=%d failed", query, limit)
        raise
    items = results.get("playlists", {}).get("items", []) if results else []

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

    logger.info("spotify.search cache=miss query=%r limit=%d results=%d", query, limit, len(playlists))
    _search_cache[cache_key] = playlists
    return playlists
