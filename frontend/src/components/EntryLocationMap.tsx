import { useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { MapContainer, Marker, Popup, TileLayer } from 'react-leaflet'

interface Props {
  latitude: number
  longitude: number
  locationName: string
}

function pinIcon(): L.DivIcon {
  return L.divIcon({
    className: 'map-marker map-marker-generic',
    html: '<div class="map-marker-pin"></div>',
    iconSize: [22, 22],
    iconAnchor: [11, 22],
    popupAnchor: [0, -22],
  })
}

/** A small, collapsed-by-default single-pin map for one entry's location -
 * replaces the old full-page map view (formerly components/MapView.tsx,
 * which plotted every located entry in a workspace at once). Instead, each
 * entry that has a location gets this inline toggle, and the map itself
 * (and its tile requests) is only created once someone actually opens it,
 * so an entry list full of located entries stays light by default.
 *
 * Used from EntryCard.tsx (so it works anywhere EntryCard is rendered - the
 * authenticated feed and the no-login public workspace browser, both of
 * which already receive this entry's coordinates from the backend) and
 * from SharedEntryView.tsx's standalone single-shared-entry page, which
 * gets latitude/longitude from the same `GET /api/shared/{token}` response
 * it already renders location_name from. */
export default function EntryLocationMap({ latitude, longitude, locationName }: Props) {
  const [open, setOpen] = useState(false)

  return (
    <span className="entry-location-map">
      <button
        type="button"
        className="link-btn entry-location-map-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {open ? 'Hide map' : 'View on map'}
      </button>
      {open && (
        <div className="entry-location-map-popup">
          <MapContainer
            center={[latitude, longitude]}
            zoom={12}
            className="entry-location-map-container"
            scrollWheelZoom={false}
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <Marker position={[latitude, longitude]} icon={pinIcon()}>
              <Popup>{locationName}</Popup>
            </Marker>
          </MapContainer>
        </div>
      )}
    </span>
  )
}
