import os

# Must be set before anything under app/ is imported: database.py reads
# DATABASE_URL at import time to build its engine, and auth/spotify_client
# read their env vars lazily but must never fall through to a real .env.
# Points at the `musical_memories_test` database created alongside the main
# one by docker/init-test-db.sh (see docker-compose.yml) - a separate
# database from the dev one so test runs never touch real data.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://musical_memories:musical_memories@localhost:5432/musical_memories_test",
)
os.environ["JWT_SECRET_KEY"] = "test-secret-key-do-not-use-in-production"
os.environ.setdefault("SPOTIFY_CLIENT_ID", "test-client-id")
os.environ.setdefault("SPOTIFY_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("SPOTIFY_REDIRECT_URI", "http://localhost:8000/api/spotify/callback")

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.spotify_client import clear_search_cache


@pytest.fixture(autouse=True)
def _clean_database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _clear_spotify_search_cache():
    # Otherwise a cached result from one test (e.g. a mocked response with a
    # specific image/owner shape) would silently satisfy a later test's
    # identically-worded search instead of that test's own mock being called.
    clear_search_cache()
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db_session():
    """A direct DB session for tests that need to set up or assert on rows
    the API surface doesn't expose (e.g. spotify_tokens, which never appears
    in any response body)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def make_user(client):
    """Registers + logs in a user, returning {id, username, headers}."""

    def _make(username: str = "alice", password: str = "password123"):
        register_res = client.post(
            "/api/users",
            json={"username": username, "email": f"{username}@example.com", "password": password},
        )
        assert register_res.status_code == 201, register_res.text
        user = register_res.json()

        login_res = client.post("/api/sessions", json={"username": username, "password": password})
        assert login_res.status_code == 201, login_res.text
        token = login_res.json()["access_token"]

        return {"id": user["id"], "username": username, "headers": {"Authorization": f"Bearer {token}"}}

    return _make
