import { useEffect, useState } from 'react'
import { fetchTags } from '../api'
import { useAuth } from '../auth/AuthContext'

interface Props {
  selected: string[]
  onChange: (tags: string[]) => void
}

export default function TagInput({ selected, onChange }: Props) {
  const { token } = useAuth()
  const [query, setQuery] = useState('')
  const [knownTags, setKnownTags] = useState<string[]>([])

  useEffect(() => {
    fetchTags(token)
      .then(setKnownTags)
      .catch(() => setKnownTags([]))
  }, [token])

  function addTag(raw: string) {
    const name = raw.trim().toLowerCase()
    if (!name || selected.includes(name)) {
      setQuery('')
      return
    }
    onChange([...selected, name])
    setQuery('')
  }

  function removeTag(name: string) {
    onChange(selected.filter((t) => t !== name))
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      addTag(query)
    }
  }

  const trimmedQuery = query.trim().toLowerCase()
  const suggestions = knownTags.filter((t) => trimmedQuery && t.startsWith(trimmedQuery) && !selected.includes(t))

  return (
    <div className="tag-input">
      <label htmlFor="tag-query">Tags</label>

      {selected.length > 0 && (
        <ul className="tag-chips">
          {selected.map((tagName) => (
            <li key={tagName}>
              {tagName}
              <button type="button" onClick={() => removeTag(tagName)} aria-label={`Remove ${tagName}`}>
                &times;
              </button>
            </li>
          ))}
        </ul>
      )}

      <input
        id="tag-query"
        type="text"
        placeholder="Add a tag, press Enter..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={handleKeyDown}
      />

      {suggestions.length > 0 && (
        <ul className="tag-suggestions">
          {suggestions.slice(0, 6).map((tagName) => (
            <li key={tagName}>
              <button type="button" onClick={() => addTag(tagName)}>
                {tagName}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
