"""Backend-proxied place search via OpenStreetMap's Nominatim
(https://nominatim.org/) - free, no API key, matching this project's
established preference for free/no-signup defaults (Cloudflare R2, the
SMTP log-fallback, etc.), used here instead of Google/Mapbox geocoding.

Never called directly from the frontend (see routers/places.py) for two
reasons: Nominatim's usage policy
(https://operations.osmfoundation.org/policies/nominatim/) requires a
descriptive User-Agent identifying the calling application - something
only a server-side call can reliably attach - and asks for roughly no
more than 1 request/second from a single application, which this module
enforces itself via a shared minimum-interval throttle (the same pattern
spotify_client.py already uses for Spotify's own rate limit) rather than
trusting many independent browser tabs to self-limit.
"""

import logging
import os
import threading
import time

import requests

from cachetools import TTLCache

from .schemas import PlaceResult, ReverseGeocodeResult

logger = logging.getLogger(__name__)

NOMINATIM_BASE_URL = os.environ.get("NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org")
# A generic/absent User-Agent risks this app's traffic being blocked
# outright under Nominatim's usage policy - identify it descriptively.
# Override via env if deploying under a different app name/contact.
NOMINATIM_USER_AGENT = os.environ.get(
    "NOMINATIM_USER_AGENT", "MusicalMemories/1.0 (personal journal app; https://github.com/)"
)
NOMINATIM_REQUEST_TIMEOUT_SECONDS = 5

# Same reasoning as spotify_client.py's search cache: a single-process
# local app, so an in-memory TTL cache is the right tool, not Redis. 10
# minutes is plenty fresh for place names, which essentially never change,
# and absorbs a user retyping/backspacing while composing a search.
#
# Shared by both search_places and reverse_geocode below (distinctly
# tagged keys - ("search", query, limit) vs ("reverse", lat, lon) - so
# there's exactly one cache, exactly one MAXSIZE budget, and exactly one
# place to clear in tests, rather than two parallel caches that would
# only cost more memory for no benefit; the two lookups never collide.
SEARCH_CACHE_TTL_SECONDS = 600
SEARCH_CACHE_MAXSIZE = 256

_search_cache: TTLCache = TTLCache(maxsize=SEARCH_CACHE_MAXSIZE, ttl=SEARCH_CACHE_TTL_SECONDS)


def clear_search_cache() -> None:
    """Exposed mainly for tests, which must not let one test's cached
    result leak into the next test's assertions about a fresh call."""
    _search_cache.clear()


# Nominatim's usage policy asks for roughly no more than 1 request/second
# from this application in total, a stricter budget than Spotify's, hence
# a distinct (slower) default than spotify_client.SEARCH_MIN_INTERVAL_SECONDS.
NOMINATIM_MIN_INTERVAL_SECONDS = float(os.environ.get("NOMINATIM_MIN_INTERVAL_SECONDS", "1.0"))

_throttle_lock = threading.Lock()
_last_call_monotonic: float | None = None


def reset_throttle() -> None:
    """Test-only: same reasoning as clear_search_cache - one test's recent
    call shouldn't make a later test's first call wait a full second."""
    global _last_call_monotonic
    with _throttle_lock:
        _last_call_monotonic = None


def _throttle() -> None:
    global _last_call_monotonic
    with _throttle_lock:
        now = time.monotonic()
        wait = 0.0
        if _last_call_monotonic is not None:
            wait = _last_call_monotonic + NOMINATIM_MIN_INTERVAL_SECONDS - now
        if wait > 0:
            time.sleep(wait)
        _last_call_monotonic = time.monotonic()


class PlacesUnavailableError(Exception):
    """Nominatim is unreachable or returned an error - never crashes the
    request, this surfaces as a clean 503 (see routers/places.py)."""


def search_places(query: str, limit: int = 5) -> list[PlaceResult]:
    cache_key = (query, limit)
    cached = _search_cache.get(cache_key)
    if cached is not None:
        logger.info("places.search cache=hit query=%r results=%d", query, len(cached))
        return cached

    _throttle()
    try:
        response = requests.get(
            f"{NOMINATIM_BASE_URL}/search",
            params={"q": query, "format": "jsonv2", "limit": limit},
            headers={"User-Agent": NOMINATIM_USER_AGENT},
            timeout=NOMINATIM_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        raw_results = response.json()
    except requests.RequestException:
        logger.exception("places.search query=%r failed", query)
        raise PlacesUnavailableError("Place search is temporarily unavailable") from None
    except ValueError:
        # response.json() failed to parse - Nominatim returned something
        # unexpected (an HTML error page, etc.).
        logger.exception("places.search query=%r returned unparseable response", query)
        raise PlacesUnavailableError("Place search is temporarily unavailable") from None

    # Deliberately narrow: only display_name/lat/lon are ever extracted
    # from Nominatim's response - its many other fields (osm_id, address
    # breakdown, importance score, bounding box, etc.) never reach the
    # frontend, matching this project's existing "proxy, don't pass
    # through the raw response" pattern (see spotify_client.search_playlists).
    places = [
        PlaceResult(display_name=item["display_name"], latitude=float(item["lat"]), longitude=float(item["lon"]))
        for item in raw_results
        if isinstance(item, dict) and "display_name" in item and "lat" in item and "lon" in item
    ]

    logger.info("places.search cache=miss query=%r results=%d", query, len(places))
    _search_cache[cache_key] = places
    return places


# ~11m at the equator - close enough that "use my current location"
# clicked twice from roughly the same spot (GPS jitter, or the same user
# a minute later) hits the cache, without rounding away meaningfully
# different nearby addresses.
REVERSE_GEOCODE_COORD_PRECISION = 4


def reverse_geocode(latitude: float, longitude: float) -> ReverseGeocodeResult:
    """Turns raw coordinates into a human-readable place name - used by
    "use my current location" (see routers/places.py and
    LocationPicker.tsx), which otherwise has only bare lat/lng from the
    browser's geolocation API. Shares search_places' throttle and cache
    above rather than a second independent one, so the two lookups
    together still respect Nominatim's single combined rate policy."""
    cache_key = (
        "reverse",
        round(latitude, REVERSE_GEOCODE_COORD_PRECISION),
        round(longitude, REVERSE_GEOCODE_COORD_PRECISION),
    )
    cached = _search_cache.get(cache_key)
    if cached is not None:
        logger.info("places.reverse cache=hit lat=%s lon=%s", latitude, longitude)
        return cached

    _throttle()
    try:
        response = requests.get(
            f"{NOMINATIM_BASE_URL}/reverse",
            params={"lat": latitude, "lon": longitude, "format": "jsonv2"},
            headers={"User-Agent": NOMINATIM_USER_AGENT},
            timeout=NOMINATIM_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        raw_result = response.json()
    except requests.RequestException:
        logger.exception("places.reverse lat=%s lon=%s failed", latitude, longitude)
        raise PlacesUnavailableError("Reverse geocoding is temporarily unavailable") from None
    except ValueError:
        logger.exception("places.reverse lat=%s lon=%s returned unparseable response", latitude, longitude)
        raise PlacesUnavailableError("Reverse geocoding is temporarily unavailable") from None

    # Nominatim returns a 200 with {"error": "Unable to geocode"} (no
    # display_name) for coordinates with nothing nearby - that's still a
    # "no name available" outcome the caller should fall back on, same as
    # any other failure here.
    if not isinstance(raw_result, dict) or "display_name" not in raw_result:
        logger.warning("places.reverse lat=%s lon=%s no display_name in response", latitude, longitude)
        raise PlacesUnavailableError("No place name found for this location")

    result = ReverseGeocodeResult(display_name=raw_result["display_name"])
    logger.info("places.reverse cache=miss lat=%s lon=%s", latitude, longitude)
    _search_cache[cache_key] = result
    return result
