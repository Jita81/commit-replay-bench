# Integration notes

Append-only. Any module records here what it could not do inside its own directory: a change it needs to a frozen file,
a design detail that was impossible as written and the nearest working thing it implemented instead, or a seam another
module must honour. Each entry: date, module, what, why.

## 2026-10-16 — step zero (foundation)

Pinned versions (all verified to exist on the registry with `npm view <pkg>@<version> version`):
`onnxruntime-web` = `1.31.0-dev.20260914-8d85527a0` (exactly what `@huggingface/transformers@4.3.1` declares, and the
scratch-install value the design quotes); `@types/ws` = `8.18.2` (`npm view @types/ws version` at implementation).
No pinned version in design §3.1 was missing; nothing was re-pinned.

Deviations and decisions recorded by step zero:

1. **`GET /api/health` body.** Design §8.3 says `{ app: "exmap", version: "0.1.0", pid }`; the step-zero brief asked for
   `{ app: "exmap", version, ok: true }`. The route returns the union `{ app, version, ok: true, pid }` so both readers
   are satisfied. The launcher's probe only reads `app`.
2. **ORT runtime files: no copy step.** Design §7.1 and §8.2 serve `ort-wasm-simd-threaded.asyncify.{mjs,wasm}` straight
   from `node_modules/onnxruntime-web/dist` at `/ort/` via `resolveOrtDir(root)`; there is no `public/ort/`. Step zero
   follows the design: `src/server/static.ts` resolves and serves them, `startServer` refuses with `ORT_RUNTIME_MISSING`
   when a file is absent, and `scripts/build.mjs` step 3 deletes the dead `dist/web/assets/ort-wasm-*.wasm` copy Vite
   emits. Nothing is copied.
3. **`conversation.v1.json` is the §14 wrapper, not a byte copy.** The step-zero brief said "copied from
   `docs/FIXTURE-CONVERSATION.json`"; that file is a bare utterance array, while design §14 and the audio module's
   `parseReplayFixture` expect `{ version, title, story, speakers, utterances, ui }`. The shipped file is that wrapper with
   the `utterances` array copied verbatim (asserted equal at generation) and the `ui` array of §14; the per-row `expect`
   blocks are left for the classifier module to add.
4. **Server stubs that are real.** `src/server/main.ts` (`startServer`, CLI entry with SIGINT/SIGTERM close),
   `app.ts` (`buildApp`: Fastify with `bodyLimit` 1 MiB, `trustProxy: false`, the `exmap` decoration, the health route,
   static roots), `static.ts`, `config.ts` (`findRoot`, `packageVersion`, `configFromEnv`), `home.ts` (`ensureHomeDir`,
   `HomeLockedError`), `hash.ts`, `ids.ts`, `routes/meta.ts` (health only). Not done: `server.lock`, the Host guard,
   COOP/COEP and `no-store` headers, `/api/config`, settings, sessions, WebSocket. `buildApp` constructs a `SessionStore`
   whose methods throw, so the `exmap.store` decoration has the designed type without a fake.
5. **Core**: `createEngine` is implemented as the plain composition of §5.10 (no logic); `refusals.ts` and the `dod.ts`
   constants are real; everything else throws `not implemented: <name>`. `canonicalState`/`computeRevision` accept either
   the state's card map or a card list (`Readonly<Record<CardId, CardRecord>> | readonly CardRecord[]`) because §5.3 passes
   `state.cards` and §12.5 passes "live cards"; the core module may narrow this.
6. **Export**: `catalogue.ts` is real (three one-liners over the vendored JSON, which proves the
   `import … with { type: "json" }` path compiles under NodeNext and that tsc copies the JSON into
   `dist/server/export/`). The five mapper names are step zero's choice, since §12 names the files but not the functions:
   `backlogItem(ctx)`, `ticket(ctx)`, `ticketMarkdown(ctx)`, `feature(ctx)`, `evidence(ctx)`, each taking
   `ExportContext`. `draftsOf(p: ClassifierProposal): CardDraft[]` in `schema.ts` is likewise a guessed signature.
7. **Classifier `claude/client.ts`** types `ModelClient` against `@anthropic-ai/sdk/resources/messages`
   (`Message`, `MessageCreateParamsNonStreaming`), which is the SDK subpath that exports them.
8. **Web**: component stubs are functions returning `never` (they throw); `App.tsx` renders only the heading; the test
   hooks (`window.__exmap`) do not exist yet, so `tests/e2e/fixtures.ts#playUntil/skip` will fail until the web module
   adds them. `cardByText` assumes `data-testid="column-<kind>"` columns and `data-testid="card-…"` cards (§13.1); adjust
   with the component contract.
9. **`tsconfig.json`** holds project references without `composite: true` (editor support only, as §3.2 says); `tsc -b`
   is not a supported entry point — `npm run typecheck` runs the three configs.
10. **Vitest** projects set `globals: true` (tsconfig.test.json lists `vitest/globals`); tests still import from `vitest`
    explicitly.
11. **`/ort/*.mjs` is served as `application/javascript; charset=utf-8`**, not the `text/javascript` design §8.2 names:
    `@fastify/static`'s mime table maps `.mjs` that way. Browsers accept either JavaScript MIME type for module scripts,
    so the ORT loader works (verified: 200 with the full 53 057-byte body; `.wasm` is `application/wasm`). The server
    module may force `text/javascript` via `setHeaders` if it wants the letter of §8.2.
12. **Close waits for in-flight responses.** Fastify 5's default `forceCloseConnections: "idle"` closes idle keep-alive
    sockets but waits for a response still streaming (a client mid-way through the 26 MB wasm download). With idle
    clients the CLI exits 9 ms after SIGTERM and the launcher 13 ms after; with a client holding a half-read body the
    close waits for it. The launcher's second signal (exit 130) is the designed escape hatch; the server module may
    prefer `forceCloseConnections: true` plus the 1001 WebSocket close §11 step 8 describes.
13. **`onnxruntime-node` is in the lockfile and in `node_modules`** (a hard dependency of `@huggingface/transformers`);
    only its postinstall download is skipped (`.npmrc` + the launcher's env). Nothing in `src/` imports it.
    `npm ls onnxruntime-web` shows one copy (deduped). `node_modules` is ~704 MB here.
14. **Verified at step zero** (all exit 0): `npm install`; the three typechecks; `vitest run` (2 files, 6 tests);
    `npm run build` (vite + tsc, stamp written); `playwright test tests/e2e/smoke.spec.ts` (3 passed); the launcher with
    `EXMAP_NO_OPEN=1 EXMAP_PORT=0 EXMAP_HOME=<tmp>` (listening line in ~0.3 s warm, ~3.9 s with a rebuild; SIGTERM → 0);
    `scripts/dev.mjs --server-only` (`GET /` → 503 with the §8.2 text, `/ort/` served, SIGTERM stops both). Not
    exercised: `npm run dev` with Vite (the proxy config is as §3.2), Windows paths in `locateNpm`/`start.ps1`.
