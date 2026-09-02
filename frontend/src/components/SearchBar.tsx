import { useEffect, useState } from 'react'

interface Props {
  onSearch: (query: string) => void
}

export default function SearchBar({ onSearch }: Props) {
  const [query, setQuery] = useState('')

  useEffect(() => {
    const handle = setTimeout(() => onSearch(query.trim()), 300)
    return () => clearTimeout(handle)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query])

  return (
    <div className="search-bar">
      <input
        type="search"
        placeholder="Search your memories..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        aria-label="Search memories"
      />
    </div>
  )
}
