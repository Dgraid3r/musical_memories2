import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

export type ThemeChoice = 'light' | 'dark' | 'system'

// Same localStorage-preference pattern AuthContext.tsx already uses for
// the access token, not a new mechanism - see that file's
// TOKEN_STORAGE_KEY. Keep this string in sync with the inline
// no-flash script in index.html.
const THEME_STORAGE_KEY = 'musical_memories_theme'

interface ThemeContextValue {
  theme: ThemeChoice
  setTheme: (theme: ThemeChoice) => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

function isThemeChoice(value: string | null): value is ThemeChoice {
  return value === 'light' || value === 'dark' || value === 'system'
}

/** "system" is represented by the *absence* of the data-theme attribute,
 * not a third attribute value - App.css's `@media (prefers-color-scheme:
 * dark)` block only takes over when no attribute is present at all, and
 * an explicit "light"/"dark" choice always wins over OS preference
 * either way. */
function applyTheme(theme: ThemeChoice) {
  if (theme === 'system') {
    document.documentElement.removeAttribute('data-theme')
  } else {
    document.documentElement.setAttribute('data-theme', theme)
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeChoice>(() => {
    let stored: string | null = null
    try {
      stored = localStorage.getItem(THEME_STORAGE_KEY)
    } catch {
      // localStorage unavailable (private browsing, etc.) - fall back
      // to system, same as never having chosen.
    }
    return isThemeChoice(stored) ? stored : 'system'
  })

  // Re-applied on every change (and once on mount) so switching is
  // instant with no page reload - just a DOM attribute flipping and the
  // CSS custom properties in App.css reacting to it. index.html's inline
  // script already applied an explicit stored choice before this ever
  // runs, so there's no flash on load either.
  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  function setTheme(next: ThemeChoice) {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next)
    } catch {
      // Preference just won't survive a refresh in this browsing mode -
      // still apply it for the current session.
    }
    setThemeState(next)
  }

  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider')
  return ctx
}
