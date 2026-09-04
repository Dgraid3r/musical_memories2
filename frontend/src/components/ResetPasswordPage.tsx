import { useState } from 'react'
import { ApiError, confirmPasswordReset } from '../api'

interface Props {
  token: string
  onDone: () => void
}

export default function ResetPasswordPage({ token, onDone }: Props) {
  const [newPassword, setNewPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await confirmPasswordReset(token, newPassword)
      setDone(true)
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : 'Something went wrong',
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="auth-shell">
      <form className="auth-form" onSubmit={handleSubmit}>
        <h1>Musical Memories</h1>
        <p className="hint">Choose a new password</p>

        {done ? (
          <>
            <p className="hint">Your password has been reset. You can now log in with your new password.</p>
            <button type="button" onClick={onDone}>
              Go to log in
            </button>
          </>
        ) : (
          <>
            <label htmlFor="reset-new-password">New password</label>
            <input
              id="reset-new-password"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              minLength={8}
              required
            />

            {error && <p className="error">{error}</p>}

            <button type="submit" disabled={submitting || newPassword.length < 8}>
              {submitting ? 'Please wait...' : 'Reset password'}
            </button>

            <button type="button" className="link-btn" onClick={onDone}>
              Back to log in
            </button>
          </>
        )}
      </form>
    </div>
  )
}
