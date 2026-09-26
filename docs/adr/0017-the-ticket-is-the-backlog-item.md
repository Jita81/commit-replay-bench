# ADR-0017 — The ticket is the backlog item; the column is the consent gate

**Status:** Accepted (operator decision DL-051; built in wave 1, stream I) · **Superseded in part by [ADR-0022](0022-intake-approval-by-default.md)** (2026-09-25: the column is the request, an operator's Register act is the consent)
**Date:** 2026-09-22
**Apparatus impact:** none — nothing here changes what a belt means, how a cell is keyed
or how a route is decided. Intake decides *which* items exist, never how one is graded.

## Context

Until now, work entered the factory only by somebody typing it into this product: the
freeze form on the Factory screen, or `POST /factory/{repo}/backlog`. Every enterprise
that would use the product already keeps that work somewhere else — an Azure DevOps board,
a Jira project — with its own acceptance criteria, its own estimate and its own workflow.
Asking a team to keep a second backlog is asking them to keep two, and the second one
rots. [hypothesis] The gap analysis records this as the journey with no entry point
(`docs/dod/journeys/intake-from-a-ticket.md`, gaps G-900, G-901, G-332…G-337, G-903).

Three constraints shaped the answer.

**Consent.** Reading somebody's board and writing on their tickets is not something a
product may switch on for itself. It has to be a deliberate, attributable act, and it has
to be reversible in one click.

**Money.** The expensive part of this product is manufacturing. Everything the ticket is
missing should be discovered and said *before* a builder is invoked — the readiness gate
already knows what a good test for each class of change needs
(`src/crb/factory/readiness.py`), and the capability map already knows whether changes of
that kind and size can be delivered at all (`src/crb/core/routing.py`). Both can be read
for nothing.

**The frozen record.** The factory's integrity rests on a backlog that is frozen and
hashed, and on the rule that change arrives as a new item superseding an old one
(ADR-0002, `src/crb/factory/backlog.py`). A ticket, by contrast, is edited in place all
day. The two have to be reconciled without weakening the first.

## Decision

**The ticket is the backlog item.** One ticket becomes one `BacklogItem` with the id
`<tracker>-<key>` (`ado-4711`, `jira-abc-123`), registered through exactly the path the
API uses (`FactoryHome.register_backlog` / `register_evolution`). Nothing is typed twice.

**The column is the consent gate.** Moving a ticket into one watched column is the request
to manufacture. Nothing outside that column is read, ever.

**The listener is per repository and default OFF.** The deployment-wide connection
(`crb.server.settings.IntakeSettings` plus the `tracker_token` secret) is an admin's;
switching a listener on is an operator's, is refused when no tracker is configured, and is
stored on the repository row with who threw it and when
(`crb.server.intake.ListenerState`). A repository nobody switched on is never polled —
enforced twice, at the API (`PUT /factory/{repo}/intake`) and in the worker
(`Worker.intake_repos`).

**An edit is an evolution, never an overwrite.** `(tracker, key, revision)` is the
idempotency key and it lives on the factory's own hash-chained evidence, not in memory. A
ticket read again at the same revision writes nothing. A ticket whose *content* has changed
becomes a new item, `<id>.r<revision>`, with `supersedes` set — the frozen record's hash
never moves (`crb.intake.draft.draft_from`). The revision is the pre-filter and never the
test on its own, because the product's own writes move it: an Azure DevOps tag PATCH
increments `System.Rev` and every Jira write moves `fields.updated`, so a ticket nobody had
touched became a new evolution on the next pass. What is compared is a digest of what the
draft is actually made of — title, body, acceptance criteria, type, points, url and the
classifier tags — recorded on the item as `content_revision` and on `intake.read`
(`crb.intake.draft.content_revision`).

**The ticket learns before any spend.** One comment about what is missing, idempotent by its
own marker, carries the readiness gate's open questions with the exact line that closes each
one, and the cell's route with its n, its 95 % interval, its apparatus version and whether the
honesty floor is intact — read from the map *before* any run
(`crb.intake.feedback.render_feedback`). One of four labels goes with it:
`crb:needs-info`, `crb:ready`, `crb:not-deliverable`, `crb:queued`. Three further marked notes
follow the item's life (queued, the pull request, the stop), so what the product writes is
**four comments at most, each marked as its own**, the label, a link to the item and a link to
the pull request, and the one configured state change — and the comment on the ticket says
exactly that list, counted, rather than reassuring the reader that it writes little.

**How the marker is carried depends on the tracker, and both are found the same way.** Azure
DevOps renders comments as HTML, so the marker is an HTML comment a reader never sees. Jira
comments are Atlassian Document Format, which has no hidden node: a marker written as an HTML
comment there is READ OUT as the first line. On Jira the identity is therefore shown rather
than smuggled — one attribution line in plain English carrying the same token
(`crb.intake.client.marker_token`), and the renderer's structure is mapped onto ADF marks
instead of being flattened to characters. Idempotency compares like with like on both: a
comparison across a lossy conversion rewrote the same unchanged comment on every poll.

**Every link the product writes is absolute.** A relative path in somebody else's comment
resolves against *their* host, so `CRB_PUBLIC_URL` is required before a listener may be
switched on, and a pass without it stops with `no_public_url` before it writes anything
(`crb.server.intake.item_url_for`).

**One pass is bounded twice.** At most `CRB_INTAKE__MAX_PER_POLL` tickets, and no tracker
call started once `CRB_INTAKE__POLL_BUDGET_S` seconds have gone: a first pass over one ticket
it registers costs **eleven** Azure DevOps requests, or **nine** Jira ones **[measured —
n = 1 ready ticket × 2 adapters; method: every request counted through an
`httpx.MockTransport` for the verb sequence one pass makes,
`tests/test_intake_write_bound.py`; apparatus 2.2. A count, so no interval]**, runs in front
of the worker's heartbeat and, on demand, inside an API request. The budget is asked again at
the tracker boundary inside a ticket, so an expired pass starts no further call on somebody's
board (`crb.server.intake._BudgetGuard`). It bounds the calls rather than holding a
stopwatch: a call already in flight is not cancelled and runs on to its own timeout, so the
pass takes the budget plus the verb in progress. Wherever the budget goes — between two
tickets or inside the last one — the pass itself records the stop and how far it got, so a
served view that names no stop means there was none. A column longer than the bound is not
read at all — `column_too_large`, with the advice to narrow the area path or the JQL, because
reading an arbitrary 200 of somebody's board and saying nothing about the rest would be worse
than reading none of it.

**The consent switch is an event, not just a field.** `switched_by` on the repository row is
one mutable value a later switch overwrites, so every throw of the switch is
`intake.listener.switched` on that repository's system trace, naming the operator — otherwise
writes made under one operator's consent would later appear to have been consented by
whoever switched it last.

**The classifier never guesses silently.** It serves a confidence, and below the published
threshold the class is `unclassified` and the comment says so, asking the person rather
than routing money at a guess (`crb.intake.draft.classify`).

**Six verbs, and no more.** `TrackerClient` is `entered`, `read`, `comment`, `label`,
`transition`, `link` (`src/crb/intake/client.py`). The non-goals below are enforced by the
size of that protocol, not by a rule somebody has to remember. Adapters are stdlib plus
`httpx` — no vendor SDK.

**A registration during a run is queued, not refused.** The API refuses a registration
while a factory run holds the backlog hash (409 `factory_run_active`). The listener cannot
hand that refusal to anybody, so it records `intake.queued` and registers on the next poll.

## Consequences

*Easier.* A team's existing board is the front door: no second backlog, no re-typing, and
the questions a good test needs are asked on the ticket, in the ticket's own thread, for
nothing. A second tracker is an adapter and nothing else changes.

*Harder.* The product now writes on somebody else's system, so every write must be
idempotent and every failure must have a word a person can act on (`STOP_REASONS`, with
`STOP_ADVICE` beside it). The walkthrough cannot use a real tracker, so there is a
file-backed fake gated behind `CRB_ENABLE_FAKE_TRACKER=1` (`src/crb/intake/fake.py`).

*What we must never do.* Edit any ticket field other than our own label, our own comment
and the one configured state transition. Create a ticket. Read a column we were not
pointed at. Poll a repository whose listener nobody switched on. Put a credential in a URL,
a log, an event or an error message. Force a workflow transition the tracker refused.

## Alternatives considered

**Webhooks instead of polling.** Faster, and it is where this should end up. It needs a
publicly reachable endpoint, a shared secret per tracker and a replay-safe receiver — none
of which a single-host evaluation deployment has. Polling needs nothing inbound and is
idempotent by construction, so it ships first. [aspiration] A webhook receiver can be added
later without changing the protocol or the chain.

**Mirroring the whole board.** Reading every ticket and deciding for ourselves which to
work would remove the consent gate and make the product's appetite unbounded. One column
is a boundary a person controls.

**Editing the item in place on a re-read.** Simpler to write, and it destroys the property
the whole factory rests on: that the record a run verified against cannot move under it.

**Using a vendor SDK.** Both vendors publish one. Each brings a dependency tree, its own
auth model and its own failure vocabulary into a product whose error words are a published
contract. Six verbs over `httpx` is less code and testable with a mock transport.
