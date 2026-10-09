/**
 * makeQueryClient — the one query client, and the rule that every act re-reads the inbox.
 *
 * Navigation
 * ----------
 * What it is:   `makeQueryClient` (the app's `QueryClient` and every screen test's), the app's
 *               query defaults (`APP_QUERY_DEFAULTS`) and `DECISIONS_PREFIX`, the key every
 *               reading of the decisions inbox starts with.
 * What it does: Builds the client with a mutation cache that marks every decisions reading
 *               stale when any act settles — an Attest, a revoke, a gap signed, a calibration
 *               funded, a library entry sponsored or signed, a prevention registered, a
 *               re-measurement queued, and any act added later — so the nav badge and the
 *               Decisions page re-read the server's inbox at once instead of showing a person
 *               the act they have just taken still waiting (P-613). The rule is on the client,
 *               not on each hook, so a new act cannot forget it.
 * How:          `new QueryClient({ mutationCache: new MutationCache({ onSettled }) })`;
 *               `onSettled` invalidates `DECISIONS_PREFIX` (the active readings refetch, the
 *               others are marked stale and refetch when they mount). A refused act settles
 *               too: a refusal can mean the inbox moved under the person (someone else acted).
 * Layer:        ui — docs/ARCHITECTURE.md#44-outer-layers
 * ADRs:         none
 * Works with:   ui/src/main.tsx (the app's client), ui/src/test/utils.tsx (every screen test's
 *               client), ui/src/screens/Decisions/useDecisionCount.ts (the two readings under
 *               `DECISIONS_PREFIX`), src/crb/server/routes/decisions.py (the count is
 *               `no-cache`, so the re-read is not served from the browser's cache)
 * Tested by:    ui/src/screens/Decisions/useDecisionCount.test.tsx
 * Touch when:   never for a new repository; a query default changes for every screen, or a
 *               reading other than the inbox must follow every act.
 */
import { MutationCache, QueryClient, type DefaultOptions } from '@tanstack/react-query'

/** Every reading of the decisions inbox starts with this key (the list and the badge's count). */
export const DECISIONS_PREFIX = ['decisions'] as const

/**
 * The app's defaults: no refetch on window focus (a governance surface never changes under the
 * reader's eye — hooks opt in to polling explicitly), no retry, 10 s stale.
 */
export const APP_QUERY_DEFAULTS: DefaultOptions = {
  queries: { refetchOnWindowFocus: false, retry: false, staleTime: 10_000 },
}

/** A `QueryClient` whose every settled act re-reads the decisions inbox. */
export function makeQueryClient(defaultOptions: DefaultOptions = APP_QUERY_DEFAULTS): QueryClient {
  const client: QueryClient = new QueryClient({
    defaultOptions,
    mutationCache: new MutationCache({
      onSettled: () => void client.invalidateQueries({ queryKey: DECISIONS_PREFIX }),
    }),
  })
  return client
}
