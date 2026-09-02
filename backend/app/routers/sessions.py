from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import create_access_token, verify_password
from ..database import get_db
from ..models import User
from ..schemas import LoginInput, TokenOut

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", response_model=TokenOut, status_code=201)
def login(payload: LoginInput, db: Session = Depends(get_db)):
    """Logging in is modeled as creating a session resource (the token).

    There is no server-side session state to delete on logout since the
    token is a stateless JWT - the frontend just discards it.
    """
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    return TokenOut(access_token=create_access_token(user.id))
