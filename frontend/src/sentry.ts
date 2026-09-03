import * as Sentry from '@sentry/react'

/**
 * Opt-in via VITE_SENTRY_DSN: if it's not set, this is a no-op - the
 * captain doesn't have a Sentry account set up yet, and the app must keep
 * working with nothing configured. Mirrors the backend's SENTRY_DSN
 * opt-in (see backend/app/sentry_config.py).
 */
export function initSentry(): void {
  const dsn = import.meta.env.VITE_SENTRY_DSN
  if (!dsn) return

  Sentry.init({ dsn, tracesSampleRate: 0 })
}
