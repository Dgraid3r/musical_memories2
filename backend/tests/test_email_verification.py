from datetime import datetime, timedelta

from app.email import last_email_to
from app.models import EmailVerificationToken


def test_registration_sends_verification_email(client, make_user):
    make_user("alice")
    sent = last_email_to("alice@example.com")
    assert sent is not None
    assert sent["token"]


def test_new_user_starts_unverified(client, make_user):
    alice = make_user("alice")
    res = client.get("/api/users/me", headers=alice["headers"])
    assert res.status_code == 200
    assert res.json()["email_verified"] is False


def test_unverified_user_is_not_blocked_from_normal_use(client, make_user):
    """This is the one to be careful not to accidentally break: an
    unverified account must be able to log in and use the app - create a
    workspace, create an entry - exactly like a verified one."""
    alice = make_user("alice")
    assert client.get("/api/users/me", headers=alice["headers"]).json()["email_verified"] is False

    ws_res = client.post("/api/workspaces", headers=alice["headers"], json={"name": "My Workspace"})
    assert ws_res.status_code == 201
    ws = ws_res.json()

    entry_res = client.post(
        f"/api/workspaces/{ws['id']}/entries",
        headers=alice["headers"],
        data={
            "start_date": "2026-01-01",
            "playlist_id": "p1",
            "playlist_name": "T",
            "playlist_url": "https://open.spotify.com/playlist/p1",
        },
    )
    assert entry_res.status_code == 201

    list_res = client.get(f"/api/workspaces/{ws['id']}/entries", headers=alice["headers"])
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1


def test_verify_email_with_valid_token_succeeds(client, make_user):
    alice = make_user("alice")
    token = last_email_to("alice@example.com")["token"]

    res = client.post(f"/api/account/verify-email/{token}")
    assert res.status_code == 200
    assert res.json()["email_verified"] is True

    me = client.get("/api/users/me", headers=alice["headers"])
    assert me.json()["email_verified"] is True


def test_verify_email_token_works_only_once(client, make_user):
    alice = make_user("alice")
    token = last_email_to("alice@example.com")["token"]

    first = client.post(f"/api/account/verify-email/{token}")
    assert first.status_code == 200

    second = client.post(f"/api/account/verify-email/{token}")
    assert second.status_code == 404


def test_verify_email_unknown_token_404(client):
    res = client.post("/api/account/verify-email/not-a-real-token")
    assert res.status_code == 404


def test_verify_email_expired_token_returns_410(client, make_user, db_session):
    alice = make_user("alice")
    token = last_email_to("alice@example.com")["token"]

    record = db_session.query(EmailVerificationToken).filter_by(token=token).one()
    record.expires_at = datetime.utcnow() - timedelta(hours=1)
    db_session.commit()

    res = client.post(f"/api/account/verify-email/{token}")
    assert res.status_code == 410


def test_resend_verification_requires_auth(client):
    res = client.post("/api/account/verify-email/resend")
    assert res.status_code == 401


def test_resend_verification_sends_a_new_usable_token(client, make_user):
    alice = make_user("alice")
    original_token = last_email_to("alice@example.com")["token"]

    resend_res = client.post("/api/account/verify-email/resend", headers=alice["headers"])
    assert resend_res.status_code == 200
    assert resend_res.json()["detail"] == "Verification email sent."

    new_token = last_email_to("alice@example.com")["token"]
    assert new_token != original_token

    # The old token no longer works - resend replaces it rather than
    # allowing either token to independently verify.
    old_attempt = client.post(f"/api/account/verify-email/{original_token}")
    assert old_attempt.status_code == 404

    new_attempt = client.post(f"/api/account/verify-email/{new_token}")
    assert new_attempt.status_code == 200


def test_resend_verification_when_already_verified_is_friendly_not_an_error(client, make_user):
    alice = make_user("alice")
    token = last_email_to("alice@example.com")["token"]
    client.post(f"/api/account/verify-email/{token}")

    res = client.post("/api/account/verify-email/resend", headers=alice["headers"])
    assert res.status_code == 200
    assert "already verified" in res.json()["detail"].lower()


def test_resend_verification_rate_limited_after_five_attempts_per_minute(client, make_user):
    alice = make_user("alice")
    for _ in range(5):
        res = client.post("/api/account/verify-email/resend", headers=alice["headers"])
        assert res.status_code == 200

    res = client.post("/api/account/verify-email/resend", headers=alice["headers"])
    assert res.status_code == 429
