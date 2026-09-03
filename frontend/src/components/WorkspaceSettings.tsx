import { useEffect, useState } from 'react'
import {
  ApiError,
  addWorkspaceMember,
  fetchWorkspaceMembers,
  removeWorkspaceMember,
  updateWorkspaceMemberRole,
  updateWorkspaceVisibility,
} from '../api'
import { useAuth } from '../auth/AuthContext'
import type { WorkspaceMember, WorkspaceRole } from '../types'
import { useWorkspace } from '../workspace/WorkspaceContext'

interface Props {
  onClose: () => void
}

export default function WorkspaceSettings({ onClose }: Props) {
  const { token, user } = useAuth()
  const { activeWorkspace, refresh } = useWorkspace()
  const [members, setMembers] = useState<WorkspaceMember[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [togglingVisibility, setTogglingVisibility] = useState(false)
  const [newUsername, setNewUsername] = useState('')
  const [addingMember, setAddingMember] = useState(false)

  const isOwner = activeWorkspace?.role === 'owner'

  useEffect(() => {
    if (!activeWorkspace || !token) return
    setLoading(true)
    fetchWorkspaceMembers(activeWorkspace.id, token)
      .then(setMembers)
      .catch(() => setError('Could not load members.'))
      .finally(() => setLoading(false))
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

  async function handleAddMember(e: React.FormEvent) {
    e.preventDefault()
    if (!token || !activeWorkspace || !newUsername.trim()) return
    setAddingMember(true)
    setError(null)
    try {
      const member = await addWorkspaceMember(activeWorkspace.id, newUsername.trim(), token)
      setMembers((prev) => [...prev, member])
      setNewUsername('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not add member.')
    } finally {
      setAddingMember(false)
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
          <form className="workspace-add-member-form" onSubmit={handleAddMember}>
            <input
              type="text"
              placeholder="Add member by username..."
              value={newUsername}
              onChange={(e) => setNewUsername(e.target.value)}
            />
            <button type="submit" disabled={addingMember || !newUsername.trim()}>
              {addingMember ? 'Adding...' : 'Add'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
