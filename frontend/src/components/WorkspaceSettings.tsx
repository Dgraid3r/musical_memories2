import { useEffect, useState } from 'react'
import {
  ApiError,
  createWorkspaceInvite,
  fetchWorkspaceInvites,
  fetchWorkspaceMembers,
  removeWorkspaceMember,
  revokeWorkspaceInvite,
  updateWorkspaceMemberRole,
  updateWorkspaceVisibility,
} from '../api'
import { useAuth } from '../auth/AuthContext'
import type { WorkspaceInvite, WorkspaceMember, WorkspaceRole } from '../types'
import { useWorkspace } from '../workspace/WorkspaceContext'

interface Props {
  onClose: () => void
}

export default function WorkspaceSettings({ onClose }: Props) {
  const { token, user } = useAuth()
  const { activeWorkspace, refresh } = useWorkspace()
  const [members, setMembers] = useState<WorkspaceMember[]>([])
  const [invites, setInvites] = useState<WorkspaceInvite[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [togglingVisibility, setTogglingVisibility] = useState(false)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<Extract<WorkspaceRole, 'member' | 'subscriber'>>('member')
  const [sendingInvite, setSendingInvite] = useState(false)

  const isOwner = activeWorkspace?.role === 'owner'

  useEffect(() => {
    if (!activeWorkspace || !token) return
    setLoading(true)
    Promise.all([
      fetchWorkspaceMembers(activeWorkspace.id, token),
      isOwner ? fetchWorkspaceInvites(activeWorkspace.id, token) : Promise.resolve([]),
    ])
      .then(([memberList, inviteList]) => {
        setMembers(memberList)
        setInvites(inviteList)
      })
      .catch(() => setError('Could not load members.'))
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeWorkspace, token])

  if (!activeWorkspace) return null

  async function toggleVisibility() {
    if (!token || !activeWorkspace) return
    setTogglingVisibility(true)
    setError(null)
    try {
      await updateWorkspaceVisibility(
        activeWorkspace.id,
        activeWorkspace.visibility === 'public' ? 'private' : 'public',
        token,
      )
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not update visibility.')
    } finally {
      setTogglingVisibility(false)
    }
  }

  async function handleSendInvite(e: React.FormEvent) {
    e.preventDefault()
    if (!token || !activeWorkspace || !inviteEmail.trim()) return
    setSendingInvite(true)
    setError(null)
    try {
      const invite = await createWorkspaceInvite(activeWorkspace.id, inviteEmail.trim(), inviteRole, token)
      setInvites((prev) => [invite, ...prev])
      setInviteEmail('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not send invite.')
    } finally {
      setSendingInvite(false)
    }
  }

  async function handleRevokeInvite(inviteId: number) {
    if (!token || !activeWorkspace) return
    setError(null)
    try {
      await revokeWorkspaceInvite(activeWorkspace.id, inviteId, token)
      setInvites((prev) => prev.filter((i) => i.id !== inviteId))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not revoke invite.')
    }
  }

  async function handleRoleChange(userId: number, role: Extract<WorkspaceRole, 'member' | 'subscriber'>) {
    if (!token || !activeWorkspace) return
    setError(null)
    try {
      const updated = await updateWorkspaceMemberRole(activeWorkspace.id, userId, role, token)
      setMembers((prev) => prev.map((m) => (m.user_id === userId ? updated : m)))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not update role.')
    }
  }

  async function handleRemove(userId: number) {
    if (!token || !activeWorkspace) return
    setError(null)
    try {
      await removeWorkspaceMember(activeWorkspace.id, userId, token)
      setMembers((prev) => prev.filter((m) => m.user_id !== userId))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not remove member.')
    }
  }

  return (
    <div className="workspace-settings-overlay" onClick={onClose}>
      <div className="workspace-settings" onClick={(e) => e.stopPropagation()}>
        <header>
          <h2>{activeWorkspace.name}</h2>
          <button type="button" className="link-btn" onClick={onClose}>
            Close
          </button>
        </header>

        <div className="workspace-visibility-row">
          <span>
            This workspace is <strong>{activeWorkspace.visibility}</strong>
            {activeWorkspace.visibility === 'public'
              ? ' - anyone can read it, no account needed.'
              : ' - only members can read it.'}
          </span>
          {isOwner && (
            <button type="button" onClick={toggleVisibility} disabled={togglingVisibility}>
              {togglingVisibility ? 'Updating...' : `Make ${activeWorkspace.visibility === 'public' ? 'private' : 'public'}`}
            </button>
          )}
        </div>

        {error && <p className="error">{error}</p>}

        <h3>Members</h3>
        {loading && <p className="hint">Loading...</p>}
        <ul className="workspace-member-list">
          {members.map((m) => (
            <li key={m.user_id}>
              <span>{m.username}</span>
              {isOwner && m.role !== 'owner' && m.user_id !== user?.id ? (
                <span className="workspace-member-controls">
                  <select
                    value={m.role}
                    onChange={(e) => handleRoleChange(m.user_id, e.target.value as 'member' | 'subscriber')}
                    aria-label={`Role for ${m.username}`}
                  >
                    <option value="member">Member (read/write)</option>
                    <option value="subscriber">Subscriber (read-only)</option>
                  </select>
                  <button type="button" className="link-btn" onClick={() => handleRemove(m.user_id)}>
                    Remove
                  </button>
                </span>
              ) : (
                <span className="workspace-member-role">{m.role}</span>
              )}
            </li>
          ))}
        </ul>

        {isOwner && (
          <>
            <h3>Pending invites</h3>
            {invites.length === 0 && <p className="hint">No pending invites.</p>}
            <ul className="workspace-member-list">
              {invites.map((invite) => (
                <li key={invite.id}>
                  <span>
                    {invite.email} <span className="workspace-member-role">({invite.role})</span>
                  </span>
                  <button type="button" className="link-btn" onClick={() => handleRevokeInvite(invite.id)}>
                    Revoke
                  </button>
                </li>
              ))}
            </ul>

            <form className="workspace-add-member-form" onSubmit={handleSendInvite}>
              <input
                type="email"
                placeholder="Invite by email..."
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
              />
              <select
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value as 'member' | 'subscriber')}
                aria-label="Invited role"
              >
                <option value="member">Member (read/write)</option>
                <option value="subscriber">Subscriber (read-only)</option>
              </select>
              <button type="submit" disabled={sendingInvite || !inviteEmail.trim()}>
                {sendingInvite ? 'Sending...' : 'Invite'}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  )
}
