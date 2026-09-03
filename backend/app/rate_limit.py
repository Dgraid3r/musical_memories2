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
