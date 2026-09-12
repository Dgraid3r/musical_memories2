import { useEffect, useState } from 'react'
import { ApiError, fetchSharedRecap } from '../api'
import type { WorkspaceRecap } from '../types'
import RecapCards from './RecapCards'

interface Props {
  token: string
}

/** The destination a `?shared-recap=<token>` link lands on (see
 * App.tsx) - standalone, read-only, no login, no navigation back into
 * the rest of the app, the same shape as SharedEntryView but one level
 * up (a whole workspace+year summary instead of a single entry). */
export default function SharedRecapView({ token }: Props) {
  const [recap, setRecap] = useState<WorkspaceRecap | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    fetchSharedRecap(token)
      .then((result) => {
        if (!cancelled) setRecap(result)
      })
      .catch((err) => {
        if (cancelled) return
        setError(
          err instanceof ApiError && err.status === 404
            ? 'This shared link is no longer valid - it may have been revoked.'
            : 'Could not load this recap.',
        )
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [token])

  return (
    <div className="app-shell shared-entry-shell">
      <header className="app-header">
        <div>
          <h1>Musical Memories</h1>
          <p>A shared year in review.</p>
        </div>
      </header>

      <main>
        {loading && <p>Loading...</p>}
        {!loading && error && <p className="error">{error}</p>}
        {!loading && !error && recap && <RecapCards recap={recap} heading={`${recap.year} in review`} />}
      </main>
    </div>
  )
}
