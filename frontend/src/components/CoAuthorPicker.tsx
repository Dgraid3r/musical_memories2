import { useEffect, useState } from 'react'
import { searchUsers } from '../api'
import { useAuth } from '../auth/AuthContext'
import type { UserPublic } from '../types'

interface Props {
  selected: string[]
  onChange: (usernames: string[]) => void
}

export default function CoAuthorPicker({ selected, onChange }: Props) {
  const { token } = useAuth()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<UserPublic[]>([])

  useEffect(() => {
    if (!token || query.trim().length < 2) {
      setResults([])
      return
    }
    const handle = setTimeout(() => {
      searchUsers(query, token)
        .then((users) => setResults(users.filter((u) => !selected.includes(u.username))))
        .catch(() => setResults([]))
    }, 300)
    return () => clearTimeout(handle)
  }, [query, token, selected])

  function addCoauthor(username: string) {
    onChange([...selected, username])
    setQuery('')
    setResults([])
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
        placeholder="Search users to add..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />

      {results.length > 0 && (
        <ul className="coauthor-results">
          {results.map((user) => (
            <li key={user.id}>
              <button type="button" onClick={() => addCoauthor(user.username)}>
                {user.username}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
