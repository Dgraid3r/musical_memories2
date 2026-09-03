import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import get_current_user, hash_password
from ..database import get_db
from ..models import User
from ..rate_limit import AUTH_RATE_LIMIT, limiter
from ..schemas import UserCreate, UserOut, UserPublic

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["users"])


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
