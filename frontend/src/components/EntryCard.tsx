import { useState } from 'react'
import { addImages, disableEntrySharing, enableEntrySharing, updateEntry } from '../api'
import { useAuth } from '../auth/AuthContext'
import type { EntryLocation, JournalEntry, PlaylistResult } from '../types'
import CommentThread from './CommentThread'
import EntryEditHistory from './EntryEditHistory'
import EntryPhoto from './EntryPhoto'
import LocationPicker from './LocationPicker'
import PlaylistSearch from './PlaylistSearch'
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
  const [editingLocation, setEditingLocation] = useState(false)
  const [savingLocation, setSavingLocation] = useState(false)
  const [draftLocation, setDraftLocation] = useState<EntryLocation | null>(null)
  const [addingPlaylist, setAddingPlaylist] = useState(false)
  const [draftPlaylist, setDraftPlaylist] = useState<PlaylistResult | null>(null)
  const [savingPlaylist, setSavingPlaylist] = useState(false)
  const [showSharePanel, setShowSharePanel] = useState(false)
  const [shareLink, setShareLink] = useState<string | null>(null)
  const [shareBusy, setShareBusy] = useState(false)
  const [shareError, setShareError] = useState<string | null>(null)
  const [shareCopied, setShareCopied] = useState(false)
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

  /** Opens the share panel and (whether sharing was already on or not)
   * fetches the current token - enabling is idempotent server-side, so
   * this is also how "Copy link" re-displays an already-shared entry's
   * link without the frontend needing to persist the token anywhere
   * itself (see api.ts's enableEntrySharing / models.JournalEntry.
   * share_token's comment on why the token never comes back from the
   * ordinary entry-fetch endpoints). */
  async function openSharePanel() {
    if (!token) return
    setShowSharePanel(true)
    setShareError(null)
    setShareCopied(false)
    setShareBusy(true)
    try {
      const shareToken = await enableEntrySharing(workspaceId, entry.id, token)
      setShareLink(`${window.location.origin}/?shared=${shareToken}`)
      if (!entry.is_shared) onUpdated({ ...entry, is_shared: true })
    } catch {
      setShareError('Could not create a share link.')
    } finally {
      setShareBusy(false)
    }
  }

  async function copyShareLink() {
    if (!shareLink) return
    try {
      await navigator.clipboard.writeText(shareLink)
      setShareCopied(true)
    } catch {
      setShareError('Could not copy the link - you can select and copy it manually.')
    }
  }

  async function revokeSharing() {
    if (!token) return
    setShareBusy(true)
    setShareError(null)
    try {
      await disableEntrySharing(workspaceId, entry.id, token)
      setShareLink(null)
      setShowSharePanel(false)
      onUpdated({ ...entry, is_shared: false })
    } catch {
      setShareError('Could not turn off sharing.')
    } finally {
      setShareBusy(false)
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

  function startEditingLocation() {
    setDraftLocation(
      entry.latitude !== null && entry.longitude !== null && entry.location_name !== null
        ? { latitude: entry.latitude, longitude: entry.longitude, location_name: entry.location_name }
        : null,
    )
    setEditingLocation(true)
  }

  async function saveLocation() {
    if (!token) return
    setSavingLocation(true)
    try {
      const updated = await updateEntry(workspaceId, entry.id, { location: draftLocation }, token)
      onUpdated(updated)
      setEditingLocation(false)
    } finally {
      setSavingLocation(false)
    }
  }

  async function savePlaylist() {
    if (!token || !draftPlaylist) return
    setSavingPlaylist(true)
    try {
      const updated = await updateEntry(workspaceId, entry.id, { playlist: draftPlaylist }, token)
      onUpdated(updated)
      setAddingPlaylist(false)
      setDraftPlaylist(null)
    } finally {
      setSavingPlaylist(false)
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
    <article className="entry-card" id={`entry-${entry.id}`}>
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
            <button type="button" onClick={openSharePanel} disabled={shareBusy}>
              {entry.is_shared ? 'Sharing on' : 'Share'}
            </button>
            <button type="button" className="delete-btn" onClick={() => onDelete(entry.id)}>
              Delete
            </button>
          </div>
        )}
      </header>

      {isOwner && showSharePanel && (
        <div className="share-panel">
          <p className="hint">
            Anyone with this link can view this one memory - no login required. It doesn't make the rest of this
            workspace visible to anyone.
          </p>
          {shareBusy && !shareLink && <p>Preparing link...</p>}
          {shareLink && (
            <div className="share-link-row">
              <input type="text" readOnly value={shareLink} onFocus={(e) => e.target.select()} />
              <button type="button" onClick={copyShareLink}>
                {shareCopied ? 'Copied!' : 'Copy'}
              </button>
            </div>
          )}
          {shareError && <p className="error">{shareError}</p>}
          <div className="share-panel-actions">
            <button type="button" className="delete-btn" onClick={revokeSharing} disabled={shareBusy}>
              Turn off sharing
            </button>
            <button type="button" className="link-btn" onClick={() => setShowSharePanel(false)}>
              Close
            </button>
          </div>
        </div>
      )}

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

      {editingLocation ? (
        <div className="location-edit">
          <LocationPicker value={draftLocation} onChange={setDraftLocation} />
          <div className="location-edit-actions">
            <button type="button" onClick={saveLocation} disabled={savingLocation}>
              {savingLocation ? 'Saving...' : 'Save location'}
            </button>
            <button
              type="button"
              className="link-btn"
              onClick={() => setEditingLocation(false)}
              disabled={savingLocation}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="entry-location-row">
          {entry.location_name && <span className="entry-location-name">&#128205; {entry.location_name}</span>}
          {canEditContent && (
            <button type="button" className="link-btn" onClick={startEditingLocation}>
              {entry.location_name ? 'Edit location' : '+ Add location'}
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

      {entry.playlist_id ? (
        <iframe
          title={entry.playlist_name ?? undefined}
          src={`https://open.spotify.com/embed/playlist/${entry.playlist_id}`}
          width="100%"
          height="152"
          style={{ borderRadius: 12 }}
          allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
          loading="lazy"
        />
      ) : addingPlaylist ? (
        <div className="tag-edit">
          <PlaylistSearch selected={draftPlaylist} onSelect={setDraftPlaylist} />
          <div className="tag-edit-actions">
            <button type="button" onClick={savePlaylist} disabled={savingPlaylist || !draftPlaylist}>
              {savingPlaylist ? 'Saving...' : 'Save playlist'}
            </button>
            <button
              type="button"
              className="link-btn"
              onClick={() => {
                setAddingPlaylist(false)
                setDraftPlaylist(null)
              }}
              disabled={savingPlaylist}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        // No playlist yet - true for every entry synced from an offline
        // draft (see offlineDrafts.ts) until someone picks one here.
        canEditContent && (
          <p className="hint no-playlist-hint">
            No playlist yet.{' '}
            <button type="button" className="link-btn" onClick={() => setAddingPlaylist(true)}>
              + Add playlist
            </button>
          </p>
        )
      )}

      <CommentThread workspaceId={workspaceId} entryId={entry.id} entryOwnerId={entry.user_id} canWrite={canWrite} />
      <EntryEditHistory workspaceId={workspaceId} entryId={entry.id} />
    </article>
  )
}
