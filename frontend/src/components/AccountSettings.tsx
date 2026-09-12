import { useState } from 'react'
import { ApiError, deleteAccount, exportAccountData } from '../api'
import { useAuth } from '../auth/AuthContext'
import { useTheme, type ThemeChoice } from '../theme/ThemeContext'

interface Props {
  onClose: () => void
}

const APPEARANCE_OPTIONS: { value: ThemeChoice; label: string }[] = [
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
  { value: 'system', label: 'System' },
]

/** Account-level settings (as opposed to WorkspaceSettings, which is
 * per-workspace) - currently just the permanent account deletion flow.
 * Reuses WorkspaceSettings' modal-overlay CSS classes rather than
 * duplicating that layout for a second settings panel. */
export default function AccountSettings({ onClose }: Props) {
  const { token, logout } = useAuth()
  const { theme, setTheme } = useTheme()
  const [confirming, setConfirming] = useState(false)
  const [password, setPassword] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  async function handleExport() {
    if (!token) return
    setExporting(true)
    setExportError(null)
    try {
      const blob = await exportAccountData(token)
      // The browser's own download sandboxing means a plain data/blob URL
      // can't trigger a "Save As" - a temporary, immediately-removed
      // anchor with the `download` attribute is the standard way to turn
      // a fetched Blob into an actual file save.
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'musical-memories-export.zip'
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      setExportError(err instanceof ApiError ? err.message : 'Could not export your data.')
    } finally {
      setExporting(false)
    }
  }

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

        <h3>Appearance</h3>
        <p className="hint">
          "System" follows your device's light/dark setting automatically. Switching takes effect immediately.
        </p>
        <div className="appearance-options" role="group" aria-label="Appearance">
          {APPEARANCE_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={theme === option.value ? 'active' : ''}
              onClick={() => setTheme(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>

        <h3>Export my data</h3>
        <p className="hint">
          Download a zip archive of your own data: your profile basics, every entry you've authored or co-authored
          (across all your workspaces), your own comments, and your photos.
        </p>
        <button type="button" onClick={handleExport} disabled={exporting}>
          {exporting ? 'Preparing export...' : 'Export my data'}
        </button>
        {exportError && <p className="error">{exportError}</p>}

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
