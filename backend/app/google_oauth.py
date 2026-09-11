"""Google Sign-In (OAuth 2.0 Authorization Code flow, ending in Google's
OpenID Connect ID token) - lets a user log in, and implicitly register,
with their Google account. Additive to the existing local email/password
auth (routers/sessions.py, routers/users.py), never a replacement.

Distinct in kind from spotify_oauth.py: Spotify's flow connects a music
service to an already-logged-in local user. This flow is actual
authentication into the app itself - there may be no logged-in user (or
even an existing local account) when it starts, so it can't reuse
auth.create_oauth_state/verify_oauth_state (those carry a local user id
to protect Spotify's redirect round-trip; see auth.create_signin_state/
verify_signin_state instead, a lighter sibling with no identity to carry).

Requires GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET (an OAuth client
registered in the Google Cloud Console) and GOOGLE_REDIRECT_URI,
registered exactly as an authorized redirect URI for that client. Opt-in
like every other external integration in this app (Spotify, Sentry, SMTP,
object storage) - unset, GET /api/auth/google/config reports disabled and
the frontend simply doesn't show the "Sign in with Google" button, rather
than the app erroring.
"""

import logging
import os
from dataclasses import dataclass
from urllib.parse import urlencode

import requests
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

logger = logging.getLogger(__name__)

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
# openid is what makes Google's response include an ID token at all;
# email/profile are the two claims this app actually reads (email,
# email_verified) - nothing broader is requested.
SCOPE = "openid email profile"
REQUEST_TIMEOUT_SECONDS = 10

# What Google's ID tokens are expected to carry in `iss`. google-auth's
# own verify_oauth2_token already enforces this internally (raising if
# the issuer doesn't match), but this app checks it again explicitly too -
# cheap, harmless in normal operation, and gives this module's own code a
# directly testable line matching the "iss is Google's" requirement,
# rather than relying entirely on trust in the library's internals.
EXPECTED_ISSUERS = ("accounts.google.com", "https://accounts.google.com")


class GoogleSignInNotConfigured(RuntimeError):
    pass


class GoogleSignInUnavailable(RuntimeError):
    """Google's endpoints were unreachable, timed out, or returned a
    non-2xx/unparseable response during the code exchange - distinct from
    GoogleTokenInvalid, which means Google responded normally but the ID
    token itself didn't check out."""


class GoogleTokenInvalid(RuntimeError):
    """The exchanged ID token failed verification (bad signature, wrong
    audience/issuer, expired) or reported an unverified email, or Google's
    token response was missing an ID token entirely. Never trust the
    caller's claimed identity in any of these cases."""


@dataclass
class GoogleIdentity:
    """What routers/google_auth.py needs after a successful sign-in - the
    verified, stable account id (`sub`) and the verified email. Nothing
    else from Google's ID token (name, picture, locale, etc.) is ever
    extracted or stored."""

    sub: str
    email: str


def _config() -> tuple[str, str, str]:
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI")
    if not client_id or not client_secret or not redirect_uri:
        raise GoogleSignInNotConfigured(
            "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI are not set. "
            "Copy backend/.env.example to backend/.env and fill them in, and register the "
            "redirect URI as an authorized redirect URI on that OAuth client in the Google "
            "Cloud Console."
        )
    return client_id, client_secret, redirect_uri


def is_configured() -> bool:
    """Used by GET /api/auth/google/config - the frontend's "should the
    Sign in with Google button even appear" check."""
    try:
        _config()
        return True
    except GoogleSignInNotConfigured:
        return False


def build_authorize_url(state: str) -> str:
    client_id, _, redirect_uri = _config()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        # Always show the account chooser rather than silently reusing
        # whatever Google session happens to already be active in the
        # browser - this is a conscious sign-in action, not a background
        # connection like Spotify's.
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code_for_identity(code: str) -> GoogleIdentity:
    """Exchanges an authorization code for Google's tokens, then verifies
    the returned ID token properly - signature against Google's published
    keys, `aud` matches our client id, `iss` is Google's, not expired -
    via google-auth's own google.oauth2.id_token.verify_oauth2_token.
    Never hand-rolled JWT/JWKS verification. Refuses (raises
    GoogleTokenInvalid) unless Google also reports the email as verified;
    an unverified email is never trusted for linking or account creation."""
    client_id, client_secret, redirect_uri = _config()

    try:
        response = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        token_response = response.json()
    except requests.RequestException:
        logger.exception("google_signin.token_exchange_failed")
        raise GoogleSignInUnavailable("Google sign-in is temporarily unavailable") from None
    except ValueError:
        logger.exception("google_signin.token_exchange_unparseable_response")
        raise GoogleSignInUnavailable("Google sign-in is temporarily unavailable") from None

    raw_id_token = token_response.get("id_token")
    if not raw_id_token:
        logger.warning("google_signin.no_id_token_in_response")
        raise GoogleTokenInvalid("Google did not return an identity token")

    try:
        claims = google_id_token.verify_oauth2_token(raw_id_token, google_requests.Request(), audience=client_id)
    except Exception:
        # google-auth raises a few different exception types here
        # (ValueError for a malformed token, google.auth.exceptions.
        # GoogleAuthError for a bad signature/expired token/wrong
        # issuer/wrong audience) - all of them mean the same thing to
        # this caller: don't trust this token, full stop.
        logger.exception("google_signin.id_token_verification_failed")
        raise GoogleTokenInvalid("Could not verify Google's identity token") from None

    if claims.get("iss") not in EXPECTED_ISSUERS:
        logger.warning("google_signin.unexpected_issuer iss=%r", claims.get("iss"))
        raise GoogleTokenInvalid("Could not verify Google's identity token")

    if not claims.get("email_verified"):
        logger.warning("google_signin.email_not_verified sub=%r", claims.get("sub"))
        raise GoogleTokenInvalid("Your Google account's email address is not verified")

    email = claims.get("email")
    sub = claims.get("sub")
    if not email or not sub:
        logger.warning("google_signin.missing_claims")
        raise GoogleTokenInvalid("Google's identity token was missing required fields")

    logger.info("google_signin.identity_verified sub=%s", sub)
    return GoogleIdentity(sub=sub, email=email)
