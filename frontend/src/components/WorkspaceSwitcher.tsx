import { useState } from 'react'
import { ApiError } from '../api'
import { useWorkspace } from '../workspace/WorkspaceContext'

export default function WorkspaceSwitcher() {
  const { workspaces, activeWorkspace, switchWorkspace, createWorkspace } = useWorkspace()
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function handleSelect(e: React.ChangeEvent<HTMLSelectElement>) {
    if (e.target.value === '__new__') {
      setCreating(true)
      return
    }
    switchWorkspace(Number(e.target.value))
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!newName.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      await createWorkspace(newName.trim())
      setNewName('')
      setCreating(false)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create workspace.')
    } finally {
      setSubmitting(false)
    }
  }

  if (creating) {
    return (
      <form className="workspace-create-form" onSubmit={handleCreate}>
        <input
          type="text"
          autoFocus
          placeholder="Workspace name..."
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
        />
        <button type="submit" disabled={submitting || !newName.trim()}>
          {submitting ? 'Creating...' : 'Create'}
        </button>
        <button type="button" className="link-btn" onClick={() => setCreating(false)} disabled={submitting}>
          Cancel
        </button>
        {error && <p className="error">{error}</p>}
      </form>
    )
  }

  return (
    <select
      className="workspace-switcher"
      value={activeWorkspace?.id ?? ''}
      onChange={handleSelect}
      aria-label="Active workspace"
    >
      {workspaces.map((w) => (
        <option key={w.id} value={w.id}>
          {w.name}
        </option>
      ))}
      <option value="__new__">+ New workspace...</option>
    </select>
  )
}
