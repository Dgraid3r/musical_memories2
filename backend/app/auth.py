import logging
import os
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
    if user is not None and user.is_deleted:
        # There's no server-side session table for a stateless JWT to
        # revoke from (see sessions.py) - this is what "revoking all
        # active sessions" on deletion actually means here: any token
        # issued before deletion, on any device, stops authenticating
        # immediately, rather than staying valid until it naturally
        # expires up to ACCESS_TOKEN_EXPIRE_MINUTES later.
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


def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    if credentials is None:
        return None
    return _user_from_token(credentials.credentials, db)
