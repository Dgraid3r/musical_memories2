import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    // Makes the app installable (manifest + icons) and lets the app shell
    // (HTML/CSS/JS/fonts) load with no connection, via a Workbox-generated
    // service worker - registered automatically (injectRegister: 'auto',
    // the default) with no custom update-prompt UI, since that's not
    // something this task needs. This alone does not make offline entry
    // creation work - see offlineDrafts.ts and OfflineDraftQueue.tsx for
    // the separate IndexedDB draft queue and its own online-triggered
    // sync, which is what actually lets a draft reach
    // POST /api/workspaces/{id}/entries once the connection returns.
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'favicon.ico', 'apple-touch-icon-180x180.png'],
      manifest: {
        name: 'Musical Memories',
        short_name: 'Musical Memories',
        description: 'Journal entries tied to the playlists that go with them.',
        // Same "Liner Notes" palette as App.css's :root tokens (light
        // theme, the default/unconfigured look) - never invented colors.
        // background_color is the splash-screen background shown before
        // the app's own CSS paints; theme_color tints the OS/browser
        // chrome (status bar, task switcher) around the app.
        background_color: '#f1f0eb',
        theme_color: '#8a2f3f',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: 'pwa-64x64.png', sizes: '64x64', type: 'image/png' },
          { src: 'pwa-192x192.png', sizes: '192x192', type: 'image/png' },
          { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png' },
          { src: 'maskable-icon-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        // Cache-first for the built app shell and the Google Fonts files
        // it loads (see index.html) - enough for the app to actually load
        // offline. Deliberately not attempting to cache arbitrary API
        // responses here (workspaces/entries/images) - that's a much
        // bigger "what's stale, for how long, for whom" problem this app
        // doesn't need; the offline story for *creating* content is the
        // separate IndexedDB draft queue in offlineDrafts.ts, not a
        // cached API response.
        globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2}'],
        runtimeCaching: [
          {
            urlPattern: /^https:\/\/fonts\.googleapis\.com\/.*/i,
            handler: 'CacheFirst',
            options: {
              cacheName: 'google-fonts-stylesheets',
            },
          },
          {
            urlPattern: /^https:\/\/fonts\.gstatic\.com\/.*/i,
            handler: 'CacheFirst',
            options: {
              cacheName: 'google-fonts-webfonts',
              expiration: {
                maxEntries: 30,
                maxAgeSeconds: 60 * 60 * 24 * 365,
              },
              cacheableResponse: {
                statuses: [0, 200],
              },
            },
          },
        ],
      },
    }),
  ],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  // `vite preview` (serving the real production build - the only way the
  // service worker/manifest below actually run, since the dev server
  // intentionally skips PWA generation) doesn't inherit `server.proxy`,
  // so it needs its own copy to reach the backend the same way.
  preview: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
