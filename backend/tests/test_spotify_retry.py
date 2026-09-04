from unittest.mock import MagicMock, patch

import pytest
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyOauthError

from app.spotify_retry import (
    MAX_ATTEMPTS,
    SpotifyUnavailableError,
    call_with_retry,
)


def _rate_limited(retry_after: str | None = None):
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return SpotifyException(429, -1, "rate limited", headers=headers)


def _server_error():
    return SpotifyException(500, -1, "server error", headers={})


# --- call_with_retry: SpotifyException path (search, per-user calls) -------


def test_retry_then_succeed_on_429():
    fn = MagicMock(side_effect=[_rate_limited(), "ok"])
    with patch("app.spotify_retry.time.sleep") as mock_sleep:
        result = call_with_retry(fn, log_label="test")

    assert result == "ok"
    assert fn.call_count == 2
    mock_sleep.assert_called_once()


def test_retry_exhausted_raises_clean_error():
    fn = MagicMock(side_effect=[_rate_limited(), _rate_limited(), _rate_limited(), _rate_limited()])
    with patch("app.spotify_retry.time.sleep"):
        with pytest.raises(SpotifyUnavailableError) as exc_info:
            call_with_retry(fn, log_label="test")

    assert fn.call_count == MAX_ATTEMPTS
    assert "temporarily unavailable" in str(exc_info.value)


def test_non_429_spotify_exception_is_not_retried():
    fn = MagicMock(side_effect=_server_error())
    with patch("app.spotify_retry.time.sleep") as mock_sleep:
        with pytest.raises(SpotifyException) as exc_info:
            call_with_retry(fn, log_label="test")

    assert exc_info.value.http_status == 500
    assert fn.call_count == 1
    mock_sleep.assert_not_called()


def test_retry_after_header_is_respected_and_capped():
    fn = MagicMock(side_effect=[_rate_limited(retry_after="9999"), "ok"])
    with patch("app.spotify_retry.time.sleep") as mock_sleep:
        call_with_retry(fn, log_label="test")

    # A huge Retry-After must never translate into an equally huge sleep -
    # this is exactly what keeps a request from hanging indefinitely.
    slept_for = mock_sleep.call_args[0][0]
    assert 0 < slept_for <= 5.0


def test_small_retry_after_is_used_directly():
    fn = MagicMock(side_effect=[_rate_limited(retry_after="1"), "ok"])
    with patch("app.spotify_retry.time.sleep") as mock_sleep:
        call_with_retry(fn, log_label="test")

    mock_sleep.assert_called_once_with(1.0)


def test_call_succeeds_immediately_without_sleeping():
    fn = MagicMock(return_value="ok")
    with patch("app.spotify_retry.time.sleep") as mock_sleep:
        result = call_with_retry(fn, log_label="test")

    assert result == "ok"
    assert fn.call_count == 1
    mock_sleep.assert_not_called()


# --- call_with_retry: SpotifyOauthError path (token exchange/refresh) ------


def test_oauth_429_retried_using_session_status():
    session = MagicMock()
    session.last_status = 429
    session.last_headers = {"Retry-After": "1"}
    fn = MagicMock(side_effect=[SpotifyOauthError("rate limited"), {"access_token": "a"}])

    with patch("app.spotify_retry.time.sleep") as mock_sleep:
        result = call_with_retry(fn, log_label="test", session=session)

    assert result == {"access_token": "a"}
    assert fn.call_count == 2
    mock_sleep.assert_called_once_with(1.0)


def test_oauth_non_429_error_is_not_retried():
    session = MagicMock()
    session.last_status = 400
    fn = MagicMock(side_effect=SpotifyOauthError("invalid_grant"))

    with patch("app.spotify_retry.time.sleep") as mock_sleep:
        with pytest.raises(SpotifyOauthError):
            call_with_retry(fn, log_label="test", session=session)

    assert fn.call_count == 1
    mock_sleep.assert_not_called()


def test_oauth_error_without_session_is_not_retried():
    """No session was passed, so there's no way to know whether this was
    actually a 429 - must not guess and retry blindly."""
    fn = MagicMock(side_effect=SpotifyOauthError("something"))

    with patch("app.spotify_retry.time.sleep") as mock_sleep:
        with pytest.raises(SpotifyOauthError):
            call_with_retry(fn, log_label="test")

    assert fn.call_count == 1
    mock_sleep.assert_not_called()
