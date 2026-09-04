import { useState } from 'react'
import { ApiError, requestPasswordReset } from '../api'

interface Props {
  onBackToLogin: () => void
}

export default function ForgotPasswordPage({ onBackToLogin }: Props) {
  const [email, setEmail] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Deliberately not "did we find an account" - the backend always returns
  // the same generic response either way, and the frontend shows it
  // unconditionally too, so this flow never reveals whether an email is
  // registered.
  const [sent, setSent] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await requestPasswordReset(email)
      setSent(true)
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
        <p className="hint">Reset your password</p>

        {sent ? (
          <p className="hint">
            If that email address has an account, a password reset link has been sent to it. Check your
            inbox.
          </p>
        ) : (
          <>
            <label htmlFor="forgot-email">Email</label>
            <input
              id="forgot-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />

            {error && <p className="error">{error}</p>}

            <button type="submit" disabled={submitting || !email.trim()}>
              {submitting ? 'Sending...' : 'Send reset link'}
            </button>
          </>
        )}

        <button type="button" className="link-btn" onClick={onBackToLogin}>
          Back to log in
        </button>
      </form>
    </div>
  )
}
