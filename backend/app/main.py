from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from .routers import entries, sessions, spotify, users  # noqa: E402  (must load after .env)

# Schema is owned by Alembic now (see backend/alembic/) - run
# `alembic upgrade head` before starting the app instead of relying on
# create_all, which doesn't know how to create the search-vector triggers.

app = FastAPI(title="Musical Memories API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=Path(__file__).resolve().parent.parent / "uploads"), name="uploads")

app.include_router(users.router)
app.include_router(sessions.router)
app.include_router(entries.router)
app.include_router(spotify.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
