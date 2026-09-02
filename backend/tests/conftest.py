import os

# Must be set before anything under app/ is imported: database.py reads
# DATABASE_URL at import time to build its engine, and auth/spotify_client
# read their env vars lazily but must never fall through to a real .env.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-do-not-use-in-production"
os.environ.setdefault("SPOTIFY_CLIENT_ID", "test-client-id")
os.environ.setdefault("SPOTIFY_CLIENT_SECRET", "test-client-secret")

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def _clean_database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


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
