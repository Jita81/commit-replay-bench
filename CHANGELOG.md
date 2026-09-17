# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). The **apparatus version**
(`crb.core.version.APPARATUS_VERSION`) is listed separately because a change to it changes
the meaning of a verdict (see [EVIDENCE-AND-CLAIMS §4](docs/EVIDENCE-AND-CLAIMS.md#4-the-apparatus-stamp--evidence-expires)).

## [Unreleased]

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

[Unreleased]: https://github.com/Jita81/commit-replay-bench/compare/2.0.0a1-rc1...reboot/v2
[2.0.0a1]: https://github.com/Jita81/commit-replay-bench/compare/v1.0.0-legacy...2.0.0a1-rc1
[2.0.0a0]: https://github.com/Jita81/commit-replay-bench/compare/v1.0.0-legacy...v2.0.0a0
