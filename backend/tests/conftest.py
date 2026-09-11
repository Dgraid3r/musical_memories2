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
# A real (if fixed) Fernet key - not a placeholder string, since
# crypto.EncryptedString actually encrypts/decrypts with it in tests.
os.environ["TOKEN_ENCRYPTION_KEY"] = "zdoZ_SoNNaBLvqnw_2jnivraHmB-SkxHdJXsLK0LyrU="
os.environ.setdefault("SPOTIFY_CLIENT_ID", "test-client-id")
os.environ.setdefault("SPOTIFY_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("SPOTIFY_REDIRECT_URI", "http://localhost:8000/api/spotify/callback")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-google-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-google-client-secret")
os.environ.setdefault("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback")

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.email import clear_dev_outbox, last_email_to
from app.main import app
from app.nominatim_client import clear_search_cache as clear_places_search_cache
from app.nominatim_client import reset_throttle as reset_places_throttle
from app.rate_limit import limiter
from app.spotify_client import clear_search_cache, reset_throttle
from app.storage import get_storage


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


@pytest.fixture(autouse=True)
def _reset_spotify_throttle():
    # Same reasoning as the search-cache fixture above - otherwise a
    # search made near the end of one test could make an unrelated later
    # test's first search wait on the shared-client throttle for no
    # reason that test caused.
    reset_throttle()
    yield


@pytest.fixture(autouse=True)
def _clear_places_search_cache():
    # Same reasoning as _clear_spotify_search_cache above.
    clear_places_search_cache()
    yield


@pytest.fixture(autouse=True)
def _reset_places_throttle():
    # Same reasoning as _reset_spotify_throttle above - Nominatim's
    # throttle interval defaults to a full second, so leaving this unreset
    # could make an unrelated later test's first place search wait up to a
    # second for no reason that test caused.
    reset_places_throttle()
    yield


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    # Otherwise register/login calls from an earlier test (make_user calls
    # both, for every user it creates) would count against a later test's
    # budget and start returning 429s for reasons that test never intended.
    limiter.reset()
    yield


@pytest.fixture(autouse=True)
def _clear_email_outbox():
    # Same reasoning as the search-cache and rate-limiter fixtures above -
    # otherwise an email "sent" in one test (e.g. to alice@example.com)
    # would still be sitting in the in-memory outbox for a later test that
    # sends its own email to the same address and checks last_email_to.
    clear_dev_outbox()
    yield


@pytest.fixture(autouse=True)
def _reset_storage_backend():
    # get_storage() is lru_cache'd (constructing an S3 client per request
    # would be wasteful) - a test that monkeypatches OBJECT_STORAGE_* env
    # vars to exercise the S3-compatible backend must not leave that
    # cached selection in place for every other test, which all assume
    # the default local-disk backend.
    get_storage.cache_clear()
    yield
    get_storage.cache_clear()


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
    """Registers + logs in a user, returning {id, username, email, headers}."""

    def _make(username: str = "alice", password: str = "password123"):
        email = f"{username}@example.com"
        register_res = client.post(
            "/api/users",
            json={"username": username, "email": email, "password": password},
        )
        assert register_res.status_code == 201, register_res.text
        user = register_res.json()

        login_res = client.post("/api/sessions", json={"username": username, "password": password})
        assert login_res.status_code == 201, login_res.text
        token = login_res.json()["access_token"]

        return {
            "id": user["id"],
            "username": username,
            "email": email,
            "headers": {"Authorization": f"Bearer {token}"},
        }

    return _make


@pytest.fixture
def add_workspace_member(client):
    """Adds `member` (from make_user, who must already have an account) to
    `workspace` (from make_workspace), as its `owner` - via the real
    invite flow (create invite by email, then the invitee accepts),
    exactly like a real owner+invitee would, rather than a shortcut.
    Returns the created WorkspaceMemberOut dict."""

    def _add(owner: dict, workspace: dict, member: dict, role: str = "member") -> dict:
        invite_res = client.post(
            f"/api/workspaces/{workspace['id']}/invites",
            headers=owner["headers"],
            json={"email": member["email"], "role": role},
        )
        assert invite_res.status_code == 201, invite_res.text

        sent = last_email_to(member["email"])
        assert sent is not None, f"no invite email recorded for {member['email']}"
        token = sent["token"]

        accept_res = client.post(f"/api/invites/{token}/accept", headers=member["headers"])
        assert accept_res.status_code == 200, accept_res.text
        return accept_res.json()

    return _add


@pytest.fixture
def make_workspace(client, add_workspace_member):
    """Creates a workspace as `owner` (from make_user), who becomes its
    owner, and adds every user in `members` to it. Returns the created
    WorkspaceOut dict (id, name, created_at, created_by, role)."""

    def _make(owner: dict, *members: dict, name: str = "Test Workspace") -> dict:
        res = client.post("/api/workspaces", headers=owner["headers"], json={"name": name})
        assert res.status_code == 201, res.text
        workspace = res.json()
        for member in members:
            add_workspace_member(owner, workspace, member)
        return workspace

    return _make
