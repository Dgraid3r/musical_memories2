"""Regression coverage for the browser-enforced CORS allowlist (see
app.main._cors_allowed_origins).

This used to be a single hardcoded "http://localhost:5173", which
silently broke anonymous/browser access to GET /api/workspaces/public
(and everything else) from any other, equally legitimate local origin -
http://127.0.0.1:5173 instead of http://localhost:5173 (browsers treat
these as different origins), or `vite preview`'s default port 4173. The
failure was invisible to curl/pytest because CORS is enforced by the
browser reading the *response*, not by this server rejecting the
*request* - the handler still runs and still returns 200, just without
an Access-Control-Allow-Origin header the browser will accept, so the
page's own fetch() throws and (see PublicWorkspaceBrowser.tsx) that used
to render the exact same "No public journals found" empty state as
there really being nothing to browse.

These tests assert on the presence of that header for a real TestClient
request carrying an Origin header - the same signal an actual browser
depends on - rather than only unit-testing the origin list function, so
a future regression that includes an origin in the list but a middleware
config mistake still breaks CORS would also be caught here.
"""

import app.main as main_module


def test_default_vite_dev_origin_is_allowed(client):
    res = client.get("/api/workspaces/public", headers={"Origin": "http://localhost:5173"})
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_127_0_0_1_variant_of_the_dev_origin_is_allowed(client):
    """The exact regression this file exists for: 127.0.0.1 and localhost
    are different origins to a browser even though they're the same
    machine and the same Vite dev server - both must work."""
    res = client.get("/api/workspaces/public", headers={"Origin": "http://127.0.0.1:5173"})
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"


def test_vite_preview_ports_are_allowed_on_both_hosts(client):
    """`vite preview` (the closest local approximation to the real
    production build - see vite.config.ts's own `preview.proxy` comment)
    defaults to port 4173, not the dev server's 5173."""
    for origin in ("http://localhost:4173", "http://127.0.0.1:4173"):
        res = client.get("/api/workspaces/public", headers={"Origin": origin})
        assert res.status_code == 200
        assert res.headers.get("access-control-allow-origin") == origin


def test_an_unlisted_origin_gets_no_cors_header(client):
    """Confirms the test actually distinguishes allowed from disallowed
    origins - i.e. that a passing test above isn't just FastAPI/Starlette
    echoing back whatever Origin it's given regardless of the allowlist."""
    res = client.get("/api/workspaces/public", headers={"Origin": "http://evil.example.com"})
    assert res.status_code == 200
    assert "access-control-allow-origin" not in res.headers


def test_cors_allowed_origins_reads_frontend_url_and_extra_origins(monkeypatch):
    """Unit-level coverage of the configurable pieces. _cors_allowed_origins()
    reads os.environ fresh on every call (it isn't memoized - only its
    one call site at module import time is fixed), so this can exercise
    it directly with monkeypatched env vars without reloading app.main or
    rebuilding the FastAPI app/its middleware stack."""
    monkeypatch.setenv("FRONTEND_URL", "https://memories.example.com")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://192.168.1.23:5173, https://staging.example.com")

    origins = set(main_module._cors_allowed_origins())

    assert "https://memories.example.com" in origins
    assert "http://192.168.1.23:5173" in origins
    assert "https://staging.example.com" in origins
    # The always-on local dev defaults must still be present alongside
    # whatever FRONTEND_URL/CORS_ALLOWED_ORIGINS add.
    assert "http://localhost:5173" in origins
    assert "http://127.0.0.1:5173" in origins
    assert "http://localhost:4173" in origins
    assert "http://127.0.0.1:4173" in origins
