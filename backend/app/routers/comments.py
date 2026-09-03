from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_current_user_optional
from ..database import get_db
from ..models import Comment, JournalEntry, User
from ..schemas import CommentCreate, CommentOut, CommentUpdate
from .entries import _can_view, _is_owner, _visible_or_404

router = APIRouter(tags=["comments"])


def _visible_entry_or_404(entry_id: int, db: Session, user: User | None) -> JournalEntry:
    """Comment visibility is exactly entry visibility - the same public /
    own-private / co-authored-private rule GET /api/entries uses, not a
    separate concept. Delegates straight to entries.py's own
    _visible_or_404/_can_view (the same helpers list_entries and
    get_entry use) instead of re-deriving the same check here, so there is
    exactly one visibility implementation, not two that could drift."""
    return _visible_or_404(db.get(JournalEntry, entry_id), user)


def _visible_comment_or_404(comment_id: int, db: Session, user: User | None) -> Comment:
    comment = db.get(Comment, comment_id)
    if comment is None or not _can_view(comment.entry, user):
        raise HTTPException(status_code=404, detail="Comment not found")
    return comment


@router.get("/api/entries/{entry_id}/comments", response_model=list[CommentOut])
def list_comments(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """The full thread for an entry, as a nested tree: top-level comments in
    chronological order, each carrying its replies (also chronological,
    arbitrarily deep) inline."""
    entry = _visible_entry_or_404(entry_id, db, current_user)
    stmt = (
        select(Comment)
        .where(Comment.entry_id == entry.id, Comment.parent_comment_id.is_(None))
        .order_by(Comment.created_at)
    )
    return db.scalars(stmt).unique().all()


@router.post("/api/entries/{entry_id}/comments", response_model=CommentOut, status_code=201)
def create_comment(
    entry_id: int,
    payload: CommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Anyone who can view the entry can comment on it - same rule as
    viewing its comments (see _visible_entry_or_404)."""
    entry = _visible_entry_or_404(entry_id, db, current_user)

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
    comment = _visible_comment_or_404(comment_id, db, current_user)
    if comment.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the comment's author can edit it")

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
    """A comment's own author can always delete it. The entry's primary
    author can additionally delete *any* comment on their own entry
    (moderation) - the same extra power the primary author already has over
    visibility, co-authors, and entry deletion. Co-authors get none of that:
    they can comment like anyone else with view access, but they don't get
    moderation power just because they can edit the entry's text."""
    comment = _visible_comment_or_404(comment_id, db, current_user)

    is_author = comment.author_id == current_user.id
    is_entry_primary_author = _is_owner(comment.entry, current_user)
    if not (is_author or is_entry_primary_author):
        raise HTTPException(status_code=403, detail="You do not have permission to delete this comment")

    db.delete(comment)
    db.commit()
