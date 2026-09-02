import { useState } from 'react'
import { ApiError, createEntry } from '../api'
import { useAuth } from '../auth/AuthContext'
import type { JournalEntry, PlaylistResult } from '../types'
import CoAuthorPicker from './CoAuthorPicker'
import PlaylistSearch from './PlaylistSearch'

interface Props {
  onCreated: (entry: JournalEntry) => void
}

const today = () => new Date().toISOString().slice(0, 10)

export default function NewEntryForm({ onCreated }: Props) {
  const { token } = useAuth()
  const [startDate, setStartDate] = useState(today())
  const [spansMultipleDays, setSpansMultipleDays] = useState(false)
  const [endDate, setEndDate] = useState(today())
  const [text, setText] = useState('')
  const [playlist, setPlaylist] = useState<PlaylistResult | null>(null)
  const [images, setImages] = useState<File[]>([])
  const [isPublic, setIsPublic] = useState(false)
  const [coauthorUsernames, setCoauthorUsernames] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!playlist) {
      setError('Pick a Spotify playlist first.')
      return
    }
    const effectiveEndDate = spansMultipleDays ? endDate : startDate
    if (effectiveEndDate < startDate) {
      setError('End date cannot be before the start date.')
      return
    }
    if (!token) return
    setSubmitting(true)
    setError(null)
    try {
      const entry = await createEntry(
        { startDate, endDate: effectiveEndDate, text, playlist, images, isPublic, coauthorUsernames },
        token,
      )
      onCreated(entry)
      setText('')
      setPlaylist(null)
      setImages([])
      setIsPublic(false)
      setCoauthorUsernames([])
      setStartDate(today())
      setEndDate(today())
      setSpansMultipleDays(false)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save this memory. Try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="new-entry-form" onSubmit={handleSubmit}>
      <h2>New memory</h2>

      <label htmlFor="entry-start-date">{spansMultipleDays ? 'Start date' : 'Date'}</label>
      <input
        id="entry-start-date"
        type="date"
        value={startDate}
        onChange={(e) => setStartDate(e.target.value)}
        required
      />

      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={spansMultipleDays}
          onChange={(e) => setSpansMultipleDays(e.target.checked)}
        />
        This memory spans multiple days
      </label>

      {spansMultipleDays && (
        <>
          <label htmlFor="entry-end-date">End date</label>
          <input
            id="entry-end-date"
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            required
          />
        </>
      )}

      <label htmlFor="entry-text">Journal entry</label>
      <textarea
        id="entry-text"
        rows={5}
        placeholder="What does this playlist remind you of?"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />

      <PlaylistSearch selected={playlist} onSelect={setPlaylist} />

      <CoAuthorPicker selected={coauthorUsernames} onChange={setCoauthorUsernames} />

      <label htmlFor="entry-images">Photos</label>
      <input
        id="entry-images"
        type="file"
        accept="image/*"
        multiple
        onChange={(e) => setImages(Array.from(e.target.files ?? []))}
      />

      <label className="checkbox-label">
        <input type="checkbox" checked={isPublic} onChange={(e) => setIsPublic(e.target.checked)} />
        Make this memory public
      </label>

      {error && <p className="error">{error}</p>}

      <button type="submit" disabled={submitting}>
        {submitting ? 'Saving...' : 'Save memory'}
      </button>
    </form>
  )
}
