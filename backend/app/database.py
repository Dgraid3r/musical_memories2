import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


def normalize_database_url(url: str) -> str:
    """Accepts a plain `postgresql://` URL - what Railway's own Postgres
    plugin (and most hosts) provide by default - in addition to the
    `postgresql+psycopg://` driver-qualified form this app otherwise uses
    everywhere. Without this, a first deploy needs a manual edit to the
    host-provided DATABASE_URL just to add the driver marker; with it,
    whatever format the host hands over just works. Also normalizes the
    legacy `postgres://` scheme some older tooling still emits."""
    for plain_scheme in ("postgresql://", "postgres://"):
        if url.startswith(plain_scheme):
            return "postgresql+psycopg://" + url[len(plain_scheme) :]
    return url


DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Copy backend/.env.example to backend/.env and point it at your "
        "Postgres instance (e.g. `docker compose up -d` from the project root, then "
        "DATABASE_URL=postgresql+psycopg://musical_memories:musical_memories@localhost:5432/musical_memories)."
    )
DATABASE_URL = normalize_database_url(DATABASE_URL)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
