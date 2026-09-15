/**
 * vitest setup — jest-dom matchers and DOM cleanup after every test.
 *
 * Navigation
 * ----------
 * What it is:   The vitest `setupFiles` entry (ui/vite.config.ts).
 * What it does: Registers the jest-dom matchers (`toBeInTheDocument`, `toHaveAttribute` …)
 *               and unmounts every rendered tree after each test so no state leaks between
 *               cases.
 * How:          Two imports and one `afterEach(cleanup)`.
 * Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/vite.config.ts (names this file), ui/src/test/utils.tsx (the render and
 *               mock helpers every screen test uses), ui/tsconfig.app.json (the jest-dom
 *               types)
 * Tested by:    ui/src/test/setup.ts (runs before every vitest file)
 * Touch when:   a global matcher or polyfill is needed by every UI test; never for a new
 *               repository.
 */
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => {
  cleanup()
})
