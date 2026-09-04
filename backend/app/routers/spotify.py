import os

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import create_oauth_state, get_current_user, verify_oauth_state
from ..database import get_db
from ..models import SpotifyToken, User
from ..schemas import PlaylistResult, SpotifyConnectOut, SpotifyStatusOut
from ..spotify_client import search_playlists
from ..spotify_oauth import (
    SpotifyOAuthNotConfigured,
    build_authorize_url,
    ensure_fresh_access_token,
    exchange_code_for_tokens,
    get_user_playlists,
    token_info_to_fields,
)
from ..spotify_retry import SpotifyUnavailableError

router = APIRouter(prefix="/api/spotify", tags=["spotify"])


@router.get("/playlists", response_model=list[PlaylistResult])
def search(q: str = Query(..., min_length=1)):
    try:
        return search_playlists(q)
    except SpotifyUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# --- Account linking (Authorization Code flow) ------------------------------
#
# Distinct from the app-only client above: these endpoints let a logged-in
# local user grant this app access to *their own* Spotify account.


@router.get("/status", response_model=SpotifyStatusOut)
def connection_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    token = db.scalar(select(SpotifyToken).where(SpotifyToken.user_id == current_user.id))
    return SpotifyStatusOut(connected=token is not None)


@router.get("/connect", response_model=SpotifyConnectOut)
def connect(current_user: User = Depends(get_current_user)):
    """Requires the caller's local JWT (via the Authorization header), which
    a plain browser redirect can't carry - so this returns the authorize URL
    as JSON, and the frontend navigates the browser there itself
    (window.location = authorize_url) rather than us issuing an HTTP
    redirect directly. `state` is a signed, short-lived token identifying
    this user, since the callback below is a bare browser navigation with
    no auth header of its own."""
    try:
        state = create_oauth_state(current_user.id)
        return SpotifyConnectOut(authorize_url=build_authorize_url(state))
    except SpotifyOAuthNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/callback")
def callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Spotify redirects the user's browser here after they approve (or
    deny) access. No auth dependency - the browser can't attach our JWT to
    a redirect Spotify initiates - so the user is identified entirely from
    `state` (see create_oauth_state)."""
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:5173")

    if error is not None:
        return RedirectResponse(f"{frontend_url}/?spotify=denied")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    user_id = verify_oauth_state(state)
    if user_id is None:
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="Unknown user")

    try:
        token_info = exchange_code_for_tokens(code)
    except SpotifyOAuthNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SpotifyUnavailableError:
        # This leg of the flow is a bare browser redirect from Spotify, not
        # an API caller expecting JSON - send it back the same way a denied
        # authorization already is, with a distinct flag the frontend can
        # show a clean message for.
        return RedirectResponse(f"{frontend_url}/?spotify=unavailable")

    fields = token_info_to_fields(token_info)
    existing = db.scalar(select(SpotifyToken).where(SpotifyToken.user_id == user_id))
    if existing is None:
        db.add(SpotifyToken(user_id=user_id, **fields))
    else:
        for key, value in fields.items():
            setattr(existing, key, value)
    db.commit()

    return RedirectResponse(f"{frontend_url}/?spotify=connected")


@router.get("/me/playlists", response_model=list[PlaylistResult])
def my_playlists(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    token = db.scalar(select(SpotifyToken).where(SpotifyToken.user_id == current_user.id))
    if token is None:
        raise HTTPException(status_code=404, detail="Spotify account not connected")

    try:
        access_token = ensure_fresh_access_token(token)
        db.commit()
        return get_user_playlists(access_token)
    except SpotifyOAuthNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SpotifyUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
