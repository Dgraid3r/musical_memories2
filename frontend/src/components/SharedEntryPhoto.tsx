import { useEffect, useState } from 'react'
import { fetchSharedEntryImageBlob } from '../api'

interface Props {
  token: string
  imageId: number
}

/** The shared-link equivalent of EntryPhoto - fetches through the public,
 * token-scoped GET /api/shared/{token}/images/{imageId} instead of the
 * authenticated per-entry endpoint, since this view has no login and no
 * workspace context at all. */
export default function SharedEntryPhoto({ token, imageId }: Props) {
  const [src, setSrc] = useState<string | null>(null)

  useEffect(() => {
    let objectUrl: string | null = null
    let cancelled = false

    fetchSharedEntryImageBlob(token, imageId)
      .then((blob) => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(blob)
        setSrc(objectUrl)
      })
      .catch(() => {
        // Same "just don't render" fallback as EntryPhoto - a photo that
        // fails to load is a secondary part of the shared memory.
      })

    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [token, imageId])

  if (!src) return null
  return <img src={src} alt="" />
}
