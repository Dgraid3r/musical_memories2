from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from .logging_config import configure_logging  # noqa: E402  (must load after .env)
from .rate_limit import limiter  # noqa: E402
from .sentry_config import configure_sentry  # noqa: E402
from .routers import account, comments, entries, invites, sessions, spotify, users, workspaces  # noqa: E402

configure_logging()
configure_sentry()

# Schema is owned by Alembic now (see backend/alembic/) - run
# `alembic upgrade head` before starting the app instead of relying on
# create_all, which doesn't know how to create the search-vector triggers.

app = FastAPI(title="Musical Memories API")

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many attempts. Please wait a moment and try again."},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# No raw static mount for uploads - every image fetch goes through
# entries.image_router (GET /api/entries/{entry_id}/images/{image_id}),
# which enforces the same visibility check as the entry itself before
# serving or redirecting to the image. See app/storage.py.

app.include_router(users.router)
app.include_router(sessions.router)
app.include_router(account.router)
app.include_router(workspaces.router)
app.include_router(invites.router)
app.include_router(entries.router)
app.include_router(entries.image_router)
app.include_router(comments.router)
app.include_router(spotify.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
