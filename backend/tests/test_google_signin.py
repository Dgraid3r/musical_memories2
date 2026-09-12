from unittest.mock import MagicMock, patch

from sqlalchemy import select

from app import auth
from app.auth import verify_password
from app.google_oauth import GoogleIdentity, GoogleSignInUnavailable, GoogleTokenInvalid, is_configured
from app.models import User
from app.routers.google_auth import GOOGLE_SIGNIN_NONCE_COOKIE


def _valid_state_and_cookies(nonce: str = "test-nonce") -> tuple[str, dict[str, str]]:
    """A create_signin_state token plus the matching cookie dict the real
    /login endpoint would have set on the browser making this request -
    verify_signin_state now requires both to agree (see auth.py), so any
    test that needs a signin state the callback will actually accept uses
    this rather than calling create_signin_state directly."""
    return auth.create_signin_state(nonce), {GOOGLE_SIGNIN_NONCE_COOKIE: nonce}

# --- google_oauth.exchange_code_for_identity (unit-level) ------------------
#
# Mocks requests.post (the code<->token exchange) and
# google_id_token.verify_oauth2_token (the ID token signature/claims
# verification itself) - a real Google-signed token can't be faked in a
# test, so the failure paths are tested by making the mocked verifier
# behave the way the real one would on a bad token (raising), proving this
# module actually refuses in that case rather than skipping the check.


def _fake_token_response(id_token="fake.jwt.token"):
    fake_response = MagicMock()
    fake_response.json.return_value = {"id_token": id_token, "access_token": "unused", "expires_in": 3600}
    fake_response.raise_for_status.return_value = None
    return fake_response


def _fake_claims(**overrides):
    claims = {
        "sub": "1234567890",
        "email": "alice@gmail.com",
        "email_verified": True,
        "iss": "https://accounts.google.com",
        "aud": "test-google-client-id",
    }
    claims.update(overrides)
    return claims


def test_exchange_code_for_identity_success():
    from app.google_oauth import exchange_code_for_identity

    with patch("app.google_oauth.requests.post", return_value=_fake_token_response()), patch(
        "app.google_oauth.google_id_token.verify_oauth2_token", return_value=_fake_claims()
    ):
        identity = exchange_code_for_identity("auth-code")

    assert identity == GoogleIdentity(sub="1234567890", email="alice@gmail.com")


def test_exchange_code_for_identity_rejects_unverified_email():
    from app.google_oauth import exchange_code_for_identity

    with patch("app.google_oauth.requests.post", return_value=_fake_token_response()), patch(
        "app.google_oauth.google_id_token.verify_oauth2_token", return_value=_fake_claims(email_verified=False)
    ):
        try:
            exchange_code_for_identity("auth-code")
            assert False, "expected GoogleTokenInvalid"
        except GoogleTokenInvalid:
            pass


def test_exchange_code_for_identity_rejects_wrong_issuer():
    from app.google_oauth import exchange_code_for_identity

    with patch("app.google_oauth.requests.post", return_value=_fake_token_response()), patch(
        "app.google_oauth.google_id_token.verify_oauth2_token",
        return_value=_fake_claims(iss="https://evil.example.com"),
    ):
        try:
            exchange_code_for_identity("auth-code")
            assert False, "expected GoogleTokenInvalid"
        except GoogleTokenInvalid:
            pass


def test_exchange_code_for_identity_rejects_when_verifier_raises():
    """The real failure path a tampered/invalid/expired ID token takes:
    google.oauth2.id_token.verify_oauth2_token itself raises (bad
    signature, expired, wrong audience, etc.) - this must surface as
    GoogleTokenInvalid, not propagate the library's raw exception or
    (worse) get swallowed and treated as success."""
    from app.google_oauth import exchange_code_for_identity

    with patch("app.google_oauth.requests.post", return_value=_fake_token_response()), patch(
        "app.google_oauth.google_id_token.verify_oauth2_token",
        side_effect=ValueError("Token used too early, 123 < 456"),
    ):
        try:
            exchange_code_for_identity("auth-code")
            assert False, "expected GoogleTokenInvalid"
        except GoogleTokenInvalid:
            pass


def test_exchange_code_for_identity_missing_id_token_in_token_response():
    from app.google_oauth import exchange_code_for_identity

    fake_response = MagicMock()
    fake_response.json.return_value = {"access_token": "unused", "expires_in": 3600}  # no id_token
    fake_response.raise_for_status.return_value = None

    with patch("app.google_oauth.requests.post", return_value=fake_response):
        try:
            exchange_code_for_identity("auth-code")
            assert False, "expected GoogleTokenInvalid"
        except GoogleTokenInvalid:
            pass


def test_exchange_code_for_identity_token_endpoint_unreachable():
    import requests

    from app.google_oauth import exchange_code_for_identity

    with patch("app.google_oauth.requests.post", side_effect=requests.ConnectionError("boom")):
        try:
            exchange_code_for_identity("auth-code")
            assert False, "expected GoogleSignInUnavailable"
        except GoogleSignInUnavailable:
            pass


def test_is_configured_true_with_env_set():
    assert is_configured() is True


def test_is_configured_false_when_env_unset(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    assert is_configured() is False


# --- GET /api/auth/google/config --------------------------------------------


def test_google_config_reports_enabled_by_default(client):
    res = client.get("/api/auth/google/config")
    assert res.status_code == 200
    assert res.json() == {"enabled": True}


def test_google_config_reports_disabled_when_not_configured(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    res = client.get("/api/auth/google/config")
    assert res.status_code == 200
    assert res.json() == {"enabled": False}


# --- GET /api/auth/google/login ---------------------------------------------


def test_google_login_redirects_to_google_authorize_url(client):
    with patch("app.routers.google_auth.build_authorize_url", return_value="https://accounts.google.com/o/oauth2/v2/auth?x=1"):
        res = client.get("/api/auth/google/login", follow_redirects=False)
    assert res.status_code in (302, 307)
    assert res.headers["location"] == "https://accounts.google.com/o/oauth2/v2/auth?x=1"


def test_google_login_state_is_verifiable_signin_state(client):
    captured = {}

    def fake_build_authorize_url(state):
        captured["state"] = state
        return "https://accounts.google.com/o/oauth2/v2/auth"

    with patch("app.routers.google_auth.build_authorize_url", side_effect=fake_build_authorize_url):
        res = client.get("/api/auth/google/login", follow_redirects=False)

    assert res.status_code in (302, 307)
    cookie_nonce = res.cookies.get(GOOGLE_SIGNIN_NONCE_COOKIE)
    assert cookie_nonce is not None
    assert auth.verify_signin_state(captured["state"], cookie_nonce) is True


def test_google_login_returns_503_when_not_configured(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    res = client.get("/api/auth/google/login", follow_redirects=False)
    assert res.status_code == 503


# --- GET /api/auth/google/callback: state/CSRF verification ----------------


def test_google_callback_denied_redirects_with_flag(client):
    res = client.get("/api/auth/google/callback?error=access_denied", follow_redirects=False)
    assert res.status_code in (302, 307)
    assert "google=denied" in res.headers["location"]


def test_google_callback_missing_code_or_state_rejected(client):
    res = client.get("/api/auth/google/callback", follow_redirects=False)
    assert res.status_code in (302, 307)
    assert "google=invalid_state" in res.headers["location"]

    res = client.get("/api/auth/google/callback?code=abc", follow_redirects=False)
    assert res.status_code in (302, 307)
    assert "google=invalid_state" in res.headers["location"]


def test_google_callback_forged_state_rejected_and_creates_no_account(client, db_session):
    before_count = db_session.query(User).count()

    res = client.get("/api/auth/google/callback?code=abc&state=not-a-real-token", follow_redirects=False)

    assert res.status_code in (302, 307)
    assert "google=invalid_state" in res.headers["location"]
    assert db_session.query(User).count() == before_count


def test_google_callback_rejects_state_from_a_different_purpose(client, make_user):
    """A regular access token, or Spotify's own oauth_state, is a validly
    -signed JWT too, but was never meant to authorize this callback - the
    "purpose" claim must gate it, exactly like Spotify's callback already
    defends against the mirror-image confusion."""
    alice = make_user("alice")
    access_token = auth.create_access_token(alice["id"])
    spotify_state = auth.create_oauth_state(alice["id"])

    for forged_state in (access_token, spotify_state):
        res = client.get(f"/api/auth/google/callback?code=abc&state={forged_state}", follow_redirects=False)
        assert res.status_code in (302, 307)
        assert "google=invalid_state" in res.headers["location"]


def test_google_callback_expired_state_rejected(client):
    from datetime import datetime, timedelta

    with patch("app.auth.datetime") as mock_dt:
        mock_dt.now.return_value = datetime.now(auth.timezone.utc) - timedelta(minutes=20)
        state, cookies = _valid_state_and_cookies()

    res = client.get(f"/api/auth/google/callback?code=abc&state={state}", cookies=cookies, follow_redirects=False)
    assert res.status_code in (302, 307)
    assert "google=invalid_state" in res.headers["location"]


def test_google_callback_token_exchange_unavailable_redirects_with_flag(client):
    state, cookies = _valid_state_and_cookies()
    with patch("app.routers.google_auth.exchange_code_for_identity", side_effect=GoogleSignInUnavailable("x")):
        res = client.get(f"/api/auth/google/callback?code=abc&state={state}", cookies=cookies, follow_redirects=False)
    assert res.status_code in (302, 307)
    assert "google=unavailable" in res.headers["location"]


def test_google_callback_invalid_token_redirects_with_flag(client):
    """The router-level contract for the "tampered/invalid ID token"
    failure path - proven at the unit level above that exchange_code_for_
    identity itself raises; this confirms the callback turns that into a
    clean redirect flag rather than a 500."""
    state, cookies = _valid_state_and_cookies()
    with patch("app.routers.google_auth.exchange_code_for_identity", side_effect=GoogleTokenInvalid("bad token")):
        res = client.get(f"/api/auth/google/callback?code=abc&state={state}", cookies=cookies, follow_redirects=False)
    assert res.status_code in (302, 307)
    assert "google=invalid_token" in res.headers["location"]


# --- GET /api/auth/google/callback: CSRF nonce-cookie binding ---------------


def test_google_callback_state_with_no_cookie_at_all_rejected(client):
    """The core CSRF fix: a validly-signed, unexpired, correct-purpose
    state token is *not* enough on its own - see auth.verify_signin_state.
    Without the matching cookie, this must be rejected exactly like any
    other invalid state, never treated as good just because the signature
    checks out."""
    state = auth.create_signin_state("real-nonce")
    res = client.get(f"/api/auth/google/callback?code=abc&state={state}", follow_redirects=False)
    assert res.status_code in (302, 307)
    assert "google=invalid_state" in res.headers["location"]


def test_google_callback_state_with_mismatched_cookie_rejected(client, db_session):
    """The actual attack this closes: an attacker completes their own
    sign-in to obtain a validly-signed state (bound to *their* nonce
    cookie), then gets a victim's browser to hit the callback with the
    attacker's code/state but the victim's own (different) nonce cookie.
    The mismatch must be rejected, and critically must never proceed far
    enough to exchange the code or touch the database."""
    state = auth.create_signin_state("attackers-nonce")
    before_count = db_session.query(User).count()

    with patch("app.routers.google_auth.exchange_code_for_identity") as mock_exchange:
        res = client.get(
            f"/api/auth/google/callback?code=abc&state={state}",
            cookies={GOOGLE_SIGNIN_NONCE_COOKIE: "victims-nonce"},
            follow_redirects=False,
        )

    assert res.status_code in (302, 307)
    assert "google=invalid_state" in res.headers["location"]
    mock_exchange.assert_not_called()
    assert db_session.query(User).count() == before_count


def test_google_login_sets_httponly_samesite_nonce_cookie(client):
    """Confirms the cookie login() sets actually carries the CSRF-relevant
    attributes - httpOnly (never readable from page JS) and SameSite=Lax
    (still sent on the top-level GET navigation Google's redirect back to
    /callback performs)."""
    with patch("app.routers.google_auth.build_authorize_url", return_value="https://accounts.google.com/x"):
        res = client.get("/api/auth/google/login", follow_redirects=False)

    set_cookie = res.headers.get("set-cookie", "")
    assert GOOGLE_SIGNIN_NONCE_COOKIE in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "samesite=lax" in set_cookie.lower()


def test_google_callback_clears_nonce_cookie_after_success(client):
    """The cookie is single-use - clear/expired once the callback consumes
    it, whichever way the sign-in attempt resolves."""
    state, cookies = _valid_state_and_cookies()
    identity = GoogleIdentity(sub="google-sub-cookie-clear", email="cookieclear@example.com")
    with patch("app.routers.google_auth.exchange_code_for_identity", return_value=identity):
        res = client.get(f"/api/auth/google/callback?code=abc&state={state}", cookies=cookies, follow_redirects=False)

    set_cookie = res.headers.get("set-cookie", "").lower()
    assert GOOGLE_SIGNIN_NONCE_COOKIE in set_cookie
    assert "max-age=0" in set_cookie


# --- GET /api/auth/google/callback: account matching/creation --------------


def _token_from_fragment(location: str) -> str:
    assert "#token=" in location
    return location.split("#token=", 1)[1]


def _mark_email_verified(db_session, user_id: int) -> None:
    """make_user registers through the ordinary /api/users endpoint, which
    (by design - see routers/account.py's email-verification section)
    never requires proving email ownership, so its accounts start
    unverified. Tests exercising the auto-link path specifically need a
    *verified* existing account to reach it (see google_auth.callback's
    email_verified gate) - this sets that up directly rather than running
    the full email-verification-link flow just to flip one flag."""
    user = db_session.get(User, user_id)
    user.email_verified = True
    db_session.commit()


def test_google_callback_creates_new_account(client, db_session):
    state, cookies = _valid_state_and_cookies()
    identity = GoogleIdentity(sub="google-sub-new", email="brandnew@example.com")

    with patch("app.routers.google_auth.exchange_code_for_identity", return_value=identity):
        res = client.get(f"/api/auth/google/callback?code=abc&state={state}", cookies=cookies, follow_redirects=False)

    assert res.status_code in (302, 307)
    token = _token_from_fragment(res.headers["location"])

    user = db_session.query(User).filter_by(google_sub="google-sub-new").one()
    assert user.email == "brandnew@example.com"
    assert user.username == "brandnew"
    assert user.email_verified is True
    # Unusable, never-revealed password - can't be logged into locally
    # with any guessable password, including an empty one.
    assert not verify_password("", user.hashed_password)
    assert not verify_password("password123", user.hashed_password)
    assert not verify_password("brandnew", user.hashed_password)

    # The token handed back really authenticates as this new user.
    me_res = client.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["id"] == user.id


def test_google_callback_deduplicates_username_with_numeric_suffix(client, db_session):
    # An unrelated local account already holds the username the email's
    # local-part would naturally produce.
    taken_res = client.post(
        "/api/users", json={"username": "newperson", "email": "unrelated@other.com", "password": "password123"}
    )
    assert taken_res.status_code == 201

    state, cookies = _valid_state_and_cookies()
    identity = GoogleIdentity(sub="google-sub-dup", email="newperson@gmail.com")
    with patch("app.routers.google_auth.exchange_code_for_identity", return_value=identity):
        res = client.get(f"/api/auth/google/callback?code=abc&state={state}", cookies=cookies, follow_redirects=False)

    assert res.status_code in (302, 307)
    user = db_session.query(User).filter_by(google_sub="google-sub-dup").one()
    assert user.username == "newperson2"


def test_google_callback_links_existing_local_account_by_verified_email(client, make_user, db_session):
    bob = make_user("bob")  # email is bob@example.com (see make_user fixture)
    _mark_email_verified(db_session, bob["id"])

    state, cookies = _valid_state_and_cookies()
    identity = GoogleIdentity(sub="google-sub-bob", email="bob@example.com")
    with patch("app.routers.google_auth.exchange_code_for_identity", return_value=identity):
        res = client.get(f"/api/auth/google/callback?code=abc&state={state}", cookies=cookies, follow_redirects=False)

    assert res.status_code in (302, 307)
    token = _token_from_fragment(res.headers["location"])

    # Same account, not a new one - linked, not duplicated.
    users_with_this_email = db_session.query(User).filter_by(email="bob@example.com").all()
    assert len(users_with_this_email) == 1
    linked = users_with_this_email[0]
    assert linked.id == bob["id"]
    assert linked.google_sub == "google-sub-bob"
    assert linked.username == "bob"  # unchanged - not re-derived

    # The Google-issued token authenticates as bob.
    me_res = client.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["id"] == bob["id"]

    # And bob can still log in the original local way too - linked, not
    # replaced.
    login_res = client.post("/api/sessions", json={"username": "bob", "password": "password123"})
    assert login_res.status_code == 201


def test_google_callback_returning_google_sub_is_fast_path_and_does_not_rederive_from_email(client, db_session):
    # First sign-in creates the account.
    state1, cookies1 = _valid_state_and_cookies("nonce-1")
    first_identity = GoogleIdentity(sub="google-sub-returning", email="original@example.com")
    with patch("app.routers.google_auth.exchange_code_for_identity", return_value=first_identity):
        res1 = client.get(f"/api/auth/google/callback?code=abc&state={state1}", cookies=cookies1, follow_redirects=False)
    assert res1.status_code in (302, 307)
    user_id = db_session.query(User).filter_by(google_sub="google-sub-returning").one().id

    # Second sign-in, same sub, but Google now reports a different email
    # (simulating the email having changed on Google's side) - the
    # google_sub match must be used as-is, never re-deriving the local
    # username/email from this newer email.
    state2, cookies2 = _valid_state_and_cookies("nonce-2")
    second_identity = GoogleIdentity(sub="google-sub-returning", email="changed@example.com")
    with patch("app.routers.google_auth.exchange_code_for_identity", return_value=second_identity):
        res2 = client.get(f"/api/auth/google/callback?code=abc&state={state2}", cookies=cookies2, follow_redirects=False)
    assert res2.status_code in (302, 307)

    db_session.expire_all()
    user = db_session.get(User, user_id)
    assert user.email == "original@example.com"  # untouched
    assert user.username is not None and not user.username.startswith("changed")
    # Still exactly one account for this google_sub - no duplicate created.
    assert db_session.query(User).filter_by(google_sub="google-sub-returning").count() == 1


def test_google_callback_rejects_deleted_account_matched_via_google_sub(client, db_session):
    from datetime import datetime

    state1, cookies1 = _valid_state_and_cookies("nonce-1")
    identity = GoogleIdentity(sub="google-sub-deleted", email="deleteme@example.com")
    with patch("app.routers.google_auth.exchange_code_for_identity", return_value=identity):
        res1 = client.get(f"/api/auth/google/callback?code=abc&state={state1}", cookies=cookies1, follow_redirects=False)
    assert res1.status_code in (302, 307)

    # This account's password is an unusable random one (see the account-
    # creation test above), so the normal self-deletion flow (which
    # requires knowing the password) isn't how a Google-only account would
    # realistically get deleted in this test - set the marker directly to
    # set up the "matched via google_sub but deleted" scenario this test
    # targets, the same account.is_deleted flag account.py's real deletion
    # endpoint sets.
    user = db_session.query(User).filter_by(google_sub="google-sub-deleted").one()
    user.deleted_at = datetime.utcnow()
    db_session.commit()

    state2, cookies2 = _valid_state_and_cookies("nonce-2")
    with patch("app.routers.google_auth.exchange_code_for_identity", return_value=identity):
        res2 = client.get(f"/api/auth/google/callback?code=abc&state={state2}", cookies=cookies2, follow_redirects=False)

    assert res2.status_code in (302, 307)
    assert "google=account_deleted" in res2.headers["location"]


def test_google_callback_email_case_insensitive_match(client, make_user, db_session):
    carol = make_user("carol")  # email carol@example.com
    _mark_email_verified(db_session, carol["id"])

    state, cookies = _valid_state_and_cookies()
    identity = GoogleIdentity(sub="google-sub-carol", email="Carol@Example.com")
    with patch("app.routers.google_auth.exchange_code_for_identity", return_value=identity):
        res = client.get(f"/api/auth/google/callback?code=abc&state={state}", cookies=cookies, follow_redirects=False)

    assert res.status_code in (302, 307)
    users_named_carol = db_session.query(User).filter_by(username="carol").all()
    assert len(users_named_carol) == 1
    assert users_named_carol[0].google_sub == "google-sub-carol"


# --- GET /api/auth/google/callback: unverified-existing-account conflict ---
# (finding #1 - see google_auth.callback's email_verified gate)


def test_google_callback_refuses_to_link_unverified_existing_account(client, make_user, db_session):
    """The account-takeover scenario this closes: an attacker registers
    victim@example.com locally (email_verified defaults False - local
    registration never proves ownership), then the real owner later signs
    in with Google using that same, Google-verified address. Auto-linking
    must be refused - linking would hand the attacker's pre-existing,
    attacker-controlled local account (and its attacker-known password)
    permanent access to what the real owner just proved is their
    address."""
    victim_local_account = make_user("victim")  # email victim@example.com, email_verified=False by default
    before_count = db_session.query(User).count()

    state, cookies = _valid_state_and_cookies()
    identity = GoogleIdentity(sub="google-sub-victim", email="victim@example.com")
    with patch("app.routers.google_auth.exchange_code_for_identity", return_value=identity):
        res = client.get(f"/api/auth/google/callback?code=abc&state={state}", cookies=cookies, follow_redirects=False)

    assert res.status_code in (302, 307)
    assert "google=email_unverified_conflict" in res.headers["location"]

    # Not linked...
    db_session.expire_all()
    unverified_account = db_session.get(User, victim_local_account["id"])
    assert unverified_account.google_sub is None
    # ...and no second account silently created for the same email either.
    assert db_session.query(User).count() == before_count
    assert db_session.query(User).filter_by(email="victim@example.com").count() == 1


def test_google_callback_unverified_conflict_issues_no_token(client, make_user, db_session):
    """Belt-and-suspenders on the same case above: the redirect must never
    carry a #token= fragment either, since that would authenticate the
    caller as someone even though no linking or account creation
    happened."""
    make_user("victim2")

    state, cookies = _valid_state_and_cookies()
    identity = GoogleIdentity(sub="google-sub-victim2", email="victim2@example.com")
    with patch("app.routers.google_auth.exchange_code_for_identity", return_value=identity):
        res = client.get(f"/api/auth/google/callback?code=abc&state={state}", cookies=cookies, follow_redirects=False)

    assert "#token=" not in res.headers["location"]
