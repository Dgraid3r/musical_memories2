"""Rate limiting on the auth endpoints (login/register). The autouse
_reset_rate_limits fixture in conftest.py resets the limiter before every
test, so these don't interfere with each other or with the rest of the
suite's much lighter use of these same endpoints via make_user."""


def test_login_rate_limited_after_five_attempts_per_minute(client, make_user):
    # make_user itself performs one successful login, which counts toward
    # the same 5/minute budget - only 4 more are available before the limit.
    make_user("alice")

    for _ in range(4):
        res = client.post("/api/sessions", json={"username": "alice", "password": "wrong-password"})
        assert res.status_code == 401

    res = client.post("/api/sessions", json={"username": "alice", "password": "wrong-password"})
    assert res.status_code == 429
    assert "detail" in res.json()

    # Even the *correct* password is rejected once rate-limited - the limit
    # is per-caller, not "5 wrong guesses."
    res = client.post("/api/sessions", json={"username": "alice", "password": "password123"})
    assert res.status_code == 429


def test_register_rate_limited_after_five_attempts_per_minute(client):
    for i in range(5):
        res = client.post(
            "/api/users",
            json={"username": f"user{i}", "email": f"user{i}@example.com", "password": "password123"},
        )
        assert res.status_code == 201

    res = client.post(
        "/api/users",
        json={"username": "user5", "email": "user5@example.com", "password": "password123"},
    )
    assert res.status_code == 429


def test_login_and_register_have_independent_rate_limit_budgets(client, make_user):
    """make_user itself calls both register and login once for every test in
    this suite - this confirms hitting one endpoint's limit doesn't count
    against the other's, which the rest of the suite already relies on
    implicitly (many make_user calls per test file, well under 5 each, but
    never fewer than 1 of each)."""
    # Registered *before* exhausting the register budget below - this
    # itself uses 1 of the 5 register calls, so only 4 more are available.
    alice = make_user("alice")

    for i in range(4):
        res = client.post(
            "/api/users",
            json={"username": f"budget{i}", "email": f"budget{i}@example.com", "password": "password123"},
        )
        assert res.status_code == 201

    # Register is now exhausted, but login for an already-registered user
    # must still work - it's a different endpoint with its own budget.
    res = client.post("/api/sessions", json={"username": alice["username"], "password": "password123"})
    assert res.status_code == 201
