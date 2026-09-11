from fastapi import APIRouter, HTTPException, Query

from ..nominatim_client import PlacesUnavailableError, reverse_geocode, search_places
from ..schemas import PlaceResult, ReverseGeocodeResult

router = APIRouter(prefix="/api/places", tags=["places"])


@router.get("/search", response_model=list[PlaceResult])
def search(q: str = Query(..., min_length=1)):
    """Backend-proxied place search (OpenStreetMap Nominatim) - never
    called directly from the frontend. See nominatim_client.py for why:
    a descriptive User-Agent Nominatim's usage policy requires, a shared
    request throttle to stay within that policy's rate, and a short TTL
    cache, the same shape as how Spotify search is already proxied
    through this backend rather than hit client-side. No auth required -
    the same "no login needed" bar as Spotify's app-only playlist search."""
    try:
        return search_places(q)
    except PlacesUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/reverse", response_model=ReverseGeocodeResult)
def reverse(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)):
    """Reverse geocoding for "use my current location" (see
    LocationPicker.tsx) - turns the browser's bare coordinates into a
    human-readable place name. Reuses search_places' Nominatim
    client/throttle/cache rather than a second independent setup (see
    nominatim_client.reverse_geocode), and is narrowed to display_name
    only, the same "never Nominatim's raw response" rule as /search. No
    auth required, same bar as /search - this is a nice-to-have label,
    not a sensitive lookup."""
    try:
        return reverse_geocode(lat, lon)
    except PlacesUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
