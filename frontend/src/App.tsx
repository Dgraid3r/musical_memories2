import { useEffect, useState } from 'react'
import { deleteEntry, fetchEntries } from './api'
import { useAuth } from './auth/AuthContext'
import AuthForm from './components/AuthForm'
import EntryCard from './components/EntryCard'
import NewEntryForm from './components/NewEntryForm'
import SearchBar from './components/SearchBar'
import type { JournalEntry } from './types'
import './App.css'

export default function App() {
  const { user, token, loading: authLoading, logout } = useAuth()
  const [entries, setEntries] = useState<JournalEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  useEffect(() => {
    if (authLoading) return
    setLoading(true)
    fetchEntries(token, { q: searchQuery || undefined })
      .then(setEntries)
      .catch(() => setError('Could not load memories.'))
      .finally(() => setLoading(false))
  }, [token, authLoading, searchQuery])

  async function handleDelete(id: number) {
    if (!token) return
    await deleteEntry(id, token)
    setEntries((prev) => prev.filter((e) => e.id !== id))
  }

  function handleUpdated(updated: JournalEntry) {
    setEntries((prev) => prev.map((e) => (e.id === updated.id ? updated : e)))
  }

  if (authLoading) return null
  if (!user) return <AuthForm />

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <h1>Musical Memories</h1>
          <p>Journal entries tied to the playlists that go with them.</p>
        </div>
        <div className="account-bar">
          <span>{user.username}</span>
          <button type="button" className="link-btn" onClick={logout}>
            Log out
          </button>
        </div>
      </header>

      <main>
        <NewEntryForm onCreated={(entry) => setEntries((prev) => (searchQuery ? prev : [entry, ...prev]))} />

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
            <EntryCard key={entry.id} entry={entry} onDelete={handleDelete} onUpdated={handleUpdated} />
          ))}
        </section>
      </main>
    </div>
  )
}
