import { useEffect, useState } from 'react'
import { ApiError, confirmEmailVerification, deleteEntry, fetchEntries, previewInvite } from './api'
import { useAuth } from './auth/AuthContext'
import AccountSettings from './components/AccountSettings'
import AdminDashboard from './components/AdminDashboard'
import AuthForm from './components/AuthForm'
import EntryCard from './components/EntryCard'
import ForgotPasswordPage from './components/ForgotPasswordPage'
import InviteAcceptPrompt from './components/InviteAcceptPrompt'
import MapView from './components/MapView'
import MyInvites from './components/MyInvites'
import NewEntryForm from './components/NewEntryForm'
import NotificationBell from './components/NotificationBell'
import PublicWorkspaceBrowser from './components/PublicWorkspaceBrowser'
import ResetPasswordPage from './components/ResetPasswordPage'
import SearchBar from './components/SearchBar'
import SpotifyConnect from './components/SpotifyConnect'
import VerifyEmailBanner from './components/VerifyEmailBanner'
import WorkspaceSettings from './components/WorkspaceSettings'
import WorkspaceSwitcher from './components/WorkspaceSwitcher'
import type { InvitePreview, JournalEntry } from './types'
import { useWorkspace } from './workspace/WorkspaceContext'
import './App.css'

// Same "load more" pagination convention as PublicWorkspaceBrowser.tsx -
// same page size, same hasMore-from-a-short-page derivation.
const ENTRIES_PAGE_SIZE = 20

function useSpotifyCallbackNotice(): string | null {
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const spotifyResult = params.get('spotify')
    if (!spotifyResult) return

    if (spotifyResult === 'connected') {
      setNotice('Spotify account connected.')
    } else if (spotifyResult === 'unavailable') {
      setNotice('Spotify is temporarily unavailable, try again shortly.')
    } else {
      setNotice('Spotify connection was not completed.')
    }
    params.delete('spotify')
    const rest = params.toString()
    window.history.replaceState({}, '', window.location.pathname + (rest ? `?${rest}` : ''))
  }, [])

  return notice
}

/** Google sign-in's error outcomes (success delivers a token via the URL
 * fragment instead - see auth/AuthContext.tsx - so there's no "connected"
 * case to handle here, unlike Spotify's). */
function useGoogleSignInNotice(): string | null {
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const googleResult = params.get('google')
    if (!googleResult) return

    if (googleResult === 'denied') {
      setNotice('Google sign-in was not completed.')
    } else if (googleResult === 'unavailable') {
      setNotice('Google sign-in is temporarily unavailable, try again shortly.')
    } else if (googleResult === 'invalid_token') {
      setNotice("Could not verify your Google account's identity - please try again.")
    } else if (googleResult === 'account_deleted') {
      setNotice('That account has been deleted and can no longer be signed into.')
    } else if (googleResult === 'account_deactivated') {
      setNotice('That account has been deactivated. Contact an admin if you think this is a mistake.')
    } else if (googleResult === 'email_unverified_conflict') {
      setNotice(
        'An account with this email already exists but has not verified its address yet, so it ' +
          "cannot be linked to Google sign-in automatically. Log in with that account's password and " +
          'verify its email first, or contact support if you no longer have access to it.'
      )
    } else {
      setNotice('Google sign-in could not be completed - please try again.')
    }
    params.delete('google')
    const rest = params.toString()
    window.history.replaceState({}, '', window.location.pathname + (rest ? `?${rest}` : ''))
  }, [])

  return notice
}

/** Reads a query param exactly once on first mount and strips it from the
 * URL, the same one-shot pattern as useSpotifyCallbackNotice - used for
 * ?invite=, ?verify=, and ?reset= links landed on from an email. */
function useOneShotUrlParam(name: string): string | null {
  const [value] = useState<string | null>(() => new URLSearchParams(window.location.search).get(name))

  useEffect(() => {
    if (!value) return
    const params = new URLSearchParams(window.location.search)
    params.delete(name)
    const rest = params.toString()
    window.history.replaceState({}, '', window.location.pathname + (rest ? `?${rest}` : ''))
    // Only ever needs to run once, right after mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return value
}

export default function App() {
  const { user, token, loading: authLoading, logout } = useAuth()
  const {
    activeWorkspace,
    loading: workspaceLoading,
    error: workspaceError,
    refresh: refreshWorkspaces,
    switchWorkspace,
  } = useWorkspace()
  const [entries, setEntries] = useState<JournalEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [showPublicBrowser, setShowPublicBrowser] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [showAccountSettings, setShowAccountSettings] = useState(false)
  const [showForgotPassword, setShowForgotPassword] = useState(false)
  const [showMapView, setShowMapView] = useState(false)
  const [showAdminDashboard, setShowAdminDashboard] = useState(false)
  const [showMyInvites, setShowMyInvites] = useState(false)
  // Set when a map pin's "View this memory" is clicked - closes the map
  // and scrolls that entry's card into view once the (already-loaded)
  // list is showing again. Cleared right after scrolling so it doesn't
  // re-trigger on an unrelated re-render.
  const [scrollToEntryId, setScrollToEntryId] = useState<number | null>(null)
  const spotifyNotice = useSpotifyCallbackNotice()
  const googleNotice = useGoogleSignInNotice()

  // --- Workspace invite accept flow (?invite=TOKEN) ------------------
  const inviteTokenFromUrl = useOneShotUrlParam('invite')
  const [inviteToken, setInviteToken] = useState(inviteTokenFromUrl)
  const [invitePreview, setInvitePreview] = useState<InvitePreview | null>(null)
  const [inviteError, setInviteError] = useState<string | null>(null)
  const [inviteAcceptedNotice, setInviteAcceptedNotice] = useState<string | null>(null)

  useEffect(() => {
    if (!inviteToken) return
    previewInvite(inviteToken)
      .then(setInvitePreview)
      .catch((err) => {
        setInviteError(err instanceof ApiError ? err.message : 'This invite link is not valid.')
        setInviteToken(null)
      })
  }, [inviteToken])

  function handleInviteAccepted() {
    setInviteAcceptedNotice(`You've joined "${invitePreview?.workspace_name}".`)
    setInviteToken(null)
    setInvitePreview(null)
    refreshWorkspaces()
  }

  function dismissInvite() {
    setInviteToken(null)
    setInvitePreview(null)
  }

  // --- Email verification (?verify=TOKEN) -----------------------------
  const verifyToken = useOneShotUrlParam('verify')
  const [verifyNotice, setVerifyNotice] = useState<string | null>(null)

  useEffect(() => {
    if (!verifyToken) return
    confirmEmailVerification(verifyToken)
      .then(() => setVerifyNotice('Your email address has been verified.'))
      .catch((err) =>
        setVerifyNotice(
          err instanceof ApiError ? err.message : 'This verification link is invalid or has expired.',
        ),
      )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [verifyToken])

  // --- Password reset (?reset=TOKEN) - its own standalone page --------
  const resetTokenFromUrl = useOneShotUrlParam('reset')
  const [resetToken, setResetToken] = useState(resetTokenFromUrl)

  useEffect(() => {
    if (authLoading || !activeWorkspace) return
    setLoading(true)
    fetchEntries(activeWorkspace.id, token, { q: searchQuery || undefined, limit: ENTRIES_PAGE_SIZE, offset: 0 })
      .then((page) => {
        setEntries(page)
        setHasMore(page.length === ENTRIES_PAGE_SIZE)
      })
      .catch(() => setError('Could not load memories.'))
      .finally(() => setLoading(false))
  }, [token, authLoading, activeWorkspace, searchQuery])

  async function loadMoreEntries() {
    if (!activeWorkspace) return
    setLoadingMore(true)
    try {
      const page = await fetchEntries(activeWorkspace.id, token, {
        q: searchQuery || undefined,
        limit: ENTRIES_PAGE_SIZE,
        offset: entries.length,
      })
      setEntries((prev) => [...prev, ...page])
      setHasMore(page.length === ENTRIES_PAGE_SIZE)
    } catch {
      setHasMore(false)
    } finally {
      setLoadingMore(false)
    }
  }

  // Runs after the map closes and the (unfiltered, already-loaded) list is
  // showing again - the target entry is almost certainly already in
  // `entries`, but if it isn't yet rendered this simply no-ops rather than
  // erroring, and the id stays pending harmlessly until it is.
  useEffect(() => {
    if (scrollToEntryId === null || showMapView) return
    const el = document.getElementById(`entry-${scrollToEntryId}`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      setScrollToEntryId(null)
    }
  }, [scrollToEntryId, showMapView, entries])

  function handleViewEntryFromMap(entryId: number) {
    setShowMapView(false)
    setScrollToEntryId(entryId)
  }

  // A "comment" notification's target entry might not be in the
  // currently-loaded page (a different search filter, or just further
  // back than the first page) - clearing the search and switching to
  // the entry's own workspace maximizes the chance it's actually there
  // once the list reloads. Same accepted limitation as
  // handleViewEntryFromMap above if it still isn't: the scroll-target
  // effect simply no-ops and the id stays pending harmlessly.
  function handleNavigateToEntryFromNotification(workspaceId: number, entryId: number) {
    setShowMyInvites(false)
    setShowAdminDashboard(false)
    setShowMapView(false)
    setSearchQuery('')
    if (workspaceId !== activeWorkspace?.id) {
      switchWorkspace(workspaceId)
    }
    setScrollToEntryId(entryId)
  }

  function handleNavigateToInvitesFromNotification() {
    setShowAdminDashboard(false)
    setShowMapView(false)
    setShowMyInvites(true)
  }

  async function handleDelete(id: number) {
    if (!token || !activeWorkspace) return
    await deleteEntry(activeWorkspace.id, id, token)
    setEntries((prev) => prev.filter((e) => e.id !== id))
  }

  function handleUpdated(updated: JournalEntry) {
    setEntries((prev) => prev.map((e) => (e.id === updated.id ? updated : e)))
  }

  if (authLoading) return null

  if (resetToken) {
    return <ResetPasswordPage token={resetToken} onDone={() => setResetToken(null)} />
  }

  if (showPublicBrowser) {
    return <PublicWorkspaceBrowser onClose={() => setShowPublicBrowser(false)} />
  }

  // A logged-in user (whether they just registered/logged in to accept
  // this invite, or already had a session open and clicked the link)
  // confirms joining explicitly here - acceptance is never automatic.
  if (user && inviteToken && invitePreview) {
    return (
      <InviteAcceptPrompt
        token={inviteToken}
        preview={invitePreview}
        onAccepted={handleInviteAccepted}
        onDismiss={dismissInvite}
      />
    )
  }

  if (!user) {
    if (showForgotPassword) {
      return <ForgotPasswordPage onBackToLogin={() => setShowForgotPassword(false)} />
    }
    return (
      <>
        {invitePreview && (
          <p className="hint invite-banner">
            You've been invited to join <strong>{invitePreview.workspace_name}</strong> as a{' '}
            <strong>{invitePreview.role}</strong> -{' '}
            {invitePreview.account_exists ? 'log in to accept.' : 'create an account below to accept.'}
          </p>
        )}
        {inviteError && <p className="error invite-banner">{inviteError}</p>}
        {verifyNotice && <p className="hint">{verifyNotice}</p>}
        {googleNotice && <p className="hint">{googleNotice}</p>}
        <AuthForm
          inviteToken={invitePreview && !invitePreview.account_exists ? inviteToken ?? undefined : undefined}
          prefillEmail={invitePreview && !invitePreview.account_exists ? invitePreview.email : undefined}
          initialMode={invitePreview ? (invitePreview.account_exists ? 'login' : 'register') : undefined}
          onForgotPassword={() => setShowForgotPassword(true)}
        />
        <p className="public-browse-link">
          <button type="button" className="link-btn" onClick={() => setShowPublicBrowser(true)}>
            Browse public journals without logging in
          </button>
        </p>
      </>
    )
  }

  if (showAdminDashboard && user.is_admin) {
    return <AdminDashboard onClose={() => setShowAdminDashboard(false)} />
  }

  if (showMyInvites) {
    return (
      <MyInvites
        onClose={() => setShowMyInvites(false)}
        onAccepted={() => {
          refreshWorkspaces()
          setShowMyInvites(false)
        }}
      />
    )
  }

  // A subscriber can read everything in the active workspace but can't
  // create entries, add photos, or comment - the entry-specific
  // owner/co-author actions inside EntryCard are already correctly hidden
  // for a subscriber on their own (they can never own or co-author an
  // entry), so this flag only needs to gate the "new memory" form here and
  // the comment box inside each EntryCard.
  const canWrite = activeWorkspace?.role !== 'subscriber'

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <h1>Musical Memories</h1>
          <p>Journal entries tied to the playlists that go with them.</p>
        </div>
        <div className="account-bar">
          <WorkspaceSwitcher />
          {activeWorkspace && (
            <button type="button" className="link-btn" onClick={() => setShowSettings(true)}>
              Settings
            </button>
          )}
          {activeWorkspace && (
            <button type="button" className="link-btn" onClick={() => setShowMapView((v) => !v)}>
              {showMapView ? 'List view' : 'Map view'}
            </button>
          )}
          <button type="button" className="link-btn" onClick={() => setShowPublicBrowser(true)}>
            Browse public
          </button>
          <button type="button" className="link-btn" onClick={() => setShowMyInvites(true)}>
            Invites
          </button>
          <NotificationBell
            onNavigateToEntry={handleNavigateToEntryFromNotification}
            onNavigateToInvites={handleNavigateToInvitesFromNotification}
          />
          {user.is_admin && (
            <button type="button" className="link-btn" onClick={() => setShowAdminDashboard(true)}>
              Admin
            </button>
          )}
          <span>{user.username}</span>
          <button type="button" className="link-btn" onClick={() => setShowAccountSettings(true)}>
            Account
          </button>
          <SpotifyConnect />
          <button type="button" className="link-btn" onClick={logout}>
            Log out
          </button>
        </div>
      </header>

      {spotifyNotice && <p className="hint spotify-notice">{spotifyNotice}</p>}
      {verifyNotice && <p className="hint spotify-notice">{verifyNotice}</p>}
      {inviteAcceptedNotice && <p className="hint spotify-notice">{inviteAcceptedNotice}</p>}
      {inviteError && <p className="error spotify-notice">{inviteError}</p>}
      <VerifyEmailBanner />

      {showSettings && activeWorkspace && <WorkspaceSettings onClose={() => setShowSettings(false)} />}
      {showAccountSettings && <AccountSettings onClose={() => setShowAccountSettings(false)} />}

      <main>
        {workspaceLoading && <p>Loading workspaces...</p>}
        {!workspaceLoading && workspaceError && <p className="error">{workspaceError}</p>}
        {!workspaceLoading && !workspaceError && !activeWorkspace && (
          <p className="hint">
            You don't belong to a workspace yet - create one above to start adding memories.
          </p>
        )}

        {activeWorkspace && showMapView && (
          <MapView workspaceId={activeWorkspace.id} onViewEntry={handleViewEntryFromMap} />
        )}

        {activeWorkspace && !showMapView && (
          <>
            {canWrite && (
              <NewEntryForm
                workspaceId={activeWorkspace.id}
                onCreated={(entry) => setEntries((prev) => (searchQuery ? prev : [entry, ...prev]))}
              />
            )}
            {!canWrite && (
              <p className="hint subscriber-notice">
                You're a subscriber here - you can read everything, but only an owner or member can add or edit
                memories.
              </p>
            )}

            <SearchBar onSearch={setSearchQuery} />

            <section className="entry-list">
              {loading && <p>Loading...</p>}
              {error && <p className="error">{error}</p>}
              {!loading && !error && entries.length === 0 && searchQuery && (
                <p className="hint">No memories match "{searchQuery}".</p>
              )}
              {!loading && !error && entries.length === 0 && !searchQuery && (
                <p className="hint">No memories yet — add your first one above.</p>
              )}
              {entries.map((entry) => (
                <EntryCard
                  key={entry.id}
                  entry={entry}
                  workspaceId={activeWorkspace.id}
                  canWrite={canWrite}
                  onDelete={handleDelete}
                  onUpdated={handleUpdated}
                />
              ))}
              {!loading && hasMore && (
                <button type="button" className="link-btn" onClick={loadMoreEntries} disabled={loadingMore}>
                  {loadingMore ? 'Loading...' : 'Load more'}
                </button>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  )
}
