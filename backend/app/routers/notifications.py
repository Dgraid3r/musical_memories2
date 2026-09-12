"""In-app notifications - see app/models.py's Notification docstring for
the data model and why it's deliberately generic (built to support a
future notification type without a schema rework).

Strictly per-user: the only permission rule anywhere in this file is
"you can only ever see or mark-read your own notifications" - there is
no cross-user visibility of any kind, and no role/workspace-membership
check applies here at all.

Notifications themselves are created inline by whatever action triggers
them (see routers/comments.py's create_comment and routers/workspaces.py's
create_invite) rather than here - this module only ever reads and updates
rows that already exist for the caller."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import Notification, User
from ..schemas import NotificationActionOut, NotificationOut, UnreadNotificationCountOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

# Same limit/offset convention as GET /api/workspaces/public and GET
# /api/admin/users - see workspaces.py's PUBLIC_WORKSPACES_DEFAULT_LIMIT/
# MAX_LIMIT for the reasoning; matched here rather than inventing a new
# one, same as entries.py's list_entries did.
NOTIFICATIONS_DEFAULT_LIMIT = 20
NOTIFICATIONS_MAX_LIMIT = 100


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    limit: int = Query(NOTIFICATIONS_DEFAULT_LIMIT, ge=1, le=NOTIFICATIONS_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Most-recent-first, strictly the caller's own."""
    stmt = (
        select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return db.scalars(stmt).all()


@router.get("/unread-count", response_model=UnreadNotificationCountOut)
def unread_notification_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Powers the bell icon's badge - a plain count rather than making the
    frontend fetch every notification just to count the unread ones."""
    count = (
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == current_user.id, Notification.read_at.is_(None))
        )
        or 0
    )
    return UnreadNotificationCountOut(count=count)


def _get_own_notification_or_404(notification_id: int, db: Session, current_user: User) -> Notification:
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != current_user.id:
        # 404, not 403 - same non-disclosure convention used everywhere
        # else in this app: whether some other user's notification with
        # this id even exists is never confirmed to a caller it isn't
        # theirs.
        raise HTTPException(status_code=404, detail="Notification not found")
    return notification


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Idempotent - marking an already-read notification read again just
    returns it unchanged rather than bumping read_at to now."""
    notification = _get_own_notification_or_404(notification_id, db, current_user)
    if notification.read_at is None:
        notification.read_at = datetime.utcnow()
        db.commit()
        db.refresh(notification)
    return notification


@router.post("/mark-all-read", response_model=NotificationActionOut)
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """A single bulk UPDATE rather than loading and saving every row -
    only ever touches the caller's own still-unread notifications."""
    db.execute(
        update(Notification)
        .where(Notification.user_id == current_user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.utcnow())
    )
    db.commit()
    return NotificationActionOut(detail="All notifications marked as read.")
