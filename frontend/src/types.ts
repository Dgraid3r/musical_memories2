export interface EntryImage {
  id: number
}

export interface UserPublic {
  id: number
  username: string
}

export interface Tag {
  id: number
  name: string
}

export interface JournalEntry {
  id: number
  workspace_id: number
  user_id: number
  owner_username: string
  coauthors: UserPublic[]
  start_date: string
  end_date: string
  text: string | null
  is_public: boolean
  // All three null together - an offline-created draft (see
  // offlineDrafts.ts) syncs with no playlist at all, since picking one
  // needs Spotify search, which needs a connection the draft didn't have
  // when it was captured. Addable afterward via updateEntry's `playlist`
  // option.
  playlist_id: string | null
  playlist_name: string | null
  playlist_url: string | null
  playlist_image_url: string | null
  created_at: string
  images: EntryImage[]
  tags: Tag[]
  // All three null together (no location set) or all three set together -
  // never a partial location. Never inferred/captured automatically - see
  // LocationPicker.tsx.
  latitude: number | null
  longitude: number | null
  location_name: string | null
  // Whether a public single-entry share link currently exists - never the
  // actual token (see backend schemas.JournalEntryOut.is_shared). The
  // token itself is only ever returned from POST .../share, to the
  // primary author who just requested it.
  is_shared: boolean
}

/** The public, unauthenticated single-entry view fetched from
 * GET /api/shared/{token} - deliberately a separate, smaller shape than
 * JournalEntry: no id, no workspace, no author identity, nothing that
 * would let the viewer learn anything beyond this one memory. */
export interface SharedEntry {
  start_date: string
  end_date: string
  text: string | null
  playlist_id: string | null
  playlist_name: string | null
  playlist_url: string | null
  playlist_image_url: string | null
  latitude: number | null
  longitude: number | null
  location_name: string | null
  tags: Tag[]
  images: EntryImage[]
}

// A location as picked from place search or "use my current location" -
// the shape LocationPicker.tsx produces and PATCH .../entries/{id} (and
// the create form) send. Distinct from EntryImage etc. above in that this
// isn't itself a server response type - see PlaceResult below for that.
export interface EntryLocation {
  latitude: number
  longitude: number
  location_name: string
}

// What GET /api/places/search returns - never Nominatim's full raw
// response, just enough to plot a pin and label it.
export interface PlaceResult {
  display_name: string
  latitude: number
  longitude: number
}

export interface PlaylistResult {
  id: string
  name: string
  url: string
  image_url: string | null
  owner: string
  track_count: number
}

export interface User {
  id: number
  username: string
  email: string
  email_verified: boolean
  created_at: string
  // Site-wide admin flag - gates the admin dashboard nav link (see
  // App.tsx). Separate from any workspace-level role.
  is_admin: boolean
}

// One row of GET /api/admin/users - reuses the same "Deleted user"
// display-name masking as everywhere else for a deleted account.
export interface AdminUser {
  id: number
  username: string
  email: string
  created_at: string
  email_verified: boolean
  is_admin: boolean
  is_active: boolean
  is_deleted: boolean
}

export interface AdminBackupStatus {
  started_at: string
  succeeded: boolean
  error_message: string | null
}

export interface AdminStats {
  total_users: number
  total_workspaces: number
  total_entries: number
  new_signups_7d: number
  new_signups_30d: number
  database_healthy: boolean
  latest_backup: AdminBackupStatus | null
}

// One row of an entry's audit log (see GET .../entries/{id}/edit-history).
// Deliberately no old/new value - audit-log only, not version history.
export interface EntryEditEvent {
  id: number
  editor_user_id: number
  editor_username: string
  edited_at: string
  change_summary: string
}

export interface Comment {
  id: number
  entry_id: number
  author_id: number
  author_username: string
  parent_comment_id: number | null
  body: string
  created_at: string
  edited_at: string | null
  replies: Comment[]
}

export type WorkspaceVisibility = 'public' | 'private'
export type WorkspaceRole = 'owner' | 'member' | 'subscriber'

export interface Workspace {
  id: number
  name: string
  visibility: WorkspaceVisibility
  created_at: string
  created_by: number
  // The caller's own role in this workspace.
  role: WorkspaceRole
}

export interface WorkspaceMember {
  user_id: number
  username: string
  role: WorkspaceRole
}

export interface RecapTagCount {
  name: string
  count: number
}

// A playlist referenced by more than one entry in the recapped year -
// top_playlists is simply empty when nothing repeats.
export interface RecapPlaylistCount {
  playlist_id: string
  playlist_name: string
  playlist_image_url: string | null
  count: number
}

// The first/last entry of the recapped year, reduced to a glimpse -
// deliberately never text or photos, see backend schemas.WorkspaceRecapOut.
export interface RecapEntryHighlight {
  start_date: string
  // Null when this entry has no playlist yet - see JournalEntry's own
  // playlist_name comment.
  playlist_name: string | null
  playlist_image_url: string | null
}

// A workspace's "wrapped"-style yearly summary - aggregate stats only,
// identical shape whether fetched in-app (fetchWorkspaceRecap) or via a
// public share link (fetchSharedRecap). contributors/top_playlists are
// simply empty when that stat isn't interesting (a solo workspace, or no
// repeated playlist) rather than omitted or an error.
export interface WorkspaceRecap {
  year: number
  entry_count: number
  photo_count: number
  top_tags: RecapTagCount[]
  most_active_month: string | null
  first_entry: RecapEntryHighlight | null
  last_entry: RecapEntryHighlight | null
  contributors: UserPublic[]
  top_playlists: RecapPlaylistCount[]
}

export type PublicWorkspaceSort = 'active' | 'name'

// A public workspace as returned by the discovery endpoint - deliberately
// just enough to identify/browse to it, never entry content and never a
// caller-specific role (browsing needs no auth at all). entry_count and
// last_active_at are aggregates only (how much/how recent) - never
// anything about what's actually in an entry.
export interface PublicWorkspace {
  id: number
  name: string
  created_at: string
  entry_count: number
  last_active_at: string
}

export interface WorkspaceInvite {
  id: number
  email: string
  role: WorkspaceRole
  created_at: string
  expires_at: string
}

// The public preview shown before an invite is accepted - never includes
// the token itself, and account_exists tells the frontend whether to
// route the invitee to login or to registration.
export interface InvitePreview {
  workspace_id: number
  workspace_name: string
  email: string
  role: WorkspaceRole
  expires_at: string
  account_exists: boolean
}

// One row of GET /api/invites - invites currently pending for *my own*
// email, so a logged-in user has somewhere to see (and act on) an invite
// beyond just the emailed link. Unlike WorkspaceInvite above (what a
// workspace owner sees for invites they sent), this one includes the
// token - accepting it is POST /api/invites/{token}/accept, the same
// endpoint the emailed link itself uses.
export interface MyPendingInvite {
  token: string
  workspace_id: number
  workspace_name: string
  role: WorkspaceRole
  inviter_username: string
  created_at: string
  expires_at: string
}

export interface Notification {
  id: number
  // "comment" and "invite" today, matched by string in
  // NotificationBell.tsx to decide where a click navigates - see
  // models.Notification's docstring for why this stays a plain string
  // (not a fixed union) on the backend, so a future notification type
  // never needs a schema change there. An unrecognized type still
  // renders fine via `message`, it just won't have special navigation.
  type: string
  message: string
  entry_id: number | null
  workspace_id: number | null
  read_at: string | null
  created_at: string
}
