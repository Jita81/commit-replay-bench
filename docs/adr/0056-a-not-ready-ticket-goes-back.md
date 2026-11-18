# ADR-0056 — A ticket with open questions goes back to a state the team names

**Status:** Proposed (DL-424)
**Date:** 2026-11-17
**Apparatus impact:** none. Intake decides which items exist, never how one is graded
(ADR-0017's reasoning holds). No belt, cell, route, threshold, sign-off clause, set digest or
row changes; APPARATUS_VERSION and every policy version are unchanged. With
`CRB_INTAKE__RETURN_STATE` unset, every tracker call, comment byte, label and event is pinned
unchanged.
**Amends:** ADR-0017, the paragraph on what the product writes ("and the one configured
state change") and Consequences, *What we must never do* ("Edit any ticket field other than
our own label, our own comment and the one configured state transition"). Both places carry
an inline "(Amended by ADR-0056: …)" mark. See "Amended text".

## Context

A ticket the readiness gate finds gaps in gets a comment listing them and `crb:needs-info`,
and stays in the watched column. On a team's board that reads as "the factory has it". The
person who must answer does not see it come back to them. The board needs to show that the
next move is theirs, which means the ticket going back a column.

## Decision

1. One optional setting, `CRB_INTAKE__RETURN_STATE`, for the deployment, EMPTY BY DEFAULT.
   It names the Azure DevOps state or Jira status a ticket goes back to. The product cannot
   work out "the previous column": the tracker protocol reads no workflow order or history,
   and Azure DevOps columns are addressed by state here.
2. A ticket is moved back only when all hold: its label is `crb:needs-info`; the read
   confirms it is still in the watched column; it is not already in the return state; it has
   never been registered as an item; and the chain holds no return of it at this revision.
   `crb:not-deliverable`, `crb:ready` and `crb:queued` never move.
3. Order: the gap comment, then the label, then the ticket is read again, then the move,
   with the existing `read` and `transition` verbs. The six verbs stay six. If the read again
   finds the ticket has left the watched column (a person moved it), there is no move: their
   move stands, `intake.read` carries `return_skipped: true` and `state_now`, and the comment
   is written again without the sentence about the return. If the read again finds the
   ticket's own content changed (title, description, acceptance criteria, type, points or
   classifier tags; not the product's label or comment), there is no move either:
   `intake.read` carries `return_pending: true` and `content_changed: true`, so the next pass
   assesses the ticket as it now reads.
4. A move is `intake.transitioned` with `outcome` = `returned`, `from_state` and `revision`.
   A failed move is `intake.stopped` with `step` = `return`. The comment and label stay and
   the row shows the stop; the stop carries `tracker` and `revision`. A refusal (`refused`) is
   final at that revision for every normal pass, including a pass that rebuilds a served row
   the cache lost: that pass reads the refusal from the chain, rebuilds the comment and the
   row, and makes no move. It is tried again when the ticket changes, or when an operator
   forces *Post the feedback again*. Any other failure (the tracker did not answer, the pass ran
   out of time, the lease went) leaves `return_pending: true` on `intake.read`, so the next
   pass tries the move again at the same revision.
5. The comment says so: when a move is due, one sentence says the product will try to move
   the ticket back to the named state and asks for it to be moved into the watched column
   again. A re-post at a revision already returned, or refused, keeps the sentence, so the
   comment's bytes do not change.
6. Start-up refuses a return state equal to the watched column or to any `outcome_map` state.
   Switching a repository's listener on to a column equal to the return state is refused
   (`intake_column_is_return_state`). A listener switched on to that column before the
   setting was named is in neither check, so while any switched-on listener watches the
   return state no ticket is moved back on any repository; the worker's pass and the poll
   route ask the same question, so they cannot disagree.

### Amended text

- **ADR-0017, the paragraph on what the product writes**, "and the one configured state
  change", now reads as: the one configured state change after a merge or close, and, where
  `CRB_INTAKE__RETURN_STATE` is set, one return of a ticket with open questions per changed
  revision.
- **ADR-0017, Consequences, *What we must never do***, "Edit any ticket field other than our
  own label, our own comment and the one configured state transition", now reads as: other
  than our own label, our own comment, the configured outcome transition and the configured
  return.

Everything else in ADR-0017 stands, including "Force a workflow transition the tracker
refused": a refused return is recorded, never forced through the workflow or retried with
another state. Trying the same move again on an operator's request is not forcing it.

## Consequences

*Easier.* The board shows who holds a not-ready ticket. Nothing changes for a deployment that
sets nothing.

*Harder.* "One transition per ticket" becomes "one return per changed revision": a person
who moves the ticket forward without answering gets it back again. People bound this,
not the product. On both trackers the product's own label write moves the revision (Azure
DevOps `System.Rev`, Jira `updated`), so a refused return is tried once more on the next
poll, and then not again until a person changes the ticket or an operator posts the
feedback again. A return costs two Azure DevOps requests (the read again, then one PATCH of
the state) or three Jira ones (the read again, a list of the transitions on offer, then the
POST of the one that lands on the state) **[hypothesis — counted from the adapters' `read`
and `transition` code in `src/crb/intake/`, not measured against a live tracker]**.

*Gaps.* The product cannot check that the named state is earlier in the team's workflow
(only that it is not the watched column or an outcome state). A repository that overrides the
watched column shares the deployment's return state. Azure DevOps board columns that split one
state cannot be addressed. A person who moves the ticket in the moment between the read
again and the move is still overwritten: closing that needs a conditional write (Azure
DevOps's `test` operation on `System.Rev`), which would change the `transition` verb. The
comment says the product will try to move the ticket back before the move is made; when the
tracker refuses it the comment is not written again, because a comment edit moves the
revision and the product would then try, refuse and edit again on every pass. The served
row and the chain carry the stop, and an operator acts on it.

## Alternatives considered

**Work out the previous column from the board.** Needs the work item type's state order or
the board's column configuration: new reads and a new verb, for a guess.

**Move not-deliverable tickets back too.** A person cannot answer those on the ticket; it
would only add a round trip.

**A per-repository return state.** Truer for a repository whose team names its states
differently, but it changes the listener's shape, API and UI. Deferred until a team needs it.

**Retry a refused move every pass.** It hammers a workflow that will keep refusing, which
ADR-0017 already rules out for the outcome move.
