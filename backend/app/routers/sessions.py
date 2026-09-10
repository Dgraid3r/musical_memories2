import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import create_access_token, verify_password
from ..database import get_db
from ..models import User
from ..rate_limit import AUTH_RATE_LIMIT, limiter
from ..schemas import LoginInput, TokenOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", response_model=TokenOut, status_code=201)
@limiter.limit(AUTH_RATE_LIMIT)
def login(request: Request, payload: LoginInput, db: Session = Depends(get_db)):
    """Logging in is modeled as creating a session resource (the token).

    There is no server-side session state to delete on logout since the
    token is a stateless JWT - the frontend just discards it.
    """
    user = db.scalar(select(User).where(User.username == payload.username))
    # A deleted account's username is already scrubbed to a synthetic
    # placeholder (see routers/account.py), so this lookup already fails
    # to find it under the old, real username in practice - the explicit
    # is_deleted check is defense in depth, not the only thing stopping
    # this, and keeps the same generic message rather than confirming an
    # account by that name ever existed.
    if user is None or user.is_deleted or not verify_password(payload.password, user.hashed_password):
        logger.warning("auth.login_failed username=%r", payload.username)
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    logger.info("auth.login_succeeded user_id=%s", user.id)
    return TokenOut(access_token=create_access_token(user.id))
