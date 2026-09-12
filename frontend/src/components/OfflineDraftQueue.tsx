import type { OfflineDraft } from '../offlineDrafts'

interface Props {
  drafts: OfflineDraft[]
  syncing: boolean
  justSynced: boolean
  online: boolean
  onSyncNow: () => void
}

const STATUS_LABEL: Record<OfflineDraft['status'], string> = {
  queued: 'Queued',
  syncing: 'Syncing...',
  failed: 'Failed, will retry',
}

/** Visible state for the IndexedDB-backed offline draft queue (see
 * offlineDrafts.ts/useOfflineDrafts.ts): how many drafts are waiting,
 * each one's own queued/syncing/failed status, and a manual "Sync now"
 * action for when the browser's `online` event doesn't fire reliably.
 * Renders nothing once the queue is empty and there's no just-synced
 * confirmation left to show - never a persistent fixture of the page. */
export default function OfflineDraftQueue({ drafts, syncing, justSynced, online, onSyncNow }: Props) {
  if (drafts.length === 0) {
    if (!justSynced) return null
    return (
      <div className="offline-draft-queue">
        <p className="hint">All drafts synced.</p>
      </div>
    )
  }

  return (
    <div className="offline-draft-queue">
      <div className="offline-draft-queue-header">
        <p>
          {drafts.length} offline {drafts.length === 1 ? 'draft' : 'drafts'} queued
        </p>
        <button type="button" onClick={onSyncNow} disabled={syncing || !online}>
          {syncing ? 'Syncing...' : 'Sync now'}
        </button>
      </div>
      {!online && <p className="hint">You're offline - drafts will sync automatically once you're back online.</p>}
      <ul className="offline-draft-list">
        {drafts.map((draft) => (
          <li key={draft.id}>
            <div className="offline-draft-row">
              <span className="offline-draft-summary">
                {draft.startDate} - {draft.text ? draft.text.slice(0, 60) : '(no text)'}
              </span>
              <span className={`offline-draft-status offline-draft-status-${draft.status}`}>
                {STATUS_LABEL[draft.status]}
              </span>
            </div>
            {draft.status === 'failed' && draft.error && <p className="error offline-draft-error">{draft.error}</p>}
          </li>
        ))}
      </ul>
    </div>
  )
}
