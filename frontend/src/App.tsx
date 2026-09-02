import { useEffect, useState } from 'react'
import { deleteEntry, fetchEntries } from './api'
import EntryCard from './components/EntryCard'
import NewEntryForm from './components/NewEntryForm'
import type { JournalEntry } from './types'
import './App.css'

export default function App() {
  const [entries, setEntries] = useState<JournalEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchEntries()
      .then(setEntries)
      .catch(() => setError('Could not load your memories.'))
      .finally(() => setLoading(false))
  }, [])

  async function handleDelete(id: number) {
    await deleteEntry(id)
    setEntries((prev) => prev.filter((e) => e.id !== id))
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Musical Memories</h1>
        <p>Journal entries tied to the playlists that go with them.</p>
      </header>

      <main>
        <NewEntryForm onCreated={(entry) => setEntries((prev) => [entry, ...prev])} />

        <section className="entry-list">
          {loading && <p>Loading...</p>}
          {error && <p className="error">{error}</p>}
          {!loading && !error && entries.length === 0 && <p className="hint">No memories yet — add your first one above.</p>}
          {entries.map((entry) => (
            <EntryCard key={entry.id} entry={entry} onDelete={handleDelete} />
          ))}
        </section>
      </main>
    </div>
  )
}
