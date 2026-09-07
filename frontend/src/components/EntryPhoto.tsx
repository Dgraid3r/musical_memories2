import { useEffect, useState } from 'react'
import { fetchEntryImageBlob } from '../api'
import { useAuth } from '../auth/AuthContext'

interface Props {
  entryId: number
  imageId: number
}

/** Renders one entry photo, fetched through the permission-checked
 * /api/entries/{entryId}/images/{imageId} endpoint rather than a raw
 * static URL. A plain <img src="..."> can't attach an Authorization
 * header, so this fetches the bytes itself (with the caller's token,
 * when logged in - a public entry's photo works with none at all) and
 * hands <img> an object URL instead, revoked on unmount/change to avoid
 * leaking memory. */
export default function EntryPhoto({ entryId, imageId }: Props) {
  const { token } = useAuth()
  const [src, setSrc] = useState<string | null>(null)

  useEffect(() => {
    let objectUrl: string | null = null
    let cancelled = false

    fetchEntryImageBlob(entryId, imageId, token)
      .then((blob) => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(blob)
        setSrc(objectUrl)
      })
      .catch(() => {
        // A photo that fails to load (e.g. access no longer permitted)
        // just doesn't render - no broken-image icon, no error banner
        // for what's a secondary part of the entry.
      })

    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [entryId, imageId, token])

  if (!src) return null
  return <img src={src} alt="" />
}
