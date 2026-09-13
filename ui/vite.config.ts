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
 * - Build: static assets land in `ui/dist`; the server serves them behind
 *   the same origin as the API in production.
 * - Test: vitest with jsdom; `src/test/setup.ts` installs jest-dom matchers.
 */
const apiOrigin = process.env.CRB_API_ORIGIN ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
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
