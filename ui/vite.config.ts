/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

/**
 * Vite config for the crb UI.
 *
 * - Dev proxy: every `/api/*` call is forwarded to the crb server on
 *   127.0.0.1:8000 (override with CRB_API_ORIGIN). Cookies stay same-origin,
 *   so the `crb_session` / `crb_csrf` cookies work unchanged in dev, and the
 *   SSE stream at `/api/v1/runs/{id}/events` is passed through unbuffered.
 * - Docs: the eight user-facing guides under `../docs` are bundled into the UI as
 *   lazy chunks (`ui/src/help/docs.ts`); `server.fs.allow` lets the dev server (and
 *   vitest) read them from outside `ui/` — the production build needs no such setting.
 *   The list is exactly `ui/` and `../docs`: setting `allow` replaces Vite's default
 *   (the project root), so the root is named too, and nothing else in the repository
 *   is readable through `/@fs/` should the dev server ever be exposed beyond localhost.
 * - Build: static assets land in `ui/dist`; the server serves them behind
 *   the same origin as the API in production.
 * - Test: vitest with jsdom; `src/test/setup.ts` installs jest-dom matchers.
 */
const apiOrigin = process.env.CRB_API_ORIGIN ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // this project + the guides only, so `import.meta.glob('../../../docs/*.md')` resolves in
    // dev and vitest without opening the rest of the repository to the dev server
    fs: { allow: ['.', '../docs'] },
    proxy: {
      '/api': {
        target: apiOrigin,
        changeOrigin: false,
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
              proxyRes.headers['cache-control'] = 'no-cache'
              proxyRes.headers['x-accel-buffering'] = 'no'
            }
          })
        },
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: true,
  },
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
  },
})
