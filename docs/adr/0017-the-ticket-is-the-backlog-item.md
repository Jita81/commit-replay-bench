# ADR-0017 — The ticket is the backlog item; the column is the consent gate

**Status:** Accepted
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
ticket read again at the same revision writes nothing. A ticket read at a *new* revision
becomes a new item, `<id>.r<revision>`, with `supersedes` set — the frozen record's hash
never moves (`crb.intake.draft.draft_from`).

**The ticket learns before any spend.** One comment, idempotent by a hidden HTML marker,
carries the readiness gate's open questions with the exact line that closes each one, and
the cell's route with its n, its 95 % interval, its apparatus version and whether the
honesty floor is intact — read from the map *before* any run
(`crb.intake.feedback.render_feedback`). One of four labels goes with it:
`crb:needs-info`, `crb:ready`, `crb:not-deliverable`, `crb:queued`.

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
