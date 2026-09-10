import logging
import os
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import get_current_user, hash_password, verify_password
from ..database import get_db
from ..email import send_email
from ..models import EmailVerificationToken, PasswordResetToken, User, WorkspaceMembership
from ..rate_limit import AUTH_RATE_LIMIT, limiter
from ..schemas import (
    AccountDeleteInput,
    AccountDeleteOut,
    EmailVerificationResendOut,
    PasswordResetConfirmInput,
    PasswordResetRequestInput,
    PasswordResetRequestOut,
    UserOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/account", tags=["account"])

EMAIL_VERIFICATION_EXPIRE_HOURS = 24
PASSWORD_RESET_EXPIRE_MINUTES = 60
GENERIC_RESET_MESSAGE = "If that email address has an account, a password reset link has been sent to it."


def _frontend_url() -> str:
    # Mirrors workspaces._frontend_url() - the email link needs to land on
    # a frontend page that presents a form and calls the API itself, not
    # directly on the raw JSON API endpoint.
    return os.environ.get("FRONTEND_URL", "http://localhost:5173")


# --- Email verification ------------------------------------------------


@router.post("/verify-email/resend", response_model=EmailVerificationResendOut)
@limiter.limit(AUTH_RATE_LIMIT)
def resend_verification_email(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Requires being logged in - unlike password reset, there's no
    email-enumeration concern here (the caller already knows their own
    account), so this can just tell them plainly if they're already
    verified rather than pretending to resend."""
    if current_user.email_verified:
        return EmailVerificationResendOut(detail="Your email is already verified.")

    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=EMAIL_VERIFICATION_EXPIRE_HOURS)
    existing = db.scalar(select(EmailVerificationToken).where(EmailVerificationToken.user_id == current_user.id))
    if existing is None:
        db.add(EmailVerificationToken(user_id=current_user.id, token=token, expires_at=expires_at))
    else:
        existing.token = token
        existing.expires_at = expires_at
    db.commit()

    body = (
        "Verify your email address by visiting:\n\n"
        f"{_frontend_url()}/?verify={token}\n\n"
        f"This link expires in {EMAIL_VERIFICATION_EXPIRE_HOURS} hours."
    )
    send_email(current_user.email, "Verify your email - Musical Memories", body, token=token)
    logger.info("auth.verification_email_resent user_id=%s", current_user.id)
    return EmailVerificationResendOut(detail="Verification email sent.")


@router.post("/verify-email/{token}", response_model=UserOut)
def confirm_email_verification(token: str, db: Session = Depends(get_db)):
    """No auth required - the token itself, an unguessable 32-byte random
    value from the emailed link, is the proof of ownership. Verifying
    never blocks or changes core app access either way (see User.
    email_verified) - this only flips the flag."""
    record = db.scalar(select(EmailVerificationToken).where(EmailVerificationToken.token == token))
    if record is None:
        raise HTTPException(status_code=404, detail="Verification link not found or already used")
    if record.expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="This verification link has expired")

    user = record.user
    user.email_verified = True
    db.delete(record)
    db.commit()
    db.refresh(user)
    logger.info("auth.email_verified user_id=%s", user.id)
    return user


# --- Password reset ------------------------------------------------------


@router.post("/password-reset/request", response_model=PasswordResetRequestOut)
@limiter.limit(AUTH_RATE_LIMIT)
def request_password_reset(request: Request, payload: PasswordResetRequestInput, db: Session = Depends(get_db)):
    """Always returns the same response whether or not the email belongs
    to an account - responding differently would let anyone probe which
    email addresses are registered (account enumeration), which this
    endpoint must not leak."""
    user = db.scalar(select(User).where(User.email.ilike(payload.email)))
    if user is not None:
        # Invalidate any still-live earlier requests - only the most
        # recently requested link should actually work.
        for old in db.scalars(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)
            )
        ):
            old.used_at = datetime.utcnow()

        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(minutes=PASSWORD_RESET_EXPIRE_MINUTES)
        db.add(PasswordResetToken(user_id=user.id, token=token, expires_at=expires_at))
        db.commit()

        body = (
            "A password reset was requested for your Musical Memories account. If this was you, "
            f"visit:\n\n{_frontend_url()}/?reset={token}\n\n"
            f"This link expires in {PASSWORD_RESET_EXPIRE_MINUTES} minutes. If you didn't request "
            "this, you can ignore this email - your password hasn't been changed."
        )
        send_email(user.email, "Reset your password - Musical Memories", body, token=token)
        logger.info("auth.password_reset_requested user_id=%s", user.id)
    else:
        logger.info("auth.password_reset_requested_unknown_email")

    return PasswordResetRequestOut(detail=GENERIC_RESET_MESSAGE)


@router.post("/password-reset/{token}", response_model=PasswordResetRequestOut)
@limiter.limit(AUTH_RATE_LIMIT)
def confirm_password_reset(
    request: Request, token: str, payload: PasswordResetConfirmInput, db: Session = Depends(get_db)
):
    record = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token == token))
    if record is None:
        raise HTTPException(status_code=404, detail="Reset link not found")
    if record.used_at is not None:
        raise HTTPException(status_code=410, detail="This reset link has already been used")
    if record.expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="This reset link has expired")

    user = record.user
    user.hashed_password = hash_password(payload.new_password)
    record.used_at = datetime.utcnow()
    db.commit()
    logger.info("auth.password_reset_completed user_id=%s", user.id)
    return PasswordResetRequestOut(detail="Your password has been reset. You can now log in with your new password.")


# --- Account deletion ------------------------------------------------------


@router.delete("", response_model=AccountDeleteOut)
@limiter.limit(AUTH_RATE_LIMIT)
def delete_account(
    request: Request,
    payload: AccountDeleteInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permanently deletes the caller's own account.

    The User row itself is never deleted - it's anonymized in place (see
    models.User.deleted_at / is_deleted). Every entry or comment this user
    authored in a shared workspace survives untouched under the same
    user_id; only this user's own identifying fields (username, email,
    password) get scrubbed, and anywhere the app renders that authorship it
    shows models.DELETED_USER_DISPLAY_NAME instead of a real name once
    is_deleted is set.

    Sole ownership of a workspace that still has other members blocks
    deletion outright - the caller must transfer ownership first through
    the existing PATCH /api/workspaces/{id}/transfer-ownership endpoint
    (this endpoint deliberately never performs a transfer itself). Sole
    ownership of a workspace where the caller is also the *only* member is
    safe to cascade-delete along with the account: nobody else could
    possibly have write access to it (a co-author must already be a
    workspace member), so nothing shared is lost.
    """
    if not verify_password(payload.password, current_user.hashed_password):
        logger.warning("account.delete_failed_wrong_password user_id=%s", current_user.id)
        raise HTTPException(status_code=401, detail="Incorrect password")

    owned_memberships = db.scalars(
        select(WorkspaceMembership).where(
            WorkspaceMembership.user_id == current_user.id,
            WorkspaceMembership.role == "owner",
        )
    ).all()

    blocking_workspaces = []
    solely_owned_workspaces = []
    for membership in owned_memberships:
        other_members_count = db.scalar(
            select(func.count())
            .select_from(WorkspaceMembership)
            .where(
                WorkspaceMembership.workspace_id == membership.workspace_id,
                WorkspaceMembership.user_id != current_user.id,
            )
        )
        if other_members_count > 0:
            blocking_workspaces.append(membership.workspace)
        else:
            solely_owned_workspaces.append(membership.workspace)

    if blocking_workspaces:
        names = ", ".join(f'"{w.name}"' for w in blocking_workspaces)
        raise HTTPException(
            status_code=409,
            detail=(
                "Transfer ownership of the following workspace(s) before deleting your account: "
                f"{names}. Use the workspace settings to transfer ownership to another member first."
            ),
        )

    # Safe to cascade - the caller is the only member, so deleting the
    # workspace deletes only their own content (Workspace.memberships/
    # entries/tags/invites all cascade="all, delete-orphan").
    for workspace in solely_owned_workspaces:
        db.delete(workspace)

    # Every remaining membership (non-owner roles, or owner roles already
    # handled above) is removed outright - a deleted account can't log in
    # anymore, so staying listed as a workspace member would be misleading.
    for membership in db.scalars(
        select(WorkspaceMembership).where(WorkspaceMembership.user_id == current_user.id)
    ):
        db.delete(membership)

    if current_user.spotify_token is not None:
        db.delete(current_user.spotify_token)

    for token in db.scalars(
        select(EmailVerificationToken).where(EmailVerificationToken.user_id == current_user.id)
    ):
        db.delete(token)
    for token in db.scalars(
        select(PasswordResetToken).where(PasswordResetToken.user_id == current_user.id)
    ):
        db.delete(token)

    # Scrub PII. The placeholder username/email only need to satisfy the
    # unique constraints on those columns - they're never shown to anyone;
    # DELETED_USER_DISPLAY_NAME is what actually gets displayed once
    # is_deleted is set (see owner_username/author_username/UserPublic).
    # ".invalid" is the RFC 2606 reserved TLD guaranteed to never be a real
    # registrable domain, so this placeholder can never collide with a
    # future real registration.
    current_user.username = f"deleted-user-{current_user.id}"
    current_user.email = f"deleted-user-{current_user.id}@deleted.invalid"
    current_user.hashed_password = hash_password(secrets.token_urlsafe(32))
    current_user.deleted_at = datetime.utcnow()

    db.commit()
    logger.warning("account.deleted user_id=%s", current_user.id)
    return AccountDeleteOut(detail="Your account has been permanently deleted.")
