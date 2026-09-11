import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { AuthProvider } from './auth/AuthContext.tsx'
import { initSentry } from './sentry.ts'
import { ThemeProvider } from './theme/ThemeContext.tsx'
import { WorkspaceProvider } from './workspace/WorkspaceContext.tsx'

initSentry()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {/* Outside AuthProvider - the theme choice applies on the
        logged-out login/register screen too, not just once signed in. */}
    <ThemeProvider>
      <AuthProvider>
        <WorkspaceProvider>
          <App />
        </WorkspaceProvider>
      </AuthProvider>
    </ThemeProvider>
  </StrictMode>,
)
