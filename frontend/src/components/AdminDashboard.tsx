import { useEffect, useState } from 'react'
import { ApiError, deactivateAdminUser, fetchAdminStats, fetchAdminUsers, reactivateAdminUser } from '../api'
import { useAuth } from '../auth/AuthContext'
import type { AdminStats, AdminUser } from '../types'

interface Props {
  onClose: () => void
}

const PAGE_SIZE = 20

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

/** User management + operational visibility only - deliberately no
 * workspace/entry browsing or content moderation tooling here (see
 * routers/admin.py's module docstring for the same scope boundary on the
 * backend). Rendered only when the logged-in user's is_admin is true -
 * see App.tsx, which checks that off the same AuthContext user object
 * every other current-user-attribute check in this app already uses. */
export default function AdminDashboard({ onClose }: Props) {
  const { token, user: currentUser } = useAuth()
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [statsError, setStatsError] = useState<string | null>(null)

  const [query, setQuery] = useState('')
  const [users, setUsers] = useState<AdminUser[]>([])
  const [usersLoading, setUsersLoading] = useState(true)
  const [usersError, setUsersError] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [actioningId, setActioningId] = useState<number | null>(null)

  useEffect(() => {
    if (!token) return
    fetchAdminStats(token)
      .then(setStats)
      .catch((err) => setStatsError(err instanceof ApiError ? err.message : 'Could not load stats.'))
  }, [token])

  useEffect(() => {
    if (!token) return
    setUsersLoading(true)
    setUsersError(null)
    fetchAdminUsers({ q: query.trim() || undefined, limit: PAGE_SIZE, offset: 0 }, token)
      .then((page) => {
        setUsers(page)
        setHasMore(page.length === PAGE_SIZE)
      })
      .catch((err) => {
        setUsersError(err instanceof ApiError ? err.message : 'Could not load users.')
        setUsers([])
        setHasMore(false)
      })
      .finally(() => setUsersLoading(false))
  }, [token, query])

  async function loadMore() {
    if (!token) return
    setLoadingMore(true)
    try {
      const page = await fetchAdminUsers({ q: query.trim() || undefined, limit: PAGE_SIZE, offset: users.length }, token)
      setUsers((prev) => [...prev, ...page])
      setHasMore(page.length === PAGE_SIZE)
    } catch (err) {
      setUsersError(err instanceof ApiError ? err.message : 'Could not load more users.')
    } finally {
      setLoadingMore(false)
    }
  }

  async function toggleActive(user: AdminUser) {
    if (!token) return
    setActioningId(user.id)
    setUsersError(null)
    try {
      if (user.is_active) {
        await deactivateAdminUser(user.id, token)
      } else {
        await reactivateAdminUser(user.id, token)
      }
      setUsers((prev) => prev.map((u) => (u.id === user.id ? { ...u, is_active: !u.is_active } : u)))
    } catch (err) {
      setUsersError(err instanceof ApiError ? err.message : 'Could not update this account.')
    } finally {
      setActioningId(null)
    }
  }

  return (
    <div className="app-shell admin-dashboard">
      <header className="app-header">
        <div>
          <h1>Admin dashboard</h1>
          <p>User management and operational visibility - not content moderation.</p>
        </div>
        <button type="button" className="link-btn" onClick={onClose}>
          Back
        </button>
      </header>

      <main>
        <section className="admin-stats">
          <h2>Stats</h2>
          {statsError && <p className="error">{statsError}</p>}
          {!statsError && !stats && <p>Loading...</p>}
          {stats && (
            <>
              <div className="admin-stats-grid">
                <div className="admin-stat-card">
                  <span className="admin-stat-value">{stats.total_users}</span>
                  <span className="admin-stat-label">Users</span>
                </div>
                <div className="admin-stat-card">
                  <span className="admin-stat-value">{stats.total_workspaces}</span>
                  <span className="admin-stat-label">Workspaces</span>
                </div>
                <div className="admin-stat-card">
                  <span className="admin-stat-value">{stats.total_entries}</span>
                  <span className="admin-stat-label">Memories</span>
                </div>
                <div className="admin-stat-card">
                  <span className="admin-stat-value">{stats.new_signups_7d}</span>
                  <span className="admin-stat-label">New signups (7d)</span>
                </div>
                <div className="admin-stat-card">
                  <span className="admin-stat-value">{stats.new_signups_30d}</span>
                  <span className="admin-stat-label">New signups (30d)</span>
                </div>
              </div>

              <div className="admin-status-row">
                <span className={`admin-status-badge ${stats.database_healthy ? 'ok' : 'bad'}`}>
                  Database {stats.database_healthy ? 'healthy' : 'unreachable'}
                </span>
                {stats.latest_backup ? (
                  <span className={`admin-status-badge ${stats.latest_backup.succeeded ? 'ok' : 'bad'}`}>
                    Last backup {stats.latest_backup.succeeded ? 'succeeded' : 'failed'} -{' '}
                    {formatDateTime(stats.latest_backup.started_at)}
                  </span>
                ) : (
                  <span className="admin-status-badge">No backup has run yet</span>
                )}
              </div>
              {stats.latest_backup && !stats.latest_backup.succeeded && stats.latest_backup.error_message && (
                <p className="error">{stats.latest_backup.error_message}</p>
              )}
            </>
          )}
        </section>

        <section className="admin-users">
          <h2>Users</h2>
          <div className="search-bar">
            <input
              type="search"
              placeholder="Search by username or email..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          {usersError && <p className="error">{usersError}</p>}
          {usersLoading && <p>Loading...</p>}
          {!usersLoading && users.length === 0 && <p className="hint">No users found.</p>}

          {users.length > 0 && (
            <ul className="admin-user-list">
              {users.map((u) => (
                <li key={u.id} className={u.is_deleted ? 'admin-user-deleted' : ''}>
                  <div className="admin-user-info">
                    <strong>{u.username}</strong>
                    <span className="admin-user-email">{u.email}</span>
                    <span className="admin-user-meta">
                      Joined {formatDateTime(u.created_at)}
                      {u.is_admin && ' · Admin'}
                      {!u.email_verified && ' · Unverified email'}
                      {!u.is_active && ' · Deactivated'}
                      {u.is_deleted && ' · Deleted'}
                      {u.id === currentUser?.id && ' · You'}
                    </span>
                  </div>
                  {!u.is_deleted && u.id !== currentUser?.id && (
                    <button
                      type="button"
                      className="link-btn"
                      onClick={() => toggleActive(u)}
                      disabled={actioningId === u.id}
                    >
                      {actioningId === u.id
                        ? 'Please wait...'
                        : u.is_active
                          ? 'Deactivate'
                          : 'Reactivate'}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}

          {!usersLoading && hasMore && (
            <button type="button" className="link-btn" onClick={loadMore} disabled={loadingMore}>
              {loadingMore ? 'Loading...' : 'Load more'}
            </button>
          )}
        </section>
      </main>
    </div>
  )
}
