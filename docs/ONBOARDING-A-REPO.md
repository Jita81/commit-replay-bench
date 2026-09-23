# Using Commit Replay Bench on a client's repository

**Who this is for.** A delivery team (developers + a governance/assurance reviewer) putting
the bench on one of their client's repositories for the first time. It says, in order, what
you do, what you must change, what you must check, what the product will tell you, and what
you may then claim. Commands and configuration detail live in [OPERATOR.md](OPERATOR.md);
the meaning of every number lives in [EVIDENCE-AND-CLAIMS.md](EVIDENCE-AND-CLAIMS.md); the
code behind each step is one click away in [CODE-MAP.md](CODE-MAP.md).

**Roles you need.** *Operator* (runs the stack, spends the credits), *approver* (signs
cells; must not be the operator who queued the runs), *reader* (governance — reads
evidence, never writes). All three exist as RBAC roles ([SECURITY.md](SECURITY.md)).

**Time and money, honestly.** A first repository takes a working day of a developer's
attention (most of it on step 2) and, with Claude Sonnet, roughly £0.20–£0.60 per attempt;
a first useful picture (≈ 30 attempts) is under £20. Nothing spends money without a queued
run you can see and cancel.

---

## Step 0 — Deploy the stack (operator, once)

[DEPLOYMENT.md](DEPLOYMENT.md): Docker Compose or Helm; PostgreSQL for anything beyond a
laptop; OIDC (Entra ID) or the local admin bootstrap; the builder's credential
(`claude_code` via a Claude Code token entered in Settings → never in a file the repo
knows about). Run `GET /health`: every probe must be `ok` except `sandbox` (which says
`degraded` on a laptop's local executor — production uses Docker, see step 6).

**What you must decide here:** where the ledger lives (it is the audit record — back it
up like one), who the approvers are, and whether builder transcripts are retained
([DATA-RETENTION.md](DATA-RETENTION.md): default zero raw retention).

## Step 1 — Register the repository (developer, 30 minutes)

Repos → *Add a repository* (or `crb repo add`, [OPERATOR §2](OPERATOR.md#2-configure-a-repository)).
You are describing the repository's **shape**, not its code:

| You set | What it means | Get it wrong and… |
|---|---|---|
| `language`, `runner` | pytest / jest / vitest / mocha / node-test / go / maven / gradle / cargo | nothing runs: the probe fails, loudly |
| `src_prefix`, `test_prefix` (or `test_mode: suffix` + `test_suffix`) | which files are code and which are tests | mining finds nothing, or tests are mistaken for source (belt 1 then DQs the task — you will see it) |
| `belt_scope` | how much of the suite the regression belt runs (`AFFECTED_DIRS` is the usual answer) | too narrow: regressions escape; `BARE` on a 40-minute suite: everything times out |
| `probe` | one known-green test scope | the toolchain is never proven |
| `runner_opts` | the repo's quirks: node version, jest projects, pip extras, `services` the tests need, `dist_info_stubs` | see step 2 |
| `lint` (optional) | the formatter/linter command if detection cannot see it | belt 5 is "not evaluated" instead of the repo's own gate |

Presets exist for the common shapes. **Tests the developer runs now:** `crb repo setup` then
`crb repo probe` — green means the toolchain, the dependencies and your layout are right.

## Step 2 — Make the oracle reproducible (developer, the real work)

The bench grades against the repository's **own tests at each historical commit**. Real
repositories drift: dependency pins move, a service the tests need bit-rots, a linter
version changes. Everything the three NHS repositories needed is now configuration
([reviews/2026-09-14-nhs-public-repos.md](reviews/2026-09-14-nhs-public-repos.md) §1 and §8):

- **Dependency eras** — JavaScript task commits whose lockfile differs from HEAD get their
  own `node_modules` automatically; Python pins of `ruff` are honoured per commit. You
  configure nothing; you *watch* the mine run's `gold` notes for "gold target not green".
- **Services the tests need** (a MESH sandbox, a database) — declare them under
  `runner_opts.services` ([OPERATOR §2.2](OPERATOR.md#22-services-the-oracle-needs)) with the
  era variants (certificates, image tags); the grader *and the builder* get the same
  service.
- **Packaging-metadata tests** — `runner_opts.dist_info_stubs`.
- **The linter/formatter** — belt 5 runs the repository's own (`prettier`, `eslint`, `tsc`,
  `ruff`, `gofmt`, `spotless`, `cargo fmt`) at the commit's pinned version. If the
  maintainers' own commits fail it, the task is kept but flagged `gold_clean: false` and
  never counted — that is their lint debt, not the model's.

**The check:** after `crb mine` (or a Mine run), the tasks list shows `gold_clean` per
task and a note for each failure. Aim for most of the mined tasks gold-clean; every
`gold target not green` is a reproducibility gap you either fix in configuration or accept
as "this slice of history is not measurable". Re-qualify tasks after a config change with
`kind: mine` + `task_ids` — you never re-mine from scratch.

## Step 3 — Prove the instrument on this repository (operator, £0)

Two runs before any model attempt:

1. **Oracle** — mutation scoring: how many injected faults the tests catch, per task. A
   repository whose tests catch a third of faults will route `human` however well the
   model does, and that is the right answer.
2. **Controls** — the bench cheats on purpose (does nothing, hard-codes the answer, edits a
   test, poisons the environment) and must catch itself every time. The report says
   `passed` with `0 escapes`, or it does not: if it does not, **stop** — nothing measured
   on this repository is evidence until it passes (the map withholds `deliver` on its own).

Governance reads both on the Oracle screen. They are the negative controls of the
experiment; without them a pass rate is a rumour.

## Step 4 — Measure (operator, the money step)

A sighted replay run: the builder sees the failing test and must make it pass; the grader
never trusts the builder's word. Start with `limit: 10`, `retain: {worktrees, transcripts}`
so a human can read every accepted patch, `preflight: true` so the repository's own
formatter is applied before grading (4 of the 6 NHS misses were formatting), and
`outage_stop` at its default so a usage-limit outage stops the run rather than burning it.

**What to look at on the Run page:** the failure split. `builder_red` is the model's;
`lint` is the maintainers' gate; `budget`, `protocol`, `harness`, `outage` are the
instrument's or the operator's — each is named per row, none is hidden in a rate.

## Step 5 — Read the map (everyone)

Capability → the grid of *change class × size*. A cell shows `n` attempts **and**
`n_tasks` distinct commits (16 attempts on 4 commits is a statement about 4 commits),
the pass rate with its Wilson interval, false-Q1 (must be 0), the oracle strength, the
controls verdict, and the route the ONE published rule gives: `deliver`, `calibrate`,
`human` — with the reason code. The rule is in [adr/0003-one-routing-rule.md](adr/0003-one-routing-rule.md);
you cannot change it per repository, only read it.

## Step 6 — Before anyone signs anything

- Run the measurement on the **sealed posture** (`CRB_BUILDER__EXECUTOR=docker`,
  [adr/0012-builder-in-a-sealed-container.md](adr/0012-builder-in-a-sealed-container.md)):
  a host-executor measurement is a development reading, and the evidence caveat in the
  CHANGELOG says so.
- Have a human read at least one accepted diff per cell with the
  [human-review guide](reviews/human-review-guide.md) — "clean" is a mechanical
  observation, not mergeability.

## Step 7 — Sign off (approver)

Sign-off is a **policy decision refused at write** (signoff-policy v3,
[EVIDENCE-AND-CLAIMS §6a](EVIDENCE-AND-CLAIMS.md)): the cell must have `n ≥ 10`, the rule
must say `deliver`, the controls must have passed with 0 escapes, the oracle must be
measured and ≥ 0.80, the approver must **attest to one accepted row they read**, and the
approver must be a **second person**: the approver is refused when they are the actor of the
attested row (`Grade.actor`), the actor of the run that produced it (`Run.actor`), or the
only person behind the cell's accepted evidence (`same_actor`; the operator who ran steps
4–6 cannot sign their own result, whatever their role). Anything else is a 409 with every
failing clause listed, shown on the Sign-off page before you try. A sign-off is a
hash-chained row that records who signed and what kind of account it was; it is revoked by a
newer row, never deleted.

Step 7 is before step 8 in the code as well as in this guide: by default the factory opens
**no pull request** in a cell nobody has signed off, however well that cell measures
([ADR-0018](adr/0018-a-signed-cell-licenses-delivery.md)). A sign-off expires with the
apparatus, so after an apparatus move delivery waits for a fresh signature.

## Step 8 — Forward mode (when a cell is trusted)

Register a frozen backlog (`POST /factory/{repo}/backlog`): items with structural facts
and, today, an operator-authored test per item. The loop assesses readiness (structural
gaps can be signed by an approver; **value** gaps never), proves the test RED, builds
under the same belts, reviews independently with the verdict recorded before any edit,
and — only when you switch delivery on — opens a branch + PR, never touching the default
branch. Every step is in the evidence chain ([API.md](API.md) "Factory").

**What licenses that pull request** (ADR-0018): the item's (class × size) cell must route
`deliver` **and** carry your approver's sign-off. Either clause failing means the change is
built, graded and reviewed and the delivery is withheld, with the clause on the item's chain
(`unsigned_cell` for the missing signature). The Factory screen says which items would be
delivered before you spend anything. An approver may override the gate for one run; that
override is one person licensing one pull request under their own name — it is not a
sign-off, and the pull request body says so. A deployment that decides the measurement is
its whole licence sets `CRB_FACTORY__REQUIRE_SIGNED_CELL=false`, and the Posture page then
says that is what it is running.

---

## Step 9 — Let the work arrive from your own board (optional)

Steps 1 to 8 assume somebody types the backlog into this product. They do not have to.
A team's own board can be the front door: move a ticket into **one** watched column and
that is the request to manufacture — the ticket *is* the backlog item, and the column is
the consent gate (ADR-0017).

**What you get for nothing.** Before any build is paid for, the ticket gets one comment in
its own thread saying what a good acceptance test still needs answering — each question in
the catalogue's words with the exact line to paste into the acceptance criteria — plus what
this deployment has measured about changes of that kind and size (the route, the number of
graded attempts behind it, the interval, and whether the honesty floor is intact). It is
labelled `crb:needs-info`, `crb:ready`, `crb:not-deliverable` or `crb:queued`. Reading a
column, drafting the item and posting that comment call no model and spend nothing.

**Switching it on takes two steps, and the second one is the consent.** First an admin
configures the tracker, stores its credential and sets this deployment's own address
(`CRB_PUBLIC_URL` — the links the product writes on your tickets are built from it, and a
relative path would resolve against your tracker's host, so the listener cannot be switched on
without it). Then an operator switches the listener on for a repository from the Factory
screen's *Work arriving from your board*, or at `/factory/intake?repo=`. Every repository starts
with its listener **off**. The two steps are two **roles**, not necessarily two people: the role
ladder admits an admin wherever an operator is asked for, so one admin account can take both.
The switch records who threw it and when; nothing here refuses the same person taking both
steps, and the product's two-person rule applies to signing a cell, not to this switch
(`signoff-policy.v3`).
[OPERATOR §11](OPERATOR.md#11-intake--work-arriving-from-a-board) has both.

**One read is bounded.** A column holding more tickets than one pass may read (200 by default)
is not read at all: the pass stops and says to narrow the area path or the JQL, because reading
an arbitrary 200 of your board and saying nothing about the rest would be worse than reading
none of it.

**Two things to know about how it reads a ticket.**

*It says when it does not know.* The class of change is inferred from the title and the
description and comes with a confidence. Below the published threshold the product says it
could not classify the ticket and asks, rather than routing money at a guess. You can settle
it yourself with a tag: `crb:class=bug.fix` (and `crb:kind=`, `crb:level=` likewise).

*An edit is never an overwrite.* `(tracker, key, revision)` is the key: a ticket read again
unchanged is not read again, and nothing is written. A ticket **you** edit comes back as a new
item that **supersedes** the old one, so the frozen record a run verified against never
moves under it. What the product itself writes on the ticket — the label, the comments, the
link — moves a tracker's own revision, and that is not an edit: only a change to the ticket's
content makes a new item.

Story points map to a size tier on a published scale: `≤ 1 → XS`, `≤ 3 → S`, `≤ 8 → M`,
`≤ 20 → L`, above that `XL`. A ticket with no estimate is `S`, and the comment says so.

**What it writes, counted, so nobody has to wonder.** Over a ticket's life the product adds
up to four comments, each marked as its own: what is missing, a note when the work is queued,
a note when a pull request opens, and a note if the work stopped. It sets one `crb:` label.
It attaches a link to the backlog item and a link to the pull request. And — only where your
deployment configured a mapping — it makes one state change after a pull request merges. It
edits no other ticket field. It never creates a ticket. It never reads a column it was not
pointed at. It never puts your source code, your diffs, the ledger or an evidence pack on the
tracker. Those are bounded by the size of the protocol it has (six verbs: read the column,
read a ticket, comment, label, link, transition), not by a rule somebody has to remember
([SECURITY §2](SECURITY.md#2-trust-boundaries)). The comment on your ticket carries the same
list, so this page and your board cannot drift apart.

---

## What a developer changes for a new repository — and what they do not

**Change:** the repository's configuration (step 1), its `runner_opts` (step 2), possibly a
new [runner](../src/crb/core/runners/) if the language is not covered, possibly a lint
detection rule ([`src/crb/core/lint.py`](../src/crb/core/lint.py)) if the repository gates on
a tool the bench does not know.

**Never change for a repository:** the grader ([`src/crb/core/grade.py`](../src/crb/core/grade.py)),
the routing rule, the sign-off policy, the ledger. Those are the instrument; changing them
is an apparatus bump with an ADR, and every row measured before it expires
([EVIDENCE-AND-CLAIMS §4](EVIDENCE-AND-CLAIMS.md)).

## Tests you run, in order

| When | Test | Passes when |
|---|---|---|
| after step 1 | `crb repo probe` | the probe scope is green in the provisioned environment |
| after step 2 | a Mine run | most tasks `gold_clean: true`; every failure has a note you understand |
| step 3 | Oracle + Controls runs | controls `passed`, `escapes: 0`; oracle strengths recorded per task |
| step 4 | a small sighted replay | rows have failure kinds you can explain; `false_q1` stays 0 |
| before sign-off | the same on the sealed posture; a human review | the review is recorded as a review row |
| always | `GET /health`, `crb ledger verify` | every probe `ok`; the chain verifies |

## What you may claim afterwards (and what you may not)

Only what [EVIDENCE-AND-CLAIMS.md](EVIDENCE-AND-CLAIMS.md) §7 permits, with the tag the
product gives it: a cell's rate with its interval, `n` and `n_tasks`, on the apparatus
version it was measured with. Not a repository-wide rate, not "the AI can do X%", not a
blind capability from budget-capped rows, not anything from a repository whose controls
did not pass.
