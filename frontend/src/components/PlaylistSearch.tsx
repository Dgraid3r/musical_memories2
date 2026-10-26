import { useEffect, useState } from 'react'
import { ApiError, fetchMyPlaylists, fetchSpotifyStatus, searchPlaylists } from '../api'
import { useAuth } from '../auth/AuthContext'
import type { PlaylistResult, SpotifyStatus } from '../types'
import CreatePlaylistPanel from './CreatePlaylistPanel'

interface Props {
  selected: PlaylistResult | null
  onSelect: (playlist: PlaylistResult) => void
}

export default function PlaylistSearch({ selected, onSelect }: Props) {
  const { token } = useAuth()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<PlaylistResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [spotifyStatus, setSpotifyStatus] = useState<SpotifyStatus | null>(null)
  const spotifyConnected = spotifyStatus?.connected ?? false
  const [mode, setMode] = useState<'search' | 'mine' | 'create'>('search')
  const [myPlaylists, setMyPlaylists] = useState<PlaylistResult[]>([])
  const [loadingMyPlaylists, setLoadingMyPlaylists] = useState(false)

  useEffect(() => {
    if (!token) return
    fetchSpotifyStatus(token)
      .then(setSpotifyStatus)
      .catch(() => setSpotifyStatus({ connected: false, can_create_playlists: false }))
  }, [token])

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
        .catch((err) =>
          setError(
            err instanceof ApiError ? err.message : 'Could not search Spotify. Check your API credentials.',
          ),
        )
        .finally(() => setLoading(false))
    }, 350)
    return () => clearTimeout(handle)
  }, [query])

  function showMine() {
    setMode('mine')
    if (myPlaylists.length === 0 && token) {
      setLoadingMyPlaylists(true)
      fetchMyPlaylists(token)
        .then(setMyPlaylists)
        .catch((err) =>
          setError(err instanceof ApiError ? err.message : 'Could not load your Spotify playlists.'),
        )
        .finally(() => setLoadingMyPlaylists(false))
    }
  }

  function handleCreated(playlist: PlaylistResult) {
    onSelect(playlist)
    setMode('search')
  }

  const listedPlaylists = mode === 'mine' ? myPlaylists : mode === 'search' ? results : []

  return (
    <div className="playlist-search">
      <label htmlFor="playlist-query">Spotify playlist</label>

      {token && (
        <div className="playlist-source-toggle">
          <button type="button" className={mode === 'search' ? 'active' : ''} onClick={() => setMode('search')}>
            Search Spotify
          </button>
          {spotifyConnected && (
            <button type="button" className={mode === 'mine' ? 'active' : ''} onClick={showMine}>
              My playlists
            </button>
          )}
          <button type="button" className={mode === 'create' ? 'active' : ''} onClick={() => setMode('create')}>
            Create new playlist
          </button>
        </div>
      )}

      {mode === 'create' && <CreatePlaylistPanel spotifyStatus={spotifyStatus} onCreated={handleCreated} />}

      {mode === 'search' && (
        <input
          id="playlist-query"
          type="text"
          placeholder="Search playlists..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      )}
      {(loading || loadingMyPlaylists) && <p className="hint">Loading...</p>}
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

      {listedPlaylists.length > 0 && (
        <ul className="playlist-results">
          {listedPlaylists.map((playlist) => (
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
