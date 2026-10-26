"""Rate limiting for the auth endpoints (login/register) - blunts
brute-forcing and credential stuffing. In-memory, keyed by caller IP: this
is a single-process app (same reasoning as the Spotify search cache and the
JWT-based auth), so there's no need for a shared/distributed limiter store.

Applied narrowly to POST /api/sessions and POST /api/users, not globally -
everything else (reading entries, browsing playlists, etc.) is unaffected.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

AUTH_RATE_LIMIT = "5/minute"

# "Generate from a prompt" (POST /api/spotify/playlists/generate): each
# call spends real Anthropic API tokens plus a burst of Spotify searches,
# so it's capped per caller far more tightly than ordinary reads.
PLAYLIST_GENERATE_RATE_LIMIT = "10/hour"


def user_or_ip_key(request) -> str:
    """Rate-limit key for logged-in-only endpoints: the authenticated user
    id from the bearer token when it decodes, so one user can't dodge the
    limit by switching networks and users behind one NAT don't share a
    budget; the caller IP otherwise. The endpoint's own get_current_user
    dependency still does the real authentication - this only picks a
    bucket."""
    import jwt

    from .auth import ALGORITHM, _secret_key

    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        try:
            payload = jwt.decode(header[7:].strip(), _secret_key(), algorithms=[ALGORITHM])
            sub = payload.get("sub")
            if sub is not None:
                return f"user:{sub}"
        except jwt.PyJWTError:
            pass
    return get_remote_address(request)
