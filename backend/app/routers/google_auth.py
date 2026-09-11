import logging
import os
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import create_access_token, create_signin_state, hash_password, verify_signin_state
from ..database import get_db
from ..google_oauth import (
    GoogleSignInNotConfigured,
    GoogleSignInUnavailable,
    GoogleTokenInvalid,
    build_authorize_url,
    exchange_code_for_identity,
    is_configured,
)
from ..models import User
from ..schemas import GoogleSignInConfigOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth/google", tags=["auth"])


def _frontend_url() -> str:
    # Mirrors spotify._frontend_url()/account._frontend_url()/etc.
    return os.environ.get("FRONTEND_URL", "http://localhost:5173")


def _username_from_email(email: str, db: Session) -> str:
    """Derives a username from the email's local-part, de-duplicated with
    a numeric suffix if already taken - used only when creating a brand
    new account (an existing account keeps its existing username even
    when later linked to Google)."""
    local_part = email.split("@", 1)[0]
    # UserCreate constrains usernames to [a-zA-Z0-9_.-] - an email
    # local-part can contain characters outside that (e.g. "+"), so strip
    # anything not already allowed rather than reject the whole email.
    base = re.sub(r"[^a-zA-Z0-9_.-]", "", local_part)
    if len(base) < 3:
        # Below UserCreate's min_length=3 - pad rather than fail outright.
        base = (base + "user") if base else "user"
    base = base[:50]  # UserCreate's max_length=50

    candidate = base
    suffix = 1
    while db.scalar(select(User.id).where(User.username == candidate)) is not None:
        suffix += 1
        candidate = f"{base}{suffix}"[:50]
    return candidate


@router.get("/config", response_model=GoogleSignInConfigOut)
def config():
    """Whether Google sign-in is available at all - the frontend uses
    this to decide whether to show the button. No auth required: this has
    to be checkable before anyone can possibly be logged in."""
    return GoogleSignInConfigOut(enabled=is_configured())


@router.get("/login")
def login():
    """Starts the redirect round-trip to Google. See google_oauth.py's
    module docstring and auth.create_signin_state for why this can't
    reuse Spotify's create_oauth_state (there's no logged-in user yet -
    there may not even be an existing account)."""
    try:
        state = create_signin_state()
        return RedirectResponse(build_authorize_url(state))
    except GoogleSignInNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/callback")
def callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Google redirects the user's browser here after they approve (or
    deny) sign-in. No auth dependency - the browser can't attach a JWT to
    a redirect Google initiates - callers are identified entirely from
    Google's verified ID token once the code is exchanged.

    On success, redirects to the frontend with the new access token in
    the URL *fragment* (`#token=...`), never a query param - a fragment
    is never sent to the server (ours or any proxy/CDN in front of it) or
    written to access logs, and the frontend reads it once, stores it
    through the exact same localStorage mechanism a normal login uses,
    then strips it from the URL (see auth/AuthContext.tsx). On any
    failure, redirects with a `?google=<reason>` flag instead - the same
    query-param-flag shape spotify.py's callback already uses for its own
    non-fatal outcomes (denied/unavailable), since none of these reasons
    are secret and a query param is fine for them."""
    frontend_url = _frontend_url()

    if error is not None:
        return RedirectResponse(f"{frontend_url}/?google=denied")
    if not code or not state or not verify_signin_state(state):
        logger.warning("google_signin.invalid_or_missing_state")
        return RedirectResponse(f"{frontend_url}/?google=invalid_state")

    try:
        identity = exchange_code_for_identity(code)
    except GoogleSignInNotConfigured:
        return RedirectResponse(f"{frontend_url}/?google=unavailable")
    except GoogleSignInUnavailable:
        return RedirectResponse(f"{frontend_url}/?google=unavailable")
    except GoogleTokenInvalid:
        return RedirectResponse(f"{frontend_url}/?google=invalid_token")

    # 1) Returning user - a google_sub match is the fast path and never
    #    re-derives anything from the (possibly since-changed) email.
    user = db.scalar(select(User).where(User.google_sub == identity.sub))
    if user is not None:
        if user.is_deleted:
            return RedirectResponse(f"{frontend_url}/?google=account_deleted")
    else:
        # 2) No google_sub match - an existing *local* account with this
        #    exact (Google-verified) email gets this google_sub linked,
        #    so it can be signed into either way from now on.
        existing = db.scalar(select(User).where(User.email.ilike(identity.email)))
        if existing is not None:
            if existing.is_deleted:
                # A deleted account's email is scrubbed to a synthetic
                # deleted-user-{id}@deleted.invalid address (see
                # account.py), so this branch shouldn't be reachable with
                # a real Google email in practice - defensive anyway,
                # same as sessions.py's login() checking is_deleted.
                return RedirectResponse(f"{frontend_url}/?google=account_deleted")
            existing.google_sub = identity.sub
            db.commit()
            logger.info("google_signin.linked_existing_account user_id=%s", existing.id)
            user = existing
        else:
            # 3) Neither matched - brand new account.
            username = _username_from_email(identity.email, db)
            new_user = User(
                username=username,
                email=identity.email,
                # Unusable, never revealed to anyone including this user -
                # Google sign-in is the only way into this account unless
                # they later set a local password (out of scope here).
                # Same "scrub to an unusable random hash" spirit as
                # account.py's self-deletion PII scrub, applied here to
                # *create* an already-unusable password rather than
                # scrub a real one away.
                hashed_password=hash_password(secrets.token_urlsafe(32)),
                email_verified=True,  # Google already verified this address
                google_sub=identity.sub,
            )
            db.add(new_user)
            db.commit()
            db.refresh(new_user)
            logger.info("google_signin.created_account user_id=%s", new_user.id)
            user = new_user

    token = create_access_token(user.id)
    return RedirectResponse(f"{frontend_url}/#token={token}")
