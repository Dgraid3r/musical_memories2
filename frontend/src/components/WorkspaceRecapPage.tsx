import { useEffect, useState } from 'react'
import { ApiError, disableRecapSharing, enableRecapSharing, fetchWorkspaceRecap } from '../api'
import { useAuth } from '../auth/AuthContext'
import type { Workspace, WorkspaceRecap } from '../types'
import RecapCards from './RecapCards'

interface Props {
  workspace: Workspace
  onClose: () => void
}

const currentYear = () => new Date().getFullYear()

/** The in-app "year in review" page for the active workspace - a full-
 * page swap (same pattern as AdminDashboard/MyInvites in App.tsx)
 * rather than squeezed into the ordinary entry-list layout, since the
 * whole point is a moment worth lingering on. Any workspace member can
 * view it; only the owner sees the share controls (same isOwner gate
 * already used for workspace-level settings like visibility). */
export default function WorkspaceRecapPage({ workspace, onClose }: Props) {
  const { token } = useAuth()
  const [year, setYear] = useState(currentYear())
  const [recap, setRecap] = useState<WorkspaceRecap | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showSharePanel, setShowSharePanel] = useState(false)
  const [shareLink, setShareLink] = useState<string | null>(null)
  const [shareBusy, setShareBusy] = useState(false)
  const [shareError, setShareError] = useState<string | null>(null)
  const [shareCopied, setShareCopied] = useState(false)
  const isOwner = workspace.role === 'owner'

  useEffect(() => {
    if (!token) return
    let cancelled = false
    setLoading(true)
    setError(null)
    setShowSharePanel(false)
    setShareLink(null)
    fetchWorkspaceRecap(workspace.id, year, token)
      .then((result) => {
        if (!cancelled) setRecap(result)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Could not load this year in review.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [workspace.id, year, token])

  async function openSharePanel() {
    if (!token) return
    setShowSharePanel(true)
    setShareError(null)
    setShareCopied(false)
    setShareBusy(true)
    try {
      const shareToken = await enableRecapSharing(workspace.id, year, token)
      setShareLink(`${window.location.origin}/?shared-recap=${shareToken}`)
    } catch {
      setShareError('Could not create a share link.')
    } finally {
      setShareBusy(false)
    }
  }

  async function copyShareLink() {
    if (!shareLink) return
    try {
      await navigator.clipboard.writeText(shareLink)
      setShareCopied(true)
    } catch {
      setShareError('Could not copy the link - you can select and copy it manually.')
    }
  }

  async function revokeSharing() {
    if (!token) return
    setShareBusy(true)
    setShareError(null)
    try {
      await disableRecapSharing(workspace.id, year, token)
      setShareLink(null)
      setShowSharePanel(false)
    } catch {
      setShareError('Could not turn off sharing.')
    } finally {
      setShareBusy(false)
    }
  }

  return (
    <div className="app-shell recap-page">
      <header className="app-header">
        <div>
          <button type="button" className="link-btn" onClick={onClose}>
            &larr; Back to {workspace.name}
          </button>
        </div>
        <div className="account-bar recap-year-nav">
          <button type="button" className="link-btn" onClick={() => setYear((y) => y - 1)} aria-label="Previous year">
            &lsaquo;
          </button>
          <span className="recap-year-label">{year}</span>
          <button
            type="button"
            className="link-btn"
            onClick={() => setYear((y) => y + 1)}
            disabled={year >= currentYear()}
            aria-label="Next year"
          >
            &rsaquo;
          </button>
          {isOwner && (
            <button type="button" onClick={openSharePanel} disabled={shareBusy}>
              Share this year
            </button>
          )}
        </div>
      </header>

      {isOwner && showSharePanel && (
        <div className="share-panel">
          <p className="hint">
            Anyone with this link can view this year's recap - no login required. It only ever shows the aggregate
            stats below, never your actual entries or photos.
          </p>
          {shareBusy && !shareLink && <p>Preparing link...</p>}
          {shareLink && (
            <div className="share-link-row">
              <input type="text" readOnly value={shareLink} onFocus={(e) => e.target.select()} />
              <button type="button" onClick={copyShareLink}>
                {shareCopied ? 'Copied!' : 'Copy'}
              </button>
            </div>
          )}
          {shareError && <p className="error">{shareError}</p>}
          <div className="share-panel-actions">
            <button type="button" className="delete-btn" onClick={revokeSharing} disabled={shareBusy}>
              Turn off sharing
            </button>
            <button type="button" className="link-btn" onClick={() => setShowSharePanel(false)}>
              Close
            </button>
          </div>
        </div>
      )}

      <main>
        {loading && <p>Loading...</p>}
        {!loading && error && <p className="error">{error}</p>}
        {!loading && !error && recap && <RecapCards recap={recap} heading={`${workspace.name} - ${year} in review`} />}
      </main>
    </div>
  )
}
