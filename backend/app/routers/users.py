import logging
import os
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import get_current_user, hash_password
from ..database import get_db
from ..email import send_email
from ..models import EmailVerificationToken, User, WorkspaceInvite, WorkspaceMembership
from ..rate_limit import AUTH_RATE_LIMIT, limiter
from ..schemas import UserCreate, UserOut, UserPublic

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["users"])

EMAIL_VERIFICATION_EXPIRE_HOURS = 24


def _frontend_url() -> str:
    # Mirrors workspaces._frontend_url()/account._frontend_url() - the
    # emailed link needs to land on a frontend page, not the raw JSON API.
    return os.environ.get("FRONTEND_URL", "http://localhost:5173")


def _send_verification_email(user: User, db: Session) -> None:
    """Called on register and on resend - either way this replaces any
    previous still-live token for the user (see EmailVerificationToken),
    so an old email's link stops working once a newer one is sent."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=EMAIL_VERIFICATION_EXPIRE_HOURS)

    existing = db.scalar(select(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id))
    if existing is None:
        db.add(EmailVerificationToken(user_id=user.id, token=token, expires_at=expires_at))
    else:
        existing.token = token
        existing.expires_at = expires_at
    db.commit()

    link = f"{_frontend_url()}/?verify={token}"
    body = (
        "Welcome to Musical Memories! Verify your email address by visiting:\n\n"
        f"{link}\n\n"
        f"This link expires in {EMAIL_VERIFICATION_EXPIRE_HOURS} hours. You can keep using the app "
        "in the meantime - verifying isn't required to log in or add memories."
    )
    send_email(user.email, "Verify your email - Musical Memories", body, token=token)


def _try_apply_invite_on_register(invite_token: str, user: User, db: Session) -> None:
    """Best-effort: a broken, expired, or mismatched invite token must
    never block account creation - registration has already succeeded by
    the time this runs. Failures here are logged, not raised."""
    invite = db.scalar(select(WorkspaceInvite).where(WorkspaceInvite.token == invite_token))
    if invite is None:
        logger.warning("invite.apply_on_register_not_found user_id=%s", user.id)
        return
    if invite.accepted_at is not None or invite.revoked_at is not None or invite.expires_at < datetime.utcnow():
        logger.warning("invite.apply_on_register_invalid user_id=%s invite_id=%s", user.id, invite.id)
        return
    if invite.email.lower() != user.email.lower():
        logger.warning("invite.apply_on_register_email_mismatch user_id=%s invite_id=%s", user.id, invite.id)
        return

    db.add(WorkspaceMembership(workspace_id=invite.workspace_id, user_id=user.id, role=invite.role))
    invite.accepted_at = datetime.utcnow()
    db.commit()
    logger.info(
        "workspace.invite_accepted_via_registration workspace_id=%s user_id=%s role=%s",
        invite.workspace_id, user.id, invite.role,
    )


@router.post("", response_model=UserOut, status_code=201)
@limiter.limit(AUTH_RATE_LIMIT)
def register(request: Request, payload: UserCreate, db: Session = Depends(get_db)):
    user = User(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.warning("auth.register_conflict username=%r", payload.username)
        raise HTTPException(status_code=409, detail="Username or email already registered")
    db.refresh(user)
    logger.info("auth.register_succeeded user_id=%s", user.id)

    _send_verification_email(user, db)

    if payload.invite_token:
        _try_apply_invite_on_register(payload.invite_token, user, db)

    db.refresh(user)
    return user


@router.get("/me", response_model=UserOut)
def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("", response_model=list[UserPublic])
def search_users(
    q: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Username search for picking co-authors. Auth-gated (not the email-
    bearing UserOut) so the user directory isn't scrapable anonymously."""
    stmt = (
        select(User)
        .where(User.username.ilike(f"%{q}%"))
        .where(User.id != current_user.id)
        .order_by(User.username)
        .limit(10)
    )
    return db.scalars(stmt).all()
