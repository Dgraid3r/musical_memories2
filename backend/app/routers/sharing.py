import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import JournalEntry, WorkspaceRecap
from ..schemas import SharedEntryOut, WorkspaceRecapOut
from ..storage import get_storage
from .workspaces import _compute_recap_stats

logger = logging.getLogger(__name__)

# Deliberately its own router/prefix, not nested under
# /api/workspaces/{workspace_id}/entries like the rest of entries.py - a
# shared link is looked up purely by its own unguessable token, with no
# workspace or entry id in the URL at all, so there is nothing here that
# could let a viewer browse to anything else in the workspace. See
# routers/entries.py's enable_entry_sharing/disable_entry_sharing for how
# a token is created/cleared (primary author only) and models.JournalEntry.
# share_token's comment for the full design reasoning.
router = APIRouter(prefix="/api/shared", tags=["sharing"])


def _get_shared_entry_or_404(token: str, db: Session) -> JournalEntry:
    """The token is an unguessable 32-byte random value (secrets.
    token_urlsafe), generated only by the entry's primary author - the
    same non-disclosure 404 every other token-lookup endpoint in this
    app already gives (invites, password reset, email verification):
    never found, expired/revoked-equivalent, and disabled-and-reused-
    afterward all look identical to the caller."""
    entry = db.scalar(select(JournalEntry).where(JournalEntry.share_token == token))
    if entry is None:
        raise HTTPException(status_code=404, detail="Shared link not found")
    return entry


@router.get("/{token}", response_model=SharedEntryOut)
def get_shared_entry(token: str, db: Session = Depends(get_db)):
    """No auth required, and deliberately not built on the authenticated
    entry-visibility logic in entries.py (_can_view/_apply_visibility) -
    a clean, low-blast-radius addition rather than a special case bolted
    onto that shared machinery. Returns only this one entry's own
    content (see schemas.SharedEntryOut) - independent of both
    Workspace.visibility and JournalEntry.is_public, since the whole
    point of this feature is sharing one memory without exposing
    anything about the workspace it lives in."""
    return _get_shared_entry_or_404(token, db)


@router.get("/{token}/images/{image_id}")
def get_shared_entry_image(token: str, image_id: int, db: Session = Depends(get_db)):
    """Scoped to *this* token's own entry only - a valid token for one
    shared entry can never be used to fetch another entry's (or another
    workspace's) image by guessing image ids; an image_id that isn't one
    of this entry's own gets the same 404 as a wrong token entirely."""
    entry = _get_shared_entry_or_404(token, db)
    image = next((img for img in entry.images if img.id == image_id), None)
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    return get_storage().serve_response(image.filename)


# --- Yearly recap sharing -------------------------------------------------
#
# A second, separate router in this same file (same reasoning as entries.py
# splitting router/image_router: one file owning every "here's what an
# unauthenticated holder of a valid token gets to see" surface) rather than
# folding a different prefix into the router above.
recap_router = APIRouter(prefix="/api/shared-recap", tags=["sharing"])


@recap_router.get("/{token}", response_model=WorkspaceRecapOut)
def get_shared_recap(token: str, db: Session = Depends(get_db)):
    """No auth required. The token is generated only by the workspace
    owner (see routers/workspaces.py's enable_workspace_recap_sharing) -
    same non-disclosure 404 as get_shared_entry above for an invalid,
    never-shared, or since-revoked token. Reuses _compute_recap_stats
    (the same aggregation the authenticated in-app recap endpoint calls)
    so the public view can never diverge from - or expose more than -
    what's already documented as safe to disclose in schemas.
    WorkspaceRecapOut: aggregate stats and highlighted-entry glimpses
    only, never entry text, photos, or anything about a member beyond
    the same username already shown next to their entries/comments
    everywhere else in this app."""
    recap = db.scalar(select(WorkspaceRecap).where(WorkspaceRecap.share_token == token))
    if recap is None:
        raise HTTPException(status_code=404, detail="Shared recap not found")
    return _compute_recap_stats(recap.workspace_id, recap.year, db)
