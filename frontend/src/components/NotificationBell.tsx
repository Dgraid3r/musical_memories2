import { useEffect, useRef, useState } from 'react'
import {
  ApiError,
  fetchNotifications,
  fetchUnreadNotificationCount,
  markAllNotificationsRead,
  markNotificationRead,
} from '../api'
import { useAuth } from '../auth/AuthContext'
import type { Notification } from '../types'

interface Props {
  /** Called (after the notification is already marked read) when a
   * "comment" notification with a real entry/workspace to go to is
   * clicked - the caller (App.tsx) owns actually getting the user
   * there, the same responsibility MapView.tsx's onViewEntry callback
   * already has for the map's own "view this memory" action. */
  onNavigateToEntry: (workspaceId: number, entryId: number) => void
  /** Called for an "invite" notification, or any notification type this
   * component doesn't know how to deep-link (see models.Notification's
   * docstring on why `type` stays an open string) - falls back to just
   * opening the one other per-user destination this app has today. */
  onNavigateToInvites: () => void
}

const PAGE_SIZE = 20
// Frequent enough that the badge feels "live" without hammering the
// backend - there's no push/websocket channel in this app, so polling
// is the only option; the panel's own open-triggered fetch (below) is
// what actually shows fresh content, this just keeps the closed bell's
// count from going stale for too long.
const UNREAD_COUNT_POLL_MS = 60_000

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

/** The bell icon + unread badge in the main nav, and the dropdown panel
 * it opens - notifications most-recent-first, each clickable to navigate
 * to its source and mark itself read, plus "mark all as read". Strictly
 * the logged-in user's own (see routers/notifications.py) - there's
 * nothing here to permission-check beyond already being logged in. */
export default function NotificationBell({ onNavigateToEntry, onNavigateToInvites }: Props) {
  const { token } = useAuth()
  const [open, setOpen] = useState(false)
  const [unreadCount, setUnreadCount] = useState(0)
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!token) return
    function refresh() {
      if (!token) return
      fetchUnreadNotificationCount(token)
        .then(setUnreadCount)
        .catch(() => {
          // A failed background poll shouldn't surface an error banner -
          // the badge just stays at its last known value until the next
          // successful poll (or the panel itself is opened).
        })
    }
    refresh()
    const interval = setInterval(refresh, UNREAD_COUNT_POLL_MS)
    return () => clearInterval(interval)
  }, [token])

  useEffect(() => {
    if (!open || !token) return
    setLoading(true)
    setError(null)
    fetchNotifications({ limit: PAGE_SIZE, offset: 0 }, token)
      .then(setNotifications)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Could not load notifications.'))
      .finally(() => setLoading(false))
  }, [open, token])

  // Standard dropdown-panel behavior: a click anywhere outside closes it.
  useEffect(() => {
    if (!open) return
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  async function handleSelect(notification: Notification) {
    if (token && notification.read_at === null) {
      try {
        const updated = await markNotificationRead(notification.id, token)
        setNotifications((prev) => prev.map((n) => (n.id === updated.id ? updated : n)))
        setUnreadCount((prev) => Math.max(0, prev - 1))
      } catch {
        // Navigate anyway - read status is a nicety, not a gate on
        // actually getting the user where they're trying to go.
      }
    }
    setOpen(false)
    if (notification.type === 'comment' && notification.workspace_id !== null && notification.entry_id !== null) {
      onNavigateToEntry(notification.workspace_id, notification.entry_id)
    } else {
      onNavigateToInvites()
    }
  }

  async function handleMarkAllRead() {
    if (!token) return
    try {
      await markAllNotificationsRead(token)
      const now = new Date().toISOString()
      setNotifications((prev) => prev.map((n) => (n.read_at === null ? { ...n, read_at: now } : n)))
      setUnreadCount(0)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not mark notifications as read.')
    }
  }

  return (
    <div className="notification-bell" ref={containerRef}>
      <button
        type="button"
        className="notification-bell-btn"
        onClick={() => setOpen((v) => !v)}
        aria-label={unreadCount > 0 ? `Notifications (${unreadCount} unread)` : 'Notifications'}
      >
        <span aria-hidden="true">🔔</span>
        {unreadCount > 0 && <span className="notification-badge">{unreadCount > 99 ? '99+' : unreadCount}</span>}
      </button>

      {open && (
        <div className="notification-panel">
          <div className="notification-panel-header">
            <strong>Notifications</strong>
            {notifications.some((n) => n.read_at === null) && (
              <button type="button" className="link-btn" onClick={handleMarkAllRead}>
                Mark all as read
              </button>
            )}
          </div>

          {loading && <p>Loading...</p>}
          {error && <p className="error">{error}</p>}
          {!loading && !error && notifications.length === 0 && (
            <p className="hint">No notifications yet.</p>
          )}

          <ul className="notification-list">
            {notifications.map((n) => (
              <li key={n.id}>
                <button
                  type="button"
                  className={n.read_at === null ? 'notification-item unread' : 'notification-item'}
                  onClick={() => handleSelect(n)}
                >
                  <span className="notification-message">{n.message}</span>
                  <span className="notification-time">{formatDateTime(n.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
