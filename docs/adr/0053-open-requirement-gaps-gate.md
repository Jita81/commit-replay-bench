# ADR-0053 — Open requirement gaps: a stated set records its questions and a run refuses them

**Status:** Proposed (DL-421)
**Date:** 2026-11-16
**Apparatus impact:** none. APPARATUS_VERSION stays 2.6. No existing set digest, row, arm,
guard decision, reader result or builder input changes. The new field is optional, the new
refusal fires only on sets that carry it, and the new stamp is provenance.
**Builds on:** ADR-0050 (context sets) and ADR-0052 (stated-requirement arms).

## Context

ADR-0052 measures the pass rate when every required item is stated. Its sets are written by
an author who reads the commit and its request. Some items cannot be decided from what the
author was shown: an error text, a name, a format or a rule that the request leaves open. The
author can either guess or leave the item out.

Both choices spoil the measurement. A guessed item is a statement nobody made. A missing item
turns a "stated" row into a row with a gap, so the arm no longer reads "every gap closed".
Nothing in a v2 set records that the author had an open question, and nothing stops a run over
such a set. The tool should push back on a request with known gaps until they are closed.

## Decision

1. **The record.** A `crb.ctxset.v2` entry may carry an optional `gaps` list. Each gap is
   `{"question": str, "decision": kind}`:
   - `question` is one trimmed line, at most 240 characters, with no code fence;
   - `decision` is one of the item kinds (`name`, `signature`, `error_text`, `format`,
     `rule`, `value`): the kind of item the answer would become.
   - The list holds at most as many gaps as an entry may hold items, and no question repeats.
   - A malformed gap is refused as strictly as a malformed item. A v1 entry refuses `gaps`.
2. **The digest.** The set digest includes `gaps` only when the list is non-empty, so every
   existing set keeps its digest and its name. The items digest never includes gaps, so a
   closed set pairs with the control of the open one.
3. **Never in the brief.** A gap is never rendered into the builder's prompt. The rendered
   entry text is the items alone, unchanged.
4. **The gate.** `POST /runs` with `context_role: entries` over a set with any open gap is
   409 `ctx_open_gaps`, listing the questions per task, before any spend. The worker refuses
   the same run at claim, before anything is built. A `control` run is unaffected.
5. **The opt-in.** `measure_open_gaps: true` (only with `context_set` and role `entries`)
   runs the set anyway, for measurement only. It is stored on the run, and every row whose
   entry had gaps carries `ctx_open_gaps` = the gap count. The ledger refuses that stamp on
   any other row and refuses a value that is not a positive count. The default is refuse.
6. **Offline.** `crb ctxset lint` prints each entry's open gaps as questions. It does not fail
   on them: a gap is a question for a person, not a defect in the file.

No existing guard is weakened: the reading, posture, digest, repository and coverage checks
run first and unchanged.

## Consequences

- An author can say "I do not know" in the record instead of guessing. The question travels
  with the set and is shown at the moment a run would spend.
- A run over a set with gaps costs nothing until a person answers the questions and stores
  the closed set, or opts in to measure the set as it is.
- Rows measured with gaps open are distinguishable by their stamp, so a reader can split
  them from rows whose gaps were closed. No reader splits on it yet [gap].
- The gaps are not checked against the commit. A question that the request did answer is
  still a question; that is a matter for the author and the reviewer.

## Alternatives considered

- **Refuse gaps at store time.** Rejected: the record of what is unknown is the value. A set
  with gaps should be storable and inspectable; only spending on it should wait.
- **Render gaps into the brief as open questions.** Rejected: it changes the builder's input
  for the arm and mixes the "every item stated" measurement with a different one.
- **Include gaps in the items digest.** Rejected: closing a gap would then break the pairing
  with the control already run over the same items.
- **Make the gate advisory (warn and run).** Rejected: the default must stop spend on a
  measurement that cannot mean what its arm says; the opt-in covers deliberate measurement.
