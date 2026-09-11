import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { fetchCurrentUser, login as apiLogin, registerUser } from '../api'
import type { User } from '../types'

const TOKEN_STORAGE_KEY = 'musical_memories_token'

/** Reads a freshly-issued token out of the URL fragment left by the
 * Google sign-in redirect (GET /api/auth/google/callback ->
 * `<frontend>/#token=...`) and strips it from the URL immediately -
 * called at most once, from the token useState's lazy initializer below.
 * A fragment (never a query param) is what the backend deliberately used
 * here specifically because it's never sent to any server (ours or a
 * proxy/CDN in front of it) or written to access logs - see
 * routers/google_auth.py's callback docstring. */
function readTokenFromFragment(): string | null {
  if (!window.location.hash) return null
  const params = new URLSearchParams(window.location.hash.slice(1))
  const token = params.get('token')
  if (!token) return null
  params.delete('token')
  const rest = params.toString()
  window.history.replaceState(
    {},
    '',
    window.location.pathname + window.location.search + (rest ? `#${rest}` : ''),
  )
  return token
}

interface AuthContextValue {
  user: User | null
  token: string | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  register: (username: string, email: string, password: string, inviteToken?: string) => Promise<void>
  logout: () => void
  refreshUser: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  // A token delivered via the Google sign-in redirect fragment takes
  // priority over anything already in localStorage (it's the freshest
  // possible credential, e.g. after signing in as a different Google
  // account than whichever local session was previously stored).
  const [token, setToken] = useState<string | null>(
    () => readTokenFromFragment() ?? localStorage.getItem(TOKEN_STORAGE_KEY),
  )
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!token) {
      setLoading(false)
      return
    }
    fetchCurrentUser(token)
      .then((currentUser) => {
        // Persisted here (not just after a plain login()) so a token
        // that arrived via the fragment - which never goes through
        // login() - is stored through that exact same mechanism once
        // validated, rather than a second parallel storage path.
        localStorage.setItem(TOKEN_STORAGE_KEY, token)
        setUser(currentUser)
      })
      .catch(() => {
        // stored token is stale/invalid - drop it and require login again
        localStorage.removeItem(TOKEN_STORAGE_KEY)
        setToken(null)
        setUser(null)
      })
      .finally(() => setLoading(false))
  }, [token])

  async function login(username: string, password: string) {
    const accessToken = await apiLogin(username, password)
    const currentUser = await fetchCurrentUser(accessToken)
    localStorage.setItem(TOKEN_STORAGE_KEY, accessToken)
    setToken(accessToken)
    setUser(currentUser)
  }

  async function register(username: string, email: string, password: string, inviteToken?: string) {
    await registerUser(username, email, password, inviteToken)
    await login(username, password)
  }

  function logout() {
    localStorage.removeItem(TOKEN_STORAGE_KEY)
    setToken(null)
    setUser(null)
  }

  async function refreshUser() {
    if (!token) return
    setUser(await fetchCurrentUser(token))
  }

  return (
    <AuthContext.Provider value={{ user, token, loading, login, register, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
