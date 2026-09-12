import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, createEntry } from './api'
import {
  addOfflineDraft,
  deleteOfflineDraft,
  listOfflineDrafts,
  updateOfflineDraftStatus,
  type NewOfflineDraft,
  type OfflineDraft,
} from './offlineDrafts'
import type { JournalEntry } from './types'

interface UseOfflineDraftsResult {
  drafts: OfflineDraft[]
  syncing: boolean
  /** True for a few seconds right after a sync pass leaves the queue
   * completely empty - the "confirmation once everything's synced" the
   * queue UI shows, not a persistent state. */
  justSynced: boolean
  addDraft: (draft: NewOfflineDraft) => Promise<void>
  syncNow: () => Promise<void>
}

/** Owns the IndexedDB-backed offline draft queue's lifecycle: loads it
 * on mount, syncs automatically when the browser's `online` event fires,
 * and exposes `syncNow` for the visible manual "Sync now" action -
 * `online` alone isn't reliable enough to depend on exclusively (not
 * universally supported the same way everywhere, and can fire on a
 * connection that's technically back but still unusable). Each draft
 * syncs via the same POST .../entries endpoint (api.ts's createEntry)
 * normal entry creation uses, with no playlist/location/co-authors -
 * exactly what an offline capture could gather (see OfflineEntryForm.tsx).
 * A draft that fails to sync stays in the queue with its error recorded,
 * never silently dropped; one that succeeds is deleted from IndexedDB
 * and reported via onEntrySynced so the caller can show it as a real
 * entry immediately. */
export function useOfflineDrafts(
  token: string | null,
  onEntrySynced: (entry: JournalEntry) => void,
): UseOfflineDraftsResult {
  const [drafts, setDrafts] = useState<OfflineDraft[]>([])
  const [syncing, setSyncing] = useState(false)
  const [justSynced, setJustSynced] = useState(false)
  // syncNow is registered as a long-lived `online` event listener below,
  // so it reads the latest token/callback through a ref rather than
  // closing over stale ones from whichever render first attached the
  // listener - updated in an effect, not during render itself.
  const tokenRef = useRef(token)
  const onEntrySyncedRef = useRef(onEntrySynced)
  useEffect(() => {
    tokenRef.current = token
    onEntrySyncedRef.current = onEntrySynced
  }, [token, onEntrySynced])

  const refresh = useCallback(async () => {
    setDrafts(await listOfflineDrafts())
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const syncNow = useCallback(async () => {
    const currentToken = tokenRef.current
    if (!currentToken) return
    setSyncing(true)
    try {
      // Never re-attempt a draft already mid-sync (e.g. the manual
      // button clicked while an automatic online-triggered pass is
      // still running) - avoids submitting the same draft twice.
      const pending = (await listOfflineDrafts()).filter((d) => d.status !== 'syncing')
      let anySucceeded = false
      for (const draft of pending) {
        await updateOfflineDraftStatus(draft.id, 'syncing')
        setDrafts(await listOfflineDrafts())
        try {
          const entry = await createEntry(
            draft.workspaceId,
            {
              startDate: draft.startDate,
              endDate: draft.startDate,
              text: draft.text,
              playlist: null,
              images: draft.photos.map((photo) => new File([photo.blob], photo.name, { type: photo.type })),
              isPublic: false,
              coauthorUsernames: [],
              tags: draft.tags,
              location: null,
            },
            currentToken,
          )
          await deleteOfflineDraft(draft.id)
          anySucceeded = true
          onEntrySyncedRef.current(entry)
        } catch (err) {
          await updateOfflineDraftStatus(
            draft.id,
            'failed',
            err instanceof ApiError ? err.message : 'Could not reach the server. Will retry.',
          )
        }
      }
      const remaining = await listOfflineDrafts()
      setDrafts(remaining)
      if (anySucceeded && remaining.length === 0) {
        setJustSynced(true)
        setTimeout(() => setJustSynced(false), 4000)
      }
    } finally {
      setSyncing(false)
    }
  }, [])

  useEffect(() => {
    window.addEventListener('online', syncNow)
    return () => window.removeEventListener('online', syncNow)
  }, [syncNow])

  const addDraft = useCallback(
    async (draft: NewOfflineDraft) => {
      await addOfflineDraft(draft)
      await refresh()
    },
    [refresh],
  )

  return { drafts, syncing, justSynced, addDraft, syncNow }
}
