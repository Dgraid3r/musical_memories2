import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_current_user_optional
from ..database import get_db
from ..models import Comment, User
from ..schemas import CommentCreate, CommentOut, CommentUpdate
from .entries import _can_view, _get_entry_in_workspace_or_404, _is_owner, _visible_or_404
from .workspaces import require_workspace_read_access, require_workspace_write_access

logger = logging.getLogger(__name__)

router = APIRouter(tags=["comments"])


def _visible_entry_or_404(entry_id: int, workspace_id: int, db: Session, user: User | None):
    """Comment visibility is exactly entry visibility - the same public /
    own-private / co-authored-private rule (now also workspace-scoped, and
    public-workspace-readable-by-anyone) that
    GET /api/workspaces/{workspace_id}/entries uses, not a separate concept.
    Delegates straight to entries.py's own scope-then-visibility helpers
    (the same ones list_entries and get_entry use) instead of re-deriving
    the same checks here, so there is exactly one visibility implementation,
    not two that could drift."""
    entry = _get_entry_in_workspace_or_404(entry_id, workspace_id, db)
    return _visible_or_404(entry, user, db)


def _visible_comment_or_404(comment_id: int, db: Session, user: User | None) -> Comment:
    """No workspace_id in this URL (see /api/comments/{comment_id} below) -
    _can_view derives the right workspace entirely from the comment's own
    entry, so this is correct regardless of which workspace the comment
    actually belongs to."""
    comment = db.get(Comment, comment_id)
    if comment is None or not _can_view(comment.entry, user, db):
        raise HTTPException(status_code=404, detail="Comment not found")
    return comment


@router.get("/api/workspaces/{workspace_id}/entries/{entry_id}/comments", response_model=list[CommentOut])
def list_comments(
    workspace_id: int,
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """The full thread for an entry, as a nested tree: top-level comments in
    chronological order, each carrying its replies (also chronological,
    arbitrarily deep) inline. Readable with no auth token at all when the
    workspace is public, same as the entry itself."""
    require_workspace_read_access(workspace_id, db, current_user)
    entry = _visible_entry_or_404(entry_id, workspace_id, db, current_user)
    stmt = (
        select(Comment)
        .where(Comment.entry_id == entry.id, Comment.parent_comment_id.is_(None))
        .order_by(Comment.created_at)
    )
    return db.scalars(stmt).unique().all()


@router.post("/api/workspaces/{workspace_id}/entries/{entry_id}/comments", response_model=CommentOut, status_code=201)
def create_comment(
    workspace_id: int,
    entry_id: int,
    payload: CommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Commenting is a write action: requires an owner or member role - a
    subscriber (or an anonymous visitor to a public workspace) can read
    every comment but never post one."""
    require_workspace_write_access(workspace_id, db, current_user)
    entry = _visible_entry_or_404(entry_id, workspace_id, db, current_user)

    parent_id = None
    if payload.parent_comment_id is not None:
        parent = db.get(Comment, payload.parent_comment_id)
        if parent is None or parent.entry_id != entry.id:
            raise HTTPException(status_code=422, detail="parent_comment_id does not belong to this entry")
        parent_id = parent.id

    comment = Comment(
        entry_id=entry.id,
        author_id=current_user.id,
        parent_comment_id=parent_id,
        body=payload.body,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@router.patch("/api/comments/{comment_id}", response_model=CommentOut)
def update_comment(
    comment_id: int,
    payload: CommentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Editing requires the caller to *currently* hold write access
    (owner or member role) in the comment's workspace, the same bar
    create_comment already requires to post one in the first place - not
    just having been the author at some point in the past. Without this,
    a member demoted to subscriber (or removed from the workspace
    entirely, if the workspace happens to still be readable to them some
    other way) would keep standing rewrite power over everything they
    ever posted, which contradicts subscriber being a read-only role.
    Deleting your own comment is deliberately NOT held to this same bar -
    see delete_comment below for why that's a different judgment call."""
    comment = _visible_comment_or_404(comment_id, db, current_user)
    if comment.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the comment's author can edit it")
    require_workspace_write_access(comment.entry.workspace_id, db, current_user)

    comment.body = payload.body
    comment.edited_at = datetime.utcnow()
    db.commit()
    db.refresh(comment)
    return comment


@router.delete("/api/comments/{comment_id}", status_code=204)
def delete_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """A comment's own author can always delete it - deliberately NOT
    gated on still holding write access to the workspace, unlike editing
    (see update_comment above): retracting your own words isn't a write
    privilege in the same sense actively rewriting them is, so a member
    later demoted to subscriber can still take down something they
    posted while they had write access, even though they could no longer
    edit it. The entry's primary author can additionally delete *any*
    comment on their own entry (moderation) - the same extra power the
    primary author already has over visibility, co-authors, and entry
    deletion. Co-authors get none of that: they can comment like anyone
    else with view access, but they don't get moderation power just
    because they can edit the entry's text."""
    comment = _visible_comment_or_404(comment_id, db, current_user)

    is_author = comment.author_id == current_user.id
    is_entry_primary_author = _is_owner(comment.entry, current_user)
    if not (is_author or is_entry_primary_author):
        raise HTTPException(status_code=403, detail="You do not have permission to delete this comment")

    db.delete(comment)
    db.commit()
