from datetime import datetime, timedelta

from app.email import last_email_to
from app.models import WorkspaceInvite


def _create_invite(client, owner, workspace, email, role="member"):
    res = client.post(
        f"/api/workspaces/{workspace['id']}/invites", headers=owner["headers"], json={"email": email, "role": role}
    )
    assert res.status_code == 201, res.text
    return res.json()


def _token_for(email):
    sent = last_email_to(email)
    assert sent is not None, f"no email recorded for {email}"
    return sent["token"]


# --- Creating invites ------------------------------------------------------


def test_create_invite_owner_only(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)

    res = client.post(
        f"/api/workspaces/{ws['id']}/invites", headers=bob["headers"], json={"email": "carol@example.com"}
    )
    assert res.status_code == 403


def test_create_invite_not_a_member_returns_404(client, make_user, make_workspace):
    alice = make_user("alice")
    outsider = make_user("outsider")
    ws = make_workspace(alice)

    res = client.post(
        f"/api/workspaces/{ws['id']}/invites", headers=outsider["headers"], json={"email": "carol@example.com"}
    )
    assert res.status_code == 404


def test_create_invite_sends_an_email(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)

    _create_invite(client, alice, ws, "carol@example.com")

    sent = last_email_to("carol@example.com")
    assert sent is not None
    assert ws["name"] in sent["body"]
    assert sent["token"]


def test_create_invite_response_never_includes_the_token(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)

    res = client.post(
        f"/api/workspaces/{ws['id']}/invites", headers=alice["headers"], json={"email": "carol@example.com"}
    )
    assert res.status_code == 201
    assert set(res.json().keys()) == {"id", "email", "role", "created_at", "expires_at"}


def test_create_invite_for_existing_member_conflicts(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)

    res = client.post(
        f"/api/workspaces/{ws['id']}/invites", headers=alice["headers"], json={"email": bob["email"]}
    )
    assert res.status_code == 409


def test_create_duplicate_pending_invite_conflicts(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    _create_invite(client, alice, ws, "carol@example.com")

    res = client.post(
        f"/api/workspaces/{ws['id']}/invites", headers=alice["headers"], json={"email": "carol@example.com"}
    )
    assert res.status_code == 409


def test_create_invite_wildcard_email_does_not_false_match_existing_member(client, make_user, make_workspace):
    """Same ilike-wildcard-injection root cause as account.py's password
    reset (see test_password_reset.py's wildcard tests): User.email.ilike
    treated % and _ as SQL wildcards, and WorkspaceInviteCreate.email
    (also EmailStr) doesn't reject them. A wildcard-shaped invite email
    could previously false-match an unrelated existing member and
    spuriously 409. Comparing with == against the normalized column
    means it no longer can."""
    alice = make_user("alice")
    bob = make_user("bob")  # bob@example.com - already a member, not the invitee
    ws = make_workspace(alice, bob)

    res = client.post(
        f"/api/workspaces/{ws['id']}/invites", headers=alice["headers"], json={"email": "%@example.com"}
    )
    assert res.status_code == 201


def test_create_invite_wildcard_email_does_not_false_match_pending_invite(client, make_user, make_workspace):
    """Same fix, the other lookup in create_invite: a wildcard-shaped
    email must not false-match an unrelated already-pending invite
    either."""
    alice = make_user("alice")
    ws = make_workspace(alice)
    _create_invite(client, alice, ws, "carol@example.com")

    res = client.post(
        f"/api/workspaces/{ws['id']}/invites", headers=alice["headers"], json={"email": "%@example.com"}
    )
    assert res.status_code == 201


def test_create_invite_invalid_role_rejected(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)

    res = client.post(
        f"/api/workspaces/{ws['id']}/invites",
        headers=alice["headers"],
        json={"email": "carol@example.com", "role": "owner"},
    )
    assert res.status_code == 422


# --- Listing and revoking invites ------------------------------------------


def test_list_invites_owner_only(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    _create_invite(client, alice, ws, "carol@example.com")

    res = client.get(f"/api/workspaces/{ws['id']}/invites", headers=bob["headers"])
    assert res.status_code == 403


def test_list_invites_shows_pending_only(client, make_user, make_workspace):
    alice = make_user("alice")
    carol = make_user("carol")
    ws = make_workspace(alice)
    _create_invite(client, alice, ws, "dave@example.com")
    _create_invite(client, alice, ws, carol["email"])

    accept_res = client.post(f"/api/invites/{_token_for(carol['email'])}/accept", headers=carol["headers"])
    assert accept_res.status_code == 200

    res = client.get(f"/api/workspaces/{ws['id']}/invites", headers=alice["headers"])
    assert res.status_code == 200
    emails = {i["email"] for i in res.json()}
    assert emails == {"dave@example.com"}


def test_revoke_invite_owner_only(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    invite = _create_invite(client, alice, ws, "carol@example.com")

    res = client.delete(f"/api/workspaces/{ws['id']}/invites/{invite['id']}", headers=bob["headers"])
    assert res.status_code == 403


def test_revoked_invite_cannot_be_accepted(client, make_user, make_workspace):
    alice = make_user("alice")
    carol = make_user("carol")
    ws = make_workspace(alice)
    invite = _create_invite(client, alice, ws, carol["email"])
    token = _token_for(carol["email"])

    revoke_res = client.delete(f"/api/workspaces/{ws['id']}/invites/{invite['id']}", headers=alice["headers"])
    assert revoke_res.status_code == 204

    accept_res = client.post(f"/api/invites/{token}/accept", headers=carol["headers"])
    assert accept_res.status_code == 410


# --- Accepting as an existing user ------------------------------------------


def test_accept_invite_requires_auth(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    _create_invite(client, alice, ws, "carol@example.com")

    res = client.post(f"/api/invites/{_token_for('carol@example.com')}/accept")
    assert res.status_code == 401


def test_accept_invite_creates_membership_with_invited_role(client, make_user, make_workspace):
    alice = make_user("alice")
    carol = make_user("carol")
    ws = make_workspace(alice)
    _create_invite(client, alice, ws, carol["email"], role="member")

    res = client.post(f"/api/invites/{_token_for(carol['email'])}/accept", headers=carol["headers"])
    assert res.status_code == 200
    assert res.json() == {"user_id": carol["id"], "username": "carol", "role": "member"}

    members = client.get(f"/api/workspaces/{ws['id']}/members", headers=alice["headers"]).json()
    assert {"user_id": carol["id"], "username": "carol", "role": "member"} in members


def test_accept_invite_with_subscriber_role_lands_as_subscriber(client, make_user, make_workspace):
    """A subscriber-role invite must land the invitee with subscriber
    permissions, not member - confirmed both via the response and by
    actually being denied a write action afterward."""
    alice = make_user("alice")
    carol = make_user("carol")
    ws = make_workspace(alice)
    _create_invite(client, alice, ws, carol["email"], role="subscriber")

    res = client.post(f"/api/invites/{_token_for(carol['email'])}/accept", headers=carol["headers"])
    assert res.status_code == 200
    assert res.json()["role"] == "subscriber"

    create_res = client.post(
        f"/api/workspaces/{ws['id']}/entries",
        headers=carol["headers"],
        data={
            "start_date": "2026-01-01",
            "playlist_id": "p1",
            "playlist_name": "T",
            "playlist_url": "https://open.spotify.com/playlist/p1",
        },
    )
    assert create_res.status_code == 403


def test_accept_invite_wrong_email_forbidden(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    _create_invite(client, alice, ws, "carol@example.com")

    res = client.post(f"/api/invites/{_token_for('carol@example.com')}/accept", headers=bob["headers"])
    assert res.status_code == 403


def test_accept_invite_not_found(client, make_user):
    alice = make_user("alice")
    res = client.post("/api/invites/not-a-real-token/accept", headers=alice["headers"])
    assert res.status_code == 404


def test_accept_invite_already_accepted(client, make_user, make_workspace):
    alice = make_user("alice")
    carol = make_user("carol")
    ws = make_workspace(alice)
    _create_invite(client, alice, ws, carol["email"])
    token = _token_for(carol["email"])

    first = client.post(f"/api/invites/{token}/accept", headers=carol["headers"])
    assert first.status_code == 200

    second = client.post(f"/api/invites/{token}/accept", headers=carol["headers"])
    assert second.status_code == 410


def test_accept_expired_invite_returns_clean_error_not_a_crash(client, make_user, make_workspace, db_session):
    alice = make_user("alice")
    carol = make_user("carol")
    ws = make_workspace(alice)
    _create_invite(client, alice, ws, carol["email"])
    token = _token_for(carol["email"])

    invite = db_session.query(WorkspaceInvite).filter_by(token=token).one()
    invite.expires_at = datetime.utcnow() - timedelta(days=1)
    db_session.commit()

    res = client.post(f"/api/invites/{token}/accept", headers=carol["headers"])
    assert res.status_code == 410
    assert "expired" in res.json()["detail"].lower()


def test_accept_invite_rate_limited_after_five_attempts_per_minute(client, make_user, make_workspace):
    alice = make_user("alice")
    carol = make_user("carol")
    ws = make_workspace(alice)
    _create_invite(client, alice, ws, carol["email"])
    bad_token = "wrong-token"

    for _ in range(5):
        res = client.post(f"/api/invites/{bad_token}/accept", headers=carol["headers"])
        assert res.status_code == 404

    res = client.post(f"/api/invites/{bad_token}/accept", headers=carol["headers"])
    assert res.status_code == 429


# --- Preview endpoint (no auth) ---------------------------------------------


def test_preview_invite_requires_no_auth(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    _create_invite(client, alice, ws, "carol@example.com", role="subscriber")

    res = client.get(f"/api/invites/{_token_for('carol@example.com')}")
    assert res.status_code == 200
    body = res.json()
    assert body["workspace_id"] == ws["id"]
    assert body["workspace_name"] == ws["name"]
    assert body["email"] == "carol@example.com"
    assert body["role"] == "subscriber"
    assert body["account_exists"] is False


def test_preview_invite_reports_account_exists_for_known_email(client, make_user, make_workspace):
    alice = make_user("alice")
    carol = make_user("carol")
    ws = make_workspace(alice)
    _create_invite(client, alice, ws, carol["email"])

    res = client.get(f"/api/invites/{_token_for(carol['email'])}")
    assert res.status_code == 200
    assert res.json()["account_exists"] is True


def test_preview_unknown_token_404(client):
    res = client.get("/api/invites/not-a-real-token")
    assert res.status_code == 404


def test_preview_expired_invite_returns_410(client, make_user, make_workspace, db_session):
    alice = make_user("alice")
    ws = make_workspace(alice)
    _create_invite(client, alice, ws, "carol@example.com")
    token = _token_for("carol@example.com")

    invite = db_session.query(WorkspaceInvite).filter_by(token=token).one()
    invite.expires_at = datetime.utcnow() - timedelta(days=1)
    db_session.commit()

    res = client.get(f"/api/invites/{token}")
    assert res.status_code == 410


# --- Accepting via registration (no existing account) -----------------------


def test_register_with_matching_invite_token_joins_workspace_automatically(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    _create_invite(client, alice, ws, "dave@example.com", role="member")
    token = _token_for("dave@example.com")

    register_res = client.post(
        "/api/users",
        json={
            "username": "dave",
            "email": "dave@example.com",
            "password": "password123",
            "invite_token": token,
        },
    )
    assert register_res.status_code == 201

    login_res = client.post("/api/sessions", json={"username": "dave", "password": "password123"})
    dave_headers = {"Authorization": f"Bearer {login_res.json()['access_token']}"}

    workspaces = client.get("/api/workspaces", headers=dave_headers).json()
    assert any(w["id"] == ws["id"] and w["role"] == "member" for w in workspaces)


def test_register_with_invite_token_for_subscriber_role_joins_as_subscriber(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    _create_invite(client, alice, ws, "dave@example.com", role="subscriber")
    token = _token_for("dave@example.com")

    client.post(
        "/api/users",
        json={"username": "dave", "email": "dave@example.com", "password": "password123", "invite_token": token},
    )
    login_res = client.post("/api/sessions", json={"username": "dave", "password": "password123"})
    dave_headers = {"Authorization": f"Bearer {login_res.json()['access_token']}"}

    workspaces = client.get("/api/workspaces", headers=dave_headers).json()
    assert any(w["id"] == ws["id"] and w["role"] == "subscriber" for w in workspaces)


def test_register_with_invite_token_for_different_email_does_not_join(client, make_user, make_workspace):
    """The invite link was for dave@example.com; registering a different
    email with that token must not silently join the workspace, and must
    not block registration either."""
    alice = make_user("alice")
    ws = make_workspace(alice)
    _create_invite(client, alice, ws, "dave@example.com")
    token = _token_for("dave@example.com")

    register_res = client.post(
        "/api/users",
        json={
            "username": "eve",
            "email": "eve@example.com",
            "password": "password123",
            "invite_token": token,
        },
    )
    assert register_res.status_code == 201

    login_res = client.post("/api/sessions", json={"username": "eve", "password": "password123"})
    eve_headers = {"Authorization": f"Bearer {login_res.json()['access_token']}"}

    workspaces = client.get("/api/workspaces", headers=eve_headers).json()
    assert workspaces == []


def test_register_with_expired_invite_token_still_succeeds(client, make_user, make_workspace, db_session):
    alice = make_user("alice")
    ws = make_workspace(alice)
    _create_invite(client, alice, ws, "dave@example.com")
    token = _token_for("dave@example.com")

    invite = db_session.query(WorkspaceInvite).filter_by(token=token).one()
    invite.expires_at = datetime.utcnow() - timedelta(days=1)
    db_session.commit()

    register_res = client.post(
        "/api/users",
        json={
            "username": "dave",
            "email": "dave@example.com",
            "password": "password123",
            "invite_token": token,
        },
    )
    assert register_res.status_code == 201


def test_register_with_garbage_invite_token_still_succeeds(client):
    res = client.post(
        "/api/users",
        json={
            "username": "frank",
            "email": "frank@example.com",
            "password": "password123",
            "invite_token": "not-a-real-token",
        },
    )
    assert res.status_code == 201
