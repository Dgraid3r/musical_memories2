import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import EntryLocationMap from './EntryLocationMap'

// react-leaflet mounts a real Leaflet map, which drives the DOM through
// browser APIs (layout measurement, pointer/wheel handling, etc.) jsdom
// doesn't implement - not something a component test should exercise
// anyway. This stands in a minimal fake that renders enough plain DOM to
// assert against (the tile layer, and the marker's position/popup
// content) without needing a real map engine.
vi.mock('react-leaflet', () => ({
  MapContainer: ({ children, center, className }: { children?: React.ReactNode; center: [number, number]; className?: string }) => (
    <div data-testid="map-container" data-center={center.join(',')} className={className}>
      {children}
    </div>
  ),
  TileLayer: () => <div data-testid="tile-layer" />,
  Marker: ({ children, position }: { children?: React.ReactNode; position: [number, number] }) => (
    <div data-testid="marker" data-position={position.join(',')}>
      {children}
    </div>
  ),
  Popup: ({ children }: { children?: React.ReactNode }) => <div data-testid="popup">{children}</div>,
}))

describe('EntryLocationMap', () => {
  const props = { latitude: 40.7128, longitude: -74.006, locationName: 'New York, NY' }

  it('renders only the toggle until opened, with no map in the document', () => {
    render(<EntryLocationMap {...props} />)

    expect(screen.getByRole('button', { name: 'View on map' })).toBeInTheDocument()
    expect(screen.queryByTestId('map-container')).not.toBeInTheDocument()
  })

  it('opens the map (with the marker at the given coordinates and its popup label) on click, and closes again on a second click', () => {
    render(<EntryLocationMap {...props} />)
    const toggle = screen.getByRole('button', { name: 'View on map' })

    fireEvent.click(toggle)

    expect(screen.getByRole('button', { name: 'Hide map' })).toBeInTheDocument()
    const marker = screen.getByTestId('marker')
    expect(marker).toHaveAttribute('data-position', '40.7128,-74.006')
    expect(screen.getByTestId('map-container')).toHaveAttribute('data-center', '40.7128,-74.006')
    expect(screen.getByTestId('popup')).toHaveTextContent('New York, NY')

    fireEvent.click(screen.getByRole('button', { name: 'Hide map' }))

    expect(screen.getByRole('button', { name: 'View on map' })).toBeInTheDocument()
    expect(screen.queryByTestId('map-container')).not.toBeInTheDocument()
  })
})
