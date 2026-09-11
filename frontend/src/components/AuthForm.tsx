import { useEffect, useState } from 'react'
import { ApiError, fetchGoogleSignInConfig } from '../api'
import { useAuth } from '../auth/AuthContext'

interface Props {
  // Set when arriving via a workspace invite link - passed through to
  // registration so a brand-new account joins the workspace as part of the
  // same request, and email is locked/prefilled since the invite was sent
  // to a specific address.
  inviteToken?: string
  prefillEmail?: string
  initialMode?: 'login' | 'register'
  onForgotPassword?: () => void
}

export default function AuthForm({ inviteToken, prefillEmail, initialMode, onForgotPassword }: Props) {
  const { login, register } = useAuth()
  const [mode, setMode] = useState<'login' | 'register'>(initialMode ?? 'login')
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState(prefillEmail ?? '')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [googleEnabled, setGoogleEnabled] = useState(false)

  useEffect(() => {
    fetchGoogleSignInConfig()
      .then((c) => setGoogleEnabled(c.enabled))
      .catch(() => setGoogleEnabled(false))
  }, [])

  function handleGoogleSignIn() {
    // A plain browser navigation, not a fetch - the backend responds
    // with a redirect straight to Google, and eventually redirects the
    // browser back with a fresh token (see auth/AuthContext.tsx).
    window.location.href = '/api/auth/google/login'
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      if (mode === 'login') {
        await login(username, password)
      } else {
        await register(username, email, password, inviteToken)
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="auth-shell">
      <form className="auth-form" onSubmit={handleSubmit}>
        <h1>Musical Memories</h1>
        <p className="hint">{mode === 'login' ? 'Log in to your journal' : 'Create an account'}</p>

        {googleEnabled && (
          <>
            <button type="button" className="google-signin-btn" onClick={handleGoogleSignIn}>
              Sign in with Google
            </button>
            <div className="auth-divider">
              <span>or</span>
            </div>
          </>
        )}

        <label htmlFor="auth-username">Username</label>
        <input id="auth-username" value={username} onChange={(e) => setUsername(e.target.value)} required />

        {mode === 'register' && (
          <>
            <label htmlFor="auth-email">Email</label>
            <input
              id="auth-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              readOnly={!!prefillEmail}
              required
            />
          </>
        )}

        <label htmlFor="auth-password">Password</label>
        <input
          id="auth-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          minLength={mode === 'register' ? 8 : undefined}
          required
        />

        {error && <p className="error">{error}</p>}

        <button type="submit" disabled={submitting}>
          {submitting ? 'Please wait...' : mode === 'login' ? 'Log in' : 'Create account'}
        </button>

        {mode === 'login' && onForgotPassword && (
          <button type="button" className="link-btn" onClick={onForgotPassword}>
            Forgot your password?
          </button>
        )}

        {!prefillEmail && (
          <button
            type="button"
            className="link-btn"
            onClick={() => {
              setMode(mode === 'login' ? 'register' : 'login')
              setError(null)
            }}
          >
            {mode === 'login' ? "Need an account? Register" : 'Already have an account? Log in'}
          </button>
        )}
      </form>
    </div>
  )
}
