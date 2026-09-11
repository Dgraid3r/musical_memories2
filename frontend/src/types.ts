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
  playlist_id: string
  playlist_name: string
  playlist_url: string
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
