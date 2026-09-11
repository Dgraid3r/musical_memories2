import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import User

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days
OAUTH_STATE_EXPIRE_MINUTES = 10

# auto_error=False so anonymous requests reach get_current_user_optional
# instead of FastAPI short-circuiting with its own 403.
bearer_scheme = HTTPBearer(auto_error=False)


def _secret_key() -> str:
    key = os.environ.get("JWT_SECRET_KEY")
    if not key:
        raise RuntimeError(
            "JWT_SECRET_KEY is not set. Copy backend/.env.example to backend/.env and set one "
            '(e.g. `python -c "import secrets; print(secrets.token_hex(32))"`).'
        )
    return key


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed_password.encode())


def create_access_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, _secret_key(), algorithm=ALGORITHM)


def _user_from_token(token: str, db: Session) -> User | None:
    try:
        payload = jwt.decode(token, _secret_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    user_id = payload.get("sub")
    if user_id is None:
        return None
    user = db.get(User, int(user_id))
    if user is not None and (user.is_deleted or not user.is_active):
        # There's no server-side session table for a stateless JWT to
        # revoke from (see sessions.py) - this is what "revoking all
        # active sessions" means here for either a permanent self-
        # deletion or a reversible admin deactivation: any token issued
        # before deletion/deactivation, on any device, stops
        # authenticating immediately, rather than staying valid until it
        # naturally expires up to ACCESS_TOKEN_EXPIRE_MINUTES later. A
        # reactivated user's tokens work again immediately too, for the
        # same reason - this check runs fresh on every request rather
        # than caching anything.
        return None
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        logger.warning("auth.missing_credentials")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user = _user_from_token(credentials.credentials, db)
    if user is None:
        logger.warning("auth.invalid_or_expired_token")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return user


def create_oauth_state(user_id: int) -> str:
    """A short-lived, signed token that carries the authenticated local
    user's identity through the Spotify authorize redirect. The browser
    round-trip to Spotify and back can't carry our Authorization header, so
    /api/spotify/callback identifies the user solely from this token - it
    must be both tamper-proof (hence signed, not just base64) and
    short-lived (10 minutes is far more than a real login->authorize->
    redirect-back takes)."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=OAUTH_STATE_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "purpose": "spotify_oauth", "exp": expire}
    return jwt.encode(payload, _secret_key(), algorithm=ALGORITHM)


def verify_oauth_state(state: str) -> int | None:
    """Returns the user id embedded in a state token from
    create_oauth_state, or None if it's missing, expired, tampered with, or
    wasn't actually an oauth-state token (defends against a state value
    that happens to be some other valid JWT, like an access token)."""
    try:
        payload = jwt.decode(state, _secret_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("purpose") != "spotify_oauth":
        return None
    user_id = payload.get("sub")
    if user_id is None:
        return None
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


def create_signin_state() -> str:
    """A short-lived, signed nonce protecting the Google sign-in redirect
    round-trip against CSRF - see routers/google_auth.py. Unlike
    create_oauth_state above, there is no already-authenticated local
    user to carry an identity for: Google sign-in may be creating a
    brand-new account, or the browser may have no session at all when the
    flow starts. So this only proves "this callback is answering a
    request this server itself issued a moment ago" (via the same
    signed/expiring/purpose-tagged JWT mechanism as create_oauth_state,
    not a hand-rolled scheme), never who the caller is - the callback
    identifies the user entirely from Google's verified ID token instead."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=OAUTH_STATE_EXPIRE_MINUTES)
    payload = {"purpose": "google_signin", "nonce": secrets.token_urlsafe(16), "exp": expire}
    return jwt.encode(payload, _secret_key(), algorithm=ALGORITHM)


def verify_signin_state(state: str) -> bool:
    """True if `state` is a still-valid, untampered token from
    create_signin_state - False for missing/expired/tampered/wrong-purpose
    values (including, deliberately, some other valid JWT this server
    issued for a different purpose, like an access token or a Spotify
    oauth_state - the purpose tag defends against exactly that
    cross-purpose-token confusion)."""
    try:
        payload = jwt.decode(state, _secret_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return False
    return payload.get("purpose") == "google_signin"


def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    if credentials is None:
        return None
    return _user_from_token(credentials.credentials, db)


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Site-wide admin access (see User.is_admin, routers/admin.py) -
    entirely separate from a workspace role (owner/member/subscriber),
    which only governs one workspace, not the platform.

    403, not 404: unlike require_workspace_owner and friends (which 404
    a private workspace a non-member can't see, to avoid disclosing it
    exists at all), an admin endpoint isn't hiding its own existence from
    a logged-in non-admin - it's simply refusing them, so the ordinary
    "you're logged in but not allowed to do this" status applies."""
    if not current_user.is_admin:
        logger.warning("auth.admin_required user_id=%s", current_user.id)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user
