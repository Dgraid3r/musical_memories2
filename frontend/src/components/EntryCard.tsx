import type { JournalEntry } from '../types'

interface Props {
  entry: JournalEntry
  onDelete: (id: number) => void
}

export default function EntryCard({ entry, onDelete }: Props) {
  return (
    <article className="entry-card">
      <header>
        <time dateTime={entry.entry_date}>
          {new Date(entry.entry_date + 'T00:00:00').toLocaleDateString(undefined, {
            year: 'numeric',
            month: 'long',
            day: 'numeric',
          })}
        </time>
        <button type="button" className="delete-btn" onClick={() => onDelete(entry.id)}>
          Delete
        </button>
      </header>

      {entry.text && <p className="entry-text">{entry.text}</p>}

      {entry.images.length > 0 && (
        <div className="entry-images">
          {entry.images.map((image) => (
            <img key={image.id} src={`/uploads/${image.filename}`} alt="" />
          ))}
        </div>
      )}

      <iframe
        title={entry.playlist_name}
        src={`https://open.spotify.com/embed/playlist/${entry.playlist_id}`}
        width="100%"
        height="152"
        style={{ borderRadius: 12 }}
        allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
        loading="lazy"
      />
    </article>
  )
}
