import { useEffect, useState } from 'react'
import { fetchWorkspaceMembers } from '../api'
import { useAuth } from '../auth/AuthContext'
import type { WorkspaceMember } from '../types'

interface Props {
  workspaceId: number
  selected: string[]
  onChange: (usernames: string[]) => void
}

export default function CoAuthorPicker({ workspaceId, selected, onChange }: Props) {
  const { user, token } = useAuth()
  const [query, setQuery] = useState('')
  const [members, setMembers] = useState<WorkspaceMember[]>([])

  useEffect(() => {
    // Only fellow workspace members are valid co-authors (the server
    // rejects anyone else), so this searches the workspace's own member
    // list rather than the whole app's user directory.
    if (!token) return
    fetchWorkspaceMembers(workspaceId, token)
      .then(setMembers)
      .catch(() => setMembers([]))
  }, [workspaceId, token])

  const trimmedQuery = query.trim().toLowerCase()
  const results = members.filter(
    (m) =>
      m.user_id !== user?.id &&
      !selected.includes(m.username) &&
      (trimmedQuery ? m.username.toLowerCase().includes(trimmedQuery) : false),
  )

  function addCoauthor(username: string) {
    onChange([...selected, username])
    setQuery('')
  }

  function removeCoauthor(username: string) {
    onChange(selected.filter((u) => u !== username))
  }

  return (
    <div className="coauthor-picker">
      <label htmlFor="coauthor-query">Co-authors</label>

      {selected.length > 0 && (
        <ul className="coauthor-chips">
          {selected.map((username) => (
            <li key={username}>
              {username}
              <button type="button" onClick={() => removeCoauthor(username)} aria-label={`Remove ${username}`}>
                &times;
              </button>
            </li>
          ))}
        </ul>
      )}

      <input
        id="coauthor-query"
        type="text"
        placeholder="Search workspace members to add..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />

      {results.length > 0 && (
        <ul className="coauthor-results">
          {results.map((member) => (
            <li key={member.user_id}>
              <button type="button" onClick={() => addCoauthor(member.username)}>
                {member.username}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
