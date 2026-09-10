import { useEffect, useState } from 'react'
import { fetchEntryEditHistory } from '../api'
import { useAuth } from '../auth/AuthContext'
import type { EntryEditEvent } from '../types'

interface Props {
  workspaceId: number
  entryId: number
}

function formatEditedAt(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

/** A collapsed-by-default audit trail of edits made to an entry after
 * creation - who, when, and a short label for roughly what changed. Not
 * version history: there's no old/new value to show, so this never grows
 * beyond a plain list. Secondary detail, so it stays hidden until the
 * caller explicitly expands it (same collapsed-until-clicked pattern as
 * CommentThread), rather than always showing. */
export default function EntryEditHistory({ workspaceId, entryId }: Props) {
  const { token } = useAuth()
  const [expanded, setExpanded] = useState(false)
  const [events, setEvents] = useState<EntryEditEvent[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!expanded) return
    setLoading(true)
    fetchEntryEditHistory(workspaceId, entryId, token)
      .then(setEvents)
      .finally(() => setLoading(false))
  }, [expanded, workspaceId, entryId, token])

  return (
    <div className="edit-history">
      <button type="button" className="link-btn" onClick={() => setExpanded((e) => !e)}>
        {expanded ? 'Hide edit history' : 'Edit history'}
      </button>

      {expanded && (
        <div className="edit-history-body">
          {loading && <p className="hint">Loading edit history...</p>}
          {!loading && events.length === 0 && <p className="hint">No edits yet.</p>}
          {events.length > 0 && (
            <ul className="edit-history-list">
              {events.map((event) => (
                <li key={event.id}>
                  <span className="edit-history-editor">{event.editor_username}</span>
                  {' edited '}
                  <span className="edit-history-summary">{event.change_summary}</span>
                  {' · '}
                  <span className="edit-history-time">{formatEditedAt(event.edited_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
