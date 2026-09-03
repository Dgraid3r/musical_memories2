import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { createWorkspace as apiCreateWorkspace, fetchWorkspaces } from '../api'
import { useAuth } from '../auth/AuthContext'
import type { Workspace } from '../types'

const ACTIVE_WORKSPACE_STORAGE_KEY = 'musical_memories_active_workspace'

interface WorkspaceContextValue {
  workspaces: Workspace[]
  activeWorkspace: Workspace | null
  loading: boolean
  error: string | null
  switchWorkspace: (id: number) => void
  createWorkspace: (name: string) => Promise<Workspace>
  refresh: () => Promise<void>
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null)

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { user, token } = useAuth()
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [activeId, setActiveId] = useState<number | null>(() => {
    const stored = localStorage.getItem(ACTIVE_WORKSPACE_STORAGE_KEY)
    return stored ? Number(stored) : null
  })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function refresh() {
    if (!token) {
      setWorkspaces([])
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const list = await fetchWorkspaces(token)
      setWorkspaces(list)
      // If there's no active workspace yet, or the stored one no longer
      // applies (removed, or from a previous account on this browser),
      // fall back to the first one the user belongs to.
      setActiveId((current) => {
        if (current !== null && list.some((w) => w.id === current)) return current
        return list[0]?.id ?? null
      })
    } catch {
      setError('Could not load your workspaces.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    // Not logged in yet (or logged out) - nothing to load.
    if (!user || !token) {
      setWorkspaces([])
      setActiveId(null)
      setLoading(false)
      return
    }
    refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, token])

  function switchWorkspace(id: number) {
    setActiveId(id)
    localStorage.setItem(ACTIVE_WORKSPACE_STORAGE_KEY, String(id))
  }

  async function createWorkspace(name: string): Promise<Workspace> {
    if (!token) throw new Error('Not logged in')
    const workspace = await apiCreateWorkspace(name, token)
    setWorkspaces((prev) => [...prev, workspace])
    switchWorkspace(workspace.id)
    return workspace
  }

  const activeWorkspace = workspaces.find((w) => w.id === activeId) ?? null

  return (
    <WorkspaceContext.Provider
      value={{ workspaces, activeWorkspace, loading, error, switchWorkspace, createWorkspace, refresh }}
    >
      {children}
    </WorkspaceContext.Provider>
  )
}

export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext)
  if (!ctx) throw new Error('useWorkspace must be used within WorkspaceProvider')
  return ctx
}
