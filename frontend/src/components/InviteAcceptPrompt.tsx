import { useState } from 'react'
import { ApiError, acceptInvite } from '../api'
import { useAuth } from '../auth/AuthContext'
import type { InvitePreview } from '../types'

interface Props {
  token: string
  preview: InvitePreview
  onAccepted: () => void
  onDismiss: () => void
}

// Shown to an already-authenticated user holding a pending invite token -
// covers both "just logged in/registered to accept this invite" and
// "already had a session open and clicked the link". Acceptance always
// requires this explicit click; nothing here is automatic.
export default function InviteAcceptPrompt({ token, preview, onAccepted, onDismiss }: Props) {
  const { token: authToken, user } = useAuth()
  const [accepting, setAccepting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const emailMismatch = user && user.email.toLowerCase() !== preview.email.toLowerCase()

  async function handleAccept() {
    if (!authToken) return
    setAccepting(true)
    setError(null)
    try {
      await acceptInvite(token, authToken)
      onAccepted()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not accept the invite.')
    } finally {
      setAccepting(false)
    }
  }

  return (
    <div className="auth-shell">
      <div className="auth-form">
        <h1>Musical Memories</h1>
        <p className="hint">
          You've been invited to join <strong>{preview.workspace_name}</strong> as a{' '}
          <strong>{preview.role}</strong>.
        </p>

        {emailMismatch && (
          <p className="error">
            This invite was sent to {preview.email}, but you're logged in as {user?.username} (
            {user?.email}). Log out and log in with the invited account to accept it.
          </p>
        )}

        {error && <p className="error">{error}</p>}

        {!emailMismatch && (
          <button type="button" onClick={handleAccept} disabled={accepting}>
            {accepting ? 'Joining...' : `Accept and join ${preview.workspace_name}`}
          </button>
        )}

        <button type="button" className="link-btn" onClick={onDismiss}>
          Not now
        </button>
      </div>
    </div>
  )
}
