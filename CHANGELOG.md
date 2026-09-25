# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). The **apparatus version**
(`crb.core.version.APPARATUS_VERSION`) is listed separately because a change to it changes
the meaning of a verdict (see [EVIDENCE-AND-CLAIMS §4](docs/EVIDENCE-AND-CLAIMS.md#4-the-apparatus-stamp--evidence-expires)).

## [Unreleased]

### 2026-09-25 — keep what we make, stop paying for nothing (value programme, stream K)

- **Every graded attempt keeps its patch** (`crb.core.patches`, ADR-0006 amended): the
  grader's own text, redacted, capped at 1 MiB, content-addressed under
  `CRB_HOME/evidence/patches/` and named in the evidence pack; `GET /grades/{row_hash}/patch`
  serves it with no retained worktree. The 2026-09-25 export had 0 of 190 clean patches
  retrievable [measured — n = 618 exported rows, apparatus 2.0–2.2, method: each clean row's
  retention reason]. `CRB_RETENTION__PATCHES=false` keeps none.
- **A review's mergeable answer must agree with its words**: both review ledgers refuse
  `mergeable_contradicts_statement` at append; `POST /reviews/corrections/mergeable` (admin)
  appends a correction for a stored contradiction — the two found are never edited.
- **Escalation stops where it does not pay** (default `escalation: measured`): a failed
  attempt climbs only when that rung's earlier escalations in the cell came back clean at
  least 1 in 10 times (n ≥ 10); the rule is on the row; `always` per run or per repository. On the
  export, escalated retries returned 2 clean of 40 for $20.70 [measured — n = 40 valid r2/r3
  rows, apparatus 2.0–2.2, method: the product's failure rule, `scripts/spend_from_export.py`].
- **Opt-in calibrated budget** (`budget_profile: calibrated`, per run or per repository):
  caps from the cell's clean completions (p90 × 1.5, floor the run's caps, ceiling twice
  them, n ≥ 8), recorded on the row. Off until a paired comparison measures it.
- `scripts/spend_from_export.py` recomputes the budget-stop and escalation numbers from a
  ledger export with the product's own failure rule.
### 2026-09-25 — "clean" means working, by construction (opt-in, ADR-0021)

Of the clean patches a person has reviewed, 4 of 13 would have been merged **[measured —
n = 13 reviewed clean patches, method: the review records and the cobra critical-friend
review, apparatus 2.2]**; two of the reasons are mechanical. Three mechanisms, each OFF by
default and recorded on every row it touches:

- **The format step.** The repository's own formatter rewrites the changed source files
  before grading, so the graded patch is the formatted one; skipped with a named reason when
  the repository configures none (`labels.format_step`).
- **The finish gate.** The repository's own checks go in the brief as a numbered checklist,
  are re-run after the build, and one bounded repair call follows a failure; `done` needs them
  to pass; a blind checklist that names the held-out oracle is refused before any spend
  (`labels.finish_gate`).
- **Belt 6 `api_stable`.** A patch that changes the public API of the code it touched (Go,
  Python, JavaScript/TypeScript) in a way the maintainers' commit did not is not clean;
  failure kind `api`; recorded as the hashed `api_stable` label, which the ledger checks.
- **One switchboard.** `RepoConfig.checks` (written by `PUT /repos/{name}`, on the audit
  trail) and `params.checks` per run; every row records the switches, their sources and the
  configuration version (`labels.checks`). The prevention loop writes this surface.
- **The runner-command audit** of the six live repositories fixed five detector gaps: a frozen
  pre-commit ruff `rev` (click), a ruff outside the repository's pin now refuses instead of
  judging (mesh-client), black check mode (mesh-client), eslint/stylelint `--max-warnings`
  and stylelint itself (the NHS repositories), prettier on the files it formats
  (`docs/reviews/2026-09-25-runner-commands-audit.md`).
### 2026-09-25 — a bug is closed by prevention (ADR-0020, value wave stream L)

The operator: "we should be learning from a bug and then going back to update our process or
context to remove it moving forward." Every failure class a builder shows is now registered,
given the strongest change it admits, and kept, retired or escalated by what the next first
attempts show. Behind one per-repository switch, `learning.auto_apply`, which is **off** until
an operator throws it; the apparatus stays 2.2.

- **The register** (`crb.core.prevention`, `GET /learn/register`, `crb learn prevention`):
  every class of a repository with its evidence on first attempts, the lever the loop would
  choose and every lever it passed over, the change in force and its before → after with n
  and the bar, one of five statuses and the next step.
- **The rule** (`crb.prevention.rule.v1`): the before window is frozen at application;
  exposure is read from the row's own labels; decisive n = `ceil(ln 0.025 / ln(1 − p0))`;
  two looks; harm at the tenth attempt; closed on a zero run of `max(20, n)` with no
  displacement; a quiet class with no change on record is dormant and never credited.
- **The one rule**: the loop may switch on the formatter step, the finish gate and the
  calibrated budget, and add up to seven checklist lines from closed templates — never a
  grader key (`check_writable` refuses each by name). Lines never carry task text: held out
  by task, leak-gated at injection, capped, and tested with canaries.
- **The chain**: the loop's acts are hash-chained records in `learn.prevention.recorded`
  system events (no table, no migration); every row records `learn`, `learn_changes`,
  `learn_overlay`, `learn_lines`, `learn_dropped` and `learn_playbook`.
- **Operator acts**: `PUT /learn/switch`, `POST /learn/tick`, `POST
  /learn/changes/{id}/revert`, `POST /learn/items/{id}/register`, `POST /learn/links`; a run
  may opt out with `POST /runs {learning: "off"}`. The Learn page's register card and a
  `prevention` row in the Decisions inbox.
- `scripts/prevention_from_export.py` builds the register over an exported ledger (the
  export itself is never committed).
### 2026-09-25 — the scorecard: working changes per pound, blind

The operator asked for the product to produce working software and for its learning to get
better the more data goes through it. This adds the number that says whether it does.

- **`GET /value` and one Home tile.** `crb.core.value` computes working changes per pound on
  blind attempts (blind clean rate × clean → working precision over every pound spent on blind
  attempts, with the product of the two Wilson bounds as its range), clean → working precision
  (a person's reviews first, every repository's reviews next, a labelled lint-and-interface
  proxy last), the rows and pounds lost to budget, protocol, harness and outage, each bug
  class's recurrence per window of attempts from prior data only, and how precise `deliver`
  decisions were when made at the time. The register behind the curve is a stub until the
  prevention loop is wired (`default_register`), and the response says so.
- **The baseline, recomputed.** `scripts/value_baseline.py` runs the same report over an
  exported ledger; `docs/reviews/2026-09-25-value-baseline.md` carries it: about 7% of blind
  attempts would be merged, about one working change per £5 [measured — n = 94 valid blind
  attempts × n = 13 reviewed clean patches; method: the report over the 2026-09-25 export;
  apparatus 2.2]. The page is on the claims gate.
- **VALUE heads the definition of done.** A new product category, first in `product.md`, whose
  open criteria outrank every other in the order of work; the checker refuses a product
  artefact where it is not first.
### 2026-09-25 — our own bugs are closed by prevention, not by a fix alone

The product's loop now has one rule — learn from a bug, then change the process or the context
so its class cannot recur — and we build the product by the same rule (`docs/dod/STANDARD.md`
§7). `docs/PREVENTION.md` is our own bug register: each bug's class, when it bit us, and the
artefact that FAILS if the class comes back; `scripts/dod_check.py` refuses a row closed by
prose or by a reference that cannot fail, and the new pull-request template asks for the row.
Each artefact below was proved by breaking it and watching its test fail.

- **A CI job name can no longer outgrow a required check** (P-001):
  `tests/test_ci_job_names.py` renders every job name in every workflow, matrix values
  expanded, and fails at 100 characters.
- **The stack says when it serves stale code** (P-002): `/health` serves the commit the server
  was started from, the checkout's and the UI bundle's (`ui/vite.config.ts` now writes
  `build-stamp.json`; an image carries `CRB_SOURCE_COMMIT`) as `served` with `stale`, and a
  degraded `build` probe; `crb doctor` fails when the bundle is not the code and warns when the
  checkout trails `origin/main`.
- **A run that can only fail is refused at submit** (P-003): `POST /runs` answers 422
  `builder_credential_missing` with the fix when a `claude_code` rung's auth has no credential
  — a presence check that never reads a secret — and the Runs dialog shows it.
- **A missing runner tool is caught before the builder is paid** (P-004): an attempt whose
  test command cannot start (`jest` missing) is refused with `runner tool missing: <tool>`
  before any builder call.
- Two bugs this wave made in its own work are registered with their artefacts (P-011, a
  namespace package's `__file__`; P-012, header lines over 100 columns — a ratchet).

### 2026-09-23 — what the product writes on somebody else's ticket is counted, absolute and bounded

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

### 2026-09-22 — the work arrives from the board, and the gates that watch the gates

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
  [EVIDENCE-AND-CLAIMS §1](docs/EVIDENCE-AND-CLAIMS.md#1-claim-tags) — it was already in use
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

### 2026-09-21 — shippable: every element explains itself; users can recover; the loop closes on a merge

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

### 2026-09-21 — reference sandbox images, built and proven by CI (F42 part 1)

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

### 2026-09-21 — the two-person rule is enforced at write; every sign-off says who signed (F7b, F34)

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

### 2026-09-21 — the operating envelope: what the platform team is told is true (F36–F41, F44, F47, F25)

- **`/health` gains a `migrations` probe** — the contract is stated once, in
  [API.md — The `migrations` probe](docs/API.md#the-migrations-probe): `ok` at head; `degraded` (still served) for an unstamped `create_all` schema that matches the head, until `crb migrate` stamps it; `down` (the endpoint answers 503) when the store is behind, ahead, empty or an older unversioned schema (crb tables, no `alembic_version`, fingerprints of a revision behind the head) — revisions named where applicable, with the fix — or when it cannot be read — the fixed detail `migrations could not be read — see the API log, request id <id>`, `data: {}`, the exception in the API log under that id. The go-live checklist now
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

### 2026-09-21 — a locked-out administrator has a way back in (F23)

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

### 2026-09-19 — B-1b: the first real factory pull requests

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

### 2026-09-19 — what the first factory run taught the loop

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

### 2026-09-19 — journeys that explain themselves: contextual help, honest in-flight states, telemetry a platform team can use

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

### 2026-09-18 — link a repository you already measured to the GitHub App

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

### 2026-09-17 — the factory is the point (DL-044): route before the spend, a backlog as a person writes it, the journey re-centred

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

### 2026-09-17 — the NHS design system and the prototype's screens, on real data (DL-042)

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

### 2026-09-17 — the GitHub App is the connection (ADR-0014, DL-041)

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

### 2026-09-17 — the front end has a purpose: connect → results → decisions → factory (DL-040)

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

## [2.0.0a1] — 2026-09-16 — first releasable v2, tagged on `main`

Tagged `v2.0.0a1` on `main` on 2026-09-16 (DL-039) after the day's work below: the merge
from the `reboot/v2` integration branch (PR #2), the third-party review batches, the
repository going public with CI green and branch protection requiring it, the browser
sign-in, the dogfood measurement, the external assessment's two code fixes, and the MCP
server. The release workflow builds the wheel and the container image, smokes both, writes
an SPDX SBOM and signs the image keyless (Sigstore); `docs/DEPLOYMENT.md` §2.2 says how to
verify. Everything before this tag is 2.0.0a1 — nothing was tagged earlier because the
tag's purpose is the signed image and CI was unavailable until the afternoon (DL-035).

### 2026-09-16 (night) — the MCP server: drive a deployment from Claude Code

- **`crb mcp`** — the API as Model Context Protocol tools on stdio (`claude mcp add crb --
  crb mcp`; [MCP](docs/MCP.md)). Thirty-eight tools, each a one-line pass-through to
  `/api/v1` that returns the API's JSON unchanged: repositories, tasks, runs, ledger rows
  and evidence packs, the capability map and routes (with `policy_thresholds`), the oracle
  and controls, the learning-loop plans, ledger verify, sign-offs and reviews (read), the
  factory. The tools act as a local service account under the deployment's RBAC; a
  refusal comes back as `{"error": true, status, code, message, detail}`. Creating a
  sign-off or a review is deliberately **not** a tool (a human attestation; EVIDENCE §2).
  The server's instructions carry the claims policy. New layer `crb.mcp` (a client of the
  server over HTTP, never an importer of it — import-linter enforces the direction); extra
  `[mcp]`; `docs/MCP.md`; ADR-0008 layer table.
- `GET /routes` decisions now serve `policy_thresholds` (the field was added to
  `RouteDecision` in #28 and dropped by the response schema — found by the MCP tests).

### 2026-09-16 (evening) — the external assessment: the map gates the factory; a policy names its bar

An external reviewer's forty-point assessment of the explainer was checked point by point
against the source (docs/reviews/2026-09-16-external-assessment.md; DL-038). Most of it the
repository already answered; two gaps were real and are closed here:

- **The capability map now gates factory delivery** (ADR-0003 amendment 2026-09-16). With
  `deliver` on, a clean build gets a branch and pull request only when its (class × size)
  cell routes `deliver` on the repository's signed map — sighted rows, current apparatus,
  the latest controls verdict, sign-offs overlaid, the same map `GET /capability-map`
  serves. Any other route, or a cell nobody has measured, withholds delivery: the build is
  still graded and reviewed, and the withholding is a `delivery.refused` event carrying the
  measured route, its reason code and the policy version. An **approver** may override for
  one run (`deliver_override: true` on `POST /runs`; 403 below approver); the override is a
  `route.decided` event naming who and what it overrode. Before this the route was rendered
  in the PR body and never consulted.
- **A routing policy names its bar.** `RoutingPolicy` refuses to be looser than the published
  rule under `routing.v1` (`crb route --policy-json '{"min_n": 3}'` needs a `"version"`);
  tightening keeps the name. Every `RouteDecision` carries `policy_thresholds` beside
  `policy_version` — the symmetry the sign-off policy already had.
- `POST /runs` accepts `deliver`, `deliver_override` and `max_rework` for factory runs (they
  were documented and rejected by the schema).
- Documents: README "Not a licence to deploy"; EVIDENCE-AND-CLAIMS §6b (domain of validity),
  §6c (the evidence ladder — hash-chained means unaltered, never verified), the
  conditioning list in §3, the throughput-headline and mutation-strength bars in §7; the
  README's blind number carries its budget; ARCHITECTURE's stale apparatus numbers.
- The dogfood measurement (docs/reviews/2026-09-16-dogfood.md, DL-036) and the review's
  ranked backlog (sealed-posture campaign, sign-off anchored to a review, review defects as
  a routing clause, environment in the stamp, time-based staleness, context arms, an
  independent-oracle arm, generative controls, complexity facets) are recorded for the
  operator.

### 2026-09-16 — sign in with a Claude account from the browser; the repository is public; CI runs again

- **Settings → Sign in with your Claude account.** An admin no longer needs a terminal
  to register the Claude Code login: the API host runs `claude setup-token` in a
  pseudo-terminal behind a **login session** (`POST /settings/secrets/claude-code-token/login`
  → the Anthropic sign-in URL, opened in a new tab; `POST …/login/{id}/code` with the code
  Anthropic shows; `GET …/login/{id}` polled to `done`). The minted token goes straight into
  the owner-only secrets store on the API host — never through the browser, never in a
  response, event, log or the session directory. A detached helper
  (`crb.server.claude_login_driver`) owns the PTY, so several API workers and an API
  restart see one session; one session per deployment; ten-minute expiry; admin only.
  `CRB_BUILDER__CLAUDE_BINARY` names the CLI on the API host when it is not on PATH (the
  verify probe honours it too). Tested against a fake CLI that replays the real
  transcript (observed on Claude Code 2.1.132).
- **Public repository.** Made public on 2026-09-16 (Apache-2.0 already; the full history
  scanned — only test fixtures match credential shapes). GitHub Actions runs again on the
  free tier: the first run on `main` was 10 of 12 jobs green; the two red ones were the
  gate's own configuration, fixed here — the gitleaks scanner pinned to `8.30.1` (the
  action's default `8.24.3` predates the top-level `[[allowlists]]` form and reported the
  test tree's deliberately fake credentials), and two walkthrough expectations moved by
  batch 4 (the cell's accessible label now carries its interval and provenance; the
  controls gate renders the API's verdict — `thin` keeps it closed, as routing withholds
  deliver).
- Dependabot's GitHub Actions bumps arrive as one grouped PR; the first one (checkout,
  upload/download-artifact, setup-python, setup-uv, docker actions, gitleaks-action v3)
  merged green.
- **Branch protection on `main`**: the eleven CI jobs are required and the branch must be
  up to date; no force-push, no deletion (DL-037).

### 2026-09-16 — the release-to-main documentation pass

- `main` is the trunk: README status, CONTRIBUTING (branch model, the local gate list when
  CI has no minutes), ADR-0013, REPRODUCING-THE-CENSUS, `.coderabbit.yaml` base branches.
- The live measurement state after the staged spend is in the README's *measured state*
  and the NHS report §9–§11 (Stage B $3.68, Stage C $8.42, the koa/cobra/click top-up
  $7.48, click's controls re-run on the merged instrument); DL-034.
- `docs/DEPLOYMENT.md` gained *If revision 0004 refuses* — the recorded remedy for a
  database that already holds a duplicated `(trace_id, seq)` pair (the dev stack needed it).

### 2026-09-16 — CodeRabbit batch 4 (the front end and the documents; PR #6's findings)

The `ui/**` instruction is "every number rendered carries its n, its interval and its
apparatus; a route or verdict is read from the API, never decided in the UI; unmeasured is
never a fabricated zero". The `docs/**` instruction is the claim schema. What changed:

- **The API serves what a rendered rate needs.** `/routes` decisions carry `ci_high`,
  `belt_sets`, `model_ci_low` / `model_ci_high`; `/failure-split`, the capability cells and
  the sign-off evidence serve `model_point` and both bounds as **`null`** when `model_n ==
  0` (never `0.0` / `[0, 1]`); `/learn/refusals` serves `share {rows_total, rows_protocol,
  share, ci_low, ci_high}` and `by_apparatus[]` beside `protocol_share`.
- **Routing page**: the interval bar draws the server's asymmetric Wilson interval (the
  upper bound used to be mirrored from the lower one); every bar's accessible label carries
  apparatus + belt set.
- **Capability page**: the selected cell is a key resolved against the current response
  (a repo / projection / filter change no longer keeps a stale detail with the new repo's
  ledger link); a projected dimension with no filter renders every cell behind a class×size
  slot, stacked and labelled (a `Map` used to keep an arbitrary one); the cell label and the
  bar carry `95% CI … apparatus 2.2 · belts v5`; the model rate shows its interval; the
  coverage tile says why it has no interval (a coverage of the change profile, not a sampled
  rate); the controls pill and tile take the policy's `min_controls_share` instead of a
  literal `50%`.
- **Sign-off page**: the deliver bars come from the capability map's policy (`min_point`,
  `min_ci_low`), never `0.9` / `0.8` in the UI; the controls explanation takes the sign-off
  policy's share.
- **Oracle page**: the gate renders the API's `verdict` (the reduction `/capability-map` and
  `/routes` gate on) as its first criterion; the counts are supporting detail. Task strength
  shows its Wilson interval from the served kill / mutant counts.
- **Learn page**: the instrument-caused share is shown per apparatus version with its
  interval; a blended number is never the headline.
- **Repo detail**: the profile histogram states it is a census (an absent cell is a measured
  0 of N examined commits, with that reading in the cell's title — not `NOT_YET_MEASURED`,
  which is the capability map's word for a cell nobody has measured); gold-clean carries
  a Wilson interval. The config form's change baseline is the STORED config, so a repo
  registered without a runner can be saved over (the normalised baseline hid the
  substitution and Save stayed disabled).
- **Task detail**: a review opens the pack the review recorded, not the grade row's.
- **Runs**: `fetchRetainedPatch` goes through the shared `fetchBounded` + `errorFromResponse`
  (timeout → `ApiError('timeout')`, a half-shaped body → `invalid_response`).
- **Repo picker** walks every `/repos` page (`useAllRepos`); the first page no longer
  hides a repository.
- **Factory page** matches the shipped contract: `/tasks` is a bare list, a 404 is "no
  backlog registered — POST /factory/{repo}/backlog", the types mirror `FactoryTaskOut`,
  and the screen has a test (`FactoryPage.test.tsx`); the "phase P6 not enabled" state is
  gone.
- **Documents**: `POST /runs` and the `runs.kind` column list `label` and `factory`; the
  OIDC callback example is the real `/api/v1/auth/oidc/callback`; SECURITY lists every
  flow that crosses the tenant boundary (model endpoint, git remote, OIDC issuer — what is
  sent, what never is) and adopts the repository's three claim tags; ADR-0002 no longer
  claims a filtered export verifies standalone (it says what does); the census document
  splits the two `deliver` cells by mode × belt set (sighted v4 ≈ 89 %, blind ≈ 85 %, legacy
  sighted ≈ 97 % — the blended 94.4 % is not a rate to quote) and its claim example follows;
  ADR-0011's 4-of-10 `tsc` reading is split sighted 3/9, blind 1/1 with n, method and
  apparatus; the measured claims in ADR-0001/0003/0004/0006/0009/0010 carry n, method and
  apparatus, and ADR-0002/0005/0008's inspections are tagged as inspections.

Declined from this slice: intervals on counts, costs and durations (the Runs page's
progress, cost, event and duration figures are exact counts and sums, not sampled rates —
a Wilson interval on them would be fabricated context); the `pyproject` matrix / entry-point
/ coverage findings (review artefacts of a slice without `src/`).

### 2026-09-16 — CodeRabbit batch 3 (the test suite; PR #5's findings)

The tests are the evidence that the instrument is honest, so a test that cannot fail is a
finding. Every assertion below was loosened by an `or`, a membership set, a guard or a
sample, and now pins the exact contract:

- `grade.error` events carry the REDACTED error (the raw `on_event` seam no longer sees a
  token); the test pins the redacted form instead of `token in … or "RuntimeError" in …`.
- Exact pins: the quoted-git-verb refusal label; the factory's RED baseline; the clean
  scratch directory (present AND empty); the `weak` band below the adequacy floor; the
  controls-file usage error (`2`, never the verdict's `1`); the label run's `succeeded` +
  `intent`; the capability map's blind separation (a blind row is seeded and `n_all ==
  n_default + 1`); every clean row's evidence pack (not a sample of five); the events
  read clamp (5,004 rows, the cap wins); the secrets file checked before the admin writes
  it; the username as well as the token absent from a clone error; JS runner-hook poison
  pinned as belt-1b `disqualified` (a `clean` row is now a failure, not an alternative).
- Docstrings say what the body proves: the cargo / maven suites pin FIXED defects (the
  "strict xfail" sentences and dead `_DEFECT` constants are gone); three `env` fixtures
  name the role they log in as; the builders fixture's baseline is the RED target, not
  empty; the belt-5 regression case names the executable cases it defers to.
- Precondition instead of guard: the CLI chain-break check asserts `> 1` rows and always
  runs; the server drift guard imports `fastapi` hard (the test jobs install the server
  extra); the migration files test pins the head to an existing revision file.
- **Warm-ups fail in CI.** `CRB_TEST_STRICT_WARMUP=1` (set on the `test` job) turns a
  failed npm install, Maven resolution or docker build into a test FAILURE — a broken pin,
  fixture or Dockerfile is a repository defect; offline they stay skips with the reason
  (a missing tool or daemon is always a skip).
- The release tag rule is one script, `scripts/check_release_tag.py`, run by `release.yml`
  and pinned by the tests (accept `v<version>` only; refuse a suffix, a missing or
  upper-case `v`, a branch is a no-op); the workflow's `on.push.tags` is asserted `["v*"]`.
- `tests/fixtures/remote.py` runs git through the hermetic helper (fixed identity, no
  user config, 120 s timeout); the openai-agent tool-call ids are a stable digest, not
  `hash()`; the real-LLM labeller test carries `@pytest.mark.live`.
- The census case in `tests/test_capability.py` goes through the shipped
  `crb.core.legacy.import_census` over the vendored `data/census-2026-07-08` (it used a
  private re-implementation over `~/.expansion-bench` and skipped everywhere but one
  machine).
- New `tests/test_core_is_stdlib_only.py`: the POSITIVE form of ADR-0008 — every import
  under `src/crb/core` must be in `sys.stdlib_module_names` or `crb.core`; import-linter's
  `forbidden` contract only rejects what it lists.

Declined from this slice (review artefacts of a slice without `src/`): the `conftest`
importability, `.coderabbit.yaml` paths, the console entry point and the CI matrix.

### 2026-09-16 — CodeRabbit batch 2 (server / store / factory / deploy; PR #4's findings)

Third-party review of the server, store, factory and deployment slices (ADR-0013: advisory,
never an input to a verdict). Every item below is a finding CodeRabbit raised on the review
slice and that was confirmed against the code; each fix carries its test.

- **Cross-process JSONL locks.** `JsonlLedger`, `JsonlFactoryStore` and
  `JsonlGapSignoffLedger` now hold an OS `flock` on `<file>.lock` across read-head + append
  (`crb.core.ledger.jsonl_append_lock`); the API and the worker append to the same factory
  evidence file, and a thread lock cannot order two processes. The tail reader that grows to
  a line boundary is shared (`jsonl_last_line`) — a record longer than 64 KiB no longer
  breaks the next append.
- **Delivery refuses clear-text remotes.** `GitCredentials` rejects any remote that is not
  `https://`, `ssh://` or `git@host:path` at construction, so a push token can never travel
  over `http://` / `git://`.
- **OIDC and CORS fail at start-up, not at login.** `oidc.issuer` must be `https://`; the
  discovery document's `authorization_endpoint`, `token_endpoint` and `jwks_uri` must be
  too (502 `oidc_discovery_failed` otherwise). `cors_origins` refuses `*` / `null` / a
  non-http(s) value: the middleware always allows credentials, so a wildcard would let any
  site drive the session cookie (and Starlette silently refuses to echo it anyway).
- **Last-admin guard is serialised.** `PUT /admin/users/{id}/role` counts and updates under
  the users write lock (`BEGIN IMMEDIATE` / advisory 7336): two concurrent demotions of the
  last two admins can no longer leave none.
- **`GET /repos/{name}/profile?refresh=true` needs operator** — a viewer can read the cached
  histogram but not force the git walk and config write.
- **Factory runs pin their backlog.** `POST /runs {kind: factory}` stamps the ACTIVE
  backlog's hash into `params.backlog_hash` at enqueue (409 `no_frozen_backlog` when there
  is none; `backlog_hash` in the request must match — 409 `backlog_hash_mismatch`) and the
  worker re-verifies it on claim (the run fails closed if the backlog was re-registered in
  between). `register_backlog` writes the history file and the freeze EVENT before moving
  the active pointer (atomic rename), so a failed append never leaves an active backlog the
  chain does not cover. The evidence route verifies the chain it already read (one file
  read, not two).
- **`(trace_id, seq)` is UNIQUE on `events`** (revision `0004`) — `seq` is the SSE resume
  cursor and a duplicate silently lost an event on `?after=`. `DbEventSink` re-allocates
  under the write lock on a collision instead of dropping (`realloc` counter). The upgrade
  REFUSES a database that already holds a duplicate pair (rows are append-only; the
  operator exports and decides). `crb.store.migrate.REVISION_INDEXES` lets an `init_db`
  database adopt at an index-only revision.
- **Paging in SQL.** `GET /reviews` counts and slices in the query; `GET /signoffs` filters
  and slices on the chain before serialising (the live false-Q1 query runs for the page,
  not the table); the ledger import dedupes `row_id` / pack hashes in chunks of 500.
- **Store hygiene.** `make_engine` parses the SQLite URL with `make_url` (driver forms and
  `?mode=` queries no longer leave the driver name in the path); the migration template's
  `downgrade` raises until written, and its rules name every append-only table and the
  adoption markers.
- **Helm refuses two silent misconfigurations.** `postgresql.mode=external` with empty
  `networkPolicy.postgres.cidrs` (every pod would be denied its database under default
  deny); `worker.replicaCount > 1` on a `ReadWriteOnce` work volume. `extraEgress` applies
  to every crb pod (api, worker, migrate, embedded postgres) as its comment always said.
  `CRB_FORWARDED_ALLOW_IPS` defaults to empty (believe nobody), never `*`.
- **Release hygiene.** `release.yml` smokes the PUSHED digest (uid, read-only root, migrate,
  imports) after the push — what a user pulls is what was tested; every `actions/checkout`
  in both workflows sets `persist-credentials: false`; `hatchling>=1.27` (PEP 639
  `license-files` array) and the deprecated licence classifier is dropped.
- README: the P5 row says 14 routed screens (`ui/src/App.tsx`), the file-header programme
  is marked complete; `scripts/code_map.py` describes the real `EXEMPT` rule (explicit
  paths only — no size-based exemption).
- `crb.core.services.authored_of` normalises git ≥ 2.5x's `Z` suffix like
  `Repo.author_date` (the one CI failure on PR #7).

### 2026-09-15 — the rc pin and what it carried

### 2026-09-15 — the NHS measurement's instrument findings (DL-020..025)
- **CI green.** Red on every push since 2026-09-13: labeller tests needed a real `claude` on
  PATH; git 2.5x renders a UTC `%aI` as `Z` (`GitRepo.author_date` normalises to `+00:00`);
  `grades.trial` is `VARCHAR(16)`, which PostgreSQL enforces and SQLite does not
  (`GradeRow` now refuses a longer label on every dialect; the store suite verified on
  postgres:16); a non-existent `hadolint@v3` pin; artifact uploads made non-fatal.
- **JavaScript dependency eras** (ADR-0011 amendment c): a task commit whose lockfile differs
  from HEAD's gets its own `node_modules`, installed once per lockfile hash; a failed install
  is a harness row; installs refuse below 2 GiB free, at most 8 eras per repo (LRU).
- **Support files under the test layout** (`tests/helpers.py`, `tests/mock_server.py`) are
  overlaid, never targets; a candidate with only support files is skipped. `kind: mine` +
  `task_ids` re-qualifies known commits under their stored pool.
- **One oracle measurement**: the capability map routes every cell under the repo's
  task-level mutation scores — the same number the sign-off evidences — so the two can never
  disagree (`oracle_strength_mean` is the strength the cell was routed under).
- **The builder gets the grader's services** (DL-024): a sighted build brings the task's era
  services up first and exports their environment in the test command.
- **`outage` failure kind**: a provider refusal (usage limit / 429 / dead credential) is
  outside `n`, never `harness`; label runs with only outage labels fail instead of succeeding.
- Error strings are capped head-first so a long docker refusal keeps its
  `protocol violation:` kind; one candidate's harness error skips it in a mine run (three in a
  row stop the run); a non-build run's own counters are served as `counts.detail`.
- Capability map: `mode` (default sighted) and `apparatus` (default current) filters; the
  sign-off measures sighted rows of the current apparatus only.
- **Licence**: BSL 1.1 adopted (DL-015/DL-025); `LICENSE` is a reservation of rights until
  the text lands; the image label is `NOASSERTION`; `docs/LICENSING.md`.

### 2026-09-15 (later) — forward mode wired, the builder's own gate, honest counts
- **Factory P6 wired** (`45c2f99`): the forward-mode loop is a run kind (`kind: factory`)
  over a frozen, hashed backlog registered through `POST /factory/{repo}/backlog`; task
  view, structural-gap sign-offs (value slots refused) and the hash-chained evidence chain
  are served; delivery opt-in and fail-closed. Not yet: a model-backed test author.
- **Belt-5 pre-flight** (`36f7949`, `44bd380`): `POST /runs.preflight` applies the
  repository's own fixers after an honest build and, if still rejected, gives the builder
  ONE bounded repair call with the findings; recorded as the builder `<name>+preflight`
  (a distinct arm) with `labels.preflight`. Stage A offline: fixers alone flip 2 of the 4
  NHS lint misses.
- **Provider circuit breaker** (`12bec2a`): a build run stops after `outage_stop` (3)
  consecutive refused attempts instead of writing a refused row per remaining attempt.
- **`n_tasks`** (`adc42b1`): distinct tasks behind `n` on every cell, the sign-off preview
  and the map ("16 rows on 4 commits is a statement about 4 commits").
- **Re-measurement plan** (`cf851ef`): one entry per (cell, mode); blind rows priced at the
  ladder's rungs; relabelled tasks left out and named; task counts shown.
- **Mutant wall clock** (`196fdb6`): a mutant's run is capped at 4× the green baseline —
  an infinite-loop mutant no longer holds an oracle run for the full 900 s.
- **Licence: Apache-2.0** (`8d8bceb`, DL-028) — LICENSE, NOTICE, SPDX, image label.
- **File headers + code map**: every source file carries a `Navigation` block
  (docs/FILE-HEADER-STANDARD.md); `scripts/code_map.py` generates docs/CODE-MAP.md and
  gates it in CI; README rewritten as the front door; docs/ONBOARDING-A-REPO.md for a
  delivery team; two defects the header pass found are fixed (`74ee888`).
- CI green on `reboot/v2` for the first time since the reboot (`d03f8eb`, `fd25f2d`).

### Evidence caveat for this release
Every ledger row to date was measured on the **host executor posture** (`executor: local`)
— including the rows graded after the independent review's finding 1 (the builder
controlled the grader's git view) was closed in code. The sealed-container posture
(ADR-0012) is built and tested; no measurement has yet been taken on it. Numbers in this
release license statements about the instrument, not demonstrations (EVIDENCE-AND-CLAIMS §7).

### Independent AI review pass (2026-09-14) — findings 1, 2, 4, 5, 6, 7, 8 closed
Every finding of `docs/reviews/signoffs/2026-09-14-fable-ai-pass.md` was reproduced with its
recorded command before it was fixed, and each reproduction is now a regression test. Finding 3
(`oracle_unmeasured`) is the sign-off policy v2 entry below.
- **The grader's view is independent of the builder's git (finding 1, blocks demo).**
  `Workspace.touched_files` enumerates from the filesystem against the parent tree
  (`ls-tree -r <parent>` object ids vs a fresh blob hash of every file); the index, `HEAD`,
  `info/exclude` and `core.excludesFile` are never consulted, and the only ignore rules
  honoured for an untracked path are patterns present in a `.gitignore` tracked at the
  parent. `Workspace.enforce_integrity` is the grader's pre-flight: `HEAD == parent`, the
  gitdir is the harness clone's, no skip-worktree / assume-unchanged bits, and the shared
  `info/exclude` (the *main clone's*, for a linked worktree) holds only what the harness
  recorded at create time — foreign lines are removed and reported. `grade()` disqualifies
  on any violation (`dq_reason: worktree integrity: …`, event `grade.tamper kind=worktree`)
  on the CLI and `run_task` paths alike; `diff_stats` diffs against the parent by sha. The
  three reproductions (`info/exclude`, a commit inside the worktree, `--skip-worktree`)
  each graded `clean` on `842875b` and DQ now; a forged index entry, a self-hiding
  `.gitignore` and symlink type changes are covered too.
- **Lint configuration is test infrastructure (finding 2; ADR-0011 amendment).**
  `ruff.toml`/`.ruff.toml`/`.flake8`/`.pre-commit-config.yaml`, `.eslintrc*`/
  `eslint.config.*`/`.eslintignore`/`.prettierrc*`/`prettier.config.*`/`.prettierignore`/
  `.editorconfig` (JS only — prettier reads it), `.golangci.*`, `rustfmt.toml`/`clippy.toml`
  (+ dotted forms), `*checkstyle*.xml`; section-aware `pyproject.toml [tool.ruff*]`,
  `setup.cfg`/`tox.ini` `[flake8]`, `package.json` `eslintConfig`/`prettier`/`scripts.lint`,
  `Cargo.toml [lints]`. Touching any disqualifies under belt 1b before a test runs
  (`[tool.ruff.lint] select = []` and a nested `pkg/ruff.toml` had turned a
  `repo_lint_clean=False` row `CLEAN`).
- **`belt_set` must agree with the apparatus (finding 4).** `GradeRow` refuses
  (`LedgerIntegrityError`, at construction — so at write and on read) any belt set its
  `apparatus_version` could not have recorded: `v3-legacy` (and a `1.0-census` `v4`) only for
  `imported:` census rows, `2.0`–`2.1` ⇒ `v4`, `2.2+` ⇒ `v5`; a `v3-legacy` row records no
  `source_changed`. `expected_belt_sets` is the one rule.
- **A review is anchored to the reviewed row's pack (finding 5).** `DbReviewLedger.append`
  resolves the row by `grade_row_hash` (`row_not_found` otherwise) and the pack by the
  row's hash, never the record's field (`pack_hash_mismatch`); a caller's pack is only
  accepted as a self-certifying copy of the row's. `JsonlReviewLedger.append` requires the
  pack for a verdict (`pack_required`). `check_review_anchor` is the one rule both apply.
- **Guard (findings 6/7).** Redirection targets (`>` `>>` `<` …), `dd of=` and
  tee/cp/mv/install/ln targets that resolve into `.git` — through a symlink when the cwd is
  known — are refused; `TestFileGuard` classifies by what a path resolves to (`gitlink ->
  .git`, `t2 -> tests`); a quoted or escaped paren is text, not a stray sub-shell token
  (`grep '('`, `find … \( … \)`). Corpus: 456 honest / 461 refused lines.
- **Guide (finding 8).** `docs/reviews/human-review-guide.md` re-baselined: twelve files to
  read (adds `core/workspace.py`, `core/test_infra.py`, `core/lint.py`,
  `builders/container.py`, `core/review.py`, `core/signoff.py`), ten triggers, exercises 3b
  and 4 now DQ, new exercises 4b/4c/6b/6c, exercise 5's four bypasses refused and the live
  gaps named; the sign-off template's tables grow to match.

### Sign-off policy v2 — an unmeasured oracle is a refusal (`signoff-policy.v2`)
- **`oracle_unmeasured`** (`crb.core.signoff`): a cell none of whose tasks carries a
  task-level mutation score cannot be signed off — "≥ `min_oracle_strength` when
  measured" became "measured AND ≥". Non-overridable like `false_q1` and
  `attestation_missing`: there is no `CRB_SIGNOFF__*` knob (`REQUIRE_ORACLE_MEASURED`
  may only be `true`; anything else is **503 signoff_policy_invalid**), because signing an
  unmeasured oracle is exactly the "a green suite proves correctness" claim
  EVIDENCE-AND-CLAIMS §7 forbids. Decided 2026-09-14 by the independent decider
  (`signoff-policy: adjust`, DL-016) from the NHS reading: oracle 0.36 with 2 of 6 tasks
  scoreable, 4 of 10 clean rows failing their own repo's `tsc`.
- The server measures the cell's oracle from the repo's `oracle.score` events (the latest
  per task, the same reduction `/oracle/{repo}` serves, averaged over the cell's scored
  tasks — `cell_oracle_strength`); the preview and the 409 detail carry
  `evidence.oracle: {strength, scored, tasks}`; the refusal lists `observed: null` (never
  0). The measurement feeds the two oracle clauses and the stamped
  `oracle_strength_at_signoff`, never the route (the route stays the capability map's).
- `policy_version` → `signoff-policy.v2`; `policy_thresholds` gains
  `require_oracle_measured: true`. Records signed under v1 keep their stamp and verify.
- UI: the Sign-off gate row reads "Oracle strength measured and ≥ 0.80"; the tile says
  how many of the cell's tasks are scored; the clause renders as non-overridable.
- Walkthrough 08 seeds the signable cell with an `oracle` run as well.

### Belt 5 runs `tsc` where the repository's CI does (ADR-0011 amendment)
- `crb.core.lint.tsc_evidence` / `js_plan`: a JavaScript / TypeScript repository whose
  `package.json` `scripts["lint:types"]` (or another script, or its CI) runs `tsc` and
  that carries `tsconfig.json` + `node_modules/.bin/tsc` gets a `tsc` step appended to
  its belt-5 plan — the script verbatim + `--pretty false` (nhsuk-frontend and
  nhsuk-react-components: `tsc --build tsconfig.json --pretty`). `[measured 2026-09-14]`
  4 of 10 clean NHS rows failed the repositories' own type check; belt 5 never ran it.
- Whole-project, attributed per file: `LintTool.findings_re` (`TSC_FINDINGS_RE`) makes
  the rejection count only findings in CHANGED files (`LintStep.findings_changed` /
  `findings_other`, in the pack); errors only in unchanged files are the maintainers'
  debt — belt `True` with the counts on the run's note; a rejection naming no file is a
  harness error, never a pass. `RepoConfig.lint.findings_re` declares the same for any
  other whole-project tool. `lint_run.detected` records `…+tsc:lint:types`.
- Guard corpus: the 19 refusal groups of the NHS + public measurement pinned with the
  independent decider's verdicts (9 honest / 10 refused, provenance per line); `npx
  standard` on koa is honest — the pre-fill's "not in node_modules/.bin" came from a
  cwd-less check.

Apparatus version **2.2** (2.0 → 2.1 in Wave A, 2.1 → 2.2 in Wave B; the sections below
say what each bump changed about the meaning of a verdict). Everything on `reboot/v2`
since the reboot commit, grouped by wave and area. `pyproject.toml`,
`crb.core.version.__version__` and the chart's `appVersion` are `2.0.0a1`; the release
workflow refuses a `v*` tag that does not match `pyproject.toml`.

### Follow-ups (Wave C17)
- **The gold must pass belt 5 too** (ADR-0011's named residual): `crb.core.mine.gold_check`
  runs the same lint plan `grade()` would on the overlaid gold's source files; a gold the
  repository's own linter rejects (or that times out) is `gold_clean=False` with
  `gold_note="gold fails belt 5 (<detected>): …"` — the maintainers' lint debt is excluded
  from the denominator, never counted against the builder. A linter that cannot run is a
  harness error (never a pass); no linter leaves belt 5 not evaluated. The `mine.gold`
  event carries `lint` (`true`/`false`/`null`).
- **`crb learn strengthen` derives the route's items from the server's exports.** A ledger
  export is the rows alone; the per-task oracle scores are `oracle.score` events and the
  cell's held-ness is the controls verdict. `--oracle` now takes `GET /oracle/{repo}` JSON,
  a run's `events/log` page/JSONL (score actions only), a `to_report()` JSON or a bare
  list; new `--controls` takes `GET /oracle/{repo}/controls` (or a `controls` run body).
  With both, the CLI's items and ids equal the route's; `/learn/strengthen` stamps the
  repo on every score so they can.
- **`GET /api/v1/health/live`** — liveness: the process is up and its database answers
  (one probe; never the sandbox). `/health` stays the deep probe and is role-aware:
  `CRB_ROLE=api` (`api` | `worker` | `all`, default `all`) reports the sandbox `skipped`
  instead of failing the API for a docker socket it is not meant to have. The image
  `HEALTHCHECK` and the Helm startup/liveness probes hit `/health/live`; readiness stays
  on `/health`; the chart sets `CRB_ROLE` per container.
- **CI**: the `types` and `test` jobs install `.[server,postgres,dev]` (mypy under `.[dev]`
  alone reported 95 `import-not-found`, 277 errors with the cascades).
- **Version** `2.0.0a0 → 2.0.0a1` in `pyproject.toml`, `crb.core.version.__version__`
  (`APPARATUS_VERSION` stays `2.2`) and `deploy/helm/crb/Chart.yaml` `appVersion`.

### Sign-off is a policy decision, refused at write (`signoff-policy.v1`, Wave B7, DL-014)
- `crb.core.signoff.SignoffPolicy` (defaults: `n_min = 10`, route must be `deliver`, controls
  gate passed with `max_controls_escapes = 0` and `min_constructible_share = 0.5`,
  `min_oracle_strength = 0.80` when measured, attestation mandatory) and
  `evaluate_signoff` / `check_signable`: refusal codes `false_q1` (first, non-overridable),
  `thin_cell`, `controls_unmeasured|failed|escapes|thin`, `oracle_weak`,
  `route_not_deliver:<reason_code>`, `attestation_missing` (non-overridable), each naming the
  number that failed and the threshold it missed. Operator-adjustable within published bounds
  via `CRB_SIGNOFF__*`; a value outside them makes the sign-off routes answer
  `503 signoff_policy_invalid`.
- `SignoffRecord` schema `crb.signoff.v2`: `ci_low_at_signoff`, `oracle_strength_at_signoff`,
  `policy_version` + `policy_thresholds`, `route_at_signoff` + `route_reason_code`,
  `controls_verdict|run_id|k|total|escapes`, `attestation {reviewed_task_id,
  reviewed_row_hash, statement, at}` — all hashed into the chain; `v1` records still verify
  (schema-aware body) and load with defaults.
- API: `POST /signoffs` takes `attestation {reviewed_row_hash, statement}` (the row must be an
  accepted row of the cell — else 422), routes the cell under the repo's latest controls
  verdict (the same helper as `/capability-map`) and answers `409 signoff_refused` with
  `detail.{code, thresholds, observed, refusals[]}`; `GET /signoffs/preview` (the bar before
  the approver tries, plus the cell's accepted rows), `GET /signoffs/policy`,
  `GET /signoffs/{id}`.
- UI: the Sign-off screen shows n / point / Wilson-low / false-Q1 / oracle strength / the
  controls verdict (k of N, escapes, run, date) / route + reason, every refusal with observed
  vs threshold, an accepted-row picker with the "I have read this accepted diff" affirmation
  and statement; the button stays disabled while the preview refuses. Walkthrough `08-signoff`
  proves the refusal on the live fixture (whose `hardcode_cheat` control really escapes) and a
  real sign-off on an API-seeded repo whose tests are parametrised.

### Apparatus 2.1 → 2.2 — belt 5 `repo_lint_clean` (ADR-0011, Wave B5)
- **Grader**: after belt 4, the repository's OWN formatter/linter runs on the changed
  non-test files (`crb.core.lint`): declared by `RepoConfig.lint` or detected from the
  repo's configuration — `gofmt -l` (Go), `ruff check` (+ `ruff format --check`) (Python),
  `eslint` / `prettier --check` / `standard` (JS), `spotless:check` / `checkstyle:check`
  (Maven), `cargo fmt --check` / `clippy` (Rust). No linter ⇒ belt `None` (not evaluated:
  neither a pass nor a fail). Rejected or timed out ⇒ `False`, never clean. A linter that
  cannot run ⇒ harness error. `GradeResult.lint_run` records the tool, files and redacted
  tail; `grade.belt` events carry `belt="repo_lint_clean"` + `detected`.
- **Ledger**: `GradeRow.repo_lint_clean`; `belt_set="v5"` for new rows; `v4` / `v3-legacy`
  rows never carry belt 5 and hash byte-for-byte as before (ADR-0002 rule 2 amended: the
  body excludes an unrecorded optional belt). New failure kind `lint` (belts 1–4 held,
  belt 5 rejected); `FailureSplit.lint` / `lint_evaluated`; `CellStats.n_lint` /
  `n_lint_evaluated`; `model_n` includes `lint`.
- **Store**: revision `0002` adds `grades.repo_lint_clean` (nullable, in place);
  revision-aware adoption of unversioned `init_db` databases (`REVISION_MARKERS`).
- **API/UI**: `repo_lint_clean` on grade rows and belts, `belt_set` on run task rows,
  `lint` / `lint_evaluated` on every split; five belt pills under `v5`, four otherwise;
  "Lint run (belt 5)" in the evidence drawer.

### Wave A and the reboot → first-releasable work (2026-09-13)

Apparatus version **2.0** at the time these entries were written (Wave A bumped it to
2.1 — belt 1 covers test infrastructure, routing gated on the controls verdict,
intent-resolved change class, polyglot controls.v2; see `crb.core.version`). 76 commits,
grouped by area.

### Release engineering
- `release.yml` now publishes the container image on a `v*` tag: build `deploy/Dockerfile`
  (UI + package), smoke it (uid 10001, read-only root, `migrate upgrade`, UI present), syft
  SPDX SBOM, then push `ghcr.io/jita81/commit-replay-bench:<version>` and `:sha-<short>`
  with SLSA provenance — only for a tag of the canonical repository. A separate `sign` job
  signs the digest with cosign **keyless** (GitHub OIDC) and attaches the SBOM as an in-toto
  attestation; it is skipped on forks and dry runs. `workflow_dispatch` is a no-push dry run.
- `deploy/verify-image.sh`: operator verification (signature + SBOM attestation + optional
  digest pin) with a `--print` mode; `tests/test_release_verify_image.py` holds the script,
  the workflow and the Helm values to one repository / issuer / signing identity.
- CI `container` job: hadolint; explicit tmpfs ownership in the image smoke (newer daemons
  make `--tmpfs` inherit `root:0750`, which uid 10001 cannot write); asserts the UI is in the
  image. `docs/DEPLOYMENT.md §2.2` and `deploy/README.md §1.1`: image name, tags, how to
  verify, and the compose path with the released image instead of a local build.
- `docs/REPRODUCING-THE-CENSUS.md`: a reviewer's step-by-step to re-derive the census
  ledger invariants (manifest, import, chain, false-Q1 = 0, routing) with real output.

### Core (`crb.core`, stdlib-only)
- Census / legacy import (`crb.core.legacy`): 1,071 verdicts as `GradeRow`s with imported
  evidence packs, `belt_set = v3-legacy` for the 706 three-belt rows; Athena aggregates as
  reference-only `AggregateRow`s (never in the grade ledger).
- Capability map, forecast / readiness, sign-off ledger (409 on false-Q1), federated
  abstract export (cells only, no ids, no code).
- Oracle-adequacy programme (`crb.core.oracle`): mutation strength, adequacy gate, negative
  controls, sealed corpus; text-level mutators for Go / JavaScript / JVM / Rust with
  uncompilable mutants excluded (ADR-0009).
- Runners: environment-setup phase (the one network-permitted step) for venv/pip, npm, go,
  mvn, cargo; jest/vitest `--` path handling and suite-load attribution; snapshot files map
  to their owning test; `|`-separated extension / test-suffix alternatives; `runner_opts.env`
  and `extra_args`. `LocalExecutor` closes stdin (tests waiting on input fail at EOF); cancel
  tokens kill the running process / container.
- Run orchestrator: prep → build (escalation ladder) → grade → evidence pack → ledger, per
  attempt; one `GradeResult → GradeRow` mapping shared by CLI and worker.
- Forward-mode factory core: frozen backlog, DoR gate, RED proof, build under belts,
  never-to-default delivery, verdict-before-edit review, evidence ledger.

### Builders
- Adapter contract, budgets and guards; `editblock`, OpenAI-compatible tool loop (Azure
  OpenAI / Cerebras / local), Claude Code CLI with `api_key` and `cli` auth modes (Sonnet 5
  default; `CLAUDE_CODE_OAUTH_TOKEN` forwarded in `cli` mode); `fixture_gold` test builder.
- Archaeology guard: command substitutions are checked recursively, quoted parentheses are
  not sub-shells (both false positives found on live koa / click runs); the sighted test
  command carries the runner env and the rules state the environment is provisioned.
- Token accounting: `tokens_in` is the whole prompt (cache creation + reads included).

### Server, store, worker
- FastAPI core: settings, auth (local + OIDC), RBAC, CSRF, health / metrics / version, error
  envelope; domain routes (repos, runs + SSE, grades / evidence, capability, routes,
  forecast, sign-offs, ledger verify / export / import, oracle, factory stubs); the built UI
  served at `/` with deep-link fallback.
- SQLAlchemy models with append-only triggers (SQLite and PostgreSQL), `DbLedger` with the
  hash chain, Alembic migrations, store suite on both dialects.
- DB job queue, run executors (probe / setup / mine / replay / blind / oracle / controls),
  DB event sink; a run whose every attempt errored on infrastructure is `failed`, never
  `succeeded`.
- **Per-run raw retention** (`POST /runs` `retain: {worktrees, transcripts}`): the operator
  may keep attempt worktrees and builder transcripts for human re-examination of a clean
  grade; the ADR-0006 default (keep nothing) is unchanged.

### UI and walkthrough
- Vite / React observability front end (Ledger v2 tokens, 14 routed screens, SSE live log,
  evidence drawer, repo / run dialogs with presets and editors); unit tests + axe smoke.
- Full-browser walkthrough against a live temp stack (`scripts/walkthrough.sh`, 25
  Playwright specs; hermetic tier 1 in CI).

### Deployment
- `deploy/Dockerfile` (multi-stage, non-root, read-only-root compatible, docker client
  only), `docker-compose.yml` (hardened single host), Helm chart `deploy/helm/crb` (default
  deny NetworkPolicy, dind / hostSocket sandbox modes, external or embedded PostgreSQL),
  `docs/DEPLOYMENT.md`, `docs/SECURITY.md`, `docs/DATA-RETENTION.md`, Postgres + container
  + walkthrough CI jobs.

### Evidence and reviews
- Vendored census evidence `data/census-2026-07-08/` (1,071 grades, 25 task sets, 24
  configs, sha256 manifest) with the CI gate `tests/test_census_gate.py` (false-Q1 = 0
  re-derived on every PR).
- `docs/reviews/2026-09-13-critical-friend.md`: the critical-friend review of AI output
  quality and process governance — the floor held (false-Q1 = 0 on every live row), 13 of 15
  non-clean live rows were harness-caused, none of three "clean" cobra patches was
  mergeable as-is, the class axis is degenerate on library repos, and `env_poison` escapes
  belt 1 on click. Its §8 actions are the Wave A / B backlog.

### Documentation
- README, `docs/ARCHITECTURE.md` (arc42-lite, C4 mermaid, sequence diagrams, data model),
  `docs/EVIDENCE-AND-CLAIMS.md`, `docs/CONTRIBUTING.md`, `docs/OPERATOR.md`, `docs/API.md`
  (HTTP contract v1), `docs/DECISION-LOG.md`, ADR index and ADR-0001…0009.
- CI: lint, types, layers, test matrix (3.12 / 3.13, coverage ≥ 70%), security (gitleaks +
  pip-audit), SBOM (CycloneDX); Dependabot for pip and GitHub Actions; `.gitleaks.toml`
  with the `tests/` fixture allowlist.
- `crb.observability`: `StepEvent` envelope, sinks, Prometheus metrics with no-op fallback,
  JSON logging with redaction, health probes.

### Changed
- `pyproject.toml` import-linter contract: `include_external_packages = true`; not-yet-existing
  layers are optional (parenthesised) until their packages land; `cli` sits above `server`.

## [2.0.0a0] — 2026-09-13 — reboot

Apparatus version **2.0**.

### Added
- Package `crb` with a **standard-library-only** core (`crb.core`): `spec` (languages, one
  size table, deterministic change classes, `RepoConfig`, `TaskSpec`), `git`, `execution`
  (`LocalExecutor`, fail-closed `DockerExecutor`), `runners` (pytest, go, node, vitest,
  jest, mocha, maven, cargo), `workspace`, `mine` (RED / baseline / gold), `grade` (**four
  belts**, `FalseQ1Violation` at construction), `evidence` (`EvidencePack`,
  `ApparatusStamp`, `BuilderRef`), `ledger` (`GradeRow` with write-time invariants,
  hash-chained `JsonlLedger`, `verify_chain`, `CellKey`, `cell_stats`), `stats` (Wilson),
  `routing` (the one published rule, `routing.v1`), `redact`, `version`.
- `pyproject.toml` (Python ≥ 3.12; ruff, mypy strict, import-linter, pytest-cov configuration;
  optional extras `openai`, `claude`, `server`, `postgres`, `dev`, `all`).

### Changed
- **Breaking (apparatus):** verdicts are four belts + `clean`, not the v1 three-bucket
  `ai_can / needs_human / fails`; `source_changed` is a new belt. Rows graded under the
  three-belt census apparatus are imported as `belt_set = v3-legacy` and reported separately.
- **Breaking:** false-Q1 is enforced at **write** time (previously read time upstream);
  a clean row requires an evidence-pack hash.
- Package renamed `commit_replay_bench` → `crb`; CLI `commit-replay` → `crb`.

### Removed
- The v1 (June 2026) implementation (`src/commit_replay_bench/*`, SEARCH/REPLACE-only
  generator, host-only pytest harness). Its last commit is tagged `v1.0.0-legacy`.

[Unreleased]: https://github.com/Jita81/commit-replay-bench/compare/v2.0.0a1...main
[2.0.0a1]: https://github.com/Jita81/commit-replay-bench/compare/v1.0.0-legacy...2.0.0a1-rc1
[2.0.0a0]: https://github.com/Jita81/commit-replay-bench/compare/v1.0.0-legacy...v2.0.0a0
