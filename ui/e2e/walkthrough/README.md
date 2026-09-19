# The walkthrough — a full-browser story against a LIVE stack

`ui/e2e/walkthrough` drives a real crb deployment (API + worker + the built UI) through
the product's whole story, **entirely through the UI** — forms, clicks, the status pill
the run page itself polls — and asserts what every screen shows against rows the stack
just produced. Nothing is mocked. The one direct API read is `GET /api/v1/health` in
`support.ts`, so a spec can say *why* a stack is unusable instead of timing out.

The smoke suite next door (`ui/e2e/smoke.spec.ts`, `npm run e2e`) answers a different
question — "does the bundle render the contract?" — against fixtures. This suite answers
"does the product work, end to end, with the numbers it shows earned?"

```
scripts/walkthrough.sh              # boots a fresh stack in a temp dir, runs tier 1, tears down
scripts/walkthrough.sh -x --headed  # any extra args go to `playwright test`
npm run walkthrough                 # (from ui/) against a stack YOU booted — needs CRB_E2E_*
```

## Two tiers

| | Tier 1 — hermetic (default; CI) | Tier 2 — live public repos (opt-in) |
|---|---|---|
| Switch | none | `CRB_E2E_PUBLIC=1` (+ `CRB_E2E_BUILDER=claude_code`) |
| Network | none | clones from github.com; `pip install` / `go mod download` |
| Repos onboarded (02/03) | `tests/fixtures/pyrepo.py`, padded with 40 coupled commits, served as a bare `file://` clone (`CRB_ALLOW_LOCAL_CLONE=1`) | `https://github.com/spf13/cobra.git` (Go preset, probe `./...`) and `https://github.com/pallets/click.git` (Python src layout, `{"pythonpath_suffix":"/src","pip":["click","pytest"],"uninstall":["click"]}`, belt scope `TARGET_ONLY`, probe `tests/test_basic.py`) |
| Measured repo (04–06) | the fixture | `click` (the Python target) |
| Builder (05) | `fixture_gold` — test-only, replays the commit's own source; **registered only under `CRB_ENABLE_FIXTURE_BUILDER=1`**, never in production | `fixture_gold` unless `CRB_E2E_BUILDER=claude_code`: then a REAL replay — `claude_code`, `claude-sonnet-5`, limit 2, `builder_config {"auth":"cli"}` (the worker must be able to run `claude` on the operator's CLI login) |
| Model / cost | none / $0 | with `claude_code`: a few Sonnet turns per task |
| Wall clock | **~1.4 min** for the 36 story tests (08 seeds and replays a second repo, ~30 s) plus **~4 min** for 11-screens (8 persona × width passes over 23 routes, each settled and captured) (+ ~10 s boot; + ~1 min if `ui/dist` must be built) on a laptop; budget 6–8 min in CI | 10–30 min: the first probe clones + installs each repo (minutes), mining click for 3 tasks runs its suite per candidate; a real replay adds a few minutes per task |

The tier is chosen at *spec load time* from the environment; the same files run
in both. Nothing in this repository runs tier 2 unattended — it costs network, time and
(optionally) money, so it stays a deliberate `CRB_E2E_PUBLIC=1 scripts/walkthrough.sh`.

## What each spec proves

The files are one story and run **serially, in order, on one worker**
(`playwright.walkthrough.config.ts`: `workers: 1`, `fullyParallel: false`, `retries: 0`
— a retry would replay against a stack the first attempt already changed). Each file is
also `test.describe.configure({ mode: 'serial' })`. Every wait on a run is a poll of the
run page's status pill (`data-testid="run-status"`), never a fixed sleep.

| Spec | Proves |
|---|---|
| `01-login` | `/health` reports a database, the append-only triggers, `false_q1 = 0` and a worker. A wrong password renders the API's error envelope (`Wrong username or password · HTTP 401`), a right one lands in the shell with the RBAC chip reading **admin**; a protected route bounces to `/login?next=` and returns; sign-out ends the session. |
| `02-repo-onboard` | *Add repo* by URL with a preset (`python-src-layout` / `go`) plus runner-options JSON creates the repo and lands on its page (config tab shows what was typed). *Probe now* → run page; the live log shows `repo.clone.start` / `repo.clone.done` (with a head sha, never a credential), `setup.auto` → `setup.done` when the runner had to prepare the environment (a public clone; not the pinned-interpreter fixture), `probe.start` / `probe.done`; the run **succeeds**. Back on the repo page the probe pill is **OK** with the runner's own summary (`N passed`), and the Repos list agrees. |
| `03-mine` | *Start run* (kind `mine`, task limit) succeeds; the log shows `mine.task` / `mine.done`; the progress bar reports found/target; the repo's **Tasks** tab lists ≥ 1 task with its size tier, capability class and gold pill (≥ 1 gold-clean); the Runs list shows the run succeeded. |
| `04-oracle-and-controls` | An `oracle` run (limit 1) scores mutation strength; the **Oracle** page shows per-task strength, killed / mutants, the band and the gate it licenses, plus the per-cell roll-up and the policy version. A `controls` run (limit 1) renders the **negative-controls** gate OPEN with `0 violation(s)` and all seven controls with verdicts: `gold` → clean / ok, `noop` → red / ok, `test_tamper` → **disqualified** / ok (caught), and never a `VIOLATION`. |
| `05-replay-fake` | A `replay` run (`fixture_gold:gold`, limit 2) succeeds with ledger rows, clean 100 %, cost $0.00; the task table shows all four belts ✓ and `$0.00`; the **Evidence drawer** opens with the belts, the Apparatus section (provenance `app 2.x`, grader) and the **verified** badge; the **Ledger** gate is OPEN (chain verifies, `false_q1_total = 0`) and lists the rows; the **Capability** page shows the graded task's (class × size) cell with `n`, its Wilson interval and route **calibrate** (`n < 10`), no false-Q1 alert, and the detail card's reason `n=N < 10`; the **Sign-off** page, with that cell chosen, keeps the policy gate **CLOSED** — the server's preview lists `thin_cell` (observed 2 vs threshold 10) — with *Sign off* disabled and no attestation recorded (08 tells the whole story); **Export JSONL** downloads a file whose rows carry `row_hash`/`prev_hash`, name the builder, and verify with `crb ledger verify --path … --json` (`ok`, `chain_ok`, `false_q1 = 0`, row count matches). With `CRB_E2E_BUILDER=claude_code` the same spec asserts ≥ 1 row and builder turns / tokens / cost > 0 on the pack instead of a clean grade. |
| `06-cancel` | A `mine` run with a large limit is cancelled from the run page **while running**: "cancel requested" appears, the Cancel button goes, the run ends **cancelled** (not failed) within 30 s — the executor's cancel token kills the in-flight test command — the log carries `mine.cancelled`, and the Runs list agrees. The fixture history is padded (`CRB_E2E_PAD`, default 40) so a full mine outlasts the click. |
| `07-settings-and-a11y` | **Settings** lists every builder credential as configured / not configured (never a value — the page text is checked for key shapes), the sandbox mode, the ledger backend, and apparatus / policy versions that match the footer; the health probes are listed. The **Claude Code login** card round-trips a shape-valid fake `claude setup-token` value: a wrong shape is refused (422, not echoed), the real shape is stored and shown only as its last four characters with who/when, the password field is cleared, Verify is enabled (clicked only in tier 2 — tier 1 is offline; a fake token can only come back `invalid`/`cli_missing`), Remove returns it to absent; the page text never contains a key shape. Then **axe (WCAG 2.1 AA)** finds **0 violations** on Repos, the repo page, Runs, a Run detail with real rows and a scrolling log, Capability, Ledger, Sign-off, Oracle and Settings — against live data. |
| `08-signoff` | **A sign-off is a policy decision, refused at write** (`signoff-policy.v2`). The primary repo's only measured cell (n = 2) is REFUSED before the approver tries: the Sign-off page shows n / point / Wilson-low / false-Q1 / oracle strength / the controls verdict (k of N, escapes, run id, date) / route + reason, and lists every failing clause with *observed vs threshold* — `thin_cell` (2 vs 10), `controls_escapes` (1 vs 0), `route_not_deliver:n_below_min`, `attestation_missing` (non-overridable) — the gate is CLOSED and the action disabled even with a row named and affirmed. The escape is a **real finding** of 04's controls run: the fixture's literal-assert tests let the `hardcode_cheat` control grade clean. Then a cell that clears the policy is seeded **through the API** (never by editing a seed): a second calculator repo whose tests are parametrised (the cheat is then `not_constructible` → 0 escapes) is built in the temp dir, served as a bare `file://` clone, onboarded, probed, mined (18), put through a `controls` run (passed, 5 of 7, 0 escapes), an `oracle` run (v2: the cell's oracle strength must be **measured** on its tasks — the parametrised tests kill the arithmetic/return mutants, so the cell scores ≥ 0.80; an unscored cell is `oracle_unmeasured`, a refusal no knob waives) and replayed with `fixture_gold` (18 clean rows → point 100 %, Wilson lower 82 % → `deliver`); the approver picks the cell, names an accepted row (subject · row hash · date), ticks **I have read this accepted diff**, writes the statement, signs — and the attestations table shows the snapshot (evidence at signing incl. the oracle, `signoff-policy.v2 · deliver · controls passed 5/7 esc 0`, the attested row); the API serves the same record hash-chained, and the Capability map lists the cell `human-verified` with its route unchanged. |
| `09-review` | **A human's verdict on an accepted patch has a place to live, anchored to the bytes read** (ADR-0006 amendment, review §5 plays 05/07). A `replay` run queued through the API with `retain: {worktrees, transcripts}` (`fixture_gold`, limit 1) leaves the graded worktree behind; `GET /grades/{row_hash}/retained` says the patch is available and names the pack's `diff_sha256`; the cell's `n_reviewed` is 0. On the run page the **Evidence drawer**'s **Patch** tab fetches the diff computed on demand, hashes the served bytes in the browser and shows **hash matches pack**, the file list with `+n`, coloured added lines and `+/−` counts that agree with the pack's `diff` stats; the **Transcript** tab reports honestly that the fixture builder retained none. The **Review** panel is disabled until the Patch tab was loaded in the session (the anchor reads *unanchored* → *anchored*); the reviewer picks **Defect**, writes the note (with a file), says *Not mergeable*, writes the statement and records it — *Recorded Defect* — and the reviews list shows the item with the attested patch hash. Then the API serves the review hash-chained (`row_hash` / `prev_hash`, `patch_sha256_reviewed` = the pack's anchor, the finding), `/reviews/verify` is `ok` with 0 unanchored, the cell's `n_reviewed` / `n_review_defects` read 1 / 1, a `POST /reviews` with a wrong hash is **422 `review_refused` · `patch_hash_mismatch`** and records nothing, and the task page's Review column shows the verdict pill. |
| `09-budget-sweep` | **The budget is a measured variable** (C8). A `blind` run queued with the dialog's **Blind budget sweep 25 → 50 → 100 tool calls** preset declares three object rungs of the same `fixture_gold:gold` (`{builder, model, budget: {max_tool_calls: n}}`); the run header names them with their caps; the fixture is clean on rung 1, so every task has exactly one trial (`r1` — the ladder climbs only on a red attempt, rungs 2–3 never run), clean 100 %, $0.00, and the r1 pack verifies. The worker stamps each row `labels.budget_tier` (`25/25/900`) / `labels.rung_index` (proved in `tests/test_worker_budget_ladder.py`). Runs last because it adds rows to the primary cell whose `n = 2` 05 and 08 assert on; tier 1 only — a real sweep is a deliberate, priced run. |
| `11-screens` | **Every route renders for every role, at two widths, with the one help mechanism on it.** For each persona (viewer / operator / approver / admin — the three non-admin accounts are created through the API if missing, with per-run passwords that are never printed) and each width (1280 × 900, 375 × 812) it signs in through the form, visits every authenticated route (the journey, the instrument, the detail pages anchored to a run and a task 01–09 produced, and the two help pages), saves a full-page PNG `<persona>__<route-slug>__<width>.png` under `<CRB_E2E_OUTPUT_DIR>/screens/` — the visual record a reviewer reads — and asserts `data-testid="about-this-screen"` (the "About this screen" block `Layout` mounts once after the outlet) is present on every route except `/help` and `/help/docs/:name`, which are the help. Changes no data; tier 1 and tier 2 alike. |

A finding this suite made on its first live pass, fixed at the source: the virtualised
live log (`LiveLog`) was a scrollable region with no keyboard access
(`scrollable-region-focusable`, WCAG 2.1.1) — invisible to the mocked smoke, whose log
never had enough events to scroll.

## The sign-off refusal, precisely

Since `signoff-policy.v1` the server enforces the bar **at write** (`POST /signoffs`) and
publishes it **before** the approver tries (`GET /signoffs/preview`): the Sign-off page
fetches the preview for the chosen cell (and again for the named row) and derives the
gate's rows from its `refusals[]` — nothing on the screen is asserted by the UI. The
codes, in evaluation order: `false_q1` (**409 false_q1_refused**, first, never
overridable), then **409 signoff_refused** for `thin_cell`, `controls_unmeasured` /
`controls_failed` / `controls_escapes` / `controls_thin`, `oracle_unmeasured` (since
`signoff-policy.v2`: no task of the cell carries a mutation score — never overridable;
`observed` is `null`, not 0), `oracle_weak`, `route_not_deliver:<reason_code>`, and
`attestation_missing` (never overridable). Each
refusal names the number that failed and the threshold it missed. The Sign-off form only
offers measured cells and only accepted (clean) rows of the chosen cell, so the two 422s
(a row that is not clean / not in the cell) cannot be produced through the UI; they are
covered by `tests/test_server_routes_signoffs.py`. 05 asserts the CLOSED gate on the thin
cell; 08 asserts every refusal on the live stack and a real sign-off with an attestation;
the 409 rendering as a REFUSED gate (both codes) is covered by the mocked
`SignoffPage.test.tsx`.

Tier 1 cannot sign the fixture repo, by design: its padded tests are literal asserts, so
04's `hardcode_cheat` control **escapes** (grades clean) and every cell of that repo is
refused with `controls_escapes` until the tests are strengthened — exactly the product
behaviour on a cheatable oracle. That is why 08 builds a second, parametrised fixture.

## `fixture_gold` — the instrument check, not a builder

`src/crb/builders/fixture_gold.py` overlays the commit's non-test files onto the parent
worktree — exactly the `gold` negative control — so a run that *should* grade clean does,
hermetically. Under the protocol real builders are held to that is git archaeology, so it
cannot be mistaken for a measurement: it is registered only when the worker's environment
has `CRB_ENABLE_FIXTURE_BUILDER=1` (`deploy/` never sets it), its identity is forced to
`fixture_gold` / `gold` / `fixture` whatever the rung says, it spends nothing
(`cost_usd = 0`, `cost_known = true`, no tokens, no transcript) and claims nothing
(`done = false`). Exclude `builder == "fixture_gold"` rows from any abstract / federated
export.

## Running it

**Tier 1, the whole thing:**

```sh
uv venv -q .venv --python 3.12 && uv pip install -q -e '.[server,dev]' --python .venv/bin/python
(cd ui && npm install --legacy-peer-deps && npx playwright install --with-deps chromium)
scripts/walkthrough.sh
```

The script (`scripts/walkthrough.sh`) builds `ui/dist` if missing, builds the padded
fixture and its bare clone, creates **its own** `CRB_HOME` + SQLite database under one
`mktemp -d` directory, runs `crb migrate`, starts `crb serve` on a **free** port (never
8000) with `CRB_ENV=dev`, a bootstrap admin and `CRB_UI_DIST=ui/dist`, starts
`crb worker --executor local --poll 0.5` with `CRB_ALLOW_LOCAL_CLONE=1` and
`CRB_ENABLE_FIXTURE_BUILDER=1`, exports `CRB_E2E_*`, runs Playwright, and stops **only
the two processes it started**. It refuses to run if `CRB_HOME` or `CRB_DATABASE_URL`
is already set (it must never touch another stack), and removes only its own temp
directory — kept on failure (and with `CRB_E2E_KEEP=1`) so the logs, the HTML report and
the traces survive; their location is printed.

| Variable | Meaning |
|---|---|
| `CRB_E2E_BASE_URL` | the stack's origin — the specs use this and nothing else |
| `CRB_E2E_USER` / `CRB_E2E_PASS` | the bootstrap admin |
| `CRB_E2E_REPO_URL` / `CRB_E2E_REPO_NAME` | tier 1: the fixture's `file://` URL and ledger key (`walk-pyrepo`) |
| `CRB_E2E_PYTHON` | tier 1: pinned as `runner_opts.python` so the probe never installs |
| `CRB_E2E_CRB` | path to `crb` for `ledger verify` on the export (skipped with a note if absent) |
| `CRB_E2E_WORK` | where downloads land |
| `CRB_E2E_REPORT_DIR` / `CRB_E2E_OUTPUT_DIR` | HTML report / traces (default: inside the temp dir; CI points them at `ui/`) |
| `CRB_E2E_PUBLIC=1`, `CRB_E2E_BUILDER=claude_code` | tier 2 (above) |
| `CRB_E2E_PORT`, `CRB_E2E_PAD`, `CRB_E2E_KEEP`, `CRB_PYTHON` | script knobs (see its header) |

**Tier 2:**

```sh
CRB_E2E_PUBLIC=1 scripts/walkthrough.sh                              # cobra + click, fixture builder
CRB_E2E_PUBLIC=1 CRB_E2E_BUILDER=claude_code scripts/walkthrough.sh  # + a real Sonnet 5 replay on click
```

**Against a stack you booted yourself** (any port but a *disposable* home — the specs
create repos and runs): export `CRB_E2E_BASE_URL`, `CRB_E2E_USER`, `CRB_E2E_PASS` and
the tier-1 variables above, then `cd ui && npm run walkthrough`.

**CI:** the `walkthrough` job in `.github/workflows/ci.yml` runs tier 1 on every push /
PR (installs Chromium with its system deps, points the report at
`ui/playwright-report-walkthrough`, uploads it with the traces on failure).

## Selectors

Roles, labels and visible text first; `data-testid` where a role is not enough:
`run-status`, `repo-probe`, `repo-probe-detail`, `live-log`, `tile-clean`, `tile-rows`,
`tile-cost`, `tile-false-q1`, `tile-false-q1-total`, `cell-measured` / `cell-false-q1` /
`cell-not-measured`, `evidence-drawer`, `pack-verified` / `pack-unverified`,
`belt-<name>`, `provenance`, `ledger-gate`, `signoff-gate`, `signoff-evidence` / `signoff-tile-*` / `signoff-controls` / `signoff-route` / `signoff-refusals` / `refusal-<code>` / `attest-row` / `attest-read` / `attest-statement` / `signoff-recorded` / `signoff-row-*`, `gate-banner`, `user-chip`,
`error-state`, `settings-*`, `about-this-screen`. Required fields render their label as `Label *`;
`field(scope, 'Label')` in `support.ts` matches that exactly (and never `Source` for
`Source prefix`).
