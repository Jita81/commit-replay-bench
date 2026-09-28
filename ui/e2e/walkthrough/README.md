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

From a **git worktree**, put its `src` first: `PYTHONPATH=$PWD/src scripts/walkthrough.sh`.
The venv's editable install imports the main checkout's `crb`, so without it the API and
worker under test are main's while the UI bundle is the worktree's — a spec then fails on
(or, worse, passes against) a server that does not carry the change. The script refuses to
start when `CRB_PYTHON` imports `crb` from any tree but this one, and names both (P-157).

## Two tiers

| | Tier 1 — hermetic (default; CI) | Tier 2 — live public repos (opt-in) |
|---|---|---|
| Switch | none | `CRB_E2E_PUBLIC=1` (+ `CRB_E2E_BUILDER=claude_code`) |
| Network | none | clones from github.com; `pip install` / `go mod download` |
| Repos onboarded (02/03) | `tests/fixtures/pyrepo.py`, padded with 40 coupled commits, served as a bare `file://` clone (`CRB_ALLOW_LOCAL_CLONE=1`) | `https://github.com/spf13/cobra.git` (Go preset, probe `./...`) and `https://github.com/pallets/click.git` (Python src layout, `{"pythonpath_suffix":"/src","pip":["click","pytest"],"uninstall":["click"]}`, belt scope `TARGET_ONLY`, probe `tests/test_basic.py`) |
| Measured repo (04–06) | the fixture | `click` (the Python target) |
| Builder (05) | `fixture_gold` — test-only, replays the commit's own source; **registered only under `CRB_ENABLE_FIXTURE_BUILDER=1`**, never in production | `fixture_gold` unless `CRB_E2E_BUILDER=claude_code`: then a REAL replay — `claude_code`, `claude-sonnet-5`, limit 2, `builder_config {"auth":"cli"}` (the worker must be able to run `claude` on the operator's CLI login) |
| Model / cost | none / $0 | with `claude_code`: a few Sonnet turns per task |
| Wall clock | **~2 min** for the 41 story tests (08 seeds and replays a second repo, ~30 s; 10 runs the factory over two items, ~20 s) plus **~16 min** for 11-screens (8 persona × width passes over 24 routes — the unknown address included — each settled, captured, axe-swept with a hint open five times, tabbed at 1280 and width-checked at 375) **[measured — one tier-1 run on a laptop on 2026-09-22: 56 passed in 17.7 min, 11-screens 15.7 min of it, apparatus 2.2, n = 1 run]** (+ ~10 s boot; + ~1 min if `ui/dist` must be built) on a laptop; budget 6–8 min in CI | 10–30 min: the first probe clones + installs each repo (minutes), mining click for 3 tasks runs its suite per candidate; a real replay adds a few minutes per task |

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
| `05-replay-fake` | A `replay` run (`fixture_gold:gold`, limit 2) succeeds with ledger rows, clean 100 %, cost $0.00; the task table shows all four belts ✓ and `$0.00`; the **Evidence drawer** opens with the belts, the Apparatus section (provenance `app 2.x`, grader) and the **verified** badge; the **Ledger** gate is OPEN (chain verifies, `false_q1_total = 0`) and lists the rows; the **Capability** page shows the graded task's (class × size) cell with `n`, its Wilson interval and route **calibrate** (`n < 10`), no false-Q1 alert, and the detail card's reason `n=N < 10`; the **Sign-off** page, with that cell chosen, keeps the policy gate **CLOSED** — the server's preview lists `thin_cell` (observed *n* vs threshold 10 — 2 in tier 1, where both graded tasks share a cell; in tier 2 the two real tasks may land in different cells, so the spec asserts the map's own n) — with *Sign off* disabled and no attestation recorded (08 tells the whole story); **Export JSONL** downloads a file whose rows carry `row_hash`/`prev_hash`, name the builder, and verify with `crb ledger verify --path … --json` (`ok`, `chain_ok`, `false_q1 = 0`, row count matches). With `CRB_E2E_BUILDER=claude_code` the same spec asserts ≥ 1 row and builder turns / tokens / cost > 0 on the pack instead of a clean grade. |
| `06-cancel` | A `mine` run with a large limit is cancelled from the run page **while running**: "cancel requested" appears, the Cancel button goes, the run ends **cancelled** (not failed) within 30 s — the executor's cancel token kills the in-flight test command — the log carries `mine.cancelled`, and the Runs list agrees. The fixture history is padded (`CRB_E2E_PAD`, default 40) so a full mine outlasts the click. |
| `06b-baseline-read` | **Home's task tags on real data, and the read that completes task 6** (G-166, G-165, DL-074). Runs after 05 has given the primary repository rows and before 07 — the first spec that opens its baseline — so the transition is seen, not only its end state: Home reads *Choose a repository*, *Confirm its shape* and *Measure* Completed with no failed read, and *Read the baseline* **Incomplete**; opening `/results?repo=` makes the page's own `POST /repos/{name}/baseline-read` answer **201** with `recorded: true`; Home then reads *Read the baseline* **Completed**. Writes one `repo.baseline_read` event; tier 1 and tier 2 alike. |
| `07-settings-and-a11y` | **Settings** lists every builder credential as configured / not configured (never a value — the page text is checked for key shapes), the sandbox mode, the ledger backend, and apparatus / policy versions that match the footer; the health probes are listed. The **Claude Code login** card round-trips a shape-valid fake `claude setup-token` value: a wrong shape is refused (422, not echoed), the real shape is stored and shown only as its last four characters with who/when, the password field is cleared, Verify is enabled (clicked only in tier 2 — tier 1 is offline; a fake token can only come back `invalid`/`cli_missing`), Remove returns it to absent; the page text never contains a key shape. Then **axe (WCAG 2.1 AA)** finds **0 violations** on Repos, the repo page, Runs, a Run detail with real rows and a scrolling log, a Task page with real grade rows (reached from a Ledger row; at 375 px its grade table must fit inside the phone with the verdict on screen — G-292), Capability, Ledger, Sign-off, Oracle and Settings — against live data. Then the **account lifecycle** (F23): the `walk-approver` persona is created if an earlier run has not, an admin sets its password from the **Set password** dialog (typed twice, never echoed on the page, the success state naming the account and saying its sessions ended), **that persona signs in with the new password**, and back as the admin the account is **deactivated and reactivated** — each act with its own sentence — while the bootstrap admin's own role select and active toggle stay **disabled** as the last active admin. The account's **History** then lists `user.created`, `user.password_set`, `user.deactivated` and `user.activated` with the actor of each. The password set is the stable `personaPassword`, so 08 and 11 sign in afterwards as they always did. |
| `08-signoff` | **A sign-off is a policy decision, refused at write** (`signoff-policy.v4`, ADR-0025 as ADR-0026 amends it). The primary repo's only measured cell (n = 2) is REFUSED before the approver tries: the Sign-off page shows n / point / Wilson-low / false-Q1 / oracle strength / the controls verdict (k of N, escapes, run id, date) / route + reason, and lists every failing clause with *observed vs threshold* — `thin_cell` (2 vs 10), `controls_escapes` (1 vs 0), `route_not_deliver:posture_unsealed`, `not_standard:reading_unregistered`, `attestation_missing` (non-overridable) — the gate is CLOSED and the action disabled even with a row named and affirmed. The escape is a **real finding** of 04's controls run: the fixture's literal-assert tests let the `hardcode_cheat` control grade clean. Then a second calculator repo whose tests are parametrised (the cheat is then `not_constructible` → 0 escapes) is built in the temp dir, served as a bare `file://` clone, onboarded, probed, mined (18), put through a `controls` run (passed, 0 escapes), an `oracle` run (the cell's strength measured ≥ 0.80) and replayed with `fixture_gold` (18 clean rows). Under `routing.v2` it still routes `calibrate` `posture_unsealed`: tier 1 grades on the host and registers no reading, so no walkthrough cell delivers (G-956). The admin who queued every run is refused by the two-person rule (`same_actor`, shown before they try, never overridable, 409 from the API with nothing written); a second person (`walk-approver`, created through `POST /users`) names an accepted row and affirms it and is still refused on the reading and the posture — 409, nothing written, the map's tier unmoved. |
| `09-review` | **A human's verdict on an accepted patch has a place to live, anchored to the bytes read** (ADR-0006 amendment, review §5 plays 05/07). A `replay` run queued through the API with `retain: {worktrees, transcripts}` (`fixture_gold`, limit 1) leaves the graded worktree behind; `GET /grades/{row_hash}/retained` says the patch is available and names the pack's `diff_sha256`; the cell's `n_reviewed` is 0. On the run page the **Evidence drawer**'s **Patch** tab fetches the diff computed on demand, hashes the served bytes in the browser and shows **hash matches pack**, the file list with `+n`, coloured added lines and `+/−` counts that agree with the pack's `diff` stats; the **Transcript** tab reports honestly that the fixture builder retained none. The **Review** panel is disabled until the Patch tab was loaded in the session (the anchor reads *unanchored* → *anchored*); the reviewer picks **Defect**, writes the note (with a file), says *Not mergeable*, writes the statement and records it — *Recorded Defect* — and the reviews list shows the item with the attested patch hash. Then the API serves the review hash-chained (`row_hash` / `prev_hash`, `patch_sha256_reviewed` = the pack's anchor, the finding), `/reviews/verify` is `ok` with 0 unanchored, the cell's `n_reviewed` / `n_review_defects` read 1 / 1, a `POST /reviews` with a wrong hash is **422 `review_refused` · `patch_hash_mismatch`** and records nothing, and the task page's Review column shows the verdict pill. |
| `09-budget-sweep` | **The budget is a measured variable** (C8). A `blind` run queued with the dialog's **Blind budget sweep 25 → 50 → 100 tool calls** preset declares three object rungs of the same `fixture_gold:gold` (`{builder, model, budget: {max_tool_calls: n}}`); the run header names them with their caps; the fixture is clean on rung 1, so every task has exactly one trial (`r1` — the ladder climbs only on a red attempt, rungs 2–3 never run), clean 100 %, $0.00, and the r1 pack verifies. The worker stamps each row `labels.budget_tier` (`25/25/900`) / `labels.rung_index` (proved in `tests/test_worker_budget_ladder.py`). Runs last because it adds rows to the primary cell whose `n = 2` 05 and 08 assert on; tier 1 only — a real sweep is a deliberate, priced run. |
| `10-factory` | **The factory journey, end to end, without a model** (tier 1 only). A two-item backlog is frozen through the dialog's JSON view (I-1 `bug.fix` with its structural facts and an operator-authored `tests/test_multiply.py` that fails today; I-2 `backend.route.add` with every structural slot but `method_path` answered); before any run each item reads *not assessed* with its cell-route pill from the signed map, and **Before you run** states the builder, `2 of 2 will be worked`, the estimate with its provenance (the fixture's rows cost $0, so the documented planning band), `not linked — no pull request` with the reason and the admin's next step (the deliver checkbox is disabled), `no spend cap yet`, and that cancelled runs still charge built items. The operator names `fixture_gold · gold` under *Use a different builder* (the deployment's default would be a real model), presses **Run the factory**, sees the in-progress banner replace the controls, opens the run and waits on its status pill (**succeeded**). Back on the factory: I-1 is *route build* → RED proved → built under the belts **not clean** (the fixture overlays a commit's own sources; a factory item has none — an honest not-clean, never a fabricated pass), status *Build not clean*, a `run <id>` link and an **Evidence** button that opens the drawer with the **verified** pack naming `fixture_gold`; I-2 is *Waiting on a signature* with `1 structural gap unsigned: method_path` (its open value slot `example_payload` is named apart as routing test-first — the first live pass found the fold listing it as a gap to sign, which the server refuses with 422; `task_views` now serves `dor_gaps` and `value_gaps` separately), the refusal sentence and the way forward (*freeze a revised backlog*), no Evidence, and the approver's gap select labelled with the catalogue's question. The Runs list names the `factory` kind, and at 375 px `/factory` does not scroll sideways. |
| `11-screens` | **Every route renders for every role, at two widths, with the one help mechanism on it.** For each persona (viewer / operator / approver / admin — the three non-admin accounts are created through the API if missing, with **test-only passwords that are stable per stack** — derived from the bootstrap admin password, never printed, so a rerun against the same stack signs into the accounts an earlier run created and the setup asserts that sign-in through the API) and each width (1280 × 900, 375 × 812) it signs in through the form, visits every authenticated route (the journey, the instrument, the detail pages anchored to a finished run and a task of the primary repository, and the two help pages), saves a full-page PNG `<persona>__<route-slug>__<width>.png` under `<CRB_E2E_OUTPUT_DIR>/screens/` — the visual record a reviewer reads — and asserts `data-testid="about-this-screen"` (the "About this screen" block `Layout` mounts once after the outlet) is present on every route — the help pages and the unknown address included (G-926). On every route it then opens a sample of up to five hinted elements (`data-hint`; hover at 1280, the touch `pointerdown` a tap begins with at 375 where no hover exists — a full tap would also click a nav link away from the route), asserts the `role="tooltip"` bubble the element's `aria-describedby` names becomes visible with a full sentence and no link, runs **axe (WCAG 2.1 AA)** with the bubble open and closes it with Escape; at 1280 it tabs **each route** from the first control of its own `<main>` (bounded at two verified stops or 12 presses) and asserts a hinted control's bubble shows on focus and hides when Tab moves on, and at 375 it asserts the document does not scroll sideways (`scrollWidth <= innerWidth`), naming the widest element when it does — both on every route, not on one (G-905). Two real defects turned up on its first full pass: `/help/docs/:name` (an 87-character token in inline `code` set the document's width — fixed in `ui/src/index.css`) and the 11-column grade table on `/tasks/:repo/:taskId` (scrollWidth 981), recorded against G-292 in the spec's `SIDEWAYS_SCROLL_RATCHET` (a list that may only shrink) until the table folded its secondary columns below 768 px; the list is now empty. Before anyone signs in, `/login` gets the same checks at both widths — axe, the keyboard pass, the hint sample, no sideways scroll and Sign in on the first screen at 375 (G-192). At 375 the top bar is one row: the navigation, role, Help, theme and Sign out fold behind one **Menu** button (F26), and on every route the spec opens it, checks `aria-expanded`, runs axe with it open, tabs into it and closes it with Escape, with focus back on the button. The five keyboard steps that operate controls are `11b-keyboard`'s (below). The route list ends with an unknown address, so the 404 is captured, hint-sampled and axe-swept per persona at both widths like any other screen (G-918). **It never assumes state another spec made**: its first test finds the primary repository or, on a stack of its own (its CI jobs), seeds it through the API — onboard, probe, mine (limit 3), an `oracle` and a `controls` run (limit 1), a two-task `fixture_gold` replay, the runs 02–05 queue through the dialog (tier 1 only; tier 2 runs it after 02–03) — and the anchor test fails if no finished run or task is found. `CRB_E2E_SCREENS_SHARD=k/n` runs every n-th persona from the k-th (unset: all four). Changes no data beyond that seed; tier 1 and tier 2 alike. |
| `11b-keyboard` | **The controls a keyboard person has to operate, by Tab and keys alone from the skip link (G-905).** It first makes sure the operator and approver accounts exist (the stable passwords 08 and 11-screens use), then: a map cell and its reason code (`/capability`), a reason code on `/routing`, a term on `/oracle` — each opening and closing with `aria-expanded` —, the sign-off form on `walk-signable` filled, with Sign off still closed on a cell with no proven standard (`/signoff`; the walk of an enabled Sign off and of the revoke confirmation waits on G-956), and the freeze dialog on `/factory` (focus in, kept in, and back) — plus a negative control that takes the map cells out of the tab order and requires the same step to fail. It runs in the stateful story, after 08 seeded `walk-signable` and 10 gave the factory a backlog (the steps began in 11-screens, whose shards run on stacks of their own without that state). It presses neither Sign off, Revoke sign-off, Freeze nor Run, so it changes no data; tier 1 and tier 2 alike. |
| `12-intake` | **Work arriving from the team's own board, end to end, with no real tracker** (tier 1 only). The stack runs with `CRB_ENABLE_FAKE_TRACKER=1` and `CRB_INTAKE__TRACKER=fake`, so the whole board is one JSON file (`CRB_E2E_BOARD`) the spec writes and reads — **no Azure DevOps or Jira is contacted by this spec or by CI**; everything above the six tracker verbs is the product's own code. It asserts the listener reads *Not listening* on every repository until somebody switches it on and that nothing has been written to the board; switches it on as the operator and finds the switch recorded under their name; reads the column and finds a `bug.fix` ticket labelled `crb:needs-info` on the board with ONE marked comment naming the missing acceptance fact as the catalogue's question, the cell's route (or that the cell is unmeasured), the false-Q1 statement and the non-goals; re-reads the unchanged column and asserts the board file is byte-identical (the idempotency key is `(tracker, key, revision)` on the chain); edits the ticket and moves its revision, re-reads, and finds it DRAFTED and waiting for an operator with nothing registered (ADR-0022), presses *Register this ticket* and finds it registered, labelled `crb:queued`, linked, and visible as `fake-4711` on the Factory screen; deletes the comment and proves *Post the feedback again* puts it back; signs in as the viewer and finds the two operator acts absent with a sentence saying who can; checks `/factory/intake` does not scroll sideways at 375 px; and switches the listener off. |
| `13-recover-an-account` | **An account is recovered from the screen, end to end, and the walk is timed** (tier 1 and tier 2 alike; it changes only its own account, `walk-recover`). The person signs in on one device; on a second they type a wrong password and `/login` shows the 401 envelope with the next step inside it — ask an admin of this deployment to set a new password on the Settings screen, or, when no admin can sign in, the person who runs the deployment (`crb users`, OPERATOR §9). The admin sets a new password from the Users card; the first device's session is refused on its very next request; the person signs in with the new password. The account's History then reads, newest first, the new sign-in (`user.login`), the password set and the refused sign-in (`user.login_failed`, by `anonymous`). The time from the wrong password to the new sign-in is attached to the test as the `recovery-ms` annotation and must stay under 60 s. A second test runs axe (WCAG 2.1 AA) on `/login` with the envelope and its next step showing. |
| `13-learn` | **The learning loop acts from the page, on real rows** (tier 1 only). A real guard refusal is made through the Runs dialog: a `fixture_gold` replay with `builder_config {"attempt": "git log -p"}` puts that command to the real shell guard (never running it), which refuses it as archaeology, so the rows land as `protocol` exactly as an agentic builder's would, and the run ends `failed` naming the refusal (every attempt was refused). More free fixture replays of the primary repository bring its cell to the routing rule's n, where 04's controls escape holds it for the oracle. As `walk-operator` it reads the loop's position line, the prevention register's refused class, the refusal tile's n, interval and apparatus, a refusal row, a strengthening row and the plan — nothing stale on a fresh stack, then a what-if plan against apparatus 99.0 whose row names its runs and offers no Queue; decides the class (refused, with a note) and reads that the line was written to `shell_corpus_refused.txt` under "Walk operator", the row now reading the verdict and who made it; registers the strengthening item and follows the Factory link to that item; follows Re-score to a Runs dialog opened with kind `oracle`, the task and the loop step filled in; walks the Oracle link to a task and back to the plan. A viewer is offered none of the decisions or hand-offs. axe (WCAG 2.1 AA) is clean on `/learn?repo=<primary>` for every persona at 1280 and 375 with every card rendered, a register class expanded and a hint open; the page is captured beside 11-screens' images, the top bar is at most two rows and nothing scrolls sideways at 375. |
| `13-orient` | **Sign in and find your way, as one journey** (G-413). Starting signed out, the bootstrap admin visits `/`, is bounced to `/login?next=%2F` (whose own About block says what the page is for), signs in, returns to `/` and is replaced onto `/home`; Home lists its eight tasks and names the next; the About block's first term opens its glossary entry on `/help`; that entry's *Read more* opens the guide at the heading it names, in view; an unknown address says so with its own About block and leads back to Home; sign-out ends the session and a protected screen bounces again. The pass is timed and the time printed and attached to the report — the figure `ONBOARDING-A-REPO.md` quotes (G-414). Then all nine bundled guides are opened on the served bundle, each rendering the file's own first heading as the article's h2 under the page's one h1, and a decision record is followed from `/help` (G-149, G-156, P-176). Writes nothing but sessions; tier 1 and tier 2 alike. |

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
`observed` is `null`, not 0), `oracle_weak`, `route_not_deliver:<reason_code>`,
`attestation_missing` (never overridable) and `same_actor` (since `signoff-policy.v3`: the
would-be approver queued the run that produced the attested row, or is the only person
behind the cell — never overridable; the preview judges it for the signed-in viewer). Each
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
| `CRB_E2E_SCREENS_SHARD` | `k/n`: 11-screens runs every n-th persona from the k-th; unset, all of them (CI's `walkthrough-screens` jobs set `1/4` … `4/4`) |
| `CRB_E2E_PORT`, `CRB_E2E_PAD`, `CRB_E2E_KEEP`, `CRB_PYTHON` | script knobs (see its header) |

**Tier 2:**

```sh
CRB_E2E_PUBLIC=1 scripts/walkthrough.sh                              # cobra + click, fixture builder
CRB_E2E_PUBLIC=1 CRB_E2E_BUILDER=claude_code scripts/walkthrough.sh  # + a real Sonnet 5 replay on click
```

**Against a stack you booted yourself** (any port but a *disposable* home — the specs
create repos and runs): export `CRB_E2E_BASE_URL`, `CRB_E2E_USER`, `CRB_E2E_PASS` and
the tier-1 variables above, then `cd ui && npm run walkthrough`.

**CI:** tier 1 runs on every push / PR as five parallel jobs in `.github/workflows/ci.yml`,
each on a fresh stack of its own (Chromium with its system deps; the report pointed at
`ui/playwright-report-walkthrough` and uploaded with the traces on failure), and a sixth that
carries the required context:

| Job | Runs | Exactly as |
|---|---|---|
| `walkthrough-story` — *walkthrough story (browser, live stack, tier 1)* | the stateful story: every spec except 11-screens, in order | `scripts/walkthrough.sh --grep-invert '11-screens\.spec\.ts'` |
| `walkthrough-screens` — *walkthrough screens (browser, live stack, tier 1, shard k of 4)*, k = 1…4 | 11-screens for one persona, both widths, on a stack the spec seeds | `CRB_E2E_SCREENS_SHARD=k/4 scripts/walkthrough.sh e2e/walkthrough/11-screens.spec.ts` |
| `walkthrough` — *walkthrough (browser, live stack, tier 1)*, the required context | nothing of its own: passes only when the story and all four shards passed (a failed, cancelled or skipped part fails it) | `needs: [walkthrough-story, walkthrough-screens]`, `if: always()` |

The walk used to be one job; 11-screens grew it past two budgets (25 and then 40 minutes — PR
#57), so it was split instead of raised again. The required context kept its name on the
aggregator, so every spec still blocks a merge under the one check branch protection already
lists. `--grep-invert` matches the file name, so a spec added later runs in the story with no
list to update, and the shard rule covers every persona by construction
(`tests/test_ci_job_budget.py` holds both, and holds the aggregator's `needs` equal to every job
that runs `scripts/walkthrough.sh`). Every job that runs the walk ends with
`scripts/ci_job_budget.py`, which fails the job past 80 % of its own `timeout-minutes` — split
again before that, never raise the budget (docs/PREVENTION.md P-051). To reproduce one
job locally, run its command above; `--trace off` keeps the disk use down.

## Selectors

Roles, labels and visible text first; `data-testid` where a role is not enough:
`run-status`, `repo-probe`, `repo-probe-detail`, `live-log`, `tile-clean`, `tile-rows`,
`tile-cost`, `tile-false-q1`, `tile-false-q1-total`, `cell-measured` / `cell-false-q1` /
`cell-not-measured`, `evidence-drawer`, `pack-verified` / `pack-unverified`,
`belt-<name>`, `provenance`, `ledger-gate`, `signoff-gate`, `signoff-evidence` / `signoff-tile-*` / `signoff-controls` / `signoff-route` / `signoff-refusals` / `refusal-<code>` / `attest-row` / `attest-read` / `attest-statement` / `signoff-recorded` / `signoff-row-*`, `gate-banner`, `user-chip`,
`error-state`, `settings-*`, `about-this-screen`. Required fields render their label as `Label *`;
`field(scope, 'Label')` in `support.ts` matches that exactly (and never `Source` for
`Source prefix`).
