def test_register_creates_user(client):
    res = client.post(
        "/api/users",
        json={"username": "alice", "email": "alice@example.com", "password": "password123"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["username"] == "alice"
    assert body["email"] == "alice@example.com"
    assert "password" not in body
    assert "hashed_password" not in body


def test_register_duplicate_username_conflicts(client):
    client.post(
        "/api/users",
        json={"username": "alice", "email": "alice@example.com", "password": "password123"},
    )
    res = client.post(
        "/api/users",
        json={"username": "alice", "email": "different@example.com", "password": "password123"},
    )
    assert res.status_code == 409


def test_register_duplicate_email_conflicts(client):
    client.post(
        "/api/users",
        json={"username": "alice", "email": "alice@example.com", "password": "password123"},
    )
    res = client.post(
        "/api/users",
        json={"username": "someoneelse", "email": "alice@example.com", "password": "password123"},
    )
    assert res.status_code == 409


def test_register_normalizes_email_to_lowercase(client):
    """Emails are stored lowercase (see routers/users.register) so every
    later exact-match lookup - login-adjacent flows, password reset,
    Google sign-in linking, invite matching - can compare with a plain ==
    instead of relying on ilike as a case-insensitivity workaround."""
    res = client.post(
        "/api/users",
        json={"username": "mixedcase", "email": "MixedCase@Example.COM", "password": "password123"},
    )
    assert res.status_code == 201
    assert res.json()["email"] == "mixedcase@example.com"


def test_register_duplicate_email_different_case_conflicts(client):
    """Before email normalization, "Alice@x.com" and "alice@x.com" could
    both register successfully as if they were different addresses - a
    real inconsistency (User.email's unique constraint is itself
    case-sensitive) that made later lookups nondeterministic. Normalizing
    on write closes that: these two must now be treated as the same
    address."""
    first = client.post(
        "/api/users",
        json={"username": "alice", "email": "Alice@Example.com", "password": "password123"},
    )
    assert first.status_code == 201

    second = client.post(
        "/api/users",
        json={"username": "alice2", "email": "ALICE@EXAMPLE.COM", "password": "password123"},
    )
    assert second.status_code == 409


def test_register_short_password_rejected(client):
    res = client.post(
        "/api/users",
        json={"username": "alice", "email": "alice@example.com", "password": "short"},
    )
    assert res.status_code == 422


def test_register_invalid_email_rejected(client):
    res = client.post(
        "/api/users",
        json={"username": "alice", "email": "not-an-email", "password": "password123"},
    )
    assert res.status_code == 422


def test_register_invalid_username_rejected(client):
    res = client.post(
        "/api/users",
        json={"username": "has spaces", "email": "alice@example.com", "password": "password123"},
    )
    assert res.status_code == 422


def test_me_requires_auth(client):
    res = client.get("/api/users/me")
    assert res.status_code == 401


def test_me_returns_current_user(client, make_user):
    user = make_user("alice")
    res = client.get("/api/users/me", headers=user["headers"])
    assert res.status_code == 200
    assert res.json()["username"] == "alice"


# --- User search (co-author picker) --------------------------------------


def test_search_requires_auth(client, make_user):
    make_user("alice")
    res = client.get("/api/users?q=ali")
    assert res.status_code == 401


def test_search_finds_partial_username_match(client, make_user):
    make_user("alice")
    bob = make_user("bob")

    res = client.get("/api/users?q=ali", headers=bob["headers"])
    assert res.status_code == 200
    usernames = [u["username"] for u in res.json()]
    assert usernames == ["alice"]


def test_search_excludes_self(client, make_user):
    alice = make_user("alice")
    make_user("alicia")

    res = client.get("/api/users?q=ali", headers=alice["headers"])
    usernames = {u["username"] for u in res.json()}
    assert usernames == {"alicia"}


def test_search_does_not_leak_email(client, make_user):
    make_user("alice")
    bob = make_user("bob")

    res = client.get("/api/users?q=ali", headers=bob["headers"])
    assert res.status_code == 200
    for user in res.json():
        assert "email" not in user
        assert set(user.keys()) == {"id", "username"}


def test_search_no_match_returns_empty_list(client, make_user):
    alice = make_user("alice")
    res = client.get("/api/users?q=nonexistent-xyz", headers=alice["headers"])
    assert res.status_code == 200
    assert res.json() == []


def test_search_requires_nonempty_query(client, make_user):
    alice = make_user("alice")
    res = client.get("/api/users?q=", headers=alice["headers"])
    assert res.status_code == 422
