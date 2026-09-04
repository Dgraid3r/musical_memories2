import logging
import os
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user, hash_password
from ..database import get_db
from ..email import send_email
from ..models import EmailVerificationToken, PasswordResetToken, User
from ..rate_limit import AUTH_RATE_LIMIT, limiter
from ..schemas import (
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
