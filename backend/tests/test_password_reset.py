from datetime import datetime, timedelta

from app.email import last_email_to
from app.models import PasswordResetToken


def test_request_reset_for_existing_email_sends_email(client, make_user):
    make_user("alice")
    res = client.post("/api/account/password-reset/request", json={"email": "alice@example.com"})
    assert res.status_code == 200

    sent = last_email_to("alice@example.com")
    assert sent is not None
    assert sent["token"]


def test_request_reset_for_nonexistent_email_returns_identical_response(client, make_user):
    """No account-existence leak: the response body and status for a real
    account and a nonexistent one must be byte-identical."""
    make_user("alice")

    real_res = client.post("/api/account/password-reset/request", json={"email": "alice@example.com"})
    fake_res = client.post("/api/account/password-reset/request", json={"email": "nobody@example.com"})

    assert real_res.status_code == fake_res.status_code == 200
    assert real_res.json() == fake_res.json()
    assert last_email_to("nobody@example.com") is None


def test_reset_password_with_valid_token_changes_password(client, make_user):
    make_user("alice", password="oldpassword123")
    client.post("/api/account/password-reset/request", json={"email": "alice@example.com"})
    token = last_email_to("alice@example.com")["token"]

    reset_res = client.post(f"/api/account/password-reset/{token}", json={"new_password": "newpassword456"})
    assert reset_res.status_code == 200

    old_login = client.post("/api/sessions", json={"username": "alice", "password": "oldpassword123"})
    assert old_login.status_code == 401

    new_login = client.post("/api/sessions", json={"username": "alice", "password": "newpassword456"})
    assert new_login.status_code == 201


def test_reset_token_works_only_once(client, make_user):
    make_user("alice", password="oldpassword123")
    client.post("/api/account/password-reset/request", json={"email": "alice@example.com"})
    token = last_email_to("alice@example.com")["token"]

    first = client.post(f"/api/account/password-reset/{token}", json={"new_password": "newpassword456"})
    assert first.status_code == 200

    second = client.post(f"/api/account/password-reset/{token}", json={"new_password": "thirdpassword789"})
    assert second.status_code == 410


def test_reset_token_unknown_404(client):
    res = client.post("/api/account/password-reset/not-a-real-token", json={"new_password": "newpassword456"})
    assert res.status_code == 404


def test_reset_token_expired_returns_410(client, make_user, db_session):
    make_user("alice")
    client.post("/api/account/password-reset/request", json={"email": "alice@example.com"})
    token = last_email_to("alice@example.com")["token"]

    record = db_session.query(PasswordResetToken).filter_by(token=token).one()
    record.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db_session.commit()

    res = client.post(f"/api/account/password-reset/{token}", json={"new_password": "newpassword456"})
    assert res.status_code == 410


def test_new_reset_request_invalidates_earlier_tokens(client, make_user):
    """Only the most recently requested link should work - an older,
    still-unused reset email must stop working once a newer one is sent."""
    make_user("alice")
    client.post("/api/account/password-reset/request", json={"email": "alice@example.com"})
    old_token = last_email_to("alice@example.com")["token"]

    client.post("/api/account/password-reset/request", json={"email": "alice@example.com"})
    new_token = last_email_to("alice@example.com")["token"]
    assert new_token != old_token

    old_attempt = client.post(f"/api/account/password-reset/{old_token}", json={"new_password": "newpassword456"})
    assert old_attempt.status_code == 410

    new_attempt = client.post(f"/api/account/password-reset/{new_token}", json={"new_password": "newpassword456"})
    assert new_attempt.status_code == 200


def test_reset_password_too_short_rejected(client, make_user):
    make_user("alice")
    client.post("/api/account/password-reset/request", json={"email": "alice@example.com"})
    token = last_email_to("alice@example.com")["token"]

    res = client.post(f"/api/account/password-reset/{token}", json={"new_password": "short"})
    assert res.status_code == 422


def test_request_reset_wildcard_email_does_not_match_unrelated_account(client, make_user):
    """The core fix: User.email.ilike(payload.email) treated % and _ as SQL
    wildcards, and EmailStr doesn't reject them ("%@gmail.com" passes
    validation as a syntactically-plausible-looking address). An attacker
    could wildcard-match an arbitrary victim's real account this way,
    invalidating the victim's own pending reset tokens and triggering an
    unsolicited reset email to them. Comparing with == against the
    normalized column instead means a wildcard pattern simply doesn't
    equal anyone's real, literal email address.

    Registering already sends victim@example.com a verification email, so
    last_email_to for that address is never None to begin with - the
    assertion instead confirms the wildcard request didn't append a
    *newer* (reset) email on top of it."""
    make_user("victim")  # email victim@example.com
    before = last_email_to("victim@example.com")
    assert before is not None and before["subject"].startswith("Verify your email")

    res = client.post("/api/account/password-reset/request", json={"email": "%@example.com"})
    assert res.status_code == 200  # same generic response either way - no enumeration leak
    assert last_email_to("victim@example.com") == before


def test_request_reset_wildcard_with_matching_literal_substring_still_does_not_match(client, make_user):
    """A second wildcard shape - % anywhere in the local-part, not just as
    the whole thing - proving this isn't merely "a bare % is special-
    cased" but that ilike's wildcard semantics are gone entirely."""
    make_user("victim")  # email victim@example.com
    before = last_email_to("victim@example.com")

    res = client.post("/api/account/password-reset/request", json={"email": "%victim@example.com"})
    assert res.status_code == 200
    assert last_email_to("victim@example.com") == before


def test_request_reset_matches_regardless_of_requested_case(client, make_user):
    """Case-insensitivity itself must still work - == against the
    lowercase-normalized column, with the incoming value also lowered,
    rather than relying on ilike for that job."""
    make_user("alice")  # stored as alice@example.com (see register normalization)

    res = client.post("/api/account/password-reset/request", json={"email": "ALICE@EXAMPLE.COM"})
    assert res.status_code == 200
    assert last_email_to("alice@example.com") is not None


def test_request_reset_rate_limited_after_five_attempts_per_minute(client, make_user):
    make_user("alice")
    for _ in range(5):
        res = client.post("/api/account/password-reset/request", json={"email": "alice@example.com"})
        assert res.status_code == 200

    res = client.post("/api/account/password-reset/request", json={"email": "alice@example.com"})
    assert res.status_code == 429
