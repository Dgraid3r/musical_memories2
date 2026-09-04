"""Shared 429 (rate limit) retry/backoff handling for every outbound
Spotify call - the app-only search client, per-user OAuth playlist
calls, and OAuth token exchange/refresh.

Why this exists instead of relying on spotipy/urllib3's own built-in
retry: urllib3's Retry, by default, *honors* a server's Retry-After
header with essentially no practical cap (its own default
retry_after_max is 21600 seconds - six hours). If Spotify ever sent a
large Retry-After, that would hang a user's web request for however
long Spotify said to wait. This module always owns the retry loop
itself instead, and caps every sleep to a few seconds regardless of
what Spotify asks for, bounded to a small, fixed number of attempts -
so a request fails fast with a clean error rather than hanging.
"""

import logging
import time

import requests
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyOauthError

logger = logging.getLogger(__name__)

# Bounded on purpose: a handful of quick retries is enough to ride out a
# brief 429, and a user-facing request must still fail fast rather than
# hang if Spotify stays unhappy.
MAX_ATTEMPTS = 3  # 1 initial try + up to 2 retries
MAX_BACKOFF_SECONDS = 5.0
BASE_BACKOFF_SECONDS = 0.5


class SpotifyUnavailableError(Exception):
    """Raised once every retry attempt has been exhausted on a 429.
    Routers catch this and return a clean, specific user-facing error
    instead of a raw 500 or an unhandled exception."""


class StatusCapturingSession(requests.Session):
    """A plain requests.Session that also remembers the status code and
    headers of the most recent response.

    spotipy's OAuth flows (SpotifyOauthError) discard the original HTTP
    status code and headers when converting a requests HTTPError, so
    there's no way to ask "was this actually a 429, and what did
    Retry-After say" from the exception alone. Passing one of these in
    as SpotifyOAuth's `requests_session` lets callers recover that
    information by reading the session back after the call.
    """

    def __init__(self) -> None:
        super().__init__()
        self.last_status: int | None = None
        self.last_headers: "requests.structures.CaseInsensitiveDict | dict" = {}

    def send(self, request, **kwargs):  # type: ignore[override]
        response = super().send(request, **kwargs)
        self.last_status = response.status_code
        self.last_headers = response.headers
        return response


def _retry_after_seconds(headers) -> float | None:
    value = headers.get("Retry-After") if headers else None
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        # Retry-After can also be an HTTP-date rather than a delta-seconds
        # value - rare from Spotify in practice, and not worth parsing
        # here since we cap the wait ourselves regardless.
        return None


def _sleep_seconds(attempt: int, retry_after: float | None) -> float:
    if retry_after is not None:
        return max(0.0, min(retry_after, MAX_BACKOFF_SECONDS))
    return min(BASE_BACKOFF_SECONDS * (2**attempt), MAX_BACKOFF_SECONDS)


def call_with_retry(fn, *args, log_label: str, session: StatusCapturingSession | None = None, **kwargs):
    """Calls fn(*args, **kwargs), retrying with capped backoff whenever
    Spotify responds 429, up to MAX_ATTEMPTS total tries.

    `session`, when given, is a StatusCapturingSession used for this same
    call's underlying request - consulted whenever fn raises
    SpotifyOauthError, since that exception type doesn't carry the status
    code itself (see StatusCapturingSession).

    Raises SpotifyUnavailableError once retries are exhausted. Any
    non-429 error is re-raised immediately, unretried.
    """
    for attempt in range(MAX_ATTEMPTS):
        retry_after: float | None = None
        try:
            return fn(*args, **kwargs)
        except SpotifyException as exc:
            if exc.http_status != 429:
                raise
            retry_after = _retry_after_seconds(exc.headers)
        except SpotifyOauthError:
            status = session.last_status if session else None
            if status != 429:
                raise
            retry_after = _retry_after_seconds(session.last_headers if session else None)

        attempts_left = MAX_ATTEMPTS - attempt - 1
        if attempts_left <= 0:
            logger.warning(
                "spotify.rate_limit_exhausted call=%s attempts=%d retry_after=%s",
                log_label, MAX_ATTEMPTS, retry_after,
            )
            raise SpotifyUnavailableError("Spotify is temporarily unavailable, try again shortly.")

        wait = _sleep_seconds(attempt, retry_after)
        logger.warning(
            "spotify.rate_limited call=%s attempt=%d retry_after=%s sleeping=%.2f",
            log_label, attempt + 1, retry_after, wait,
        )
        time.sleep(wait)

    # Unreachable (the loop above always either returns or raises), but
    # keeps this function's return type honest.
    raise SpotifyUnavailableError("Spotify is temporarily unavailable, try again shortly.")
