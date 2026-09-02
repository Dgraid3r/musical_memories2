import os
from functools import lru_cache

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

from .schemas import PlaylistResult


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
    sp = get_spotify_client()
    results = sp.search(q=query, type="playlist", limit=limit)
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
    return playlists
