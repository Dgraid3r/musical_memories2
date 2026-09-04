import { useState } from 'react'
import { ApiError, resendVerificationEmail } from '../api'
import { useAuth } from '../auth/AuthContext'

// Non-blocking - shown whenever the logged-in user hasn't verified their
// email yet, but never prevents any action elsewhere in the app. Nothing
// currently gates behind email_verified (see README/report).
export default function VerifyEmailBanner() {
  const { user, token } = useAuth()
  const [sending, setSending] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [dismissed, setDismissed] = useState(false)

  if (!user || user.email_verified || dismissed || !token) return null

  async function handleResend() {
    setSending(true)
    setMessage(null)
    try {
      const res = await resendVerificationEmail(token as string)
      setMessage(res.detail)
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : 'Could not resend the verification email.')
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="verify-email-banner hint">
      <span>
        Verify your email address ({user.email}) to keep your account secure.
        {message ? ` ${message}` : ''}
      </span>
      <span className="verify-email-banner-actions">
        <button type="button" className="link-btn" onClick={handleResend} disabled={sending}>
          {sending ? 'Sending...' : 'Resend email'}
        </button>
        <button type="button" className="link-btn" onClick={() => setDismissed(true)}>
          Dismiss
        </button>
      </span>
    </div>
  )
}
