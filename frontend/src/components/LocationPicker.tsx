import { useEffect, useState } from 'react'
import { ApiError, searchPlaces } from '../api'
import type { EntryLocation, PlaceResult } from '../types'

interface Props {
  value: EntryLocation | null
  onChange: (location: EntryLocation | null) => void
}

/** A location is always added deliberately - never captured
 * automatically or silently. Search is debounced text typed by the user
 * (geocoded server-side via Nominatim, see api.ts searchPlaces), and "Use
 * my current location" only ever triggers the browser's geolocation
 * prompt on this exact click, never on mount or in the background. */
export default function LocationPicker({ value, onChange }: Props) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<PlaceResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [locating, setLocating] = useState(false)

  useEffect(() => {
    if (query.trim().length < 3) {
      setResults([])
      return
    }
    const handle = setTimeout(() => {
      setLoading(true)
      setError(null)
      searchPlaces(query)
        .then(setResults)
        .catch((err) => setError(err instanceof ApiError ? err.message : 'Could not search for places.'))
        .finally(() => setLoading(false))
    }, 350)
    return () => clearTimeout(handle)
  }, [query])

  function selectPlace(place: PlaceResult) {
    onChange({ latitude: place.latitude, longitude: place.longitude, location_name: place.display_name })
    setQuery('')
    setResults([])
  }

  function useCurrentLocation() {
    if (!navigator.geolocation) {
      setError('Your browser does not support location services.')
      return
    }
    setLocating(true)
    setError(null)
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const { latitude, longitude } = position.coords
        onChange({
          latitude,
          longitude,
          location_name: `Current location (${latitude.toFixed(4)}, ${longitude.toFixed(4)})`,
        })
        setLocating(false)
      },
      () => {
        setError('Could not get your location - check your browser/OS location permission.')
        setLocating(false)
      },
    )
  }

  return (
    <div className="location-picker">
      <label htmlFor="location-query">Location (optional)</label>

      {value ? (
        <div className="selected-location">
          <span>{value.location_name}</span>
          <button type="button" className="link-btn" onClick={() => onChange(null)}>
            Clear
          </button>
        </div>
      ) : (
        <>
          <div className="location-picker-controls">
            <input
              id="location-query"
              type="text"
              placeholder="Search for a place..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <button type="button" onClick={useCurrentLocation} disabled={locating}>
              {locating ? 'Locating...' : 'Use my current location'}
            </button>
          </div>

          {loading && <p className="hint">Searching...</p>}
          {error && <p className="error">{error}</p>}

          {results.length > 0 && (
            <ul className="location-results">
              {results.map((place, i) => (
                // Nominatim results have no stable id in this response
                // shape - index is fine since this list is replaced whole
                // on every search, never patched in place.
                <li key={i}>
                  <button type="button" onClick={() => selectPlace(place)}>
                    {place.display_name}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  )
}
