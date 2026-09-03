import logging
import os
from functools import lru_cache

import spotipy
from cachetools import TTLCache
from spotipy.oauth2 import SpotifyClientCredentials

from .schemas import PlaylistResult

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
    return spotipy.Spotify(auth_manager=auth_manager)


def search_playlists(query: str, limit: int = 10) -> list[PlaylistResult]:
    cache_key = (query, limit)
    cached = _search_cache.get(cache_key)
    if cached is not None:
        logger.info("spotify.search cache=hit query=%r limit=%d results=%d", query, limit, len(cached))
        return cached

    try:
        sp = get_spotify_client()
        results = sp.search(q=query, type="playlist", limit=limit)
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
