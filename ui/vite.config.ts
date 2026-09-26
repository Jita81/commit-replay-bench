/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { markOffMachineRequest } from './src/dev/apiProxy'

/**
 * Vite config for the crb UI.
 *
 * - Dev proxy: every `/api/*` call is forwarded to the crb server on
 *   127.0.0.1:8000 (override with CRB_API_ORIGIN). Cookies stay same-origin,
 *   so the `crb_session` / `crb_csrf` cookies work unchanged in dev, and the
 *   SSE stream at `/api/v1/runs/{id}/events` is passed through unbuffered. The proxy
 *   connects from 127.0.0.1, so a request that reached it from another machine (the dev
 *   server started with `--host`) is marked with `X-Forwarded-For` before it is forwarded
 *   (`src/dev/apiProxy.ts`); the API then never treats it as a browser on this machine, which
 *   is what keeps automatic sign-in (ADR-0027) off it. `vite preview` inherits this proxy.
 * - Docs: the eight user-facing guides under `../docs` are bundled into the UI as
 *   lazy chunks (`ui/src/help/docs.ts`); `server.fs.allow` lets the dev server (and
 *   vitest) read them from outside `ui/` — the production build needs no such setting.
 *   The list is exactly `ui/` and `../docs`: setting `allow` replaces Vite's default
 *   (the project root), so the root is named too, and nothing else in the repository
 *   is readable through `/@fs/` should the dev server ever be exposed beyond localhost.
 * - Build: static assets land in `ui/dist`; the server serves them behind
 *   the same origin as the API in production.
 * - Test: vitest with jsdom; `src/test/setup.ts` installs jest-dom matchers; the per-test
 *   timeout is raised from vitest's 5 s default because the `ui-unit` CI job is blocking and
 *   runs on a slower shared runner than a developer's machine (see `test.testTimeout` below).
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
          // before the incoming headers are copied into the forwarded request (ADR-0027)
          proxy.on('start', (req) => markOffMachineRequest(req))
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
    // vitest's default is 5 s, which is a per-test budget the suite's `userEvent` cases do not
    // meet on a loaded machine: typing into a controlled React form re-renders on every
    // keystroke, and the dialog suites type whole JSON bodies. [measured] n = 56 files, the
    // full suite run twice on an 8-core Mac while the walkthrough held the other cores: 18
    // then 24 tests failed, every one "Test timed out in 5000ms", and all 44 of them passed
    // when the same five files ran alone (method: `npx vitest run` twice, then the failing
    // files alone; apparatus 2.2, 2026-09-22). The `ui-unit` CI job is blocking and runs on a
    // two-core shared runner, slower than that, so the default would fail green work. 20 s is
    // a real ceiling — a test that hangs still fails — not a way to let a slow screen through.
    testTimeout: 20_000,
    hookTimeout: 20_000,
  },
})
