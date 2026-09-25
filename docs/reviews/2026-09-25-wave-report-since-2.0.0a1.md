# Wave report — from `v2.0.0a1` to `main` at `8ab88ad` (pull requests #30 to #48)

*Moved here on 2026-09-25, unchanged apart from its heading levels and two relative links,
from the `Unreleased` section of [CHANGELOG.md](../../CHANGELOG.md). The changelog now grows
by one paragraph per pull request (CONTRIBUTING, "Documentation"); a wave's narrative — what
was built, why, and what it found — belongs in a dated report like this one. The claims
below carry the tags they carried in the changelog; this page is not on the claims gate's
allowlist, so read each tag as its author wrote it.*

## 2026-09-23 — what the product writes on somebody else's ticket is counted, absolute and bounded

Four independent reviews read the intake path end to end against a fake board, the real
readiness gate and a real hash chain. What they found was one class of defect rather than a
list: the product's statements about its own writes were reassuring rather than true. Fixed
here, each with the test that would have caught it (ADR-0017 amended, DL-052).

- **The comment counts what it writes.** The paragraph on the customer's ticket said the
  product "only ever adds this one comment … and never edits any other field"; one poll of a
  ready ticket leaves two comments and attaches a link, and over its life a ticket can receive
  four. It now names the four marked notes, the one `crb:` label, the link to the item and to
  the pull request, and the one configured state change — and the test counts the renderers
  and the protocol's verbs against the sentence instead of looking for the word "never".
  ONBOARDING step 9 and SECURITY §2 say the same list.
- **Every link is absolute.** Each URL written on a ticket was a relative path
  (`/factory?repo=…`), which on Azure DevOps or Jira resolves against the *tracker's* host, so
  the "Follow it here" the customer was given could not reach the product (and Azure DevOps
  refuses such a string as a `Hyperlink` relation). `CRB_PUBLIC_URL` is now a setting, one
  builder makes every link, a listener cannot be switched on until it is set
  (`intake_no_public_url`) and a pass that somehow starts without it stops `no_public_url`
  before writing anything.
- **One pass is bounded twice.** A first pass over one ticket it registers costs eleven Azure
  DevOps requests, or nine Jira ones [measured — n = 1 ready ticket × 2 adapters; method: every
  request counted through an `httpx.MockTransport` for the verb sequence one pass makes,
  `tests/test_intake_write_bound.py`; apparatus 2.2 — a count, so no interval]. A pass runs in
  front of the worker's heartbeat and, on demand, inside an API request; nothing bounded it,
  and Azure DevOps answers a WIQL query with up to 20,000 ids. `CRB_INTAKE__MAX_PER_POLL`
  (200) and `CRB_INTAKE__POLL_BUDGET_S` (60) now bound it: a longer column is **not read at
  all** (`column_too_large`, with the advice to narrow the area path or the JQL), and a pass
  that runs out of time serves what it read and says how far it got. The adapters ask for one
  more than the bound, so an overflow is visible rather than silently truncated, and Jira's
  search pages properly instead of taking 200 and ignoring the rest.
- **Jira reads like a person wrote it.** ADF has no hidden node, so the "hidden" marker was
  the first line of every comment, the renderer's Markdown arrived as raw `##` and `**`
  characters, and idempotency compared held text against a lossily flattened document — which
  is never equal for a real comment, so the same unchanged comment was rewritten on **every
  poll**. The marker is now an attribution line a reader understands (carrying the same
  token), the structure maps onto ADF headings, strong marks and code marks, and both sides of
  the comparison go through the same flattening. A remote link is named by what it points at
  ("Backlog item" / "Pull request") instead of always "Pull request".
- **A half-written ticket is repaired.** A re-read of a ticket already registered wrote
  nothing at all, so a ticket whose queued note or link had failed once kept `crb:ready` on
  the board for ever while the screen said queued. The poll now re-asserts the label, the
  queued note and the item link — all idempotent, so a healthy ticket is untouched.
- **The consent switch is an event.** `switched_by` is one mutable field, so switching off and
  on again overwrote who consented. Every throw of the switch is now
  `intake.listener.switched` on the repository's system trace, naming the operator.
- **`/health` reports the stop the last read recorded.** A deployment whose every listener was
  failing `unauthorised` read `intake: ok`, so monitoring never learned the front door was
  shut. The probe still contacts no tracker: it reports the reachability the last real poll
  measured, and `degraded` names the repository, the reason and the advice.
- **The screen has a door, and says something useful when it cannot classify.** Nothing in the
  app linked to `/factory/intake`: the only ways in were a bookmark or the raw path the guides
  printed. The Factory screen now links to it, and a new source-level ratchet fails when any
  route in `App.tsx` has no link anywhere (or no stated reason). A ticket the classifier could
  not place showed an amber "needs information" pill and listed nothing; it now says the one
  thing that closes it. The route reads as a verdict pill, as it does on every other screen,
  and the button beside a drafted replacement item now uses that draft.
- **Smaller, still load-bearing.** A decision now carries both ends of its Wilson interval, so
  the worker's own timed poll no longer writes "67 % to unknown" on a ticket where the
  on-demand poll writes "67 % to 90 %". Two long ticket keys can no longer collapse onto one
  item id (the overflow is hashed, not truncated). A ticket whose key cannot become an id costs
  that ticket alone instead of the whole column. The served view is written by the poll that
  produced it, and a deleted view is rebuilt by the next pass. The tracker credential is in no
  log, no event, no state file and no error message — as a test, not a promise; the https-only
  rule on the tracker URL has one too. `test_run_forever_survives_a_broken_iteration` waits on
  an event instead of a 0.3 s sleep, so the full suite is deterministic.
- **A second review pass over the same path, and what it found was the same class again.** A
  ticket is no longer read as *edited* because this product wrote on it: the tracker's own
  revision moves when a tag or a comment is written (`System.Rev` on Azure DevOps,
  `fields.updated` on Jira), which made an untouched ticket a new EVOLUTION on every pass. The
  comparison is now a digest of what the draft is made of — `content_revision`, on the item and
  on `intake.read` — with the revision as the pre-filter. A `crb:class=` / `crb:kind=` /
  `crb:level=` tag somebody put on their own ticket is an INPUT and is kept: clearing every
  `crb:` tag by prefix deleted the operator's classification, and the tag write then moved the
  revision, so the next draft read the ticket without it. A registration the frozen record
  REFUSES is served as stopped instead of as queued (three outcomes were one boolean, so the
  screen showed an item that was never registered). A refusal comment is written by the latest
  item a ticket produced, not once per superseded item. The pass now asks its budget again at
  the tracker boundary inside a ticket, so an expired pass starts no further call on somebody's
  board, and the worker keeps checking in for as long as a pass lasts — a slow board read as a
  stale worker. `CRB_PUBLIC_URL` is parsed rather than prefix-matched, so
  `http://localhost.example.com` is refused. Azure DevOps comments name their format, so the
  marker survives the round trip. The `/health` intake line asks for a credential only where
  one is needed. `RouteDecision.ci_high` is required, so no caller can serialise a made-up
  upper bound beside a measured lower one. On screen: a long error message in the live log
  opens in full from a keyboard-reachable button outside the fixed-height row, a drafted
  successor takes its predecessor's place in the dependency graph as well as the list, and the
  intake row's route carries its apparatus like every other number.
- **A third pass, on the gates themselves.** A poll whose budget ran out **inside the last
  ticket** reported nothing: `_handle_ticket` recorded the stop on that ticket's row and the
  pass-level stop was set only by the check at the top of the next iteration, which a
  one-ticket column never reaches — so the served view, `/health`'s intake line and the screen
  all read `ok` on a pass that had run out of time. The budget check now remembers that it
  fired, and the pass records the stop against the ticket it actually curtailed rather than
  over-counting a ticket that did not finish. The claim gate stopped exempting the bare word
  "confidence": `65% confidence that the builder can deliver` is an outcome claim, and it
  passed untagged because the `interval`/`level` half of the phrase was optional (`a confidence
  of 95%` is still exempt, because there the percentage *is* the confidence). The whole-life
  write bound is driven through `apply_outcome_map` instead of the test calling `transition`
  itself, so the "one state change" count bounds the product rather than the test. And three
  statements now say what is true: the poll budget stops further tracker calls rather than
  capping a pass's wall-clock time (SECURITY §2, ADR-0017), the 11-screens keyboard and
  375-px checks cover every *authenticated* route (PLAN stream E), and G-192 separates what is
  measured about `/login` from what is still missing.
- **The record itself.** `product.evidence.6` is back to `partial`: the `dod`, `claims`,
  `ui-unit` and `ui-smoke` jobs run on every pull request but are not on branch protection's
  required list (G-930). The walkthrough's `proof.20` is narrowed to what the spec walks, with
  the pull-request and outcome leg opened as G-931. A gap id used twice in one file is
  renumbered (G-929) and `dod_check.py` now fails on that instead of silently dropping one of
  them. Its anchor rule matches GitHub's, so the 63 cited headings a reader clicks resolve.
  Two criteria whose text still said a thing "does not exist" now say what shipped.

## 2026-09-22 — the work arrives from the board, and the gates that watch the gates

- **Work arrives from the team's own board (stream I; ADR-0017, DL-051).** A person moves a
  ticket into ONE watched column on their own Azure DevOps or Jira board, and the ticket **is**
  the backlog item — nothing is typed twice. `src/crb/intake/` holds one `TrackerClient`
  protocol of six verbs (`entered`, `read`, `comment`, `label`, `transition`, `link`) with
  `ado.py` and `jira.py` adapters on stdlib + `httpx` and no vendor SDK, so the non-goals (the
  product never edits another ticket field, never creates a ticket, never reads a column it was
  not pointed at) are enforced by the size of the protocol rather than by a rule somebody
  remembers. `draft.py` turns the ticket into a draft `BacklogItem` — every mapping states its
  rule, and the capability classifier serves its confidence and says `unclassified` rather than
  routing money at a guess. `feedback.py` leaves ONE comment, idempotent by a hidden HTML
  marker, carrying the readiness gate's open questions with the line that closes each, the
  cell's route with its `n`, its Wilson interval and its apparatus — and, for a cell nobody has
  measured, saying so instead of quoting a zero — plus one of `crb:needs-info` /
  `crb:ready` / `crb:not-deliverable` / `crb:queued`. `server/intake.py` is the listener:
  `(tracker, key, revision)` is the idempotency key and it lives on the factory's hash chain,
  so a restart never double-comments, an edited ticket comes back as an **evolution** that
  supersedes the old item, and a registration arriving while a factory run holds the backlog
  hash is queued rather than refused with a 409 the listener has nobody to hand.
- **Off by default, twice.** An admin configures the connection (`CRB_INTAKE__*` on the API and
  the worker) and stores the credential in the product's own secret store (`tracker_token`,
  read back as a fingerprint and `set_at`, never a value); an operator then switches the
  listener on **per repository**, and the switch is stored with who threw it and when. Refused
  when no tracker is configured, enforced at the API and again in the worker.
- **New:** the route `/factory/intake?repo=` (the listener, the connection with no secret in
  it, the last read, and every ticket with its draft, its label, its open questions and the
  comment verbatim, with three acts each naming its outcome or the server's own advice on a
  stop); `GET /factory/{repo}/intake`, `POST /factory/{repo}/intake/poll` and
  `PUT /factory/{repo}/intake` (operator), and `POST /factory/{repo}/backlog/evolutions`; an
  `intake` line on `/health` and `crb doctor` that contacts no tracker; eight `intake.*` events
  on the repository's chain and six published stop reasons with a way forward each; a
  SECURITY §2 egress row and OPERATOR §11.
- **Proof.** `tests/test_intake_*.py` and `tests/test_server_routes_intake.py` against a fake
  `TrackerClient`, and the tier-1 walkthrough spec `ui/e2e/walkthrough/12-intake.spec.ts`
  driving a file-backed fake tracker behind `CRB_ENABLE_FAKE_TRACKER=1`. **No real Azure
  DevOps or Jira is contacted by any test or by CI** [measured — `tests/test_intake_adapters.py`,
  n = 27 requests, every one answered by an `httpx.MockTransport`; apparatus 2.2].
- **The factory can write its own failing test (stream T; DL-050).** Forward mode has no
  held-out test, so nothing is built until one failing test exists — and the served worker
  built its `FactorySpec` with no `test_author` at all, so every item nobody had hand-written
  an oracle for stopped `no_oracle` and waited for a person. The loop's test-first path was
  built, tested and unreachable on a real deployment. `src/crb/factory/author.py` adds a
  `TestAuthor` on any OpenAI-compatible endpoint, shown the item, its facts, the repository's
  test layout and one or two of its own tests for style; a reply it cannot parse, or one naming
  a path the repository does not call a test, is re-asked with the reason and then refused.
- **New setting:** `CRB_FACTORY__TEST_AUTHOR` (API *and* worker; empty by default, which is why
  such an item still stops `no_oracle`), spelled as a rung — `builder:model[:provider]`, the
  builder half a **registered** builder name — with the per-run override `POST /runs
  {test_author}`; `none` in either place declines one. The invariant: **the author rung and the
  build rung are never the same rung.** No new refusal was invented — the loop already applies
  `assert_distinct_identity` to every rung when a spec is built, so a deployment configured
  that way fails before anything is built or paid for, and the rung spelling is what gives that
  refusal a closed label space to compare. What it deliberately does not catch (the same model
  under a different registered builder name — a different process) is written down rather than
  papered over. Nothing the author writes is trusted: the RED proof runs it at the base and
  requires attributable failing ids, and belt 1 re-checks every test byte after the build.
- A stopped item's `way_forward` now carries the superseding item **already drafted** from the
  item that stopped and the stop's own reason — for an `oracle_needs_strengthening` verdict,
  the reviewer's weak-oracle finding, read where the test is strengthened. Proof:
  `tests/test_factory_author.py`, `tests/test_worker_test_author.py`, and
  `tests/test_server_routes_factory.py::test_a_weak_oracle_stop_serves_the_superseding_item_pre_filled`.
  Docs: OPERATOR §10, the API factory rows and the `author.*` event vocabulary.
- **The UI's own gates run in CI, and nothing explains itself by hover alone (stream E).**
  Two new jobs on every pull request: `ui-unit` (`npm ci`, `npm run typecheck`, `npx vitest
  run` — the hint ratchet, the native-`title=` allowlist and every screen suite) and
  `ui-smoke` (the mocked Playwright spec over the built bundle). Until now those ran only when
  somebody remembered them. Neither context is on `main`'s required-checks list yet, so a red
  one must be fixed like any other gate but does not by itself stop a merge; only an
  administrator of the repository can add them (README's "Status" records the list in force,
  docs/DEPLOYMENT.md §3.4 names the branch-protection call, and the gap is G-930).
  `testTimeout`/`hookTimeout` are 20 s so a shared runner can meet them [measured — the
  full vitest suite run twice on an 8-core laptop while the walkthrough held the other cores:
  18 then 24 tests failed, every one "Test timed out in 5000ms", and all passed when the same
  files ran alone; method: `npx vitest run` twice, then the failing files alone; apparatus 2.2].
- **Every route is now keyboard- and phone-checked**, not `/results` and `/factory` alone: the
  `11-screens` keyboard pass and the 375-px `scrollWidth <= innerWidth` assertion run on all of
  them, and an unknown address is in the route list, so the 404 is captured, hint-sampled and
  axe-swept per persona at both widths like any other screen. The new assertion earned its keep
  twice on its first runs: `/help/docs/OPERATOR` scrolled sideways at 375 px [measured —
  scrollWidth 763 at innerWidth 375; method: the `11-screens` assertion, tier-1 run 2026-09-22;
  apparatus 2.2], caused by an 87-character unbroken token in inline `code` that nothing wrapped
  — `.prose-doc` now breaks words while a fenced block stays exempt and copyable — and the
  11-column grade table on `/tasks/:repo/:taskId` [measured — scrollWidth 981 at innerWidth 375;
  same method], which belongs to the page that owns it and is recorded against **G-292** in the
  spec's `SIDEWAYS_SCROLL_RATCHET`, a list that may only shrink.
- **The last native `title=` tooltips are retired and the per-file allowlist is EMPTY.**
  `ShortId` puts the rest of a shortened id or hash in the accessible text, `/learn`'s
  strengthening table shows an item's description as a second line under the id, and the
  ratchet's `TITLE_RE` now names react-router's `Link`/`NavLink`, which spread onto an `<a>` —
  a hole that was hiding three more escaped cells. `/login`, `/help`, `/help/docs/:name` and the
  catch-all have `SCREENS` entries, fixtures and `MIN_HINTS` floors, so every route `App.tsx`
  declares is enforced rather than skipped by name. One sentence under the sign-in form names
  who resets a password or reactivates an account.
- **A claim carries its tag or CI fails (`claims`).** `scripts/claims_check.py` reads the
  pages on its allowlist (today `README.md` and `docs/RELEASING.md`), finds the sentences
  that quantify something — a percentage, or a cardinal qualifying a plural noun — and fails
  when one carries none of `[measured]` / `[hypothesis]` / `[aspiration]` / `[gap]`, or when
  a `[measured]` one carries no `n`, no method or no apparatus version. The heuristic and
  what it deliberately does not catch (unquantified claims, tables, headings, fenced code, a
  lead-in ending in a colon, whether a tag is the *right* one, and every page off the
  allowlist) are stated in the module docstring; `tests/test_claims_check.py` pins both the
  behaviour and that the covered pages are clean. `[gap]` joins the permitted tags in
  [EVIDENCE-AND-CLAIMS §1](../EVIDENCE-AND-CLAIMS.md#1-claim-tags) — it was already in use
  in SECURITY — and the README's tag table says so.
- **The two wrong claims on `main` are corrected.** The README's status line said CI was
  "eleven jobs, required by branch protection": the required-checks list read from the
  repository on 2026-09-22 names **ten** checks, and `sbom` and `sandbox-images` run on every
  pull request without being on it — the line now says that, with its method. `RELEASING` §1
  tagged the tag-protection ruleset `[aspiration]` as though it were planned; the repository
  has **no ruleset at all**, so the sentence now says that as a `[gap]`, with the reading
  that found it, and keeps the workflow's `--require-on origin/main` refusal as the floor.
  The README's opening no longer counts the belts (the count has moved twice; belt set v5
  and the definitions in EVIDENCE-AND-CLAIMS §2 carry it instead).
- **Definition of done:** `product.claims.21` keeps its `partial` — the gate is real but
  covers two pages — and its gap is now **G-605**: the pages still ungated, one page per
  change. G-603 is closed.
- **Merging the four streams closed two more criteria between them.**
  `intake-from-a-ticket.recovery.24` (no oracle / weak oracle) is **met**: stream T built the
  test-author rung and stream I made the ticket ask for the acceptance test, and each was the
  other's remaining half. `manufacture-and-deliver.automation.15` is **met** for the same
  reason — the backlog no longer arrives by hand. G-901, G-902 and G-904 are closed, and
  stream I's time-cost gap is renumbered **G-928** (stream E landed first and owns G-926).

## 2026-09-21 — shippable: every element explains itself; users can recover; the loop closes on a merge

- **Every element explains itself (hover, focus and tap — one registry, one ratchet).** A
  person on any screen can rest the mouse on, tab to, or tap any element they meet — every
  stat tile, number, pill, tag, column header, field, button, link, gate clause, task item,
  summary row, banner and kicker — and read one plain-English sentence saying what it is and
  what its value means; the same sentence is listed under *About this screen → Elements on
  this screen* and is announced by a screen reader (`aria-describedby`). Hover is never the
  only way (DL-048). The mechanism: `<Hint id>` (`ui/src/components/Hint.tsx` — opens on
  mouse-over after 150 ms, on keyboard focus and on a touch `pointerdown`; Escape closes and
  stops there; a `role="tooltip"` bubble, portalled, never a tab stop inside a control, never
  a link; a `crb:help` event for telemetry), the registry `ui/src/help/hints.ts` (661 ids
  from the inventory, `HintId`, `MIN_HINTS` per route; `hints.test.ts` lints length, the full
  stop, no links and term use), and every shared component taking `hint?: HintId` (StatTile,
  Pill, DataTable columns, buttons, fields, GateBanner criteria, govuk Tag / TaskItem /
  SummaryRow / StartButton / WarningButton); VerdictPill, BeltPills, Provenance, CiBar,
  FailureSplit, ModelPointLine, ControlsPill and CellRoutePill derive their own ids. The
  shell — every nav entry, the health pill, the role chip, Help, theme, Sign out, the
  stop-condition banner, the footer — is hinted.
- **The on-ramp screens (H1):** `/login`, `/home`, `/connect`, `/connect/:name`,
  `/connect/:name/measure`, `/results`, `/decisions`, `/signoff` — 152 inventory rows wired.
  The sign-off attestation statement is rendered under its row instead of a hover-only
  `title` (a governance record is never hover-only); Measure's "Every knob" door is a hinted
  note line; the map's column and row headers, route tag and every cell line carry
  `col.map.*` / `map.cell.*` with the numbers out of the tab order. One test per screen
  asserts the sample hint opens on hover with the registry copy and `unhinted()` is empty.
- **The factory, deployment and instrument screens (H2):** `/factory`, `/posture`, `/repos`,
  `/repos/:name` (all four tabs), `/runs` (+ Start a run), `/runs/:id` (+ the live log and
  the evidence drawer's Pack, Patch and Review tabs), `/tasks/:repo/:taskId`, `/capability`
  (+ the open cell detail), `/routing`, `/oracle`, `/learn`, `/ledger`, `/settings` (viewer
  and admin) and `/help` — 436 elements. Native `title=` attributes on those screens are
  retired where a hint stands (LiveLog 4→3, Factory 2→1, RepoDetail 2→1, EvidenceDrawer 7→6,
  Oracle / RepoConfigTab / RunNewDialog / Sign-off → 0). Opening an evidence pack moves focus
  into the drawer and returns it to the opener on close (WCAG 2.4.3), so one Escape closes it.
- **The ratchet (`ui/src/help/hints-ratchet.test.tsx`)** reads every `<Route path>` in
  `App.tsx` and requires a `SCREENS` entry — rendered per role under its fixtures, every
  element resolved to a registry id, at least `MIN_HINTS[route]` hinted — for all 21 routes
  (`hints-ratchet.onramp.tsx`, `hints-ratchet.instrument.tsx` with the deeper states: tabs,
  dialogs, the drawer); the `ALLOWLIST` of routes not yet wired is **empty**; the per-file
  `title=` count only goes down. The tier-1 walkthrough's `11-screens` opens a sample of
  five hints on every route × persona × width (hover at 1280, touch at 375), asserts the
  bubble is a full sentence with no link, runs axe WCAG 2.1 AA with the bubble open and
  closes it with Escape; a keyboard pass on `/results` proves focus opens and Tab closes.
- **Users can recover (F23, merged from main via #42):** password set / change, deactivate
  with a last-admin guard, sessions revoked on change, and the break-glass `crb users` CLI;
  **the operating envelope (F36–F41, F44, F47, F25, #43):** the `/health` `migrations` probe,
  no probe serving an exception, `crb doctor` coverage, the temporary-home guard, SQLite
  backup and restore, `docs/RELEASING.md`, the release main-provenance check and the viewer
  secrets projection — each carried here unchanged; the `/signoff` help anchor follows the
  operator guide's renamed heading (`OPERATOR#5-sign-off`).
- **The loop closes on a merge (L — F39, B-9/F30, F32; DL-049).** *Fetch before a run:*
  every factory run (and a replay / blind / mine on a repository linked through the GitHub
  App) fetches the row's URL and fast-forwards the clone's default branch first —
  `repo.fetch.start` / `repo.fetch.done` carry the before / after shas, a factory run's
  apparatus carries `base_sha` — and a fetch that fails or a branch that cannot fast-forward
  refuses the run with a plain reason (`FetchRefused`; never a build on a stale base, never
  a merge or reset the product did on its own). *The merge outcome as evidence:* at the start
  of every factory run, or on demand via `POST /factory/{repo}/outcomes/sync` (operator),
  each delivered pull request whose fate can still change is read through the installation
  token and recorded as `delivery.merged` / `delivery.closed` on the item's chain — at most
  closed, then merged, per PR: a merge is terminal and never read again; a closed one is
  read again because a person can reopen and merge it; a repeated state appends nothing
  (`FactoryEvidence.record_delivery_outcome` is idempotent per state; the one predicate both
  the worker and the route ask before minting a token is `outcomes_pending`); the task view
  serves `outcome` (state, PR, merged_at, merged_by, merge_sha, synced_at), the backlog
  serves `outcomes` (delivered / merged / closed / open — the fact Home's task 8 reads), the
  capability map's cell serves `n_delivered` / `n_merged` (counts, no interval). *Evolutions
  over the frozen backlog:* `POST /factory/{repo}/backlog/evolutions` registers a new item
  chained onto the frozen hash with `supersedes`, refused while a run is active, recorded as
  `backlog.evolved`; the task view shows the superseded item above its evolution, `GET
  …/backlog` lists `evolutions` + `evolutions_hash`, and a run works the latest evolution of
  each item. Tests: `tests/test_worker_fetch.py` (fast-forward, an unreachable remote, a
  diverged branch, a clone left on another branch, the linked-only rule) and
  `tests/test_factory_outcomes.py` (the FakeGitHub pull-request shapes — open / merged /
  closed, GHES `merged: null` — outcome idempotency at the ledger, the sync route: 409 until
  linked, 502 on a dead token, per-PR errors retried; the evolutions chain end to end;
  delivery counts per cell). Docs: API.md rows, GITHUB-APP.md §5, ADR-0014 clauses 6–7.
- Gates on the merged branch: ruff, ruff format, mypy, `code_map --check`, `tsc -b`, vitest,
  the full pytest, and the tier-1 walkthrough (55 specs incl. `10-factory` and `11-screens`).

## 2026-09-21 — reference sandbox images, built and proven by CI (F42 part 1)

- **`deploy/sandbox/Dockerfile.{python,node,go}`** — the images the fail-closed sandbox
  runs a repository's tests in, so "what do I run?" no longer answers "build one yourself":
  each `FROM` pinned by the multi-arch index digest, the toolchain and the test runner only
  (pytest 9.1.1 hash-pinned via `python-requirements.txt`; Node 22.19.0 with `node --test`;
  Go 1.26.8 copied onto a slim base of the same Debian release — 477 MB on disk against the
  official image's 1.2 GB), `USER 65534:65534`, OCI labels, `HOME` and every cache under the
  executor's tmpfs, hadolint-clean. `deploy/sandbox/README.md`: build / tag / push, the keys
  that select an image, extending one for a repository's dependencies, the re-pin cadence.
  A JVM image is deliberately not shipped — the Maven runner's docker branch cannot resolve
  plugins offline yet (README §6).
- **CI `sandbox-images` job** — hadolint + `docker buildx build` (GHA layer cache, no push)
  of each image, then the smoke that matters: `tests/test_sandbox_images_docker.py` runs
  each language's fixture repository through `DockerExecutor` on the image just built (uid
  65534 by default and under the executor, `/usr` and `/work` read-only from inside while
  `/tmp` is writable, a network probe FAILS through the language's runner, an absent image is
  `SandboxUnavailable`, qualify + grade clean with the host worktree untouched, labels), and
  the sandbox + sealed-builder suites on the python image. `CRB_TEST_SANDBOX_IMAGE` /
  `CRB_TEST_SANDBOX_IMAGE_<LANG>` name a present image to test; the `test` job deselects the
  `sandbox_images` marker (the images are built once, there).
- **Found by the first smoke, fixed:** Docker mounts a `--tmpfs` `noexec` unless told
  otherwise, so `go test` could not exec the test binaries it builds under `/tmp` — the Go
  runner had never run against a daemon. `Command.exec_tmp` (the Go runner declares it)
  mounts the sandbox's tmpfs `rw,exec,nosuid,nodev` for that toolchain alone; every other
  command's tmpfs now says `noexec` on the argv instead of inheriting it from the runtime;
  every other flag holds; the exception is per toolchain, never per repository (ADR-0005
  amendment, SECURITY.md §3.1). Proven from inside: `/proc/mounts` in each shipped image
  carries `noexec` for an ordinary command and drops it only for the Go runner's, and a
  script written under `/tmp` is refused / runs accordingly
  (`tests/test_sandbox_images_docker.py`). `--pull=never` on every sandbox `docker run`:
  the documentation always said the worker never pulls, and now it cannot.
- **Fixed: the worker ignored the deployment's sandbox keys.** compose, Helm and
  DEPLOYMENT.md set `CRB_SANDBOX__EXECUTOR` / `CRB_SANDBOX__IMAGE`; the API read them, the
  worker read only `CRB_EXECUTOR` / `CRB_SANDBOX_IMAGE` and defaulted to `local` — a
  compose / Helm worker ran untrusted tests on the host while `/settings` reported
  `docker`. The worker now reads the deployment keys (short forms still honoured when they
  are absent), and a repository's own `sandbox_image` wins over the deployment default
  (`docker_settings_for`), as DEPLOYMENT.md §2.1 always said — the default silently
  overrode it, which is wrong the moment two toolchains share a worker.
- Docs: DEPLOYMENT.md §2.1 / §3.1 / §3.4, deploy/README.md §3 and §8, OPERATOR.md §2.1,
  SECURITY.md §3.1 and §5 (the images are measured; verdicts under the docker posture are
  still pending — the measurement gap stays open), ARCHITECTURE.md §9.3,
  docs/reviews/2026-09-17-enterprise-front-end.md §9 (F42 part 1 shipped, part 2 pending;
  F52 SHA-pinning every Action repo-wide, from CodeRabbit on PR #44). Corrected on review:
  a sandbox that cannot be provided ends the run `failed` (`sandbox unavailable: …`) — the
  job store has no `blocked` status, and OPERATOR §7, DEPLOYMENT §3.4, deploy/README,
  compose, Helm and ARCHITECTURE §9 now say the word the worker records; under docker a
  host setup's `node_modules` is NOT visible inside the sandbox (the worktree's link to the
  clone dangles in the container) — OPERATOR §2.1 and `Dockerfile.node` now say so and
  point at the derived-image recipe (deploy/sandbox/README.md §4); claim tags with n /
  method / apparatus on every sandbox-image statement. `tests/conftest_langs.py`: a
  `docker image inspect` that raises after the daemon probe goes through the warm-up policy
  (skip locally, fail under strict warm-up) instead of erroring the test
  (`tests/test_conftest_langs.py`).
- Second review round (adversarial verifier): the three sandbox Dockerfiles strip every
  setuid/setgid bit the Debian bases ship (`su`, `mount`, `passwd` …, 11 files per image →
  0), proven from inside as uid 65534 (`test_no_setuid_or_setgid_binary_in_the_image`);
  the absent-image test now pins the daemon's no-pull wording (`No such image`) so losing
  `--pull=never` fails it rather than passing on the registry's `pull access denied`;
  a missing daemon is a skip on *every* call under strict warm-up too — the daemon reason
  is no longer memoised against the image tag, where a later caller re-raised it as a
  failure (`tests/test_conftest_langs.py`); `Dockerfile.go`'s header shows the argv the
  Go command really gets (`exec` on the tmpfs) and its true size (477 MB); every
  `[measured]` sandbox-image tag names the run that executed on which head (a document can
  never cite a run of its own commit) with the local count on images built from the tree;
  `sandbox-images` runs on every pull request, is not on `main`'s required-checks list, and
  DEPLOYMENT §3.4 gives the branch-protection call that would put it there (a repository
  setting, for the administrator).

## 2026-09-21 — the two-person rule is enforced at write; every sign-off says who signed (F7b, F34)

- **`same_actor` — the fourth non-overridable clause** (`signoff-policy.v3`, DL-047). `POST
  /signoffs` and `GET /signoffs/preview` resolve the actors behind the evidence from the
  ledger (`Grade.actor` of the attested row and `Run.actor` of the run that produced it; the
  same for every accepted row of the measured cell) and refuse — `409 signoff_refused`,
  `detail.code: same_actor`, `observed` the approver's id, the message naming the row (and
  the run, when the approver is the actor of that run) — the approver is refused when they
  are the actor of the attested row (`Grade.actor`), the actor of the run that produced it
  (`Run.actor`), or the only person behind the cell's accepted evidence. The preview judges
  it for the signed-in viewer, so "you queued run X, which produced the attested row — a
  second approver must sign" shows before they try; the gate gains a *Signed by a second
  person* row, judged (○) only once a row is named. Non-person actors never count (`is_person_actor`: the
  worker, `system…`, `cli:<os user>`, `service:…`, `import`, the empty actor) — a cell the
  worker graded from one operator's runs is that operator's alone, and a second approver
  CAN sign it. No `CRB_SIGNOFF__*` knob: `require_independent_verifier` may only be `true`
  (else `503 signoff_policy_invalid`) and is stamped into `policy_thresholds`, so an audit
  reads from the record that the rule was in force. The core stays stdlib-only: the
  actors are inputs (`attested_actors`, `cell_actors`); a caller that resolves none leaves
  the clause silent.
- **`verifier_kind`** on every sign-off (F34): `local` | `oidc`, stamped at write from the
  approver's issuer into `cell_json` under the hash (`crb.signoff.v3`; the v2 body's field
  tuple is frozen, so every earlier chain still verifies); `service` is reserved for a
  delegated, non-person signature and no write path mints it. Served on `POST /signoffs`,
  `GET /signoffs` and `GET /signoffs/{id}`, in `would_record`, on the `signoff.created`
  event and in the JSONL ledger's records; rows written before the field read `""`
  (`schema: crb.signoff.v2`), never a guessed kind. No migration. The Sign-off page shows
  it as a tag next to the approver (`local account` / `identity provider` / `service —
  delegated, not a person` / `kind not recorded`) with its meaning on hover. A signing
  account whose `users.issuer` is blank (no product path writes one) answers **503
  `account_issuer_missing`** on the write, the preview and a revocation, nothing written —
  a diagnosed answer naming the account, never a 500.
- The posture page's *Separation of duties* row and Home's *Why two people* now state the
  enforced rule; `docs/API.md` (`/signoffs`), `SECURITY.md` §3.4, `EVIDENCE-AND-CLAIMS` §6a
  (the claim sentence names the second person and the account kind; four clauses have no
  knob), DL-047. The browser walkthrough (`08-signoff`) is now a two-person walkthrough: the
  admin who queued every run is refused `same_actor`, and a `walk-approver` persona signs.
  Tests: `tests/test_signoff.py` (the clause on the attested row's actor, on the run's, on
  every-person-is-the-verifier, non-person actors, the relaxed-policy floor, v2 records
  verifying), `tests/test_server_routes_signoffs.py::TestTwoPersonRule` (409 at write, the
  preview, a second approver signing, `verifier_kind` `local` / `oidc` served and
  hash-covered).
- **ADR-0016** — the two-person rule is a policy clause, not an apparatus move:
  `APPARATUS_VERSION` stays `2.2` (bumping it would stale every current sign-off for a
  change that touched no grade — ADR-0015 §4); the seam an audit reads is `policy_version`
  (`v2` → `v3`) and `schema` (`crb.signoff.v3`), hash-covered and served on every read, so a
  pre-v3 record stays valid and is identifiable. Backlog F53: list active pre-v3 sign-offs
  in the Decisions inbox as "signed before the two-person rule". The rule is stated in one
  sentence, identically, in ONBOARDING-A-REPO, OPERATOR §5, API.md, SECURITY.md §3.4,
  EVIDENCE-AND-CLAIMS §6a and the §9 F7b row; SECURITY.md's two `[measured]` claims carry
  n, method and apparatus; DL-047 sits after DL-046 (append-only order).

## 2026-09-21 — the operating envelope: what the platform team is told is true (F36–F41, F44, F47, F25)

- **`/health` gains a `migrations` probe** — the contract is stated once, in
  [API.md — The `migrations` probe](../API.md#the-migrations-probe): `ok` at head; `degraded` (still served) for an unstamped `create_all` schema that matches the head, until `crb migrate` stamps it; `down` (the endpoint answers 503) when the store is behind, ahead, empty or an older unversioned schema (crb tables, no `alembic_version`, fingerprints of a revision behind the head) — revisions named where applicable, with the fix — or when it cannot be read — the fixed detail `migrations could not be read — see the API log, request id <id>`, `data: {}`, the exception in the API log under that id. The go-live checklist now
  points at a check that proves what it says (F36).
- **No probe on `/health` serves an exception** (CWE-209 — the route is unauthenticated): every
  read — `db`, `migrations`, `append_only`, `ledger`, `worker`, and the `sandbox`, `toolchains`
  and `builders` probes — runs under one guard, `crb.observability.probes.run_probe`; a read
  that raises is `down` with the one fixed detail `<probe> could not be read — see the API
  log, request id <id>` and `data: {}`, and the exception is logged under that id (the
  `X-Request-ID` the response echoes). Before, `db`, `append_only`, `ledger` and `worker`
  served `<ExceptionType>: <message>` — for PostgreSQL that is host, user and DSN. `crb
  doctor`'s lines render the same sentence without an id.
- **`crb doctor`** checks the GitHub App (configured, key readable, an installation reachable
  when configured), the Claude Code token store (a live turn only with `--live`), the
  database (initialised, every append-only trigger present, an UPDATE refused — the same
  reading as `/health`), the migration head, the worker heartbeat, the docs bundle in
  `ui/dist` (one non-empty chunk per guide) and where `CRB_HOME` and the secrets directory
  live (mode 0700 and owned by the current user) — each a labelled ok/warn/fail/skip line
  with the fix (F38).
- **A deployment never lives under an OS temp directory**: settings refuse in prod and warn in
  dev when `CRB_HOME` resolves under `/tmp`, `/private/tmp`, `/var/folders` or `$TMPDIR`
  (`CRB_ALLOW_TEMP_HOME` overrides for a knowing trial); DEPLOYMENT.md says why (F37).
- **Backup and restore (SQLite)** — quiesce, `sqlite3 .backup`, the tar of `home/evidence`,
  `home/events`, `home/factory`, `home/secrets`, `home/transcripts`; the proof reads the copy
  with sqlite3 and `crb ledger verify` (F44).
- **docs/RELEASING.md** — how a release is cut (version, CHANGELOG section, tag, the image
  release.yml builds and signs, the chart) (F40). The version moves in the release commit
  itself (RELEASING §2), not here: the tree stays `2.0.0a1` until `2.0.0b1` is cut; the
  chart's own `version` is now the SemVer form of the package version (`2.0.0-a1`) and
  `tests/test_version_consistency.py` pins all four numbers plus that rule
  (`test_chart_version_is_the_semver_form_of_the_package_version`). OPERATOR.md's front matter describes the
  product as it is, with the phase markers gone (F41); dangling cross-references resolved
  (F47).
- **`GET /settings/secrets` serves viewers `{name, present}` only** — a distinct
  `SecretPresenceOut` item model, so no empty `fingerprint` / `set_at` / `set_by` keys reach a
  viewer (F25).
- Tests: `tests/test_settings_home_guard.py`, `tests/test_cli_doctor.py`,
  `tests/test_server_system.py` (migrations probe; every raising probe serves the fixed
  detail and logs under the request id, through the route and at the function),
  `tests/test_store_migrate.py`, `tests/test_version_consistency.py` (chart version).

## 2026-09-21 — a locked-out administrator has a way back in (F23)

- **`PUT /users/{id}/password`** (admin), **`PUT /users/me/password`** (any local account,
  current password required), **`PUT /users/{id}/active`** with a last-active-admin guard
  (409 `last_admin`, decided under lock); `GET /users` rows carry `active` and `last_login`.
  A changed password ends every session issued under the old one at its next request
  (401 `session_revoked`): the signed cookie carries a fingerprint of the credential, so no
  session table and no migration; deactivation suspends sessions (re-activation within the
  TTL revives them — set a password as well, the docs say so).
- **`crb users list | create | set-password | activate | deactivate`** — break-glass on the
  API host against the same database `crb serve` uses; the password comes from a prompt or
  `CRB_USERS_PASSWORD_FILE`, never argv; actor `cli:<os user>`; the CLI names the database
  it resolved and never creates a stray one in the working directory.
- Every change is a `system` event on the account's trace (`user.password_set` with
  `by: admin|self|cli`, `user.activated`, `user.deactivated`, `user.role_set`) carrying actor
  and target and never a password. docs/API.md, SECURITY.md §3.3–3.4, OPERATOR.md §9 *Users*,
  DEPLOYMENT.md §8 (the go-live line is now achievable). Tests:
  `tests/test_server_admin_users.py`, `tests/test_cli_users.py`.

## 2026-09-19 — B-1b: the first real factory pull requests

- **Two pull requests opened by the factory on a real repository** — `Jita81/cobra` (a fork
  of `spf13/cobra` at `adbc881`), items authored from open upstream issues #2154 and #1918 with
  operator-authored oracles proven RED at the base, built by `claude_code / claude-sonnet-5`
  under the five belts, gated on the signed `bug.fix × S` cell (route *deliver*, `routing.v1`),
  reviewed independently, $0.69 in total, 11 minutes **[measured — run `e9acd89c…`, apparatus
  2.2, local executor: a development reading]**. Record:
  docs/reviews/2026-09-19-b1b-first-factory-pull-request.md; the backlog and the two Go tests
  are in docs/reviews/2026-09-19-b1b/. Decision DL-045.
- Found by the run, not yet fixed: a re-delivery after `accept_with_edit` cannot update the PR
  branch (`--force-with-lease` with no lease to hold — one rework build wasted); the route gate
  reads the map after the item's own row has landed (`n=27` in the PR body where the freeze saw
  26); the UI's *Run the factory* posts no builder (fix on the journeys branch); a deployment
  under `/private/tmp` loses files to the OS after ~3 days (stack relocated to `~/crb-stack`).

## 2026-09-19 — what the first factory run taught the loop

The first real factory run (B-1b: two pull requests on `Jita81/cobra`, $0.69 **[measured —
run `e9acd89c…`, apparatus 2.2, local executor: a development reading; n = 2 items]**,
record: docs/reviews/2026-09-19-b1b-first-factory-pull-request.md, decision DL-045) found
two product defects. Both are fixed here, with the tests that would have caught them.

- **A re-delivery after `accept_with_edit` updates the pull request it already opened**
  (finding 1). The rework's push used a bare `--force-with-lease`; delivery pushes to a URL,
  so git had no remote-tracking ref to lease against and answered `[rejected] … (stale
  info)` — and had the push gone through, a second pull request would have been opened for
  the same branch (GitHub 422). Now `git_push_fn(expected=…)` leases against the commit the
  first delivery pushed (`--force-with-lease=<branch>:<sha>`; a first push keeps the bare
  lease, which is what refuses a branch that already exists), `deliver(previous=…)` refuses
  a different branch or base, opens no second PR (url and number carried over) and posts a
  comment naming the rework (n, the verdict it answers, the new pack hash, the new commit)
  through the new `comment_pr_fn` seam (`github_comment_pr_fn`, the installation token, wired
  by the worker beside `open_pr_fn`). `DeliveryResult` gains `previous_commit_sha` and
  `updated`; the chain records the re-delivery as **`delivery.updated`**; the task view's
  `pr_url` folds from `delivery.opened` or `delivery.updated`. The bare-repository test in
  `tests/test_factory_delivery.py` reproduces the `stale info` refusal under real git, then
  proves the fix (correct lease moves the branch, a wrong lease is rejected and the remote
  does not move). The rework comment is the optional step and runs after the push has
  moved the remote branch, so its failure (a rate limit, a 5xx, a timeout) is not a delivery
  failure: `DeliveryResult.comment_error` carries the redacted failure, the chain still
  records `delivery.updated`, the trace gets a `delivery.comment_failed` warning and the
  item is reviewed on the branch the pull request now carries — the record agrees with the
  remote (verifier finding on this fix). The task view's `pr_url` follows whichever delivery
  event is newest on the chain, so a fresh pull request opened by a later run is never
  hidden behind an earlier run's update; the Factory screen's delivery step says
  "pull request updated by a rework" when that is the item's newest event.
- **The route gate reads the map as it stood before the run** (finding 2). The gate was
  evaluated at delivery, after the item's own `build.graded` row had landed: both PR bodies
  said `n=27` where the freeze saw 26. The decision is now taken ONCE per item at readiness,
  before any build — the worker's `_route_lookup(repo, run_id)` excludes the run's own rows —
  cached on the item, used by the gate and the PR body, and recorded on the item's
  `route.decided` event as `cell_route` (`n`, `point`, `ci_low`, `false_q1`, `policy_version`,
  `apparatus_versions`) so the chain quotes the pre-run map. ADR-0003 amended (2026-09-19);
  docs/API.md updated.
- **A `weak_oracle` verdict never triggers a rebuild against an unchanged oracle** (finding 3,
  DL-045 rule 3). The rework of `cobra-2154` re-proved RED with the same test the reviewer had
  just found weak and rebuilt — and the builder found another way to pass it (a guard dropped,
  untested). Now, in the loop's rework path, an `accept_with_edit` whose findings carry
  `kind: weak_oracle` rebuilds only against an oracle whose sha256 differs: with no test author
  (`rework_test is None`) the item stops **`oracle_needs_strengthening`** before any edit is
  permitted; with one, the author is asked and the same bytes back (or `None`) is the same
  stop. The stop is a `route.decided` event routing the item `human` — reason: the finding and
  the way forward ("strengthen the test and register a superseding item"; `after_verdict`,
  `finding`, `verdict_event`, `oracle_sha256`) — a `rework.refused` step on the trace, the
  reason on the `ItemOutcome` and on `item.outcome`; no second RED proof, build or push, and
  the pull request keeps the one reviewed build. A rework asked for any other reason keeps
  its path. The task view carries `outcome_reason` (the `item.outcome`'s `error`) and the
  Factory screen's outcome step renders the stop as a sentence with the way forward.
  `crb.factory.review.FINDING_WEAK_ORACLE` names the finding kind. ADR-0013 amended
  (2026-09-21); docs/API.md updated. Review follow-ups: the reason quotes the HEAD of the
  finding's detail (300 chars), so its prefix and way forward survive `ItemOutcome.error`'s
  tail cap whatever the detail's length; the outcome step gives the way forward once (the
  quoted reason is trimmed to the finding and why); the readiness step of a stopped item says
  it was built, then routed human after the review — `route_hint` is the item's newest route.

## 2026-09-19 — journeys that explain themselves: contextual help, honest in-flight states, telemetry a platform team can use

Six streams on one foundation. Every screen now says what it is for, what to do next
for the role reading it, what its numbers mean and where the definition is; every
in-flight state names the stage, the count and the money; and the run, the queue and
the worker report the same facts to the person and to the platform team's dashboards.

**On-ramp** (`/home`, `/connect`, `/connect/:name`, `/connect/:name/measure`, `/login`)

- **Home:** the green button reads *Continue to task N: name* and lands on the first task
  the person can act on (nothing connected → task 2 → `/connect`, never an empty
  Decisions). Task 6 is *Read the baseline* and completes once the repository has an active
  sign-off, so 8 of 8 is reachable. Task 8 reads *Backlog frozen — run the factory* with a
  frozen backlog and no run, and *In progress — item k of n* only while a factory run is
  queued or running. A non-admin sees task 7 as *Not known yet* with who can add users.
  The degraded-sandbox banner opens `/posture`, not raw JSON.
- **Connection list:** the journey eyebrow; *gold-clean* is a term with its definition one
  click away; a measured repository's button reads *Baseline*.
- **Connection walk:** a queued run shows *Queued — n runs ahead of it*; a running stage
  shows its own counter (*Probing — running the repository's own suite (started 40 s
  ago)*, *Mining — 4 tasks found · 37 commits examined · target 25*, *Scoring oracles —
  task 3 of 12*, *Measuring — attempt 3 of 10 · $0.42 so far, builder-reported*) and an
  in-flight panel with *Open the run* and, for an operator, *Cancel the run* behind a
  confirm that says attempts already made are still charged. A failed measurement with no
  rows reads *Failed* with *Retry*; a cancelled one says how many rows landed. A viewer or
  approver reads *An operator runs this* instead of the bare word *operator*. Oracle
  strength and negative controls carry their definitions.
- **Measure:** the kicker says *task 5 of 8 · this step spends money*; the button reads
  *Start the run — estimated $8.16 to $12.24* (no promised cap) and the Budget cap row
  says there is no spend cap yet, what each attempt is capped on, and that cancelling
  still charges attempts made. The estimate links *Measure: the money step* in the bundled
  guide. While a replay is queued or running the red button is gone and a banner says
  *A measurement is already running for repo — started 14:05; 3 of 10 attempts made;
  $1.02 spent so far*. The no-gold message points at stage 3 and links Configuration.
- **Login:** *Measures what an AI builder can be trusted to change in your repository,
  graded by your own tests.*
- **Baseline** (`/results`): reached from the nav with no repository chosen, the most
  recently updated repository is picked and written into the URL; *Loading the baseline
  for repo…* while the map loads; a blue *A measurement is running* banner (attempt,
  spend so far, *Open the run*) while a replay is in flight. The Oracle strength tile
  shows n, *95% CI —* with *no interval: a mean of per-task scores, not a rate* and an
  apparatus line from the report and the policy in force; the Negative controls tile's
  apparatus line is the report's own stamp. The four route names are terms. A viewer
  sees *Read* + *approver acts* instead of *Attest*; *sign-off due* is plain text for
  anyone who cannot sign.
- **Decisions** (`/decisions`): kicker *Under apparatus 2.2* with apparatus as a term;
  each row's reason code is a term with its meaning beside it; *Revoke or re-sign* only
  for an approver.
- **Sign-off** (`/signoff`): eyebrow *Journey · 3 of 4 · Decisions · sign-off*; a
  two-sentence purpose; the seven refusal clauses behind *Why a sign-off can be refused*
  with each term defined inline; a viewer or operator keeps the gate, the evidence and
  the attestations but never the approver form, and is told so. Not found goes *Back to
  Home*.

**Factory** (`/factory`, `/posture`)

- **Run the factory** works from the UI: it posts the builder `builderChoice` picks (as
  Measure does) and is disabled with Measure's reason when there is none; an operator can
  name another builder. A *Before you run* summary states the builder, *k of m will be
  worked (j wait on a signed gap); d sit in a cell that routes deliver*, the estimated
  cost as a ±20 % band on the repository's measured mean with n and apparatus (or the
  guide's planning band, said to be unmeasured), the delivery target (*not linked — no
  pull request* with the reason and the admin's next step, or *pushes a branch to
  owner/repo and opens a pull request against main; nothing is written to main*), that
  there is no spend cap yet and that cancelling still charges built items; the button
  names the estimate (*Run the factory — estimated $X to $Y*), never a cap the request
  does not carry. Reached from the nav with no repository chosen, the most recently
  updated one is picked and written into the URL, as the Baseline does.
- **`GET /factory/{repo}/backlog`** carries `delivery: {can_deliver, reason_code, reason,
  full_name, default_branch, installation_id, account_login}` — a server pre-flight
  answered by the same rule as the worker's delivery credentials (host check included,
  CWE-201). The deliver checkbox is enabled only when it says the repository can deliver;
  the approver's override explanation is visible text.
- **Every item says why it stopped**, from the chain: a structural gap and how to bring
  it back, a RED refusal with its reason, *Delivery withheld — the route gate*, *Delivery
  failed — the push was refused*, a dependency wait naming the item. `FactoryTaskOut`
  gains `value_gaps`, `refusal {step, reason, reason_code, measured_route}`, `error`,
  `task_id`, `run_id`, `pack_hash`, `row_hash`; `dor_gaps` is structural slots only.
  *Freeze a revised backlog…* opens the dialog prefilled from the active backlog. A built
  item has an Evidence button and a *run id* link. While a run is active the items poll
  every 5 s under a banner (*item 2 of 5 … $0.31 so far · Open the run · Cancel*);
  afterwards one line summarises the last run. At 375 px each item is one line with the
  six readiness cards behind *All 6 steps*, and the page no longer scrolls sideways.
- **Deployment** (`/posture`): every row that is not the production posture ends with
  what to do, with a Settings link for admins and a guide link for everyone; a Delivery
  group (Writes, Permissions with *k of n installations can deliver*, Route gate under the
  live policy name, Override, Credentials).

**Instrument** (`/capability`, `/routing`, `/oracle`, `/learn`, `/ledger`, `/settings`,
`/repos`, `/runs`)

- **Map grid:** the tile's five abbreviated numbers no longer rely on hover titles — every
  tile is `aria-describedby` one visually-hidden legend and a visible legend sits under
  the grid; the reason code in the cell card opens its sentence inline (`ReasonCode`, the
  same a11y contract as `Term`); the idle state's action is *Connect a repository*;
  *Start a replay run* is operator-only.
- **Routes:** each reason code opens its plain sentence inline; *No decisions yet* offers
  the run to operators only.
- **Oracle:** the purpose says what a green is worth; the two *auto-ship* strings are
  gone; a legend explains Band and Gate; the controls section explains negative controls,
  VIOLATION and controls escape; Run oracle / Run controls are operator-only.
- **Learn:** card eyebrows are *Refusals*, *Weak oracles*, *Stale evidence*; each report
  opens with what a person does with it; codes are plain words.
- **Ledger:** the abstract export's meaning is visible text (*Cells only: no code, no
  identifiers; what a federated deployment may share*); a filter legend defines clean,
  belt, sighted and blind.
- **Settings:** a read-only GitHub App installation says which permissions to grant and
  to sync; the not-configured state, the builder-token card and the Users card link the
  bundled guides; the Users card explains the role ladder.
- **Repositories:** Next steps are Connection walk · Factory · Capability map · Oracle
  adequacy · Runs; the active tab lives in `?tab=`; the run button is operator-only. All
  instrument screens carry an *Instrument · name* eyebrow.
- **Runs** (`/runs`, `/runs/:id`): the Kind filter offers probe, label and factory. The
  Progress card has a *Now* line (*Started 12 min ago · 3 of 10 tasks done · $0.84 so far
  · about 28 minutes left if the 7 remaining take the mean of the 3 done — a planning
  estimate, not a measurement*), a queue line (*Queued — position 3 of 7 · ahead of it:
  2 replay, 1 mine*, or that the server does not report the position), a stage line from
  the last event (*Task 4 of 12 · build · turn 7 of 25*), and a heartbeat line that turns
  amber only when older than the worker probe's `stale_after_s`. A factory run's header
  reads *delivery on (override by name)* when the server sends `factory`. The live log
  reads *belt ✓* / *belt ✗ — 2 new failures* with a red glyph, and every row carries
  `actionHelp(action)` as a muted second line (*Explain each row*, on by default). The
  Evidence drawer's Pack tab opens with one headline sentence (*Not clean: belt 3 (the
  repository's own suite) — 2 new failures: …*; *Clean: all five belts held and the
  pack's hash verifies. This says nothing about whether the change is mergeable*).
  Oracle, controls and label runs render `counts.detail` as tiles.

**Telemetry** (`/health`, `/runs/:id`, `/metrics`, events)

- **Worker heartbeats:** a `workers` table every worker upserts each `heartbeat_s` even
  when idle. The `/health` worker probe reads it: three queued runs with a crashed worker
  read `degraded` *3 runs queued, no worker has checked in for 360 s (w-1) — queued runs
  will not start until a worker does* instead of ok *idle, 3 queued* (never `down`: the
  API pod's readiness is not the worker's liveness, and a 503 would take the API — and the
  sentence — out of the Service); behind a clean stop it names the stop (*the last worker
  (w-1) stopped 40 s ago*); a fresh store says *no worker has checked in yet*; ok reads *1
  worker, last check-in 4 s ago · 2 runs queued*. `data` carries `workers[]`, `queued`,
  `stale`, `stale_after_s`; alive = a heartbeat within 3 × that worker's `heartbeat_s`.
  Deployment (`/posture`) shows the worker probe's sentence as a row, and says when the
  health check itself could not be read.
- **`RunOut`** gains `queue_position` (1-based FIFO; null unless queued),
  `queue_kinds_ahead` (oldest first) and `factory {deliver, deliver_override_by,
  deliver_override_by_name, backlog_hash}` (null for every other kind). An oracle,
  controls or label run serves its own counters verbatim under `counts.detail`, so it no
  longer renders as *Clean 0.0 %* with a Wilson interval over the wrong n; a label run's
  spend is in `detail.usage.cost_usd`. Shapes per kind are in API.md.
- **Events:** `run.cancel_requested` is written for queued and running runs and names the
  operator who asked (not the run's creator), with `status_at_request`;
  `signoff.revoked` carries `row_hash`, `revokes_row_hash` and the note, so an auditor
  reconciles against the chain without searching by time. `tests/test_event_vocabulary.py`
  fails on a missing or a ghost action in API.md.
- **Metrics:** the worker serves its own `/metrics` on `CRB_METRICS_HOST:CRB_METRICS_PORT`
  (default `127.0.0.1:9464` — loopback like the API's bind, because the series name
  repositories, builders, per-repository cost and installation ids; 0 = off; compose and
  Helm set `0.0.0.0` inside the container, where only the compose network / the
  NetworkPolicy's scraper reaches the port: Helm container port + headless Service +
  opt-in `serviceMonitor.worker` + NetworkPolicy rule). `crb_builder_tokens_total` and
  `crb_builder_cost_usd_total` gain a leading `repo` label; new
  `crb_deliveries_total{repo, outcome ∈ opened|withheld|failed}` (metered from the
  worker's event sink), `crb_github_tokens_minted_total{installation}` (a real mint only,
  by digest — never the token), `crb_queue_depth`. DEPLOYMENT.md §9 Observability: the
  metrics table by process (ratchet-tested against `metrics.py`), four alert rules,
  scrape targets, logs, events.
- **Logging:** the text formatter now redacts tracebacks; a broken %-format record no
  longer reaches `Handler.handleError` with raw args.
- **Fixed:** `tests/test_store_migrate.py::test_module_is_runnable_as_main` ran the venv's
  editable install instead of the worktree; the child now gets `PYTHONPATH` pointing at
  the src the module was imported from.

**Help** (`/help`, `/help/docs/:name`, every route)

- **One help mechanism.** `ui/src/help/`: `glossary.ts` (22 terms, plain English, each
  with a guide anchor), `docs.ts` (the eight user-facing guides bundled at UI build time
  as lazy chunks — the repository is private and a deployment may have no egress; DL-046),
  `markdown.ts` (a subset renderer to React elements, never raw HTML), `help.ts` (`HELP`,
  one entry per route in App.tsx; `helpFor` via `matchPath`). `AboutThisScreen` is
  mounted once in Layout after the outlet: purpose · next step by role · what the numbers
  mean · terms · read more · glossary link. `Term` is a real button
  (`aria-expanded`/`aria-controls`, Escape closes, no hover tooltip); `DocLink` opens a
  bundled guide at its heading. `PageHeader` defaults its eyebrow to the journey position
  (`journeyEyebrow`).
- **`/help`** (glossary, guide index, ADR titles) and **`/help/docs/:name`** (a bundled
  guide, scrolls to the hash; unknown name → empty state). Help as a compact ? icon in
  the top bar (the display name hides below `sm`, so the cluster is one row at 375 px and
  *Sign out* never a third header row); Help · Glossary in the footer.
- **Copy:** the human route names all three causes; deliver, the strong band and the
  oracle gate say *a branch and pull request under review, never a merge* — the
  *Auto-ship* label is gone (API enum values unchanged). `ACTION_HELP` / `actionHelp`:
  one plain sentence per event action.

**On the merge** (what fell between the streams): `/runs?new=<kind>` opens the start
dialog only for a role that can start a run — a viewer or approver reads *An operator
starts a run; it spends model budget* (J-FAC-12); a task the factory built is introduced
on `/tasks/:repo/:taskId` as *One factory item (I-2) — not a replayed commit: the id is the
authored test's sha* (J-FAC-18); `DocLink` is underlined, so a guide link inside a
sentence is told apart without colour (axe `link-in-text-block` on `/settings`, WCAG
1.4.1); `repo.github_linked` (#34) joins the event vocabulary table and `ACTION_HELP` —
the ratchet caught it; the `/results` help copy no longer cites a backlog id. With the
three loop rules (#39): the rule-3 stop's `route.decided` to `human` carries `after_verdict`,
so `refusal` folds it as step `review` — a built, delivered item is never read as *Routed to
a person* at readiness; the review step says the reviewer asked for a stronger test and the
item's sentence gives the finding and the way forward; `pr_url` follows a rework's
`delivery.updated`; the status list reads *Test needs strengthening*; `delivery.updated`,
`delivery.comment_failed` and `rework.refused` join the event vocabulary table and
`ACTION_HELP` — the ratchet (`test_event_vocabulary`) caught all three.

**On review** (three adversarial verifiers, 21 surviving findings): the worker probe never
turns `/health` into a 503 (above); the worker's `/metrics` binds loopback unless
`CRB_METRICS_HOST` says otherwise (above); `ACTION_HELP` is keyed exactly as the
vocabulary table is — the belt-5 pre-flight and sealed-container events under their
`builder.` prefix, the four legacy import events added, seven sentences for events
nothing emits removed — and `verdict.test.ts` now reads docs/API.md as
`test_event_vocabulary.py` does, so the two halves cannot drift; the Connection walk
reads `queue_position` from the API (the queued list is the older-server fallback); one
`fmtAgo` in `ui/src/lib/format.ts` serves the walk and the run page; every count line is
pluralised (*1 task scored*, *1 escape*); a passed controls report that still carries an
escape or a thin set reads *Done, with a finding* in amber with *deliver is withheld
until the tests are hardened and the controls re-run* — the walk goes on, the finding is
named — and the glossary's negative-controls entry says what *passed* means; the help
copy names controls that exist (*Baseline*, *Not started*, *Start a run*) and actions the
role can take (a *Sign a gap* row is the approver's); a viewer's Home button names its
destination; a non-operator on Measure reads the choices as lists, not live radios; the
Factory empty state offers *Connect* only to an operator on an empty deployment; the
licence sentence carries builder/model (EVIDENCE-AND-CLAIMS §7); the Decisions pill reads
*n waiting across k repositories*; `Term` and `ReasonCode` share one `InlineDisclosure`;
Deployment shows the worker probe and says when the health check could not be read; the
11-screens spec annotates instead of `console.log` and asserts a two-row top bar at
375 px; a filled button darkens on hover instead of fading (the axe sweep caught a filled
*Baseline* at 3.97:1 under the pointer); ten *Works with* blocks are back within three to
eight entries.

**Tests.** UI: 49 files / 340 tests — `Help`, `Layout`, `PageHeader`, `govuk`, `StatTile`,
`help/{glossary,docs,help,markdown}`, `verdict`, `builder`, `connection`, `HomePage`,
`ConnectPage`, `MeasurePage`, `LoginPage`, `ResultsPage`, `MapTable`, `DecisionsPage`,
`decisions`, `SignoffPage`, `NotFoundPage`, `FactoryPage`, `CapabilityPage`, `RoutingPage`,
`OraclePage`, `LearnPage`, `LedgerPage`, `SettingsPage`, `GitHubAppCard`,
`ClaudeCodeLoginCard`, `RepoDetail`, `RunsPage`, `RunDetailPage`, `telemetry`, `ReviewPanel`,
`HelpPage`; the help ratchet checks every App route has an entry and every anchor resolves
to a real heading. Python: `test_deploy_health_probes` (worker probe),
`test_server_routes_runs` (queue position, per-kind counts, factory), `test_worker` and
`test_worker_label` (heartbeat table, metered GitHub app, counters), `test_store_jobs`,
`test_event_vocabulary`, `test_observability_metrics`, `test_observability_logging`,
`test_server_routes_factory` (delivery pre-flight, refusal), `test_server_routes_signoffs`
(revoked payload), `test_server_system`, `test_store_migrate`. Walkthrough: `10-factory`
(freeze → run → chain → evidence → Runs → 375 px) and `11-screens` (every route × persona ×
width, the About block on every authenticated route).

## 2026-09-18 — link a repository you already measured to the GitHub App

- **`POST /repos/{name}/github-link`** `{installation_id, full_name}` (operator) attaches an
  EXISTING crb repository to one of an installation's repositories: the row keeps its name —
  and so its ledger rows, map and sign-offs — while its `url` becomes the https clone URL,
  `github_full_name` the constrained identity and `config_json.github` the link connect
  writes. Language, runner, layout and belt scope are not touched. The case it exists for:
  a repository measured before the app existed, or whose history now lives on a fork
  (`cobra` → `Jita81/cobra`, B-1b). Recorded as a `repo.github_linked` event with
  `url_before` / `url_after` / `previous_full_name` — a visible seam on the events table,
  not a silent edit. 409 when the GitHub repository is linked to a different row (the unique
  index decides a race); a viewer may not link. The worker's host rule is unchanged: a token
  goes only to an https remote on the app's own host (CWE-201). The event also carries the
  `repo.updated` shape (`fields: ["url"]`, `diff: {url: {from, to}}`) so the Configuration
  tab's audit trail renders "Changed: url" with the before/after.
- **Written only when GitHub's answer IS the repository asked for** (connect and link share
  the guard): the client now treats GitHub's 3xx as a refusal (a renamed or transferred
  repository's 301 is a 502 naming it — it never follows redirects, and the redirect body
  read as an EMPTY record before), refuses a dot segment as owner or name (`../rate_limit`
  would be collapsed by the URL layer into `GET /rate_limit` under the installation's
  bearer) — the request bodies carry GitHub's own `owner/name` grammar — and refuses a 200
  whose `full_name` is not the one asked for (422 naming the current name) or that has no
  `clone_url` (502). Before this a renamed repository linked as `url=""` with a 200.
- **Connect dialog polish:** the link-mode select says *Loading repositories…* while the
  list loads; a failed attempt's alert clears when the mode is switched; a long clone URL
  wraps at phone width. `SelectField` and `TextArea` now describe their hint / error to the
  control through `aria-describedby` as `TextField` always did.
- **Connect dialog:** once a repository is picked, two ways — *Register as a new repository*
  (the form as before) or *Link to an existing repository* (a select of the repositories
  with no GitHub link). `GET /repos` rows carry `github_full_name` so the select can filter.
- Connect and link both catch the unique-index refusal at the event's autoflush as well as
  at commit (a race answered 409, never 500).

## 2026-09-17 — the factory is the point (DL-044): route before the spend, a backlog as a person writes it, the journey re-centred

- **DL-044** — the factory and the self-improvement loop are the product; connect → measure →
  sign-off is the on-ramp that earns their baseline; the end state is a framework the teams
  using it improve. README says so; the backlog is re-ordered by it.
- **F28 — the cell's route before the run.** Every factory task carries `cell_route`
  (`route`, `reason_code`, `reason`, `n`, `deliverable`) from the SAME signed map the
  delivery gate reads; the Factory page shows *routes deliver · n=…* / *routes calibrate —
  delivery withheld* / *cell not measured — delivery withheld* on each item and counts how
  many items a run could actually deliver, before anything is spent.
- **F24 — the backlog as a person writes it.** `GET /factory/catalogue` serves the readiness
  catalogue (each class's structural and value slots with their questions, the sizes, kinds
  and levels); the freeze dialog is a form that asks those questions per item and posts
  `slot: fact` lines, with "Advanced: paste JSON" for a prepared file. An empty structural
  answer is exactly the gap the run will stop on.
- **The journey re-centred.** The nav is Home · Connection · **Baseline** · Decisions ·
  Factory · Deployment for every role; the operator's tooling (Runs, Map grid, Routes,
  Oracle, Learn) sits on an *Instrument* row operators see, Ledger stays for every role,
  Settings for admins; Repositories and Sign-off left the nav (still routable — Connection
  lists repositories, Decisions and the map link to the sign-off form). Home's walk ends at
  task 8 **Deliver your first change**, with its status from the backlog and items; the
  Results page is titled *Baseline*.
- Test infrastructure: `Dialog` mirrors its jsdom fallback for `close()`.

## 2026-09-17 — the NHS design system and the prototype's screens, on real data (DL-042)

The operator's Claude Design prototype ("crb Front End", twelve NHS/GOV.UK-patterned
screens) was read against the front end; the verdict and the screen-by-screen comparison
are in docs/reviews/2026-09-17-claude-design-prototype.md. Its grammar is adopted; its
numbers were never trusted.

- **Design system**: the light theme is the NHS palette (NHS blue accent on white, the
  design system's green / warm yellow / red for status, Arial); the header is the NHS blue
  bar with the `crb` mark over a dark-blue nav row that carries a **Decisions badge**, with
  the explore screens on a grey row beneath; a full-width red **stop-condition banner**
  appears on every screen while the ledger holds a false-Q1 row. New GOV.UK/NHS pattern
  components: `Tag`, `TaskList`, `SummaryList`, `NotificationBanner`, `WarningCallout`,
  `InsetText`, `BackLink`, `ConfirmationPanel`, the green / red / grey buttons.
- **Home** (`/home`) — "Get started": the seven tasks (connect GitHub, choose a repository,
  confirm its shape, prove the instrument £0, measure — spends money, read the map, invite
  an approver) with statuses derived from the API, "completed n of 7", the degraded sandbox
  as an *Important* banner, the cost sentence, "Why two people".
- **Measure** (`/connect/:name/measure`) — attempts (10/30/60 with what each buys),
  retention with the policy statement, "Before you start" (the estimate from the
  repository's own measured cost per attempt, the cap, retention, posture) and one red
  button that names the spend.
- **Capability map** on Results — the class × size **table** with the route as a solid
  tag, `n on tasks`, point and interval, and the sign-off state on the cell (*signed
  <date>* / *sign-off due* / *sign-off stale*); "What this licenses you to say" for the
  signed cell with every qualifier the claims policy demands; economics tiles; the "no
  throughput headline" callout.
- **Decisions** — the NHS grammar, and a **"Signed cells now stale"** section.
- **Sign-off** — "What your signature does not mean" before the affirmation; a
  **confirmation panel** with a reference and "what happens next" after a recorded sign-off.
- **Deployment posture** (`/posture`) — "About this deployment" for an architecture review
  board, printable, from `/version`, `/health`, `/settings` and `/ledger/verify`.
- **Core / API**: a sign-off made on an earlier apparatus is **stale** — it lifts nothing at
  read (`SignoffRecord.covers_apparatus`, ADR-0002/EVIDENCE §4) and is served with
  `stale: true`, `apparatus_current` and `active: false`. The prototype drew this as if it
  existed; it did not.
- Backlog: F3b (shape review with risk copy), F5b (per-run spend cap), F7b (separation of
  duties at write — the prototype claims it; the product does not enforce it) added to
  docs/reviews/2026-09-17-enterprise-front-end.md §9; F2 and F19 marked landed.
- **Review findings on the GitHub App connection (CodeRabbit on #31), fixed here**: the
  setup callback records an installation only with a signed `state` the install link carries,
  bound to the operator AND to a nonce the same response sets as an httponly cookie, consumed
  by the write (`GET /github/app` mints it for operators; without both the callback writes
  nothing and lands on Connect `unverified=1`, where the CSRF-protected sync records it —
  CWE-352); revision 0006 refuses to run while two legacy rows link the same GitHub
  repository (naming them) and creates its unique index only after the backfill; an empty
  2xx from GitHub is a 502, never a false "no installations"; `repos.github_full_name` (revision 0006, unique) makes "one GitHub
  repository connects once" a database fact and the race a 409; a `PUT /repos/{name}` that
  changes the URL drops the GitHub link, and the worker sends an installation token only to
  the app's own host (CWE-201); delivery credentials exist only while the installation
  grants `contents: write` **and** `pull_requests: write`, read from GitHub at the time
  (no branch pushed before a PR call could fail); a malformed 2xx from GitHub is a 502, not a
  500; the per-request GitHub client is closed; the worker reads only `CRB_GITHUB__*` and
  refuses to start on a malformed value instead of running without the connection; the
  picker says a search is page-local; the Measure page prices the capped attempt count and
  derives posture from the probe's explicit `executor`; the Decisions count is never served
  as ready with a non-404 failure behind it; Home and Deployment do not call an unanswered
  GitHub App status "not configured"; every map cell carries its apparatus; the unversioned
  schema walk is revision-ordered across columns, indexes and tables.
- **Four external documents assessed against the product** (docs/reviews/2026-09-17-external-documents-assessment.md,
  an independent Fable pass): the Quality Floor essay (the product honours every mechanism
  it names and is stricter on most; the essay copy on disk still carries the pre-correction
  specification-lever figures — not re-imported), the Automated Agile process architecture
  (mostly out of scope by DL-001; three transferable items), the AAF ISO architecture and
  code-quality guide (substance already met; two learnings), and the operator's experience
  profile (nothing new — the product embodies it). Eight rows F27–F34 added to the backlog:
  audit sample per signed cell (P1), item route before the run, PR body naming the signed
  facts and the licensing sign-off, human PR review comments as evidence, the repository's
  own security scanner as a review probe, review finding → follow-up item, a
  recurrence-after-prevention alarm, verifier account kind on attestations.
- **Persona walkthrough on the live stack** (docs/reviews/2026-09-17-persona-walkthrough.md).
  Scope, stated separately: the journey screens were driven in a real browser as a viewer,
  an operator, an approver and an admin, each along their own path (not every screen by
  every persona); the developer and platform-engineer paths were the Factory, a run's
  evidence pack and the not-configured GitHub dialog; the MCP consumer was driven over stdio
  as the viewer (38 tools, reads answered, `crb_start_run` refused 403), not through the
  browser; axe WCAG 2.1 AA covered nine journey screens for three of the four personas; the
  375 px check covered Home, Results, Sign-off, Decisions and Deployment. What it found and
  fixed: the Measure page posted no builder (422) — it now derives the builder from
  the health probe; the connection walk said *Done* while a replay was running — running
  outranks done; the sign-off form asked for an affirmation without showing the diff — the
  retained patch is now on the form (`ReadTheDiff`); sign-offs named the approver by user id
  everywhere including the licence sentence — the API now resolves `approver_name` /
  `revoked_by_name` at read; **revoke** was one click with no reason — it now confirms and
  records a required reason as the revocation note, and revoked rows stay listed; Home gave
  a viewer an operator's to-do list and called a run in flight *Incomplete* — role-aware copy,
  *In progress*, the map openable from the first row, no non-admin sent to `/settings`; the
  login page offered the organisation button when no provider existed — `/version` now says
  `oidc_enabled` and the button and the posture row read it; the admin Users table's Username
  column was blank (API `subject` vs UI `username`) — `/users` now serves `username`; the
  Factory chain drew a never-built item as *failed* and an unassessed one as *done* — both
  read honestly; two WCAG 2.1 AA findings (an undistinguished link in the Important banner,
  the red pill ink at 4.4:1 — WCAG contrast ratios, not sampled rates) — links in prose
  underline, the red soft fill is lightened to 4.7:1; the journey screens joined the
  walkthrough's axe sweep. Figures from the stack, tagged: the operator's run
  `6fb61af9…` (cobra, replay, sighted, `claude_code / claude-sonnet-5`, apparatus 2.2) made
  10 attempts, 9 clean, $2.57 builder-reported, against the Measure page's ±20 % planning
  band around the repository's measured mean [measured — the run's ledger rows]; during the
  walk cobra's `bug.fix × S` cell moved from *calibrate* (23 of 24 clean, 95.8 %, 95 %
  Wilson [79.8 %, 99.3 %] — lower below the 80 % bar) to *deliver* (24 of 25 clean,
  96.0 %, 95 % Wilson [80.5 %, 99.3 %]) under `routing.v1` [measured — `/capability-map`,
  current apparatus 2.2, sighted, `claude_code / claude-sonnet-5`]; ledger after the walk 602
  rows, chain intact, false-Q1 0, 0 clean rows without a pack [measured — `/ledger/verify`,
  apparatus 2.2; exact counts, no interval].

## 2026-09-17 — the GitHub App is the connection (ADR-0014, DL-041)

The first item of the enterprise front-end backlog (F1): an organisation installs the
deployment's GitHub App on *selected* repositories and the product connects them from a
picker — no personal access token, nothing long-lived stored.

- **`crb.server.github_app`** — the app client: an RS256 app JWT (nine minutes), the app's
  installations, an installation's repositories, and installation tokens minted per use,
  cached in memory until five minutes before their one-hour expiry, never persisted. GHES via
  `CRB_GITHUB__API_URL` / `__WEB_URL`.
- **Routes** — `GET /github/app` (configured? install link? installations on record — never
  404s), `GET /github/setup` (the app's Setup URL: verifies the installation with the app's
  own credential, records it, lands on Connect), `POST /github/installations/sync`,
  `GET /github/installations/{id}/repositories` (the picker, with a suggested name /
  language / runner per repository and `connected_as` for those already connected),
  `POST /github/installations/{id}/connect` (an ordinary repository row, linked through
  `config_json.github`; the link survives config updates).
- **Worker** — a linked repository clones with the installation's token passed to git as a
  one-shot `Authorization` header through `GIT_CONFIG_COUNT` (never argv, never
  `.git/config`); a factory run on a linked repository whose installation may write gets
  its delivery credentials from the same token and opens the pull request against the
  repository's default branch; a read-only installation fails closed on delivery.
- **Store** — revision `0005`: `github_installations` (mutable state, no triggers).
- **UI** — *Connect from GitHub* on the Connect screen (installation → search → pick →
  confirm the pre-filled name/language/runner → connect; a connected repository is marked
  and cannot be connected twice; an unconfigured app is a state with the URL fallback, not
  an error); the setup callback lands on `/connect?installation=` with the picker open;
  Settings gains a GitHub App card (configured / install link / installations, "can
  deliver" vs "read-only", sync).
- Docs: `docs/GITHUB-APP.md` (register once, install per organisation, the permission table
  and what each is for, federation, trial without the app); ADR-0014; API, DEPLOYMENT
  (`CRB_GITHUB__*` on the API **and** the worker), SECURITY §3.3, OPERATOR §2.0.

## 2026-09-17 — the front end has a purpose: connect → results → decisions → factory (DL-040)

The operator's brief: "if we are keeping the front end it should have a purpose. It should be
the points where human sign-off is surfaced. It should be the process of the factory, and
before that a guided walk through GitHub and a results page for enterprises to select a
repo." The primary navigation is now that journey; the evidence screens sit behind it as
*Explore* (every old route still works — nothing was removed from the URL space).

- **Connect** (`/connect`, `/connect/:name`) — a guided walk from a Git URL to a results
  page: register → probe → mine → oracle → controls → first measurement, as a task list whose
  statuses are *derived from the API* (`ui/src/screens/Connect/connection.ts`: a stage is
  done only when the API holds its evidence; a 404 oracle/controls is "not started", never
  an error; a running run is watched and the inputs refetched when it ends). Each stage says
  what it proves and what it costs ("no model involved" / "spends model budget"); actions are
  operator-gated like the API; the list shows every connected repository's next stage.
- **Results** (`/results?repo=`) — the answer in the order an enterprise reader needs: is the
  instrument trustworthy here (controls verdict, oracle mean, false-Q1, each with n); what may
  the builder be trusted to do (cells per route with n, the top cells, and a sentence saying
  what `deliver` means and does not mean, with the policy's numbers); what waits on a person.
- **Decisions** (`/decisions`) — the inbox: across repositories, every cell whose sign-off is
  due (unsigned `deliver`), every cell routed to a human with its reason, every `do_not_ship`,
  every factory item blocked on a structural gap, routed to a human, asked for rework, or
  withheld by the route gate — ordered by what blocks what, each row linking to the surface
  where the act is recorded (`/signoff?cell=` preselects the cell; `/factory?item=` scrolls
  to the item). A viewer sees the same rows with "View" and the role that acts.
- **Factory** (`/factory`) — the process, item by item: readiness → RED proof → build →
  delivery → review → outcome as a six-step list per item with why it is where it is; the
  human acts in place — an approver signs a structural gap (`POST …/signoff-gap`), an operator
  freezes a backlog (JSON, `POST /factory/{repo}/backlog`) and runs the loop (`POST /runs`
  kind `factory`, the `deliver` toggle; `deliver_override` shown to approvers only).
- UI types caught up with the API: `RunKind` gains `label` and `factory`; `RunCreateRequest`
  gains `deliver`, `deliver_override`, `max_rework`; cells and decisions carry `reason_code`.
