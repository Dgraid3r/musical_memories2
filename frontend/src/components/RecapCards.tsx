import type { WorkspaceRecap } from '../types'

interface Props {
  recap: WorkspaceRecap
  heading: string
}

function formatDate(iso: string): string {
  return new Date(iso + 'T00:00:00').toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

/** The purely presentational "wrapped"-style card sequence - given only
 * the aggregate stats and a heading, with no idea whether it's being
 * rendered in-app (WorkspaceRecapPage) or from a public share link
 * (SharedRecapView), and no way to tell the difference from what it
 * renders: both surfaces get exactly the same page. Deliberately built
 * entirely from this app's own existing theme tokens/fonts (--bg,
 * --surface, --accent, --font-display, etc. - see App.css) rather than
 * a separate visual language, so light/dark/system all work here the
 * same as everywhere else, and the big numbers use the same serif
 * display face (Fraunces) entry titles/headings already use, just
 * turned up for this one occasion. */
export default function RecapCards({ recap, heading }: Props) {
  if (recap.entry_count === 0) {
    return (
      <div className="recap-cards">
        <section className="recap-card recap-hero">
          <p className="recap-eyebrow">{heading}</p>
          <p className="recap-card-caption">No memories logged in {recap.year} yet.</p>
        </section>
      </div>
    )
  }

  return (
    <div className="recap-cards">
      <section className="recap-card recap-hero">
        <p className="recap-eyebrow">{heading}</p>
        <p className="recap-big-number">{recap.entry_count}</p>
        <p className="recap-card-caption">{recap.entry_count === 1 ? 'memory logged' : 'memories logged'}</p>
      </section>

      {recap.photo_count > 0 && (
        <section className="recap-card">
          <p className="recap-big-number">{recap.photo_count}</p>
          <p className="recap-card-caption">{recap.photo_count === 1 ? 'photo captured' : 'photos captured'}</p>
        </section>
      )}

      {recap.most_active_month && (
        <section className="recap-card">
          <p className="recap-card-caption">Your most active month was</p>
          <p className="recap-big-word">{recap.most_active_month}</p>
        </section>
      )}

      {recap.top_tags.length > 0 && (
        <section className="recap-card">
          <p className="recap-card-caption">Top tags this year</p>
          <ul className="recap-tag-list">
            {recap.top_tags.map((tag) => (
              <li key={tag.name}>
                <span className="recap-tag-name">{tag.name}</span>
                <span className="recap-tag-count">{tag.count}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {(recap.first_entry || recap.last_entry) && (
        <section className="recap-card recap-bookends">
          {recap.first_entry && (
            <div className="recap-bookend">
              <p className="recap-card-caption">The year began</p>
              <p className="recap-bookend-date">{formatDate(recap.first_entry.start_date)}</p>
              {/* No playlist yet on an entry synced from an offline draft -
                  see JournalEntry.playlist_name's own comment. */}
              {recap.first_entry.playlist_name && (
                <p className="recap-bookend-playlist">{recap.first_entry.playlist_name}</p>
              )}
            </div>
          )}
          {recap.last_entry && (
            <div className="recap-bookend">
              <p className="recap-card-caption">...and closed</p>
              <p className="recap-bookend-date">{formatDate(recap.last_entry.start_date)}</p>
              {recap.last_entry.playlist_name && (
                <p className="recap-bookend-playlist">{recap.last_entry.playlist_name}</p>
              )}
            </div>
          )}
        </section>
      )}

      {recap.contributors.length > 0 && (
        <section className="recap-card">
          <p className="recap-card-caption">Who showed up this year</p>
          <p className="recap-big-word">{recap.contributors.map((c) => c.username).join(', ')}</p>
        </section>
      )}

      {recap.top_playlists.length > 0 && (
        <section className="recap-card">
          <p className="recap-card-caption">Most-replayed soundtrack</p>
          <p className="recap-big-word">{recap.top_playlists[0].playlist_name}</p>
          <p className="recap-card-caption">revisited {recap.top_playlists[0].count} times</p>
        </section>
      )}
    </div>
  )
}
