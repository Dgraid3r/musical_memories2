import { useEffect, useState } from 'react'
import { ApiError, fetchSharedEntry } from '../api'
import type { SharedEntry } from '../types'
import SharedEntryPhoto from './SharedEntryPhoto'

interface Props {
  token: string
}

function formatDate(iso: string): string {
  return new Date(iso + 'T00:00:00').toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

function formatDateRange(startDate: string, endDate: string): string {
  return startDate === endDate ? formatDate(startDate) : `${formatDate(startDate)} – ${formatDate(endDate)}`
}

/** The destination a `?shared=<token>` link lands on (see App.tsx) - a
 * standalone, read-only view of exactly one shared memory. No login, no
 * workspace switcher, no comments, no edit controls, and deliberately no
 * link back into the rest of the app: a shared link is meant to show
 * exactly one memory and nothing else, matching what the backend's
 * GET /api/shared/{token} itself already scopes down to. */
export default function SharedEntryView({ token }: Props) {
  const [entry, setEntry] = useState<SharedEntry | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    fetchSharedEntry(token)
      .then((result) => {
        if (!cancelled) setEntry(result)
      })
      .catch((err) => {
        if (cancelled) return
        setError(
          err instanceof ApiError && err.status === 404
            ? 'This shared link is no longer valid - it may have been revoked.'
            : 'Could not load this shared memory.',
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
          <p>A shared memory.</p>
        </div>
      </header>

      <main>
        {loading && <p>Loading...</p>}
        {!loading && error && <p className="error">{error}</p>}
        {!loading && !error && entry && (
          <article className="entry-card shared-entry-card">
            <header>
              <time dateTime={entry.start_date}>{formatDateRange(entry.start_date, entry.end_date)}</time>
            </header>

            {entry.text && <p className="entry-text">{entry.text}</p>}

            {entry.tags.length > 0 && (
              <ul className="entry-tag-chips">
                {entry.tags.map((tag) => (
                  <li key={tag.id}>{tag.name}</li>
                ))}
              </ul>
            )}

            {entry.location_name && (
              <div className="entry-location-row">
                <span className="entry-location-name">&#128205; {entry.location_name}</span>
              </div>
            )}

            {entry.images.length > 0 && (
              <div className="entry-images">
                {entry.images.map((image) => (
                  <SharedEntryPhoto key={image.id} token={token} imageId={image.id} />
                ))}
              </div>
            )}

            <iframe
              title={entry.playlist_name}
              src={`https://open.spotify.com/embed/playlist/${entry.playlist_id}`}
              width="100%"
              height="152"
              style={{ borderRadius: 12 }}
              allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
              loading="lazy"
            />
          </article>
        )}
      </main>
    </div>
  )
}
