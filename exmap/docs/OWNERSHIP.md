# Module ownership for the parallel implementation phase

Step zero laid every shared file so the parallel modules never conflict on one. Each directory below has exactly one
owner; a module edits only what it owns. Everything else it needs, it imports.

| Path | Owner | Notes |
|---|---|---|
| `src/core/` | **core** | `types.ts` is frozen (see below); every other file is a stub to replace |
| `src/classifier/` (incl. `claude/`) | **classifier** | `constants.ts` and `schema.ts` are real; the rest are stubs |
| `src/export/` (incl. `crb-catalogue.json`) | **export** | `catalogue.ts` is real; the catalogue JSON is a vendored copy, never edited |
| `src/server/` (incl. `routes/`) | **server** | `main.ts`, `app.ts`, `static.ts`, `config.ts`, `routes/meta.ts` start for real at step zero; extend, do not fork |
| `src/web/` except `src/web/audio/` | **web** | `App.tsx` is a placeholder; `hash.ts`, `api/client.ts#ApiError` are real; `public/replay/*` is shared data (see below) |
| `src/web/audio/` and `src/web/public/pcm-worklet.js` | **audio** | all stubs |
| `bin/`, `scripts/`, `start.sh`, `start.ps1` | **launcher** | working at step zero; `scripts/whisper-check.mjs` (manual) is the audio module's to add |
| `tests/unit/core/` | core | `types.test.ts` is the step-zero smoke test; keep it passing |
| `tests/unit/classifier/` | classifier | |
| `tests/unit/audio/`, `tests/unit/web/audio/` | audio | |
| `tests/unit/server/` | server | |
| `tests/unit/export/` | export | |
| `tests/unit/web/` (except `audio/`) | web | `setup.ts` and `smoke.test.tsx` are step-zero; extend `setup.ts`, do not replace its stubs |
| `tests/unit/launcher/` | launcher | |
| `tests/e2e/` | web (journey, replay, axe), audio (`audio.spec.ts`), launcher (`launcher.spec.ts`) | `fixtures.ts` is shared: add helpers, do not change existing ones; `smoke.spec.ts` stays |
| `tests/fixtures/audio/` | audio | |
| `tests/fixtures/sessions/` | server | prebuilt ledgers: valid, tampered, truncated |
| `docs/` | integration | `DESIGN.md`, `TEST-PLAN.md`, `FIXTURE-CONVERSATION.json` are the spec; `INTEGRATION-NOTES.md` is append-only, any module |
| `README.md` | integration phase | not written at step zero |

## Frozen files

These are frozen for the whole parallel phase. No module edits them:

`package.json`, `package-lock.json`, `.npmrc`, `tsconfig.base.json`, `tsconfig.server.json`, `tsconfig.web.json`,
`tsconfig.test.json`, `tsconfig.json`, `vite.config.ts`, `vitest.config.ts`, `playwright.config.ts`, `src/core/types.ts`.

A module that needs a change to a frozen file (a new dependency, a compiler option, a type) **does not make it**. It
records the exact change and the reason as a dated entry in `docs/INTEGRATION-NOTES.md`, works around it locally if it
can (a local type, a narrower cast), and the integration phase applies the change once for everyone.

## Shared data files

- `src/web/public/replay/conversation.v1.json` — the demo fixture (design §14). The `utterances` array is the verbatim
  copy of `docs/FIXTURE-CONVERSATION.json`; the classifier module adds the per-row `expect` blocks; the web and audio
  modules read it; nobody changes the utterance texts or labels.
- `src/web/public/replay/index.json` — lists the fixture; changes only when the fixture does.

## Import rules (design §3)

`src/core` imports nothing; `src/classifier` imports only types from `src/core`; `src/export` imports `src/core`;
`src/server` imports all three; `src/web` imports `src/core` at runtime and types from the others; `src/web/audio`
imports only types from `src/core`. Tests may import anything. Every import inside `src/` uses an explicit `.js`
extension.
