import { useEffect, useState } from 'react'
import { fetchEntries, fetchPublicWorkspaces } from '../api'
import type { JournalEntry, PublicWorkspace } from '../types'
import EntryCard from './EntryCard'

interface Props {
  onClose: () => void
}

/** Fully read-only, requires no login at all - browsing and reading a
 * public workspace's entries works with no auth token anywhere in here. */
export default function PublicWorkspaceBrowser({ onClose }: Props) {
  const [query, setQuery] = useState('')
  const [workspaces, setWorkspaces] = useState<PublicWorkspace[]>([])
  const [listLoading, setListLoading] = useState(true)
  const [selected, setSelected] = useState<PublicWorkspace | null>(null)
  const [entries, setEntries] = useState<JournalEntry[]>([])
  const [entriesLoading, setEntriesLoading] = useState(false)

  useEffect(() => {
    setListLoading(true)
    fetchPublicWorkspaces(query.trim() || undefined)
      .then(setWorkspaces)
      .catch(() => setWorkspaces([]))
      .finally(() => setListLoading(false))
  }, [query])

  useEffect(() => {
    if (!selected) return
    setEntriesLoading(true)
    fetchEntries(selected.id, null)
      .then(setEntries)
      .catch(() => setEntries([]))
      .finally(() => setEntriesLoading(false))
  }, [selected])

  return (
    <div className="app-shell public-browser">
      <header className="app-header">
        <div>
          <h1>Browse public journals</h1>
          <p>No account needed - these are shared openly by their owners.</p>
        </div>
        <button type="button" className="link-btn" onClick={onClose}>
          Back
        </button>
      </header>

      {!selected && (
        <main>
          <div className="search-bar">
            <input
              type="search"
              placeholder="Search public journals by name..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          {listLoading && <p>Loading...</p>}
          {!listLoading && workspaces.length === 0 && <p className="hint">No public journals found.</p>}

          <ul className="public-workspace-list">
            {workspaces.map((w) => (
              <li key={w.id}>
                <button type="button" onClick={() => setSelected(w)}>
                  {w.name}
                </button>
              </li>
            ))}
          </ul>
        </main>
      )}

      {selected && (
        <main>
          <button type="button" className="link-btn" onClick={() => setSelected(null)}>
            &larr; All public journals
          </button>
          <h2>{selected.name}</h2>

          <section className="entry-list">
            {entriesLoading && <p>Loading...</p>}
            {!entriesLoading && entries.length === 0 && <p className="hint">No public memories here yet.</p>}
            {entries.map((entry) => (
              <EntryCard
                key={entry.id}
                entry={entry}
                workspaceId={selected.id}
                canWrite={false}
                onDelete={() => {}}
                onUpdated={() => {}}
              />
            ))}
          </section>
        </main>
      )}
    </div>
  )
}
