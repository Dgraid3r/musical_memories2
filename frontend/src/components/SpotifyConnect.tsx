import { useEffect, useState } from 'react'
import { fetchSpotifyStatus, getSpotifyConnectUrl } from '../api'
import { useAuth } from '../auth/AuthContext'

export default function SpotifyConnect() {
  const { token } = useAuth()
  const [connected, setConnected] = useState<boolean | null>(null)
  const [connecting, setConnecting] = useState(false)

  useEffect(() => {
    if (!token) return
    fetchSpotifyStatus(token)
      .then((s) => setConnected(s.connected))
      .catch(() => setConnected(null))
  }, [token])

  async function handleConnect() {
    if (!token) return
    setConnecting(true)
    try {
      const url = await getSpotifyConnectUrl(token)
      window.location.href = url
    } catch {
      setConnecting(false)
    }
  }

  if (connected === null) return null

  return (
    <div className="spotify-connect">
      {connected ? (
        <span className="spotify-connect-status connected">Spotify connected</span>
      ) : (
        <button type="button" className="link-btn" onClick={handleConnect} disabled={connecting}>
          {connecting ? 'Redirecting...' : 'Connect Spotify'}
        </button>
      )}
    </div>
  )
}
