def test_login_succeeds_with_correct_credentials(client, make_user):
    make_user("alice", password="password123")
    res = client.post("/api/sessions", json={"username": "alice", "password": "password123"})
    assert res.status_code == 201
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_login_fails_with_wrong_password(client, make_user):
    make_user("alice", password="password123")
    res = client.post("/api/sessions", json={"username": "alice", "password": "wrong-password"})
    assert res.status_code == 401


def test_login_fails_for_unknown_user(client):
    res = client.post("/api/sessions", json={"username": "ghost", "password": "password123"})
    assert res.status_code == 401


def test_protected_endpoint_rejects_missing_token(client):
    res = client.get("/api/users/me")
    assert res.status_code == 401


def test_protected_endpoint_rejects_garbage_token(client):
    res = client.get("/api/users/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert res.status_code == 401


def test_protected_endpoint_rejects_token_for_deleted_user(client, make_user):
    # A token stays structurally valid even if the user it names no longer
    # exists; the dependency should still reject it rather than 500.
    from app import auth

    token = auth.create_access_token(user_id=999999)
    res = client.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
