import { useState } from 'react'
import type { NewOfflineDraft } from '../offlineDrafts'

interface Props {
  workspaceId: number
  onQueued: (draft: NewOfflineDraft) => Promise<void>
}

const today = () => new Date().toISOString().slice(0, 10)

/** The simplified entry-creation path offered when the browser has no
 * connectivity - text, date, tags, and photos only. Playlist, location,
 * and co-author search all require the network, and none of them
 * degrade to a useful offline experience (searching a stale local cache
 * would just be misleading), so they're not offered here at all -
 * they're addable afterward, once the draft has synced into a real
 * entry, through the normal full edit form (see EntryCard.tsx's
 * "+ Add playlist"/location/co-author controls). See NewEntryForm.tsx
 * for the online equivalent this replaces while offline. */
export default function OfflineEntryForm({ workspaceId, onQueued }: Props) {
  const [startDate, setStartDate] = useState(today())
  const [text, setText] = useState('')
  const [tagsInput, setTagsInput] = useState('')
  const [images, setImages] = useState<File[]>([])
  const [queuedNotice, setQueuedNotice] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    try {
      const tags = tagsInput
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean)
      const photos = images.map((file) => ({ name: file.name, type: file.type, blob: file }))
      await onQueued({ workspaceId, text, startDate, tags, photos })
      setStartDate(today())
      setText('')
      setTagsInput('')
      setImages([])
      setQueuedNotice(true)
      setTimeout(() => setQueuedNotice(false), 4000)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="new-entry-form offline-entry-form" onSubmit={handleSubmit}>
      <h2>New memory</h2>
      <p className="offline-banner">
        You're offline - this will save as a draft and sync when you're back online. Playlist, location, and
        co-author fields aren't available offline; add them afterward once it's synced.
      </p>

      <label htmlFor="offline-entry-date">Date</label>
      <input
        id="offline-entry-date"
        type="date"
        value={startDate}
        onChange={(e) => setStartDate(e.target.value)}
        required
      />

      <label htmlFor="offline-entry-text">Journal entry</label>
      <textarea id="offline-entry-text" rows={5} value={text} onChange={(e) => setText(e.target.value)} />

      <label htmlFor="offline-entry-tags">Tags</label>
      <input
        id="offline-entry-tags"
        type="text"
        value={tagsInput}
        onChange={(e) => setTagsInput(e.target.value)}
        placeholder="roadtrip, summer (comma-separated)"
      />

      <label htmlFor="offline-entry-images">Photos</label>
      <input
        id="offline-entry-images"
        type="file"
        accept="image/*"
        multiple
        onChange={(e) => setImages(Array.from(e.target.files ?? []))}
      />

      {queuedNotice && <p className="hint">Saved as a draft - it'll sync once you're back online.</p>}

      <button type="submit" disabled={submitting}>
        {submitting ? 'Saving draft...' : 'Save as draft'}
      </button>
    </form>
  )
}
