/** IndexedDB-backed queue for entries drafted with no connectivity (see
 * OfflineEntryForm.tsx/useOfflineDrafts.ts). Deliberately its own tiny
 * hand-rolled wrapper rather than a library - IndexedDB itself already
 * persists across a reload/app-restart while still offline, which is
 * the one property this feature actually needs; nothing here depends on
 * anything the service worker (see vite.config.ts) does or caches.
 *
 * A draft stores exactly what an offline capture can gather without the
 * network: text, date, tags, and photo files as raw Blobs - never a
 * playlist/location/co-author, none of which degrade to a useful
 * offline experience (see OfflineEntryForm.tsx). Each draft remembers
 * the workspace it was captured in (see App.tsx's use of
 * WorkspaceContext.ACTIVE_WORKSPACE_STORAGE_KEY) so syncing later
 * attaches it to the right place even if the user has since switched
 * workspaces. */

const DB_NAME = 'musical_memories_offline_drafts'
const DB_VERSION = 1
const STORE_NAME = 'drafts'

export type OfflineDraftStatus = 'queued' | 'syncing' | 'failed'

export interface OfflineDraftPhoto {
  name: string
  type: string
  blob: Blob
}

export interface OfflineDraft {
  id: number
  workspaceId: number
  text: string
  startDate: string
  tags: string[]
  photos: OfflineDraftPhoto[]
  createdAt: string
  status: OfflineDraftStatus
  error: string | null
}

export type NewOfflineDraft = Pick<OfflineDraft, 'workspaceId' | 'text' | 'startDate' | 'tags' | 'photos'>

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'id', autoIncrement: true })
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

export async function addOfflineDraft(draft: NewOfflineDraft): Promise<number> {
  const db = await openDb()
  try {
    return await new Promise<number>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite')
      const record: Omit<OfflineDraft, 'id'> = {
        ...draft,
        createdAt: new Date().toISOString(),
        status: 'queued',
        error: null,
      }
      const request = tx.objectStore(STORE_NAME).add(record)
      let newId: number
      request.onsuccess = () => {
        newId = request.result as number
      }
      tx.oncomplete = () => resolve(newId)
      tx.onerror = () => reject(tx.error)
    })
  } finally {
    db.close()
  }
}

export async function listOfflineDrafts(): Promise<OfflineDraft[]> {
  const db = await openDb()
  try {
    return await new Promise<OfflineDraft[]>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readonly')
      const request = tx.objectStore(STORE_NAME).getAll()
      request.onsuccess = () => resolve(request.result as OfflineDraft[])
      request.onerror = () => reject(request.error)
    })
  } finally {
    db.close()
  }
}

export async function updateOfflineDraftStatus(
  id: number,
  status: OfflineDraftStatus,
  error: string | null = null,
): Promise<void> {
  const db = await openDb()
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite')
      const store = tx.objectStore(STORE_NAME)
      const getRequest = store.get(id)
      getRequest.onsuccess = () => {
        const record = getRequest.result as OfflineDraft | undefined
        // Already synced/deleted by a concurrent sync pass - nothing to
        // update, and not an error.
        if (!record) return
        record.status = status
        record.error = error
        store.put(record)
      }
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error)
    })
  } finally {
    db.close()
  }
}

export async function deleteOfflineDraft(id: number): Promise<void> {
  const db = await openDb()
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite')
      tx.objectStore(STORE_NAME).delete(id)
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error)
    })
  } finally {
    db.close()
  }
}
