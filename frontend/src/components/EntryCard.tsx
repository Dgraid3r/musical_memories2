import { useState } from 'react'
import { updateEntry } from '../api'
import { useAuth } from '../auth/AuthContext'
import type { JournalEntry } from '../types'

interface Props {
  entry: JournalEntry
  onDelete: (id: number) => void
  onUpdated: (entry: JournalEntry) => void
}

export default function EntryCard({ entry, onDelete, onUpdated }: Props) {
  const { user, token } = useAuth()
  const [togglingVisibility, setTogglingVisibility] = useState(false)
  const isOwner = user?.id === entry.user_id

  async function toggleVisibility() {
    if (!token) return
    setTogglingVisibility(true)
    try {
      const updated = await updateEntry(entry.id, { is_public: !entry.is_public }, token)
      onUpdated(updated)
    } finally {
      setTogglingVisibility(false)
    }
  }

  return (
    <article className="entry-card">
      <header>
        <div>
          <time dateTime={entry.entry_date}>
            {new Date(entry.entry_date + 'T00:00:00').toLocaleDateString(undefined, {
              year: 'numeric',
              month: 'long',
              day: 'numeric',
            })}
          </time>
          {!isOwner && <span className="owner-tag"> &middot; {entry.owner_username}</span>}
          <span className={`visibility-badge ${entry.is_public ? 'public' : 'private'}`}>
            {entry.is_public ? 'Public' : 'Private'}
          </span>
        </div>
        {isOwner && (
          <div className="entry-actions">
            <button type="button" onClick={toggleVisibility} disabled={togglingVisibility}>
              Make {entry.is_public ? 'private' : 'public'}
            </button>
            <button type="button" className="delete-btn" onClick={() => onDelete(entry.id)}>
              Delete
            </button>
          </div>
        )}
      </header>

      {entry.text && <p className="entry-text">{entry.text}</p>}

      {entry.images.length > 0 && (
        <div className="entry-images">
          {entry.images.map((image) => (
            <img key={image.id} src={`/uploads/${image.filename}`} alt="" />
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
  )
}
