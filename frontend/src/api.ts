import type {
  AdminStats,
  AdminUser,
  Comment,
  EntryEditEvent,
  EntryLocation,
  InvitePreview,
  JournalEntry,
  PlaceResult,
  PlaylistResult,
  PublicWorkspace,
  PublicWorkspaceSort,
  User,
  UserPublic,
  Workspace,
  WorkspaceInvite,
  WorkspaceMember,
  WorkspaceRole,
  WorkspaceVisibility,
} from './types'

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

export async function registerUser(
  username: string,
  email: string,
  password: string,
  inviteToken?: string,
): Promise<User> {
  const res = await fetch('/api/users', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, email, password, invite_token: inviteToken || undefined }),
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

export async function searchUsers(query: string, token: string): Promise<UserPublic[]> {
  const res = await fetch(`/api/users?q=${encodeURIComponent(query)}`, { headers: authHeaders(token) })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'User search failed'))
  return res.json()
}

// --- Workspaces --------------------------------------------------------

export async function fetchWorkspaces(token: string): Promise<Workspace[]> {
  const res = await fetch('/api/workspaces', { headers: authHeaders(token) })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to load workspaces'))
  return res.json()
}

export async function createWorkspace(name: string, token: string): Promise<Workspace> {
  const res = await fetch('/api/workspaces', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ name }),
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to create workspace'))
  return res.json()
}

export async function deleteWorkspace(workspaceId: number, token: string): Promise<void> {
  const res = await fetch(`/api/workspaces/${workspaceId}`, { method: 'DELETE', headers: authHeaders(token) })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to delete workspace'))
}

export async function updateWorkspaceVisibility(
  workspaceId: number,
  visibility: WorkspaceVisibility,
  token: string,
): Promise<Workspace> {
  const res = await fetch(`/api/workspaces/${workspaceId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ visibility }),
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to update workspace visibility'))
  return res.json()
}

export interface PublicWorkspaceSearchParams {
  q?: string
  sort?: PublicWorkspaceSort
  limit?: number
  offset?: number
}

/** No auth required - public discovery. Server default (no `sort` sent) is
 * "active" (most recently active first); pass sort: 'name' for the old
 * alphabetical behavior. `offset` is how the caller pages through results
 * ("load more" - see PublicWorkspaceBrowser.tsx). */
export async function fetchPublicWorkspaces(params: PublicWorkspaceSearchParams = {}): Promise<PublicWorkspace[]> {
  const query = new URLSearchParams()
  if (params.q) query.set('q', params.q)
  if (params.sort) query.set('sort', params.sort)
  if (params.limit !== undefined) query.set('limit', String(params.limit))
  if (params.offset !== undefined) query.set('offset', String(params.offset))
  const qs = query.toString()
  const res = await fetch(`/api/workspaces/public${qs ? `?${qs}` : ''}`)
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to load public journals'))
  return res.json()
}

export async function fetchWorkspaceMembers(workspaceId: number, token: string): Promise<WorkspaceMember[]> {
  const res = await fetch(`/api/workspaces/${workspaceId}/members`, { headers: authHeaders(token) })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to load members'))
  return res.json()
}

export async function fetchWorkspaceInvites(workspaceId: number, token: string): Promise<WorkspaceInvite[]> {
  const res = await fetch(`/api/workspaces/${workspaceId}/invites`, { headers: authHeaders(token) })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to load pending invites'))
  return res.json()
}

export async function createWorkspaceInvite(
  workspaceId: number,
  email: string,
  role: Extract<WorkspaceRole, 'member' | 'subscriber'>,
  token: string,
): Promise<WorkspaceInvite> {
  const res = await fetch(`/api/workspaces/${workspaceId}/invites`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ email, role }),
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to send invite'))
  return res.json()
}

export async function revokeWorkspaceInvite(workspaceId: number, inviteId: number, token: string): Promise<void> {
  const res = await fetch(`/api/workspaces/${workspaceId}/invites/${inviteId}`, {
    method: 'DELETE',
    headers: authHeaders(token),
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to revoke invite'))
}

// --- Invite accept flow (not workspace-nested - the token resolves it) ---

export async function previewInvite(inviteToken: string): Promise<InvitePreview> {
  const res = await fetch(`/api/invites/${encodeURIComponent(inviteToken)}`)
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'This invite link is not valid'))
  return res.json()
}

export async function acceptInvite(inviteToken: string, token: string): Promise<WorkspaceMember> {
  const res = await fetch(`/api/invites/${encodeURIComponent(inviteToken)}/accept`, {
    method: 'POST',
    headers: authHeaders(token),
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Could not accept invite'))
  return res.json()
}

// --- Account: email verification and password reset ----------------------

export async function resendVerificationEmail(token: string): Promise<{ detail: string }> {
  const res = await fetch('/api/account/verify-email/resend', { method: 'POST', headers: authHeaders(token) })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to resend verification email'))
  return res.json()
}

export async function confirmEmailVerification(verifyToken: string): Promise<User> {
  const res = await fetch(`/api/account/verify-email/${encodeURIComponent(verifyToken)}`, { method: 'POST' })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'This verification link is not valid'))
  return res.json()
}

export async function requestPasswordReset(email: string): Promise<{ detail: string }> {
  const res = await fetch('/api/account/password-reset/request', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to request password reset'))
  return res.json()
}

export async function confirmPasswordReset(resetToken: string, newPassword: string): Promise<{ detail: string }> {
  const res = await fetch(`/api/account/password-reset/${encodeURIComponent(resetToken)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_password: newPassword }),
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'This reset link is not valid'))
  return res.json()
}

/** Permanently deletes the caller's own account. Requires re-entering the
 * current password (see AccountDeleteInput). A 409 means the caller solely
 * owns a workspace that still has other members - its message names
 * exactly which workspace(s) need ownership transferred first via the
 * existing transferWorkspaceOwnership flow. */
export async function deleteAccount(password: string, token: string): Promise<{ detail: string }> {
  const res = await fetch('/api/account', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ password }),
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to delete account'))
  return res.json()
}

export async function updateWorkspaceMemberRole(
  workspaceId: number,
  userId: number,
  role: Extract<WorkspaceRole, 'member' | 'subscriber'>,
  token: string,
): Promise<WorkspaceMember> {
  const res = await fetch(`/api/workspaces/${workspaceId}/members/${userId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ role }),
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to update member role'))
  return res.json()
}

export async function removeWorkspaceMember(workspaceId: number, userId: number, token: string): Promise<void> {
  const res = await fetch(`/api/workspaces/${workspaceId}/members/${userId}`, {
    method: 'DELETE',
    headers: authHeaders(token),
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to remove member'))
}

/** Hands ownership to an existing member immediately - no accept step.
 * Returns the caller's own (now "member") WorkspaceOut. */
export async function transferWorkspaceOwnership(
  workspaceId: number,
  newOwnerUserId: number,
  token: string,
): Promise<Workspace> {
  const res = await fetch(`/api/workspaces/${workspaceId}/transfer-ownership`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ new_owner_user_id: newOwnerUserId }),
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to transfer ownership'))
  return res.json()
}

// --- Places (geocoding, backend-proxied) ----------------------------------

/** No auth required - same bar as Spotify's app-only playlist search.
 * Proxied through the backend rather than called directly (see
 * nominatim_client.py for why: a required User-Agent header and staying
 * within Nominatim's free-tier rate policy). */
export async function searchPlaces(query: string): Promise<PlaceResult[]> {
  const res = await fetch(`/api/places/search?q=${encodeURIComponent(query)}`)
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Place search failed'))
  return res.json()
}

/** Turns raw coordinates (from the browser's geolocation API) into a
 * human-readable place name, for "use my current location" - see
 * LocationPicker.tsx, which treats a failure here as non-fatal and falls
 * back to a coordinate-based label rather than blocking location picking
 * entirely. No auth required, same bar as searchPlaces. */
export async function reverseGeocode(latitude: number, longitude: number): Promise<{ display_name: string }> {
  const res = await fetch(`/api/places/reverse?lat=${latitude}&lon=${longitude}`)
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Reverse geocoding failed'))
  return res.json()
}

// --- Entries (workspace-scoped) -----------------------------------------

export interface EntrySearchParams {
  q?: string
  tag?: string
  /** Only entries with a location set - powers the map view. Same
   * visibility rules as every other entry listing. */
  locatedOnly?: boolean
  /** Same limit/offset pagination convention as fetchPublicWorkspaces
   * above - `offset` is how the caller pages through results ("load
   * more" - see App.tsx's entry list). Omitting `limit` gets the
   * backend's own default page size. */
  limit?: number
  offset?: number
}

export async function fetchEntries(
  workspaceId: number,
  token: string | null,
  params: EntrySearchParams = {},
): Promise<JournalEntry[]> {
  const query = new URLSearchParams()
  if (params.q) query.set('q', params.q)
  if (params.tag) query.set('tag', params.tag)
  if (params.locatedOnly) query.set('located_only', 'true')
  if (params.limit !== undefined) query.set('limit', String(params.limit))
  if (params.offset !== undefined) query.set('offset', String(params.offset))
  const qs = query.toString()
  const res = await fetch(`/api/workspaces/${workspaceId}/entries${qs ? `?${qs}` : ''}`, {
    headers: authHeaders(token),
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to load entries'))
  return res.json()
}

/** The only way to fetch an entry photo's bytes - permission-checked on
 * the backend exactly like the entry itself (see
 * GET /api/entries/{entry_id}/images/{image_id}), unlike the old raw
 * /uploads/... static URL. A plain <img src> can't carry the
 * Authorization header a private entry's photo requires, so callers
 * fetch the blob themselves and hand the resulting object URL to <img>
 * instead - see EntryPhoto.tsx. */
export async function fetchEntryImageBlob(entryId: number, imageId: number, token: string | null): Promise<Blob> {
  const res = await fetch(`/api/entries/${entryId}/images/${imageId}`, { headers: authHeaders(token) })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to load photo'))
  return res.blob()
}

export async function fetchTags(workspaceId: number, token: string | null): Promise<string[]> {
  const res = await fetch(`/api/workspaces/${workspaceId}/entries/tags`, { headers: authHeaders(token) })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to load tags'))
  return res.json()
}

/** Audit log only - who edited this entry and when, plus a short label
 * (e.g. "content", "tags"), most-recent-first. Same visibility rule as the
 * entry itself (404 if the caller can't see the entry), no separate
 * permission check. */
export async function fetchEntryEditHistory(
  workspaceId: number,
  id: number,
  token: string | null,
): Promise<EntryEditEvent[]> {
  const res = await fetch(`/api/workspaces/${workspaceId}/entries/${id}/edit-history`, {
    headers: authHeaders(token),
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to load edit history'))
  return res.json()
}

export async function deleteEntry(workspaceId: number, id: number, token: string): Promise<void> {
  const res = await fetch(`/api/workspaces/${workspaceId}/entries/${id}`, {
    method: 'DELETE',
    headers: authHeaders(token),
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to delete entry'))
}

export async function updateEntry(
  workspaceId: number,
  id: number,
  updates: {
    text?: string
    is_public?: boolean
    coauthor_usernames?: string[]
    tags?: string[]
    // Omit this key entirely to leave the location unchanged (the usual
    // case for e.g. a text-only edit); pass null to clear it; pass an
    // EntryLocation to set it. JSON.stringify below preserves exactly
    // that distinction - an omitted (undefined) key never appears in the
    // request body, while an explicit null does - matching the backend's
    // model_fields_set check (see routers/entries.py update_entry).
    location?: EntryLocation | null
  },
  token: string,
): Promise<JournalEntry> {
  const res = await fetch(`/api/workspaces/${workspaceId}/entries/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify(updates),
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to update entry'))
  return res.json()
}

export async function addImages(workspaceId: number, id: number, images: File[], token: string): Promise<JournalEntry> {
  const form = new FormData()
  for (const image of images) form.append('images', image)

  const res = await fetch(`/api/workspaces/${workspaceId}/entries/${id}/images`, {
    method: 'POST',
    headers: authHeaders(token),
    body: form,
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to add photos'))
  return res.json()
}

export interface NewEntryInput {
  startDate: string
  endDate: string
  text: string
  playlist: PlaylistResult
  images: File[]
  isPublic: boolean
  coauthorUsernames: string[]
  tags: string[]
  location: EntryLocation | null
}

export async function createEntry(workspaceId: number, input: NewEntryInput, token: string): Promise<JournalEntry> {
  const form = new FormData()
  form.set('start_date', input.startDate)
  form.set('end_date', input.endDate)
  form.set('text', input.text)
  form.set('playlist_id', input.playlist.id)
  form.set('playlist_name', input.playlist.name)
  form.set('playlist_url', input.playlist.url)
  if (input.playlist.image_url) form.set('playlist_image_url', input.playlist.image_url)
  form.set('is_public', String(input.isPublic))
  for (const username of input.coauthorUsernames) form.append('coauthor_usernames', username)
  for (const tag of input.tags) form.append('tags', tag)
  for (const image of input.images) form.append('images', image)
  if (input.location) {
    form.set('latitude', String(input.location.latitude))
    form.set('longitude', String(input.location.longitude))
    form.set('location_name', input.location.location_name)
  }

  const res = await fetch(`/api/workspaces/${workspaceId}/entries`, {
    method: 'POST',
    headers: authHeaders(token),
    body: form,
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to create entry'))
  return res.json()
}

// --- Comments (nested under workspace-scoped entries; edit/delete are not) -

export async function fetchComments(workspaceId: number, entryId: number, token: string | null): Promise<Comment[]> {
  const res = await fetch(`/api/workspaces/${workspaceId}/entries/${entryId}/comments`, {
    headers: authHeaders(token),
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to load comments'))
  return res.json()
}

export async function createComment(
  workspaceId: number,
  entryId: number,
  input: { body: string; parent_comment_id?: number | null },
  token: string,
): Promise<Comment> {
  const res = await fetch(`/api/workspaces/${workspaceId}/entries/${entryId}/comments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify(input),
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to post comment'))
  return res.json()
}

export async function updateComment(commentId: number, body: string, token: string): Promise<Comment> {
  const res = await fetch(`/api/comments/${commentId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ body }),
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to update comment'))
  return res.json()
}

export async function deleteComment(commentId: number, token: string): Promise<void> {
  const res = await fetch(`/api/comments/${commentId}`, { method: 'DELETE', headers: authHeaders(token) })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to delete comment'))
}

// --- Spotify -------------------------------------------------------------

export async function searchPlaylists(query: string): Promise<PlaylistResult[]> {
  const res = await fetch(`/api/spotify/playlists?q=${encodeURIComponent(query)}`)
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Playlist search failed'))
  return res.json()
}

export async function fetchSpotifyStatus(token: string): Promise<{ connected: boolean }> {
  const res = await fetch('/api/spotify/status', { headers: authHeaders(token) })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to load Spotify status'))
  return res.json()
}

export async function getSpotifyConnectUrl(token: string): Promise<string> {
  const res = await fetch('/api/spotify/connect', { headers: authHeaders(token) })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to start Spotify connection'))
  const data = await res.json()
  return data.authorize_url
}

export async function fetchMyPlaylists(token: string): Promise<PlaylistResult[]> {
  const res = await fetch('/api/spotify/me/playlists', { headers: authHeaders(token) })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to load your playlists'))
  return res.json()
}

// --- Google sign-in --------------------------------------------------------

/** Whether "Sign in with Google" is available at all - opt-in like every
 * other external integration in this app. No auth required (this runs
 * before anyone can be logged in) - AuthForm.tsx uses it to decide
 * whether to show the button at all. Starting the flow itself is a plain
 * browser navigation to GET /api/auth/google/login, not a fetch - see
 * AuthForm.tsx. */
export async function fetchGoogleSignInConfig(): Promise<{ enabled: boolean }> {
  const res = await fetch('/api/auth/google/config')
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to load sign-in options'))
  return res.json()
}

// --- Admin dashboard (admin-only; see AuthContext's user.is_admin) --------

export interface AdminUserSearchParams {
  q?: string
  limit?: number
  offset?: number
}

export async function fetchAdminUsers(params: AdminUserSearchParams, token: string): Promise<AdminUser[]> {
  const query = new URLSearchParams()
  if (params.q) query.set('q', params.q)
  if (params.limit !== undefined) query.set('limit', String(params.limit))
  if (params.offset !== undefined) query.set('offset', String(params.offset))
  const qs = query.toString()
  const res = await fetch(`/api/admin/users${qs ? `?${qs}` : ''}`, { headers: authHeaders(token) })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to load users'))
  return res.json()
}

export async function deactivateAdminUser(userId: number, token: string): Promise<void> {
  const res = await fetch(`/api/admin/users/${userId}/deactivate`, {
    method: 'POST',
    headers: authHeaders(token),
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to deactivate account'))
}

export async function reactivateAdminUser(userId: number, token: string): Promise<void> {
  const res = await fetch(`/api/admin/users/${userId}/reactivate`, {
    method: 'POST',
    headers: authHeaders(token),
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to reactivate account'))
}

export async function fetchAdminStats(token: string): Promise<AdminStats> {
  const res = await fetch('/api/admin/stats', { headers: authHeaders(token) })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to load stats'))
  return res.json()
}
