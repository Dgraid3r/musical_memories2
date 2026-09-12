import { useEffect, useState } from 'react'

/** Tracks browser connectivity via the `online`/`offline` events, seeded
 * from navigator.onLine. Not a perfect signal (a browser can report
 * "online" while genuinely unable to reach anything, e.g. a captive
 * portal) but it's the standard one, and enough to decide whether to
 * offer the simplified offline entry form (see OfflineEntryForm.tsx)
 * and to gate the offline draft queue's automatic sync attempt (see
 * useOfflineDrafts.ts, which listens for the same `online` event
 * itself for that separate purpose). */
export function useOnlineStatus(): boolean {
  const [online, setOnline] = useState(() => navigator.onLine)

  useEffect(() => {
    function goOnline() {
      setOnline(true)
    }
    function goOffline() {
      setOnline(false)
    }
    window.addEventListener('online', goOnline)
    window.addEventListener('offline', goOffline)
    return () => {
      window.removeEventListener('online', goOnline)
      window.removeEventListener('offline', goOffline)
    }
  }, [])

  return online
}
