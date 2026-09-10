import { useState } from 'react'
import { ApiError, deleteAccount } from '../api'
import { useAuth } from '../auth/AuthContext'

interface Props {
  onClose: () => void
}

/** Account-level settings (as opposed to WorkspaceSettings, which is
 * per-workspace) - currently just the permanent account deletion flow.
 * Reuses WorkspaceSettings' modal-overlay CSS classes rather than
 * duplicating that layout for a second settings panel. */
export default function AccountSettings({ onClose }: Props) {
  const { token, logout } = useAuth()
  const [confirming, setConfirming] = useState(false)
  const [password, setPassword] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleDelete(e: React.FormEvent) {
    e.preventDefault()
    if (!token || !password) return
    setDeleting(true)
    setError(null)
    try {
      await deleteAccount(password, token)
      // The account is gone server-side and the token is now rejected on
      // every future request (see auth._user_from_token) - discard it
      // locally too and drop back to the logged-out view.
      logout()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not delete your account.')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="workspace-settings-overlay" onClick={onClose}>
      <div className="workspace-settings" onClick={(e) => e.stopPropagation()}>
        <header>
          <h2>Account settings</h2>
          <button type="button" className="link-btn" onClick={onClose}>
            Close
          </button>
        </header>

        <h3>Delete my account</h3>
        {!confirming && (
          <>
            <p className="hint">
              Permanently deletes your account. You won't be able to log in again. Your entries and comments in
              shared workspaces stay visible to other members, but will show as posted by "Deleted user" instead of
              your name.
            </p>
            <button type="button" onClick={() => setConfirming(true)}>
              Delete my account
            </button>
          </>
        )}

        {confirming && (
          <form onSubmit={handleDelete}>
            <p className="error">
              This is permanent and cannot be undone. If you're the sole owner of a workspace that still has other
              members, you'll need to transfer ownership first (in that workspace's Settings) before you can delete
              your account.
            </p>
            <label htmlFor="delete-account-password">Confirm your password to continue</label>
            <input
              id="delete-account-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
            {error && <p className="error">{error}</p>}
            <div className="workspace-member-controls">
              <button type="submit" disabled={deleting || !password}>
                {deleting ? 'Deleting...' : 'Permanently delete my account'}
              </button>
              <button
                type="button"
                className="link-btn"
                onClick={() => {
                  setConfirming(false)
                  setPassword('')
                  setError(null)
                }}
              >
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
