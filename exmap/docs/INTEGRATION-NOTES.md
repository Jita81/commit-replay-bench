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

## 2026-10-16 — core (`src/core/`, `tests/unit/core/`)

1. **`src/core/shape.ts` added** (internal, not in the §3.1 file list): step (0) of `apply()` — the command's shape (types,
   enums, unknown keys → `BAD_SHAPE` naming the path), text normalisation, the 2-dp confidence rule, definitions. Every
   stored value is rebuilt from validated fields. `apply.ts` imports it; nothing else needs to.
2. **The §5.10 scenario is 104 events, not 60.** `tests/unit/core/fixtures.ts#scenario()` runs every item §5.10 lists
   (30 commands plus the server-style `classification.record` after each AI proposal) and lands on 104 chained events;
   TEST-PLAN §1 case 5 asserts `count === events.length` (and > 60), not the literal 60.
3. **A batch cannot name an id minted inside the same batch.** §5.4 validates pass 1 with placeholder ids and mints only
   in pass 2 (so a refusal never calls `nextId`); consequently proposal 2 of a batch cannot target a card proposal 1
   creates. TEST-PLAN case 41's "create then update of the created card" is replaced by "update then identical update
   → `NO_CHANGE` at `proposal 2 of 2`" / "update then update → version 3", which proves the same thing (proposal n is
   validated against the result of 1..n−1). The bridge must not emit such a batch.
4. **DoD check 5 compares structure, not a hash.** `dodReport(state, opts?)` has no `Sha256Fn` (its §5.6 signature is
   fixed), so "the current revision hash equals computeRevision of the snapshot" is implemented as `canonicalJson(
   canonicalState(current.snapshot)) === canonicalJson(canonicalState(state.cards))` plus `seq ≥ 1`, `event_id`, head
   hash non-empty. The hash itself is re-checked by `replay()` on every load and by `apply()` on every undo.
5. **`ChainError.seq` is the failing event's own `seq` field**, `event_id` its id, and `detail` names the position
   (`event evt_7 at position 5 …`). For `SEQ_MISMATCH` these differ by definition; the server's `BrokenInfo.row` should be
   the index of `event_id` in the file (TEST-PLAN §1 cases 7 and 8 word it both ways; the core tests assert the event's
   seq plus the position in `detail`).
6. **`replay([])` is `{ ok: false, error: { code: "EMPTY_LEDGER" } }`** (the `ReplayError` union has the code; the
   session id is unknowable from no events). The server opens a new or empty session with `initialState(session_id)`.
7. **Voice confirmations carry the speaker as `classifier.actor`.** Core copies `proposal.classifier.actor` into
   `confirmation.by.actor` (§4 `ConfirmedBy.actor` wants the speaker label; §4 `ClassifierStamp.actor` says null for a
   pure AI interpretation — the two disagree for a voice "yes"). The bridge should set `actor` = the lane's speaker label
   (or null when none) on `confirm` proposals only; AI `card.remove` / `undo` / `interpretation.reject` keep `actor: null`
   so `select.unreviewedActs` lists them. The DoD detail then reads `confirmed by voice (rules.v1, 1, speaker Priya)`
   / `speaker unlabelled`.
8. **Refusals added where §5.4 was silent:** a `provider: "human"` stamp with `actor` null/empty → `ACTOR_REQUIRED`;
   `confirm.card_ids` / `proposal_ids` with a duplicate → `BAD_SHAPE`; `patch.answer: ""` → `EMPTY_TEXT` (null re-opens);
   `undo.to_revision_seq` non-integer → `BAD_SHAPE`; a template `card.replace { replacement_card_id }` naming a non-live
   or already-superseding card is refused at ask time (`CARD_NOT_LIVE` / `REPLACEMENT_INVALID`). A `NewCard` with
   `rule_id` / `about_card_id` absent is read as `null` (the one lenient field; every other missing field is `BAD_SHAPE`).
9. **Review-state-only inverse (interpretation.reject):** `needs_review = before.needs_review` is restored only while the
   flag that proposal set is still the card's current flag; a confirmation or a later rule change since then stands.
   (Literal §5.4 would re-flag an example a person had reviewed in between; found by TEST-PLAN case 36.)
10. **Undo diff** leaves a card that is already `rejected` and absent from the target snapshot as it is (it keeps
    `removed` / `interpretation rejected` rather than being relabelled `undone`); a superseded card absent from the
    snapshot becomes `rejected / undone` with `superseded_by: null` (invariant). A card leaving the live set (remove,
    supersede, reject, undone) gets `needs_review: null` (§5.8 "cleared by leaving the live set").
11. **`affected_card_ids`** is derived by the reducer from `operation` + `effects` (§4 "primary targets"): create → the
    created id; update/remove/refine → `[card_id]`; replace → `[old, replacement]`; confirm → `card_ids`; reject/undo →
    every effect's card. A rule update's flagged examples are in `effects` but not in `affected_card_ids`.
12. **`confirms_proposal_ids`** (`byCards`): candidates are each changed card's `changed.proposal_id` plus, for a card
    whose `needs_review` flag is being cleared, the proposal whose outcome event set that flag; a candidate is confirmed
    when every live card among its effects is `confirmed` with `needs_review === null`. So confirming a rule and its
    flagged examples in either order confirms the rule update; confirming only the replacement of a replace does not
    confirm the replace while its re-linked examples are unreviewed (TEST-PLAN case 32).
13. **`select.openQuestions` / `counts.open_questions`** = live questions with `answer === null`, accepted ones included
    (an accepted question is still unanswered — brief §1.11); `counts.accepted_questions` counts the accepted ones.
    `select.statusLabel` of a transient `proposed` card (between `made` and `applied` in a WS stream) is `"applied"`.
14. **Extra exports** beyond §5.10: `select.ACT_KINDS` (the three reviewable act kinds), `dod.describeAct(state,
    record)` (the check-3 wording for one act, for the tray), `effects.ts` helpers (`stripHistory`, `isLive`,
    `contentEquals`, `isSubstantiveEffect`, `applyEffects`, `invertEffects`, `diffToSnapshot`, `rejectability`,
    `primaryTargets`, `deepEqual`) — internal, not re-exported from `index.ts`.
15. **Timestamps:** `ctx.now()` is called once per emitted event (pass 2 only; a refusal calls neither `now` nor
    `nextId`); `export.options_set` reuses its event's `at` for `options.at`. Ids are minted in the order they appear:
    event id first, then the payload's ids (`card` inside the made effect for a create; `prop` inside
    `clarification.answered` for a resolved clarification; `clar` / `sig` after their event id).

## 2026-10-16 — classifier

1. **`text_append` carries no `Amendment: ` prefix.** §6.3 says the append form is `"Amendment: " + <utterance minus
   correction cues>`; §14 (u08, u31) and the e2e (§13.1 step 3, "ends with 'Keep two hours for GPs.'") show the bare
   sentence. rules.v1 follows §14: `patch.text_append = "Make that 24 hours for nurse appointments only. Keep two hours
   for GPs."`. The bridge's §8.7 rule ("`append` = the `text_append` minus a leading `Amendment: `") accepts both forms, so
   nothing else changes; the bridge builds `patch.text = card.text + " " + text_append.trim()` as designed.
2. **Seam for the bridge — `last_rejectable` / `last_proposal` need a source utterance.** `LastProposalRef.utterance_id`
   is required (`ClassifierInputSchema`; `classify()` throws `E_CLASSIFIER_INPUT_INVALID` on `undefined`), and core's
   `select.isRejectable` is true for a human proposal too (the story made at session creation is rejectable). The bridge
   must map only proposals with a non-empty `source_utterance_ids` into `last_rejectable` (`last_proposal` already is
   `aiOnly`). Verified against core as landed with a scratch bridge over the whole §14 fixture.
3. **The removal reason does not survive a clarification round-trip.** Core's `OperationTemplate` for `card.remove` is
   `{}` (frozen type), so the pending operation the bridge rebuilds for u05 is `card.remove { "$choice", reason: "" }` and
   the proposal that resolves it at u06 carries `reason: ""`. The fixture's u06 `expect` therefore asserts kind and target
   only (§14 shows the reason). If the reason should be kept, the bridge can put it in the asking proposal's rationale
   (`" — <reason>"`, as §8.7 already does for a resolved removal) — no classifier change needed.
4. **DoD check 3 vs §13.1 / §14 after the undone removal (u26 → u27).** With core as landed, the AI removal `$p26` keeps
   status `applied` after the undo (§5.9 "proposals whose effects were undone keep their historical status") and
   `select.unreviewedActs` lists it, so the fixture's `accept_acts` `[$p17, $p21, $p27]` leaves `changes_resolved` failing
   at the u30 sign-off (`SIGNOFF_DOD_FAILED`). Either core's check 3 (and `unreviewedActs`) excludes an act whose effects
   were reverted by a later undo — then §13.1's "exactly three unreviewed acts" holds — or the fixture's `ui` step gains
   `"$p26"` and §13.1 becomes four. `tests/unit/classifier/conversation.test.ts` follows the fixture as it stands and
   passes end to end once one of the two is chosen (verified with `$p26` accepted in a scratch run: u31 invalidates the
   sign-off, the re-sign-off verifies, the final live index is the §14 set, counts 31/31).
5. **`conversation.test.ts` needs the real bridge.** It imports `buildClassifierInput`, `toCoreCommands` and `intentOf`
   from `src/server/classifier-bridge.ts` (still the step-zero stub at the time of writing) and `testCtx()` from
   `tests/unit/core/fixtures.ts`; every other classifier test is self-contained.
6. **Fixture `expect` blocks added** to `src/web/public/replay/conversation.v1.json` (utterance texts, labels, timings
   and the `ui` array untouched; asserted equal to `docs/FIXTURE-CONVERSATION.json` at generation). Shape per row:
   `{ intent, heard_intent? (none rows), confidence, ops: [{ kind, …fields with $symbols, bind?: "$symbol" }],
   clarification: { kind, candidates: ["$…"], pending: [ops with "$choice"] } | null, resolves?: { proposal_id: "$pNN",
   chosen: ["$…"], dismissed } }`. `bind` on a `card.create` names the symbol bound to the id core mints; `$pNN` is the
   id of the main (last) proposal of utterance NN's batch; `$story` is the story made at session creation.
7. **Cue-table details that differ from the literal §6.3 lists**, each forced by a §14 row or a TEST-PLAN row: A5's
   opener list leaves out `when` (it opens examples; row 31 "When we say cut-off…" must not be damped); A3 is evaluated on
   the sentence and on each clause after a comma (row 32); A3's excluded subjects also include yes/no/okay/right/
   correct/exactly/actually/sure/fine/perfect/great/good/so/well/and/but/answer (otherwise "Yes, that's exactly right"
   scores add, and row 54's "the answer is" scores a rule); the rule-kind cue search skips a sentence-initial
   interrogative opener (row 47: "Should we delete that?" is A5, not A2 `should`); D1 `cut` ignores `cut off`/`cut-off`
   (u16); M3 `i meant` is ignored inside `not what i meant` (row 20); a referent paraphrase (`that limit`, `the GP
   window`) is only read after a change/remove/undo/replace verb, after a sentence-initial interrogative, or at the
   sentence start (u13's "when the cancellation fails" must stay an A2 `when the` cue).
8. **Signatures beyond the design's one-liners:** `parseAnswer(s1, pending, rest, s1Scores, ctx: { scoreOf, cards })`
   takes the scorer and the card index as a fifth argument (a module cycle otherwise; the design's four arguments are
   kept in order); `resolveClarificationAnswer` returns a full `ClassifierProposal` (the caller asserts invariants);
   `extractReason(sentences, cueIdx, cueEnd)`; `replacementDraft(sentences, minWords)`; `detectKind(sentences, { input,
   continuation })`; `askTarget(res, op, intent, verb, input, { question?, kind? })`.
9. **Claude provider:** `createAnthropicClient()` is called lazily on the first `classify()` so a constructor failure
   is provenance (`auth` / `transport`), never a crash; `selectProvider` trims and lower-cases `EXMAP_CLASSIFIER`;
   `validateModelProposal` adds the fallback code `invalid:invariant:<I#>` for a repaired proposal that still violates an
   invariant (never thrown); the pinned SHA-256 of `FROZEN_SYSTEM` is
   `be2ecbc5f192cd57604441f89971cce95aae00d520b2065b7eacaac2d656a626` (`SYSTEM_PROMPT_VERSION` `exmap.classifier.claude.v1`).
10. **Candidate labels never invent a speaker:** `"<title> (<kind>, <speaker>)"` uses the assigned label; a card made in
    the UI reads `by hand`; a voice card with no label reads `<lane>, no speaker label` (or `typed` for the manual lane).
11. **Extra exports from `src/classifier/index.ts`** for the server: `createRulesClassifier`, `classifyRules`,
    `createClaudeClassifier`, `FORMAT`, `createAnthropicClient`, `FROZEN_SYSTEM`, `renderUserMessage`,
    `validateModelProposal`, type `CreateResult`; `schema.ts` also exports `INTENT_OF_OP`, `idsOfOperation`,
    `targetCardIds`.

## 2026-10-16 — export (`src/export/`, `tests/unit/export/`)

1. **`src/export/questions.ts` added** (internal, not in the §3.1 file list): the one partition of live questions that
   `ticket.md` and `requirement.feature` share — answered+confirmed, else accepted outstanding, else answered-but-unconfirmed,
   else unresolved — mirroring core's DoD check 4 so the files and the gate cannot disagree; plus `collectDefinitions`
   (dedupe by term, first in card_order wins, sorted) and `featureLevelQuestions`.
2. **`ExportContext.head` carries `event_id`** (`{ seq, hash, event_id }`): §12.1 listed only `seq`/`hash`, but
   `Evidence.chain_head` (§4) needs the head event id. Only the export module constructs the context.
3. **`DRAFT_WATERMARK` is defined in `text.ts`** and re-exported from `index.ts` under the §12.1 name, so the mappers can
   import it without a runtime cycle through `index.ts` (which imports them). Same value.
4. **Titles.** `storyTitle` / `titleOf(text, max)` drop the sentence's trailing full stop (and a trailing `,;:`) so a
   one-sentence story and a multi-sentence one title alike; truncation is at a word boundary with no ellipsis (§12.1 names
   none). A Scenario title is `titleOf(oneLine(example.text), 80)` — the whitespace-collapsed first sentence, not the
   first line of a multi-line example. `exportFile` falls back to the session title, then `"Untitled requirement"`, when
   there is no live story; the backlog description / ticket body then say `No story card is recorded in this session.`
5. **`parseGwt` with a "when" opener fills `given`** (`when: null`): the `Gwt` shape of §12 has a required `given` and an
   optional `when`, and "When X, then Y" is a conditional Gherkin states as Given X / Then Y. A "when" that follows "then"
   is prose, not a split; a dangling "and" before the next keyword is stripped along with the leading one.
6. **Accepted-outstanding wording** in `ticket.md` and the feature comments is
   `accepted as outstanding by <by>: <reason> (no answer recorded)` — not §12.3's literal `(not answered)`, because
   TEST-PLAN §5.3 requires that section never to contain "answered". A question accepted outstanding that also carries an
   unconfirmed classifier answer stays in that section with `(an unconfirmed answer is recorded: <answer>)`; an answered
   question nobody confirmed is listed under "Answered questions" with `(answer recorded, not confirmed)`.
7. **Draft on a verified map** (`draft && verified`): still watermarked and `-draft-` in the id, but the banner reads
   `exported as a draft at the caller's request; the map is human-verified and no check fails` and the failing-checks
   summary says `none (…)` — never the claim that the map has not passed verification. `evidence.export_options` is `null`
   while no options were ever set (the seq-0 default is never written to a file).
8. **Seam for the server (`routes/export.ts`).** `exportFile(input, file)` returns `ExportResult` with `filename` already
   `DRAFT-`-prefixed on drafts and `content_type` from the exported `CONTENT_TYPES` map (`application/json`,
   `text/markdown; charset=utf-8`, `text/plain; charset=utf-8`); JSON bodies are 2-space pretty-printed with a trailing
   newline. An `ExportRefusal` carries `detail` = exported `REFUSAL_DETAIL` (the §8.5 text), `checks` and `signoff`
   (`none` / `invalidated` + `invalidated_by_event_id` / `active_but_stale` / `active_but_dod_failed`) and maps to 422
   unchanged. `EXPORT_FILES` lists the five file tokens for the `EXPORT_FILE_UNKNOWN` check. Extra exports beyond §12:
   `EXPORT_FILES`, `CONTENT_TYPES`, `REFUSAL_DETAIL`, `defaultExportOptions(now)`, `itemIdFor(baseTitle, draft, hash)`,
   `acceptanceCriteria`, `exampleLine`, `factLine`, `description`, `ticketTags`, `POINTS_FOR_SIZE`, `titleOf`, `oneLine`,
   `groupQuestions`.
9. **Fixtures.** `tests/unit/export/fixtures.ts` builds literal `MapState`s (never through `apply()`): `verifiedState()`
   passes core's `isHumanVerified` (asserted), with `invalidatedState()`, `activeButDodFailedState()`, `staleState()`,
   `draftState()` (unattached examples, an unresolved question) and `storyOnlyState()` (e2e §13.1 step 14). The revision
   hash is `sha256(canonicalJson(canonicalState(cards)))` so `evidence.json`'s hash identity is checked for real. Other
   modules may import them.
10. **Verified at the end of the module**: `npx vitest run tests/unit/export` → 6 files, 69 tests passed;
    `npm run typecheck` reports no error in `src/export` or `tests/unit/export` (the one tree error at that moment was in
    `src/web/audio/providers/replay.ts`, another module mid-edit). The vendored catalogue's sha256
    (`de1012c2…0cf1`) is checked in `catalogue.test.ts` against the generator's output.

## 2026-10-16 — audio (`src/web/audio/`, `src/web/public/pcm-worklet.js`, `tests/unit/audio/`, `tests/unit/web/audio/`, `tests/e2e/audio.spec.ts`, `scripts/whisper-check.mjs`)

1. **Public surface is `src/web/audio/index.ts`.** The web module needs: `AudioController` (+ `AudioControllerDeps`),
   `audioTestHooks(controller)` → `{ audio: { state, postQueueIdle, segmentsClosed, pendingWork }, replay: { playUntil,
   skip, playAll, position } }` (exactly the §7.7 / §10.9 names; `main.tsx` can assign `window.__exmap = audioTestHooks(c)`
   or spread it), `useAudioController`, `CaptureControls { controller, media? }` (renders `ConsentNotice` and
   `GuidancePanel` itself, so mounting it gives the whole audio UI), `ManualInput { controller, clock, speakers }`,
   `ReplayControls { controller, replay, fetchFn? }`, `SpeakerStore({ userName, storage, sessionStorage })`,
   `createSessionClock(session.created_at)`, `HttpUtteranceSink({ baseUrl, sessionId })`, `parseReplayFixture`,
   `fetchReplayIndex` / `fetchReplayFixture`, and the `ReplayFixture` / `AudioState` types. `ReplayDriver` (web's
   `replay/driver.ts`) calls `controller.playReplay("instant", { until })`, `controller.skipReplay(target)`,
   `controller.idle()` and reads `getState().replay.index` for `position`.
2. **Controller extras beyond §7.7** (additive): `resumeReplay()`; `applyReplayQuery(location.search, fetch?)` implements
   the `?replay=<name>&speed=&autostart=1` hook of §7.4 (loads from `/replay/index.json`, presses Play with `autostart`),
   so `App` only calls it once the session screen is open; `clearDownloadedModels()`; `segmentsClosed()`; `os`;
   `replayProvider`. Deps extras: `providerDeps` (fake worker / recogniser / timers for tests), `sessionStorage`, `os`,
   `isSecureContext`, `timers`. `AudioState` extras: `refused` (the post queue's refused utterances with the server's
   reason), `webSpeechAvailable` / `webSpeechReason`, `modelDeclined`. `updateSettings(patch)` applies the fields it can
   and returns `false` when a lane-bound field (`provider`, `deviceId`, `remoteSource`) was refused for a requesting|live
   lane; it never throws.
3. **`AudioGraph.attach(lane, stream, onFrame)`** takes the frame handler as a third argument (§7.3 names two); `detach`
   posts `{ type: "flush" }`, waits for `{ type: "flushed" }` (500 ms cap) and delivers the partial frame through the
   same handler first. `WebAudioGraph({ createContext?, createWorkletNode?, workletUrl?, flushTimeoutMs? })` is injectable
   so the unit test proves "addModule once across two lanes" with fakes.
4. **`CaptureLane` owns its VAD + segmenter** (`deps: { id, media, graph, clock, speaker: () => label, hooks, source?,
   segmenter?, vad?, isSecureContext? }`; hooks `onView`, `onSegment`, `onGuidance`, `onDeviceUnavailable`, `onLevel`,
   `onFlush`). Frame time = `startedAtMs + frameIndex × 20` (sample-accurate, not wall clock). The lane's `start()` is a
   non-async function so the media request is synchronous inside the click; it returns the settlement promise.
5. **`TranscriptionQueue` extras:** `pause()` (held while the model is not loaded; segments accumulate), `resume()`,
   `failWaiting()` (a declined download moves the waiting segments to `failed[]` — visible as "could not be transcribed",
   Retry re-asks for consent — nothing is dropped silently).
6. **Whisper worker (`providers/whisper.worker.ts`)** follows the spike's verified shapes: `env.backends.onnx.wasm.wasmPaths`
   and `numThreads` are set inside the worker from the `load` message; `device: "auto"` = `navigator.gpu.requestAdapter()`
   probe → try `webgpu` → catch → `wasm` (the device actually used is in `ready`); `threads` in `ready` is the wasm thread
   count only when `crossOriginIsolated`, else 1. Verified: the module bundles under Vite 8.3.4 with `worker.format: "es"`
   (a scratch entry importing `src/web/audio/index.ts` emitted `whisper.worker-*.js` ≈ 547 kB plus the dead 26.9 MB wasm
   copy that `scripts/build.mjs` step 3 deletes). Not verified here: WebGPU inside a worker on Chrome 141 (no GPU in the
   container; `wasm` is the path the spike proved).
7. **`@axe-core/playwright@4.14.0` types `page` against the hoisted `playwright-core@1.64.1`**, not `@playwright/test@1.56.1`'s
   `Page` (TS2740 in `tests/e2e/audio.spec.ts`). The lockfile is frozen, so the spec casts
   `page as unknown as import("playwright-core").Page` (same object at runtime). The web module's `axe.spec.ts` will hit
   the same; the integration phase may pin `playwright-core` to `1.56.1` in the lockfile instead.
8. **E2E seams the audio spec assumes from the web module** (the audio spec cannot run until the session screen exists):
   `data-testid="transcript"` with rows `utterance-<id>` showing the lane name, the speaker (or "— (no speaker label)"),
   `mm:ss` and the provider chip ("Replay" / "Typed"); `data-testid="header-utterance-count"` on the header's utterance
   counter (E1 "the session counter equals 31" — the design names no id; E1 also checks `GET /api/sessions/:id`
   `counts.utterances`); `clarification-<cid>` with `clarification-candidate-<cid>-<cardId>` buttons (E1a); the session
   screen mounting `CaptureControls`, `ManualInput`, `ReplayControls` and `window.__exmap` with `testhooks=1`.
   `scripts/whisper-check.mjs` additionally reads `GET /api/sessions/:id/events` (an array or `{ events }`).
9. **Headless remote lane (E4):** when the error is `NOT_ACTIVATED` no guidance opens by itself (design §7.2 lists
   `PERMISSION_DENIED` / `UNSUPPORTED` / `NO_DEVICE` / `NO_AUDIO_TRACK`), so the spec opens Setup help and asserts the
   Linux page; which branch headless Chrome 141 takes is recorded by the run, not assumed.
10. **Hallucination table and segmenter arithmetic** are as §7.5 / §7.3; the hard cap closes on the frame where
    `tMs + 20 − startedAt ≥ 15000` and trailing silence on `tMs + 20 − lastSpeechAt ≥ 600` (the design's formulas; 29 silent
    frames after the last speech frame close a segment). The VAD seeds the floor with the minimum of the first 10 frames
    capped at −64 dB.
11. **Step-zero `.gitkeep` files** in `tests/unit/audio/` and `tests/unit/web/audio/` were removed (replaced by tests).
12. **`src/web/audioContract.ts` (web) is honoured:** every audio component renders with `{ controller }` alone —
    `CaptureControls`, `ReplayControls` (status from the hook), `ManualInput` (`controller.clock` and the live speaker
    labels), `ConsentNotice` (follows `state.notice`, renders nothing while null) and `GuidancePanel` (follows
    `state.guidance`); the explicit props of §7.7 remain as optional overrides. `AudioControllerDeps.speakers` is
    `SpeakerStoreLike` (the contract's type), `controller.clock` / `controller.speakers` are exposed, and `updateSettings`
    / `submitManual` return booleans that a `void` contract ignores. The loader's `./audio/react/<X>.js` imports resolve
    to the `.tsx` files under Vite's bundler resolution.
