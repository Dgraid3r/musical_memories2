import logging
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from .database import get_db  # noqa: E402
from .logging_config import configure_logging  # noqa: E402  (must load after .env)
from .rate_limit import limiter  # noqa: E402
from .sentry_config import configure_sentry  # noqa: E402
from .routers import account, comments, entries, invites, places, sessions, spotify, users, workspaces  # noqa: E402

configure_logging()
configure_sentry()

logger = logging.getLogger(__name__)

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
app.include_router(places.router)


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    """Actually checks the database rather than unconditionally claiming
    ok - a dead/unreachable DB is exactly the condition an external
    uptime monitor (see README "Monitoring") needs to catch, and this is
    what it should be pointed at once the app is deployed somewhere
    reachable from the internet."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.error("health.database_unreachable", exc_info=True)
        return JSONResponse(status_code=503, content={"status": "unhealthy", "detail": "database unreachable"})
    return {"status": "ok"}


# --- Serve the built frontend (production only) -----------------------
#
# Populated by the root Dockerfile's frontend build stage, which copies
# frontend/dist here (see DEPLOYMENT.md). Absent in local dev - the Vite
# dev server serves the frontend there instead (see README "Running
# locally") - so this whole block is a no-op unless the directory exists,
# never a startup requirement.
FRONTEND_DIST_DIR = Path(__file__).resolve().parent.parent / "static" / "dist"

if FRONTEND_DIST_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST_DIR / "assets"), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_frontend(full_path: str):
        """SPA fallback: any path that isn't an API route or a real static
        file resolves to index.html, so client-side routing (even though
        the frontend doesn't use any today - cheap to support now, awkward
        to retrofit later) works on a hard refresh/direct link too. Every
        /api/* route is registered above and already took precedence for
        anything it matches; an /api/* path that reaches here at all is
        genuinely unmatched and must 404, never silently fall back to the
        frontend shell."""
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = FRONTEND_DIST_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST_DIR / "index.html")
