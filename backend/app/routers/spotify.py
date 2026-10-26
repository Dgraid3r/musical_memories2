import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from spotipy.exceptions import SpotifyException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import playlist_generator

from ..auth import create_oauth_state, get_current_user, verify_oauth_state
from ..database import get_db
from ..models import SpotifyToken, User
from ..rate_limit import PLAYLIST_GENERATE_RATE_LIMIT, limiter, user_or_ip_key
from ..schemas import (
    PlaylistCreateInput,
    PlaylistGenerateInput,
    PlaylistGenerateOut,
    PlaylistGeneratorStatusOut,
    PlaylistResult,
    SpotifyConnectOut,
    SpotifyStatusOut,
    SuggestedTrack,
    TrackResult,
)
from ..spotify_client import search_playlists, search_tracks
from ..spotify_oauth import (
    SpotifyOAuthNotConfigured,
    build_authorize_url,
    create_user_playlist,
    ensure_fresh_access_token,
    exchange_code_for_tokens,
    get_user_playlists,
    has_playlist_write_scope,
    token_info_to_fields,
)
from ..spotify_retry import SpotifyUnavailableError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/spotify", tags=["spotify"])

# Exact strings the frontend's create-playlist panel keys off (alongside
# the 409/403 status codes) to show a connect / reconnect prompt.
CONNECT_TO_CREATE_DETAIL = "Connect Spotify to create playlists."
RECONNECT_TO_CREATE_DETAIL = "Reconnect Spotify to create playlists."


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
    return SpotifyStatusOut(
        connected=token is not None,
        can_create_playlists=token is not None and has_playlist_write_scope(token),
    )


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


# --- Create-a-playlist (entry picker's "Create new playlist") ---------------


@router.get("/tracks", response_model=list[TrackResult])
def search_catalog_tracks(q: str = Query(..., min_length=1, max_length=200)):
    """App-only catalog track search - same bar as playlist search above
    (no login needed to search; creating the playlist does)."""
    try:
        return search_tracks(q)
    except SpotifyUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/playlists", response_model=PlaylistResult, status_code=201)
def create_playlist(
    payload: PlaylistCreateInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Creates a private playlist on the caller's linked Spotify account
    with the given tracks, returning it in the same PlaylistResult shape
    search returns - so the entry links it exactly like any other playlist.

    409 = no linked account ("Connect Spotify"); 403 = linked, but the
    token lacks playlist write scope or Spotify rejected it ("Reconnect")."""
    token = db.scalar(select(SpotifyToken).where(SpotifyToken.user_id == current_user.id))
    if token is None:
        raise HTTPException(status_code=409, detail=CONNECT_TO_CREATE_DETAIL)
    if not has_playlist_write_scope(token):
        raise HTTPException(status_code=403, detail=RECONNECT_TO_CREATE_DETAIL)

    try:
        access_token = ensure_fresh_access_token(token)
        db.commit()
        return create_user_playlist(access_token, payload.name, payload.track_uris)
    except SpotifyOAuthNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SpotifyUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SpotifyException as exc:
        if exc.http_status in (401, 403):
            raise HTTPException(status_code=403, detail=RECONNECT_TO_CREATE_DETAIL) from exc
        raise HTTPException(
            status_code=502, detail="Spotify couldn't create the playlist. Try again shortly."
        ) from exc


# --- "Generate from a prompt" (dormant until ANTHROPIC_API_KEY is set) --------


@router.get("/generate/status", response_model=PlaylistGeneratorStatusOut)
def generator_status():
    """The frontend renders the "Generate from a prompt" button only when
    this is true. Only a boolean - never anything about the key itself."""
    return PlaylistGeneratorStatusOut(available=playlist_generator.is_available())


def _match_suggestion(suggestion: SuggestedTrack) -> TrackResult | None:
    title = suggestion.title.replace('"', "")
    artist = suggestion.artist.replace('"', "")
    hits = search_tracks(f"track:{title} artist:{artist}", limit=1)
    if not hits:
        # Field filters are strict about exact wording ("feat." credits,
        # punctuation) - one looser free-text try before giving up.
        hits = search_tracks(f"{title} {artist}", limit=1)
    return hits[0] if hits else None


@router.post("/generate", response_model=PlaylistGenerateOut)
@limiter.limit(PLAYLIST_GENERATE_RATE_LIMIT, key_func=user_or_ip_key)
def generate_playlist(
    request: Request,
    payload: PlaylistGenerateInput,
    current_user: User = Depends(get_current_user),
):
    """Claude suggests songs for the prompt; each is resolved against
    Spotify's catalog. Matched tracks pre-fill the create-playlist draft,
    unmatched suggestions are listed. Creating the playlist itself still
    goes through POST /playlists above."""
    if not playlist_generator.is_available():
        raise HTTPException(status_code=503, detail="Playlist generation isn't configured on this server.")

    try:
        suggestions = playlist_generator.suggest_tracks(payload.prompt)
    except playlist_generator.GenerationRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except playlist_generator.GenerationRateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except playlist_generator.GenerationUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    matched: list[TrackResult] = []
    unmatched: list[SuggestedTrack] = []
    seen_ids: set[str] = set()
    try:
        for suggestion in suggestions:
            track = _match_suggestion(suggestion)
            if track is None:
                unmatched.append(suggestion)
            elif track.id not in seen_ids:
                seen_ids.add(track.id)
                matched.append(track)
    except SpotifyUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    logger.info(
        "playlist_generate user_id=%s matched=%d unmatched=%d",
        current_user.id, len(matched), len(unmatched),
    )
    return PlaylistGenerateOut(matched=matched, unmatched=unmatched)
