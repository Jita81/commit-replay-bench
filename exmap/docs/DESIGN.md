# Example Map Live (`exmap`) — Design

Status: the implementation design. It synthesises the four revised sub-specs (core engine, classifier, audio pipeline, server/UI/launcher/export) and the brief into one internally consistent document. Where this document and a sub-spec differ, this document wins; every such difference is listed with its reason in §18 (decision log). Nothing in `exmap/` imports from crb; `exmap/` is outside every crb CI gate.

Companion files: `docs/FIXTURE-CONVERSATION.json` (the scripted conversation, plain utterance array) and `docs/TEST-PLAN.md` (every unit and e2e test by module). `docs/` holds no other files.

## 0. How to read this document

| § | Contents |
|---|---|
| 1 | Product statement: what it is, the interaction model, the honesty rules |
| 2 | Fixed decisions (from the brief) and the recorded deviations |
| 3 | Repository layout |
| 4 | The shared type model — `exmap/src/core/types.ts` in full |
| 5 | Core engine semantics: canonical JSON, chain, revision, reducer, `apply()`, DoD, undo |
| 6 | Classifier: interface, `rules.v1`, `claude` (frozen system prompt in full), clarification protocol |
| 7 | Audio pipeline: lanes, VAD, segmenter, providers, queues, speakers, components |
| 8 | Server: HTTP + WebSocket API with JSON shapes, the classifier bridge |
| 9 | Persistence: home directory, ledger file, locks, load and verify |
| 10 | Web UI |
| 11 | Launcher and one-command start |
| 12 | Export mappers and the vendored crb catalogue |
| 13 | Test plan (summary; the full list is `TEST-PLAN.md`) |
| 14 | The fixture conversation with expected proposals |
| 15 | README outline |
| 16 | Non-goals |
| 17 | Open risks and `[VERIFY]` items |
| 18 | Decision log: every cross-spec conflict and how it was resolved |

Names are used exactly once: one name per type, event, operation, route and field. The type block in §4 is normative; prose elsewhere refers to it.

## 1. Product statement

**Example Map Live** (`exmap`) is a local-first, voice-driven requirements modeller. It listens to a live discussion (a Teams call captured in the browser, the user's own microphone, typed text, or a scripted replay), turns each utterance into a *proposal* against an Example Map (one story, rules, examples, questions), applies valid proposals so the map evolves while people talk, and lets people create, amend, reject, remove, replace, clarify, confirm and undo through natural conversation or clicks. Every change is an event in an append-only hash-chained ledger with full provenance. The product produces a requirement — and the crb factory export files — only after an authorised person has reviewed the complete map and recorded a sign-off that the Definition of Done gate has passed. Any later substantive change invalidates that sign-off.

The human owns the meaning; the software owns the mechanics of structuring it.

### 1.1 The interaction model (brief §0, supported end to end)

1. **Talk naturally.** "A patient should be able to cancel online, but not within two hours of their appointment." The utterance is recorded with its lane, the speaker label a person assigned, provider, timing and locality.
2. **Watch the map populate.** The classifier proposes `card.create` for a rule; the engine validates and applies it in the same batch; the card appears with provenance (utterance ids, proposal id, classifier, confidence, rationale). Examples and questions follow as the conversation develops.
3. **Change your mind by talking.** "Actually, make that 24 hours for nurse appointments. Keep two hours for GPs." → `card.update`; the rule gains a new version, its history is kept, and every live example linked to it is flagged `needs_review`.
4. **Remove or redo conversationally.** "Delete that example. It's not what I meant." → `card.remove` when the target is clear; when two examples could be meant the proposal is a *clarification* naming the candidates — the system asks, never guesses. A removed card stays in the chain as `rejected` with `rejection.kind = "removed"` and is viewable under the history toggle. "Go back to the previous version." → `undo`, a new revision restoring the earlier state.
5. **Human-verified completion.** The reviewer opens the Review drawer, sees the five DoD checks computed from the ledger, confirms cards, accepts or rejects AI acts, resolves or explicitly accepts outstanding questions, and records a sign-off naming the reviewer, time, exact revision hash, evidence chain head and the five checks. A later substantive change emits `signoff.invalidated`; the map must be verified again.

### 1.2 Conversational intents (all eight, plus `none`)

| Intent | Example | Operation |
|---|---|---|
| add | "We also need an error case." | `card.create` |
| amend | "Change that limit to 24 hours." | `card.update` |
| remove | "We don't need that rule." | `card.remove` |
| replace | "Use this example instead." | `card.replace` |
| clarify | "By appointment, I mean a booked slot." | `definition.refine` |
| reject | "No, that's not what I said." | `interpretation.reject` |
| confirm | "Yes, that's exactly right." | `confirm` |
| undo | "Go back to the previous version." | `undo` |
| none | chatter, or words carrying an intent that cannot be applied | nothing; the classification is still ledgered with `heard_intent` |

Below a confidence threshold, or when the target is ambiguous, the proposal is a clarification request (a question to the humans with the candidate targets or a yes/no on a fully resolved operation) — never a guess.

### 1.3 Honesty rules (brief §1.11)

- An accepted-outstanding question stays unanswered; the word "answered" is never used for it.
- A fallback classifier is named as such on every proposal it produced (`fallback_from`, `error`).
- A capture lane with no audio track is an error with per-OS guidance, never a silent lane; a live lane with no sound says "no sound heard".
- Speaker identity is only the label a person assigned to a lane; `speaker: null` means nobody did. No diarisation.
- Every number shown about the session (counts, confidence) is derived from the ledger by `select.counts(state)`, never estimated; page diagnostics (dropped hallucinations, post retries) are labelled "this page" and never mixed with session numbers.
- A card's `rejected` status is rendered as its `rejection.kind` (`removed`, `interpretation rejected`, `undone`), never as the bare word.
- The Whisper device actually used (`webgpu` / `wasm`) is the one shown. Web Speech is labelled "not local".
- The reviewer's name on a sign-off is self-asserted and labelled so.

### 1.4 The six brief states, mapped

| Brief state | In this design |
|---|---|
| Proposed | a `proposal.made` event whose outcome is not yet reduced (`ProposalRecord.status` `pending` / `clarifying`); a card is `proposed` only inside that batch's `proposal.made` effect |
| Applied | card status `applied` / proposal status `applied` |
| Confirmed | card or proposal status `confirmed` |
| Rejected | card status `rejected` with `rejection.kind` ∈ `interpretation_rejected` (a person rejected the proposal), `removed`, `undone` |
| Superseded | card status `superseded` |
| Human verified | `isHumanVerified(state)` — derived, never stored |

## 2. Fixed decisions and recorded deviations

The brief's §1 decisions are binding. They are restated here only where this design pins a detail; the deviations are listed explicitly.

1. **Name and place.** `exmap/` at the repository root, self-contained (`package.json`, `.npmrc`, `.gitignore`, `README.md`, `docs/`). Never touches crb's `README.md`, `docs/`, `src/`, `tests/`, `ui/`, `scripts/`, `deploy/`, `pyproject.toml`, `.github/`.
2. **Stack.** Node 22, TypeScript 5.9.3 (ESM), Fastify 5 (+ `@fastify/websocket`, `@fastify/static`), Vite 8 + React 19 + Tailwind 4, vitest (unit), `@playwright/test` 1.56.1 (e2e, Chromium at `/opt/pw-browsers`, never `playwright install`), `@anthropic-ai/sdk` + `zod` 4, `@huggingface/transformers` (Whisper in the browser), `@noble/hashes` (browser SHA-256). No native modules. `exmap/.npmrc` carries `onnxruntime-node-install=skip`; the launcher sets `ONNXRUNTIME_NODE_INSTALL=skip` and `npm_config_onnxruntime_node_install=skip` on the `npm install` it spawns.
3. **One command.** `./exmap/start.sh`, `exmap\start.ps1`, `npm start` → `exmap/bin/exmap.mjs`: Node check, install when the lockfile changed, build when stale, serve `http://127.0.0.1:4317`, open the browser. Idempotent. **Deviation (recorded):** the Node floor is **22.12**, not the brief's bare "22", because Vite 8 declares `engines.node >= 22.12` and fails below it with an opaque error; the launcher, `package.json#engines`, the wrappers and the README all say 22.12 and the README names the reason.
4. **Local-first.** Loopback only (`127.0.0.1`), DNS-rebinding host guard, no CORS. Audio never leaves the machine except through Web Speech, which is opt-in behind a consent notice and labelled "not local". State under `~/.exmap/sessions/<id>/events.jsonl` (`EXMAP_HOME` overrides). The only network calls: the first-run Whisper model download (Hugging Face Hub, after consent), the optional Claude classifier call (server side, to the operator's configured endpoint), and Web Speech (browser vendor, only when chosen). No telemetry.
5. **Audio.** Two capture lanes in the browser, `remote` (`getDisplayMedia` with `systemAudio: "include"`, or a loopback input device) and `me` (`getUserMedia`); energy VAD (silence ≥ 600 ms closes a segment, hard cap 15 s); each utterance records lane, times, provider and the speaker label a person assigned.
6. **Transcription providers.** `local-whisper` (default; `onnx-community/whisper-base.en` q8, `whisper-tiny.en` selectable; cached after download), `web-speech` (mic lane only, not local), `manual`, `replay`. A server-side STT provider is a documented seam.
7. **Classifier.** Two providers behind one interface, both producing a proposal and never a state change: `rules.v1` (deterministic, offline, cue tables + heuristics, scores a confidence; the default and the fallback) and `claude` (`@anthropic-ai/sdk`, model `claude-opus-5-5`, `output_config: { format: zodOutputFormat(ModelProposalSchema), effort: "medium" }`, a frozen system prompt block with `cache_control: { type: "ephemeral" }`, the volatile context in the user message). Selected when `EXMAP_CLASSIFIER=claude` or when `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` is set; `EXMAP_CLASSIFIER=rules.v1` forces the offline classifier even with a key. A refusal or any API error falls back to `rules.v1` with provenance saying so. **Deviation (recorded):** the provider calls `client.messages.create(...)` with the same `output_config.format` object and runs `format.parse()` itself *after* inspecting `stop_reason`, instead of `client.messages.parse(...)`. Reason: `parse()` runs the schema on every text block before the caller can see `stop_reason`, so a refusal carrying partial text and every `max_tokens` truncation would be ledgered as `parse` — misnaming the failure (brief §1.11). The request shape, schema and effort are exactly the brief's; only the caller of `parse` differs. The operator may flip it to `messages.parse` (§6.5 states the consequence). **Ruling (recorded):** `CLAUDE_MODEL = "claude-opus-5-5"` lives in `src/classifier/constants.ts`; brief §1.12's "never put a model name in committed files" governs the authoring session's own model and session ids, not the product's fixed classifier model, which brief §1.7 pins.
8. **State engine.** Event-sourced, deterministic, hash-chained (`prev_hash` `""` at genesis, `hash` = SHA-256 of canonical JSON of the body including `prev_hash`). The map state is a pure reduction. Undo creates a new revision; nothing is deleted. The requirement revision is the SHA-256 of the canonical map state. Sign-off records reviewer, timestamp, revision, evidence head and the five checks; `signoff.invalidated` is emitted on the next substantive change.
9. **Cards.** `story` (one live), `rule`, `example` (→ rule), `question` (→ card). Status `proposed | applied | confirmed | rejected | superseded`, version history, provenance. The board shows live cards with a history toggle.
10. **Factory export.** Refused with `422 NOT_HUMAN_VERIFIED` (+ the failing DoD checks) unless `isHumanVerified(state)`, except `?draft=true` (files watermarked `DRAFT / NOT VERIFIED`). Files: `crb-backlog-item.json`, `ticket.json`, `ticket.md`, `requirement.feature`, `evidence.json`. The export UI offers crb's capability classes and slot questions from the vendored catalogue so acceptance-criteria lines can be written as `slot: text` facts.
11. **Honesty rules** as §1.3.
12. **Repository conventions.** Conventional Commits with scope `exmap`; no model name or session id in committed files except `claude-opus-5-5` in `constants.ts` and the README; credentials written as `ANTHROPIC_API_KEY=<your key>`.
13. **Design-level decisions taken here** (details in §18): export options are a ledger event (`export.options_set`), not a side file; `heard_intent` is a field on `utterance.classified`; a spoken "Yes." after a removal / undo / rejection reviews that act; the shipped fixture is `src/web/public/replay/conversation.v1.json`, listed as `demo`; the utterance POST answers `201` before classification and the browser sink's timeout is 15 s; the device actually used by Whisper is probed explicitly rather than left to `device: "auto"`'s silent fallback (brief §6 named `auto`; §1.11 requires naming the device used).

## 3. Repository layout

```
exmap/
  package.json  package-lock.json  .npmrc  .gitignore  README.md
  start.sh  start.ps1
  bin/exmap.mjs                     the launcher (plain ESM JavaScript; runs before npm install)
  scripts/build.mjs  scripts/dev.mjs  scripts/clean.mjs  scripts/install-stamp.mjs  scripts/whisper-check.mjs (manual)
  tsconfig.base.json  tsconfig.server.json  tsconfig.web.json  tsconfig.test.json  tsconfig.json
  vite.config.ts  vitest.config.ts  playwright.config.ts
  docs/DESIGN.md  docs/FIXTURE-CONVERSATION.json  docs/TEST-PLAN.md
  src/
    core/        pure engine (§5); compiled into both bundles
      index.ts types.ts refusals.ts canonical.ts chain.ts revision.ts effects.ts reduce.ts replay.ts apply.ts dod.ts select.ts
    classifier/  server only (§6)
      index.ts types.ts schema.ts constants.ts normalize.ts cues.ts extract.ts referents.ts clarification.ts rules-v1.ts
      claude/client.ts claude/system-prompt.ts claude/user-message.ts claude/validate.ts claude/claude-provider.ts
    export/      server only (§12): index.ts types.ts catalogue.ts text.ts backlog-item.ts ticket.ts feature.ts evidence.ts crb-catalogue.json
    server/      §8–§9: main.ts app.ts config.ts home.ts ledger.ts mutex.ts ids.ts hash.ts session.ts session-store.ts
                 classifier-bridge.ts errors.ts static.ts routes/{meta,sessions,utterances,acts,export,stream}.ts
    web/         §10 (Vite root; index.html here)
      main.tsx App.tsx styles.css hash.ts api/client.ts store/{sessionStore,useSession}.ts replay/driver.ts keyboard/rovingFocus.ts
      components/…   (§10.1)
      audio/         §7 (lanes/ dsp/ providers/ pipeline/ react/ …)
      public/pcm-worklet.js
      public/replay/index.json  public/replay/conversation.v1.json
  tests/
    unit/core/  unit/classifier/  unit/audio/  unit/server/  unit/export/  unit/web/  unit/web/audio/  unit/launcher/
    e2e/        fixtures.ts  journey.spec.ts  replay.spec.ts  audio.spec.ts  axe.spec.ts  launcher.spec.ts
    fixtures/   audio/mlk16k.f32  audio/mlk16k.wav  sessions/ (prebuilt ledgers: valid, tampered, truncated)
  dist/        build output (gitignored): dist/web/ (Vite), dist/server/ (tsc, rootDir src), dist/.exmap-build-stamp
```

Import rules: `src/core` imports nothing; `src/classifier` imports only types from `src/core`; `src/export` imports `src/core`; `src/server` imports all three; `src/web` imports `src/core` (runtime: `reduce`, `select`, `dodReport`, `canonicalJson`, `eventHash`) and types from the others; `src/web/audio` imports only types from `src/core`. Tests may import anything. All imports inside `src/` use explicit `.js` extensions (NodeNext on the server, bundler resolution on the web).

### 3.1 `package.json`

```json
{
  "name": "exmap", "version": "0.1.0", "private": true, "type": "module",
  "description": "Example Map Live - a local-first, voice-driven requirements modeller with human verification",
  "engines": { "node": ">=22.12.0" },
  "scripts": {
    "start": "node bin/exmap.mjs",
    "postinstall": "node scripts/install-stamp.mjs",
    "dev": "node scripts/dev.mjs",
    "dev:server": "node scripts/dev.mjs --server-only",
    "dev:web": "vite",
    "build": "node scripts/build.mjs",
    "build:web": "vite build",
    "build:server": "tsc -p tsconfig.server.json",
    "typecheck": "tsc -p tsconfig.server.json --noEmit && tsc -p tsconfig.web.json --noEmit && tsc -p tsconfig.test.json --noEmit",
    "test": "vitest run",
    "test:watch": "vitest",
    "check": "npm run typecheck && npm run test && npm run build",
    "e2e": "npm run build && playwright test",
    "clean": "node scripts/clean.mjs"
  },
  "dependencies": {
    "@anthropic-ai/sdk": "0.135.0", "zod": "4.6.7",
    "fastify": "5.12.7", "@fastify/websocket": "11.3.4", "@fastify/static": "10.1.6",
    "@huggingface/transformers": "4.3.1",
    "onnxruntime-web": "<exactly the version @huggingface/transformers 4.3.1 resolves; 1.31.0-dev.20260914-8d85527a0 in the scratch install>",
    "@noble/hashes": "2.4.0",
    "react": "19.3.1", "react-dom": "19.3.1"
  },
  "devDependencies": {
    "typescript": "5.9.3", "tsx": "4.23.15",
    "vite": "8.3.4", "@vitejs/plugin-react": "6.1.2", "tailwindcss": "4.3.3", "@tailwindcss/vite": "4.3.3",
    "vitest": "5.0.5", "jsdom": "30.1.3",
    "@testing-library/react": "16.3.3", "@testing-library/dom": "10.4.2", "@testing-library/user-event": "14.6.8", "@testing-library/jest-dom": "7.0.1",
    "@playwright/test": "1.56.1", "@axe-core/playwright": "4.14.0",
    "ws": "8.22.0",
    "@types/node": "24.12.2", "@types/react": "19.3.0", "@types/react-dom": "19.3.0", "@types/ws": "<npm view @types/ws version at implementation>"
  }
}
```

Notes: runtime deps include `@huggingface/transformers` and `react*` because the web bundle is built on the user's machine by the launcher; the launcher never sets `NODE_ENV=production` or `--omit=dev`. `onnxruntime-web` is a direct dependency pinned to the version transformers resolves (one copy; `npm ls onnxruntime-web` deduped) so the served runtime is the one the worker bundles against. `@noble/hashes` 2.4.0 is imported as `@noble/hashes/sha2.js` and `@noble/hashes/utils.js` (its `exports` map lists only the `.js` subpaths). `ws` is listed because the WebSocket unit tests use it as a client. **Implementation step zero:** `npm install` the full set in `exmap/` and commit the lockfile before any source is written; a peer conflict is fixed by re-pinning, never by `--legacy-peer-deps`.

`.npmrc`: `onnxruntime-node-install=skip`, `audit=false`, `fund=false`. `.gitignore`: `node_modules/`, `dist/`, `test-results/`, `playwright-report/`, `coverage/`, `.vite/`, `*.log`, `.DS_Store`, `*.tsbuildinfo`.

### 3.2 tsconfig and build

- `tsconfig.base.json`: `strict`, `target: "ES2023"`, `lib: ["ES2023"]`, `verbatimModuleSyntax`, `isolatedModules`, `skipLibCheck`, `exactOptionalPropertyTypes: false`, `noUncheckedIndexedAccess: true`, `resolveJsonModule`, `forceConsistentCasingInFileNames`.
- `tsconfig.server.json`: `module`/`moduleResolution` `NodeNext`, `types: ["node"]`, `rootDir: "src"`, `outDir: "dist/server"`, `sourceMap`; `include: ["src/server", "src/core", "src/classifier", "src/export"]`, `exclude: ["**/*.test.ts"]`. JSON via `import catalogue from "./crb-catalogue.json" with { type: "json" }`; tsc copies it into `dist/server/export/`.
- `tsconfig.web.json`: `module: "ESNext"`, `moduleResolution: "bundler"`, `jsx: "react-jsx"`, `lib: ["ES2023", "DOM", "DOM.Iterable", "WebWorker"]`, `types: ["vite/client"]`, `noEmit`; `include: ["src/web", "src/core"]`.
- `tsconfig.test.json`: as web plus `types: ["node", "vitest/globals", "@testing-library/jest-dom"]`; `include: ["tests", "src", "vitest.config.ts", "playwright.config.ts", "vite.config.ts"]`.
- `tsconfig.json`: project references only (editor support).

`scripts/build.mjs` (sequential, 4 CPUs): (1) `node <vite/bin/vite.js> build` — resolved as `join(dirname(require.resolve("vite/package.json")), "bin/vite.js")` because vite 8's `exports` has no `./bin/*`; (2) `node <typescript/bin/tsc> -p tsconfig.server.json`; (3) delete `dist/web/assets/ort-wasm-*.wasm` (never requested; `wasmPaths` always points at `/ort/`); (4) write `dist/.exmap-build-stamp` `{ lock_sha256, newest_source_mtime_ms, built_at, node }`. Any step failing → exit 1 naming the step. `scripts/install-stamp.mjs` writes `node_modules/.exmap-install-stamp` = hex `sha256(package-lock.json)`; it is the `postinstall` script.

`scripts/dev.mjs`: `tsx watch src/server/main.ts` with `EXMAP_DEV=1` (serves no `webDist` — `GET /` answers 503 pointing at Vite — but still serves `/ort/*`) plus `vite` on `http://127.0.0.1:5173` proxying `/api` (`ws: true`) and `/ort` to `:4317`, both with `changeOrigin: true` (vite's http-proxy rewrites `Host` only then; the server also accepts `:5173` hosts under `EXMAP_DEV=1`). `--server-only` skips Vite.

`vite.config.ts`: `root: "src/web"`, `publicDir: "public"`, `base: "/"`, plugins `react()`, `tailwindcss()`; `build: { outDir: "../../dist/web", emptyOutDir: true, sourcemap: false, target: "es2022" }`; `worker: { format: "es" }`; `optimizeDeps: { exclude: ["@huggingface/transformers"] }`; dev server `host: "127.0.0.1"`, `port: 5173`, `strictPort`, COOP/COEP headers, the two proxies above.

## 4. The shared type model — `exmap/src/core/types.ts`

This file is types only (no runtime code, no imports). Every package imports from it; nothing redeclares a name defined here. Sections 1–10 are the engine; 11 is what a classifier sees and returns; 12 the export shapes; 13 the server↔browser wire shapes.

```ts
// exmap/src/core/types.ts

/* ───────────── 1. Scalars and ids ───────────── */
export type CardId = string;          // "card_…"  minted by apply()
export type ProposalId = string;      // "prop_…"  minted by the server when it turns a classifier/UI act into a proposal.propose
                                      //           command, or by apply() for an engine-built clarification resolver; apply() refuses duplicates
export type ClarificationId = string; // "clar_…"  minted by apply()
export type UtteranceId = string;     // "utt_…"   minted by the capturing client ("utt_" + crypto.randomUUID()); the server mints
                                      //           one ("utt_" + 12 hex) for an utterance it originates (a typed clarification answer)
export type EventId = string;         // "evt_…"   minted by apply()
export type SignoffId = string;       // "sig_…"   minted by apply()
export type IsoTimestamp = string;    // ctx.now(), e.g. "2026-10-16T12:00:00.000Z"
export type Sha256Hex = string;       // 64 lowercase hex chars
export type Sha256Fn = (utf8: string) => Sha256Hex;

/** Omit that distributes over a union. TS's built-in Omit on a union keeps only the common keys. */
export type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;

export type CardKind = "story" | "rule" | "example" | "question";
export type CardStatus = "proposed" | "applied" | "confirmed" | "rejected" | "superseded";
export type Intent = "add" | "amend" | "remove" | "replace" | "clarify" | "reject" | "confirm" | "undo";
/** What the words carried when nothing could be proposed; set only on a classification whose intent is "none". */
export type HeardIntent = Intent | null;

/* ───────────── 2. Cards ───────────── */
export interface Definition { term: string; definition: string }   // terms trimmed, unique, sorted by term

export interface NeedsReview {                 // examples only
  reason: "rule_changed" | "rule_removed" | "rule_replaced";
  rule_id: CardId;                             // the rule as it is now (the replacement's id after a replace)
  event_id: EventId;                           // the event that set the flag
}
export interface Rejection {                   // non-null iff status === "rejected"
  kind: "removed" | "interpretation_rejected" | "undone";
  proposal_id: ProposalId;                     // the remove / reject / undo proposal
  event_id: EventId;
}
export interface ConfirmedBy {                 // copied from the confirm proposal's ClassifierStamp
  provider: ClassifierProvider;                // "human" = a click; "rules.v1" / "claude" = a voice "yes" interpreted by that classifier
  actor: string | null;                        // the person (click) or the speaker label (voice; never inferred)
  confidence: number;                          // 1 for a click; the classifier's figure for a voice confirm
}
export interface Confirmation {                // non-null iff status === "confirmed"
  proposal_id: ProposalId; event_id: EventId;  // the confirm act
  version: number;                             // the card version the person looked at (never rewritten)
  by: ConfirmedBy;
}
export interface Provenance {
  proposal_id: ProposalId; event_id: EventId;
  utterance_ids: UtteranceId[];                // copied from the proposal
  classifier: ClassifierProvider;
}
export interface AcceptedOutstanding { by: string; reason: string; event_id: EventId }

export interface CardCommon {
  id: CardId;
  text: string;                                // trimmed, CRLF→LF, non-empty
  definitions: Definition[];
  status: CardStatus;
  version: number;                             // 1 at creation; +1 on every content change (§5.2)
  history: CardVersion[];                      // earlier versions, oldest first; derived by reduce, never in events
  supersedes: CardId | null;
  superseded_by: CardId | null;
  rejection: Rejection | null;
  confirmation: Confirmation | null;
  created: Provenance;
  changed: Provenance;                         // who authored the current content (text / definitions / links / answer)
  restored_by: Provenance | null;              // the reject/undo that brought this content back; null unless the current
                                               // version is a restore; cleared by the next content change
}
export interface StoryCard    extends CardCommon { kind: "story" }
export interface RuleCard     extends CardCommon { kind: "rule" }
export interface ExampleCard  extends CardCommon { kind: "example";  rule_id: CardId | null; needs_review: NeedsReview | null }
export interface QuestionCard extends CardCommon { kind: "question"; about_card_id: CardId | null;
                                                   answer: string | null;                      // content: the recorded answer
                                                   accepted_outstanding: AcceptedOutstanding | null } // review decision
export type Card = StoryCard | RuleCard | ExampleCard | QuestionCard;

/** A card as carried in an event effect or a revision snapshot: everything except `history`. */
export type CardRecord = DistributiveOmit<Card, "history">;
export interface CardVersion { version: number; record: CardRecord; replaced_by_event_id: EventId }

/* ───────────── 3. Utterance ───────────── */
export type Lane = "remote" | "me" | "manual";
export type TranscriptionProvider = "local-whisper" | "web-speech" | "manual" | "replay";
export interface Utterance {
  id: UtteranceId;
  text: string;                 // trimmed, non-empty
  lane: Lane;
  speaker: string | null;       // the label a person assigned to the lane; never inferred
  provider: TranscriptionProvider;
  model: string | null;         // the Whisper model id; null for manual / web-speech / replay
  t_start_ms: number;           // integer ms from session start (the session's created_at)
  t_end_ms: number;             // >= t_start_ms
  is_local: boolean;            // false only for web-speech in v1
  confidence: number | null;    // the transcriber's own figure in [0,1], <= 2 dp, or null when it gives none
}

/* ───────────── 4. Classifier stamp, proposal, operations ───────────── */
export type ClassifierProvider = "rules.v1" | "claude" | "human";
export interface ClassifierStamp {
  provider: ClassifierProvider;
  model: string | null;           // served model id for "claude"; null otherwise
  prompt_version: string | null;  // SYSTEM_PROMPT_VERSION for "claude"; null otherwise
  fallback_from: "claude" | null; // rules.v1 answered because claude refused/errored
  error: string | null;           // the failure code (§6.5) when fallback_from is set; null otherwise
  actor: string | null;           // the person behind this proposal: the UI user for "human"; for a proposal that resolves a
                                  // clarification, the person who answered (UI user, or the speaker label of the voice answer);
                                  // null for a pure AI interpretation
}
/** What a classifier provider stamps: ClassifierStamp without the human provider and without actor. */
export type ClassifierProvenance = Omit<ClassifierStamp, "provider" | "actor"> & { provider: "rules.v1" | "claude" };

export interface Candidate { card_id: CardId; label: string; score: number | null }   // null = unranked (shown in asking order)

export interface Proposal {
  id: ProposalId;
  intent: Intent;
  operation: Operation | null;           // null <=> needs_clarification
  template: OperationTemplate | null;    // needs_clarification only: the operation minus its target ("which one?")
  pending_operation: Operation | null;   // needs_clarification only: a fully resolved operation awaiting a yes/no ("did you mean…?")
  candidates: Candidate[];               // needs_clarification with a template only; may be []
  confidence: number;                    // 0..1, <= 2 decimals (INVALID_CONFIDENCE otherwise; apply() never rounds)
  needs_clarification: boolean;
  question: string | null;               // the text asked of the humans; required when needs_clarification
  source_utterance_ids: UtteranceId[];   // [] for provider "human"
  classifier: ClassifierStamp;
  resolves_clarification_id: ClarificationId | null;
  rationale: string;                     // the classifier's one-line reason; "" allowed
}

export type NewCard =
  | { kind: "story";    text: string; definitions?: Definition[] }
  | { kind: "rule";     text: string; definitions?: Definition[] }
  | { kind: "example";  text: string; rule_id: CardId | null; definitions?: Definition[] }
  | { kind: "question"; text: string; about_card_id: CardId | null; definitions?: Definition[] };

export interface CardPatch {             // every field optional; at least one must change something
  text?: string;
  definitions?: Definition[];
  rule_id?: CardId | null;               // example only
  about_card_id?: CardId | null;         // question only
  answer?: string | null;                // question only (null re-opens)
}

/** A target-independent amendment; resolveTemplate() turns it into patch.text for the chosen card (§5.5). `to` may be "" when `from` is null. */
export interface Amendment { from: string | null; to: string; scope: string | null; append: string }

export type Operation =
  | { kind: "card.create";           card: NewCard }
  | { kind: "card.update";           card_id: CardId; patch: CardPatch }
  | { kind: "card.remove";           card_id: CardId }
  | { kind: "card.replace";          card_id: CardId; replacement: { text: string; definitions?: Definition[] } }
  | { kind: "card.replace";          card_id: CardId; replacement_card_id: CardId }     // an existing live card of the same kind
  | { kind: "definition.refine";     card_id: CardId; term: string; definition: string }
  | { kind: "interpretation.reject"; proposal_id: ProposalId }
  | { kind: "confirm";               card_ids: CardId[]; proposal_ids: ProposalId[] }  // at least one non-empty
  | { kind: "undo";                  to_revision_seq: number | null };                // null = one step back (§5.9)
export type OperationKind = Operation["kind"];

/** An operation whose target is still unknown; a clarification answer of kind "candidate" fills it. */
export type OperationTemplate =
  | { kind: "card.create"; card: NewCard & { kind: "example" | "question" } }   // the answer fills rule_id / about_card_id
  | { kind: "card.update"; patch: CardPatch; amendment: Amendment | null }      // amendment => patch.text is recomputed per card
  | { kind: "card.remove" }
  | { kind: "card.replace"; replacement: { text: string; definitions?: Definition[] } }
  | { kind: "card.replace"; replacement_card_id: CardId }                       // the answer names the card being replaced
  | { kind: "definition.refine"; term: string; definition: string }
  | { kind: "confirm" }                                                         // the answer names a card -> card_ids: [it]
  | { kind: "interpretation.reject" };                                          // the answer names a card; its changed.proposal_id is the target

/* ───────────── 5. Clarification ───────────── */
export type ClarificationAnswer =
  | { kind: "candidate"; card_id: CardId }                               // fills the template's target
  | { kind: "yes" }                                                      // applies pending_operation
  | { kind: "text"; text: string; utterance_id: UtteranceId | null }     // free text -> the server re-runs the classifier
  | { kind: "dismiss"; reason: string };

export interface TextAnswer { text: string; utterance_id: UtteranceId | null; actor: string; event_id: EventId }

export interface Clarification {
  id: ClarificationId;
  proposal_id: ProposalId;               // the proposal that asked
  question: string;
  candidates: Candidate[];
  template: OperationTemplate | null;
  pending_operation: Operation | null;
  status: "open" | "answered" | "dismissed";
  asked_event_id: EventId;
  text_answers: TextAnswer[];            // every text answer so far, oldest first; they do not close the clarification
  answer: ClarificationAnswer | null;    // the answer that resolved or dismissed it
  answered_event_id: EventId | null;
  resolved_by_proposal_id: ProposalId | null;   // non-null <=> status === "answered"
}

/* ───────────── 6. Export options (a person's export-time annotations; in the chain, outside the sign-off) ───────────── */
export type BacklogKind = "code" | "infra" | "operator";
export type SizeEstimate = "XS" | "S" | "M" | "L" | "XL" | "unsized";
export interface ExportFact { slot: string; text: string }       // slot /^[A-Za-z][A-Za-z0-9_]*$/, text non-empty
export interface ExportOptionsInput { capability_class: string; kind: BacklogKind; size_estimate: SizeEstimate; facts: ExportFact[]; by: string }
export interface ExportOptions extends ExportOptionsInput { seq: number; at: IsoTimestamp }   // seq 1.. per session; the current value is the last

/* ───────────── 7. Events ───────────── */
export interface RevisionStamp { seq: number; hash: Sha256Hex }
export interface CardEffect { card_id: CardId; before: CardRecord | null; after: CardRecord }
export interface RefusedOperation { operation: OperationKind | "unknown"; reason: string; detail: string }
export interface ClassifierErrorInfo { code: string; message: string }

export interface EventBase {
  id: EventId;
  seq: number;                 // 1-based position in the ledger
  at: IsoTimestamp;            // hashed (audit time); excluded from the revision
  session_id: string;          // the same in every event of a ledger
  batch_id: EventId;           // id of the first event of the apply() batch that appended this one (== id for that event)
  prev_hash: Sha256Hex | "";   // "" at genesis
  hash: Sha256Hex;             // sha256(canonicalJson(event without `hash`))
}
export type EventPayload =
  | { type: "utterance.recorded";  utterance: Utterance }
  | { type: "utterance.classified"; utterance_id: UtteranceId; intent: Intent | "none"; heard_intent: HeardIntent; classifier: ClassifierStamp;
                                    confidence: number; rationale: string; proposal_ids: ProposalId[]; refused: RefusedOperation[];
                                    error: ClassifierErrorInfo | null }
  | { type: "proposal.made";       proposal: Proposal; effects: CardEffect[] }          // card.create => one proposed card; else []
  | { type: "proposal.applied";    proposal_id: ProposalId; operation: Operation; effects: CardEffect[]; revision: RevisionStamp }
  | { type: "proposal.rejected";   proposal_id: ProposalId; rejected_proposal_id: ProposalId; effects: CardEffect[]; revision: RevisionStamp }
  | { type: "proposal.confirmed";  proposal_id: ProposalId; card_ids: CardId[]; proposal_ids: ProposalId[]; confirms_proposal_ids: ProposalId[]; effects: CardEffect[] }
  | { type: "undo.applied";        proposal_id: ProposalId; from_revision: RevisionStamp; to_revision: RevisionStamp; effects: CardEffect[]; revision: RevisionStamp }
  | { type: "clarification.asked"; clarification_id: ClarificationId; proposal_id: ProposalId; question: string; candidates: Candidate[];
                                   template: OperationTemplate | null; pending_operation: Operation | null }
  | { type: "clarification.answered"; clarification_id: ClarificationId; answer: ClarificationAnswer; actor: string; resolved_by_proposal_id: ProposalId | null }
  | { type: "question.accepted_outstanding"; question_id: CardId; by: string; reason: string; effects: CardEffect[] }
  | { type: "signoff.recorded";    signoff: SignoffRecord }
  | { type: "signoff.invalidated"; signoff_id: SignoffId; by_event_id: EventId; from_revision: RevisionStamp; to_revision: RevisionStamp }
  | { type: "export.options_set";  options: ExportOptions };
export type ExmapEvent = EventBase & EventPayload;                       // 13 event types
export type EventType = ExmapEvent["type"];
export type EventBody = DistributiveOmit<ExmapEvent, "hash">;           // distributive: every payload keeps its own fields

/* ───────────── 8. State ───────────── */
export type ProposalStatus = "pending" | "applied" | "confirmed" | "rejected" | "clarifying" | "answered" | "dismissed";
export interface ProposalRecord {
  proposal: Proposal;
  status: ProposalStatus;
  made_event_id: EventId;
  outcome_event_id: EventId | null;       // applied / rejected / confirmed / undo / clarification.asked event
  effects: CardEffect[];                  // of the outcome event (what interpretation.reject inverts)
  affected_card_ids: CardId[];            // primary targets: created / updated / removed / replaced (old + replacement) / confirmed / reverted ids
}
export interface ClassificationRecord {
  utterance_id: UtteranceId; event_id: EventId;
  intent: Intent | "none"; heard_intent: HeardIntent; classifier: ClassifierStamp; confidence: number; rationale: string;
  proposal_ids: ProposalId[]; refused: RefusedOperation[]; error: ClassifierErrorInfo | null;
}
export type RevisionCause = "genesis" | "proposal.applied" | "proposal.rejected" | "undo.applied";
export interface Revision {
  seq: number; hash: Sha256Hex; event_id: EventId | null; at: IsoTimestamp | null; cause: RevisionCause;
  batch_id: EventId | null;               // null for genesis; revisions with equal batch_id are one step (§5.9)
  source_utterance_ids: UtteranceId[];    // of the proposal that created it; [] for human acts and genesis
  snapshot: Record<CardId, CardRecord>;   // every card (all statuses) as of this revision; in-memory only (never serialised)
}
export interface SignoffRecord {
  id: SignoffId;
  reviewer: { name: string };
  confirmation_text: string;              // === SIGNOFF_CONFIRMATION_TEXT
  revision: RevisionStamp;                // the exact requirement revision
  evidence: { head_seq: number; head_hash: Sha256Hex };  // chain head immediately before this event
  checks: DodReport;                      // computed by the engine (§5.7)
}
export interface Signoff extends SignoffRecord {
  event_id: EventId; at: IsoTimestamp;
  status: "active" | "invalidated";
  invalidated: { event_id: EventId; by_event_id: EventId; to_revision: RevisionStamp } | null;
}
export interface MapState {
  schema: "exmap.state.v1";
  session_id: string;
  head: { seq: number; hash: Sha256Hex | ""; event_id: EventId | null };
  utterances: Utterance[];
  classifications: ClassificationRecord[];   // ledger order; one utterance may have several (re-runs after a text answer)
  cards: Record<CardId, Card>;          card_order: CardId[];
  proposals: Record<ProposalId, ProposalRecord>; proposal_order: ProposalId[];
  clarifications: Record<ClarificationId, Clarification>; clarification_order: ClarificationId[];
  revisions: Revision[];                // revisions[0] is genesis; revisions.at(-1) is current
  signoffs: Signoff[];                  // oldest first; at most one is "active" and it is always the last
  export_options: ExportOptions[];      // oldest first; the current value is at(-1) ?? null
}
export interface Counts {               // select.counts(state): every number the UI shows comes from here
  utterances: number; classified: number; actionable: number; classifier_errors: number; fallbacks: number;
  cards_live: number; by_kind: Record<CardKind, number>; needs_review: number; open_questions: number; accepted_questions: number;
  open_clarifications: number; unreviewed_acts: number; revision_seq: number; events: number;
}

/* ───────────── 9. Commands, apply context, refusals ───────────── */
export type Command =
  | { kind: "utterance.record";      utterance: Utterance }
  | { kind: "proposal.propose";      proposals: Proposal[] }                  // 1..n, one batch, all or nothing
  | { kind: "classification.record"; utterance_id: UtteranceId; intent: Intent | "none"; heard_intent: HeardIntent; classifier: ClassifierStamp;
                                     confidence: number; rationale: string; proposal_ids: ProposalId[]; refused: RefusedOperation[];
                                     error: ClassifierErrorInfo | null }
  | { kind: "clarification.answer";  clarification_id: ClarificationId; answer: ClarificationAnswer; actor: string }
  | { kind: "question.accept";       question_id: CardId; by: string; reason: string }
  | { kind: "signoff.record";        reviewer: { name: string }; confirmation_text: string; cited_revision_hash: Sha256Hex }
  | { kind: "export.options_set";    options: ExportOptionsInput };

export type IdPrefix = "evt" | "card" | "prop" | "clar" | "sig" | "utt";
export interface ApplyContext {
  now: () => IsoTimestamp;
  nextId: (prefix: IdPrefix) => string;   // called only after validation passes
  sha256: Sha256Fn;
}
export type RefusalCode =
  | "BAD_SHAPE" | "DUPLICATE_ID" | "EMPTY_TEXT" | "INVALID_TIMING" | "INVALID_ENUM" | "INVALID_CONFIDENCE" | "INVALID_DEFINITION"
  | "INTENT_OPERATION_MISMATCH" | "UTTERANCE_UNKNOWN"
  | "CARD_NOT_FOUND" | "CARD_NOT_LIVE" | "KIND_MISMATCH" | "LINK_KIND_MISMATCH" | "STORY_ALREADY_EXISTS"
  | "PATCH_EMPTY" | "PATCH_FIELD_NOT_ALLOWED" | "NO_CHANGE" | "EMPTY_TARGET" | "REPLACEMENT_INVALID"
  | "NOTHING_TO_CONFIRM" | "PROPOSAL_NOT_CONFIRMABLE" | "PROPOSAL_NOT_FOUND" | "PROPOSAL_NOT_REJECTABLE" | "PROPOSAL_KIND_NOT_REJECTABLE" | "REJECT_NOT_LATEST"
  | "UNDO_NO_EARLIER_REVISION" | "UNDO_TARGET_OUT_OF_RANGE" | "UNDO_TARGET_IS_CURRENT"
  | "CLARIFICATION_QUESTION_REQUIRED" | "CLARIFICATION_SHAPE" | "CLARIFICATION_NOT_FOUND" | "CLARIFICATION_NOT_ANSWERABLE"
  | "CLARIFICATION_NOT_AWAITING_PROPOSAL" | "CLARIFICATION_NO_TEMPLATE" | "CLARIFICATION_NO_OPERATION"
  | "CLASSIFICATION_PROPOSAL_MISMATCH" | "ACTOR_REQUIRED" | "REASON_REQUIRED" | "QUESTION_ALREADY_RESOLVED"
  | "SIGNOFF_REVIEWER_REQUIRED" | "SIGNOFF_CONFIRMATION_TEXT_MISMATCH" | "SIGNOFF_STALE_REVISION" | "SIGNOFF_ALREADY_ACTIVE" | "SIGNOFF_DOD_FAILED";
export type ApplyResult =
  | { ok: true;  events: ExmapEvent[]; state: MapState }
  | { ok: false; reason: RefusalCode; detail: string; checks?: DodReport };   // checks only for SIGNOFF_DOD_FAILED

/* ───────────── 10. Chain, revision, DoD ───────────── */
export type ChainErrorCode = "PREV_HASH_MISMATCH" | "HASH_MISMATCH" | "SEQ_MISMATCH" | "SESSION_MISMATCH";
export interface ChainError { code: ChainErrorCode; seq: number; event_id: string; detail: string }
export type VerifyResult = { ok: true; count: number; head: Sha256Hex | "" } | { ok: false; error: ChainError };
export type ReplayError = ChainError | { code: "REVISION_MISMATCH"; seq: number; expected: Sha256Hex; actual: Sha256Hex } | { code: "EMPTY_LEDGER" };
export type ReplayResult = { ok: true; state: MapState } | { ok: false; error: ReplayError };

export interface CanonicalState { schema: "exmap.revision.v1"; cards: CanonicalCard[] }   // live cards, sorted by id
export type CanonicalCard =
  | { id: CardId; kind: "story";    text: string; definitions: Definition[] }
  | { id: CardId; kind: "rule";     text: string; definitions: Definition[] }
  | { id: CardId; kind: "example";  text: string; definitions: Definition[]; rule_id: CardId | null }
  | { id: CardId; kind: "question"; text: string; definitions: Definition[]; about_card_id: CardId | null; answer: string | null };

export type DodCheckId = "story_rules_confirmed" | "examples_reviewed" | "changes_resolved" | "questions_resolved" | "final_version_recorded";
export interface DodCheck { id: DodCheckId; title: string; pass: boolean; details: string[] }   // details name ids
export interface DodReport { pass: boolean; checks: DodCheck[] }   // always all five, in this order
export interface DodOptions { requireHumanConfirm: boolean }       // true: only confirmations with by.provider === "human" count in checks 1, 2, 4

/* ───────────── 11. Classifier input and output (what a classifier sees and returns) ───────────── */
export type ClassifierProviderId = "rules.v1" | "claude";
export type ClassifierIntent = Intent | "none";
/** What the classifier sees of an utterance: core's record minus timing and provider. lane "manual" = typed. */
export type ClassifierUtterance = Pick<Utterance, "id" | "text" | "lane" | "speaker">;

export interface CardIndexEntry {
  id: CardId;
  kind: CardKind;
  title: string;                     // first 60 chars of text (candidate label)
  text: string;                      // full card text
  status: CardStatus;                // the index holds proposed | applied | confirmed only
  links: { rule_id: CardId | null; about_card_id: CardId | null };
  answer: string | null;             // questions: the recorded answer; null otherwise
  seq: number;                       // ledger seq of changed.event_id
  last_utterance_id: UtteranceId | null;  // changed.utterance_ids.at(-1); null for a card made in the UI
  last_speaker: string | null;       // speaker label of that utterance; null when none was assigned
  proposal_id: ProposalId | null;    // changed.proposal_id when a non-human proposal produced the current version; null otherwise
}
export interface LastProposalRef {
  id: ProposalId;
  intent: Intent;
  op: OperationKind;                 // the operation core applied
  kind: CardKind | null;             // kind of card_ids[0] (any status); null for undo
  status: "applied" | "confirmed";
  card_ids: CardId[];                // core affected_card_ids (may include cards no longer in the index)
  utterance_id: UtteranceId;         // source_utterance_ids[0]
  rejectable: boolean;               // select.isRejectable(state, id) at input-build time
}
export interface PendingClarification {
  proposal_id: ProposalId;           // the proposal that asked
  kind: "choose_target" | "confirm_intent";
  question: string;
  candidates: Array<{ card_id: CardId; label: string }>;   // asking order; [] for confirm_intent
  pending_operations: ClassifierOperation[];   // choose_target: "$choice" where the chosen id goes; confirm_intent: exactly one complete operation
  intent: Intent;
  asked_by_utterance_id: UtteranceId;
  source_utterance_ids: UtteranceId[];
  classifier: ClassifierProvenance;  // who asked
}
export interface ClassifierInput {
  utterance: ClassifierUtterance;
  recent: ClassifierUtterance[];                // the last 12 utterances before this one, oldest first
  cards: CardIndexEntry[];                      // every card with status proposed | applied | confirmed, in card_order
  last_proposal: LastProposalRef | null;        // most recent non-human proposal with status applied | confirmed
  last_rejectable: LastProposalRef | null;      // most recent proposal with rejectable === true (may equal last_proposal)
  pending_clarification: PendingClarification | null;   // the most recent open clarification the classifier can represent (§6.6)
}
export interface Classifier {
  readonly provider: ClassifierProviderId;
  classify(input: ClassifierInput, opts?: { signal?: AbortSignal }): Promise<ClassifierProposal>;
}

/** The classifier's own operation shapes (core's names plus three classifier-side fields; the bridge maps them, §8.7). */
export interface CardDraft { kind: CardKind; text: string; rule_id: CardId | null; about_card_id: CardId | null }
export interface ClassifierCardPatch { text: string | null; text_append: string | null; answer: string | null; rule_id: CardId | null; about_card_id: CardId | null }
export interface ClassifierAmendment { from: string | null; to: string; scope: string | null }
export type ClassifierOperation =
  | { kind: "card.create";           card: CardDraft }
  | { kind: "card.update";           card_id: string; patch: ClassifierCardPatch; amendment: ClassifierAmendment | null }   // card_id may be "$choice"
  | { kind: "card.remove";           card_id: string; reason: string }
  | { kind: "card.replace";          card_id: string; replacement: { text: string } | null; replacement_card_id: CardId | null }
  | { kind: "definition.refine";     card_id: string; term: string; definition: string }
  | { kind: "interpretation.reject"; proposal_id: string }
  | { kind: "confirm";               card_ids: CardId[] }     // [] = review the last proposal's act (removal / undo / rejection)
  | { kind: "undo";                  steps: number };         // one step = one batch (one utterance or one click)
export interface ClassifierClarification {
  kind: "choose_target" | "confirm_intent";
  question: string;                                          // one sentence to the people in the meeting
  candidates: Array<{ card_id: CardId; label: string }>;     // >= 2 for choose_target; [] for confirm_intent
  pending_operations: ClassifierOperation[];                 // choose_target: "$choice" in a target field; confirm_intent: exactly one complete operation
}
export interface ClassifierResolves { proposal_id: ProposalId; chosen_card_ids: CardId[]; dismissed: boolean }
export interface ClassifierProposal {
  intent: ClassifierIntent;
  operations: ClassifierOperation[];                         // [] when needs_clarification or intent none
  target_card_ids: CardId[];                                 // every index id referenced (recomputed by the provider)
  confidence: number;                                        // 0..1, 2 dp
  needs_clarification: boolean;
  clarification: ClassifierClarification | null;             // non-null iff needs_clarification
  resolves: ClassifierResolves | null;                       // only when answering pending_clarification
  rationale: string;                                         // one sentence, <= 200 chars
  heard_intent: HeardIntent;                                 // set only on intent "none"
  classifier: ClassifierProvenance;
  source_utterance_ids: UtteranceId[];                       // [utterance.id, (+ asked_by_utterance_id when resolves is set)]
}

/* ───────────── 12. Export shapes ───────────── */
export type ExportFile = "crb-backlog-item.json" | "ticket.json" | "ticket.md" | "requirement.feature" | "evidence.json";
export interface BacklogItem {   // crb BacklogItem (brief §3)
  id: string; title: string; kind: BacklogKind; description: string; acceptance_criteria: string[]; capability_class: string;
  size_estimate: SizeEstimate; structural_facts: string[]; depends_on: string[]; level: "L1" | "L2" | "L3"; supersedes: string;
  registered: IsoTimestamp; labels: Record<string, string>;
}
export interface Ticket {        // crb intake Ticket (brief §3); body is newline-joined plain text
  key: string; title: string; body: string; acceptance_criteria: string[]; type: string; tags: string[]; points: number | null;
  links: string[]; url: string; state: string; author: string;
}
export interface Evidence {
  schema: "exmap.evidence.v1"; exported_at: IsoTimestamp; draft: boolean; verified: boolean;
  session: ExportSession;
  requirement_revision: RevisionStamp;                    // the current revision at export
  chain_head: { seq: number; hash: Sha256Hex | ""; event_id: EventId | null };
  signoff: null | (SignoffRecord & { status: "active" | "invalidated"; at: IsoTimestamp; event_id: EventId; invalidated: Signoff["invalidated"] });
  dod: DodReport;                                         // computed at export time
  canonical_state: CanonicalState;                        // sha256(canonicalJson(.)) === requirement_revision.hash
  export_options: ExportOptions | null;                   // the current value; not covered by the sign-off
  export_options_history: ExportOptions[];                // every value ever set, oldest first
  watermark: "DRAFT / NOT VERIFIED" | null;
}
export interface ExportSession { id: string; title: string; created_at: IsoTimestamp }
export interface ExportInput { session: ExportSession; state: MapState; draft: boolean; now: IsoTimestamp }
export type SignoffGateStatus = "none" | "invalidated" | "active_but_stale" | "active_but_dod_failed";
export interface ExportRefusal {
  ok: false; reason: "NOT_HUMAN_VERIFIED"; detail: string; checks: DodReport;
  signoff: { status: SignoffGateStatus; id?: SignoffId; revision?: RevisionStamp; invalidated_by_event_id?: EventId };
}
export interface ExportResult { ok: true; filename: string; content_type: string; body: string }

/* ───────────── 13. Wire shapes (server <-> browser; the UI never invents its own) ───────────── */
export interface SessionMeta { schema: "exmap.session-meta.v1"; id: string; title: string; created_at: IsoTimestamp }
export interface BrokenInfo { code: string; row: number; seq: number | null; detail: string }
export interface SessionSummary {
  id: string; title: string; created_at: IsoTimestamp;
  head: { seq: number; hash: Sha256Hex | "" };
  revision: RevisionStamp;
  counts: Counts;
  human_verified: boolean;
  broken: BrokenInfo | null;          // set => the session cannot be opened; the summary is computed from the readable prefix
}
export interface ErrorBody { ok: false; reason: string; detail: string; issues?: unknown[]; checks?: DodReport;
                             event?: { id: EventId; seq: number; hash: Sha256Hex };            // DUPLICATE_ID on the utterance route
                             signoff?: ExportRefusal["signoff"] }                               // NOT_HUMAN_VERIFIED
export interface ActResponse { ok: true; events: ExmapEvent[]; proposal_id?: ProposalId }
export interface ClassificationSummary {
  event: { id: EventId; seq: number };                    // the utterance.classified event
  intent: Intent | "none"; heard_intent: HeardIntent; classifier: ClassifierStamp; confidence: number; rationale: string;
  proposals: Array<{ proposal_id: ProposalId; status: ProposalStatus; clarification_id: ClarificationId | null;
                     events: Array<{ id: EventId; seq: number; type: EventType }> }>;
  refused: RefusedOperation[]; error: ClassifierErrorInfo | null;
}
export interface UtterancePostResponse { ok: true; event: { id: EventId; seq: number; hash: Sha256Hex }; classification?: ClassificationSummary }
export interface ClassifierConfig {
  provider: ClassifierProviderId; reason: string; model: string | null;
  credentials: "api_key" | "auth_token" | "none" | "profile_or_none";
  last_error: { code: string; message: string; at: IsoTimestamp } | null;
}
export interface ConfigResponse { app: "exmap"; version: string; port: number; home: string; loopback: true; coop: boolean; classifier: ClassifierConfig }
export type StreamMessage =
  | { type: "hello"; session_id: string; head: { seq: number; hash: Sha256Hex | "" }; after: number }
  | { type: "event"; event: ExmapEvent }
  | { type: "error"; reason: "SESSION_NOT_FOUND" | "LEDGER_BROKEN" | "FORBIDDEN_ORIGIN"; detail: string; row?: number };
```

Compile-time guards (`tests/unit/core/types.test-d.ts`): `EventBody` keeps every payload's own fields; `CardRecord` of an example keeps `rule_id`; `z.infer<typeof ProposalSchema>` (classifier package) is mutually assignable with `ClassifierProposal`; `REFUSAL` (`refusals.ts`) is `{ readonly [K in RefusalCode]: K }`.

## 5. Core engine semantics (`exmap/src/core/`)

Pure TypeScript: no I/O, no Node or browser APIs. SHA-256 is injected (`Sha256Fn`); the server adapter (`src/server/hash.ts`, `node:crypto`) and the browser adapter (`src/web/hash.ts`, `@noble/hashes/sha2.js`) are both pinned to the same vectors: `sha256("") = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`, `sha256("abc") = ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad`.

Module rules: `apply.ts` imports everything; nothing imports `apply.ts` except `index.ts` and tests. `reduce.ts` imports no hashing; `replay.ts` is the only module composing `chain.ts`, `revision.ts` and `reduce.ts`.

### 5.0 Decisions at a glance

1. **Everything enters through `apply()`**: it shape-checks the command (types, enums, no unknown keys → `BAD_SHAPE` naming the path), validates completely, then mints ids, emits an atomic batch of chained events and returns the reduced state. A refusal emits nothing and calls `nextId` zero times.
2. **Events carry explicit `effects`** (`{card_id, before, after}`). The reducer sets `after` and bookkeeps history; all judgement lives in `apply()`. Reject = invert one proposal's effects; undo = diff to an earlier snapshot.
3. **Proposals auto-apply** when valid and not needing clarification: `proposal.made` + `proposal.applied` in one batch. Human acts are proposals with `classifier.provider = "human"`. **One utterance = one batch**: `proposal.propose { proposals }` is validated together, applied in order, all or nothing; every event carries the batch's `batch_id`, which is what "one step" means for undo.
4. **Card ids are stable**; `card.update` bumps `version` and keeps prior versions in `history`. `card.replace` supersedes with new text (new id) or with an existing card (`replacement_card_id`) so "use this example instead" never copies a card. `card.remove` → `rejected` with `rejection.kind = "removed"`.
5. **Revision = sha256(canonical meaning)**: live cards' id, kind, text, definitions, links and a question's `answer`. Excluded: status, confirmations, `needs_review`, `accepted_outstanding`, versions, provenance, timestamps, non-live cards, utterances, classifications, export options.
6. **Substantive change ⇔ the revision hash changes ⇔ a `Revision` is pushed ⇔ an active sign-off is invalidated.** One definition, mechanically checked.
7. **Confirmation is per card, and per act for acts that leave no card** (`confirm { card_ids, proposal_ids }`). Every confirmation records who confirmed and through which classifier (`Confirmation.by`), so a voice "yes" and a click are distinguishable.
8. **Undo restores an earlier revision's cards verbatim** (content and status, including earlier confirmations) as new card versions; cards created after the target become `rejected/undone`. The new revision's hash equals the target's.
9. **Sign-off** needs the reviewer name, the exact confirmation sentence, the revision hash the reviewer looked at, and a passing DoD report that the engine computes. `human_verified` is derived.
10. **Questions**: `answer` (content; canonical) is separate from `accepted_outstanding` (a review decision; not canonical).
11. **Every classification is ledgered** (`utterance.classified`), including `none`, fallbacks and errors, with `heard_intent`.
12. **Export options are ledgered** (`export.options_set`), non-substantive, outside the canonical state; the current value is the last.

### 5.1 Canonical JSON (`canonical.ts`) and the chain (`chain.ts`)

`canonicalJson(value)`: objects' keys sorted by UTF-16 code-unit order, recursively; `undefined` properties omitted; arrays keep order; strings escaped as `JSON.stringify`; numbers must be finite (`CanonicalError` on `NaN`/`±Infinity`); functions/symbols/bigint throw `CanonicalError`; no whitespace. Equivalent to `JSON.stringify(sortKeysDeep(value))`. The non-integers that can appear in a hashed body (`Proposal.confidence`, `Candidate.score`, `Utterance.confidence`, `ConfirmedBy.confidence`, classification `confidence`) are refused unless they have ≤ 2 decimal places, so a port to another language has a bounded formatting problem (documented, not solved).

```ts
export const GENESIS_PREV_HASH = "";
export function eventHash(body: EventBody, sha256: Sha256Fn): Sha256Hex        // sha256(canonicalJson(body)); body includes prev_hash, seq, at, session_id, batch_id
export function chainEvent(prev: { seq: number; hash: Sha256Hex | "" }, body: DistributiveOmit<EventBody, "prev_hash" | "seq">, sha256: Sha256Fn): ExmapEvent
export function verifyChain(events: readonly ExmapEvent[], sha256: Sha256Fn): VerifyResult
```
`verifyChain` walks from `prev = ""`, `seq = 0`: `event.seq === seq + 1` (`SEQ_MISMATCH`), `event.prev_hash === prev` (`PREV_HASH_MISMATCH`), `event.session_id === events[0].session_id` (`SESSION_MISMATCH`), `eventHash(event sans hash) === event.hash` (`HASH_MISMATCH`); the first failure is returned with its `seq` and `event_id`. It never repairs. An empty list is `{ ok: true, count: 0, head: "" }`.

### 5.2 Revision (`revision.ts`)

`canonicalState(cards)` = `{ schema: "exmap.revision.v1", cards: <live cards sorted by id as CanonicalCard> }`; `computeRevision(cards, sha256)` = `sha256(canonicalJson(canonicalState(cards)))`; `GENESIS_REVISION_HASH = "8e97e07bb7573b0849c4f8894c845ce76472f2c9f0eda7a7db37004bc269f675"` (= `sha256('{"cards":[],"schema":"exmap.revision.v1"}')`). **Live** = `status ∈ {applied, confirmed}`.

**Content vs review state.** *Content* = `text`, `definitions`, `rule_id`, `about_card_id`, `answer`. A content change bumps `version`, pushes the old record to `history`, sets `changed` to the changing proposal, `restored_by: null`, `status = "applied"` and clears `confirmation` — unless it is a *restore* (reject or undo), which restores the earlier record verbatim (content, status, confirmation, `needs_review`, `accepted_outstanding`, and `changed`), bumps `version` only when content differs, and sets `restored_by` to the restoring act. *Review state* = `status`, `confirmation`, `needs_review`, `accepted_outstanding`; changing it never bumps `version`. *Link state* = `supersedes`, `superseded_by`; set once, no version bump. A content change on a question clears `accepted_outstanding`.

Invariants asserted after every apply: `rejection !== null ⇔ status === "rejected"`; `confirmation !== null ⇔ status === "confirmed"`; `superseded_by !== null ⇔ status === "superseded"`; no reduced card is `proposed`; at most one live story; `needs_review` null unless kind example.

### 5.3 Reducer (`reduce.ts`) and replay (`replay.ts`)

`initialState(session_id)` → revisions `[{ seq: 0, hash: GENESIS_REVISION_HASH, event_id: null, at: null, cause: "genesis", batch_id: null, source_utterance_ids: [], snapshot: {} }]`, everything else empty. `reduce(state, event)` is pure, total over `ExmapEvent`, never mutates its input, never hashes. `replay(events, sha256)` = `verifyChain` → `initialState(events[0].session_id)` → fold `reduce` → after each revision-creating event `computeRevision(state.cards) === event.revision.hash` else `REVISION_MISMATCH`. The server replays on start-up; the browser reduces each pushed event.

`applyEffects(cards, effects, event)`: for each effect, `history` gains `{ version, record, replaced_by_event_id: event.id }` when `after.version !== existing.version`; `cards[card_id] = { ...after, history }`; new ids are appended to `card_order`. Total: an effect for an unknown card creates it.

**Totality rule.** `reduce` never throws on a well-typed event. An event naming an unknown proposal, clarification or sign-off reduces as a no-op for that record (its effects and `head` still apply; a revision is still pushed if carried). A browser must never crash on a server event.

| event | state change |
|---|---|
| `utterance.recorded` | append to `utterances` |
| `utterance.classified` | push `ClassificationRecord { …, event_id }` |
| `proposal.made` | `proposals[id] = { proposal, status: needs_clarification ? "clarifying" : "pending", made_event_id, outcome_event_id: null, effects: [], affected_card_ids: [] }`; append to `proposal_order`; applyEffects; if `resolves_clarification_id` names a known clarification: it gets `status: "answered"`, `resolved_by_proposal_id`, `answered_event_id`, `answer: <last text answer>` when `answer === null`; its asking proposal → `answered` |
| `proposal.applied` | applyEffects; proposal status `applied`, `outcome_event_id`, `effects`, `affected_card_ids` (from the effects); push `Revision` (seq+1, `event.revision.hash`, cause `proposal.applied`, `batch_id`, `source_utterance_ids`, snapshot = all cards sans history) |
| `proposal.rejected` | applyEffects (the inverse records); rejected proposal → `rejected`; the rejecting proposal → `applied` with effects; push `Revision` (cause `proposal.rejected`) |
| `proposal.confirmed` | applyEffects (status → confirmed, confirmation set, needs_review cleared); confirm proposal → `applied`, `affected_card_ids = card_ids`; **exactly** each id in `confirms_proposal_ids` → status `confirmed` (the reducer applies no rule of its own) |
| `undo.applied` | applyEffects; undo proposal → `applied`; push `Revision` (cause `undo.applied`) |
| `clarification.asked` | `clarifications[id] = { …, status: "open", asked_event_id, text_answers: [], answer: null, answered_event_id: null, resolved_by_proposal_id: null }`; append to `clarification_order`; asking proposal `outcome_event_id` |
| `clarification.answered` | `text` → push to `text_answers` (status unchanged); `candidate`/`yes` → `answered`, `answer`, `answered_event_id`, `resolved_by_proposal_id`; asking proposal → `answered`; `dismiss` → `dismissed`; asking proposal → `dismissed` |
| `question.accepted_outstanding` | applyEffects (sets `accepted_outstanding`; no version bump) |
| `signoff.recorded` | push `{ ...signoff, event_id, at, status: "active", invalidated: null }` |
| `signoff.invalidated` | that signoff → `invalidated` with `{ event_id, by_event_id, to_revision }` |
| `export.options_set` | push `options` to `export_options` |

Every event also sets `head = { seq, hash, event_id }`.

### 5.4 `apply()` (`apply.ts`)

`apply(state, command, ctx): ApplyResult`. Procedure: (0) shape-check (BAD_SHAPE; core copies declared fields only and never hashes a key it did not validate); (1) **pass 1 — validate** the whole batch against `state` with placeholder ids, each event's effects computed from the state reduced so far (a multi-proposal batch validates proposal *n* against the result of 1..n−1); any failure returns `{ ok: false, reason, detail }` with no events and no `nextId` calls; (2) **pass 2 — mint and build** with real ids (`nextId` called in the order ids appear), each event `chainEvent(prevHead, body, sha256)` advancing through the batch, `batch_id` = the first event's id; (3) if the batch creates a revision and `select.activeSignoff(state)` exists, append `signoff.invalidated` immediately after the **first** revision-creating event (once per batch); (4) return events and reduced state. Text is normalised (trim; CRLF→LF). 2-dp numbers are refused, never rounded. `detail` is a human sentence naming the offending ids (`card card_7 is superseded (by card_9)`); a multi-proposal refusal starts `proposal 2 of 3: …`.

**`utterance.record`.** Refuse: id empty or already recorded (DUPLICATE_ID); empty text (EMPTY_TEXT); non-integer / negative / `end < start` times (INVALID_TIMING); lane/provider outside their enums (INVALID_ENUM); `is_local` not boolean (BAD_SHAPE); `confidence` not null and not in [0,1] ≤ 2 dp (INVALID_CONFIDENCE). Events: `[utterance.recorded]` with exactly the ten fields. Never substantive.

**`proposal.propose`.** `proposals` non-empty (EMPTY_TARGET). Per proposal: id unique in state and batch (DUPLICATE_ID); `confidence` valid (INVALID_CONFIDENCE); every `source_utterance_ids` entry recorded (UTTERANCE_UNKNOWN); intent ↔ operation/template/pending_operation kind one-to-one (INTENT_OPERATION_MISMATCH): add→card.create, amend→card.update, remove→card.remove, replace→card.replace, clarify→definition.refine, reject→interpretation.reject, confirm→confirm, undo→undo; `resolves_clarification_id`, if set, names an `open` clarification (CLARIFICATION_NOT_AWAITING_PROPOSAL); `needs_clarification ⇔ operation === null`; when not clarifying, `template`, `pending_operation` null, `candidates = []`, `question = null` (CLARIFICATION_SHAPE). Events per proposal: `proposal.made` then its outcome; batch = `[made₁, outcome₁, (signoff.invalidated), made₂, outcome₂, …]`.

- **needs_clarification.** `question` non-empty (CLARIFICATION_QUESTION_REQUIRED); at most one of `template` / `pending_operation` (CLARIFICATION_SHAPE); both null allowed (a pure question — only text/dismiss can answer it); `candidates` non-empty only with a template; each candidate a live card with `score` null or valid; template shape-valid for its kind (`card.create` only for example/question); `pending_operation` fully validated as its operation would be now (so a Yes button is never offered for something unappliable; validated again at answer time). Events: `[proposal.made (status clarifying, effects []), clarification.asked]`. Not substantive. The engine never fills a target itself.
- **card.create.** `text` non-empty; `definitions` valid (INVALID_DEFINITION: empty term/definition or duplicate term); story: no live story (STORY_ALREADY_EXISTS); example: `rule_id` null or a live rule (CARD_NOT_FOUND / CARD_NOT_LIVE / LINK_KIND_MISMATCH); question: `about_card_id` null or any live card. Events: `proposal.made` with effect `{ before: null, after: status "proposed", version 1 }`, then `proposal.applied` with effect `{ before: the proposed record, after: status "applied" }` and a new revision. `created === changed`, `restored_by: null`. An unattached example is allowed (DoD check 3 blocks sign-off until it is attached or removed).
- **card.update.** Target live; patch non-empty (PATCH_EMPTY); keys allowed for the kind — `rule_id` only on examples, `about_card_id`/`answer` only on questions (PATCH_FIELD_NOT_ALLOWED); link targets as for create; `text` non-empty if given; patched content must differ (NO_CHANGE). Effects: card at `version+1`, status `applied`, `confirmation: null`, `changed` = this proposal, `restored_by: null`, `accepted_outstanding: null` on a question; if the card is a rule and `text` or `definitions` changed → every live example with `rule_id === card_id` gets `needs_review = { reason: "rule_changed", rule_id, event_id }` (review state only). `affected_card_ids = [card_id]`.
- **card.remove.** Target live. Effects: status `rejected`, `rejection = { kind: "removed", … }`, `confirmation: null`; a rule's linked live examples get `needs_review { rule_removed }` and keep their dangling `rule_id` (check 3 reports it); questions about it are untouched (check 3 reports the dangling link). The story may be removed (check 1 fails until a new one exists). An AI-proposed removal is an act to be reviewed (check 3).
- **card.replace.** Target live. (a) `replacement: { text, definitions? }` — text non-empty and content different (NO_CHANGE). Effects: new card, same kind, `supersedes: old`, status `applied`, version 1, links copied, `answer: null`, `created === changed` = this proposal; old card `superseded`, `superseded_by: new`, `confirmation: null`; if a rule: live examples with `rule_id === old` → `rule_id = new` (content change: version+1, status applied, `changed` = this proposal) and `needs_review { rule_replaced, rule_id: new }`; live questions about old → `about_card_id = new` (version+1). `affected_card_ids = [old, new]`. (b) `replacement_card_id` — names a live card of the same kind (KIND_MISMATCH), not the target, with `supersedes === null` (REPLACEMENT_INVALID). Effects: the replacement gets `supersedes: old` (link state: no version bump; its status, confirmation and provenance untouched); the old card as above; re-linking as above pointing at the replacement. One revision. `affected_card_ids = [old, replacement_card_id]`.
- **definition.refine.** Target live (any kind); `term` and `definition` non-empty; upsert by term (case-sensitive after trim) must change `definitions` (NO_CHANGE). A content change, including the rule → examples `rule_changed` flag.
- **interpretation.reject.** `proposal_id` exists (PROPOSAL_NOT_FOUND); status `applied` (PROPOSAL_NOT_REJECTABLE, `detail` names the status); kind not `confirm` (PROPOSAL_KIND_NOT_REJECTABLE; every other kind, including `undo` and `interpretation.reject`, is rejectable because its effects are explicit); **latest check** (REJECT_NOT_LATEST): for every *substantive* effect (before/after differ in content, live-ness or `supersedes`) the card's current `version` and `status` equal the effect's `after`; review-state-only effects (a `needs_review` flag) are not compared. Effects = `invertEffects(target.effects)`: the proposal created the card iff `before === null || before.status === "proposed"` → status `rejected`, `rejection { interpretation_rejected }`, `confirmation: null`; otherwise `before` restored verbatim with `version = current.version + 1` when content differs and `restored_by` = the rejecting proposal; a review-state-only effect restores `needs_review = before.needs_review` only. Event `proposal.rejected` with a new revision. An AI-proposed reject is itself an act to be reviewed.
- **confirm.** `card_ids` unique, each live (CARD_NOT_LIVE); `proposal_ids` unique, each existing (PROPOSAL_NOT_FOUND), status `applied` or `confirmed`, and of kind `card.remove`, `undo` or `interpretation.reject` (PROPOSAL_NOT_CONFIRMABLE: "confirm its cards instead"); both lists empty → EMPTY_TARGET; nothing would change → NOTHING_TO_CONFIRM. Effects (only for cards that change): status `confirmed`, `confirmation = { proposal_id, event_id, version: card.version, by: { provider, actor, confidence } from this proposal's stamp }`, `needs_review: null`. `confirms_proposal_ids` = distinct(`byCards` ∪ `byActs`) where `byCards` = proposals (over the changed cards' `changed.proposal_id`) not yet confirmed whose every live affected card is `confirmed` after the effects, and `byActs` = `proposal_ids` not yet confirmed. So confirming only the replacement card of a replace whose re-linked examples still need review does not confirm the replace proposal; confirming the last of them does. Event `proposal.confirmed`. No revision; never invalidates.
- **undo.** §5.9.

**`clarification.answer`.** Clarification exists (CLARIFICATION_NOT_FOUND) and `status === "open"` (CLARIFICATION_NOT_ANSWERABLE); `actor` non-empty (ACTOR_REQUIRED).
- `candidate`: `template !== null` (CLARIFICATION_NO_TEMPLATE); the card need not be among `candidates` (the person is in control) but must be live and of the kind the template needs (CARD_NOT_LIVE / LINK_KIND_MISMATCH). The engine builds the **resolved proposal** `{ id: nextId("prop"), intent: asking.intent, operation: resolveTemplate(template, card_id, state), template: null, pending_operation: null, candidates: [], confidence: 1, needs_clarification: false, question: null, source_utterance_ids: asking.source_utterance_ids, classifier: { ...asking.classifier, actor }, resolves_clarification_id: id, rationale: "clarification answered by " + actor }` — the asking classifier's stamp is kept (a fallback stays named) and the answerer is recorded in `actor`. `resolveTemplate`: `card.create` → `rule_id`/`about_card_id` = `card_id`; `card.update` → `card_id` plus the patch, where an `amendment` recomputes `patch.text` from the chosen card: `scope === null && from !== null` and the card text contains `from` (case-insensitive, first occurrence) → that occurrence replaced by `to`; otherwise `card.text + " Amendment: " + append`; `card.remove`/`card.replace`/`definition.refine` → `card_id`; `confirm` → `card_ids: [card_id], proposal_ids: []`; `interpretation.reject` → `proposal_id = cards[card_id].changed.proposal_id`. Validated exactly as `proposal.propose` against the pre-batch state; any refusal refuses the whole answer. Events: `[clarification.answered (resolved_by_proposal_id = the new id), proposal.made, <outcome>, (signoff.invalidated)]`.
- `yes`: `pending_operation !== null` (CLARIFICATION_NO_OPERATION); resolved proposal as above with `operation = pending_operation`, validated now (a target removed meanwhile → CARD_NOT_LIVE; the UI then offers Dismiss). Same events.
- `text`: non-empty (EMPTY_TEXT); `utterance_id` null or recorded (UTTERANCE_UNKNOWN). Events `[clarification.answered (resolved_by_proposal_id: null)]`; the clarification **stays open** with the text appended. The server re-runs the classifier (§8.4); a resulting proposal citing `resolves_clarification_id` resolves it. If nothing resolves it, nothing else happens: candidates / Yes / Dismiss / another text answer remain available. Core never dismisses or re-asks on anyone's behalf.
- `dismiss`: `reason` non-empty (REASON_REQUIRED); events `[clarification.answered]`; clarification → `dismissed`, asking proposal → `dismissed`. Later proposals must not cite it.

**`classification.record`.** `utterance_id` recorded (UTTERANCE_UNKNOWN); `intent` in the enum or `"none"` (INVALID_ENUM); `heard_intent !== null ⇒ intent === "none"` (BAD_SHAPE); `classifier.provider ∈ {rules.v1, claude}` (INVALID_ENUM); `confidence` valid; every `proposal_ids` entry exists and lists `utterance_id` in its `source_utterance_ids` (PROPOSAL_NOT_FOUND / CLASSIFICATION_PROPOSAL_MISMATCH); `error !== null ⇒ proposal_ids = []` (CLASSIFICATION_PROPOSAL_MISMATCH). Events `[utterance.classified]`. Not substantive. Appended by the server after the proposals of that run, also for `none`, errors and all-refused runs.

**`question.accept`.** Card live, kind question (CARD_NOT_FOUND / CARD_NOT_LIVE / KIND_MISMATCH); `answer === null` and `accepted_outstanding === null` (QUESTION_ALREADY_RESOLVED); `by` non-empty (ACTOR_REQUIRED); `reason` non-empty (REASON_REQUIRED). Effects: `accepted_outstanding = { by, reason, event_id }`. Not substantive.

**`signoff.record`.** `reviewer.name` non-empty (SIGNOFF_REVIEWER_REQUIRED); `confirmation_text.trim() === SIGNOFF_CONFIRMATION_TEXT` (SIGNOFF_CONFIRMATION_TEXT_MISMATCH); `cited_revision_hash === currentRevision.hash` (SIGNOFF_STALE_REVISION); no active sign-off (SIGNOFF_ALREADY_ACTIVE); `dodReport(state).pass` (SIGNOFF_DOD_FAILED, result carries `checks`). Events `[signoff.recorded]` with `evidence = { head_seq: state.head.seq, head_hash: state.head.hash }` and `checks` = the report just computed. Not substantive.

**`export.options_set`.** `capability_class` non-empty ≤ 80 chars (EMPTY_TEXT; the *server* checks catalogue membership and answers `CLASS_UNKNOWN`, core stays catalogue-agnostic); `kind` / `size_estimate` in their enums (INVALID_ENUM); `facts` ≤ 40 entries, each `slot` matching `/^[A-Za-z][A-Za-z0-9_]*$/` and `text` non-empty (BAD_SHAPE / EMPTY_TEXT); `by` non-empty (ACTOR_REQUIRED). Events `[export.options_set { options: { ...input, seq: previous + 1, at: ctx.now() } }]`. Not substantive; never invalidates.

### 5.5 Refusal codes (`refusals.ts`)

`REFUSAL` is the constant object `{ BAD_SHAPE: "BAD_SHAPE", … }` over every `RefusalCode` of §4; `apply()` only ever returns codes from it. The HTTP status for each code is in §8.2.

### 5.6 Definition of Done (`dod.ts`)

```ts
export const SIGNOFF_CONFIRMATION_TEXT = "I have reviewed the complete requirement and confirm it represents the agreed intent.";
export const DOD_OPTIONS: DodOptions = { requireHumanConfirm: false };   // voice confirmations count, labelled as such
export function dodReport(state: MapState, opts: DodOptions = DOD_OPTIONS): DodReport
export function isHumanVerified(state: MapState): boolean
```

| # | id | title | passes iff |
|---|---|---|---|
| 1 | `story_rules_confirmed` | Story and business rules accurately represent the agreed intent | exactly one live story and it is `confirmed`; every live rule is `confirmed` |
| 2 | `examples_reviewed` | Examples and acceptance criteria have been reviewed | every live example is `confirmed` with `needs_review === null` |
| 3 | `changes_resolved` | Changes, deletions and disputed interpretations are resolved | no proposal `pending`/`clarifying`; no clarification `open`; every applied AI act is reviewed — for every proposal with status `applied`, `classifier.actor === null` and kind ∈ {`card.remove`, `undo`, `interpretation.reject`} the check fails until it is `confirmed` (via `confirm { proposal_ids }`) or `rejected`; every live example has a `rule_id` naming a live rule; every live question with a non-null `about_card_id` names a live card |
| 4 | `questions_resolved` | Open questions are resolved or explicitly accepted as outstanding | every live question has (`answer !== null` and status `confirmed`) or `accepted_outstanding !== null` |
| 5 | `final_version_recorded` | The final version and its evidence are recorded | `currentRevision.seq ≥ 1`, `head.hash !== ""`, and the current revision hash equals `computeRevision` of the snapshot |

With `requireHumanConfirm`, "confirmed" in checks 1, 2, 4 means `confirmation.by.provider === "human"`.

Details wording (every detail names the id and the status): `rule card_3 confirmed by Ana` · `rule card_3 confirmed by voice (rules.v1, 0.5, speaker Priya)` · `rule card_3 is applied, not confirmed` · `example card_5 needs review: rule changed (event evt_12)` · `removal prop_14 of example card_9 (rules.v1, 0.5) is not reviewed` · `undo prop_21 to revision 6 (claude, 0.8) is not reviewed` · `clarification clar_2 is open: "Which example do you mean…"` · `example card_7 is not attached to a rule` · `question card_8 accepted outstanding by Sam: To be settled with the practice manager` (never "answered").

**Reviewed = explicit per-card confirm**; a "mark reviewed" control issues one `confirm` whose `card_ids` list every card it covers. **Reviewed act = explicit per-proposal confirm**; acts a person performed or answered (`classifier.actor !== null`) need no review. An answer the classifier recorded from the transcript is `applied`, not `confirmed`, so it does not satisfy check 4 until the question card is confirmed.

**The gate.** `isHumanVerified(state)` = the last sign-off exists, is `active`, `signoff.revision.hash === currentRevision.hash`, **and** `dodReport(state).pass`. Checks 1, 2, 4, 5 cannot regress without a revision (which invalidates); the last conjunct adds check 3: a clarification asked, or an AI act applied-then-rejected, after sign-off creates no revision but the map is no longer "disputed interpretations resolved" and must not export as verified. Resolving it makes the gate true again without a new sign-off. Export, the UI badge and `evidence.json` all call this.

**Rendering rule.** `select.statusLabel(card)` returns `"applied" | "confirmed" | "removed" | "interpretation rejected" | "undone" | "superseded"`; consumers never print bare `rejected`.

### 5.7 Substantive change

An event is substantive iff it pushes a `Revision`: `proposal.applied` (create/update/remove/replace/refine), `proposal.rejected`, `undo.applied`. Not substantive: `utterance.*`, `proposal.made`, `clarification.*` (alone), `proposal.confirmed`, `question.accepted_outstanding`, `signoff.*`, `export.options_set`. `apply()` refuses content operations whose result would hash identically (NO_CHANGE), so every revision changes meaning. Mechanics: immediately after the first revision-creating event of a batch, `apply()` appends `signoff.invalidated { signoff_id, by_event_id, from_revision: signoff.revision, to_revision: <that event's stamp> }` when an active sign-off exists.

### 5.8 `needs_review` (brief §0 step 3)

Set on every live example whose `rule_id` names the rule when the rule's `text` or `definitions` change via `card.update` or `definition.refine` (`rule_changed`), the rule is removed (`rule_removed`; the link is left dangling), or the rule is replaced (`rule_replaced`; the example is re-linked). Review state only. Cleared only by `confirm` naming the example, by a restore that restores an earlier `needs_review`, or by the example leaving the live set. Confirming the rule does not clear its examples' flags. Check 2 fails while any live example carries a flag. The flag's `event_id` lets the UI link to the rule's history entry.

### 5.9 Undo

Revisions are enumerated by `seq` (0 = genesis). A **step** is a run of consecutive revisions with the same `batch_id` — one utterance's batch or one click. `select.undoTarget(state, steps ≥ 1): number | null` walks back `steps` distinct steps and returns the seq of the revision just before the earliest of them (`null` when there are fewer steps). `undo { to_revision_seq: null }` = `undoTarget(state, 1)`; the classifier's `steps: n` is mapped by the bridge to `undoTarget(state, n)`.

Validation: a target exists (UNDO_NO_EARLIER_REVISION); `0 ≤ target < current.seq` (UNDO_TARGET_OUT_OF_RANGE / UNDO_TARGET_IS_CURRENT); `revisions[target].hash !== current.hash` (NO_CHANGE). Effects = `diffToSnapshot(current cards, revisions[target].snapshot)`: a card present in the snapshot whose record (sans history/version/restored_by) differs → `after` = the snapshot record verbatim with `version = current.version + 1` when content differs and `restored_by` = the undo proposal; a card absent from the snapshot (created after the target) → `rejected` / `rejection { undone }`, confirmation null. Event `undo.applied { from_revision, to_revision: target stamp, revision: { seq: current.seq + 1, hash: target.hash } }`; `apply()` asserts the recomputed hash equals `target.hash`. The undo proposal is `applied`; proposals whose effects were undone keep their historical status.

**Undo of an undo is the redo.** After an undo, the previous step *is* the undo, so a bare `undo` returns to the state before it. The bridge turns a bare voice "undo" into a `pending_operation` clarification ("The last change was itself an undo — redo it?") when `currentRevision(state).cause === "undo.applied"` and the utterance did not say "redo" (§8.7). An AI undo is an act to be reviewed (check 3) and is rejectable.

### 5.10 Public API (`index.ts`, `select.ts`)

```ts
export { canonicalJson, CanonicalError } from "./canonical.js";
export { GENESIS_PREV_HASH, eventHash, chainEvent, verifyChain } from "./chain.js";
export { GENESIS_REVISION_HASH, canonicalState, computeRevision } from "./revision.js";
export { initialState, reduce } from "./reduce.js";
export { replay } from "./replay.js";
export { apply } from "./apply.js";
export { SIGNOFF_CONFIRMATION_TEXT, DOD_OPTIONS, dodReport, isHumanVerified } from "./dod.js";
export { REFUSAL } from "./refusals.js";
export * as select from "./select.js";
export type * from "./types.js";
export function createEngine(deps: { sha256: Sha256Fn; now: () => IsoTimestamp; nextId: ApplyContext["nextId"] }): {
  apply: (state: MapState, command: Command) => ApplyResult;
  replay: (events: readonly ExmapEvent[]) => ReplayResult;
  verifyChain: (events: readonly ExmapEvent[]) => VerifyResult;
  revisionOf: (state: MapState) => Sha256Hex;
};
```

`select`: `liveCards(state)` (in `card_order`), `cardsByKind(state, kind)`, `story(state)`, `examplesOf(state, rule_id)`, `questionsAbout(state, card_id)`, `currentRevision(state)`, `revisions(state)` (without snapshots), `undoTarget(state, steps)`, `activeSignoff(state)`, `lastSignoff(state)`, `openClarifications(state)`, `pendingProposals(state)`, `lastAppliedProposal(state, opts?: { aiOnly?: boolean; statuses?: ProposalStatus[] })` (defaults `aiOnly: true` — provider ≠ human and non-empty `source_utterance_ids` — and `statuses: ["applied"]`; the bridge passes `statuses: ["applied", "confirmed"]`), `isRejectable(state, proposal_id)` (exactly the `interpretation.reject` preconditions of §5.4, so the bridge and the refusal cannot drift), `unreviewedActs(state)` (the check-3 list), `classificationsOf(state, utterance_id)`, `statusLabel(card)`, `examplesNeedingReview(state)`, `openQuestions(state)`, `exportOptions(state)` (current or null), `counts(state): Counts` (`classified` = utterances with ≥ 1 classification; `actionable` = utterances cited by ≥ 1 `proposal.made`; `classifier_errors` = classifications with `error`; `fallbacks` = classifications with `fallback_from`).

`tests/unit/core/fixtures.ts`: `testCtx()` (counter ids `evt_1`, `card_1`, …; a clock stepping 1 s) and `scenario()` — the brief's conversation as bound commands: story, rule "not within two hours", example, question, the 24h-for-nurses amendment (flags the example), a two-candidate removal clarification answered by candidate, a clarification answered by text with no resolver and later dismissed, a confirm_intent answered `yes`, a voice removal reviewed by `proposal_ids`, a two-proposal batch (reject prefix + remove), a replace by text rejected by voice, a replace by `replacement_card_id` undone, an undo of the undo, confirmations by click and by voice, acceptance of a question, export options, sign-off, a later change (invalidation), re-sign-off.

## 6. The classifier (`exmap/src/classifier/`)

Everything here is a *proposal*. Nothing in this package appends to the ledger or mutates map state; the server does that after core validates. The package imports only types from `src/core/types.ts` (§4 sections 1–4, 11) and nothing from `src/server`. Tests live under `tests/unit/classifier/`.

```
src/classifier/
  index.ts              createClassifier(), selectProvider(), re-exports
  types.ts              re-exports the §4 §11 types; ClassifierError
  schema.ts             zod: IntentSchema, CardDraftSchema, CardPatchSchema, AmendmentSchema, OperationSchema, ClarificationSchema,
                        ResolvesSchema, ModelProposalSchema (model-fillable subset), ProposalSchema, ProvenanceSchema, ClassifierInputSchema,
                        assertProposalInvariants(), draftsOf(), CHOICE = "$choice"
  constants.ts          MIN_CONFIDENCE, TARGET_CUES, RECENT_UTTERANCES, RECENCY_WINDOW, MAX_CANDIDATES, TOPIC_MIN_SCORE, DRAFT_MIN_CONTENT_WORDS,
                        ANSWER_MAX_TOKENS, ANSWER_MIN_RATIO, RATIONALE_MAX, CLAUDE_MODEL, CLAUDE_EFFORT, CLAUDE_MAX_TOKENS, CLAUDE_TIMEOUT_MS, SYSTEM_PROMPT_VERSION
  normalize.ts          normalizeText, splitSentences, stripDiscourse, contentTokens, tokenMatch, originalSpan
  cues.ts               INTENT_CUES, KIND_CUES, DISCOURSE_MARKERS, REFERENT_PATTERNS, ANSWER_FILLER (data only)
  extract.ts            detectKind, kindCue, extractDraft, extractAmendment, extractAnswer, extractDefinition, extractReason, replacementDraft
  referents.ts          parseReferent, maskReferents, resolveReferent, linkRule, linkAbout, askTarget
  clarification.ts      parseAnswer, applyChoice, resolveClarificationAnswer
  rules-v1.ts           createRulesClassifier(), classifyRules()
  claude/client.ts      ModelClient (structural type), createAnthropicClient()
  claude/system-prompt.ts  FROZEN_SYSTEM, SYSTEM_PROMPT_VERSION
  claude/user-message.ts   renderUserMessage()
  claude/validate.ts       validateModelProposal()
  claude/claude-provider.ts createClaudeClassifier()
```

### 6.1 Interface, schema, invariants

`Classifier`, `ClassifierInput`, `ClassifierProposal` and friends are the §4 §11 types. The zod schemas in `schema.ts` mirror them and `z.infer<typeof ProposalSchema>` is asserted mutually assignable with `ClassifierProposal`. `classify()` throws `ClassifierError("E_CLASSIFIER_INPUT_INVALID")` on a malformed input (a programming error, never a classification outcome). The server calls `classify()` serially per session.

`ModelProposalSchema` (what the model fills; no `optional()`, no `min`/`max` — the SDK's grammar transform drops `enum`/`const`/`minimum`/`maximum` into descriptions, so enums are spelled out in the system prompt and an off-enum value fails zod client-side): `intent`, `operations`, `target_card_ids`, `confidence: z.number()`, `needs_clarification`, `clarification`, `resolves`, `rationale`. `ProposalSchema` extends it with `confidence` in [0,1], `heard_intent`, `classifier: ProvenanceSchema`, `source_utterance_ids` (≥ 1). `CHOICE = "$choice"` is the sentinel for a target still to be chosen.

Invariants, enforced by `assertProposalInvariants(p, input)` before either provider returns (including on the fallback path; a violation is a bug → `ClassifierError("E_PROPOSAL_INVARIANT")`):

| # | Invariant |
|---|---|
| I1 | `needs_clarification === (clarification !== null)`; if true then `operations.length === 0` and `intent !== "none"` |
| I2 | add→`card.create`; amend→`card.update`; remove→`card.remove`; replace→`card.replace`; clarify→`definition.refine`; reject→`interpretation.reject`; confirm→`confirm`; undo→`undo`; none→`[]`. A proposal may additionally carry one leading `interpretation.reject` or `confirm` (the "No, …"/"Yes, …" prefix) before the intent's own operation; `remove` may carry several `card.remove` (a "both" answer). The same table binds `pending_operations` to the clarification's intent |
| I3 | `target_card_ids` = ordered unique card ids referenced by `operations` ∪ `pending_operations` (card_id, card_ids, rule_id, about_card_id, replacement_card_id; excluding `"$choice"`) ∪ `candidates` |
| I4 | Every id in I3 is in `input.cards` (never invented). `interpretation.reject.proposal_id` is `last_rejectable.id`, an index card's `proposal_id`, or `"$choice"`. `card.replace` has exactly one of `replacement` / `replacement_card_id` non-null and `replacement_card_id !== card_id`. `confirm.card_ids` may be `[]` only when `last_proposal.status === "applied"` and `last_proposal.op ∈ {card.remove, undo, interpretation.reject}` |
| I5 | `choose_target` ⇒ `candidates.length ≥ 2` and `"$choice"` occurs in `pending_operations`; `confirm_intent` ⇒ `candidates.length === 0`, `pending_operations.length === 1`, no `"$choice"` |
| I6 | `confidence ≥ MIN_CONFIDENCE` whenever `needs_clarification === false` and `intent !== "none"` |
| I7 | `source_utterance_ids[0] === input.utterance.id`; when `resolves` is set it also contains `pending_clarification.asked_by_utterance_id` |
| I8 | `rationale` non-empty and ≤ 200 characters |
| I9 | `heard_intent !== null ⇒ intent === "none"`; `intent === "none" ⇒ operations.length === 0 && !needs_clarification` |
| I10 | `card.update.patch` has ≥ 1 non-null field and not both `text` and `text_append`; `answer` only when the target is a question, `rule_id` only for an example, `about_card_id` only for a question |

`none` has two flavours: *chatter* (`heard_intent: null`, `confidence: 0`, rationale "No map-changing cue found.") and *heard but not actionable* (`heard_intent: <intent>`, the scored confidence, a rationale saying why nothing happens). Both are ledgered by the server as `utterance.classified` with `heard_intent`.

### 6.2 Constants and provider selection

```ts
export const MIN_CONFIDENCE = 0.4;        export const TARGET_CUES = 2;          export const RECENT_UTTERANCES = 12;
export const RECENCY_WINDOW = 4;          export const MAX_CANDIDATES = 4;       export const TOPIC_MIN_SCORE = 0.5;
export const DRAFT_MIN_CONTENT_WORDS = 6; export const ANSWER_MAX_TOKENS = 6;    export const ANSWER_MIN_RATIO = 0.5;
export const RATIONALE_MAX = 200;
export const CLAUDE_MODEL = "claude-opus-5-5";   export const CLAUDE_EFFORT = "medium" as const;
export const CLAUDE_MAX_TOKENS = 4096;           export const CLAUDE_TIMEOUT_MS = 20_000;
export const SYSTEM_PROMPT_VERSION = "exmap.classifier.claude.v1";
```

`selectProvider(env)`: `EXMAP_CLASSIFIER === "rules.v1" | "rules"` → `rules.v1` (explicit off wins even with a key); `"claude"` → `claude` (credentials may come from an `ant auth login` profile; with none at all the first call fails with provenance error `auth` and falls back — never a crash); any other value → `ClassifierError("E_CLASSIFIER_UNKNOWN_PROVIDER")` listing the allowed values; unset → `claude` iff `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` is non-empty, else `rules.v1`. `createClassifier({ env?, client?, onError? })` builds `createRulesClassifier()` or `createClaudeClassifier({ client, rules: createRulesClassifier(), onError })`. `ClassifierError.code ∈ { E_CLASSIFIER_UNKNOWN_PROVIDER, E_CLASSIFIER_INPUT_INVALID, E_PROPOSAL_INVARIANT }`; provider failures of the claude provider are never thrown — they become provenance (§6.5).

Environment: `EXMAP_CLASSIFIER` as above; `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` read by the SDK; `ANTHROPIC_BASE_URL` read by the SDK (the operator's endpoint), not interpreted by exmap. The model id and effort are not configurable. The startup log line reads `classifier: claude (claude-opus-5-5)` or `classifier: rules.v1 (offline)`; the UI header shows the same from `/api/config`.

`recentIds` = ids of the last `RECENCY_WINDOW` entries of `input.recent` ("the window"). A card is *recent* when `card.last_utterance_id ∈ recentIds`; a `LastProposalRef` is *in the window* when its `utterance_id ∈ recentIds`.

### 6.3 `rules.v1` — deterministic, offline

`createRulesClassifier()` wraps the pure, synchronous `classifyRules(input): ClassifierProposal` (no I/O, randomness or clock; same input → byte-identical proposal).

**Normalisation (`normalize.ts`).** `normalizeText(raw)` works token by token so every normalised token keeps the character span of the original word(s); extractors match on the normalised text and read captures back with `originalSpan`, so `from: "two hours"` and `definition: "a booked slot, not a walk-in"` keep the speaker's casing, hyphens and number words. In order: (1) lowercase, trim, collapse whitespace; hyphens and en-dashes become spaces (`walk-in` → `walk in`, the span covering the original); (2) contractions expanded from a table (`don't→do not`, `can't→can not`, `cannot→can not`, `that's→that is`, `it's→it is`, `let's→let us`, `i'm→i am`, `we're→we are`, …); (3) number words → digits (`zero…twenty, thirty…ninety, hundred`; `a couple of→2`; `half an hour→30 minutes`; `an hour→1 hour`; `twenty four→24`); (4) punctuation stripped except `,` `?` `'`; `?` kept only at sentence end; `.`/`!`/`;`/`:` become the sentence break `|`. `splitSentences` splits on `|` and `?` (kept attached). `stripDiscourse(sentence)` removes, repeatedly (≤ 3), a leading marker from {`ok, okay, right, alright, so, well, now, anyway, um, uh, er, hmm, got it, i see, understood, sure, sorry, and, but, also, then`} when followed by a comma or ≥ 3 words; a sentence consisting only of {`got it, i see, understood, so, well, anyway, um, uh, er, hmm, sorry`} is dropped; a bare `Okay.`/`Right.`/`Sure.`/`Fine.` is kept (confirm cue); `yes, yeah, yep, no, nope, exactly, correct, actually` are never stripped; the first word before stripping is remembered for A6. `contentTokens(text)` = tokens minus stop words, stemmed by suffix stripping (`ations, ation, ings, ing, ies→y, es, ed` when ≥ 4 chars remain; trailing `s` when ≥ 2); `tokenMatch(a, b)` = equal stems or prefix with the shorter ≥ 5 chars (`cancel` ~ `cancellation`, `gps`→`gp`).

**Cue tables (`cues.ts`).** Each intent has ordered *groups*; a group scores 1 if any entry matches (synonyms cannot inflate a score). Entries are phrases at word boundaries or regexes. Referents never score: A2 is evaluated on the sentence with every referent span replaced by `<ref>` (`maskReferents`).

- **add** — A1 add verbs: `we need, we also need, we will need, also need, need a, need an, needs a, there is also, there is another, another, add a, add an, add the, let us add, we should also, we should have, one more, what about adding, we need to cover, cover the case, include`. A2 lexical kind cue: `kindCue()` finds a rule/example/question phrase cue on the masked sentence (`?` and interrogative openers are A5, not A2). A3 subject-modal opener: `/^((a|an|the|every|any|all|no|each) )?[a-z]+( [a-z]+)? (should|must|shall|can|can not|may|may not|needs?|has to|have to|is|are|is not|are not)\b/` with the subject not in {`it, that, this, we, i, you, they, there, he, she, who, what, which`}. A4 example structure: `/^(for example|for instance|e g|say|suppose|imagine|let us say)\b/`, `/\b(if|when|given)\b.*\bthen\b/`, `/\b(say|suppose|imagine) (a|an|the|it|they|we|there|you)\b/`. A5 interrogative: `/\?$/` or `/^(what|why|how|when|where|who|which|does|do|is|are|can|could|should|would|will|has|have|did)\b/`. A6 continuation: first word (before stripping) ∈ {`and, also, similarly, likewise, plus, or`} and `last_proposal.intent === "add"` in the window with `kind !== null` → the draft kind is `last_proposal.kind`.
- **amend** — M1 change verbs: `change, make that, make it, make the, make them, make those, update, set that to, set it to, set the, bump, raise, lower, increase, decrease, extend, shorten, reduce, switch to, tweak, amend, adjust, alter, revise, reword, rename, correct that, should actually be, should really be`. M2 `/\b(to|up to|down to|rather than|instead of|now|not \d+ but)\s+\d+(\.\d+)?/`. M3 correction: `actually, correction, i meant, on second thought, let me correct, wait, strike that, scrap that, no wait`. M4 answer cues: `the answer is, the answer to that is, to answer that, answer: , answering that`.
- **remove** — D1: `delete, remove, drop, get rid of, scrap, take out, take that out, take it out, bin, lose, strike, cut, ditch`. D2: `do not need, no need for, not needed, do not want, unnecessary, does not belong, should not be there, redundant, duplicate, duplicates`. D3: `does not apply, irrelevant, not relevant, out of scope, forget that, forget it, never mind that, ignore that, ignore it`.
- **replace** — P1: `instead, instead of, rather than, replace, replaces, swap, in place of, supersede, supersedes, better example, better rule` (a bare sentence-final `instead` counts only when P2 also matched). P2 deictic new content: `use this, use that, use the following, this one instead, this version, this example, this rule, this wording, the following`.
- **clarify** — C1: `i mean, we mean, to clarify, to be clear, just to clarify, define, definition, means, meaning, when i say, when we say, what i mean by, let me clarify, in other words`. C2 definition patterns (capture `term`, `def`): `/\bby (an? |the )?(?<term>[a-z][a-z ]{1,40}?)\s*,?\s*(i|we) mean (?<def>.+)$/`, `/^(an? |the )?(?<term>[a-z][a-z ]{1,40}?) means (?<def>.+)$/`, `/(when (i|we) say|what (i|we) mean by) (an? |the )?(?<term>[a-z][a-z ]{1,40}?)\s*,?\s*(is|i mean|we mean|means)?\s*(?<def>.+)$/`.
- **reject** (first sentence only) — R1: `/^(no|nope|nah)\b/`, `that is not, that was not, wrong, incorrect, not right, not correct, you got that wrong, you have got that wrong, that is off`. R2: `not what i said, not what i meant, not what we said, not what we meant, misunderstood, misheard, did not say that, never said, that is not it, you misread, i did not mean, we did not mean`.
- **confirm** — F1 sentence-initial (after `stripDiscourse`): `/^(yes|yeah|yep|yup|correct|right|exactly|agreed|ok|okay|sure|fine|perfect|great|good|absolutely|definitely)\b/`. F2 anywhere: `that is right, that is correct, that is it, that is exactly, exactly right, exactly, precisely, spot on, looks good, looks right, sounds right, sounds good, i agree, we agree, confirmed, happy with that, that works, absolutely`.
- **undo** — U1: `undo, go back, revert, roll back, rollback, put it back, put that back, restore, scratch that, as it was, back to how it was, reinstate, bring back`. U2: `previous version, last version, earlier version, the way it was, how it was, that change, the last change, what it was, previous state, previous revision, before that`, `/\b(last|previous)( \d+)? (changes?|steps?|versions?)\b/`.

**Card-kind heuristics (`extract.ts`).** `kindCue(masked)` — lexical cues only: rule {`should, must, shall, may not, can not, is not allowed, are not allowed, not allowed, not within, only if, only when, unless, always, never, needs to, need to be, has to, have to, at least, at most, no more than, no later than, no earlier than, within, required, mandatory, is allowed, are allowed, can only, able to`}; example {`for example, for instance, e g, say, suppose, imagine, let us say, scenario, case where, such as, example, another example, an instance, take a`, `/\b(if|when) (a|an|the|someone|somebody|i|we|you|they|it)\b/`, `/\b(if|when|given)\b.*\bthen\b/`}; question {`what about, what if, do we know, does anyone know, not sure whether, not sure if, unclear whether, unclear if, need to check, need to find out, to be confirmed, open question, who decides, i wonder, the question is`}. `detectKind(sentences, ctx)` — every `kindCue` plus the interrogative form as question cues; precedence **question > example > rule**; no cue → A6 → `last_proposal.kind`; A1 → noun heuristic (`case, scenario, instance, example` → example; `question, unknown, to check, find out` → question; `rule, constraint, policy, limit, restriction` → rule; otherwise rule, and the rationale says the kind was defaulted). `story` is never produced by rules.v1.

**Scoring.** `scores[intent]` = cue groups matched over all sentences (reject: first sentence only). Interactions in order: (a) prefix reject — R1 in sentence 1 and another intent scored → `scores.reject = 0`, `prefix = "reject"`; (b) prefix confirm — F1 in sentence 1 and another intent scored → `scores.confirm = 0`, `prefix = "confirm"`; (c) replace absorbs content — P1 or P2 matched → A2, A3, A4 do not count for add; (d) interrogative — A5 matched and a non-add intent scored → A5 does not count for add; (e) all zero → `none`, chatter. `best, runner` = top two by (−score, precedence `[undo, reject, remove, replace, amend, clarify, confirm, add]`); `strength = min(best.score / TARGET_CUES, 1)`; `margin = (best.score − runner.score + 1) / (best.score + 1)`; `confidence = round2(strength × margin)`; (f) when (d) applied and best ≠ add → `confidence = round2(confidence × 0.5)`. With `TARGET_CUES = 2`: one group alone → 0.5 (passes); two → 1.0; two vs one → 0.67; one vs one → 0.25 (clarification); two vs two → 0.33 (clarification).

**Prefix operations.** `prefix === "reject"` → a leading `interpretation.reject { proposal_id: last_rejectable.id }` when `last_rejectable` exists and is in the window; `prefix === "confirm"` → a leading `confirm { card_ids }` when `last_proposal` is in the window, `status === "applied"`, `op ∈ {card.create, card.update, card.replace, definition.refine}` and `card_ids ∩ index ≠ ∅`. Otherwise the prefix is dropped and the rationale says so. Core may still refuse a reject with `REJECT_NOT_LATEST` / `PROPOSAL_NOT_REJECTABLE` when the map moved; that lands in `refused[]`.

**Pure reject** (best = reject, no prefix): `last_rejectable` in the window → `interpretation.reject { proposal_id }`; exists but outside the window → `askTarget` over the up-to-`MAX_CANDIDATES` most recent non-story index cards with `proposal_id !== null`, question "Which interpretation is wrong?", pending `[{ kind: "interpretation.reject", proposal_id: "$choice" }]` (one such card → `confirm_intent` "Did you mean to reject the interpretation that produced <label>?"; none → `none`/`heard_intent: "reject"`); `last_rejectable === null` → `none`, `heard_intent: "reject"`, rationale "Heard a rejection, but nothing on the map can be rejected right now; use Remove or Edit on the card."

**Pure confirm** (best = confirm, no prefix): `last_proposal` null → `none`/`heard_intent: "confirm"` "Nothing to confirm yet."; `status === "confirmed"` → `none` "That interpretation is already confirmed."; `op === "confirm"` → `none` "A confirmation cannot be confirmed."; `op ∈ {card.remove, undo, interpretation.reject}` (status applied) → **`confirm { card_ids: [] }`** with rationale "Confirmed the <removal|undo|rejection>." — the bridge turns it into `confirm { card_ids: [], proposal_ids: [last_proposal.id] }`, which reviews the act; content op with `card_ids ∩ index = ∅` → `none` "Nothing live to confirm."; otherwise `confirm { card_ids: last_proposal.card_ids ∩ index }`. The window is not required for a pure confirm.

**Threshold wrap.** When `confidence < MIN_CONFIDENCE` and the proposal is actionable: it becomes a `confirm_intent` clarification — `operations` move to `pending_operations` (the prefix op is dropped, the rationale notes it), `candidates: []`, question `Did you mean to <verb phrase>?` (`add a <kind>: "<text 40ch>"` / `change <label>` / `remove <label>` / `replace <label>` / `define "<term>"` / `reject the last interpretation` / `confirm the last interpretation` / `undo the last change`), rationale `Could be <best> or <runner>: matched '<cue>' and '<cue>'.` An ambiguous target makes it a `choose_target` instead. A target resolution of `none` makes it a `none` proposal with `heard_intent`.

**Referent resolution (`referents.ts`).** `parseReferent(sentence): Referent | null` where `Referent = { kind: CardKind | null; topic: { text; named: boolean } | null; ordinal: 1|2|3|4|"last"|"previous"|null; bare: boolean; span }` — the first referent by position is the target. Patterns: (1) `the story`; (2) `<det> (first|second|third|fourth|last|latest|previous|earlier|older|old|new|newer)? <kind-word> (about <topic>)?` (kind words `rule(s)`, `example(s)`, `question(s)`, `story`; `card(s)`/`one(s)` carry no kind; determiners `that, this, the, those, these`); (3) `the <adj>+ (example|rule|question|one)` → named topic = the adjectives (`the GP one` → "gp", `the old nurse one` → "old nurse"); (4) `the one about <topic>`; (5) `<det> <adj>* <noun>` with a non-kind content noun → *paraphrase* topic of ≤ 3 content tokens (`that limit` → "limit", `the GP window` → "gp window"); (6) bare demonstrative `that one | this one | that | this | it | those | these` followed by nothing, a stop word, a number or a verb; (7) ordinal only (`the first one`, `number N`, `option N`, `the last one`, `the previous one`). Exclusions: `this <kind>`/`this one`/`this` directly after `use`/`take` is P2, not a referent; `that` inside a C2/R2/F2 phrase is not a referent; `it` as the subject of a rule/example clause is not — only `it` after an M1/D1/U1 verb or before `to`/`back`.

`resolveReferent(ref, input, want: { kind?, exclude? }): Resolution` (`resolved { card, how } | ambiguous { candidates (≤ MAX_CANDIDATES, most recent first), why } | none { why }`), first hit wins: (0) `kind = ref?.kind ?? want.kind`; (1) pool = `input.cards` minus story (unless kind story) minus `want.exclude`, filtered by kind; (2) empty → `none`; (3) last-interpretation shortcut (bare demonstrative or no referent): `last_proposal` in the window and `last_proposal.card_ids ∩ pool` has exactly one → resolved; (4) named topic: score each card `|topic tokens matched by tokenMatch in card text| / |topic tokens|`, keep ≥ `TOPIC_MIN_SCORE`; one → resolved; several with a strict best → resolved; tie → ambiguous(tied); none → ambiguous(pool by seq desc) ("the person named a card; a miss means ask"); (5) paraphrase topic: same scoring; strict best ≥ bar → resolved; tie → ambiguous; none → continue; (6) ordinal: `last` → most recent in pool; `previous` → second; a number → ambiguous(pool); (7) `pool.length === 1` → resolved; (8) recency: `touched = pool.filter(recent)` by seq desc — one → resolved; ≥ 2 → speaker-aware tie-break: `touched[0].last_speaker !== null && touched[0].last_speaker === input.utterance.speaker` → resolved ("the <kind> you just gave") else ambiguous(touched); none → ambiguous(pool by seq desc, "nothing recent of that kind"). Kind preferences when the referent has none: amend → rule when an amendment value was extracted, question when an answer (M4) was extracted; remove → any; replace → the draft's kind, else `replacement_card.kind`; clarify → the explicit referent else the story.

`askTarget(res, op, intent, verb)`: ≥ 2 candidates → `choose_target` with `candidates = [{ card_id, label: "<title> (<kind>, <last_speaker ?? lane-or-'typed'>)" }]`, question `Which <kind ?? 'card'> do you mean: (1) <label>, or (2) <label>?` (up to 4), `pending_operations = [op with "$choice"]`; exactly 1 → `confirm_intent` bound to it, question `Did you mean to <verb> <label>? (<why>)`. A `none` resolution → a `none` proposal with `heard_intent`.

`linkRule(draft, input)` (example → rule): the rule with the highest count of matched content tokens wins if ≥ 2 and strictly best; else the rule touched most recently in the window; else the only rule; else `null`. `linkAbout(draft, input)` (question → card): same count over rules and examples; ≥ 2 strict best wins, ties rule-before-example then recency; else the single card of `last_proposal` if in the window and index; else `null`.

**Extraction (`extract.ts`).** `extractDraft` — `text` = the original text of all kept sentences (lead-in-only and discourse-only sentences dropped) minus sentence-initial discourse markers, `yes,`/`no,`/`yes but`/`no but`, `for example,`/`for instance,`/`e.g.`/`one more example:`/`another example:`/`say`, `i said`/`i meant`/`we said`, `the story is:`; first letter capitalised, trailing full stop ensured, whitespace collapsed; `rule_id` via `linkRule`, `about_card_id` via `linkAbout`. `extractAmendment(sentence, card)` — `to` = the first `<number> <unit>` (unit optional: `hour(s)|hr(s)|minute(s)|min(s)|day(s)|week(s)|month(s)|year(s)|percent|%|pound(s)|dollar(s)|time(s)`) rendered as digits + unit; `scope` = the original span after `for ` following the value, else null; `from` = the single `<number> <unit>` phrase in the card's text when exactly one exists, else null; `scope === null && from !== null` → `patch.text` = card text with `from` replaced by `to`; otherwise `patch.text_append = "Amendment: " + <utterance minus correction cues, first letter upper-cased>`; no value → `amendment: null` and the append form; when the target is `$choice` the pending operation always uses the append form. `extractAnswer` — the span after the M4 cue, trailing full stop removed; target = the most recent unanswered question in the window, else the only one, else ambiguous. `extractDefinition` — from the C2 captures as original spans, `term` trimmed of articles. `extractReason` (remove) — the sentences after the cue sentence, else the span after the first comma, else `""`. `replacementDraft` — the utterance minus P1/P2 phrases and a leading `instead,`, kept only with ≥ `DRAFT_MIN_CONTENT_WORDS` content tokens and a kind cue or A3/A4 structure.

**Pipeline (`classifyRules`).**
```
1. validate; n = normalizeText(utterance.text); sentences = splitSentences(n).map(stripDiscourse) minus dropped; s1 = sentences[0]  (none left → none, chatter)
2. if pending_clarification: a = parseAnswer(s1, pending, rest, scoresOf(s1))                       (§6.6)
     choose | yes → resolveClarificationAnswer(pending, a, input);  no | dismiss(null) → the dismissal proposal;
     dismiss(remainder) → classify(remainder) from step 3 with resolves { …, dismissed: true };  reask → the reask proposal;  null → continue
3. scores, prefix, best/runner, confidence
4. switch best:
   none    → { intent none, heard_intent null, operations [], confidence 0, rationale "No map-changing cue found." }
   add     → kind = detectKind | A6 kind | noun default; card = extractDraft(+links); [card.create]
   amend   → ref = parseReferent(s1); M4 → answer path: card.update { card_id, patch: { answer }, amendment: null }
             else value = extractAmendment; res = resolveReferent(ref, input, { kind: value ? "rule" : undefined })
                  resolved → card.update { card_id, patch, amendment }; ambiguous → askTarget(res, card.update {$choice, text_append}, "amend", "change"); none → none/heard amend
   remove  → ref; res = resolveReferent(ref, input, {}); reason = extractReason; resolved → card.remove; ambiguous → askTarget; none → none/heard remove
   replace → replacement = replacementDraft(sentences); replacement_card = replacement ? null : (last_proposal in window && intent add && its card in index ? that card : null)
             neither → none, heard replace, "Heard 'instead' but no new content; say the new example first."
             ref = parseReferent(s1) (P2 excluded); res = resolveReferent(ref, input, { kind: replacement ? detectKind(…) ?? "example" : replacement_card.kind, exclude: [replacement_card?.id] })
             resolved → card.replace { card_id, replacement, replacement_card_id }; ambiguous → askTarget; none → none/heard replace
   clarify → d = extractDefinition(s1); null → none, heard clarify, "Heard a clarification but no definition; say 'By X I mean Y'."
             else card_id = explicit referent ? resolveReferent(…) : story in index ? story.id : none ("There is no story to attach the definition to.") → definition.refine
   reject  → pure reject rules;   confirm → pure confirm rules;   undo → undo { steps } (steps = /(\d+) (steps?|changes?|versions?|times)/ → n; `twice` → 2; else 1)
5. prepend the prefix op; threshold wrap; target_card_ids (I3); stamp classifier { provider "rules.v1", model null, prompt_version null, fallback_from null, error null };
   source_utterance_ids [utterance.id] (+ pending.asked_by_utterance_id when resolves is set); assertProposalInvariants; return
```
Rationale templates: `Heard a <kind> ('<cue>', '<cue>').` · `Change to <title>: replaced '<from>' with '<to>'.` · `Change to <title>: appended the amendment verbatim; review the wording.` · `Answered "<question title>".` · `Remove <title> — the <kind> you just gave.` · `Which <kind>? Two were mentioned recently.` · `Rejecting the last interpretation ('<cue>').` · `Confirmed the last interpretation.` · `Confirmed the removal.` · `Undo one step ('<cue>').` · `Defined '<term>'.` · `Could be <a> or <b>; asking.` · `No map-changing cue found.` · `There is no <kind> to <verb>.`

Known limitations (README): a restated rule without a change verb ("the limit is 24 hours") is an add; two instructions in one utterance yield only the first intent's operation plus any reject/confirm prefix; kind defaults to rule; re-linking an example or re-pointing a question is UI-only; a definition attaches to the story unless a card is named. The claude provider covers these.

### 6.4 The `claude` provider

**Client seam (`claude/client.ts`).** `ModelClient = { messages: { create(params: MessageCreateParamsNonStreaming, options?: { timeout?, maxRetries?, signal? }): Promise<CreateResult> } }` where `CreateResult = Pick<Message, "content" | "stop_reason" | "model"> & { stop_details?: { type: "refusal"; category?: string | null; explanation?: string | null } | null; usage?: { cache_read_input_tokens?: number | null } }`. `createAnthropicClient()` = `new Anthropic()` (credentials from `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` / an `ant auth login` profile). The real client satisfies `ModelClient` structurally; tests inject a fake. Error classes are imported from the SDK so `instanceof` works for both.

**Request (`claude/claude-provider.ts`).**
```ts
const FORMAT = zodOutputFormat(ModelProposalSchema);      // one object: .schema goes to the API, .parse() runs on the reply
const res = await client.messages.create({
  model: CLAUDE_MODEL, max_tokens: CLAUDE_MAX_TOKENS,
  system: [{ type: "text", text: FROZEN_SYSTEM, cache_control: { type: "ephemeral" } }],
  messages: [{ role: "user", content: renderUserMessage(input) }],
  output_config: { format: FORMAT, effort: CLAUDE_EFFORT },
}, { timeout: CLAUDE_TIMEOUT_MS, maxRetries: 1, signal });
```
Not sent (brief §4): `thinking` (on by default; `{ type: "disabled" }` / `budget_tokens` are 400s), assistant prefill, `tool_choice`, `temperature`. The system block is the only cached prefix; everything volatile (card index, recent utterances, the new utterance) is in the user message; no timestamps or session ids anywhere in the request.

**Frozen system prompt (`claude/system-prompt.ts`).** `export const FROZEN_SYSTEM` is exactly the text between the fence lines below, no interpolation. A unit test pins its SHA-256 (the constant is computed once at implementation and committed in the test) so an accidental edit fails the build; `SYSTEM_PROMPT_VERSION` is bumped whenever it changes.

```
You are the classifier inside Example Map Live, a tool that listens to a requirements conversation and keeps an Example Map up to date. You never change the map yourself: you turn ONE new utterance into a PROPOSAL that people in the meeting will see, accept, correct or reject. The humans own the meaning; you handle the mechanics of structuring it.

EXAMPLE MAPPING
A map has one story and three kinds of cards:
- rule: a business rule or acceptance criterion ("A patient should be able to cancel online, but not within two hours of their appointment").
- example: a concrete instance that illustrates a rule, ideally as Given / When / Then in plain text. Every example should link to the rule it illustrates (rule_id).
- question: something the group does not know yet ("What about appointments already in progress?"). A question links to the card it is about (about_card_id) when there is one, and may later carry an answer.
Cards keep the speaker's own words; tidy grammar lightly, never add facts they did not say. Definitions of terms are attached to a card (usually the story) with definition.refine.

INTENTS (exactly one per utterance; "none" when the utterance changes nothing)
- add → card.create {card}. New rule, example or question. ("We also need an error case.")
- amend → card.update {card_id, patch}. A field of an existing card changes: patch.text (rewrite the full text so it reads as one coherent card with the change applied), patch.answer (the group answered a question), patch.rule_id / patch.about_card_id (re-link). Fill amendment.from/to/scope when a value changed. ("Change that limit to 24 hours.")
- remove → card.remove {card_id, reason}. ("We don't need that rule.")
- replace → card.replace {card_id, replacement, replacement_card_id}. One card is superseded by another: either new content (replacement.text) or a card that already exists (replacement_card_id); exactly one of the two. ("Use this example instead.")
- clarify → definition.refine {card_id, term, definition}. A term is defined or refined; card_id is the story unless a card was named. ("By appointment, I mean a booked slot.")
- reject → interpretation.reject {proposal_id} of the LAST REJECTABLE proposal. ("No, that's not what I said.") If there is none, intent "none" with a rationale saying so.
- confirm → confirm {card_ids} of the LAST PROPOSAL's live cards. ("Yes, that's exactly right.") When the LAST PROPOSAL was a removal, an undo or a rejection, output confirm {card_ids: []}: that records that the person accepted the act. If there is no LAST PROPOSAL, or it is already confirmed, intent "none" with a rationale saying so.
- undo → undo {steps}, steps=1 unless they say otherwise; one step is everything one utterance changed. ("Go back to the previous version.")
- none → chatter, procedure, or a statement that proposes nothing. Use it also when the words carried an intent that cannot be applied (nothing to change, nothing to confirm) and say why in the rationale.
A leading "No, …" or "Yes, …" followed by an instruction is the instruction, with interpretation.reject / confirm placed first in operations. A question that merely asks whether to do something ("Should we delete that?") is not an instruction: propose it as a confirm_intent clarification.

ASK RATHER THAN GUESS
- Only ever use card ids that appear in the CARD INDEX and proposal ids that appear in LAST PROPOSAL / LAST REJECTABLE. Never invent, shorten or guess an id. If the utterance refers to a card you cannot find in the index, ask.
- If two or more cards could be what they mean ("that one", "that example" when two examples were just discussed), set needs_clarification=true with kind "choose_target", list the candidates (most recent first, at most four) and put the operation in pending_operations with "$choice" where the card id goes. Use the speaker: "that one" right after the same speaker gave an example usually means that example; when recency and speaker disagree, ask.
- If you are not confident about the intent itself, set needs_clarification=true with kind "confirm_intent", candidates empty, exactly one complete operation in pending_operations, and a one-sentence yes/no question.
- When PENDING CLARIFICATION is present, first decide whether the new utterance answers it: an ordinal ("the second one"), a label ("the GP example"), "yes"/"no" for a confirm_intent question, or "neither"/"none of them". If it does, set resolves (proposal_id, chosen_card_ids, dismissed) and output the resolved intent and operations. "Neither, I meant …" or "No, delete the rule instead" dismisses it and the rest of the utterance is classified normally. An unrelated statement leaves it open: classify normally with resolves=null. A bare "yes" to a choose_target question cannot be mapped: intent "none" with a rationale asking them to say which one.

OUTPUT CONTRACT
- intent: one of add, amend, remove, replace, clarify, reject, confirm, undo, none.
- operations: the operations to apply, empty when needs_clarification is true or intent is none. Each uses only index ids. Operation kinds: card.create, card.update, card.remove, card.replace, definition.refine, interpretation.reject, confirm, undo. Card kinds: story, rule, example, question.
- target_card_ids: every card id named in operations, pending_operations and candidates.
- confidence: 0 to 1 — your confidence in the intent AND the target. Use ≤ 0.3 when the utterance is garbled transcript, 0.5 when one reading is clearly best but the words were loose, ≥ 0.8 when the words say exactly what the operation does.
- needs_clarification / clarification: as above. A clarification never has operations.
- resolves: only when answering the pending clarification; otherwise null.
- rationale: ONE short sentence to the people in the meeting, in plain words, naming the words you relied on. No ids.
- Drafts (card): kind, text (their words), rule_id for an example when a rule in the index clearly matches (else null), about_card_id for a question when a card in the index clearly matches (else null).
- Speakers are labels people assigned to an audio lane, or "(typed)" for text someone typed; use them only as given. Transcripts may contain speech-to-text errors: read charitably, but do not invent what was not said.
```

**User message (`claude/user-message.ts`).** `renderUserMessage(input)` — deterministic sections in this order, ids verbatim, no timestamps, no session id:

```
## CARD INDEX
(none)   | one line per card, in index order:
card_3f9a1c2b4d5e | rule | applied | <full text> | links: rule=- about=- | answer=- | last: utt_7c1d… by Sam | made by prop_0a4b…

## LAST PROPOSAL
(none) | prop_5d6e8f0a1b2c intent=amend op=card.update status=applied cards=card_3f9a1c2b4d5e from=utt_7c1d… rejectable=yes
## LAST REJECTABLE
(none) | (same as last proposal) | prop_… intent=add op=card.create status=applied cards=card_… from=utt_…

## PENDING CLARIFICATION
(none) | kind=choose_target proposal=prop_9e8d7c6b5a4f question="Which example do you mean: …"
candidates: 1. card_8b2e7d1a9c0f — <label> | 2. card_1a2b3c4d5e6f — <label>
pending_operations: [{"kind":"card.remove","card_id":"$choice","reason":"It's not what I meant."}]

## RECENT UTTERANCES (oldest first)
[utt_0b1c2d3e4f5a] Sam (me): Right, let's start with how cancellation works today.
[utt_2c3d4e5f6a7b] (typed): What counts as an appointment?

## NEW UTTERANCE
[utt_8d9e0f1a2b3c] Sam (me): Delete that example. It's not what I meant.
```
A speaker line prints `<label> (<lane>)` when a label was assigned, the lane alone (`(remote)` / `(me)`) when `speaker === null`, and `(typed)` for `lane === "manual"` regardless of label.

**Validation of the model output (`claude/validate.ts`).** `validateModelProposal(m, input, { model }): { ok: ClassifierProposal } | { fallback: string }`, in order:
1. **Structure → fallback** (a malformed answer is a provider failure): intent/op mismatch (I2) → `invalid:intent_op_mismatch`; `card.replace` with both/neither replacement forms → `invalid:replace_shape`; clarification/flag disagreement, `choose_target` with < 2 candidates or no `$choice`, `confirm_intent` with ≠ 1 operation or a `$choice` → `invalid:clarification_shape`; empty patch or both `text` and `text_append` → `invalid:patch`; `undo.steps < 1` → `invalid:undo_steps`; intent `none` with operations or a clarification → `invalid:none_shape`.
2. **Ids → clarification, never fallback, never invention.** A `rule_id`/`about_card_id` not in the index is set to null (rationale gains " (link dropped: unknown card)"). Any other unknown card id → `askTarget` over the up-to-`MAX_CANDIDATES` most recent non-story index cards of the kind the operation targets: ≥ 2 → `choose_target` with the unknown id replaced by `$choice` and question `I could not match that to a card. Which did you mean: (1) …?`; 1 → `confirm_intent`; 0 → `none` with `heard_intent` = the model's intent. `interpretation.reject.proposal_id` must be `last_rejectable.id` or an index card's `proposal_id`; anything else is not retargeted: the op is dropped and the proposal becomes `confirm_intent` "Did you mean to reject the last interpretation?" bound to `last_rejectable` when one exists, else `none`/`heard_intent: "reject"`. `confirm.card_ids` are filtered to index ids; empty is kept only under I4's act-review condition, otherwise `none`/`heard_intent: "confirm"`.
3. **resolves**: must name `pending_clarification.proposal_id` with `chosen_card_ids ⊆ candidates` (choose_target) or `[]`; otherwise `resolves` is dropped and, if the operations depended on the choice, the proposal becomes the `reask` proposal (§6.6).
4. **Confidence**: clamp to [0, 1], round to 2 dp; `< MIN_CONFIDENCE` on an actionable non-clarification → the §6.3 threshold wrap.
5. `target_card_ids` recomputed; `rationale` trimmed to `RATIONALE_MAX`, defaulted to "Classified by the model."; `heard_intent = null`.
6. Stamp `classifier: { provider: "claude", model: served.model, prompt_version: SYSTEM_PROMPT_VERSION, fallback_from: null, error: null }`, `source_utterance_ids`; `assertProposalInvariants`.

### 6.5 Refusals, errors, timeouts, fallback

```
try { res = await client.messages.create(params, { timeout: CLAUDE_TIMEOUT_MS, maxRetries: 1, signal }) }
catch (e) {
  if (e instanceof Anthropic.APIUserAbortError || signal?.aborted)  code = "aborted"      // FIRST: APIUserAbortError extends APIError
  else if (e instanceof Anthropic.AuthenticationError)              code = "auth"
  else if (e instanceof Anthropic.RateLimitError)                   code = "rate_limit"
  else if (e instanceof Anthropic.APIConnectionTimeoutError)        code = "timeout"      // before APIConnectionError
  else if (e instanceof Anthropic.APIConnectionError)               code = "connection"
  else if (e instanceof Anthropic.APIError)                         code = `api:${e.status ?? "?"}:${e.type ?? "unknown"}`
  else if (/authentication method|credential|api key/i.test(String(e?.message)))  code = "auth"   // plain Error when nothing is configured
  else                                                              code = "transport"
  return fallback(code, e.message)
}
if (res.stop_reason === "refusal")    return fallback(`refusal:${res.stop_details?.category ?? "unknown"}`, res.stop_details?.explanation ?? "")
if (res.stop_reason === "max_tokens") return fallback("stop:max_tokens", "")
text = res.content.find(b => b.type === "text")?.text;  if (text === undefined) return fallback("parse", "no text block in the reply")
try { m = FORMAT.parse(text) } catch (e) { return fallback("parse", e.message) }     // JSON + zod; off-enum values land here
v = validateModelProposal(m, input, { model: res.model });  if ("fallback" in v) return fallback(v.fallback, "")
errorKey = null;  return v.ok
```
`fallback(code, message)`: `p = await rules.classify(input)`; `p.classifier = { provider: "rules.v1", model: null, prompt_version: null, fallback_from: "claude", error: code }`; `p.rationale` gets the suffix ` (rules.v1 fallback: claude <code>)` within `RATIONALE_MAX`; invariants re-asserted. `onError({ code, message })` is called only when `code !== errorKey` (then `errorKey = code`), so the UI shows a banner once per distinct failure; the ledger carries the code on every fallback proposal. `aborted` (session closed) never calls `onError`. If the operator rules that `client.messages.parse()` must be used literally, the `try` wraps `parse()`, a thrown `AnthropicError` whose message starts "Failed to parse structured output" is coded `parse`, and refusals with partial text and `max_tokens` truncations are then reported as `parse` — the README must say so.

Latency: 20 s per attempt, `maxRetries: 1` → at most ~45 s per utterance before rules.v1 answers; the server answers the utterance POST before classification (§8.4), so no client waits on this. The session passes an `AbortSignal` that fires on close.

### 6.6 Clarification protocol (`clarification.ts`)

Decisions:
- **The classifier answers one clarification: the most recent open one the bridge can represent** (`ClassifierInput.pending_clarification`, §8.7). When a new utterance produces another clarification while one is open, the older one is *displaced*: it stays open in the ledger, the tray lists it where it can be answered or dismissed by click, and DoD check 3 blocks sign-off while any is open. Nothing is auto-dismissed.
- An **unrelated utterance leaves the clarification open**: classified normally with `resolves: null`; the pending clarification is passed again next time.
- **UI clicks never pass through the classifier.** A click goes to `POST …/clarifications/:cid/answer` and core applies the template itself with the asking classifier's stamp and the clicker as `actor`. A voice answer and a click have the same map outcome but different ledger shapes (click: `clarification.answered {candidate|yes}` + the resolved proposal in one batch; voice: `utterance.recorded` + `clarification.answered {text}` + a classifier proposal carrying `resolves_clarification_id`).
- **Stale answers.** Classification runs outside the write mutex for up to ~45 s. If a click answers or dismisses the clarification while a voice answer is in flight, the server discards the stale proposal and re-runs `classify()` for the same utterance with `pending_clarification: null` (§8.4 step 4c). The classifier is stateless, so the re-run is a plain second call.

**Answer parsing.** `parseAnswer(s1, pending, rest, s1Scores): Answer` with `Answer = choose { card_ids, how } | yes | no | dismiss { remainder } | reask | null` (`s1Scores` = the §6.3 group counts of the first sentence alone). Forms in order: (1) confirm_intent only: a bare confirm cue (F1/F2, ≤ 3 words: `yes`, `yes please`, `that is right`, `correct`, `do it`) → `yes`; a bare R1 negation → `no`. (2) dismissal: (i) `neither`, `none of them`, `none of those`, `not those`, `scrap that question`, `never mind`, bare or followed by a comma → `dismiss` with remainder = the rest after the comma and an optional `i meant`/`i mean`/`actually`, plus `rest`; (ii) sentence-initial `no|nope|neither` + remainder: remainder scoring ≥ 1 on an intent other than confirm/reject → `dismiss` with that remainder (no prefix reject); remainder scoring only on reject → `dismiss` with `null`; (iii) choose_target and a bare R1 negation → `dismiss` with `null`. (3) ordinal (choose_target): `the first (one)`, `first`, `number 1`, `option 1`, a bare digit … up to `fourth` → that candidate; `the latest/last/most recent one` → `candidates[0]`; `the earlier/older/previous one` → `candidates[1]` when exactly two; `both` (exactly two) / `all of them` → all (only meaningful for remove; otherwise the first is used and the rationale says so). (4) label (choose_target), answer-shaped only: remove filler (`one, ones, example, rule, question, card, first, second, that, this, please, the, it, i mean, i meant, yes, ok, okay`); 1–`ANSWER_MAX_TOKENS` content tokens remain; every `s1Scores` entry is 0; the unique candidate with the highest `matched / sentence tokens` ratio ≥ `ANSWER_MIN_RATIO` wins; a tie, a ratio below the bar, or an intent cue → `null`. (5) choose_target and a bare confirm cue → `reask`. (6) otherwise `null`.

**Resolution.** `applyChoice(ops, chosen, input)` replaces `$choice` with `chosen[0]` (`card.remove` → one op per chosen id; `interpretation.reject { "$choice" }` → `cards[chosen[0]].proposal_id`, or `{ none: "That card was made by a person, not by an interpretation; use Remove." }` when null). `resolveClarificationAnswer(pending, answer, input)`: `choose` → `{ intent: pending.intent, operations: applyChoice(…), confidence: 1, resolves: { proposal_id, chosen_card_ids, dismissed: false }, rationale: "You chose <label>.", classifier: pending.classifier, source_utterance_ids: [utterance.id, pending.asked_by_utterance_id] }`; `yes` → the same with `operations: pending.pending_operations`, `chosen_card_ids: []`; `no` / `dismiss(null)` → `{ intent: "none", heard_intent: pending.intent, operations: [], resolves: { …, dismissed: true }, confidence: 1, rationale: "Dismissed the question." }`; `dismiss(remainder)` → the remainder classified normally with `resolves { …, dismissed: true }` attached (its operations are independent of the dismissed clarification and must not cite it); `reask` → a non-clarifying `none` with `heard_intent: pending.intent`, `resolves: null`, rationale "Please say which one: first or second, or name it." (the existing clarification stays open; a second clarification would leave two open).

Engine contract (core vocabulary): the bridge turns a proposal with `resolves` into `clarification.answer { kind: "text" | "dismiss" }` on the clarification whose `proposal_id` matches, followed (for `dismissed: false`) by the resolved proposal(s), the first carrying `resolves_clarification_id`; core marks the clarification `answered` with `resolved_by_proposal_id`, or `dismissed`. Nothing is ever `superseded` at the proposal level.

## 7. The audio pipeline (`exmap/src/web/audio/`)

Browser TypeScript; React only under `react/`. Everything below `react/` is framework-free and unit-tested in vitest's node project with synthetic frames and fakes. Depends on `src/core/types.ts` for types only (`Utterance`, `Lane`, `TranscriptionProvider`). `[VERIFY]` marks facts the spike did not prove; each has a stated fallback.

### 7.0 Decisions at a glance

1. **Two capture lanes, each a state machine** (`idle → requesting → live → stopped | error`) over one `MediaStream` audio track. `remote` has two sources: `display` (`getDisplayMedia`, default) and `device` (a `getUserMedia` input such as BlackHole — the macOS/Linux fallback). `me` is always `device`. A stream with no audio track is an error with guidance, never a silent lane.
2. **One `AudioContext` at 16 kHz**, one `AudioWorkletNode` per lane framing mono PCM into 20 ms `Float32Array`s. VAD and segmentation are pure main-thread code; the worklet (`public/pcm-worklet.js`, plain JavaScript) only frames and forwards.
3. **One Whisper worker shared by both lanes**, one model in memory, one FIFO. Nothing is dropped; the backlog is a number on screen. The model loads only when a lane that needs it starts **and** the person has accepted the first-run download notice.
4. **Segment vs push providers.** `local-whisper` is a *segment* provider (the controller calls `transcribe(segment)`); `web-speech`, `manual`, `replay` are *push* providers (they emit drafts themselves and bypass VAD). Push providers' `transcribe()` rejects `NOT_SEGMENT_PROVIDER`; the controller never enqueues a segment for a lane whose provider is `null` or push-mode.
5. **Client-minted utterance ids** (`"utt_" + crypto.randomUUID()`), posted over HTTP; `409 DUPLICATE_ID` on a retry counts as success. Outcomes are classified by the response body's `reason`, never by status alone.
6. **Speaker is a label stamped at segment close** from the lane's current label; nothing is inferred; an unlabelled lane is ledgered with `speaker: null`.
7. **Hallucination gate** is a pure function of `(text, durationMs, peakRmsDb)` that only drops or keeps; dropped counts are a page diagnostic.
8. **Capture-only lane mode** (provider `null`) so a lane can run without a model (levels check; the e2e fake-mic test).
9. **Two consent gates, same shape**: the Whisper download and Web Speech each show a notice once and persist a flag; neither network path starts without Continue.
10. **Posting is decoupled from classification**: the server answers `201` on append (§8.4); up to three posts in flight; `timeoutMs` 15 s; a timed-out post that returns `DUPLICATE_ID` is a clean success.

### 7.1 Layout

```
src/web/audio/
  index.ts  types.ts  errors.ts  os.ts  speakers.ts  settings.ts  clock.ts  controller.ts
  lanes/captureLane.ts  lanes/constraints.ts  lanes/devices.ts  lanes/guidance.ts
  dsp/graph.ts  dsp/vad.ts  dsp/segmenter.ts  dsp/resample.ts  dsp/levels.ts
  providers/registry.ts  providers/localWhisper.ts  providers/whisper.worker.ts  providers/hallucination.ts
  providers/webSpeech.ts  providers/manual.ts  providers/replay.ts
  pipeline/transcriptionQueue.ts  pipeline/utteranceBuilder.ts  pipeline/postQueue.ts  pipeline/sink.ts
  react/useAudioController.ts  react/CaptureControls.tsx  react/LaneBadge.tsx  react/GuidancePanel.tsx  react/ConsentNotice.tsx
  react/DevicePicker.tsx  react/ModelProgress.tsx  react/LevelMeter.tsx  react/SpeakerPicker.tsx  react/ManualInput.tsx  react/ReplayControls.tsx
src/web/public/pcm-worklet.js            served at /pcm-worklet.js
src/web/public/replay/index.json         { fixtures: [{ name: "demo", file: "conversation.v1.json", title, utterances: 31, durationMs }] }
src/web/public/replay/conversation.v1.json
tests/fixtures/audio/mlk16k.f32  mlk16k.wav
```
`/ort/*` (the ORT wasm runtime) is served by the server from `node_modules/onnxruntime-web/dist` (§8.2) and proxied in dev; there is no copy step and no `public/ort/`.

### 7.2 Capture lanes

Types (`types.ts`): `CaptureLaneId = 'remote' | 'me'`; `LaneSource = { kind: 'display' } | { kind: 'device'; deviceId: string | null }`; `LaneState = 'idle' | 'requesting' | 'live' | 'stopped' | 'error'`; `StopReason = 'user' | 'ended_by_browser' | 'device_lost'`; `SignalState = 'unknown' | 'signal' | 'silent'`; `LaneError { code: LaneErrorCode; domName: string | null; message: string }`; `LaneView { id; state; source; error (iff error); stopReason (iff stopped); signal; trackLabel; segmentsClosed; startedAtMs }`. The meter level is not in `LaneView` (50×/s): it lives on `controller.levels`.

Constraints (`lanes/constraints.ts`): `REMOTE_DISPLAY_OPTIONS = { audio: true, video: true /* audio-only rejects in Chromium */, systemAudio: 'include', selfBrowserSurface: 'exclude', surfaceSwitching: 'include', monitorTypeSurfaces: 'include', preferCurrentTab: false }` (Chromium-only keys widened locally as `DisplayMediaOptionsEx` `[VERIFY lib.dom coverage in TS 5.9]`); `deviceConstraints(lane, deviceId)` = `{ audio: { echoCancellation/noiseSuppression/autoGainControl: true for 'me', false for a loopback device, channelCount: { ideal: 1 }, deviceId: { exact } when set }, video: false }`. Facts: `getDisplayMedia` needs transient activation and a secure context (`http://127.0.0.1:4317` is potentially trustworthy); **inside the Start click, the media request is called synchronously before any `await`**, and `graph.ensureContext()` (which awaits `resume()` and the once-per-context `addModule`) runs after the stream resolves. The returned stream has one video track and zero or one audio tracks (tab audio on every OS; system audio on Windows/ChromeOS; never for window sharing; detection is by the track, never by OS). Immediately after resolution the video tracks are stopped `[VERIFY in Chrome 141 that audio continues; fallback: keep the video track `enabled = false` and detached]`. `suppressLocalAudioPlayback` stays default so the user still hears the call.

Devices (`lanes/devices.ts`): `listAudioInputs(media)` (labels are empty until microphone permission was granted once → the picker shows "Allow microphone to list devices", which calls `getUserMedia({ audio: true })`, stops the tracks and lists again); `onDeviceChange(media, cb)`; `isDefault = deviceId === 'default'`; chosen ids persisted in `settings.deviceId[lane]`; a persisted id that no longer exists (`OverconstrainedError`) → clear the saved id, retry once without `deviceId`, then `DEVICE_UNAVAILABLE`. `MediaDevicesLike` (the subset `getUserMedia`, `getDisplayMedia`, `enumerateDevices`, `addEventListener`) is injected so unit tests pass a fake.

State machine (`lanes/captureLane.ts`): `CaptureLane { view; setSource(source) /* idle|stopped|error only, else LaneStateError */; start(); stop(reason?) /* total, idempotent */ }`.

| from | event | to | notes |
|---|---|---|---|
| idle / stopped / error | `start()` | requesting | error and stopReason cleared; the media request is made synchronously in this call |
| requesting | stream with an audio track | live | video tracks stopped; `await graph.ensureContext()`; `await graph.attach(lane, stream)`; `trackLabel`; `startedAtMs = clock.nowMs()` |
| requesting | stream with no audio track | error `NO_AUDIO_TRACK` | all tracks stopped (the sharing bar goes away); guidance opens with `no_audio_track` |
| requesting | promise rejected | error `<mapped code>` | guidance opens for `PERMISSION_DENIED` / `UNSUPPORTED` / `NO_DEVICE` |
| requesting | `ensureContext()` / `attach()` throws | error `AUDIO_CONTEXT_FAILED` / `WORKLET_LOAD_FAILED` | all tracks stopped |
| requesting | `stop()` | stopped `user` | a stream that arrives after `stop()` is stopped, never attached |
| live | `stop()` | stopped `user` | `graph.detach(lane)` → worklet flush → `segmenterFlush()`; tracks stopped |
| live | audio track `ended` | stopped `ended_by_browser` (display) / `device_lost` (device) | same teardown; badge text says which |
| live | track `mute` / `unmute` | live (`signal` → `silent` / `signal`) | |
| live | graph failure | error `AUDIO_CONTEXT_FAILED` / `WORKLET_LOAD_FAILED` | tracks stopped |
| idle / stopped / error | `stop()` | unchanged | no-op |

`start()` while `requesting`/`live` rejects `LaneStateError`; the controller sets a synchronous `starting[lane]` flag before its first `await` so a double-click never reaches the lane twice; source/provider/device controls are disabled while `requesting | live`.

Error codes (`errors.ts`): `LANE_ERROR = { PERMISSION_DENIED (NotAllowedError), NO_DEVICE (NotFoundError), DEVICE_BUSY (NotReadableError), DEVICE_UNAVAILABLE (OverconstrainedError after the retry), ABORTED, NOT_ACTIVATED (InvalidStateError), BAD_CONSTRAINTS (TypeError), INSECURE_CONTEXT (SecurityError or !isSecureContext), UNSUPPORTED (NotSupportedError or getDisplayMedia undefined), NO_AUDIO_TRACK, AUDIO_CONTEXT_FAILED, WORKLET_LOAD_FAILED, UNKNOWN }`; `mapDomException(e)` by `e.name`, message verbatim. The badge shows the human text; a details disclosure shows `domName` and `message` verbatim.

No-signal: a live lane whose frames stayed below −60 dBFS for 10 s sets `signal = 'silent'`; badge "Live — no sound heard"; not an error; guidance can be opened with `reason: 'silent'`; back to `signal` on the first frame above the onset threshold. It is the only per-frame-derived value published to the store, and only on change.

Guidance (`lanes/guidance.ts`): `guidanceFor(os: 'windows'|'macos'|'linux'|'other', lane, reason: 'no_audio_track'|'permission_denied'|'unsupported'|'silent'|'no_device'|'howto', source): { title; steps; alternatives; note }`; `detectOs()` from `navigator.userAgentData?.platform` falling back to UA regexes; `isChromium()`; non-Chromium browsers get `UNSUPPORTED` guidance up front ("Use Chrome or Edge: Firefox and Safari cannot share system or tab audio"). The exact copy (the snapshot test is the contract; the README's per-OS section is kept in step by hand):
- **remote / no_audio_track / Windows (display):** title "The shared screen had no audio". Steps: "Press Start again." · "In the share dialog choose **Entire screen** (not a window)." · "Tick **Share system audio** at the bottom-left, then Share." Alternatives: "Teams in a browser tab: choose **Chrome Tab**, pick the Teams tab, tick **Share tab audio**." Note: "Window sharing never carries audio in Chrome or Edge."
- **remote / no_audio_track / macOS (display):** title "Chrome on macOS cannot share system audio from the screen". Steps: "Open Teams in a Chrome tab (teams.microsoft.com) and join the call there." · "Press Start, choose **Chrome Tab**, pick the Teams tab and tick **Share tab audio**." Alternatives: "Teams desktop app: install a loopback driver (BlackHole 2ch), set it as Teams' speaker in Teams → Settings → Devices (or make a Multi-Output Device in Audio MIDI Setup so you still hear the call), then set exmap's **Call source** to *Audio device* and pick *BlackHole 2ch*." Note: "exmap only hears what reaches the shared tab or the loopback device."
- **remote / no_audio_track / Linux (display):** title "Screen sharing has no system audio on Linux". Steps: "Open Teams in a Chrome tab and join the call there." · "Press Start, choose **Chrome Tab**, pick the Teams tab and tick **Share tab audio**." Alternatives: "PulseAudio/PipeWire: set exmap's **Call source** to *Audio device* and pick the *Monitor of <your output>* device (create one with `pactl load-module module-null-sink sink_name=exmap` if none is listed)."
- **remote / no_audio_track / other:** the Linux text titled "The shared surface had no audio".
- **remote / permission_denied:** "Sharing was cancelled or blocked". Steps: "Press Start and choose a surface in the dialog." · "If no dialog appears, click the camera/screen icon in the address bar and allow screen capture for 127.0.0.1."
- **remote / silent:** "Live, but no sound for 10 s". Steps: "Check the shared tab is the one playing the call." · "Check Teams is not muted and the other side is talking." Device variant: "Check Teams' speaker is set to the loopback device."
- **me / permission_denied:** "Microphone access was denied". Step: "Click the microphone icon in the address bar, allow it for 127.0.0.1, then press Start." macOS adds "Also check System Settings → Privacy & Security → Microphone → Chrome."; Windows adds "Also check Settings → Privacy & security → Microphone."
- **me / no_device:** "No microphone found". Step: "Plug in or enable a microphone, then press Start." Linux adds "Check `pactl list sources short` lists an input."
- **howto:** the OS's no_audio_track text titled "How to capture the call on <OS>".
Every page says whether it applies to the Teams desktop app (system audio or a loopback device) or to Teams in a browser tab (tab audio; every OS).

### 7.3 Audio processing

`dsp/graph.ts`: `AudioGraph { ensureContext(); attach(lane, stream); detach(lane); sampleRate; dispose() }`. `new AudioContext({ sampleRate: 16000, latencyHint: 'playback' })` — Chromium resamples every `MediaStreamAudioSourceNode` to it `[VERIFY for display-capture tracks; mic tracks are known to work]`; on `NotSupportedError` a default-rate context is created and frames go through `resampleTo16k()` (one-pole low-pass at 7 kHz + linear interpolation; a fallback only). `ensureContext()` awaits `ctx.resume()`; still `'suspended'` → `AUDIO_CONTEXT_FAILED` "AudioContext did not resume — click Start again". `addModule('/pcm-worklet.js')` runs once per context (memoised; a rejection is `WORKLET_LOAD_FAILED` and the memo is cleared). Per lane: `MediaStreamAudioSourceNode → AudioWorkletNode(ctx, 'exmap-pcm-framer', { numberOfInputs: 1, numberOfOutputs: 0, channelCount: 1, channelCountMode: 'explicit', channelInterpretation: 'speakers' })` — stereo system audio is down-mixed to mono before `process()`; no output, so exmap never creates an echo path.

`public/pcm-worklet.js`: `registerProcessor('exmap-pcm-framer', …)`; accumulates 128-sample quanta into `FRAME = round(sampleRate × 0.02)` samples (320 at 16 kHz) and posts `{ type: 'frame', pcm }` with the buffer transferred; on `{ type: 'flush' }` posts the zero-padded partial frame and `{ type: 'flushed' }`; `process()` always returns true; zero-channel input posts nothing. Plain ES2022, no imports (the worklet globals are not in TS 5.9's libs).

VAD (`dsp/vad.ts`, pure): `FRAME_MS = 20`; `DEFAULT_VAD = { onsetMarginDb: 9, hangMarginDb: 6, absMinDb: -55, floorInitFrames: 10, floorDownAlpha: 0.2, floorUpAlpha: 0.005, floorMinDb: -70, floorMaxDb: -25, floorReseedMs: 3000 }`; `frameRms`, `rmsToDb(rms) = 20·log10(rms + 1e-9)`, `createVadState()` (floor = `floorMinDb`), `vadStep(state, rmsDb, cfg) → { state, speech, rmsDb }` with `speech = rmsDb > max(absMinDb, floorDb + (inSpeech ? hangMarginDb : onsetMarginDb))`. Floor rules: (1) seeding never raises the floor above `absMinDb − onsetMarginDb` (−64 dB) during the first `floorInitFrames` frames, so pressing Start mid-sentence detects speech on the first frame; (2) after seeding the floor updates only on non-speech frames (`alpha = rmsDb < floorDb ? floorDownAlpha : floorUpAlpha`), clamped to `[floorMinDb, floorMaxDb]`; (3) re-seed inside long "speech": if `speechFrames × 20 ≥ floorReseedMs` and `minInSpeechDb > floorDb + onsetMarginDb`, set `floorDb = clamp(minInSpeechDb)` and reset — so steady room noise or a Start pressed mid-speech cannot become one endless capped segment.

Segmenter (`dsp/segmenter.ts`, pure): `DEFAULT_SEGMENTER = { trailingSilenceMs: 600, hardCapMs: 15000, minSegmentMs: 200, preRollMs: 200, keepTailMs: 200 }`; `Segment { lane; seq (per lane from 1); startedAt; onsetAt; endedAt; speechMs; pcm (mono 16 kHz); sampleRate: 16000; peakRmsDb; cappedAt15s; speaker: string | null }`; `createSegmenter(lane)`, `segmenterStep(s, pcm, tMs, speaker, cfg, vad)`, `segmenterFlush(s, tMs, speaker)`. Rules per frame: (1) in `silence`: not speech → push into the 10-frame pre-roll ring; speech → `phase = 'speech'`, `frames = [...preRoll, frame]`, `onsetAt = tMs`, `startedAt = tMs − 20 × preRoll.length`; (2) in `speech`: append; speech frames update `lastSpeechAt` and `peakRmsDb`; (3) close on trailing silence when `tMs + 20 − lastSpeechAt ≥ 600`: trim silence beyond `keepTailMs`, `speechMs = lastSpeechAt + 20 − onsetAt`; `< minSegmentMs` → discard; else emit; the dropped silence is not carried into the next pre-roll; (4) close on the hard cap when `tMs + 20 − startedAt ≥ 15000`: emit with `cappedAt15s = true`, stay in `speech` with fresh buffers (no sample lost or duplicated; a word may be split); (5) `segmenterFlush` closes an in-speech phase as rule 3. `minSegmentMs` is 200 so a quick "Yes." reaches the classifier; the hallucination gate, not the segmenter, keeps near-silent blips out. A segment holds at most 960 KB.

Levels (`dsp/levels.ts`): `levelStep(prev, rmsDb) = max(prev × 0.85, clamp((rmsDb + 60) / 60, 0, 1))` into `controller.levels[lane]` (a mutable record outside the React snapshot), read by `LevelMeter` on `requestAnimationFrame`.

### 7.4 Transcription providers

```ts
export type ProviderId = TranscriptionProvider;   // aliased from core, never retyped
export type WireLane = Lane;
export interface UtteranceDraft { text; lane: WireLane; speaker: string | null; provider: ProviderId; model: string | null; isLocal: boolean; confidence: number | null; tStartMs: number; tEndMs: number }
export interface TranscribeResult { text: string; confidence?: number }
export interface ProviderContext { emit(draft); onInterim?(lane, text | null); onProgress?(p: ModelProgress); clock: SessionClock; speakers: SpeakerStore; signal: AbortSignal }
export interface TranscriptionProvider {
  readonly id: ProviderId; readonly label: string; readonly isLocal: boolean; readonly lanes: CaptureLaneId[]; readonly mode: 'segment' | 'push'; readonly model: string | null;
  start(ctx: ProviderContext): Promise<void>; transcribe(segment: Segment, opts?: { signal?: AbortSignal }): Promise<TranscribeResult>; stop(opts?: { force?: boolean }): Promise<void>;
}
export const PROVIDER_ERROR = { NOT_SEGMENT_PROVIDER, MODEL_LOAD_FAILED, TRANSCRIBE_FAILED, TRANSCRIBE_TIMEOUT, WEBGPU_UNAVAILABLE, WEB_SPEECH_UNSUPPORTED, WEB_SPEECH_NETWORK, WEB_SPEECH_DENIED, REPLAY_FIXTURE_INVALID, WORKER_CRASHED } as const;
```
Lane → provider is a setting: `settings.provider.remote ∈ {'local-whisper', null}`, `settings.provider.me ∈ {'local-whisper', 'web-speech', null}`; default `{ remote: 'local-whisper', me: 'local-whisper' }`. `manual` and `replay` have their own panels and are always started. `provider.start()` is called the first time a live lane needs it (after consent); `provider.stop()` only by `dispose()` and the automatic restart path — lane stop never touches the provider, so a backlog left by a stopped lane is still transcribed and posted.

**`local-whisper`.** Settings: `whisperModel: 'onnx-community/whisper-base.en' | 'onnx-community/whisper-tiny.en'` (default base.en), `whisperDtype: 'q8' | 'q4'` (default q8; `fp16` is not offered — WebGPU-only, no wasm kernels), `whisperDevice: 'auto' | 'wasm'` (default auto = probe the adapter, then try explicitly). Worker protocol: `WhisperIn = load { model, dtype, device, wasmPaths, numThreads } | transcribe { jobId, pcm } | dispose`; `WhisperOut = progress { data } (exactly transformers.js' status events initiate|download|progress|progress_total|done|ready) | ready { model, device: 'webgpu'|'wasm', threads, loadMs } | result { jobId, text, ms } | error { jobId | null, stage: 'load'|'transcribe'|'unhandled', name, message }`. Worker body: set `env.backends.onnx.wasm.wasmPaths = { mjs: '/ort/ort-wasm-simd-threaded.asyncify.mjs', wasm: '/ort/ort-wasm-simd-threaded.asyncify.wasm' }` **inside the worker** (env is per realm), `numThreads` when given; `device = (auto && navigator.gpu?.requestAdapter()) ? 'webgpu' : 'wasm'`; `pipeline('automatic-speech-recognition', model, { device, dtype, progress_callback })`, catching a webgpu failure and retrying `'wasm'` (files are cached by then); `ready` carries the device that actually loaded; every failure path posts an `error` message (an exception out of an async `onmessage` never reaches the main thread's `onerror`); `onunhandledrejection`/`onerror` post `stage: 'unhandled'`. No generation kwargs for `.en` models; no `chunk_length_s` (segments ≤ 15 s). `[VERIFY WebGPU inside a worker on Chrome 141; q8 on a real GPU — if slow, switch the webgpu attempt to { encoder_model: 'fp32', decoder_model_merged: 'q4' }]`. Main-thread `LocalWhisperProvider`: `start()` creates `new Worker(new URL('./whisper.worker.ts', import.meta.url), { type: 'module' })`, posts `load`, resolves on `ready`, rejects `MODEL_LOAD_FAILED` on a load/unhandled error or after `loadTimeoutMs` (10 min); `transcribe(segment)` posts one job and resolves on its `result`, rejects `TRANSCRIBE_FAILED` on an error with its `jobId` or `null`, `TRANSCRIBE_TIMEOUT` after `max(30 s, 10 × segment length)`; `stop()` waits for the in-flight job then disposes; `stop({ force: true })` terminates at once. A crash or timeout → one automatic forced restart (cached load ≈ 2 s); a second failure pauses the queue and offers Retry. Progress: `ModelProgress = { phase: 'downloading'|'loading_runtime'|'ready'|'error'; percent; loadedBytes; totalBytes; file; cached }` from `progress_total` (when it hits 100 before `ready`, phase `loading_runtime` — the 27 MB ORT wasm fetch is not reported). **Consent notice** before the first `load` of a model (`localStorage['exmap.audio.modelSeen.<model>']` unset): `ConsentNotice` (`data-testid="model-notice"`): "exmap will download ~77 MB (base.en) / ~44 MB (tiny.en) from huggingface.co once and keep it in the browser cache. Audio never leaves this machine." Continue (`model-notice-continue`) sets the flag and starts; Cancel (`model-notice-cancel`) leaves the lane live in capture-only mode (badge "Capture only (download declined)"). Sizes from `MODEL_INFO` (base.en q8 ≈ 77 MB, tiny.en q8 ≈ 44 MB, base.en q4 ≈ 143 MB), labelled "approx". Cache: Cache API `transformers-cache`; "Clear downloaded models" → `caches.delete('transformers-cache')` then restart. Threads: `numThreads = crossOriginIsolated ? min(4, hardwareConcurrency − 1) : null` (the server sends COOP/COEP by default).

**`web-speech`.** `SR = window.SpeechRecognition ?? window.webkitSpeechRecognition` (declared locally `[VERIFY lib.dom]`); absent → `WEB_SPEECH_UNSUPPORTED` and the option is disabled with the reason. `continuous`, `interimResults`, `maxAlternatives = 1`, `lang = settings.webSpeechLang` (default `navigator.language` if `en*`, else `'en-US'`). `isLocal: false`, `lanes: ['me']`, `mode: 'push'`. Label everywhere: "Web Speech (not local — audio goes to the browser vendor)". Consent notice (`webspeech-notice`) when first selected: "Web Speech sends audio from your microphone to the browser vendor's speech service while the lane is live. exmap stores nothing from it, but the audio does leave this machine." Continue keeps the selection; Cancel reverts. It captures the default microphone itself; the `me` lane still runs for the meter and the no-signal badge, its segments counted but never enqueued. `onresult`: interim → `onInterim('me', text)` and `interimStartedAt[i] ??= nowMs`; final → `emit({ text, lane: 'me', speaker: speakers.get('me'), provider: 'web-speech', model: null, isLocal: false, confidence: r[0].confidence > 0 ? round2 : null, tStartMs: interimStartedAt[i] ?? nowMs − 1000, tEndMs: nowMs })`. Restarts: `onend` while started → restart after 250 ms, clearing `interimStartedAt`; `not-allowed`/`service-not-allowed` → `WEB_SPEECH_DENIED`; `network` → `WEB_SPEECH_NETWORK` once, backoff 1 → 2 → 4 → 8 s; `no-speech`/`aborted` → silent restart; `audio-capture` → `WEB_SPEECH_DENIED` "no microphone". `start()` rejects `WEB_SPEECH_DENIED` "consent not given" without the flag.

**`manual`.** `ManualProvider.submit(text, lane: WireLane, speaker, tStartMs)`; `isLocal: true`, `model: null`, `confidence: null`. `ManualInput`: textarea (`manual-input`), lane select (`manual-lane`: Typed `manual` default / Me / Call), speaker field (`manual-speaker`, pre-filled from the lane's label; empty → `null`, placeholder = lane name), submit (`manual-submit`); Enter submits, Shift+Enter inserts a newline; `tStartMs` = first keystroke into an empty box, `tEndMs` = submit; empty text is not submittable.

**`replay`.** One fixture file, one shape, three readers (the provider; the e2e journey; the classifier's conversation test):
```ts
export interface ReplayFixture { version: 1; title: string; story?: string; speakers?: Partial<Record<'remote' | 'me', string>>; utterances: ReplayUtterance[]; ui?: unknown }
export interface ReplayUtterance { label?: string /* unique when present, e.g. "u05" */; atMs: number /* non-decreasing */; lane: WireLane; speaker: string | null; text: string; durationMs?: number; expect?: unknown /* opaque */ }
export function parseReplayFixture(json: unknown): ReplayFixture;   // ProviderError('REPLAY_FIXTURE_INVALID', '<index>: <field>: <why>'); tolerates exactly story/speakers/ui and label/expect; refuses any other unknown key
export type ReplaySpeed = 0.5 | 1 | 2 | 4 | 'instant';
export interface ReplayStatus { fixture: string | null; state: 'empty'|'ready'|'playing'|'paused'|'done'; index: number; total: number; speed: ReplaySpeed; until: number | null }
export class ReplayProvider implements TranscriptionProvider {
  load(fixture: ReplayFixture, name: string): void;
  play(speed: ReplaySpeed, opts?: { until?: number | string }): Promise<void>;   // resolves when the last utterance <= until has been EMITTED; until = 0-based index (inclusive) or label
  step(): void;  skip(until: number | string): void;  pause(): void;  resume(): void;  reset(): void;   // skip: advance past `until` without emitting
  get status(): ReplayStatus;
}
```
Timed mode: a `setTimeout` chain at `(atMs − prevAtMs) / speed` (timers injectable). Instant mode emits synchronously in order; the post queue still posts in order, so tests wait on `controller.idle()`. Breakpoints: `play('instant', { until: 'u30' })` emits through u30 then `paused`; `step()` emits one; `skip('u06')` advances without emitting (the journey's click-answer variant); an unknown label rejects `REPLAY_FIXTURE_INVALID`. Timing in the ledger is session-relative like every other provider: `playStartMs = clock.nowMs()` at the first `play()`; `tStartMs = playStartMs + (atMs − utterances[0].atMs)`, `tEndMs = tStartMs + (durationMs ?? 250 + 60 × wordCount)`; `provider: 'replay'`, `isLocal: true`, `model: null`, `confidence: null`; `speaker = utterance.speaker ?? speakers.get(lane)`. A custom fixture can be loaded from a file input (`replay-file`). URL hooks: `?replay=<name>&speed=<ReplaySpeed>&autostart=1` load the named fixture from `index.json` and (with `autostart`) press Play once the session is open; only on the session screen.

Registry (`providers/registry.ts`): `PROVIDERS: Record<ProviderId, { label; isLocal; lanes; mode }>`; `createProvider(id, settings, deps)` with injectable `createWorker` and `speechRecognitionCtor`. A server-side STT provider is the documented seam: a fifth `TranscriptionProvider` id in core first, a registry entry, `isLocal: false` if audio leaves the machine — not built.

### 7.5 Utterances to the server

The wire shape **is** core's `Utterance` (`UtteranceWire = Utterance`, re-exported, not retyped); segment duration is `t_end_ms − t_start_ms`, never a second field. `buildUtterance(draft, idFn)` = `{ id: 'utt_' + randomUUID(), text: trim, lane, speaker, provider, model, t_start_ms: max(0, round), t_end_ms: max(t_start_ms, round), is_local, confidence: null | round2(clamp) }`; throws `PostError('EMPTY_TEXT')` on empty text. Whisper segments: `tStartMs = segment.startedAt`, `tEndMs = segment.endedAt`, `model = settings.whisperModel`, `isLocal = true`, `confidence = null`. `SessionClock.nowMs() = max(0, round(Date.now() − Date.parse(session.created_at)))`.

`pipeline/sink.ts`: `UtteranceSink { post(u): Promise<PostOutcome> }`; `PostOutcome = { ok: true; eventId; duplicate } | { ok: false; kind: 'refused'; status; reason; detail } | { ok: false; kind: 'transient'; status | null; message }`; `HttpUtteranceSink({ baseUrl, sessionId, fetch?, timeoutMs? /* 15 000 */ })` posts `POST /api/sessions/{id}/utterances` with `AbortSignal.timeout`. Mapping by the body: `201` → ok; `409` with `reason === 'DUPLICATE_ID'` → ok, `duplicate: true`, `eventId` from `body.event.id` (a retry after a timeout lands here; no toast); any other 4xx except 408/429 (every other 409, 400, 403, 404, 422) → `refused` with `body.reason` (or `HTTP_<status>`) and `detail`, never retried; 408, 429, 5xx, a non-JSON 2xx body, network error, `AbortError` → `transient`. The server processes a client-aborted request to completion, which is why a timeout is followed by `DUPLICATE_ID`, not a lost utterance.

`pipeline/transcriptionQueue.ts`: `TranscriptionQueue({ provider(lane), onText, onError, onChange })` — `enqueue(segment)` returns `false` without queueing when the lane's provider is `null` or push-mode; FIFO across lanes; one in flight with the queue's own `AbortSignal`; a rejection pauses the queue, asks the controller to restart the provider once and retries the same segment once; a second failure sets it aside in `failed[]` (Retry button → `retryFailed()`); `Backlog = { segmentsWaiting; segmentInFlight; speechWaitingMs; oldestWaitingMs; failed; utterancesUnsent; postRetries; droppedAsHallucination }`. The UI shows "Transcription is N segments (≈ M s of speech) behind" from `segmentsWaiting ≥ 3`, suggesting tiny.en at ≥ 10. `beforeunload` is intercepted while `pendingWork() > 0`. `pendingWork() = segmentsWaiting + inFlight + failed + utterancesUnsent`, exposed on the controller and `window.__exmap.audio` so the Review drawer can refuse to treat the map as final while speech is still on its way (§10.6).

`pipeline/postQueue.ts`: FIFO, `maxInFlight = 3`; retry on `transient` with backoff 0.5 → 1 → 2 → 4 → 8 s (cap, indefinitely while the page is open); `lastError` (`scope: 'post'`) after three consecutive transient failures of one utterance, never for a timeout resolving as `duplicate`; `refused` → surfaced once with the server's reason, moved to `refused[]` (visible with the reason), never retried. Utterances are posted in production order; the ledger's `t_start_ms` carries the true order and the transcript sorts by it.

Hallucination gate (`providers/hallucination.ts`): `isLikelyHallucination(text, { durationMs: segment.endedAt − segment.startedAt, peakRmsDb })` drops a transcript that is empty after stripping punctuation/whitespace/brackets; bracket-only (`[music]`, `(applause)`, `♪`); a single token repeated ≥ 5 times with nothing else; or whose normalised form is in `KNOWN_HALLUCINATIONS = { thank you, thanks for watching, thank you for watching, thank you so much, subtitles by the amara org community, the end, blank audio }` **and** `peakRmsDb < −35` **and** `durationMs < 1000`. Single words (`okay`, `yes`, `you`, `bye`) are never in the table — "Okay." and "Yes." are Confirm cues. Nothing is ever rewritten. Dropped count → the page-diagnostics line; the README names the filter.

### 7.6 Speaker labels (`speakers.ts`)

`SpeakerStore({ userName, storage })`: `get(lane)` (`'manual'` → the `me` label; `null` until a person set one), `set(lane: 'me' | 'remote', label | null)` (trims; empty → null; a committed remote name joins `remoteKnown`, deduped, max 20), `labels`, `subscribe`. `me` starts as `settings.user_name` when set (person-set), else `null`; `remote` starts `null`. The lane names "Call"/"Me" are display text only and never written into `speaker`. `SpeakerPicker` (remote): chips for `remoteKnown` + a text input committing on Enter or blur (never per keystroke); subsequent segments are stamped at close time; "clear" sets `null`; names remembered in `sessionStorage['exmap.speakers.remoteKnown']`, the `me` label in `localStorage['exmap.speakers.me']`. Copy under the picker: "exmap does not detect who is speaking. The label is whatever you set here, and it is recorded as such. Until you set one, utterances are recorded with no speaker."

### 7.7 Controller and components

```ts
export interface AudioSettings { provider: { remote: 'local-whisper' | null; me: 'local-whisper' | 'web-speech' | null }; remoteSource: LaneSource; deviceId: { me: string | null; remote: string | null };
                                 whisperModel: WhisperModelId; whisperDtype: WhisperDtype; whisperDevice: 'auto' | 'wasm'; webSpeechLang: string }
export interface ModelStatus { state: 'idle'|'awaiting_consent'|'loading'|'ready'|'error'; progress: ModelProgress | null; device: 'webgpu'|'wasm'|null; threads: number | null; model: WhisperModelId | null; error: ProviderError | null; restarts: number }
export interface AudioState { lanes: Record<CaptureLaneId, LaneView>; model: ModelStatus; backlog: Backlog; speakers: SpeakerLabels; settings: AudioSettings; interim: { me: string | null };
                              replay: ReplayStatus; guidance: { lane; reason } | null; notice: { kind: 'model'; model; lane } | { kind: 'webspeech'; previous } | null;
                              lastError: { scope: 'lane'|'provider'|'post'; code: string; message: string; at: number } | null }
export class AudioController {
  constructor(deps: { sink: UtteranceSink; clock: SessionClock; speakers: SpeakerStore; media?; graph?; providers?; storage?; autostartRequested?: boolean });
  getState(): AudioState; subscribe(fn): () => void;  readonly levels: Record<CaptureLaneId, number>;
  startLane(lane); stopLane(lane); updateSettings(patch) /* persisted to localStorage['exmap.audio.v1']; refused for a requesting|live lane */; setSpeaker(lane, label);
  acceptNotice(); cancelNotice(); submitManual(text, lane, speaker);
  loadReplay(fixture, name); playReplay(speed, opts?: { until? }); stepReplay(); skipReplay(until); pauseReplay(); resetReplay();
  openGuidance(lane, reason); closeGuidance(); retryFailedSegments(); pendingWork(): number; idle(): Promise<void>; dispose(): void;
}
export function useAudioController(c: AudioController): AudioState;   // useSyncExternalStore
```
`startLane(lane)`: (1) if `starting[lane]` or the lane is `requesting|live` → return; set `starting[lane]`; (2) `await lane.start()` (media request synchronous inside; graph after); anything but `live` ends here; (3) if `settings.provider[lane] === 'local-whisper'` and the model is not ready/loading: no consent flag → `notice = { kind: 'model', … }`, `model.state = 'awaiting_consent'` and stop (the lane is live and its segments queue meanwhile); else `provider.start()`; (4) `web-speech` → `provider.start()`; (5) clear `starting`. `stopLane` = `lane.stop('user')` → `segmenterFlush` → the flushed segment is enqueued; it never touches providers or queues. `idle()` resolves when the post queue is empty, the transcription queue is empty, the replay (if loaded) is not `playing`, and — when `autostartRequested` — `replay.state === 'done'`.

Components (props; `data-testid`s are the e2e contract): `CaptureControls` renders per lane `LaneBadge` (`lane-<id>-badge`, `data-state`, `data-error-code`; text Idle / "Requesting…" / Live / "Live — no sound heard" / "Stopped" / "Stopped — sharing ended from the browser bar" / "Stopped — device lost" / "Error: <text>"; and `lane-<id>-provider-badge` "Whisper (local)" / "Web Speech (not local)" / "Capture only" / "Capture only (download declined)"; both `aria-live="polite"` with an `aria-label` naming the lane), Start/Stop (`lane-<id>-start` / `lane-<id>-stop`), provider select (`provider-select-<id>`, options from `PROVIDERS` + "Capture only (test audio)", disabled while requesting/live with title "Stop the lane to change this"), `remote-source` toggle, `DevicePicker` (`device-select-<id>`), `LevelMeter` (`level-<id>`, `role="meter"`, `aria-label="Call level"` / `"Microphone level"`, `aria-valuemin/max/now`; writes the DOM via a ref on its own animation frame), `SpeakerPicker` (`speaker-remote`) / `speaker-me`; below: `model-select` (base.en / tiny.en with approx sizes), `dtype-select` (q8 / q4), `ModelProgress` (`model-progress`, `<progress aria-label="Model download">`, phase text "Waiting for your OK to download" / "Downloading base.en 37 % (28 of 77 MB)" / "Loading runtime…" / "Ready · wasm · 3 threads"), "Clear downloaded models", backlog line (`backlog-count`: "0 waiting" or "3 waiting · 1 transcribing · 2 unsent · 1 could not be transcribed [Retry]"), `backlog-diagnostics` ("this page: …" — dropped-as-hallucination and post-retry counts, never read as ledger numbers), "Setup help" (`guidance-open`). `ConsentNotice` (`model-notice` / `webspeech-notice`, `role="dialog"`, `aria-modal`, focus on Continue, Escape = Cancel, buttons `<id>-continue` / `<id>-cancel`). `GuidancePanel` (`guidance-panel`, `role="dialog"`, `data-os`, `data-reason`). `ManualInput` (§7.4). `ReplayControls` (`replay-select`, `replay-file`, `replay-speed`, `replay-play`, `replay-step`, `replay-pause`, `replay-reset`, `replay-status` "12 / 31").

Test hooks: when `import.meta.env.DEV` or `location.search` contains `testhooks=1`, `main.tsx` sets `window.__exmap = { audio: { state(), postQueueIdle() /* controller.idle() */, segmentsClosed(), pendingWork() }, replay: { playUntil(label | index), skip(label | index), playAll(), position } }`. Production builds without the flag expose nothing, so every e2e URL carries `testhooks=1`.

What Playwright can drive: `getDisplayMedia` is not available headless — the remote-lane e2e asserts a transition into `error` with `data-error-code ∈ {NO_AUDIO_TRACK, PERMISSION_DENIED, UNSUPPORTED, NOT_ACTIVATED}` and the Linux guidance (`[VERIFY: try --auto-select-desktop-capture-source="Entire screen" first; keep whichever branch headless Chrome 141 takes]`); the mic lane is fully drivable with `--use-fake-ui-for-media-stream --use-fake-device-for-media-stream --use-file-for-fake-audio-capture=<abs>/tests/fixtures/audio/mlk16k.wav%noloop --autoplay-policy=no-user-gesture-required` and `permissions: ['microphone']` (`[VERIFY %noloop; without it the silent-badge assertion is dropped]`); everything that posts utterances is driven through replay and manual; the Whisper path is never exercised in e2e (`scripts/whisper-check.mjs` is a manual headed run).

## 8. Server: HTTP + WebSocket API (`exmap/src/server/`, Fastify 5)

### 8.0 Decisions at a glance

1. **The server is the only writer.** Every state change is `engine.apply()` → one fsynced append of the whole batch → broadcast over the session WebSocket. The browser never hashes a new event into existence; it reduces what the server appended and verifies each pushed event's hash with the same `canonicalJson`.
2. **Human acts are proposals with `classifier.provider = "human"`** and `actor` set. Accept = `confirm` of a content proposal's live cards, or of the act itself for removals / undos / rejects (`confirm { proposal_ids }`); Reject = `interpretation.reject`; a UI edit = `card.update`; "mark reviewed" = one `confirm` listing every card it covers; Undo = `undo`. Nothing a person does is unevented.
3. **Utterances are recorded first, answered at once, classified second, in order.** `POST …/utterances` appends `utterance.recorded` under the session's write mutex, enqueues the classification job in the same mutex-held section, and replies `201` immediately. The job runs on the session's serial classification chain without holding the mutex (a 20–45 s Claude call must not block Accept/Reject), then applies the proposals and one `classification.record` under the mutex. The outcome reaches every client as ledger events over the WebSocket. `?wait=1` (tests and tooling) makes the reply wait for the outcome.
4. **The bridge** (`classifier-bridge.ts`, §8.7) owns the seam between `ClassifierProposal` and core's `Proposal`: a pure, tested mapping in one file.
5. **Persistence is crb's discipline in Node** (§9): `events.jsonl`, one canonical-JSON line per event, one `writeSync` + `fsyncSync` per batch with truncation back to the pre-write length on failure, a per-session mutex, one `server.lock` per `EXMAP_HOME`.
6. **Export options are ledger events** (`export.options_set`); there is no side file.
7. **Web bundle by Vite; server by `tsc`**, run as plain `node dist/server/server/main.js`. The launcher never transpiles at start.
8. **COOP/COEP on by default** (`Cross-Origin-Opener-Policy: same-origin`, `Cross-Origin-Embedder-Policy: require-corp`), harmless for the Hub fetches and worth 25–30 % Whisper throughput; `EXMAP_COOP=0` turns it off.

### 8.1 Layout and options

```
main.ts   startServer(opts) / CLI entry (reads env; prints exactly one line `exmap listening on http://127.0.0.1:<port>`)
app.ts    buildApp(opts): FastifyInstance & { exmap: { store: SessionStore; config: ServerConfig } } — plugins, hooks, routes, static
config.ts ServerConfig from env + opts; classifierSelection() for /api/config
home.ts   ExmapHome: paths, settings.json (atomic write), server.lock acquire/complete/release
ledger.ts JsonlLedger: readAll(), appendBatch()         mutex.ts  Mutex (promise chain)
ids.ts    nextId(prefix), newSessionId(), isSessionId()   hash.ts   sha256 (node:crypto) pinned to the §5 vectors
session.ts        Session: state, events, run(command), classify(utteranceId), subscribers, AbortController, broken flag
session-store.ts  SessionStore: create / list / open (cached) / summaryOf; broken-ledger reporting
classifier-bridge.ts  buildClassifierInput(), toCoreCommands(), intentOf()
errors.ts         HttpError, refusalStatus(), reply helpers
routes/meta.ts  routes/sessions.ts  routes/utterances.ts  routes/acts.ts  routes/export.ts  routes/stream.ts
static.ts         dist/web at /, the ORT runtime files at /ort/; resolveOrtDir()
```
```ts
export interface AppOptions {
  home: string; port?: number; host?: "127.0.0.1"; coop?: boolean;        // default coop true
  webDist?: string | null; ortDir?: string | null;                        // null = not served (tests, dev)
  dev?: boolean;                                                           // EXMAP_DEV=1: also accept the Vite origin/host
  classifier?: Classifier;                                               // injected fake in tests; default createClassifier({ env, onError })
  env?: NodeJS.ProcessEnv; now?: () => IsoTimestamp; nextId?: ApplyContext["nextId"]; logger?: boolean;
}
export async function buildApp(opts: AppOptions): Promise<FastifyInstance & { exmap: { store: SessionStore; config: ServerConfig } }>;
export async function startServer(opts: AppOptions): Promise<{ app: FastifyInstance; url: string; port: number; close(): Promise<void> }>;
```
`buildApp` does not take `server.lock`; `startServer` does (before `listen`) and completes it with the real port after. Fastify: `bodyLimit: 1 MiB`, JSON body parser only, `trustProxy: false`. The server's `ids.nextId` is the one `ApplyContext["nextId"]` passed to core and to the routes. Per `Session`: a write `Mutex`, a serial classification chain, one `AbortController` (`classify()` passes `{ signal }`; `close()` aborts it — the claude provider reports `aborted` without calling `onError`), and `broken: LedgerReadError | LedgerWriteError | null`.

### 8.2 Cross-cutting rules

- **Loopback only.** `listen({ host: "127.0.0.1", port })`. An `onRequest` hook rejects any request whose `Host` is not `127.0.0.1:<p>`, `localhost:<p>` or `[::1]:<p>` with `403 { ok: false, reason: "FORBIDDEN_HOST" }`, where `p = app.server.address()?.port ?? opts.port` (lazy, so `--port 0` works); `dev: true` also accepts `127.0.0.1:5173` / `localhost:5173`. WebSocket upgrades additionally require an `Origin` of `http://127.0.0.1:<p>` / `http://localhost:<p>` (plus the Vite origin under `dev`) → else close 4003. No CORS headers are ever sent.
- **Headers.** `Cache-Control: no-store` on `/api/*`; COOP/COEP on everything when `coop`; `X-Content-Type-Options: nosniff`.
- **Static.** `@fastify/static` root `webDist` at `/` (`index: ["index.html"]`, `wildcard: true`) when non-null; a second registration `prefix: "/ort/"`, root `ortDir`, `decorateReply: false`, `allowedPath: p => /^\/ort-wasm-simd-threaded\.asyncify\.(mjs|wasm)$/.test(p)` (exactly the two runtime files transformers.js 4.3.1 loads; `.wasm` → `application/wasm`, `.mjs` → `text/javascript`). `resolveOrtDir(root) = dirname(require.resolve("onnxruntime-web/ort-wasm-simd-threaded.asyncify.wasm", { paths: [root] }))` (the runtime files are exported subpaths; `onnxruntime-web/package.json` is not). `startServer` refuses with `ORT_RUNTIME_MISSING` naming the path when either file is absent. `GET /` with `webDist` null → `503 text/plain "exmap: no web build; run npm run build, or npm run dev and open http://127.0.0.1:5173"`.
- **Session ids** are `ses_<base36 ms>_<6 hex>` (`newSessionId()`), validated by `/^ses_[a-z0-9]{6,12}_[a-f0-9]{6}$/` on every `:id` before any filesystem access → `400 INVALID_SESSION_ID`. Other ids: `nextId(prefix) = `${prefix}_${randomUUID().replaceAll("-", "").slice(0, 12)}``.
- **Actor.** Every human act carries `actor: string` (1–80 chars after trim) → `400 ACTOR_REQUIRED` otherwise. The one exception is `POST …/signoff`, whose body names `reviewer` (the person vouching; the sign-off record is the audit). The UI fills `actor` from `settings.user_name` and refuses to act until a name is set. It is stamped into `ClassifierStamp.actor`, `clarification.answered.actor`, `question.accepted_outstanding.by`, `export.options_set.options.by`.
- **Error body** is always `ErrorBody` (§4). Status by reason (`refusalStatus`):

| status | reasons |
|---|---|
| 400 | `BAD_REQUEST` (zod `issues`; **422 on `POST …/utterances`**, §8.4), `INVALID_SESSION_ID`, `ACTOR_REQUIRED`, `REASON_REQUIRED`, `SIGNOFF_REVIEWER_REQUIRED`, `SIGNOFF_CONFIRMATION_TEXT_MISMATCH`, `CHECK_NOT_MARKABLE`, `CLASS_UNKNOWN`, `EXPORT_FILE_UNKNOWN` |
| 403 | `FORBIDDEN_HOST`, `FORBIDDEN_ORIGIN` |
| 404 | `SESSION_NOT_FOUND`, `CARD_NOT_FOUND`, `PROPOSAL_NOT_FOUND`, `CLARIFICATION_NOT_FOUND`, `UTTERANCE_UNKNOWN` |
| 409 | `DUPLICATE_ID`, `CARD_NOT_LIVE`, `STORY_ALREADY_EXISTS`, `NO_CHANGE`, `NOTHING_TO_CONFIRM`, `PROPOSAL_NOT_CONFIRMABLE`, `PROPOSAL_NOT_REJECTABLE`, `PROPOSAL_KIND_NOT_REJECTABLE`, `REJECT_NOT_LATEST`, `REPLACEMENT_INVALID`, `UNDO_NO_EARLIER_REVISION`, `UNDO_TARGET_OUT_OF_RANGE`, `UNDO_TARGET_IS_CURRENT`, `CLARIFICATION_NOT_ANSWERABLE`, `CLARIFICATION_NOT_AWAITING_PROPOSAL`, `CLARIFICATION_NO_TEMPLATE`, `CLARIFICATION_NO_OPERATION`, `QUESTION_ALREADY_RESOLVED`, `SIGNOFF_STALE_REVISION`, `SIGNOFF_ALREADY_ACTIVE`, `LEDGER_BROKEN`, `META_INVALID` |
| 422 | `BAD_SHAPE`, `EMPTY_TEXT`, `INVALID_TIMING`, `INVALID_ENUM`, `INVALID_CONFIDENCE`, `INVALID_DEFINITION`, `INTENT_OPERATION_MISMATCH`, `KIND_MISMATCH`, `LINK_KIND_MISMATCH`, `PATCH_EMPTY`, `PATCH_FIELD_NOT_ALLOWED`, `EMPTY_TARGET`, `CLARIFICATION_QUESTION_REQUIRED`, `CLARIFICATION_SHAPE`, `CLASSIFICATION_PROPOSAL_MISMATCH`, `SIGNOFF_DOD_FAILED` (+`checks`), `NOT_HUMAN_VERIFIED` (+`checks`, `signoff`) |
| 500 | `LEDGER_WRITE_FAILED`, `INTERNAL`, `ORT_RUNTIME_MISSING` (startup only) |

Core refusal codes pass through unchanged (`reason = ApplyResult.reason`, `detail` verbatim). Success bodies always carry `ok: true`.

### 8.3 Meta and session routes

| route | request | response |
|---|---|---|
| `GET /api/health` | — | `200 { app: "exmap", version: "0.1.0", pid }` — the launcher's reuse probe |
| `GET /api/config` | — | `200 ConfigResponse`. `classifier.reason` ∈ `"EXMAP_CLASSIFIER=claude"`, `"EXMAP_CLASSIFIER=rules.v1"`, `"ANTHROPIC_API_KEY is set"`, `"ANTHROPIC_AUTH_TOKEN is set"`, `"no model configured; using the offline rules classifier"`; `model` = `CLAUDE_MODEL` when the provider is claude (the UI renders it; no model literal lives in `src/web`); **never the key** (built from booleans; a test asserts the serialised body does not contain the env value). `last_error` = the most recent `onError` from the claude provider, kept in memory, **cleared when a classification is ledgered with `provider === "claude"` and `fallback_from === null`** |
| `GET /api/settings` | — | `200 { user_name: string }` (`""` until set) |
| `PUT /api/settings` | `{ user_name: string }` (trim, ≤ 80) | `200 { user_name }`; written atomically to `<home>/settings.json` |
| `GET /api/catalogue` | — | `200` the vendored `crb-catalogue.json` verbatim |
| `GET /api/sessions` | — | `200 { sessions: SessionSummary[] }`, newest first. A broken session is listed with `broken` and a summary computed from the readable prefix (events before the bad row / `slice(0, seq − 1)` replayed; never cached as open, never written to) |
| `POST /api/sessions` | `{ title: string (1–120), actor?: string, story?: string }` | `201 { session: SessionSummary }`. Creates `sessions/<id>/`, `meta.json`, an empty `events.jsonl`. With `story`, `actor` is required and one human proposal `card.create { kind: "story", text }` is applied |
| `GET /api/sessions/:id` | — | `200 { session: SessionSummary, dod: DodReport, signoff: Signoff \| null, export_options: ExportOptions \| null }` or `404` / `409 LEDGER_BROKEN { row, seq, code }` |
| `GET /api/sessions/:id/events?after=0&limit=2000` | — | `200 { events: ExmapEvent[], head, has_more }` — events with `seq > after`, at most `limit` (cap 5000) |
| `GET /api/sessions/:id/state` | — | `200 { state: MapState }` with `revisions[].snapshot` omitted (tooling; the UI does not use it) |

`meta.json` = `SessionMeta` (immutable after creation). The audio clock uses `created_at`.

### 8.4 Utterances

`POST /api/sessions/:id/utterances[?wait=1]` — body validated by
```ts
export const UtteranceWireSchema = z.object({
  id: z.string().regex(/^utt_[0-9a-f-]{8,40}$/),
  text: z.string(), lane: z.enum(["remote", "me", "manual"]), speaker: z.string().nullable(),
  provider: z.enum(["local-whisper", "web-speech", "manual", "replay"]), model: z.string().nullable(),
  t_start_ms: z.number().int().nonnegative(), t_end_ms: z.number().int().nonnegative(),
  is_local: z.boolean(), confidence: z.number().min(0).max(1).nullable(),
}).strict();
```
1. Validate. A zod failure **on this route only** is `422 { reason: "BAD_REQUEST", detail, issues }` (a client bug of the same class as `EMPTY_TEXT`; the sink files it under `refused`, never retries).
2. Under the write mutex, in one section: `run({ kind: "utterance.record", utterance })`; on success enqueue `session.classify(utterance.id)` on the serial classification chain *before releasing the mutex* (two concurrent POSTs A then B are classified in recorded order by construction). `DUPLICATE_ID` → `409 { ok: false, reason: "DUPLICATE_ID", detail, event: <the existing utterance.recorded's { id, seq, hash }> }` (the client treats it as success; nothing is enqueued). Other refusals → 422. `session.broken` → `409 LEDGER_BROKEN`.
3. Reply **201 now** (without `wait`): `{ ok: true, event: { id, seq, hash } }`.
4. The classification job (serial per session, outside the write mutex, with the session's `signal`):
   a. `input = buildClassifierInput(session, utterance)` (§8.7).
   b. `p = await classifier.classify(input, { signal })`. A thrown `ClassifierError` or an abort → `error = { code, message }`, `cmds = []`.
   c. **Stale-answer guard**: if `p.resolves` names a clarification that is no longer `open`, discard `p`, re-run `classify()` once with `pending_clarification: null`, continue with that result (the stale proposal is never ledgered).
   d. `cmds = toCoreCommands(p, session.state, utterance, ctx)`; under the write mutex run each in order; a refusal is collected into `refused[]` as `{ operation, reason, detail }` and does not stop the remaining commands.
   e. Under the write mutex: `run({ kind: "classification.record", utterance_id, intent: p.intent, heard_intent: p.heard_intent, classifier: { ...p.classifier, actor: null }, confidence: p.confidence, rationale: p.rationale, proposal_ids: <ids of the proposals core applied or asked in this run>, refused, error })` — always, including `none`, a thrown classifier and an all-refused run.
   f. If `p.classifier.provider === "claude" && fallback_from === null`, clear `config.classifier.last_error`.
5. With `?wait=1` the handler awaits the job and adds `classification: ClassificationSummary` to `UtterancePostResponse`. The job's completion promise never rejects.

A client may have up to three posts in flight; a client-aborted request is still processed to completion, so a retry gets `409 DUPLICATE_ID` with `event`.

### 8.5 Human acts (`routes/acts.ts`)

All bodies include `actor` (except sign-off). All succeed with `200 ActResponse` (the full appended batch, including any `signoff.invalidated`). Human proposals are built by `humanProposal(intent, operation, actor, rationale)`: `{ id: nextId("prop"), intent, operation, template: null, pending_operation: null, candidates: [], confidence: 1, needs_clarification: false, question: null, source_utterance_ids: [], classifier: { provider: "human", model: null, prompt_version: null, fallback_from: null, error: null, actor }, resolves_clarification_id: null, rationale }` submitted as `{ kind: "proposal.propose", proposals: [p] }`; `intent = intentOf(operation.kind)`.

| route | body | command(s) | notes |
|---|---|---|---|
| `POST …/proposals/:pid/accept` | `{ actor }` | kind `card.remove` / `undo` / `interpretation.reject` → `confirm { card_ids: [], proposal_ids: [pid] }`; any other kind → `confirm { card_ids: affected_card_ids.filter(live), proposal_ids: [] }`; rationale `"accepted by <actor>"` | unknown pid → 404; a content proposal with no live affected card → `409 NOTHING_TO_CONFIRM`; a `confirm`-kind proposal → `409 PROPOSAL_NOT_CONFIRMABLE` (the UI never offers Accept there) |
| `POST …/proposals/:pid/reject` | `{ actor }` | `interpretation.reject { proposal_id: pid }` | core refusals pass through (409) |
| `POST …/clarifications/:cid/answer[?wait=1]` | `{ actor, answer }` with `answer` ∈ `{ kind: "candidate", card_id }` / `{ kind: "yes" }` / `{ kind: "dismiss", reason }` / `{ kind: "text", text }` (no `utterance_id`; the server mints it) | `candidate` / `yes` / `dismiss` → `clarification.answer { clarification_id: cid, answer, actor }` as-is (core builds the resolved proposal). `text` → in one mutex section: `utterance.record` of a manual utterance `{ id: nextId("utt"), text, lane: "manual", speaker: actor, provider: "manual", model: null, t_start_ms = t_end_ms = <session ms now>, is_local: true, confidence: null }`, then `clarification.answer { kind: "text", text, utterance_id, actor }` (the clarification stays open), then enqueue `classify(utt.id)` exactly as §8.4 step 2. Reply `201 { ok, events: [both batches], utterance_id }` at once; `?wait=1` adds `classification` and `resolved: boolean` (true iff a proposal of that run cites `cid`). If nothing resolves it, nothing else happens | `CLARIFICATION_NOT_ANSWERABLE` (409) when dismissed or resolved; `CLARIFICATION_NO_TEMPLATE` / `CLARIFICATION_NO_OPERATION` (409) |
| `POST …/cards` | `{ actor, card: NewCard }` | `card.create` (human) | adds a story after a removal, or a card by hand |
| `POST …/cards/:cardId/confirm` | `{ actor }` | `confirm { card_ids: [cardId], proposal_ids: [] }` | |
| `POST …/cards/:cardId/remove` | `{ actor }` | `card.remove { card_id }` | a human removal has `actor` set, so check 3 does not list it |
| `POST …/cards/:cardId/update` | `{ actor, patch: CardPatch }` | `card.update { card_id, patch }` | also how an unattached example is linked and a question answered by hand |
| `POST …/questions/:id/accept-outstanding` | `{ actor, reason }` | `question.accept { question_id, by: actor, reason }` | |
| `POST …/undo` | `{ actor, to_revision_seq: number \| null }` | `undo { to_revision_seq }` (human) | |
| `POST …/review/checks` | `{ actor, check_id: DodCheckId, card_ids: CardId[] }` | one `confirm { card_ids, proposal_ids: [] }` with **exactly the `card_ids` the client sent** (the list the person saw). Server validation: `check_id ∈ {story_rules_confirmed, examples_reviewed, questions_resolved}` (else `400 CHECK_NOT_MARKABLE` — `changes_resolved` and `final_version_recorded` are never markable); `card_ids` non-empty (`409 NOTHING_TO_CONFIRM`), each live (`409 CARD_NOT_LIVE`), each of the kind the check covers (`422 KIND_MISMATCH`) | the UI computes the list as: check 1 → live story + live rules not `confirmed`; check 2 → live examples not `confirmed` or flagged; check 4 → live questions with `answer !== null` not `confirmed`; the response echoes `card_ids` |
| `POST …/signoff` | `{ reviewer: string, statement: string, revision_hash: Sha256Hex }` | `signoff.record { reviewer: { name }, confirmation_text: statement, cited_revision_hash }` | `SIGNOFF_DOD_FAILED` → `422 { reason, detail, checks }`; stale / already active → 409 |
| `PUT …/export-options` | `{ actor, capability_class, kind, size_estimate, facts }` | `capability_class` must be a catalogue class or `"unclassified"` (else `400 CLASS_UNKNOWN`); then `export.options_set { options: { …, by: actor } }` | `200 { ok, events, export_options: ExportOptions }` |

### 8.6 Export route

`GET /api/sessions/:id/export/:file?draft=true|false` — `file ∈ ExportFile` (the URL token **is** the file name; else `400 EXPORT_FILE_UNKNOWN`); `draft = query.draft === "true"`. `!draft && !isHumanVerified(state)` → `422 ErrorBody` with `reason: "NOT_HUMAN_VERIFIED"`, `detail: "export needs a human-verified requirement; add ?draft=true for a watermarked draft"`, `checks: dodReport(state)`, `signoff: { status, id?, revision?, invalidated_by_event_id? }` (`active_but_dod_failed` = active on the current revision but check 3 regressed). Otherwise `200`, content type `application/json` / `text/markdown; charset=utf-8` / `text/plain; charset=utf-8` (feature), `Content-Disposition: attachment; filename="<file>"` prefixed `DRAFT-` when draft. Body = `exportFile({ session, state, draft, now }, file).body` (§12).

### 8.7 The classifier bridge (`classifier-bridge.ts`)

Pure functions; the only file that imports both core's and the classifier's runtime modules.

```ts
export function buildClassifierInput(s: { state: MapState; seqOfEvent: (id: EventId) => number }, utterance: Utterance): ClassifierInput;
export function toCoreCommands(p: ClassifierProposal, state: MapState, utterance: Utterance,
                               ctx: { nextId: ApplyContext["nextId"]; actorForVoice: (u: Utterance) => string }): Command[];
export function intentOf(kind: OperationKind): Intent;
```

**`buildClassifierInput`**: `utterance → { id, text, lane, speaker }` (lane passed through, `"manual"` stays; `speaker` as recorded, `null` stays `null`). `recent` = the last 12 recorded utterances before this one, same mapping. `cards` = cards with status `proposed | applied | confirmed` in `card_order` → `CardIndexEntry` with `title = text.slice(0, 60)`, `links` by kind, `answer` for questions, `seq = seqOfEvent(changed.event_id)`, `last_utterance_id = changed.utterance_ids.at(-1) ?? null`, `last_speaker` = that utterance's speaker or null, `proposal_id = changed.proposal_id` when that proposal's provider ≠ human else null. `last_proposal` = `select.lastAppliedProposal(state, { aiOnly: true, statuses: ["applied", "confirmed"] })` mapped to `{ id, intent, op: operation.kind, kind: cards[affected_card_ids[0]]?.kind ?? null, status, card_ids: affected_card_ids, utterance_id: source_utterance_ids[0], rejectable: select.isRejectable(state, id) }` (a proposal that resolved a clarification keeps the asking classifier's provider and non-empty source ids, so it qualifies). `last_rejectable` = the most recent proposal in `proposal_order` with `select.isRejectable(state, id)`, same mapping. `pending_clarification` = the most recent `open` clarification in `clarification_order` that the classifier can represent: `pending_operation !== null` → `{ kind: "confirm_intent", candidates: [], pending_operations: [toClassifierOp(pending_operation)] }`; `template !== null && candidates.length >= 2` → `{ kind: "choose_target", candidates, pending_operations: [templateToClassifierOp(template)] }` with `"$choice"` in the target field; plus `{ proposal_id, question, intent, asked_by_utterance_id: source_utterance_ids[0], source_utterance_ids, classifier: stamp sans actor }`. A pure question (neither) or a template with < 2 candidates is skipped (click-only); older open clarifications are click-only until the newer one is resolved. A text answer previously recorded is visible to the classifier as a recent utterance (voice) or as the manual utterance being classified (typed), so no extra field is passed.

**`toCoreCommands`**: at most one `clarification.answer` followed by at most one `proposal.propose { proposals }` holding **every** proposal of this result (a leading `confirm` / `interpretation.reject` prefix is its own proposal in the same batch; a "both" answer's several `card.remove`s likewise). Shared stamp `{ ...p.classifier, actor: null }`, except proposals carrying `resolves_clarification_id` get `actor: ctx.actorForVoice(utterance)` = `utterance.speaker ?? "(<Call|Me|Typed>, no speaker label)"` — the label a person assigned, or an explicit statement that none was. `confidence = round2(p.confidence)`, `rationale = p.rationale`, `source_utterance_ids = p.source_utterance_ids`. **Every core proposal's `intent` is `intentOf(operation.kind)`**, never a copy of `p.intent`.

| classifier op | core operation |
|---|---|
| `card.create { card }` | `card.create { card: NewCard }` (`rule_id` only for example, `about_card_id` only for question). `kind === "story"` with a live story → `card.update { card_id: story.id, patch: { text } }` under `amend`, rationale suffixed " (the map already has a story; updating it)" |
| `card.update { card_id, patch, amendment }` | `card.update { card_id, patch }` with null fields dropped and `text_append` turned into `text: cards[card_id].text + " " + text_append.trim()`; `amendment` dropped on a resolved update |
| `card.remove { card_id, reason }` | `card.remove { card_id }`; `rationale += " — " + reason` when non-empty |
| `card.replace { card_id, replacement: { text } }` | `card.replace { card_id, replacement: { text } }` |
| `card.replace { card_id, replacement_card_id }` | one proposal `card.replace { card_id, replacement_card_id }` |
| `definition.refine { card_id, term, definition }` | same |
| `interpretation.reject { proposal_id }` | same |
| `confirm { card_ids }` | `live = card_ids.filter(live)`; non-empty → `confirm { card_ids: live, proposal_ids: [] }`; `card_ids` empty (or none live) and `last_proposal.status === "applied"` with `op ∈ {card.remove, undo, interpretation.reject}` → `confirm { card_ids: [], proposal_ids: [last_proposal.id] }`; otherwise skipped with `refused: NOTHING_TO_CONFIRM` |
| `undo { steps }` | `target = select.undoTarget(state, steps)`; `null` → skipped with `refused: UNDO_NO_EARLIER_REVISION`; else if `select.currentRevision(state).cause === "undo.applied"` and `/\bredo\b/i` does not match the utterance → a clarification proposal `{ operation: null, needs_clarification: true, question: "The last change was itself an undo — redo it?", pending_operation: { kind: "undo", to_revision_seq: target }, template: null, candidates: [] }` under `undo`; else `undo { to_revision_seq: target }` |
| `needs_clarification` + `clarification` | one proposal with `operation: null`, `needs_clarification: true`, `question`; **confirm_intent** → `pending_operation = toCoreOp(pending_operations[0])` (a `text_append` update becomes `patch.text` from the target's current text), `template: null`, `candidates: []`; **choose_target** → `template = templateOf(pending_operations[0])` (`card.create` keeps the draft with the link unset; `card.update` → `{ patch: { text: text_append ?? text ?? "" }, amendment: { from: a?.from ?? null, to: a?.to ?? "", scope: a?.scope ?? null, append } }` with `append` = the `text_append` minus a leading `Amendment: `, or the utterance text, first letter upper-cased, trailing full stop ensured — core's `resolveTemplate` recomputes the text for the card the person picks; `card.remove` → `{}`; `card.replace` → the replacement form; `definition.refine` → `{ term, definition }`; `confirm` → `{}`; `interpretation.reject { "$choice" }` → `{ kind: "interpretation.reject" }`), `candidates = clarification.candidates.map(c => ({ ...c, score: null }))`, `pending_operation: null`. Intent = `intentOf(template?.kind ?? pending_operation.kind)` |
| `resolves { proposal_id, chosen_card_ids, dismissed }` | `cid` = the open clarification whose `proposal_id` matches (otherwise the stale guard already re-ran). `dismissed: true` → `clarification.answer { kind: "dismiss", reason: utterance.text, actor }` first, then the remainder's proposals with `resolves_clarification_id: null`. `dismissed: false` → `clarification.answer { kind: "text", text: utterance.text, utterance_id: utterance.id, actor }` first **unless** `text_answers` already holds this `utterance_id` (the typed-answer route recorded it), then the proposals, of which **exactly the first** carries `resolves_clarification_id: cid` |
| `intent: "none"` (with or without `heard_intent`) | no commands; the `classification.record` carries `heard_intent` and the rationale |

`refused[]` entries name the core operation kind the bridge produced (`"unknown"` for a skipped classifier op).

### 8.8 WebSocket `GET /api/sessions/:id/stream?after=<seq>`

Server → client `StreamMessage` frames (§4). On connect: validate id and origin (close 4003 / 4004 with an `error` frame first; `LEDGER_BROKEN` → 4009, also when the session broke after an append failure). Then, in one synchronous tick: `upto = session.events.length; session.subscribe(socket); for (e of session.events) if (e.seq > after && e.seq <= upto) send({ type: "event", event: e })` — `run()` pushes to `events` and notifies subscribers synchronously in the same tick as the append, so nothing is missed or duplicated between catch-up and live. `hello` is sent first. Every classification outcome is an ordinary ledger event on this stream; there are no non-ledger frames besides `hello` / `error`. Keep-alive: ws `ping` every 25 s; a socket missing two is terminated. Backpressure: `bufferedAmount > 8 MiB` → close 1013 and the client resyncs. `close()` sends 1001 to every client.

## 9. Persistence

```
<EXMAP_HOME>/                  default ~/.exmap (os.homedir()); created 0o700 on first start
  settings.json                { "schema": "exmap.settings.v1", "user_name": "" }
  server.lock                  { "pid", "started_at", "version", "port"? } — exists only while a server runs
  sessions/<id>/
    meta.json                  SessionMeta (immutable after creation)
    events.jsonl               one event per line: canonicalJson(event) + "\n"; append-only; hash-chained
```
Export options live in `events.jsonl` (`export.options_set`); there is no other per-session file.

**`ledger.ts`.** `JsonlLedger(path)`: `readAll(): { ok: true; events } | { ok: false; error: LedgerReadError { code: "LEDGER_PARSE_ERROR"; row; detail } }` — split on `\n`, 1-based rows, blank lines skipped; a line that is not valid JSON, not an object, or lacks `hash`/`seq` → parse error at its row; a trailing partial line is a parse error at its row, never silently dropped (the README tells the user how to inspect and, as their own act, truncate it). `appendBatch(events)`: `data = events.map(e => canonicalJson(e) + "\n").join("")`; `fd = openSync(path, "a")`; `pre = fstatSync(fd).size`; `writeSync` (a short write throws) + `fsyncSync`; on any failure `ftruncateSync(fd, pre)` + `fsyncSync` (if even that fails, `truncate_failed: true`); throw `LedgerWriteError { code: "LEDGER_WRITE_FAILED"; detail; truncated_to; truncate_failed }`; `closeSync` in `finally`. One write, one fsync per batch.

`Session.run(command)` under the write mutex: `broken` → `409 LEDGER_BROKEN`; `r = engine.apply(state, command)`; `!r.ok` → return the refusal; `ledger.appendBatch(r.events)` — on `LedgerWriteError` mark `broken`, notify WebSocket clients (`error` frame + close 4009), throw `500 LEDGER_WRITE_FAILED` with the in-memory state untouched; else `state = r.state`, push the events, notify subscribers synchronously, return `r`. After a failed append the session answers `409 LEDGER_BROKEN` to every later act, is listed with `broken`, and is evicted from the store so the next open re-reads the file. Nothing is ever appended after a failed write.

**Locks (`home.ts`, `mutex.ts`).** `Mutex.run(fn)` is a promise chain; one write mutex and one classification chain per session. `acquireHomeLock(home, version)`: `openSync(lockPath, "wx")`, write `{ pid, started_at, version }` and fsync in the same step (the file is never empty); after `listen`, `completeHomeLock(port)` rewrites it atomically (`.tmp` + `renameSync`). On `EEXIST`: parsable and `pid` alive (`process.kill(pid, 0)` succeeds or `EPERM`) → live, `HomeLockedError { pid, port: port ?? null, url: port ? "http://127.0.0.1:<port>" : null }` (the launcher prints "another exmap is starting on this home" when `url` is null); unparsable → re-read after 200 ms, and only if still unparsable **or** the pid is dead (`ESRCH`) is it stale: unlink and retry once. Removed in `close()` and best-effort on `process.on("exit")`. `settings.json` and `meta.json` are written `.tmp` + `renameSync`.

**Load and verify (`session-store.ts`).** `SessionStore({ home, engine, classifier, now, nextId })`: `list()`, `create({ title, story?, actor? })`, `open(id)` (cached; cold path: read `meta.json` — missing dir → 404, unparsable or `schema` mismatch → `409 META_INVALID`; `ledger.readAll()` → parse error → `409 LEDGER_BROKEN { row, code: "LEDGER_PARSE_ERROR" }`; zero events → `initialState(id)`; else `engine.replay(events)` → error → `409 LEDGER_BROKEN { row: error.seq ?? 1, seq, code, detail }`), `summaryOf(id)` (never throws; replays the good prefix for `head` / `counts` / `revision` and carries `broken`). A broken session is never cached as open and never written to.

## 10. Web UI (`exmap/src/web/`)

### 10.1 Layout and navigation

```
src/web/
  index.html  main.tsx  App.tsx  styles.css (@import "tailwindcss")
  hash.ts                 sha256 via @noble/hashes/sha2.js + utils.js (sync Sha256Fn for core; pinned to the §5 vectors)
  api/client.ts           ApiClient (every route of §8) and ApiError { status, reason, detail, checks?, signoff? }
  store/sessionStore.ts   SessionStore: WS pump + core.reduce; useSyncExternalStore
  store/useSession.ts     useSession(), useDod(), useCounts(), useActor()
  replay/driver.ts        ReplayDriver (window.__exmap.replay) over the audio controller's replay API
  components/ SessionPicker Header Transcript Board Column CardView CardMenu CardEditDialog ProvenancePopover
              ProposalTray ProposalItem ClarificationItem ReviewDrawer ExportDrawer SettingsDialog Drawer Toast ChainBanner
  keyboard/rovingFocus.ts
  audio/                  §7
  public/pcm-worklet.js  public/replay/index.json  public/replay/conversation.v1.json
```
One screen, no router. `App` reads `?session=<id>`: absent → `SessionPicker`; present → the session screen. Creating or choosing a session does `history.replaceState(null, "", "?session=<id>")`, preserving `?replay=…&speed=…&autostart=1` and `?testhooks=1`. **`?replay=<name>` without `?session=`** makes `App` create a session first — `POST /api/sessions { title: "Replay — <fixture title>", story: fixture.story, actor: settings.user_name }` when a user name is set and the fixture carries a `story`, else `{ title }` alone — then `replaceState` to `?session=<id>&replay=…`. `SessionPicker` carries the same `settings-open` control as the header so a name can be set before any session exists.

Session screen (≥ 1024 px): `Header` (title; revision chip `rev <seq> · <hash8>` with `data-hash`; `Human verified` / `Not verified` badge from `isHumanVerified`; chain head `<seq> events`; counts; Undo, Review, Export, Settings buttons; classifier chip from `/api/config`: `<provider>` + `· <model>` when non-null + `(offline)` for rules.v1, or `<provider> → rules.v1 (fallback: <last_error.code>)` — no model literal in `src/web`). A collapsible strip with `CaptureControls` + `ReplayControls`. Three panes: **Transcript** (left) with `ManualInput` docked at its bottom; **Board** (centre); **Proposal tray** (right). Below 1024 px the panes become tabs (`role="tablist"`: Transcript / Map / Proposals). Drawers slide from the right over the tray.

### 10.2 `SessionStore` (the browser reduces exactly as the server does)

`SessionStore({ api, sessionId, wsUrl(after), sha256, WebSocketCtor? })`: `getState(): MapState`, `subscribe`, `status: { connection: "connecting" | "live" | "reconnecting" | "closed"; head; chainError: ChainError | null }`, `connect()`, `dispose()`. Starts from `initialState(sessionId)` and opens `ws?after=0`. Every `event` frame is checked **before** reducing: (1) `seq <= head.seq` → duplicate, ignored; (2) `seq > head.seq + 1` → gap → `resync()`; (3) `seq === head.seq + 1 && prev_hash !== head.hash` → a chain break, not a gap: `chainError = PREV_HASH_MISMATCH`, the store stops reducing and `ChainBanner` shows "The event stream broke its chain at seq N; showing the state read-only" (never resyncs on this); (4) `session_id` mismatch → `SESSION_MISMATCH`; (5) `eventHash(body sans hash) !== hash` → `HASH_MISMATCH`, banner "An event failed its hash check (seq N); showing the state read-only". Then `state = reduce(state, event)`. A `chainError` is terminal; the banner offers Reload and Back to sessions. `resync()` reopens with `after = head.seq`; reconnect backoff 0.5 → 1 → 2 → 4 → 8 s with a polite live region; on 4004/4009 the banner names the reason. Every number in the UI is `select.counts(state)` or `dodReport(state)` from core, computed client-side from the same events; the server is never asked for a count. Mutations go through `ApiClient`; the response's events are not applied locally (they arrive on the WS); an optimistic "pending…" chip sits on the clicked control until the event lands or the request fails.

### 10.3 Transcript

`role="log" aria-live="polite" aria-relevant="additions"`, `data-testid="transcript"`. Rows sorted by `t_start_ms` then arrival; each `utterance-<id>` shows the lane badge (Call / Me / Typed), `speaker ?? "— (no speaker label)"` (no code path substitutes a lane name for `null`), `mm:ss` from `t_start_ms`, a provider chip ("Whisper · base.en", "Web Speech (not local)", "Typed", "Replay"), and the text. Under it `utterance-proposals-<id>`, built from the ledger only: one chip per proposal citing the utterance (intent + status `applied` / `confirmed` / `rejected` / `clarifying` / `answered` / `dismissed`); from `select.classificationsOf(state, id)`, a chip per record: "no map change — <rationale>" for `none` (prefixed "heard <heard_intent> — " when set), "classifier error: <code>", "fallback from claude: <error>", and "classifying…" while no record exists yet. Clicking a proposal chip focuses the tray item, or the card when it has left the tray; a clarification chip always focuses the tray item.

### 10.4 Board

`data-testid="board"`, four `Column`s story / rules / examples / questions: `role="region"` with `aria-labelledby` ("Story (1)" etc.), `data-testid="column-<kind>"`, backgrounds `bg-yellow-100` / `bg-sky-100` / `bg-green-100` / `bg-red-100` with `text-slate-900` (≥ 7:1; status never by colour alone). Cards: `<ul role="list">` of `<li><article tabIndex data-testid="card-<id>" aria-labelledby="card-<id>-text" aria-describedby="card-<id>-status">`. Content: text; definitions as `<dl>`; example → "for rule: <rule text 40ch>" or a "not attached to a rule" warning chip; question → "about: <card 40ch>", the answer line or "unanswered", an `accepted outstanding by <name>` chip; status chip `card-status-<id>` with `select.statusLabel(card)`; `card-needs-review-<id>` "needs review: rule changed/removed/replaced (event <seq>)"; version `v<n>`; provenance button `card-provenance-<id>` (`aria-expanded`, `aria-controls`) → `ProvenancePopover` (`role="dialog"`): created by proposal `<id>` from utterance(s) (speaker, time, excerpt), classifier `rules.v1` / `claude (<model>)` / `rules.v1 — fallback from claude: <error>` / `human: <actor>`, confidence (AI only), rationale, version history (`v1 → v2 replaced by event <seq>` with the old text), `supersedes` / `superseded_by`, `restored_by` ("restored by undo <pid>" / "restored by the rejection of <pid>"), `confirmation` ("confirmed by <actor>" for a click; "confirmed by voice (<provider>, <confidence>, speaker <actor>)" otherwise; version seen). Card menu `card-menu-<id>` (`role="menu"`): Confirm (`card-confirm-<id>`), Edit (`card-edit-<id>` → `CardEditDialog`: `card-edit-text`, a rule select for examples, an answer field for questions; `card-edit-save` → `POST cards/:id/update`), Remove (`card-remove-<id>`, with a confirm step), Accept as outstanding (questions only, with reason). Live cards only unless the **history toggle** (`history-toggle`, a labelled switch "Show history (removed, rejected and superseded)") is on; history cards render with `opacity-60`, a strike-through and their status chip, and offer only Provenance. "Add card" per column (`column-add-<kind>`) → `POST cards`.

Keyboard: roving tabindex per column (`ArrowDown`/`ArrowUp`, `Home`/`End`, `ArrowRight`/`ArrowLeft` to the neighbouring column's active card); `Enter`/`Space` opens the menu (focus on the first item; `Escape` closes and restores focus); `p` opens provenance; a visible focus ring; a `?` help dialog lists the shortcuts.

### 10.5 Proposal tray

`role="region" aria-label="Proposals"`, `data-testid="tray"`. Membership, newest first: (1) every `open` clarification, whatever its age (`select.openClarifications`); (2) every unreviewed AI act (`select.unreviewedActs`), whatever its age, until Accept or Reject; (3) `applied` AI proposals from the last 10 utterances' proposals (older ones live in the transcript; a card-affecting proposal is reviewed through its cards).

`ProposalItem` (`proposal-<pid>`): intent chip, the rationale, the operation as a diff (create: the card text; update: old → new; remove: the card; replace: old ⇢ new; refine: `term: definition`; undo: `rev a → rev b`; reject: the proposal it reverts), classifier chip + confidence as a number (`0.67`, never a bar without the number), a fallback notice when `fallback_from`, the source utterance excerpt, and for unreviewed acts `proposal-unreviewed-<pid>` "AI act — needs a person's Accept or Reject". Buttons: **Accept** (`proposal-accept-<pid>`) for content proposals with a live affected card and for removals / undos / rejects (sends `proposal_ids`); hidden for `confirm` proposals; **Reject** (`proposal-reject-<pid>`) for every rejectable kind, labelled "Restore" for `card.remove` and "Redo" for `undo`. The classifier's `last_error` (from `/api/config`, polled every 30 s and after a fallback proposal) is shown once as a dismissible `classifier-notice`.

`ClarificationItem` (`clarification-<cid>`, `role="group"` labelled by the question): the question; a line naming what will happen ("Will: remove the chosen example" / "Will: <operation rendered as in ProposalItem>"); text answers so far ("answered in words by <actor>: <text> — still open"); then: `template !== null` → one button per candidate (`clarification-candidate-<cid>-<cardId>`, label = card text 60ch + kind) → `{ kind: "candidate", card_id }`; `pending_operation !== null` → one **Yes** button (`clarification-yes-<cid>`, "Yes — <operation>") → `{ kind: "yes" }`; neither → nothing beyond the two below. Always: `clarification-text-<cid>` ("Answer in words") → `{ kind: "text", text }`; Dismiss (`clarification-dismiss-<cid>`, reason prompt) → `{ kind: "dismiss", reason }`. A refused `yes` (`CARD_NOT_LIVE`) shows the refusal and keeps Dismiss. Once resolved the item leaves the tray and the transcript chip reads `answered`.

### 10.6 Review drawer and Export drawer

`Drawer` = `role="dialog" aria-modal="true" aria-labelledby`, focus to its first control, Tab trapped, `Escape` closes, focus returns to the opener. Open with `review-open` / `export-open`; test ids `review-drawer` / `export-drawer`.

Review drawer: (1) status line `Revision <seq> · <hash8>` and "Human verified by <name> at <time>" or "Not verified"; (2) `signoff-invalidated` (`role="status"`) when the last sign-off is `invalidated`: "The sign-off by <reviewer> (<at>, revision <hash8>) was invalidated by <event type> at <at> (revision <hash8>). Review the map and sign off again."; when it is `active` but `isHumanVerified` is false: "Signed off on this revision, but not currently verified: <check 3 details>"; (3) the five checks (`dod-check-<id>`, `dod-check-status-<id>` "passes"/"fails", details), with **Mark reviewed** (`dod-mark-<id>`) on checks 1, 2, 4 that first previews the exact card list (`dod-mark-list-<id>`) then `POST review/checks` with that list; check 3's details are actionable in place — each open clarification links to its tray item, each unreviewed act gets Accept (`dod-act-accept-<pid>`) / Reject (`dod-act-reject-<pid>`), dangling links name the card; (4) **Outstanding questions**: every live question with `answer === null && accepted_outstanding === null`, each with "Accept as outstanding" (`question-accept-<id>`) and a required reason (`question-accept-reason`); accepted ones listed as "accepted outstanding by <name>: <reason>" — the word "answered" never appears for them; (5) **catching-up gate**: when the audio controller's `pendingWork() > 0`, `review-catching-up` "Transcription is still catching up (N segments or utterances on their way into the ledger)" and `signoff-submit` is disabled until it is 0 or the reviewer ticks "Sign off anyway (the map may still change)" (`signoff-anyway`). The tick only enables the button: the sign-off names the revision and chain head it vouches for, and anything that lands later is a later event that either changes the revision (and invalidates) or does not — so nothing about the page-side backlog needs to be, or is, written into the ledger; (6) **sign-off form**: `signoff-reviewer` (prefilled from settings, labelled "Reviewer (self-asserted)"), the exact statement shown as the field's label with an "Insert sentence" button, `signoff-statement`, the cited revision (read-only), `signoff-submit` (disabled until both fields are non-empty). On 422 the failing checks render inline (`signoff-errors`); on success `signoff-status` reads "Signed off by <name> at <at> on revision <hash8> (evidence head <seq>)".

Export drawer: (1) gate panel (`export-gate`): verified → "Human verified — revision <hash8>, signed by <name>"; else the failing checks and "Exports are refused until the requirement is human-verified. You can download DRAFT / NOT VERIFIED files instead." with the draft toggle (`export-draft-toggle`; links then carry `?draft=true` and `DRAFT-` names); (2) options form: `export-class` (catalogue classes + "unclassified"), `export-kind`, `export-size`, then one row per slot of the chosen class (`export-fact-slot-<slot>`: the catalogue question as label, a chip "required (structural)" or "value — routes, does not block", a text input), free facts (`export-fact-add`; a slot not in the class shows "crb will keep this as prose"); Save (`export-save`) → `PUT export-options`; the panel says "Supplied at export by <by> at <at> (change <seq> of <n>); not part of the sign-off" and a disclosure lists earlier values from `state.export_options`; (3) a preview of `ticket.md` (`export-preview`, refreshed after save); (4) download links `export-download-<file>` (`<a download href="/api/sessions/<id>/export/<file>?draft=<bool>">`).

### 10.7 Settings and the actor

`settings-open` (header and `SessionPicker`) → dialog: **Your name** (`settings-name`, `settings-save` → `PUT /api/settings`) with "This name is stamped on every change you make and is the default speaker label for your microphone"; **Classifier** (`classifier-status`: provider, reason, model, last error, from `/api/config`; "Set ANTHROPIC_API_KEY before starting to use Claude; without it the offline rules classifier is used" — never a key field); **Audio providers** (the model/provider/dtype selects, q8/q4 only); **Data** (home path; "append-only; nothing is deleted"); version. `useActor()` returns `settings.user_name`; when empty, every act button opens the settings dialog first with "Set your name so the record says who did this". `SpeakerStore` is constructed with `userName = settings.user_name || null`.

### 10.8 Accessibility (brief §5)

Every interactive element is native or has a complete ARIA pattern (menu, dialog, switch, tablist, meter) with the keyboard handling above and an accessible name; icons are `aria-hidden` with visible or `sr-only` text. Kind backgrounds with `text-slate-900`; chips use text; `prefers-reduced-motion` disables slide animations; focus always visible. Live regions: transcript (`polite`), toasts (`status`), connection status, invalidation notice, lane badges. Axe (`@axe-core/playwright`) runs on (a) the session screen with cards and tray items, (b) with the review drawer open, (c) with the export drawer open, (d) with the settings dialog open, (e) with the model consent notice open; violations with `impact` `serious` or `critical` must be `[]`.

### 10.9 Replay driver and test hooks (`replay/driver.ts`)

`ReplayDriver({ controller, postQueueIdle })`: `playUntil(target: string | number)` → `controller.playReplay("instant", { until: target })` then `await postQueueIdle()`; `skip(target)` → `controller.skipReplay(target)` (the journey's click-answer variant of u05/u06); `playAll()`; `position`. With test hooks on (`import.meta.env.DEV` or `?testhooks=1`), `main.tsx` adds `window.__exmap.replay = { playUntil, skip, playAll, position }` beside `window.__exmap.audio`. The replay panel's own Play button and `?autostart=1` play the whole fixture.

## 11. The launcher — `exmap/bin/exmap.mjs`, `start.sh`, `start.ps1`

```
node bin/exmap.mjs [--port <n>] [--home <dir>] [--no-open] [--no-install] [--no-build]
env: EXMAP_PORT (default 4317; 0 = OS-assigned), EXMAP_HOME (default ~/.exmap), EXMAP_NO_OPEN=1, EXMAP_CLASSIFIER,
     ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN (passed through, never printed), EXMAP_COOP=0
exit codes: 0 started (or already running and the browser was opened)   1 unexpected failure   2 node < 22.12
            3 port in use by a non-exmap program   4 npm install failed   5 build failed   6 EXMAP_HOME locked by another live exmap server (its URL printed)
```
Plain ESM, Node built-ins only (`node:fs`, `node:path`, `node:os`, `node:child_process`, `node:crypto`, `node:url`, `node:module`, global `fetch`), so it runs before `node_modules` exists. Pure helpers (`nodeVersionOk`, `installNeeded`, `buildStale`, `locateNpm`, `browserCommand`, `probePort`) are exported behind `if (import.meta.url === pathToFileURL(process.argv[1]).href) main()` for unit tests.

Steps, in order:
1. **Node check.** `major < 22 || (major === 22 && minor < 12)` → `exmap needs Node 22.12 or newer (found v<version>). Install it from https://nodejs.org` → exit 2.
2. **Port probe.** `GET http://127.0.0.1:<port>/api/health` with `AbortSignal.timeout(1500)`: 200 and `body.app === "exmap"` → print `exmap is already running at <url>`, open the browser, exit 0; connection refused / timeout → free; anything else → `port <port> is in use by another program; set EXMAP_PORT or pass --port` → exit 3. Skipped when `port === 0`.
3. **Install when needed.** `lockHash = sha256(package-lock.json)`; `stamp = node_modules/.exmap-install-stamp` (absent → `""`). If `!exists("node_modules") || stamp.trim() !== lockHash` → `npm install --no-audit --no-fund` with env `{ ...process.env, ONNXRUNTIME_NODE_INSTALL: "skip", npm_config_onnxruntime_node_install: "skip" }`, `stdio: "inherit"`, cwd = the package root; non-zero → exit 4; then write the stamp if `postinstall` did not. npm is located, in order: `process.env.npm_execpath`; `<dirname(execPath)>/node_modules/npm/bin/npm-cli.js` (Windows); `<dirname(execPath)>/../lib/node_modules/npm/bin/npm-cli.js` (Linux/macOS tarballs, nvm); `realpathSync(which("npm"))` resolved to its `npm-cli.js`; last, `npm` on PATH with `shell: true` (needed on Windows for `npm.cmd`; printed as `using npm from PATH`). An `npm-cli.js` is executed as `process.execPath <npm-cli.js> …`, so the Node that passed the check runs npm. `--no-install` skips this step (still checks `node_modules` exists).
4. **Build when stale.** Stale iff `dist/web/index.html` missing, or `dist/server/server/main.js` missing, or `dist/.exmap-build-stamp` missing/unparsable, or `stamp.lock_sha256 !== lockHash`, or `newestMtimeMs(["src", "vite.config.ts", "tsconfig.base.json", "tsconfig.server.json", "tsconfig.web.json", "package.json"]) > stamp.newest_source_mtime_ms` (the walk skips `**/*.test.*`; `src/web/public/replay` counts). Stale → `node scripts/build.mjs`; non-zero → exit 5. Known limitation (README): a fresh clone has new mtimes → one rebuild.
5. **Start the server in-process.** `const { startServer } = await import(pathToFileURL(join(root, "dist/server/server/main.js")).href)`; `srv = await startServer({ home, port, host: "127.0.0.1", coop, webDist: join(root, "dist/web"), ortDir: resolveOrtDir(root) })` (`resolveOrtDir` imported from `dist/server/server/static.js` after the build). `HomeLockedError { url }` → `another exmap is already using <home> at <url>` → exit 6.
6. **Wait for health.** Poll `GET <url>/api/health` every 250 ms for up to 30 s.
7. **Open the browser** unless `--no-open` / `EXMAP_NO_OPEN=1`: `darwin` → `open <url>`; `win32` → `cmd.exe /c start "" "<url>"`; `linux` with `WSL_DISTRO_NAME` → `cmd.exe /c start` if it resolves, else `xdg-open <url>` when `DISPLAY` or `WAYLAND_DISPLAY` is set; otherwise print `Open <url> in Chrome or Edge`. `spawn(..., { detached: true, stdio: "ignore" }).unref()`; a spawn error is printed, never fatal. The URL is always printed.
8. **Run until signalled.** `SIGINT`/`SIGTERM` → `await srv.close()` (stop listening, close WebSocket clients with 1001, abort every in-flight classifier call and drop queued jobs, wait for in-flight ledger appends, delete `server.lock`) → exit 0. A second signal during the close → exit 130. `start.ps1` runs node in the foreground so Ctrl+C reaches it.

`start.sh`:
```sh
#!/usr/bin/env sh
# exmap/start.sh — one command: installs, builds, starts, opens the browser
set -eu
dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if ! command -v node >/dev/null 2>&1; then
  echo "exmap needs Node.js 22.12 or newer, and 'node' is not on your PATH." >&2
  echo "Install it from https://nodejs.org (LTS) and run this again." >&2
  exit 2
fi
exec node "$dir/bin/exmap.mjs" "$@"
```
`start.ps1`:
```powershell
# exmap/start.ps1 — one command on Windows (PowerShell 5.1+ or 7)
$ErrorActionPreference = "Stop"
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
  Write-Error "exmap needs Node.js 22.12 or newer, and 'node' was not found. Install it from https://nodejs.org (LTS), reopen the terminal, and run this again."
  exit 2
}
& $node.Source (Join-Path $PSScriptRoot "bin\exmap.mjs") @args
exit $LASTEXITCODE
```
Both wrappers are ≤ 15 lines; every decision lives in `exmap.mjs`. `npm start` inside `exmap/` runs the same launcher.

## 12. Export mappers (`exmap/src/export/`) and the vendored catalogue

```
src/export/  index.ts (exportFile, buildExportContext, the five mappers)  types.ts (re-exports §4 §12)  catalogue.ts  text.ts (slugify, storyTitle, parseGwt, indent, mdEscape)
             backlog-item.ts  ticket.ts  feature.ts  evidence.ts  crb-catalogue.json
```
All functions are pure and take `now` as input; same input → byte-identical output.

### 12.1 Context

```ts
export interface ExportContext {
  session: ExportSession; draft: boolean; verified: boolean; now: IsoTimestamp;
  revision: RevisionStamp; head: { seq: number; hash: Sha256Hex | "" };
  signoff: Signoff | null;                   // the active one when verified; else the last one (its status tells) or null
  dod: DodReport;
  story: StoryCard | null; rules: RuleCard[]; examples: ExampleCard[]; questions: QuestionCard[];   // live, in card_order
  examplesByRule: Map<CardId, ExampleCard[]>; unattachedExamples: ExampleCard[];
  options: ExportOptions;                    // select.exportOptions(state) ?? { capability_class: "unclassified", kind: "code", size_estimate: "unsized", facts: [], by: "", seq: 0, at: now }
  optionsHistory: ExportOptions[];           // state.export_options
  itemId: string; title: string;
}
export function buildExportContext(input: ExportInput): { ok: true; ctx: ExportContext } | ExportRefusal;   // refuses iff !draft && !isHumanVerified(state)
export function exportFile(input: ExportInput, file: ExportFile): ExportResult | ExportRefusal;
export const DRAFT_WATERMARK = "DRAFT / NOT VERIFIED";
```
`verified = isHumanVerified(state)`; `draft && verified` still watermarks (the UI never offers the toggle on a verified map). `signoff.status` in a refusal: `none`, `invalidated`, `active_but_stale` (kept for completeness), `active_but_dod_failed`. `title = storyTitle(story) ?? session.title` — the first sentence of the text (split at `. `, `.\n` or `\n`), trimmed, truncated to 120 chars at a word boundary; draft titles prefixed `[DRAFT / NOT VERIFIED] `. `itemId = slugify(baseTitle).slice(0, 48).replace(/-+$/, "") || "exmap"` + (`-draft` when draft) + `-<hash8>` — matches `[A-Za-z0-9][A-Za-z0-9._-]{0,63}` by construction; `slugify` = NFKD → ASCII letters/digits → lowercase, runs of other chars → `-`, leading `-` removed.

### 12.2 `crb-backlog-item.json` (`BacklogItem`)

`id`, `title` as above; `kind`, `capability_class`, `size_estimate` from options. `description` = story text; then `\n\nRules:\n- <rule>` per rule when any; then `\n\nDefinitions:\n- <term>: <definition>` (deduplicated by term, sorted) when any live card has definitions. `acceptance_criteria` = per live example `Given <g>, when <w>, then <t>` when `parseGwt(text)` succeeds (`when` omitted if null), else `Example: <text>`; then each fact as `<slot>: <text>`. `structural_facts` = the fact lines verbatim. `depends_on: []`, `level: "L1"`, `supersedes: ""` (chaining exports by revision is a documented next step), `registered: now`. `labels`: `exmap_session`, `exmap_revision` (full hash), `exmap_signoff` (id or `""`), `exmap_export_options_seq`; drafts add `exmap_draft: "true"`; verified exports add `exmap_reviewer` and `exmap_signed_at`. `parseGwt(text)`: the whitespace-collapsed text must start with `given`, `if` or `when`; split at the first standalone `when` (only if it started with given/if) and the first standalone `then` (required); the opener and a leading `,`/`and` after each keyword stripped; trailing full stop removed from `then`; anything else → `null` (no invented structure).

### 12.3 `ticket.json` (`Ticket`) and `ticket.md`

`body` is a newline-joined **string** (crb's `Ticket` dataclass declares `body: str`). `key = itemId`; `type = "User Story"`; `tags = ["crb:class=<class>", "crb:kind=<kind>", "exmap:revision=<hash8>", "exmap:session=<id>"]` + `"exmap:draft"` on drafts; `links: []`, `url: ""`, `state: ""`, `author: ""` (the tracker fills these; a guess would be pretending). `points` encodes the chosen size so crb derives the same tier: `XS→1, S→3, M→8, L→20, XL→21, unsized→null`. `body` lines: the draft banner (`DRAFT / NOT VERIFIED — failing checks: <ids>`) when draft; story; blank; `Rules:` + `- …`; `Definitions:` + `- term: definition` (if any); `Size estimate: <size> (story points <n> encode this tier for crb)` or `Size estimate: unsized`; `Verification: reviewed by <name> at <at>; requirement revision <hash>; evidence head <seq>/<hash8>` or `Verification: NOT VERIFIED`; `Export options: supplied by <by> at <at> (change <seq>); outside the sign-off` (omitted when `seq === 0`); `Source: exmap session <id>`. `acceptance_criteria` identical to the backlog item's.

`ticket.md`:
```
# <title>
> DRAFT / NOT VERIFIED — this requirement has not passed human verification. Failing checks: <ids>.     (draft only)

**Story.** <story text>

## Rules
- <rule text>                                   (or "_No rules recorded._")

## Definitions                                  (only when any)
- **term** — definition

## Acceptance criteria
- Given …, when …, then …
- Example: …
- slot: text

## Structural facts (crb)                       (only when facts exist)
- `slot: text`
_Supplied at export by <by> at <at> (change <seq> of <n>); outside the sign-off._

## Open questions explicitly accepted as outstanding        (MUST appear when any question is accepted outstanding; omitted otherwise)
- <question text> — accepted as outstanding by <by>: <reason> (not answered)

## Answered questions                           (only when any)
- <question text> — <answer>

## Unresolved questions                         (draft only; only when any)
- <question text>

## Verification
Reviewed by **<name>** at <at>. Requirement revision `<hash>`. Evidence head `<seq>` / `<hash>`. exmap session `<id>`.
_or_ **NOT VERIFIED.** Failing checks: <id — detail>.

Tags: `crb:class=…` `crb:kind=…` `exmap:revision=…`
```
`mdEscape` neutralises only a leading `#`/`>`/`-` in card text and backticks.

### 12.4 `requirement.feature`

```gherkin
# DRAFT / NOT VERIFIED — failing checks: …                                      (draft only)
# Generated by Example Map Live from session <id>, revision <hash>; human verified by <name> at <at>   | ; NOT VERIFIED
@exmap @exmap-revision-<hash8> [@exmap-draft]
Feature: <title>
  <story text, each line indented two spaces>

  # Definition: <term> — <definition>                                            (per definition, after the story)
  # Open question (accepted outstanding by <by>: <reason>): <text>               (questions with no about_card_id, or about the story)
  # Question (answered): <text> — <answer>
  # Question (unresolved): <text>                                                (draft only)

  Rule: <rule text>
    # Definition: …                                                              (the rule's own definitions)
    # Open question (accepted outstanding by …): …                               (questions about this rule)

    Scenario: <example title>                                                    (storyTitle() of the example, ≤ 80 chars)
      Given <g>
      When <w>                                                                   (omitted when null)
      Then <t>

    Scenario: <example title>                                                    (unparseable text)
      * <example text verbatim>

  # Examples not attached to a rule                                              (only when any)
  Scenario: …
```
Rules and examples in `card_order`; questions about an example are comments inside that scenario; a rule with no examples still gets its block; multi-line text indented line by line; no `Background`, no tables, no invented steps; no tabs; ends with one `\n`.

### 12.5 `evidence.json` (`Evidence`)

Verified: `signoff` is the active one and `signoff.revision.hash === requirement_revision.hash`. Draft: `verified: false`, `signoff` is the last one with its status (an invalidated sign-off is shown as invalidated, never as current) or `null`. `canonical_state = canonicalState(live cards)`; `sha256(canonicalJson(canonical_state)) === requirement_revision.hash`. `export_options` / `export_options_history` from state.

### 12.6 The vendored catalogue (`src/export/crb-catalogue.json`)

Copied **unchanged** from the scratchpad generator's output: `_source: "src/crb/factory/readiness.py CATALOGUE in jita81/commit-replay-bench"`, `_source_commit: "ba05a67d8dc0114b71b63043991f1466055b2660"`, `_copied: "2026-10-16"`, `classes: { <class>: [{ name, question, kind: "structural" | "value" }] }` — 14 classes: `backend.route.add` (method_path, request_shape, response_shape, error_contract; value example_payload), `backend.route.edit` (route_identity, behaviour_change, error_contract; value example_payload), `backend.model.edit` (field_name_type, nullability, migration_needed; value default_value), `backend.migration.add` (schema_change, reversible; value data_backfill), `frontend.component.add` (props, states; value rendered_text), `frontend.component.edit` (component_identity, prop_or_state_change; value rendered_text), `frontend.route.add` (route_path, guard), `bug.fix` (reproduction, expected_behaviour; value exact_value), `test.add` (subject_under_test, behaviour_asserted), `test.fix` (failing_test, corrected_assertion), `docs.update` (doc_target), `ci.workflow.edit` (workflow, trigger_and_steps), `infra.helm.edit` (chart_and_values, provisioning), `infra.terraform.edit` (resource, provisioning). Structural slots are required by crb's readiness check; value slots route rather than block. `catalogue.ts`: `loadCatalogue(): { source, source_commit, copied, classes: Record<string, Slot[]> }`, `slotsFor(cls): Slot[]` (`[]` for unknown), `isCatalogueClass(cls)` (`"unclassified"` is not a class). `GET /api/catalogue` serves the file verbatim. Updating it is a copy, never an edit; the README states the source file, commit and date.

## 13. Test plan (summary; every case is listed in `docs/TEST-PLAN.md`)

Gates: `npm run check` = typecheck (three tsconfigs) + `vitest run` + build; `npm run e2e` = build + Playwright (journey, replay, audio, axe, launcher). Both must pass before any commit.

`vitest.config.ts`:
```ts
export default defineConfig({ test: { projects: [
  { test: { name: "node", environment: "node", include: ["tests/unit/{core,classifier,audio,server,export,launcher}/**/*.test.ts"] } },
  { plugins: [react()], test: { name: "web", environment: "jsdom", include: ["tests/unit/web/**/*.test.{ts,tsx}"],
            setupFiles: ["tests/unit/web/setup.ts"] /* @testing-library/jest-dom/vitest; stubs WebSocket, matchMedia, crypto.randomUUID */ } },
], exclude: ["tests/e2e/**", "node_modules/**"] } });
```
`playwright.config.ts`: `testDir: "tests/e2e"`, `workers: 1`, `retries: 0`, `timeout: 120_000`, `expect.timeout: 10_000`, project `chromium` with `launchOptions.args` from §7.7 and `permissions: ["microphone"]`, `reporter: [["list"], ["html", { open: "never" }]]`; no `webServer` block (`PLAYWRIGHT_BROWSERS_PATH` is preset; never `playwright install`).

`tests/e2e/fixtures.ts` extends `test` with a worker-scoped `server` fixture: `home = mkdtemp("exmap-e2e-")`; `spawn(process.execPath, ["dist/server/server/main.js"], { env: { ...process.env, EXMAP_HOME: home, EXMAP_PORT: "0", EXMAP_CLASSIFIER: "rules.v1", EXMAP_NO_OPEN: "1" } })`; waits for the stdout line `/exmap listening on (http:\/\/127\.0\.0\.1:\d+)/` (30 s) and provides `baseURL`; teardown `SIGTERM`, waits for exit, asserts `server.lock` is gone, removes `home`. `EXMAP_CLASSIFIER=rules.v1` is forced so a developer's key cannot change the journey. Helpers: `setName(request, name)`, `createSession(request, { title, story, actor })`, `openSession(page, id, extraQuery)` (always appends `&testhooks=1`), `playUntil(page, label)` = `page.evaluate(l => window.__exmap.replay.playUntil(l), label)`, `skip(page, label)`, `fixture` = the parsed `conversation.v1.json`, `cardByText(page, kind, substring)`.

Unit coverage by module (counts are the test ids in `TEST-PLAN.md`): core — canonical/chain (10), revision (5), reducer (5), operations and transitions (19), batches (3), clarification (8), classification (2), undo (5), DoD/sign-off (13), export options (1), selectors (1), apply atomicity (1), compile-time (1); classifier — rules.v1 (58 rows), clarification (20), claude provider (27), normalise/referents (6 groups), the fixture conversation (1 end-to-end run with per-row assertions); audio — VAD (8), segmenter (10), hallucination (6), replay (7), lane state machine (8), queues and sink (4), utterance builder (1), guidance (3), Web Speech (2), speakers (1), resample (1), local Whisper (1), React smoke (2); server — health/config, host guard, sessions, utterances, bridge, acts, sign-off, persistence, stream, export routes, settings, export options (12 files); export — context, backlog item, ticket, feature, evidence, catalogue (6); web — session store, board, tray, review drawer, export drawer, settings, replay driver, hash adapter (8); launcher — pure helpers (1 file, 6 tables). E2E — the journey (brief §0 steps 1–5 and §5 in one test, plus the typed variant), replay (2), audio (E1, E1a, E2–E8), axe (1 with five screens), launcher (1).

### 13.1 The e2e journey (`tests/e2e/journey.spec.ts`), driven by the replay provider over `conversation.v1.json`

Set-up: `setName("Sam")`; `createSession({ title: "Appointment cancellation", story: fixture.story, actor: "Sam" })`; `openSession(page, id, "replay=demo&speed=instant")` (no autostart; the driver plays in slices). The rules.v1 expectations of §14 are the ground truth; cards are located by text, never by ordinal.

1. **Talk naturally / watch the map populate.** `playUntil("u04")` → `column-rule` has "…not within two hours…" (`applied`); `column-example` has the GP and nurse examples, both "for rule:" the rule; transcript rows show provider "Replay" and the fixture speaker; `utterance-proposals-<u02>` shows `add · applied`; the tray item for u02 shows the rationale and a numeric confidence.
2. **Clarification, answered by click.** `playUntil("u05")` → `clarification-<cid>` with two candidate buttons (nurse first, GP second); check 3 reads "fails" and names the clarification; the item says "Will: remove the chosen example". Click the candidate containing "GP" → the GP example's chip reads `removed` (history toggle on), the nurse example is live, the tray item is gone, the u05 chip reads `answered`; the removed card's provenance names the asking classifier (`rules.v1`) with actor "Sam". `skip("u06")` (the click stood in for the voice answer), then continue.
3. **Change your mind by talking.** `playUntil("u09")` → the rule text contains "24 hours" and ends with "Keep two hours for GPs."; the nurse example shows `card-needs-review-*` "rule changed"; the rule's popover lists `v1`, `v2`, `v3`; after u09 the rule is `confirmed` with "confirmed by voice (rules.v1, 1, speaker Priya)".
4. **Questions and definitions.** `playUntil("u13")` → two questions, both "about:" the rule; the story card shows `appointment — a booked slot, not a walk-in`; the error-case example exists, linked to the rule.
5. **Remove, unambiguous, as an AI act — then reviewed by voice.** `playUntil("u14")` → the error-case example reads `removed`; the tray shows the removal with `proposal-unreviewed-*` and Accept + Restore; check 3 lists it. `playUntil("u15")` ("Yes.") → the removal proposal is `confirmed`, the unreviewed line is gone, check 3 no longer lists it; its popover reads "confirmed by voice (rules.v1, 0.5, speaker Priya)".
6. **Reject by voice.** `playUntil("u18")` → the "must be able to override" rule reads `interpretation rejected` (history on); the "must not be able to override" rule is live; the tray lists the reject as an unreviewed act.
7. **Replace by an existing card, then undo by voice.** `playUntil("u19")` → capture the revision chip's `data-hash` as `h19`. `playUntil("u20")` → the first nurse example reads `superseded`; the u19 nurse example is live with `supersedes` in its popover; the chip's seq increased and its hash differs from `h19`. `playUntil("u21")` → the first nurse example is live again (its `needs_review` flag as it was), both nurse examples live; the chip's seq increased again and its `data-hash` equals `h19`; the tray lists the undo as an unreviewed act.
8. **The rest of the talk.** `playUntil("u30")` → the dentist question, the two GP examples and the twice-a-day question exist; `$ex_gp3` was removed at u26 and restored at u27 (`restored_by` names the undo); check 3 lists exactly three unreviewed acts (u17 reject, u21 undo, u27 undo).
9. **Human-verified completion.** `review-open`; `dod-check-status-questions_resolved` "fails" → `question-accept-*` with reason "To be settled with the practice manager" for each of the four questions → "passes", details contain "accepted outstanding" and not "answered"; `dod-check-status-changes_resolved` "fails" → `dod-act-accept-*` for each listed act → "passes"; `dod-mark-story_rules_confirmed` (preview lists the story and the override rule) and `dod-mark-examples_reviewed` (preview lists every live example) → all five "passes"; the header still reads "Not verified".
10. **Sign-off.** `signoff-reviewer` "Sam", `signoff-statement` ← "Insert sentence", `signoff-submit` → `signoff-status` contains "Signed off by Sam"; header "Human verified"; `GET /api/sessions/<id>` → `human_verified: true`.
11. **Invalidation by a later change.** `playUntil("u31")` → header "Not verified"; the rule's text ends with "Make the GP window three hours."; every live example of the rule shows `needs_review`; `review-open` → `signoff-invalidated` names Sam and `proposal.applied`.
12. **Re-verify.** `dod-mark-story_rules_confirmed` (the rule) and `dod-mark-examples_reviewed` (the flagged examples); re-sign-off → "Human verified".
13. **Export.** `export-open`; `export-class` = `backend.route.edit`; `export-fact-slot-route_identity` = "PUT /appointments/{id}/cancel"; `export-save` → "change 1 of 1"; `GET …/export/crb-backlog-item.json` → 200, `id` matches `/^a-patient-cancels-an-appointment-online-[0-9a-f]{8}$/`, `labels.exmap_signoff` non-empty, `acceptance_criteria` contains `Example: For a nurse, if the appointment is at 10am and they cancel at 9am, then it is refused under the 24-hour rule.` and `route_identity: PUT /appointments/{id}/cancel`, `structural_facts` has one line; `ticket.md` contains "## Open questions explicitly accepted as outstanding" and "practice manager"; `requirement.feature` contains `Rule:`, `Scenario:` and the accepted-outstanding comment; `evidence.json` has `verified: true`, `signoff.reviewer.name === "Sam"`, `export_options_history.length === 1`.
14. **Draft gate.** A second session with a story only: `GET …/export/ticket.json` → 422 with `checks`; `?draft=true` → 200, `title` starts with `[DRAFT / NOT VERIFIED]`, filename `DRAFT-ticket.json`.

A second, shorter test in the same file types three sentences through `ManualInput` (an add, an amend, a "Delete that example." that resolves) to prove the typed path yields the same ledger shapes as replay (lane "Typed", provider "Typed", `is_local: true`). Intent coverage: add u02, amend u07, remove u14, replace u20, clarify u12, reject u17, confirm u09, undo u21; clarification round-trip u05 (click) / u05→u06 (voice, unit test); accepted outstanding questions; sign-off; invalidation; re-sign-off; export.

## 14. The fixture conversation (`src/web/public/replay/conversation.v1.json`)

One file, three readers: the replay provider plays it; the e2e journey replays it with breakpoints and performs the human acts between utterances; the unit test `conversation.test.ts` runs classifier + bridge + core over it and checks each `expect` under `rules.v1`. `docs/FIXTURE-CONVERSATION.json` is the same conversation as a plain utterance array (`label`, `atMs`, `lane`, `speaker`, `text`); the shipped file wraps it:

```json
{ "version": 1, "title": "Appointment cancellation — classifier fixture v1",
  "story": "A patient cancels an appointment online", "speakers": { "remote": "Priya", "me": "Sam" },
  "utterances": [ { "label": "u01", "atMs": 0, "lane": "me", "speaker": "Sam", "text": "…", "expect": { … } }, … ],
  "ui": [
    { "after": "u30", "action": "accept_questions", "questions": ["$q_inprogress", "$q_behalf", "$q_dentist", "$q_twice"], "by": "Sam", "reason": "To be settled with the practice manager" },
    { "after": "u30", "action": "accept_acts", "proposals": ["$p17", "$p21", "$p27"], "actor": "Sam" },
    { "after": "u30", "action": "review", "checks": ["story_rules_confirmed", "examples_reviewed"], "actor": "Sam" },
    { "after": "u30", "action": "signoff", "reviewer": "Sam" },
    { "after": "u31", "action": "review", "checks": ["story_rules_confirmed", "examples_reviewed"], "actor": "Sam" },
    { "after": "u31", "action": "signoff", "reviewer": "Sam" },
    { "after": "u31", "action": "export_options", "capability_class": "backend.route.edit", "facts": [{ "slot": "route_identity", "text": "PUT /appointments/{id}/cancel" }], "actor": "Sam" },
    { "after": "u31", "action": "export" } ] }
```
`expect` per utterance is `{ intent, heard_intent?, confidence, ops: [...], clarification: {...} | null, resolves?: {...} }` with `bind` symbols (`$rule_cancel`, …) that the unit test binds to the ids core assigns; `$pNN` is the proposal id of utterance NN. `atMs` steps every 3–5 s (the e2e uses `speed=instant`). `review` is applied as `POST …/review/checks` (one human `confirm` per check listing the cards it covers); `accept_questions` as `question.accept`; `accept_acts` as `confirm { card_ids: [], proposal_ids: [p] }`; `signoff` as `signoff.record` with the exact sentence. The journey answers u05 by click and skips u06 (`expect` for u06 is exercised by the unit test only).

Expected proposals under `rules.v1` ("window" = the last four utterances; card texts as they stand at that point; the restore semantics of §5.2 apply — a restored card keeps its original `changed` provenance):

| label | at | speaker | utterance | expected proposal (rules.v1) |
|---|---|---|---|---|
| u01 | 0 | Sam (me) | Right, let's start with how cancellation works today. | `none`, 0 (`right,` stripped; no cue). |
| u02 | 4000 | Priya (remote) | A patient should be able to cancel online, but not within two hours of their appointment. | `add` 1.0 (A2 `should`/`not within`/`able to` + A3 `a patient should`). `card.create` rule `$rule_cancel`, text verbatim. |
| u03 | 8000 | Sam | Got it. So for example, if a GP appointment is at 10am and the patient tries to cancel at 9am, then it is refused. | `Got it.` dropped; `so` stripped. `add` 1.0 (A2 `for example`/`if a` + A4 `if … then`). example `$ex_gp`, text `If a GP appointment is at 10am and the patient tries to cancel at 9am, then it is refused.`, rule_id `$rule_cancel`. |
| u04 | 12000 | Priya | And for a nurse appointment, say it is at 10am and they cancel at 8am, that one is allowed because it is more than two hours. | `and` stripped (A6 remembers it). `add` 1.0 (A2 `say` + A4 `say it` + A6; `that one` masked). example `$ex_nurse`, text `For a nurse appointment, say it is at 10am and they cancel at 8am, that one is allowed because it is more than two hours.`, rule_id `$rule_cancel`. |
| u05 | 16000 | Sam | Delete that example. It's not what I meant. | `remove` 0.5 (D1; `that example` masked; R2 in sentence 2 ignored). Pool `[$ex_gp(u03,Sam), $ex_nurse(u04,Priya)]`, both in window; `touched[0] = $ex_nurse` by Priya ≠ Sam → ambiguous → `choose_target`, candidates `[$ex_nurse, $ex_gp]`, question `Which example do you mean: (1) For a nurse appointment, say it is at 10am and they cancel… (example, Priya), or (2) If a GP appointment is at 10am and the patient tries to… (example, Sam)?`, pending `[card.remove { "$choice", reason: "It's not what I meant." }]`. |
| u06 | 19000 | Priya | The GP one. | answer form 4: tokens `[gp]`, no intent cue, ratio 1.0 against `$ex_gp` → `choose [$ex_gp]`. `remove`, ops `[card.remove { $ex_gp, reason "It's not what I meant." }]`, confidence 1, `resolves { $p05, [$ex_gp], false }`, source `[u06, u05]`. Bridge: `clarification.answer { text }` then the proposal with `resolves_clarification_id`. |
| u07 | 23000 | Priya | Change that limit to 24 hours. | `amend` 1.0 (M1 `change` + M2 `to 24`). `that limit` → paraphrase "limit"; value `24 hours` → want rule; pool `[$rule_cancel]`; topic misses → pool of one → resolved. Amendment `{ from: "two hours", to: "24 hours", scope: null }` → `card.update { $rule_cancel, patch: { text: "A patient should be able to cancel online, but not within 24 hours of their appointment." } }`. Engine flags `$ex_nurse` `rule_changed`. |
| u08 | 27000 | Sam | Actually, make that 24 hours for nurse appointments only. Keep two hours for GPs. | `amend` 1.0 (M1 `make that` + M3 `actually`). Bare `that` → shortcut: `$p07`'s card ∈ rule pool, in window → resolved. Amendment `{ from: "24 hours", to: "24 hours", scope: "nurse appointments only" }` → `patch: { text_append: "Make that 24 hours for nurse appointments only. Keep two hours for GPs." }` → the bridge sets `patch.text` = current text + " " + append. Rationale says the wording should be reviewed. |
| u09 | 30000 | Priya | Yes, that's exactly right. | `confirm` 1.0 (F1 + F2). Pure confirm: `$p08` applied, `card.update`, cards `[$rule_cancel]` live → `confirm { card_ids: [$rule_cancel] }`. |
| u10 | 34000 | Sam | What about appointments already in progress? | `add` 1.0 (A2 `what about` + A5). question `$q_inprogress`, about_card_id `$rule_cancel` (token counts < 2 → last proposal's card, in window). |
| u11 | 38000 | Priya | Do we know if a nurse can cancel on the patient's behalf? | `add` 1.0 (A2 `do we know` + A5). question `$q_behalf`, about `$rule_cancel` (`nurse`, `cancel`, `patient` = 3 vs 2 for `$ex_nurse`). |
| u12 | 42000 | Sam | By appointment I mean a booked slot, not a walk-in. | `clarify` 1.0 (C1 + C2). No referent → story. `definition.refine { $story, term: "appointment", definition: "a booked slot, not a walk-in" }`. |
| u13 | 46000 | Priya | We also need an error case, when the cancellation fails because the system is down. | `add` 1.0 (A1 `we also need` + A2 `when the`). example `$ex_error`, text verbatim, rule_id `$rule_cancel` (no rule touched in the window → the only rule). |
| u14 | 50000 | Sam | Delete that example. | `remove` 0.5. Pool `[$ex_nurse(u04), $ex_error(u13)]`; window u10–u13 → only `$ex_error` touched → resolved. `card.remove { $ex_error, reason "" }`. |
| u15 | 53000 | Priya | Yes. | `confirm` 0.5 (F1). `last_proposal = $p14` (card.remove, applied) → `confirm { card_ids: [] }`, rationale "Confirmed the removal."; bridge → `confirm { card_ids: [], proposal_ids: [$p14] }` → `$p14` is `confirmed` (reviewed by voice). |
| u16 | 57000 | Priya | A receptionist must be able to override the cut-off. | `add` 1.0 (A2 `must`/`able to` + A3). rule `$rule_override`, text verbatim (`cut-off` kept). |
| u17 | 60000 | Sam | No, that's not what I said. | `reject` 1.0 (R1 + R2). `last_rejectable = $p16` in window → `interpretation.reject { $p16 }`. Engine: `$rule_override` → `interpretation_rejected`. |
| u18 | 64000 | Sam | A receptionist must not be able to override the cut-off. | `add` 1.0. rule `$rule_override2`. |
| u19 | 68000 | Priya | For a nurse, if the appointment is at 10am and they cancel at 9am, then it is refused under the 24-hour rule. | `add` 1.0 (A2 `if the` + A4; `the 24 hour rule` masked). example `$ex_nurse2`, text verbatim, rule_id `$rule_cancel` (5 matched tokens vs 0). |
| u20 | 72000 | Sam | Use this example instead of the old nurse one. | `replace` 1.0 (P1 + P2; add's A2 absorbed). No new content → `replacement_card = $ex_nurse2` (`$p19`, add, in window). Referent `the old nurse one` → named "old nurse", want example, exclude `$ex_nurse2` → pool `[$ex_nurse]`; score 1/2 ≥ 0.5 → resolved. `card.replace { card_id: $ex_nurse, replacement: null, replacement_card_id: $ex_nurse2 }`. Engine: `$ex_nurse` superseded by `$ex_nurse2`; one revision. |
| u21 | 76000 | Priya | Go back to the previous version. | `undo` 1.0 (U1 + U2). `undo { steps: 1 }` → `undoTarget(state, 1)` = the revision before u20: `$ex_nurse` live again (its `needs_review` as it was), `$ex_nurse2.supersedes` back to null; `$ex_nurse2` stays live. |
| u22 | 80000 | Sam | Right, so is the two-hour window the same for dentists? | `right,` then `so` stripped. `add` 0.5 (A5 only; `the 2 hour window` masked). question `$q_dentist`, text `Is the two-hour window the same for dentists?`, about `$rule_cancel` (tie with `$ex_nurse` broken rule-first). |
| u23 | 83000 | Priya | Let's park that for now. | `none`, 0. |
| u24 | 87000 | Sam | One more example: a GP appointment at 10am cancelled at 7am is allowed. | `:` splits. `add` 1.0 (A1 `one more` + A2 `example`). example `$ex_gp2`, text `A GP appointment at 10am cancelled at 7am is allowed.`, rule_id `$rule_cancel`. |
| u25 | 91000 | Priya | And a GP appointment at 10am cancelled at 9am is refused. | `add` 0.5 (A6 continuation of u24's example). example `$ex_gp3`, rule_id `$rule_cancel`. |
| u26 | 95000 | Priya | Delete that example, it duplicates the GP one. | `remove` 1.0 (D1 + D2; both referents masked). Pool examples `[$ex_nurse (changed u04), $ex_nurse2 (u19), $ex_gp2 (u24, Sam), $ex_gp3 (u25, Priya)]`; window u22–u25 → touched `[$ex_gp3, $ex_gp2]`; `touched[0]` by Priya = speaker → resolved `$ex_gp3`; reason `it duplicates the GP one`. |
| u27 | 98000 | Priya | Undo that, we still need it. | `undo` 0.5 (U1). `undo { steps: 1 }` → `$ex_gp3` restored (`restored_by` = `$p27`). |
| u28 | 102000 | Sam | Can a patient cancel twice in one day? | `add` 0.5 (A5). question `$q_twice`, about `$rule_cancel` (`patient`, `cancel` = 2, unique best). |
| u29 | 106000 | Priya | I'm not sure, let's leave that open. | `none`, 0 (`not sure` without `whether/if` is not a cue). |
| u30 | 110000 | Sam | I think that's everything for today. | `none`, 0. — UI: accept the four questions; accept acts `$p17`, `$p21`, `$p27`; review (confirm story + `$rule_override2`; confirm `$ex_nurse`, `$ex_nurse2`, `$ex_gp2`, `$ex_gp3`); sign-off by Sam → `isHumanVerified` true. |
| u31 | 114000 | Priya | Actually, make the GP window three hours. | `amend` 1.0 (M1 `make the` + M3). `the GP window` → paraphrase "gp window"; value `3 hours` → want rule; `$rule_cancel` contains `GPs` → 0.5, `$rule_override2` 0 → resolved. Amendment `{ from: null (several values), to: "3 hours", scope: null }` → `patch: { text_append: "Make the GP window three hours." }`. Engine emits `signoff.invalidated` and flags the rule's four live examples. UI reviews again, re-signs, sets export options, exports. |

After u30 the live index is exactly `{ $story, $rule_cancel, $rule_override2, $ex_nurse, $ex_nurse2, $ex_gp2, $ex_gp3, $q_inprogress, $q_behalf, $q_dentist, $q_twice }` (`$ex_gp` removed at u06, `$ex_error` at u14, `$rule_override` rejected at u17; the u20 replace undone at u21; the u26 removal undone at u27). Every intent appears at least once; the clarification round-trip is u05 → u06; ambiguous and unambiguous removes are u05, u14, u26; heard-but-not-actionable `none` is covered by the unit rows (§6.3) rather than the fixture.

## 15. README outline (`exmap/README.md`)

1. **What it is** — one paragraph; the interaction model; the honesty rules as a list.
2. **The one command** — `./start.sh` / `start.ps1` / `npm start`; what the launcher does (Node **22.12** and why; install when the lockfile changed; build when stale; `http://127.0.0.1:4317`; opens the browser); re-running; `EXMAP_PORT`, `EXMAP_HOME`, `EXMAP_NO_OPEN`, `EXMAP_COOP`; exit codes; the "port in use" and "another exmap is using this home" messages.
3. **Audio setup per OS** — Windows (share the screen with *Share system audio*, or the Teams tab with *Share tab audio*); macOS (Teams in a Chrome tab + *Share tab audio*; desktop Teams needs BlackHole 2ch as Teams' speaker and *Call source: Audio device*); Linux (tab audio; a PulseAudio/PipeWire monitor device); wear headphones (the echo note); the first-run model notice and the Web Speech notice; "no audio track" and "no sound heard"; Whisper sizes (base.en ≈ 77 MB, tiny.en ≈ 44 MB) and the browser cache. "Kept in step with `src/web/audio/lanes/guidance.ts`; the snapshot test is the contract."
4. **Providers and keys** — transcription providers and which are local; classifier `rules.v1` (offline default) and `claude` (`ANTHROPIC_API_KEY=<your key>` or `ANTHROPIC_AUTH_TOKEN=<your token>` / an `ant auth login` profile; `EXMAP_CLASSIFIER=claude|rules.v1`); fallback behaviour and how the UI shows it; every classification is in the ledger; **the only network calls**: the Whisper download (after consent), Web Speech (after consent, only when chosen), the Claude classifier (server side, optional).
5. **What it does not do (v1)** — §16 verbatim, rules.v1's stated limitations, the server-side STT seam, the pre-ledger hallucination filter and exactly what it drops.
6. **The state model** — the six states and the rendering rule for `rejected`; proposals vs state; "one step" = one utterance or one click; what a revision is and what changes it.
7. **The Definition of Done gate** — the five checks; what "mark reviewed" records; AI removals / undos / rejections need Accept or Reject (a spoken "yes" counts and is labelled); voice confirmations count by default and are labelled; accepted-outstanding questions; the sign-off record; invalidation and re-verification; "the reviewer name is self-asserted".
8. **The crb bridge** — the five files and what each is for; the vendored catalogue (source file, commit, date; update = copy); classes, structural vs value slots, `slot: text` facts; export options are ledger events outside the sign-off; `?draft=true`; a push into a crb deployment is a next step.
9. **Data location** — `~/.exmap/` layout, `EXMAP_HOME`, backup = copy the directory; a broken chain is refused with its row number and never repaired (how to inspect the row); a failed append marks the session broken until restart; `server.lock`.
10. **Running the tests** — `npm run check`, `npm run e2e`, `npm test -- --project web`; Playwright uses the preinstalled Chromium; `scripts/whisper-check.mjs`; the scripted conversation and `?replay=demo`.
11. **Development** — `npm run dev`; package layout; tsconfigs; where each part lives; `feat(exmap): …` commits.

## 16. Non-goals for v1

Speaker diarisation; reading Teams' active-speaker indicator; a Teams bot or Graph API integration; multi-user collaboration over the network; a database; cloud sync; server-side STT (a documented seam only); pushing directly into a crb deployment's API (the export files are the bridge); chaining exports by revision (`supersedes` is `""`); a wrong voice confirmation cannot be "unconfirmed" (edit the card, which clears the confirmation); re-linking an example or re-pointing a question by voice (UI only); multilingual Whisper models.

## 17. Open risks and `[VERIFY]` items

| Risk | Mitigation / fallback |
|---|---|
| Whisper hallucinates on silence/noise | VAD gates (≥ 200 ms of speech); the drop-only gate with the multi-word artefact table under energy-and-duration conditions; single words never dropped; count shown as a page diagnostic |
| Model download size/time (≈ 77 MB, ≈ 7 s load after download, ≈ 2 s cached) | consent notice with sizes; one progress bar; Cache API; tiny.en in the picker; the lane is live and queuing meanwhile |
| WebGPU absent or failing after download (as in the container) | adapter probe + explicit webgpu-then-wasm attempt; the device actually used is shown; `whisperDevice: 'wasm'` pins it. `[VERIFY WebGPU in a worker on Chrome 141; q8 speed on a real GPU]` |
| A wedged or crashed worker | every worker failure path posts an `error`; per-job deadline; one automatic forced restart; then the error is shown and the segment kept with Retry |
| Echo without headphones (the far end also appears in the `me` lane under the user's name; Chrome's AEC cannot cancel the Teams desktop app) | documented in the README and the `me` lane's help text; not solved in v1 |
| CPU load on WASM (RTF ≈ 0.2 per lane single-threaded) | one worker; backlog visible with a tiny.en suggestion; threads with COOP/COEP; `latencyHint: 'playback'`; the meter bypasses React |
| Display-capture audio stops when the video track is stopped `[VERIFY]` | keep the video track `enabled = false` and detached |
| `AudioContext` at 16 kHz for display-capture tracks `[VERIFY]` | default-rate context + `resampleTo16k()` |
| Chromium-only `getDisplayMedia` keys and `SpeechRecognition` not in TS 5.9 lib.dom `[VERIFY]` | local type widening |
| `--use-file-for-fake-audio-capture …%noloop` honoured by Chrome 141 `[VERIFY]` | drop the silent-badge assertion |
| Headless Chromium's `getDisplayMedia` branch `[VERIFY]` | assert whichever error branch it takes; the full table is unit-tested with a fake |
| Classifier latency (20–45 s per utterance with Claude) | the utterance POST answers before classification; serial per-session queue; "classifying…" chip; three posts in flight |
| Speech still in the backlog when the reviewer signs off | `pendingWork()` gate in the Review drawer with an explicit "Sign off anyway" |
| System audio includes everything (music, notifications) | guidance says so; the user is told to mute other apps |
| `@types/ws` exact version and `onnxruntime-web`'s pinned dev version | pinned at implementation step zero; `npm ls` must show one copy |
| A `prompt_version` change silently altering classifications | the SHA-256 of `FROZEN_SYSTEM` is pinned in a test; `SYSTEM_PROMPT_VERSION` is bumped deliberately |
| Two-decimal confidences and a future port of the ledger to another language | documented; every non-integer in a hashed body is refused unless ≤ 2 dp |

## 18. Decision log — cross-spec conflicts and how they were resolved

| # | Conflict (specs) | Decision | Why |
|---|---|---|---|
| 1 | Fixture file name: `brief-conversation.json` (core, audio) vs `conversation.v1.json` listed as `demo` (classifier, app) | `src/web/public/replay/conversation.v1.json`, listed in `index.json` under `name: "demo"`; `?replay=demo` | the most recent revisions (classifier, app) converged on it; one file, three readers |
| 2 | Fixture symbol field: `id?` (audio, core) vs `label` (classifier, app driver) | `label` | `id` on the wire means the utterance id the provider mints; a fixture symbol must not look like one |
| 3 | Fixture extra keys: audio said `story`/`speakers`/`ui` move out; app needs `story` to create a session from `?replay=` | keep `story`, `speakers`, `ui`, `label`, `expect`; `parseReplayFixture` tolerates exactly those and refuses any other unknown key | one file serves the provider, the journey and the unit test without a generated copy |
| 4 | Utterance POST timing: classifier/app = `201` at once; audio = synchronous reply with a 150 s sink timeout | `201` on append, classification over the WebSocket, `?wait=1` for tests; `HttpUtteranceSink.timeoutMs = 15 000`; three posts in flight kept | a 45 s HTTP wait per utterance would stall the client for the whole classification; audio's own note says the timeout drops once the server answers early |
| 5 | `PostOutcome` for 4xx: audio keeps 408/429 transient; core/app say every 4xx but `DUPLICATE_ID` is refused | 408 and 429 remain transient; every other 4xx is refused | a rate-limit/timeout status is retryable by definition; the server never emits them, so nothing changes in practice |
| 6 | `last_proposal` statuses: core's selector returns `applied` only; classifier wants `applied | confirmed`; app walks `proposal_order` itself | `select.lastAppliedProposal(state, { aiOnly, statuses })` in core; the bridge passes `statuses: ["applied", "confirmed"]` | one implementation of the walk; the classifier needs to see a confirmed one to say "already confirmed" |
| 7 | `isRejectable`: app re-implemented core's `REJECT_NOT_LATEST` condition | `select.isRejectable(state, pid)` exported by core; the bridge calls it | the bridge's flag and core's refusal cannot drift |
| 8 | `CardPatch.text_append` (classifier C3) vs core's `Amendment.append` on the template | core has no `text_append`; the classifier schema keeps it (model-facing); the bridge resolves it into `patch.text`; ambiguous amends carry `Amendment` on the template and core recomputes per chosen card; `Amendment.to` may be `""` when `from` is null | keeps core's patch minimal and the chosen-card computation deterministic and offline |
| 9 | Intent `none` as a ledgered proposal (classifier C4) and `heard_intent` (C6/app 10.1.7) | no `none` proposals; `heard_intent: HeardIntent` is a field of `classification.record` / `utterance.classified` / `ClassificationRecord` | every classification is already ledgered (core §0.11); a field beats a rationale prefix for honesty and for the transcript chip |
| 10 | A spoken "Yes." after a removal / undo / rejection: classifier = `none`; core/app = review the act | the classifier emits `confirm { card_ids: [] }`; the bridge maps it to `confirm { card_ids: [], proposal_ids: [last_proposal.id] }`; the frozen prompt and I4 say so; fixture u15 and rules row 40 updated; `accept_acts` after u30 is `[$p17, $p21, $p27]` | brief §0 lists Confirm as "record human confirmation"; a "yes" to a removal is exactly that and must not be dropped |
| 11 | `pending_clarification.text_answers` (core 13.1.6) vs no extra field (app) | no extra field | text answers are already visible as recent utterances (voice) or as the utterance being classified (typed) |
| 12 | Unlabelled speaker as `""` (audio 12.3.2) vs `null` (core, classifier, app) | `null` everywhere; the classifier's tie-break guard is `last_speaker !== null` | `null` is the honest value and core's declared type |
| 13 | `ReplayProvider.playUntil` (classifier B2) vs `play(speed, { until })` + `step()` (audio) vs a slicing `ReplayDriver` (app) | native `play(speed, { until })`, `step()`, `skip(until)` on the provider; `ReplayDriver` is a thin wrapper exposing `window.__exmap.replay` | one implementation of "play up to"; `skip` is needed for the click-answer variant |
| 14 | Where the fixture replay unit test lives: `tests/unit/classifier/conversation.test.ts` (classifier) and also `tests/unit/server/bridge.test.ts` (app) | one replay test, `conversation.test.ts` (per-row expectations, `refused` empty, final index, verified/invalidated/re-verified); `bridge.test.ts` is a mapping table only | no duplicate 31-row assertions to keep in step |
| 15 | vitest globs: `tests/unit/audio/react/**` (app) vs `tests/unit/web/audio/` (audio); `src/classifier/**/*.test.ts` (app) vs tests under `tests/` (classifier) | React smoke tests under `tests/unit/web/audio/` (covered by the web project's glob); no tests under `src/` | one convention: all tests under `tests/` |
| 16 | Export options: an append-only side file `export-options.jsonl` (app) vs a ledger event (app's own §10.1.6 ask) | `export.options_set` is a core event and command; `MapState.export_options`; no side file; `META_INVALID` no longer covers a bad options line | brief §1.8: everything is an event; one file, one discipline; evidence reads them from state |
| 17 | ORT `allowedPath`: asyncify + jsep (app) vs asyncify only (audio) | the asyncify pair only; `ORT_RUNTIME_MISSING` if either is absent | transformers.js 4.3.1 never references `jsep` |
| 18 | Node floor: brief "≥ 22" vs app 22.12 | 22.12, documented with the reason | Vite 8 fails below it with an opaque error; failing early and clearly serves the one-command promise |
| 19 | `messages.parse` (brief) vs `messages.create` + `format.parse` after `stop_reason` (classifier) | `create` + `format.parse`, same request shape and schema; the operator may flip it, with the stated consequence | provenance must name refusals and truncations as what they are (brief §1.11, §4) |
| 20 | `CLAUDE_MODEL` in a committed file vs brief §1.12 | `CLAUDE_MODEL = "claude-opus-5-5"` in `constants.ts` | §1.7 fixes the model; §1.12 governs the authoring session's identifiers |
| 21 | `device: 'auto'` (brief §6) vs an explicit probe (audio) | explicit probe, then `webgpu` tried and caught, then `wasm`; the setting is still labelled `auto` | brief §1.11 requires naming the device actually used; `auto`'s fallback is silent |
| 22 | `actorForVoice` fallback "Call"/"Me"/"Typed" (app) | `utterance.speaker ?? "(<Call|Me|Typed>, no speaker label)"` | the recorded actor must not read like an assigned identity when none was |
| 23 | `SYSTEM_PROMPT_VERSION` "v2" (classifier phase 2) | `"exmap.classifier.claude.v1"` — the first shipped prompt | versions count shipped prompts, not spec revisions; the wording changed in #10 anyway |
| 24 | The journey's step 5 kept u14's removal unreviewed to "prove the gate" (app) | with #10 the removal is reviewed by u15; the gate is proved by the u17 reject and the u21/u27 undos | consistent with the fixture; the gate is still exercised |
| 25 | Clarification "preview" of the pending removal (brief §0 step 4) | `ClarificationItem` renders a "Will: <operation>" line for templates and pending operations | the brief asks that an ambiguous removal be previewed, not just asked about |

Not adopted from the specs' own rejected-findings lists: nothing is re-opened here; every item those sections rejected stays rejected for the reasons they give.
