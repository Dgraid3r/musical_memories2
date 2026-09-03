import { useEffect, useState } from 'react'
import { deleteEntry, fetchEntries } from './api'
import { useAuth } from './auth/AuthContext'
import AuthForm from './components/AuthForm'
import EntryCard from './components/EntryCard'
import NewEntryForm from './components/NewEntryForm'
import PublicWorkspaceBrowser from './components/PublicWorkspaceBrowser'
import SearchBar from './components/SearchBar'
import SpotifyConnect from './components/SpotifyConnect'
import WorkspaceSettings from './components/WorkspaceSettings'
import WorkspaceSwitcher from './components/WorkspaceSwitcher'
import type { JournalEntry } from './types'
import { useWorkspace } from './workspace/WorkspaceContext'
import './App.css'

function useSpotifyCallbackNotice(): string | null {
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const spotifyResult = params.get('spotify')
    if (!spotifyResult) return

    setNotice(
      spotifyResult === 'connected'
        ? 'Spotify account connected.'
        : 'Spotify connection was not completed.',
    )
    params.delete('spotify')
    const rest = params.toString()
    window.history.replaceState({}, '', window.location.pathname + (rest ? `?${rest}` : ''))
  }, [])

  return notice
}

export default function App() {
  const { user, token, loading: authLoading, logout } = useAuth()
  const { activeWorkspace, loading: workspaceLoading, error: workspaceError } = useWorkspace()
  const [entries, setEntries] = useState<JournalEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [showPublicBrowser, setShowPublicBrowser] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const spotifyNotice = useSpotifyCallbackNotice()

  useEffect(() => {
    if (authLoading || !activeWorkspace) return
    setLoading(true)
    fetchEntries(activeWorkspace.id, token, { q: searchQuery || undefined })
      .then(setEntries)
      .catch(() => setError('Could not load memories.'))
      .finally(() => setLoading(false))
  }, [token, authLoading, activeWorkspace, searchQuery])

  async function handleDelete(id: number) {
    if (!token || !activeWorkspace) return
    await deleteEntry(activeWorkspace.id, id, token)
    setEntries((prev) => prev.filter((e) => e.id !== id))
  }

  function handleUpdated(updated: JournalEntry) {
    setEntries((prev) => prev.map((e) => (e.id === updated.id ? updated : e)))
  }

  if (authLoading) return null

  if (showPublicBrowser) {
    return <PublicWorkspaceBrowser onClose={() => setShowPublicBrowser(false)} />
  }

  if (!user) {
    return (
      <>
        <AuthForm />
        <p className="public-browse-link">
          <button type="button" className="link-btn" onClick={() => setShowPublicBrowser(true)}>
            Browse public journals without logging in
          </button>
        </p>
      </>
    )
  }

  // A subscriber can read everything in the active workspace but can't
  // create entries, add photos, or comment - the entry-specific
  // owner/co-author actions inside EntryCard are already correctly hidden
  // for a subscriber on their own (they can never own or co-author an
  // entry), so this flag only needs to gate the "new memory" form here and
  // the comment box inside each EntryCard.
  const canWrite = activeWorkspace?.role !== 'subscriber'

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <h1>Musical Memories</h1>
          <p>Journal entries tied to the playlists that go with them.</p>
        </div>
        <div className="account-bar">
          <WorkspaceSwitcher />
          {activeWorkspace && (
            <button type="button" className="link-btn" onClick={() => setShowSettings(true)}>
              Settings
            </button>
          )}
          <button type="button" className="link-btn" onClick={() => setShowPublicBrowser(true)}>
            Browse public
          </button>
          <span>{user.username}</span>
          <SpotifyConnect />
          <button type="button" className="link-btn" onClick={logout}>
            Log out
          </button>
        </div>
      </header>

      {spotifyNotice && <p className="hint spotify-notice">{spotifyNotice}</p>}

      {showSettings && activeWorkspace && <WorkspaceSettings onClose={() => setShowSettings(false)} />}

      <main>
        {workspaceLoading && <p>Loading workspaces...</p>}
        {!workspaceLoading && workspaceError && <p className="error">{workspaceError}</p>}
        {!workspaceLoading && !workspaceError && !activeWorkspace && (
          <p className="hint">
            You don't belong to a workspace yet - create one above to start adding memories.
          </p>
        )}

        {activeWorkspace && (
          <>
            {canWrite && (
              <NewEntryForm
                workspaceId={activeWorkspace.id}
                onCreated={(entry) => setEntries((prev) => (searchQuery ? prev : [entry, ...prev]))}
              />
            )}
            {!canWrite && (
              <p className="hint subscriber-notice">
                You're a subscriber here - you can read everything, but only an owner or member can add or edit
                memories.
              </p>
            )}

            <SearchBar onSearch={setSearchQuery} />

            <section className="entry-list">
              {loading && <p>Loading...</p>}
              {error && <p className="error">{error}</p>}
              {!loading && !error && entries.length === 0 && searchQuery && (
                <p className="hint">No memories match "{searchQuery}".</p>
              )}
              {!loading && !error && entries.length === 0 && !searchQuery && (
                <p className="hint">No memories yet — add your first one above.</p>
              )}
              {entries.map((entry) => (
                <EntryCard
                  key={entry.id}
                  entry={entry}
                  workspaceId={activeWorkspace.id}
                  canWrite={canWrite}
                  onDelete={handleDelete}
                  onUpdated={handleUpdated}
                />
              ))}
            </section>
          </>
        )}
      </main>
    </div>
  )
}
