import { useEffect, useState } from 'react'
import { acceptInvite, ApiError, fetchMyPendingInvites } from '../api'
import { useAuth } from '../auth/AuthContext'
import type { MyPendingInvite } from '../types'

interface Props {
  onClose: () => void
  /** Called after successfully accepting an invite - the caller (App.tsx)
   * is responsible for refreshing the workspace list so the newly
   * joined one actually shows up in the switcher. */
  onAccepted: () => void
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

/** Every invite currently pending for the logged-in user's own email -
 * the frontend's own surface for seeing (and acting on) a workspace
 * invite beyond just finding the emailed link. See routers/invites.py's
 * list_my_pending_invites (GET /api/invites). */
export default function MyInvites({ onClose, onAccepted }: Props) {
  const { token } = useAuth()
  const [invites, setInvites] = useState<MyPendingInvite[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [acceptingToken, setAcceptingToken] = useState<string | null>(null)

  useEffect(() => {
    if (!token) return
    fetchMyPendingInvites(token)
      .then(setInvites)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Could not load your invites.'))
      .finally(() => setLoading(false))
  }, [token])

  async function handleAccept(invite: MyPendingInvite) {
    if (!token) return
    setAcceptingToken(invite.token)
    setError(null)
    try {
      await acceptInvite(invite.token, token)
      setInvites((prev) => prev.filter((i) => i.token !== invite.token))
      onAccepted()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not accept this invite.')
    } finally {
      setAcceptingToken(null)
    }
  }

  return (
    <div className="app-shell my-invites">
      <header className="app-header">
        <div>
          <h1>Your invites</h1>
          <p>Workspace invites waiting for you to accept.</p>
        </div>
        <button type="button" className="link-btn" onClick={onClose}>
          Back
        </button>
      </header>

      <main>
        {loading && <p>Loading...</p>}
        {error && <p className="error">{error}</p>}
        {!loading && invites.length === 0 && <p className="hint">No pending invites right now.</p>}

        <ul className="my-invite-list">
          {invites.map((invite) => (
            <li key={invite.token}>
              <div className="my-invite-info">
                <strong>{invite.workspace_name}</strong>
                <span className="my-invite-meta">
                  Invited by {invite.inviter_username} as a {invite.role} &middot; expires{' '}
                  {formatDate(invite.expires_at)}
                </span>
              </div>
              <button type="button" onClick={() => handleAccept(invite)} disabled={acceptingToken === invite.token}>
                {acceptingToken === invite.token ? 'Accepting...' : 'Accept'}
              </button>
            </li>
          ))}
        </ul>
      </main>
    </div>
  )
}
