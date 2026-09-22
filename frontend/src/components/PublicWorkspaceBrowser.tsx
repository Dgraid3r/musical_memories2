import { useEffect, useState } from 'react'
import { ApiError, fetchEntries, fetchPublicWorkspaces } from '../api'
import type { JournalEntry, PublicWorkspace, PublicWorkspaceSort } from '../types'
import EntryCard from './EntryCard'

interface Props {
  onClose: () => void
}

const PAGE_SIZE = 20

function formatLastActive(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

/** Fully read-only, requires no login at all - browsing and reading a
 * public workspace's entries works with no auth token anywhere in here. */
export default function PublicWorkspaceBrowser({ onClose }: Props) {
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<PublicWorkspaceSort>('active')
  const [workspaces, setWorkspaces] = useState<PublicWorkspace[]>([])
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState<string | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const [selected, setSelected] = useState<PublicWorkspace | null>(null)
  const [entries, setEntries] = useState<JournalEntry[]>([])
  const [entriesLoading, setEntriesLoading] = useState(false)

  // A new search or sort choice starts over from the first page.
  useEffect(() => {
    setListLoading(true)
    setListError(null)
    fetchPublicWorkspaces({ q: query.trim() || undefined, sort, limit: PAGE_SIZE, offset: 0 })
      .then((page) => {
        setWorkspaces(page)
        setHasMore(page.length === PAGE_SIZE)
      })
      .catch((err) => {
        // Distinct from "genuinely zero public journals" - a failed
        // request (backend unreachable, blocked by the browser, etc.)
        // must never silently render the same "No public journals
        // found" empty state, or a real problem looks identical to
        // there just being nothing to browse.
        setWorkspaces([])
        setHasMore(false)
        setListError(err instanceof ApiError ? err.message : 'Could not load public journals. Please try again.')
      })
      .finally(() => setListLoading(false))
  }, [query, sort])

  async function loadMore() {
    setLoadingMore(true)
    setListError(null)
    try {
      const page = await fetchPublicWorkspaces({
        q: query.trim() || undefined,
        sort,
        limit: PAGE_SIZE,
        offset: workspaces.length,
      })
      setWorkspaces((prev) => [...prev, ...page])
      setHasMore(page.length === PAGE_SIZE)
    } catch (err) {
      setHasMore(false)
      setListError(err instanceof ApiError ? err.message : 'Could not load more public journals. Please try again.')
    } finally {
      setLoadingMore(false)
    }
  }

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

          <div className="public-workspace-sort" role="group" aria-label="Sort public journals">
            <button
              type="button"
              className={sort === 'active' ? 'sort-toggle-active' : 'link-btn'}
              onClick={() => setSort('active')}
            >
              Recently active
            </button>
            <button
              type="button"
              className={sort === 'name' ? 'sort-toggle-active' : 'link-btn'}
              onClick={() => setSort('name')}
            >
              Name
            </button>
          </div>

          {listLoading && <p>Loading...</p>}
          {listError && <p className="error">{listError}</p>}
          {!listLoading && !listError && workspaces.length === 0 && <p className="hint">No public journals found.</p>}

          <ul className="public-workspace-list">
            {workspaces.map((w) => (
              <li key={w.id}>
                <button type="button" onClick={() => setSelected(w)}>
                  <span className="public-workspace-name">{w.name}</span>
                  <span className="public-workspace-meta">
                    {w.entry_count} {w.entry_count === 1 ? 'memory' : 'memories'} &middot; active{' '}
                    {formatLastActive(w.last_active_at)}
                  </span>
                </button>
              </li>
            ))}
          </ul>

          {!listLoading && hasMore && (
            <button type="button" className="link-btn" onClick={loadMore} disabled={loadingMore}>
              {loadingMore ? 'Loading...' : 'Load more'}
            </button>
          )}
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
