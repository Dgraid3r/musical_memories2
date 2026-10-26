import { useEffect, useState, type KeyboardEvent } from 'react'
import {
  ApiError,
  createSpotifyPlaylist,
  fetchPlaylistGeneratorStatus,
  generatePlaylistTracks,
  getSpotifyConnectUrl,
  searchTracks,
} from '../api'
import { useAuth } from '../auth/AuthContext'
import type { PlaylistResult, SpotifyStatus, SuggestedTrack, TrackResult } from '../types'

// Mirrors the backend's caps (schemas.py) so the UI stops the user before
// the server would reject the request.
const MAX_NAME_LENGTH = 100
const MAX_TRACKS = 100
const MAX_PROMPT_LENGTH = 300

const CONNECT_MESSAGE = 'Connect Spotify to create playlists.'
const RECONNECT_MESSAGE = 'Reconnect Spotify to create playlists.'

interface Props {
  /** The caller's Spotify link state, or null while it's still loading. */
  spotifyStatus: SpotifyStatus | null
  /** Receives the newly created playlist - the same callback the search
   * results use, so the entry links it like any other playlist. */
  onCreated: (playlist: PlaylistResult) => void
}

// The picker lives inside the entry <form>: Enter in one of this panel's
// inputs must not submit the whole entry.
function swallowEnter(e: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) {
  if (e.key === 'Enter' && !(e.target instanceof HTMLTextAreaElement)) e.preventDefault()
}

export default function CreatePlaylistPanel({ spotifyStatus, onCreated }: Props) {
  const { token } = useAuth()
  const [name, setName] = useState('')
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<TrackResult[]>([])
  const [searching, setSearching] = useState(false)
  const [draft, setDraft] = useState<TrackResult[]>([])
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Set when the server says the account needs (re)connecting - renders
  // the connect button alongside the message.
  const [connectPrompt, setConnectPrompt] = useState<string | null>(null)
  const [connecting, setConnecting] = useState(false)

  const [generatorAvailable, setGeneratorAvailable] = useState(false)
  const [promptOpen, setPromptOpen] = useState(false)
  const [prompt, setPrompt] = useState('')
  const [generating, setGenerating] = useState(false)
  const [unmatched, setUnmatched] = useState<SuggestedTrack[]>([])

  useEffect(() => {
    let cancelled = false
    fetchPlaylistGeneratorStatus()
      .then((s) => !cancelled && setGeneratorAvailable(s.available))
      .catch(() => !cancelled && setGeneratorAvailable(false))
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    // Under two characters: nothing to search (and the stale results are
    // hidden at render time via `showResults`).
    if (query.trim().length < 2) return
    const handle = setTimeout(() => {
      setSearching(true)
      setError(null)
      searchTracks(query.trim())
        .then(setResults)
        .catch((err) => setError(err instanceof ApiError ? err.message : 'Could not search Spotify tracks.'))
        .finally(() => setSearching(false))
    }, 350)
    return () => clearTimeout(handle)
  }, [query])

  // Known up front from the status endpoint; a 409/403 from the server
  // (below) covers a status that changed since it loaded.
  const statusPrompt =
    spotifyStatus === null
      ? null
      : !spotifyStatus.connected
        ? CONNECT_MESSAGE
        : !spotifyStatus.can_create_playlists
          ? RECONNECT_MESSAGE
          : null
  const shownConnectPrompt = connectPrompt ?? statusPrompt

  const draftIds = new Set(draft.map((t) => t.id))
  const showResults = query.trim().length >= 2 && results.length > 0

  function addTracks(tracks: TrackResult[]) {
    setDraft((current) => {
      const ids = new Set(current.map((t) => t.id))
      const next = [...current]
      for (const track of tracks) {
        if (next.length >= MAX_TRACKS) break
        if (!ids.has(track.id)) {
          ids.add(track.id)
          next.push(track)
        }
      }
      return next
    })
  }

  function removeTrack(id: string) {
    setDraft((current) => current.filter((t) => t.id !== id))
  }

  async function handleConnect() {
    if (!token) return
    setConnecting(true)
    try {
      window.location.href = await getSpotifyConnectUrl(token)
    } catch (err) {
      setConnecting(false)
      setError(err instanceof ApiError ? err.message : 'Could not start the Spotify connection.')
    }
  }

  async function handleCreate() {
    if (!token) return
    setCreating(true)
    setError(null)
    try {
      const playlist = await createSpotifyPlaylist(
        name.trim(),
        draft.map((t) => t.uri),
        token,
      )
      onCreated(playlist)
      setName('')
      setDraft([])
      setQuery('')
      setUnmatched([])
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setConnectPrompt(CONNECT_MESSAGE)
      } else if (err instanceof ApiError && err.status === 403) {
        setConnectPrompt(RECONNECT_MESSAGE)
      } else {
        setError(err instanceof ApiError ? err.message : 'Could not create the playlist.')
      }
    } finally {
      setCreating(false)
    }
  }

  async function handleGenerate() {
    if (!token) return
    setGenerating(true)
    setError(null)
    try {
      const result = await generatePlaylistTracks(prompt.trim(), token)
      addTracks(result.matched)
      setUnmatched(result.unmatched)
      if (!name.trim()) setName(prompt.trim().slice(0, MAX_NAME_LENGTH))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not generate a playlist.')
    } finally {
      setGenerating(false)
    }
  }

  const canCreate =
    !!token && !shownConnectPrompt && name.trim().length > 0 && draft.length > 0 && !creating

  return (
    <div className="create-playlist-panel">
      {shownConnectPrompt && (
        <div className="create-playlist-connect" role="alert">
          <span>{shownConnectPrompt}</span>
          <button type="button" className="link-btn" onClick={handleConnect} disabled={connecting || !token}>
            {connecting
              ? 'Redirecting...'
              : shownConnectPrompt === RECONNECT_MESSAGE
                ? 'Reconnect Spotify'
                : 'Connect Spotify'}
          </button>
        </div>
      )}

      <label htmlFor="new-playlist-name">Playlist name</label>
      <input
        id="new-playlist-name"
        type="text"
        maxLength={MAX_NAME_LENGTH}
        placeholder="Name your playlist..."
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={swallowEnter}
      />

      {generatorAvailable && (
        <div className="create-playlist-generate">
          <button
            type="button"
            className="link-btn"
            aria-expanded={promptOpen}
            onClick={() => setPromptOpen((open) => !open)}
          >
            Generate from a prompt
          </button>
          {promptOpen && (
            <div className="create-playlist-prompt">
              <label htmlFor="new-playlist-prompt">Describe the mood or theme</label>
              <textarea
                id="new-playlist-prompt"
                rows={2}
                maxLength={MAX_PROMPT_LENGTH}
                placeholder="e.g. a rainy late-night drive through the city"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              />
              <button
                type="button"
                onClick={handleGenerate}
                disabled={generating || !prompt.trim() || !token}
              >
                {generating ? 'Generating...' : 'Suggest songs'}
              </button>
            </div>
          )}
        </div>
      )}

      <label htmlFor="new-playlist-track-query">Add tracks</label>
      <input
        id="new-playlist-track-query"
        type="text"
        placeholder="Search songs..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={swallowEnter}
      />
      {searching && <p className="hint">Searching...</p>}

      {showResults && (
        <ul className="playlist-results track-results" aria-label="Track search results">
          {results.map((track) => (
            <li key={track.id}>
              <button
                type="button"
                onClick={() => addTracks([track])}
                disabled={draftIds.has(track.id) || draft.length >= MAX_TRACKS}
                aria-label={`Add ${track.name} by ${track.artists}`}
              >
                {track.image_url && <img src={track.image_url} alt="" />}
                <div>
                  <strong>{track.name}</strong>
                  <span>{track.artists}</span>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}

      {unmatched.length > 0 && (
        <div className="create-playlist-unmatched">
          <p className="hint">Couldn't find these on Spotify:</p>
          <ul>
            {unmatched.map((s) => (
              <li key={`${s.title}|${s.artist}`}>
                {s.title} - {s.artist}
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="hint">
        {draft.length === 0 ? 'No tracks added yet.' : `${draft.length} track(s) in this playlist`}
      </p>
      {draft.length > 0 && (
        <ol className="create-playlist-draft" aria-label="Playlist tracks">
          {draft.map((track) => (
            <li key={track.id}>
              <span>
                <strong>{track.name}</strong> - {track.artists}
              </span>
              <button
                type="button"
                className="link-btn"
                onClick={() => removeTrack(track.id)}
                aria-label={`Remove ${track.name}`}
              >
                Remove
              </button>
            </li>
          ))}
        </ol>
      )}

      {error && <p className="error">{error}</p>}

      <button type="button" className="create-playlist-submit" onClick={handleCreate} disabled={!canCreate}>
        {creating ? 'Creating...' : 'Create playlist'}
      </button>
    </div>
  )
}
