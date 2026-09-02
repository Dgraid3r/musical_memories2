import type { JournalEntry, PlaylistResult, User } from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function parseErrorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json()
    if (typeof body?.detail === 'string') return body.detail
  } catch {
    // response wasn't JSON - fall through to the generic message
  }
  return fallback
}

function authHeaders(token: string | null): HeadersInit {
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function registerUser(username: string, email: string, password: string): Promise<User> {
  const res = await fetch('/api/users', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, email, password }),
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Could not create account'))
  return res.json()
}

export async function login(username: string, password: string): Promise<string> {
  const res = await fetch('/api/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Login failed'))
  const data = await res.json()
  return data.access_token
}

export async function fetchCurrentUser(token: string): Promise<User> {
  const res = await fetch('/api/users/me', { headers: authHeaders(token) })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Session expired'))
  return res.json()
}

export async function fetchEntries(token: string | null): Promise<JournalEntry[]> {
  const res = await fetch('/api/entries', { headers: authHeaders(token) })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to load entries'))
  return res.json()
}

export async function deleteEntry(id: number, token: string): Promise<void> {
  const res = await fetch(`/api/entries/${id}`, { method: 'DELETE', headers: authHeaders(token) })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to delete entry'))
}

export async function updateEntry(
  id: number,
  updates: { text?: string; is_public?: boolean },
  token: string,
): Promise<JournalEntry> {
  const res = await fetch(`/api/entries/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify(updates),
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to update entry'))
  return res.json()
}

export async function searchPlaylists(query: string): Promise<PlaylistResult[]> {
  const res = await fetch(`/api/spotify/playlists?q=${encodeURIComponent(query)}`)
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Playlist search failed'))
  return res.json()
}

export interface NewEntryInput {
  entryDate: string
  text: string
  playlist: PlaylistResult
  images: File[]
  isPublic: boolean
}

export async function createEntry(input: NewEntryInput, token: string): Promise<JournalEntry> {
  const form = new FormData()
  form.set('entry_date', input.entryDate)
  form.set('text', input.text)
  form.set('playlist_id', input.playlist.id)
  form.set('playlist_name', input.playlist.name)
  form.set('playlist_url', input.playlist.url)
  if (input.playlist.image_url) form.set('playlist_image_url', input.playlist.image_url)
  form.set('is_public', String(input.isPublic))
  for (const image of input.images) form.append('images', image)

  const res = await fetch('/api/entries', { method: 'POST', headers: authHeaders(token), body: form })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to create entry'))
  return res.json()
}
