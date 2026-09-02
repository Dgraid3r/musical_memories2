export interface EntryImage {
  id: number
  filename: string
}

export interface JournalEntry {
  id: number
  user_id: number
  owner_username: string
  entry_date: string
  text: string | null
  is_public: boolean
  playlist_id: string
  playlist_name: string
  playlist_url: string
  playlist_image_url: string | null
  created_at: string
  images: EntryImage[]
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
