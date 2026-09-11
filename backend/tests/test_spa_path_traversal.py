"""Regression tests for the SPA catch-all path-traversal fix in
app/main.py. FRONTEND_DIST_DIR.is_dir() is always False in dev/test (see
that module's comment - the built frontend only exists in the production
Docker image), so the real catch-all route is never actually registered
on the shared `app` here - serve_frontend/_resolve_within_dist are
defined unconditionally specifically so they stay directly testable
regardless.

Two layers, deliberately:
- Direct calls to serve_frontend/_resolve_within_dist with an
  already-decoded "../" string - this is exactly what full_path
  contains by the time Starlette/uvicorn's own (trusted, not
  re-verified here) routing hands it to the function, whether the
  original request used a literal ../ or a percent-encoded %2e%2e.
  Reliable and deterministic - no HTTP-client URL-normalization
  behavior to account for.
- A real HTTP request, through a throwaway standalone FastAPI app (never
  the shared `app` instance other tests use) registering the real
  serve_frontend on a real route, with a genuinely percent-encoded
  traversal path on the wire - proving the fix holds end-to-end through
  actual routing/decoding, not just at the function level.
"""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import HTTPException, _resolve_within_dist, serve_frontend


@pytest.fixture
def dist_dir(tmp_path):
    """A temp directory shaped like the real deployment: a "dist" folder
    (what FRONTEND_DIST_DIR points at) containing index.html and
    assets/something.js, with a secret file as a *sibling* of dist -
    exactly the shape a ../ escape targets, mirroring the real
    /proc/self/environ-is-a-few-levels-up scenario."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa shell</html>")
    (dist / "assets" / "something.js").write_text("console.log('legit asset')")
    (tmp_path / "secret.txt").write_text("TOP SECRET - JWT_SECRET_KEY=whatever")
    return dist


# --- _resolve_within_dist (the core containment check) ----------------------


def test_resolve_within_dist_rejects_traversal(dist_dir):
    with patch("app.main.FRONTEND_DIST_DIR", dist_dir):
        assert _resolve_within_dist("../secret.txt") is None
        assert _resolve_within_dist("../../secret.txt") is None
        assert _resolve_within_dist("assets/../../secret.txt") is None


def test_resolve_within_dist_allows_a_real_contained_file(dist_dir):
    with patch("app.main.FRONTEND_DIST_DIR", dist_dir):
        resolved = _resolve_within_dist("assets/something.js")
    assert resolved == (dist_dir / "assets" / "something.js").resolve()
    assert resolved.read_text() == "console.log('legit asset')"


def test_resolve_within_dist_returns_none_for_a_merely_missing_file(dist_dir):
    """The ordinary "not a real static file" case (no traversal
    involved) must still behave exactly as before - returns None so the
    caller falls through to index.html, not an error."""
    with patch("app.main.FRONTEND_DIST_DIR", dist_dir):
        assert _resolve_within_dist("assets/does-not-exist.js") is None


def test_resolve_within_dist_rejects_absolute_path_override(dist_dir, tmp_path):
    """Path.__truediv__ with an absolute right-hand operand discards the
    left side entirely (Path("/a") / "/etc/passwd" == Path("/etc/passwd"))
    - a classic pathlib footgun that would reintroduce this exact bug if
    the containment check were ever done on the *input* instead of the
    resolved candidate. Proves it's actually the post-resolution check
    doing the work, not an accident of how these particular paths
    happen to look."""
    secret = tmp_path / "secret.txt"
    with patch("app.main.FRONTEND_DIST_DIR", dist_dir):
        assert _resolve_within_dist(str(secret)) is None


# --- serve_frontend (the actual route handler) -------------------------------


def test_serve_frontend_traversal_falls_through_to_index_html(dist_dir):
    """The security-critical behavioral requirement: a traversal attempt
    must look *identical* to any other unmatched SPA route - index.html,
    not a distinct error, and never the targeted file's contents."""
    with patch("app.main.FRONTEND_DIST_DIR", dist_dir):
        response = serve_frontend("../secret.txt")
    assert str(response.path) == str(dist_dir / "index.html")


def test_serve_frontend_serves_a_real_asset(dist_dir):
    """Must not break the actual SPA-serving behavior while fixing this."""
    with patch("app.main.FRONTEND_DIST_DIR", dist_dir):
        response = serve_frontend("assets/something.js")
    assert str(response.path) == str((dist_dir / "assets" / "something.js").resolve())


def test_serve_frontend_no_path_serves_index_html(dist_dir):
    with patch("app.main.FRONTEND_DIST_DIR", dist_dir):
        response = serve_frontend("")
    assert str(response.path) == str(dist_dir / "index.html")


def test_serve_frontend_api_path_still_404s(dist_dir):
    """Unrelated to this fix, but a one-line regression check that the
    fix didn't disturb the existing "/api/* reaching here is genuinely
    unmatched" behavior."""
    with patch("app.main.FRONTEND_DIST_DIR", dist_dir):
        with pytest.raises(HTTPException) as exc_info:
            serve_frontend("api/whatever")
    assert exc_info.value.status_code == 404


# --- Real HTTP request, real routing/decoding, a throwaway standalone app ---


def _make_standalone_app() -> FastAPI:
    """A fresh, isolated FastAPI instance - never the shared `app` other
    tests use - so registering this catch-all route here can't affect
    any other test's unmatched-path behavior for the rest of the suite."""
    standalone = FastAPI()
    standalone.get("/{full_path:path}")(serve_frontend)
    return standalone


def test_http_percent_encoded_traversal_returns_index_html_not_secret(dist_dir):
    with patch("app.main.FRONTEND_DIST_DIR", dist_dir):
        client = TestClient(_make_standalone_app())
        # %2e%2e is ".." percent-encoded - the exact shape the real
        # exploit used, since a literal ../ in a URL is commonly
        # normalized away by HTTP clients before the request is even
        # sent, while an encoded form survives to be decoded by the
        # server's own routing (uvicorn/Starlette) - see this module's
        # docstring.
        response = client.get("/%2e%2e/secret.txt")

    assert response.status_code == 200
    assert "TOP SECRET" not in response.text
    assert response.text == "<html>spa shell</html>"


def test_http_legitimate_asset_still_served(dist_dir):
    with patch("app.main.FRONTEND_DIST_DIR", dist_dir):
        client = TestClient(_make_standalone_app())
        response = client.get("/assets/something.js")

    assert response.status_code == 200
    assert response.text == "console.log('legit asset')"


def test_standalone_app_registration_never_touches_the_shared_app():
    """Confirms the isolation claim above - the real, shared app used by
    every other test in this suite must never end up with this route
    registered just because this test file imported/exercised
    serve_frontend."""
    from app.main import app as shared_app

    assert not any("full_path" in r.path for r in shared_app.routes)
