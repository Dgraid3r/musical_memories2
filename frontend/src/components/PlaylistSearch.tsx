import { useEffect, useState } from 'react'
import { searchPlaylists } from '../api'
import type { PlaylistResult } from '../types'

interface Props {
  selected: PlaylistResult | null
  onSelect: (playlist: PlaylistResult) => void
}

export default function PlaylistSearch({ selected, onSelect }: Props) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<PlaylistResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (query.trim().length < 2) {
      setResults([])
      return
    }
    const handle = setTimeout(() => {
      setLoading(true)
      setError(null)
      searchPlaylists(query)
        .then(setResults)
        .catch(() => setError('Could not search Spotify. Check your API credentials.'))
        .finally(() => setLoading(false))
    }, 350)
    return () => clearTimeout(handle)
  }, [query])

  return (
    <div className="playlist-search">
      <label htmlFor="playlist-query">Spotify playlist</label>
      <input
        id="playlist-query"
        type="text"
        placeholder="Search playlists..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {loading && <p className="hint">Searching...</p>}
      {error && <p className="error">{error}</p>}

      {selected && (
        <div className="selected-playlist">
          {selected.image_url && <img src={selected.image_url} alt="" />}
          <div>
            <strong>{selected.name}</strong>
            <span>by {selected.owner} &middot; {selected.track_count} track(s)</span>
          </div>
        </div>
      )}

      {results.length > 0 && (
        <ul className="playlist-results">
          {results.map((playlist) => (
            <li key={playlist.id}>
              <button type="button" onClick={() => onSelect(playlist)}>
                {playlist.image_url && <img src={playlist.image_url} alt="" />}
                <div>
                  <strong>{playlist.name}</strong>
                  <span>by {playlist.owner} &middot; {playlist.track_count} track(s)</span>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
