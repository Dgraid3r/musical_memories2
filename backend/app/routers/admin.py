"""Site-wide admin dashboard: user management and operational visibility
only. Deliberately NOT content moderation - no workspace or entry
browsing/removal tooling lives here, and nothing here ever reads or
returns entry text, workspace names, or any other user-authored content.

Every endpoint requires auth.require_admin (see User.is_admin) - granted
via scripts/grant_admin.py, never a web endpoint (see that script's
docstring for why the first admin can't be self-service)."""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..database import check_database_health, get_db
from ..models import BackupRun, JournalEntry, User, Workspace
from ..schemas import AdminStatsOut, AdminUserActionOut, AdminUserOut, BackupStatusOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Same limit/offset convention as GET /api/workspaces/public
# (browse_public_workspaces) - see workspaces.py's
# PUBLIC_WORKSPACES_DEFAULT_LIMIT/MAX_LIMIT for the same reasoning.
ADMIN_USERS_DEFAULT_LIMIT = 20
ADMIN_USERS_MAX_LIMIT = 100


@router.get("/users", response_model=list[AdminUserOut])
def list_users(
    q: str | None = Query(None, min_length=1, description="Filter by username or email"),
    limit: int = Query(ADMIN_USERS_DEFAULT_LIMIT, ge=1, le=ADMIN_USERS_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """User management, not content moderation - only account-level
    fields (username, email, timestamps, flags) ever appear here."""
    stmt = select(User)
    if q:
        stmt = stmt.where(or_(User.username.ilike(f"%{q}%"), User.email.ilike(f"%{q}%")))
    stmt = stmt.order_by(User.created_at.desc()).limit(limit).offset(offset)
    return db.scalars(stmt).all()


def _get_target_user_or_404(user_id: int, db: Session) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/users/{user_id}/deactivate", response_model=AdminUserActionOut)
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Reversible - sets User.is_active False, nothing else. Blocks
    login at the exact same checkpoints sessions.py's login() and
    auth._user_from_token already check (see those), so this takes
    effect immediately, including for a token issued before
    deactivation. Guards only against locking yourself out by mistake -
    deactivating another admin is allowed (v1 deliberately has no
    admin-hierarchy system, per the task scope)."""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
    target = _get_target_user_or_404(user_id, db)
    target.is_active = False
    db.commit()
    logger.warning("admin.user_deactivated user_id=%s by=%s", user_id, current_user.id)
    return AdminUserActionOut(detail="Account deactivated.")


@router.post("/users/{user_id}/reactivate", response_model=AdminUserActionOut)
def reactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Restores login immediately - the same is_active flag checked at
    login/token-auth time flips back, nothing else to undo since
    deactivation never touched anything but that flag."""
    target = _get_target_user_or_404(user_id, db)
    target.is_active = True
    db.commit()
    logger.info("admin.user_reactivated user_id=%s by=%s", user_id, current_user.id)
    return AdminUserActionOut(detail="Account reactivated.")


@router.get("/stats", response_model=AdminStatsOut)
def stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Operational visibility only - counts and timestamps, never entry
    content or workspace names (see this module's docstring)."""
    total_users = db.scalar(select(func.count()).select_from(User)) or 0
    total_workspaces = db.scalar(select(func.count()).select_from(Workspace)) or 0
    total_entries = db.scalar(select(func.count()).select_from(JournalEntry)) or 0

    now = datetime.utcnow()
    new_signups_7d = (
        db.scalar(select(func.count()).select_from(User).where(User.created_at >= now - timedelta(days=7))) or 0
    )
    new_signups_30d = (
        db.scalar(select(func.count()).select_from(User).where(User.created_at >= now - timedelta(days=30))) or 0
    )

    latest_run = db.scalar(select(BackupRun).order_by(BackupRun.started_at.desc()).limit(1))
    latest_backup = (
        BackupStatusOut(
            started_at=latest_run.started_at,
            succeeded=latest_run.succeeded,
            error_message=latest_run.error_message,
        )
        if latest_run is not None
        else None
    )

    return AdminStatsOut(
        total_users=total_users,
        total_workspaces=total_workspaces,
        total_entries=total_entries,
        new_signups_7d=new_signups_7d,
        new_signups_30d=new_signups_30d,
        database_healthy=check_database_health(db),
        latest_backup=latest_backup,
    )
