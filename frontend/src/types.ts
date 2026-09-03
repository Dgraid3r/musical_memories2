export interface EntryImage {
  id: number
  filename: string
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
  created_at: string
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

// A public workspace as returned by the discovery endpoint - deliberately
// just enough to identify/browse to it, never entry content and never a
// caller-specific role (browsing needs no auth at all).
export interface PublicWorkspace {
  id: number
  name: string
  created_at: string
}
