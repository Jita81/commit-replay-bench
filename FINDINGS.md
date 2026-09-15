# FINDINGS — TypeScript scope (ui/src, ui/e2e), file-header programme 2026-09-15

Observed while documenting; nothing below was changed (docstrings and comments only).

1. **ui/src/screens/Signoff/contract.ts:247 — dead invalidation after a sign-off.**
   `useCreateSignoffWithAttestation.onSuccess` calls
   `qc.invalidateQueries({ queryKey: ['capability-map', s.repo] })`, but the capability map is
   keyed `['capability', repo, by]` (`keys.capability` in ui/src/api/hooks.ts:120). The key
   matches nothing, so the map's verification tier does not refresh after a successful sign-off
   until its 30 s stale time or a remount. The older `useCreateSignoff` in ui/src/api/hooks.ts:518
   uses the right prefix (`['capability', s.repo]`). Fix: use `['capability', s.repo]`.

2. **ui/src/screens/Routing/RoutingPage.tsx (Interval column) — synthesised upper bound.**
   `CiBar` is drawn with `high = min(1, point + (point - ci_low))` because a `RouteDecision`
   (src/crb/core/routing.py `RouteDecision.to_dict`, `RouteDecisionOut` in
   src/crb/server/schemas.py) carries `ci_low` only. The Wilson interval is asymmetric, so the
   drawn upper end — and the bar's `aria-label`, which calls it the 95 % CI — is not the
   server's `ci_high`. Routing itself is unaffected (only `ci_low` routes); the bar overstates
   precision near 1.0. Fix: add `ci_high` to `RouteDecision` / `RouteDecisionOut`, or read the
   cell's `ci_high` from the capability map. (A WHY comment now marks the line.)

3. **ui/src/test/utils.tsx:70 — `renderApp`'s `me` option is declared but never read.**
   `Opts.me?: Principal | null` is accepted and ignored; the principal always comes from the
   mocked `GET /auth/me`. Either wire it (seed `keys.me` on the query client) or drop it.

4. **docs/API.md "Contract notes (server ↔ UI)" — stale note on `GET /settings`.**
   The note says the UI's `{builders, sandbox_mode, retention, oidc_enabled, ledger_backend,
   apparatus_version, policy_version}` reading "is NOT yet served — see the W2-B report", but
   `get_settings_view` in src/crb/server/routes/admin.py:176 serves exactly that shape (plus
   `raw`). The note should be removed or rewritten.

5. **Naming collision (cosmetic): two `VerdictPill` components.**
   ui/src/components/VerdictPill.tsx renders a ROUTE; ui/src/screens/Runs/ReviewPanel.tsx
   exports another `VerdictPill` that renders a REVIEW verdict (`data-testid="review-verdict-*"`).
   ui/src/screens/Runs/TaskDetailPage.tsx and EvidenceDrawer import the review one. Not a bug,
   but a reader grepping for `VerdictPill` lands on the wrong one half the time; consider
   `ReviewVerdictPill`.

Tooling notes for the lead:
- `npx eslint` was not run: the UI has no ESLint configuration and no `eslint` package in
  `ui/package.json` / `node_modules` (a network install would have been needed). Typecheck
  (`tsc -b --noEmit`, which covers `src` and `e2e` via tsconfig.app.json / tsconfig.node.json)
  and the full vitest suite (17 files, 135 tests) pass.
- The walkthrough specs (ui/e2e/walkthrough/*.spec.ts) had their `/** … */` comment AFTER the
  import block; the standard needs it first, so each was hoisted above the imports (comment
  move only; no code reordered).
- `ui/e2e/smoke.spec.ts`: a glob like `'**/api/v1/**'` inside a `/** */` comment closes the
  comment early (`*/`) — avoid such literals in headers.
