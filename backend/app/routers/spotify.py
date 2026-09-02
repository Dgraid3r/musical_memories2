from fastapi import APIRouter, HTTPException, Query

from ..schemas import PlaylistResult
from ..spotify_client import search_playlists

router = APIRouter(prefix="/api/spotify", tags=["spotify"])


@router.get("/playlists", response_model=list[PlaylistResult])
def search(q: str = Query(..., min_length=1)):
    try:
        return search_playlists(q)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
