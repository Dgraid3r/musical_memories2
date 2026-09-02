import type { JournalEntry, PlaylistResult } from './types'

export async function fetchEntries(): Promise<JournalEntry[]> {
  const res = await fetch('/api/entries')
  if (!res.ok) throw new Error('Failed to load entries')
  return res.json()
}

export async function deleteEntry(id: number): Promise<void> {
  const res = await fetch(`/api/entries/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to delete entry')
}

export async function searchPlaylists(query: string): Promise<PlaylistResult[]> {
  const res = await fetch(`/api/spotify/playlists?q=${encodeURIComponent(query)}`)
  if (!res.ok) throw new Error('Playlist search failed')
  return res.json()
}

export interface NewEntryInput {
  entryDate: string
  text: string
  playlist: PlaylistResult
  images: File[]
}

export async function createEntry(input: NewEntryInput): Promise<JournalEntry> {
  const form = new FormData()
  form.set('entry_date', input.entryDate)
  form.set('text', input.text)
  form.set('playlist_id', input.playlist.id)
  form.set('playlist_name', input.playlist.name)
  form.set('playlist_url', input.playlist.url)
  if (input.playlist.image_url) form.set('playlist_image_url', input.playlist.image_url)
  for (const image of input.images) form.append('images', image)

  const res = await fetch('/api/entries', { method: 'POST', body: form })
  if (!res.ok) throw new Error('Failed to create entry')
  return res.json()
}
