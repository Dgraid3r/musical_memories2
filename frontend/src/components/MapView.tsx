import { useEffect, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { MapContainer, Marker, Popup, TileLayer, useMap } from 'react-leaflet'
import { fetchEntries, fetchEntryImageBlob } from '../api'
import { useAuth } from '../auth/AuthContext'
import type { JournalEntry } from '../types'

interface Props {
  workspaceId: number
  /** Called when the user clicks "View this memory" in a pin's popup -
   * the caller (App.tsx) is responsible for getting the user back to that
   * entry (closing the map and scrolling it into view). */
  onViewEntry: (entryId: number) => void
}

type LocatedEntry = JournalEntry & { latitude: number; longitude: number }

function isLocated(entry: JournalEntry): entry is LocatedEntry {
  return entry.latitude !== null && entry.longitude !== null
}

function genericPinIcon(): L.DivIcon {
  return L.divIcon({
    className: 'map-marker map-marker-generic',
    html: '<div class="map-marker-pin"></div>',
    iconSize: [22, 22],
    iconAnchor: [11, 22],
    popupAnchor: [0, -22],
  })
}

function photoIcon(src: string): L.DivIcon {
  return L.divIcon({
    className: 'map-marker map-marker-photo',
    html: `<img src="${src}" class="map-marker-thumb" alt="" />`,
    iconSize: [40, 40],
    iconAnchor: [20, 40],
    popupAnchor: [0, -40],
  })
}

/** Fits the map to every pin's position whenever the set of located
 * entries changes - a fixed center/zoom would either miss pins or sit
 * awkwardly on just the first one. */
function FitBounds({ positions }: { positions: [number, number][] }) {
  const map = useMap()

  useEffect(() => {
    if (positions.length === 0) return
    if (positions.length === 1) {
      map.setView(positions[0], 12)
    } else {
      map.fitBounds(L.latLngBounds(positions), { padding: [30, 30] })
    }
  }, [map, positions])

  return null
}

function EntryMarker({ entry, onViewEntry }: { entry: LocatedEntry; onViewEntry: (id: number) => void }) {
  const { token } = useAuth()
  const [icon, setIcon] = useState<L.DivIcon>(() => genericPinIcon())

  useEffect(() => {
    const firstImage = entry.images[0]
    if (!firstImage) return

    let objectUrl: string | null = null
    let cancelled = false

    // Same permission-checked image endpoint EntryPhoto.tsx uses - a
    // marker never gets a thumbnail for a photo the viewer couldn't
    // otherwise see (which can't actually happen here anyway, since this
    // entry already passed the same visibility check to appear on the
    // map at all, but reusing the real endpoint rather than assuming that
    // keeps this correct even if that ever changes).
    fetchEntryImageBlob(entry.id, firstImage.id, token)
      .then((blob) => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(blob)
        setIcon(photoIcon(objectUrl))
      })
      .catch(() => {
        // Falls back to (stays) the generic pin - no broken-image marker.
      })

    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [entry.id, entry.images, token])

  const truncatedText = entry.text && entry.text.length > 140 ? `${entry.text.slice(0, 140)}...` : entry.text

  return (
    <Marker position={[entry.latitude, entry.longitude]} icon={icon}>
      <Popup>
        <div className="map-popup">
          <strong>{entry.location_name}</strong>
          <div className="map-popup-date">{entry.start_date}</div>
          {truncatedText && <p>{truncatedText}</p>}
          <button type="button" onClick={() => onViewEntry(entry.id)}>
            View this memory
          </button>
        </div>
      </Popup>
    </Marker>
  )
}

/** Plots every located entry the caller can currently see (reuses the
 * exact same visibility rules as the entry list - see the located_only
 * filter on GET .../entries) as a pin, using each entry's first photo as
 * a small circular thumbnail marker, or a generic pin when it has none. */
export default function MapView({ workspaceId, onViewEntry }: Props) {
  const { token } = useAuth()
  const [entries, setEntries] = useState<JournalEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchEntries(workspaceId, token, { locatedOnly: true })
      .then(setEntries)
      .catch(() => setError('Could not load located memories.'))
      .finally(() => setLoading(false))
  }, [workspaceId, token])

  const located = entries.filter(isLocated)
  const positions: [number, number][] = located.map((e) => [e.latitude, e.longitude])

  return (
    <div className="map-view">
      {loading && <p>Loading map...</p>}
      {error && <p className="error">{error}</p>}
      {!loading && !error && located.length === 0 && (
        <p className="hint">
          No memories have a location yet - add one from a memory's "+ Add location" button, or when creating a new
          memory.
        </p>
      )}
      {!loading && !error && located.length > 0 && (
        <MapContainer center={positions[0]} zoom={2} className="map-view-container" scrollWheelZoom>
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <FitBounds positions={positions} />
          {located.map((entry) => (
            <EntryMarker key={entry.id} entry={entry} onViewEntry={onViewEntry} />
          ))}
        </MapContainer>
      )}
    </div>
  )
}
