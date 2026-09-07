import type {
  Comment,
  InvitePreview,
  JournalEntry,
  PlaylistResult,
  PublicWorkspace,
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

/** No auth required - public discovery. */
export async function fetchPublicWorkspaces(q?: string): Promise<PublicWorkspace[]> {
  const qs = q ? `?q=${encodeURIComponent(q)}` : ''
  const res = await fetch(`/api/workspaces/public${qs}`)
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

// --- Entries (workspace-scoped) -----------------------------------------

export interface EntrySearchParams {
  q?: string
  tag?: string
}

export async function fetchEntries(
  workspaceId: number,
  token: string | null,
  params: EntrySearchParams = {},
): Promise<JournalEntry[]> {
  const query = new URLSearchParams()
  if (params.q) query.set('q', params.q)
  if (params.tag) query.set('tag', params.tag)
  const qs = query.toString()
  const res = await fetch(`/api/workspaces/${workspaceId}/entries${qs ? `?${qs}` : ''}`, {
    headers: authHeaders(token),
  })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to load entries'))
  return res.json()
}

export async function fetchTags(workspaceId: number, token: string | null): Promise<string[]> {
  const res = await fetch(`/api/workspaces/${workspaceId}/entries/tags`, { headers: authHeaders(token) })
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res, 'Failed to load tags'))
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
  updates: { text?: string; is_public?: boolean; coauthor_usernames?: string[]; tags?: string[] },
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
