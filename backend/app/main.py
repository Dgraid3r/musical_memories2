import logging
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy.orm import Session

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from .database import check_database_health, get_db  # noqa: E402
from .logging_config import configure_logging  # noqa: E402  (must load after .env)
from .rate_limit import limiter  # noqa: E402
from .sentry_config import configure_sentry  # noqa: E402
from .routers import account, admin, comments, entries, google_auth, invites, places, sessions, spotify, users, workspaces  # noqa: E402

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
app.include_router(google_auth.router)
app.include_router(admin.router)


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    """Actually checks the database rather than unconditionally claiming
    ok - a dead/unreachable DB is exactly the condition an external
    uptime monitor (see README "Monitoring") needs to catch, and this is
    what it should be pointed at once the app is deployed somewhere
    reachable from the internet. Shares its check with GET
    /api/admin/stats (see database.check_database_health) rather than
    each defining its own."""
    if not check_database_health(db):
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

def _resolve_within_dist(full_path: str) -> Path | None:
    """Resolves full_path against FRONTEND_DIST_DIR and returns it only if
    the result is genuinely contained within that directory - the same
    containment guarantee Starlette's own StaticFiles already provides for
    the /assets mount above, which this hand-rolled catch-all route was
    missing.

    full_path arrives here already percent-decoded by Starlette/uvicorn's
    own routing, so a request for /%2e%2e/%2e%2e/proc/self/environ (or the
    unencoded /../../proc/self/environ) reaches this function as a
    perfectly ordinary-looking "../../proc/self/environ" - it must never
    be trusted as safe just because the string itself looks like a
    relative path. Checking containment on the *resolved* candidate
    (rather than trying to sanitize the input string) is what actually
    closes this: it doesn't matter how ../ segments, an accidental
    absolute-path override, or a symlink inside dist/ pointing outside it
    got the candidate to where it is - if the resolved path isn't
    actually inside the resolved root, this returns None.

    Returns None for anything outside the directory or that doesn't exist
    as a file - the caller (serve_frontend) treats that identically to
    the ordinary "not a real static file" case and falls through to
    index.html either way, so a traversal attempt looks exactly like any
    other unmatched SPA route to whoever's probing it, never a distinct
    error."""
    dist_root = FRONTEND_DIST_DIR.resolve()
    candidate = (FRONTEND_DIST_DIR / full_path).resolve()
    if candidate.is_relative_to(dist_root) and candidate.is_file():
        return candidate
    return None


def serve_frontend(full_path: str):
    """SPA fallback: any path that isn't an API route or a real static
    file resolves to index.html, so client-side routing (even though
    the frontend doesn't use any today - cheap to support now, awkward
    to retrofit later) works on a hard refresh/direct link too. Every
    /api/* route is registered above and already took precedence for
    anything it matches; an /api/* path that reaches here at all is
    genuinely unmatched and must 404, never silently fall back to the
    frontend shell.

    Defined unconditionally (route *registration* below stays
    conditional on FRONTEND_DIST_DIR actually existing, exactly as
    before) purely so this - the security-relevant handler - stays
    directly importable and testable in dev/test, where that directory
    never exists."""
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")
    if full_path:
        candidate = _resolve_within_dist(full_path)
        if candidate is not None:
            return FileResponse(candidate)
    return FileResponse(FRONTEND_DIST_DIR / "index.html")


if FRONTEND_DIST_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST_DIR / "assets"), name="frontend-assets")
    app.get("/{full_path:path}", include_in_schema=False)(serve_frontend)
