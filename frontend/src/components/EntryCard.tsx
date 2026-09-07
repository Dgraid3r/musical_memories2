import { useState } from 'react'
import { addImages, updateEntry } from '../api'
import { useAuth } from '../auth/AuthContext'
import type { JournalEntry } from '../types'
import CommentThread from './CommentThread'
import EntryPhoto from './EntryPhoto'
import TagInput from './TagInput'

interface Props {
  entry: JournalEntry
  workspaceId: number
  /** False for a subscriber or a public-browse (read-only) viewer. Entry-
   * specific owner/co-author actions (toggle visibility, delete, edit
   * tags, add photos) are already correctly hidden by isOwner/canEditContent
   * below regardless of this flag - a subscriber can never be an entry's
   * owner or co-author. This only needs threading through to the comment
   * thread, which can't tell "can comment" from ownership alone. */
  canWrite: boolean
  onDelete: (id: number) => void
  onUpdated: (entry: JournalEntry) => void
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

export default function EntryCard({ entry, workspaceId, canWrite, onDelete, onUpdated }: Props) {
  const { user, token } = useAuth()
  const [togglingVisibility, setTogglingVisibility] = useState(false)
  const [addingPhotos, setAddingPhotos] = useState(false)
  const [editingTags, setEditingTags] = useState(false)
  const [savingTags, setSavingTags] = useState(false)
  const [draftTags, setDraftTags] = useState<string[]>([])
  const isOwner = user?.id === entry.user_id
  const isCoauthor = entry.coauthors.some((c) => c.id === user?.id)
  const canEditContent = isOwner || isCoauthor

  async function toggleVisibility() {
    if (!token) return
    setTogglingVisibility(true)
    try {
      const updated = await updateEntry(workspaceId, entry.id, { is_public: !entry.is_public }, token)
      onUpdated(updated)
    } finally {
      setTogglingVisibility(false)
    }
  }

  function startEditingTags() {
    setDraftTags(entry.tags.map((t) => t.name))
    setEditingTags(true)
  }

  async function saveTags() {
    if (!token) return
    setSavingTags(true)
    try {
      const updated = await updateEntry(workspaceId, entry.id, { tags: draftTags }, token)
      onUpdated(updated)
      setEditingTags(false)
    } finally {
      setSavingTags(false)
    }
  }

  async function handleAddPhotos(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? [])
    e.target.value = ''
    if (!token || files.length === 0) return
    setAddingPhotos(true)
    try {
      const updated = await addImages(workspaceId, entry.id, files, token)
      onUpdated(updated)
    } finally {
      setAddingPhotos(false)
    }
  }

  return (
    <article className="entry-card">
      <header>
        <div>
          <time dateTime={entry.start_date}>{formatDateRange(entry.start_date, entry.end_date)}</time>
          {!isOwner && <span className="owner-tag"> &middot; {entry.owner_username}</span>}
          {entry.coauthors.length > 0 && (
            <span className="owner-tag"> with {entry.coauthors.map((c) => c.username).join(', ')}</span>
          )}
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

      {editingTags ? (
        <div className="tag-edit">
          <TagInput workspaceId={workspaceId} selected={draftTags} onChange={setDraftTags} />
          <div className="tag-edit-actions">
            <button type="button" onClick={saveTags} disabled={savingTags}>
              {savingTags ? 'Saving...' : 'Save tags'}
            </button>
            <button type="button" className="link-btn" onClick={() => setEditingTags(false)} disabled={savingTags}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="entry-tags-row">
          {entry.tags.length > 0 && (
            <ul className="entry-tag-chips">
              {entry.tags.map((tag) => (
                <li key={tag.id}>{tag.name}</li>
              ))}
            </ul>
          )}
          {canEditContent && (
            <button type="button" className="link-btn" onClick={startEditingTags}>
              {entry.tags.length > 0 ? 'Edit tags' : '+ Add tags'}
            </button>
          )}
        </div>
      )}

      {entry.images.length > 0 && (
        <div className="entry-images">
          {entry.images.map((image) => (
            <EntryPhoto key={image.id} entryId={entry.id} imageId={image.id} />
          ))}
        </div>
      )}

      {canEditContent && (
        <label className="add-photos-label">
          {addingPhotos ? 'Adding...' : '+ Add photos'}
          <input type="file" accept="image/*" multiple hidden onChange={handleAddPhotos} disabled={addingPhotos} />
        </label>
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

      <CommentThread workspaceId={workspaceId} entryId={entry.id} entryOwnerId={entry.user_id} canWrite={canWrite} />
    </article>
  )
}
