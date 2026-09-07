import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

from app.spotify_client import SEARCH_MIN_INTERVAL_SECONDS, reset_throttle, search_playlists


def _fake_search_response(name="Chill Vibes"):
    return {
        "playlists": {
            "items": [
                {
                    "id": "abc123",
                    "name": name,
                    "external_urls": {"spotify": "https://open.spotify.com/playlist/abc123"},
                    "images": [],
                    "owner": {"display_name": "spotify"},
                    "tracks": {"total": 1},
                }
            ]
        }
    }


def test_single_request_is_not_delayed():
    """The throttle must never add latency to an isolated, normal
    request - only back-to-back calls should ever wait."""
    reset_throttle()
    fake_client = MagicMock()
    fake_client.search.return_value = _fake_search_response()

    with (
        patch("app.spotify_client.get_spotify_client", return_value=fake_client),
        patch("app.spotify_client.time.sleep") as mock_sleep,
    ):
        search_playlists("solo query")

    mock_sleep.assert_not_called()


def test_rapid_back_to_back_calls_are_throttled():
    reset_throttle()
    fake_client = MagicMock()
    fake_client.search.side_effect = [_fake_search_response("first"), _fake_search_response("second")]

    with (
        patch("app.spotify_client.get_spotify_client", return_value=fake_client),
        patch("app.spotify_client.time.sleep") as mock_sleep,
    ):
        search_playlists("throttle query one")
        search_playlists("throttle query two")

    mock_sleep.assert_called_once()
    waited = mock_sleep.call_args[0][0]
    # A tiny floating-point epsilon above SEARCH_MIN_INTERVAL_SECONDS is
    # expected here (real time.monotonic() calls, mocked-out sleep) - what
    # matters is that it's a small, positive, roughly-the-interval wait,
    # not that it's exactly bounded to the nanosecond.
    assert 0 < waited <= SEARCH_MIN_INTERVAL_SECONDS + 0.01


def test_a_cache_hit_never_waits_on_the_throttle():
    """The throttle only guards the actual outbound call - a cached
    result must return instantly regardless of how recently the client
    called Spotify."""
    reset_throttle()
    fake_client = MagicMock()
    fake_client.search.return_value = _fake_search_response()

    with patch("app.spotify_client.get_spotify_client", return_value=fake_client):
        search_playlists("cached throttle query")

    with (
        patch("app.spotify_client.get_spotify_client", return_value=fake_client),
        patch("app.spotify_client.time.sleep") as mock_sleep,
    ):
        search_playlists("cached throttle query")

    mock_sleep.assert_not_called()


# --- Real concurrency ------------------------------------------------------
#
# Everything above exercises the throttle sequentially, in one thread - it
# proves the math, but not that the threading.Lock actually serializes a
# real burst of concurrent callers the way FastAPI's threadpool would
# produce it. This uses real time.sleep/time.monotonic (nothing mocked) so
# the timing assertions are a genuine wall-clock proof, not a simulation.


def test_concurrent_calls_are_correctly_serialized():
    """Fires a real burst of concurrent callers through the throttle and
    verifies the lock actually serialized them - not just that the
    single-threaded math in the tests above works out.

    Timestamps are captured from _throttle()'s own return value (the
    exact moment each call was released, taken while still holding no
    lock but before any further work) rather than after the full
    search_playlists() round trip - a timestamp taken that late is
    subject to its own independent thread-scheduling delay once 25+
    threads are contending for CPU time, which can reorder finish times
    relative to true release order and make a correct throttle look
    racy. Reading the guaranteed release value directly is immune to
    that and is what actually proves the lock's ordering guarantee.
    """
    import app.spotify_client as spotify_client_module

    reset_throttle()
    worker_count = 25
    real_throttle = spotify_client_module._throttle

    release_times: list[float] = []
    times_lock = threading.Lock()

    def recording_throttle() -> float:
        released_at = real_throttle()
        with times_lock:
            release_times.append(released_at)
        return released_at

    fake_client = MagicMock()
    fake_client.search.side_effect = [_fake_search_response(f"concurrent-{i}") for i in range(worker_count)]

    def call_search(i: int) -> None:
        results = search_playlists(f"concurrent throttle query {i}")
        assert len(results) == 1

    with (
        patch("app.spotify_client.get_spotify_client", return_value=fake_client),
        patch("app.spotify_client._throttle", side_effect=recording_throttle),
    ):
        start = time.monotonic()
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            # list(...) forces every future to resolve and re-raises any
            # worker exception here, rather than silently swallowing it.
            list(executor.map(call_search, range(worker_count)))
        elapsed = time.monotonic() - start

    # Nothing raced or double-fired: every worker's call actually reached
    # Spotify exactly once, consuming its own distinct side_effect entry
    # (a raced/corrupted side_effect iterator would raise StopIteration or
    # produce a call_count mismatch instead of reaching this assertion),
    # and the throttle itself ran exactly once per call too.
    assert fake_client.search.call_count == worker_count
    assert len(release_times) == worker_count

    # The lock genuinely serialized the callers rather than letting them
    # through in parallel: total wall-clock time is at least what
    # (worker_count - 1) sequential minimum-interval gaps would take.
    assert elapsed >= (worker_count - 1) * SEARCH_MIN_INTERVAL_SECONDS

    # And no two calls were released meaningfully closer together than the
    # configured interval - guaranteed by construction (each release
    # computes its wait relative to the previous release's own timestamp,
    # under the same lock). The tolerance here isn't for scheduling
    # jitter (there's none left to account for - these are each call's
    # own guaranteed release timestamps); it's for time.sleep() itself
    # occasionally waking up slightly early, which is a genuine OS timer-
    # resolution characteristic even for a single isolated sleep (observed
    # up to ~7ms short of a requested 0.1s on this machine), not a flaw
    # in the throttle's serialization logic.
    release_times.sort()
    gaps = [b - a for a, b in zip(release_times, release_times[1:])]
    assert all(gap >= SEARCH_MIN_INTERVAL_SECONDS - 0.02 for gap in gaps)
