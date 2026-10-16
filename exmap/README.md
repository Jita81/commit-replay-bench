# Example Map Live (`exmap`)

> A local-first, voice-driven requirements modeller that turns live discussion into a dynamically evolving, fully
> traceable Example Map, lets people create, amend, reject and remove elements through natural conversation, and
> produces a requirement only after explicit human verification.

## What it is

Example Map Live listens to a requirements conversation — a Teams call captured in your browser, your own
microphone, typed text, or a scripted replay — and turns each utterance into a *proposal* against an Example Map: one
story, its business rules, the examples that illustrate them and the questions still open. A deterministic engine
validates each proposal and applies it, so the map evolves while people talk; anyone can create, amend, reject,
remove, replace, clarify, confirm or undo by speaking or by clicking. Every change is an event in an append-only,
hash-chained ledger with its provenance (which utterance, which classifier, how confident, who reviewed it). The
product produces a requirement — and the files that feed it to the crb factory — only after a responsible person has
reviewed the complete map and signed it off against a Definition of Done; any later substantive change invalidates
that sign-off. The human owns the meaning; the software owns the mechanics of structuring it.

The interaction model, end to end:

1. **Talk naturally.** "A patient should be able to cancel online, but not within two hours of their appointment."
   The utterance is recorded with its lane, the speaker label someone assigned, the transcription provider and timing.
2. **Watch the map populate.** A rule card appears with its provenance; examples and questions follow.
3. **Change your mind by talking.** "Actually, make that 24 hours for nurse appointments. Keep two hours for GPs."
   The rule gains a new version, its history is kept, and every example linked to it is flagged *needs review*.
4. **Remove or redo conversationally.** "Delete that example. It's not what I meant." If two examples could be meant,
   the system asks which one (and previews what it will do) instead of guessing. "Go back to the previous version."
   restores the earlier state as a new revision; nothing is erased from the ledger.
5. **Human-verified completion.** The reviewer works through the five Definition of Done checks, resolves or
   explicitly accepts the open questions, and records a sign-off naming the exact revision.

Honesty rules the product keeps:

- An open question accepted as outstanding stays unanswered; it is never described as "answered".
- When the offline classifier stands in for the Claude classifier, every proposal it produced says so.
- A capture lane with no audio track is an error with per-OS guidance, never a silent lane; a live lane with no sound
  says "no sound heard".
- Speaker identity is only the label a person assigned to a lane. There is no diarisation.
- Every number shown about a session (counts, confidence) is derived from the ledger; page diagnostics (dropped
  hallucinations, post retries) are labelled "this page".
- A rejected card is shown as what happened to it — *removed*, *interpretation rejected* or *undone* — never as a bare
  "rejected".
- The device Whisper actually runs on (WebGPU or WASM) is the one shown; Web Speech is labelled "not local".
- The reviewer's name on a sign-off is self-asserted, and the UI says so.

## The one command

| OS | Command (from the `exmap/` directory) |
|---|---|
| macOS, Linux | `./start.sh` |
| Windows (PowerShell 5.1 or 7) | `.\start.ps1` (if scripts are blocked: `powershell -ExecutionPolicy Bypass -File .\start.ps1`) |
| any, inside `exmap/` | `npm start` |

All three run the same launcher, `bin/exmap.mjs`, which:

1. checks Node is **22.12 or newer** (Vite 8 declares `node >= 22.12` and fails below it with an opaque error, so the
   launcher stops early with a clear message instead);
2. runs `npm install` when `node_modules` is missing or `package-lock.json` changed since the last install (the
   install stamp is `node_modules/.exmap-install-stamp`), with the `onnxruntime-node` binary download skipped (also set
   in `.npmrc`);
3. builds the web bundle and the server when `dist/` is missing or older than the sources (a fresh clone has new file
   times, so its first start rebuilds once);
4. starts the server on `http://127.0.0.1:4317` — loopback only — and waits for it to answer;
5. opens your browser (Chrome or Edge; tab and system audio capture are Chromium features).

Re-running is safe: with the stamps matching it neither installs nor builds, and if exmap is already running on the
port it says `exmap is already running at <url>`, opens the browser and exits 0. Stop it with Ctrl+C.

Options and environment:

| Flag / variable | Meaning |
|---|---|
| `--port <n>`, `EXMAP_PORT` | port (default 4317; `0` = any free port) |
| `--home <dir>`, `EXMAP_HOME` | data directory (default `~/.exmap`) |
| `--no-open`, `EXMAP_NO_OPEN=1` | do not open the browser (the URL is always printed) |
| `--no-install`, `--no-build` | skip those steps (fails if `node_modules` / `dist` is missing) |
| `EXMAP_COOP=0` | do not send the cross-origin isolation headers (Whisper then runs single-threaded) |
| `EXMAP_CLASSIFIER` | `rules.v1` or `claude` (see *Providers and keys*) |

Exit codes: `0` started (or already running), `1` unexpected failure, `2` Node older than 22.12, `3` the port is used
by another program (`port <n> is in use by another program; set EXMAP_PORT or pass --port`), `4` npm install failed,
`5` build failed, `6` another exmap server is using the same data directory (`another exmap is already using <home> at
<url>`).

## Audio setup per OS

exmap has two capture lanes in the browser. **Call** captures the Teams call; **Me** captures your microphone. Each
lane is cut into utterances by a voice-activity detector and transcribed in the browser. Give each lane a speaker label
(the Call lane's label is whoever is speaking on the far end as far as you know; the Me lane defaults to your name from
Settings) — exmap records exactly that label and never guesses who spoke. The **Setup help** button in the capture
panel shows the steps for your OS; this section is kept in step with `src/web/audio/lanes/guidance.ts`, whose snapshot
test is the contract.

**Teams in a browser tab (every OS).** Join the call at teams.microsoft.com in Chrome or Edge. Press **Start** on the
Call lane, choose **Chrome Tab**, pick the Teams tab and tick **Share tab audio**.

**Windows, Teams desktop app.** Press **Start** on the Call lane, choose **Entire screen** (window sharing never carries
audio in Chrome or Edge) and tick **Share system audio** at the bottom-left, then Share. System audio includes
everything the machine plays, so mute other apps.

**macOS, Teams desktop app.** Chrome on macOS cannot share system audio from the screen. Either use Teams in a Chrome
tab (above), or install a loopback driver such as BlackHole 2ch, set it as Teams' speaker (Teams → Settings → Devices;
or make a Multi-Output Device in Audio MIDI Setup so you still hear the call), then set exmap's **Call source** to
*Audio device* and pick *BlackHole 2ch*.

**Linux, Teams desktop app.** Screen sharing carries no system audio. Use Teams in a Chrome tab, or with
PulseAudio/PipeWire set **Call source** to *Audio device* and pick the *Monitor of <your output>* device (create one
with `pactl load-module module-null-sink sink_name=exmap` if none is listed).

**Wear headphones.** Without them the far end's voice also reaches your microphone and is transcribed in the Me lane
under your name; the browser's echo cancellation cannot remove audio the Teams desktop app plays. This is not solved in
v1.

**When a lane has no audio.** If the shared surface or device delivers no audio track, the lane shows an error and the
guidance for your OS opens; it never runs silently. A live lane that hears nothing for 10 seconds reads *Live — no
sound heard*.

**The speech model.** The default transcription provider is local Whisper, run in the browser (WebGPU when it works,
WASM otherwise; the device actually used is shown). The first time a lane needs it, a notice asks before anything is
downloaded; Cancel keeps the lane live as *Capture only (download declined)*. The files come from the Hugging Face Hub
once and stay in the browser's cache (`Clear downloaded models` in the capture panel removes them). Measured on the Hub
on 2026-10-16, a first download at the default q8 precision is about 80 MB for the default model (77 MB of model
weights plus about 3 MB of tokenizer and configuration) and about 44 MB for the smaller model offered in the **Model**
picker. Audio never leaves the machine with this provider.

## Providers and keys

**Transcription** (chosen per lane, in the browser):

| Provider | Local? | Notes |
|---|---|---|
| Whisper (local) | yes | default; model downloaded once after your consent, then cached |
| Web Speech | **no** | Me lane only; Chrome sends the audio to the browser vendor. Opt-in behind a notice and labelled "not local" everywhere |
| Manual (typed) | yes | type or paste an utterance; always available |
| Replay | yes | plays a scripted conversation (`?replay=demo`); used by the demo and the tests |

A server-side speech-to-text provider is a documented seam, not built in v1.

**Classifier** (on the server; it only ever *proposes* — the engine decides what is applied):

- `rules.v1` — deterministic, offline cue tables and heuristics with a confidence. The default, and the fallback.
- `claude` — the Anthropic API with the model `claude-opus-5-5` and structured output. Selected when
  `ANTHROPIC_API_KEY=<your key>` or `ANTHROPIC_AUTH_TOKEN=<your token>` is set in the environment that starts exmap, or
  when `EXMAP_CLASSIFIER=claude` (use that with an `ant auth login` profile). `EXMAP_CLASSIFIER=rules.v1` forces the
  offline classifier even when a key is set. The key is passed through to the SDK and never printed or stored.

On a refusal, a truncated answer or any API error, that utterance is classified by `rules.v1` instead and its
proposal's provenance names the fallback and the error code; the header's classifier chip shows the current provider
and the last error, once rather than on every utterance. Every classification — including "no intent heard" and every
error — is a ledger event.

**The only network calls** exmap makes: the Whisper model download (browser, after consent), Web Speech (browser,
after consent, only when you choose it), and the Claude classifier (server, only when configured). There is no
telemetry.

## What it does not do (v1)

Speaker diarisation; reading Teams' active-speaker indicator; a Teams bot or Graph API integration; multi-user
collaboration over the network; a database; cloud sync; server-side speech-to-text (a documented seam only); pushing
directly into a crb deployment's API (the export files are the bridge); chaining exports by revision (`supersedes` is
`""`); "unconfirming" a wrong voice confirmation (edit the card instead, which clears the confirmation); re-linking an
example or re-pointing a question by voice (UI only); multilingual Whisper models. Echo without headphones is not
cancelled (see above).

`rules.v1`'s known limitations: a restated rule without a change verb ("the limit is 24 hours") is read as an add; two
instructions in one utterance yield only the first intent's operation (plus a leading reject or confirm); an unstated
card kind defaults to rule; a definition attaches to the story unless a card is named. The `claude` classifier covers
these.

Before an utterance reaches the ledger, the browser drops likely Whisper hallucinations — and only drops, never
rewrites: text with nothing but punctuation or bracketed tokens (`[BLANK_AUDIO]`, `(music)`), one token repeated five or
more times, and a short list of stock phrases ("thank you", "thanks for watching", "the end", …) only when the segment
was both quiet and shorter than a second. Single words such as "Yes." or "Okay." are never dropped. The count is shown
as a "this page" diagnostic.

## The state model

| State | Meaning |
|---|---|
| Proposed | the classifier has interpreted an utterance; the proposal is pending, or waiting on a clarification |
| Applied | the engine validated the change and incorporated it |
| Confirmed | a person confirmed the card or the act (by click, or by voice — labelled as voice) |
| Rejected | shown as *removed*, *interpretation rejected* or *undone* |
| Superseded | a later card replaced this one |
| Human verified | the current revision passed the Definition of Done and carries an active sign-off — derived, never stored |

Proposals are kept separate from the map: a proposal names the operation, its source utterances, the classifier and
its confidence; the map is a pure reduction of the ledger. When the target is ambiguous or the confidence is low, the
proposal is a **clarification** — a question naming the candidates (or a yes/no on a fully resolved change), answered by
voice or by clicking a candidate; the same answer gives the same map either way. One *step* is one utterance's batch
or one click; **Undo** goes back one step by making a new revision that restores the earlier state. A *revision* is
the SHA-256 of the canonical map (cards' content, links and statuses); it changes on every create, update, removal,
replacement, definition, rejection or undo, and not on confirmations, question acceptance, sign-offs or export options.
Removed, rejected and superseded cards stay in the ledger and appear under **Show history**.

## The Definition of Done gate

The **Review** drawer computes five checks from the ledger:

1. **Story and business rules accurately represent the agreed intent** — exactly one live story, and it and every
   live rule are confirmed.
2. **Examples and acceptance criteria have been reviewed** — every live example is confirmed and none needs review.
3. **Changes, deletions and disputed interpretations are resolved** — no pending proposal or open clarification;
   every removal, undo or rejection the classifier made on its own has been accepted (or rejected) by a person; every
   example belongs to a live rule and every question is about a live card. A spoken "Yes." right after such an act
   reviews it, and is labelled as a voice review. An act that a later undo reverted is not listed (nothing of it is
   left in the map); the undo is.
4. **Open questions are resolved or explicitly accepted as outstanding** — every live question has a confirmed answer,
   or a person accepted it as outstanding with a reason. An accepted question is still unanswered and is never shown
   as answered.
5. **The final version and its evidence are recorded** — the current revision and the chain head exist and match.

"Mark reviewed" on checks 1, 2 and 4 first previews the exact cards it covers, then records one confirmation listing
exactly those cards. Voice confirmations count by default and are labelled `confirmed by voice (<classifier>,
<confidence>, speaker <label>)`. The **sign-off** needs a reviewer name (self-asserted) and the exact sentence "I have
reviewed the complete requirement and confirm it represents the agreed intent."; it records the reviewer, the time,
the revision hash, the evidence chain head and the five checks, and is refused while any check fails. The map is
*human verified* only while that sign-off is active, names the current revision and the checks still pass. **Any later
substantive change** (a new revision) appends `signoff.invalidated` naming the change; the header returns to "Not
verified" and the map must be reviewed and signed off again. A clarification asked after sign-off creates no revision
but still makes the map unverified until it is answered or dismissed.

## The crb bridge

The **Export** drawer (or `GET /api/sessions/<id>/export/<file>`) produces five files:

| File | For |
|---|---|
| `crb-backlog-item.json` | crb's `BacklogItem` — what `POST /factory/{repo}/backlog` registers |
| `ticket.json` | crb's intake `Ticket` shape (key, title, body, acceptance criteria, tags such as `crb:class=…`, `crb:kind=…`, points) |
| `ticket.md` | the same ticket as Markdown to paste into Azure DevOps or Jira, including "Open questions explicitly accepted as outstanding" |
| `requirement.feature` | Gherkin: a `Rule:` per live rule, a `Scenario:` per example, questions and definitions as comments |
| `evidence.json` | the sign-off, the chain head and the verified revision's canonical state (its SHA-256 is the revision hash) |

Export is refused with `422 NOT_HUMAN_VERIFIED` and the failing checks unless the map is human verified. `?draft=true`
exports anyway, with `DRAFT / NOT VERIFIED` in every file, `-draft-` in the item id and `DRAFT-` in the filename.

The export options — crb capability class, kind, size and *slot facts* — are ledger events (`export.options_set`),
outside the sign-off: changing them does not invalidate it. The class list and each class's slot questions come from a
vendored copy of crb's readiness catalogue (`src/export/crb-catalogue.json`, copied from
`src/crb/factory/readiness.py` at commit `ba05a67d`; to update it, copy the catalogue again — never edit it by hand).
Structural slots are the ones crb needs before work can start; value slots route rather than block. A fact is written as
an acceptance-criteria line `slot: text` (for example `route_identity: PUT /appointments/{id}/cancel`); crb reads a line
whose slot belongs to the item's class as a structural fact and leaves any other line as prose.

To use them: register `crb-backlog-item.json` with a crb deployment's backlog endpoint, or paste `ticket.md` (or map
`ticket.json`) into the Azure DevOps / Jira ticket crb's intake reads, keeping the `crb:` tags and the `slot: text`
lines. Pushing straight into a crb deployment is a documented next step, not part of v1.

## Data location

```
~/.exmap/                     (or EXMAP_HOME)
  settings.json               your name for acts and sign-offs
  server.lock                 exists only while a server runs (pid, port)
  sessions/<session-id>/
    meta.json                 title and creation time
    events.jsonl              the ledger: one canonical-JSON event per line, append-only
```

Each event carries `prev_hash` (the previous event's `hash`, `""` for the first) and `hash` = SHA-256 of its canonical
JSON (sorted keys, no whitespace) including `prev_hash`. Every open re-walks the chain. A broken chain — an edited,
missing or truncated line — is refused with its row number (`LEDGER_BROKEN`) and is never repaired automatically;
inspect the row with `sed -n '<row>p' events.jsonl` and, if you decide to, truncate the file yourself (keep a copy).
If an append ever fails, that session refuses further changes until the next start. Back up by copying the directory
while exmap is stopped. Only one exmap server may use a data directory at a time (`server.lock`).

## Running the tests

```sh
npm run check            # typecheck (server, web, tests) + vitest + build
npm run e2e              # build + Playwright: journey, replay, audio, accessibility, launcher, smoke
npm test -- --project web   # only the jsdom/React unit tests
npm run clean            # remove dist/ and test output
```

Playwright runs Chromium headless with a fake microphone (`tests/fixtures/audio/mlk16k.wav`) and never downloads a
browser: it uses the Chromium matching `@playwright/test` 1.56.1 under `PLAYWRIGHT_BROWSERS_PATH`. The e2e journey
replays the scripted conversation `src/web/public/replay/conversation.v1.json` (open `?replay=demo` in the app to watch
it) with the offline classifier forced. `node scripts/whisper-check.mjs` (options in its header:
model, precision, `--headless`) is a manual, headed check that the real Whisper path transcribes the test recording;
it needs `npm run build` first and downloads the model.

## Troubleshooting

- **"port 4317 is in use by another program"** (exit 3) — another program holds the port: `EXMAP_PORT=4400 ./start.sh`
  or `./start.sh --port 4400`. If it says *already running*, exmap is up: open the printed URL.
- **"another exmap is already using <home>"** (exit 6) — a second server on the same data directory: use the URL it
  prints, or stop that server, or point this one at another `EXMAP_HOME`.
- **"exmap needs Node 22.12 or newer"** (exit 2) — install a current LTS from https://nodejs.org; the floor is 22.12
  because the bundler requires it.
- **The Call lane says the shared screen had no audio** — on Windows share the *Entire screen* with *Share system audio*
  ticked; anywhere, share the Teams browser tab with *Share tab audio*; on macOS or Linux with the desktop app, use a
  loopback / monitor device as *Call source* (see *Audio setup per OS*).
- **The model download is blocked** (a proxy or firewall stops huggingface.co) — the model line reads *Model load
  failed* with the reason; nothing captured is dropped: segments wait in the backlog. Once the Hub is reachable, stop
  and start the lane to load the model again (or press **Retry** when segments are listed as failed). Meanwhile type
  into the Manual input, or choose Web Speech for the Me lane (not local).
- **"Live — no sound heard"** — the lane is capturing but nothing reached it for 10 seconds: check the shared tab is the
  one playing the call, Teams is not muted, or the right microphone is selected.
- **A session is listed as broken** — see *Data location*: the row number names the line that failed verification.

## Development

`npm run dev` runs the server under `tsx watch` and Vite on `http://127.0.0.1:5173` (proxying `/api` and `/ort` to the
server); `npm run dev:server` runs the server only. Layout: `src/core` (the pure, hash-chained engine, used by both the
server and the browser), `src/classifier` (`rules.v1` and `claude`), `src/export` (the crb mappers and catalogue),
`src/server` (Fastify routes, WebSocket stream, ledger, classifier bridge), `src/web` (React UI) with `src/web/audio`
(capture lanes, VAD, providers). Three tsconfigs: `tsconfig.server.json` (NodeNext, emits `dist/server`),
`tsconfig.web.json` (bundler resolution, no emit; Vite builds `dist/web`) and `tsconfig.test.json`. The design is
`docs/DESIGN.md`, the test plan `docs/TEST-PLAN.md`, integration decisions `docs/INTEGRATION-NOTES.md`. Commits use
Conventional Commits with the `exmap` scope (`feat(exmap): …`, `test(exmap): …`, `docs(exmap): …`).
