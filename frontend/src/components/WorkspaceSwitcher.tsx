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
    <>
      {/* A native <select> never fires `change` for clicking the option
       * that's already showing/selected - "+ New workspace" used to be a
       * pseudo-option inside this same <select>, which meant a brand-new
       * user with zero real workspaces (so that pseudo-option is the only
       * one in the list) had no way to trigger it at all. This is now a
       * genuine button with its own click handler, always rendered
       * regardless of how many workspaces exist; the <select> itself only
       * ever lists real workspaces, and is omitted entirely rather than
       * shown empty/disabled when there are none. */}
      {workspaces.length > 0 && (
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
        </select>
      )}
      <button type="button" className="link-btn" onClick={() => setCreating(true)}>
        + New workspace
      </button>
    </>
  )
}
