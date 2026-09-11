import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import User, WorkspaceInvite, WorkspaceMembership
from ..rate_limit import AUTH_RATE_LIMIT, limiter
from ..schemas import WorkspaceInvitePreviewOut, WorkspaceMemberOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/invites", tags=["invites"])


def _get_valid_invite_or_error(token: str, db: Session) -> WorkspaceInvite:
    """Not-found, expired, revoked, and already-accepted are all distinct,
    clear error cases (never a crash) rather than one generic failure - an
    invite link a user clicks days later should tell them *why* it doesn't
    work. The token is an unguessable 32-byte random value (not a small
    integer id), so unlike workspace/entry ids there's no meaningful
    non-disclosure concern in telling the holder of a genuine token exactly
    what's wrong with it."""
    invite = db.scalar(select(WorkspaceInvite).where(WorkspaceInvite.token == token))
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.revoked_at is not None:
        raise HTTPException(status_code=410, detail="This invite has been revoked")
    if invite.accepted_at is not None:
        raise HTTPException(status_code=410, detail="This invite has already been accepted")
    if invite.expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="This invite has expired")
    return invite


@router.get("/{token}", response_model=WorkspaceInvitePreviewOut)
def preview_invite(token: str, db: Session = Depends(get_db)):
    """No auth required - this is what the invite link itself loads,
    before the invitee has necessarily logged in or registered. Tells the
    frontend enough to render "you've been invited to join X as a <role>"
    and to decide whether to show a login form (account_exists) or a
    registration form."""
    invite = _get_valid_invite_or_error(token, db)
    account_exists = db.scalar(select(User.id).where(User.email.ilike(invite.email))) is not None
    return WorkspaceInvitePreviewOut(
        workspace_id=invite.workspace_id,
        workspace_name=invite.workspace.name,
        email=invite.email,
        role=invite.role,
        expires_at=invite.expires_at,
        account_exists=account_exists,
    )


@router.post("/{token}/accept", response_model=WorkspaceMemberOut)
@limiter.limit(AUTH_RATE_LIMIT)
def accept_invite(
    request: Request,
    token: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """For an invitee who already has an account: log in, then accept.
    (An invitee with no account instead registers with the invited email
    via UserCreate.invite_token, which applies the same invite as part of
    registration - see routers/users.py - rather than calling this
    endpoint at all.)"""
    invite = _get_valid_invite_or_error(token, db)

    if invite.email.lower() != current_user.email.lower():
        raise HTTPException(status_code=403, detail="This invite was sent to a different email address")

    existing = db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == invite.workspace_id,
            WorkspaceMembership.user_id == current_user.id,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="You're already a member of this workspace")

    membership = WorkspaceMembership(workspace_id=invite.workspace_id, user_id=current_user.id, role=invite.role)
    db.add(membership)
    invite.accepted_at = datetime.utcnow()
    # This existence check above is inherently racy under real concurrency
    # (two near-simultaneous accepts of the same invite by the same user -
    # e.g. a double-click, or two tabs) - both could pass it before either
    # commits. Rather than trying to close that window with a lock, let the
    # database's own uq_workspace_membership constraint be the actual race
    # arbiter and catch the resulting IntegrityError here, the same
    # pattern users.py's register() already uses for username/email
    # uniqueness - not a new one invented for this endpoint.
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.info(
            "workspace.invite_accept_race workspace_id=%s user_id=%s", invite.workspace_id, current_user.id
        )
        raise HTTPException(status_code=409, detail="You're already a member of this workspace")
    logger.info(
        "workspace.invite_accepted workspace_id=%s user_id=%s role=%s", invite.workspace_id, current_user.id, invite.role
    )
    return WorkspaceMemberOut(user_id=current_user.id, username=current_user.username, role=invite.role)
