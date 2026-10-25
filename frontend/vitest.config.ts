import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Separate from vite.config.ts (rather than merging the PWA plugin's build
// in here too) because vite-plugin-pwa's closeBundle work has nothing to
// do with running component tests, and keeping this config minimal keeps
// `vitest` fast and keeps a PWA-build concern out of the test runner.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: false,
    // The default `forks` pool hangs ("Timeout waiting for worker to
    // respond") rather than running on this Windows dev setup; `threads`
    // runs reliably here and is still process-isolated per file.
    pool: 'threads',
  },
})
