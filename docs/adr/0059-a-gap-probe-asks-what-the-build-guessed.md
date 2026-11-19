# ADR-0059 — A gap probe asks what the build guessed

**Status:** Proposed (DL-427) · **Amended by
[ADR-0060](0060-a-clean-probe-queues-one-capped-build.md)** (2026-11-18: an optional capped build
after a clean probe)
**Date:** 2026-11-18
**Apparatus impact:** none. APPARATUS_VERSION stays 2.6. A probe writes no ledger row, so no
grade, belt, cell, route, threshold or sign-off clause changes. With `CRB_INTAKE__GAP_PROBE`
off (the default) every tracker call, comment byte, label, event and builder argument is
pinned unchanged.
**Amends:** ADR-0017, the paragraph "The ticket is the backlog item" ("registered through
exactly the path the API uses"). That place carries an inline "(Amended by ADR-0059: …)"
mark. See "Amended text".

## Context

The readiness gate (ADR-0017, ADR-0056) asks a ticket's author only the questions its
structural slots expose: a missing name, signature or error text in a fixed shape. A ticket
whose slots are all filled can still leave a decision open that only a build runs into, such
as an exact message, a file format or a default. The factory then guesses, and a guess that
differs from what the team meant is a pull request nobody can merge.

The question loop was read on the bench before it was built here:

- Running the build once and asking its questions before the real run gave 36/45 clean
  against 26/45 for the request alone [measured]. n=45 Go feature tasks, `claude_code`
  `claude-sonnet-5`, blind, apparatus 2.6, in-sample. Method: registered readings read
  through the crb runs API, one per arm.
- Predicting the questions without a build was not supported in one reading [gap]. Closing
  it needs a powered reading of a no-build predictor against the same tasks.
- Those questions were read from the build's transcripts. A field in which the builder
  reports the decisions it guessed recovers them [hypothesis]. It is not yet compared with
  the transcript reading.

## Decision

**One trial build per approved ticket content, before registration.** A deployment switch,
`CRB_INTAKE__GAP_PROBE`, off by default, adds one step between approval and registration:

1. **Who asks.** A ticket the gate finds ready and that has an approval (the operator's
   Register act, or an author on the allowlist) is not registered at once. The approval is
   recorded on `intake.gap_probe.requested` (`approved_by`, `run_id`, `content_revision`)
   and one run of the new worker kind `gap_probe` is queued. The kind is created only by
   intake; `POST /runs` refuses it.
2. **What it builds.** The worker builds the ticket blind on `CRB_INTAKE__GAP_PROBE_RUNG`
   with the probe flag on the builder. The brief is the ticket's title, description,
   acceptance criteria and structural facts, which is what a factory build is told. The
   worktree is always discarded; the patch is never stored; nothing is pushed and no pull
   request is opened. The spend is capped at `CRB_INTAKE__GAP_PROBE_MAX_COST_USD`.
3. **What the builder reports.** With the flag, `claude_code`'s output schema gains an
   `assumptions` list of `{decision, question, guessed}`. Without it, the schema, system
   prompt and argument list are byte-identical to before, and a test pins that.
4. **Which guesses become questions.** An entry is dropped when its decision is not one of
   the gate's decision kinds, or its question is empty, spans lines, holds a code fence, is
   longer than 240 characters or repeats an earlier one (casefolded). Each question is
   redacted. At most `CRB_INTAKE__GAP_PROBE_MAX_QUESTIONS` are kept. The `guessed` answer
   is discarded, so a person is never shown the builder's guess as a default.
5. **What the poll does with the result.** No questions, because the build reported no
   guess (a build whose reported guesses were all dropped has failed, item 7): the ticket is
   registered under the approval recorded on the request, with no second Register act and
   no second probe.
   Questions: they are added to the existing readiness comment under its own marker, the
   label becomes `crb:needs-info` and the return (ADR-0056) applies; the four-comment bound
   is unchanged. Failure: the row stops `gap_probe_failed`, nothing is registered and the
   probe is not retried at that content.
6. **Keyed on content.** A probe is keyed on the ticket's `content_revision`, the digest of
   what the person wrote. This product's own comment, label and move never start a second
   probe; an edit to the ticket does. A ticket with a request whose result has not been read
   is never treated as handled.
7. **Fail closed.** The run fails when it was reclaimed, when its rung is not `claude_code`,
   when its model is unpriced or its cost unknown, when the build raises, and when the build
   stops without its structured answer (an error, the spend cap, the wall clock), which is
   never read as "no questions". A build that reports guesses of which none can be asked
   fails the same way. A request whose run has ended or vanished without a result
   is recorded failed once, judged on the chain read again after the run is seen ended, so a
   probe that finished during a pass is never recorded failed. A run queued whose request
   could not be recorded is cancelled; that stops its spend when the cancel lands while it
   is still queued. A pass that finds a probe run already queued for the same content reuses
   it rather than queue a second, so a process that died between the two writes leaves one
   run, not two. That holds when the run already ended too: the request then names a run
   with no result after it and fails closed. Only a run cancelled before it started is not
   reused. On a sealed worker the probe refuses exactly as a factory run does. Before it is
   queued, the run meets the one submit gate `POST /runs` applies, so a probe whose builder
   has no credential or whose model has no price is refused and never queued.
8. **Cost recording.** The probe's spend is the `cost_usd` of its `gap_probe.build` step
   event, which `GET /runs/{id}` sums as the run's served cost; its finished and failed
   events carry it too. No ledger row is written, so a probe never reaches a cell or route.
9. **Start-up refuses** the switch on with an empty rung, a rung whose builder is not
   `claude_code` (even while off), and the switch on with `CRB_INTAKE__REQUIRE_APPROVAL`
   false: a probe spends, so an unattended column must not start one.

### Amended text

- **ADR-0017, "The ticket is the backlog item"**, "registered through exactly the path the
  API uses", now reads as: registered through exactly the path the API uses, after, where
  `CRB_INTAKE__GAP_PROBE` is on, one trial build of that content reported no guess at
  all. A build whose guesses were all dropped by step 4 is a failed probe, not a clean one.

## Consequences

- A ticket can come back with a question no slot would have raised, before a factory run
  spends on a guess.
- An approved ticket waits for one trial build before it is registered, and each new content
  costs one more build. The operator opts in and caps it.
- The Register act changes shape when the switch is on: it queues the probe and returns
  `gap_probe_pending`; the poll registers. A repeated act is refused `gap_probe_pending`,
  `gap_probe_failed` or `gap_probe_questions`.
- Proven against fakes only [gap]. The out-of-sample effect of the questions and the
  quality of the answers people write are unmeasured; closing it needs a registered
  reading on tickets the loop was not tuned on.
- Not in this change: a probe on another builder, manufacturing straight after a clean
  probe (Amended by ADR-0060: built behind `CRB_INTAKE__AUTO_MANUFACTURE`, off by default),
  and showing the probe's run on the intake screen.

## Alternatives considered

- **Predict the gaps without a build.** Cheaper, but not supported in the one reading taken.
- **Read the questions from the build's transcript.** That is how the bench reading was made,
  but it needs a second model call and a parser over free text; a field in the builder's own
  output is checkable and redactable.
- **Write a ledger row for the probe.** It would put a never-delivered build into the cells
  that route real work. The step event carries the cost instead.
- **Register first and probe in the factory run.** The question would arrive after a run was
  already spent on a guess, and the item would exist before its words were settled.
