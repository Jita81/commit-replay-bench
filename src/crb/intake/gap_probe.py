"""The gap probe: build a ready ticket once, unseen, and ask what the builder had to guess.

ADR-0059. A ticket whose structural slots are all filled can still leave a decision open —
an exact error text, a name, a format. The gap probe builds the approved ticket ONCE with
``claude_code`` (blind, never delivered, its worktree discarded), reads back the decisions
the builder reports it guessed, and posts them to the ticket as questions before anything
is registered. A probe that reports nothing lets the ticket register as before; one that
reports questions sends it back with ``crb:needs-info``; one that fails stops it.

This module is the pure half: what the probe's request is keyed on, what state a ticket's
probe is in, which reported guesses become questions, and the brief's text. The poll and
the Register act (``src/crb/server/intake.py``) act on the state; the worker's
``gap_probe`` run kind (``src/crb/server/worker.py``) does the build.

Navigation
----------
What it is:   ``parse_guesses`` (builder-reported assumptions → at most N redacted
              :class:`~crb.core.stated.OpenGap` questions), ``probe_state`` (the chain →
              none / pending / done / failed for one ticket's content), ``unresolved_request``
              (the poll's "not finished with" test) and ``probe_brief`` (the ticket's text).
What it does: Keys every probe on the ticket's ``content_revision`` — the digest of what the
              person wrote, which this product's own comments, labels and moves never move —
              so a probe runs once per content and never again because of its own writes;
              drops any guess that is not one plain line of a known decision kind; and never
              keeps the builder's guessed answer, so a person is not shown it as a default.
How:          Pure functions over evidence events (``kind`` / ``item_id`` / ``payload``);
              ``crb.core.redact.redact`` on every question before it can reach a ticket.
Layer:        intake — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0059-a-gap-probe-asks-what-the-build-guessed.md,
              docs/adr/0017-the-ticket-is-the-backlog-item.md
Works with:   src/crb/server/intake.py (the poll and the Register act that act on the state),
              src/crb/server/worker.py (the ``gap_probe`` run kind that records the result),
              src/crb/builders/claude_code.py (the ``assumptions`` it reports),
              src/crb/core/stated.py (``OpenGap`` and the decision kinds),
              src/crb/intake/feedback.py (renders the questions in the readiness comment)
Tested by:    tests/test_intake_gap_probe.py
Touch when:   never for a new repository; a decision kind joins ``GAP_DECISIONS``; the probe
              gains a state.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from crb.core.redact import redact
from crb.core.stated import GAP_DECISIONS, MAX_GAP_QUESTION_CHARS, OpenGap
from crb.factory.evidence import (
    EV_INTAKE_GAP_PROBE_FAILED,
    EV_INTAKE_GAP_PROBE_FINISHED,
    EV_INTAKE_GAP_PROBE_REQUESTED,
    EV_INTAKE_READ,
)
from crb.store.jobs import TERMINAL_STATUSES

#: The only builder that reports the decisions it guessed; start-up refuses any other rung.
GAP_PROBE_BUILDER = "claude_code"
#: The worker's step event for the probe's build: its ``cost_usd`` is the probe run's served
#: cost, since a probe writes no ledger row.
GAP_PROBE_BUILD_ACTION = "gap_probe.build"
#: A question is one line of at most this many characters (a context set's gap limit).
MAX_QUESTION_CHARS = MAX_GAP_QUESTION_CHARS

#: The four states of one ticket's probe at one content.
STATE_NONE = "none"
STATE_PENDING = "pending"
STATE_DONE = "done"
STATE_FAILED = "failed"

#: Why a probe failed, as its ``intake.gap_probe.failed`` event says.
FAIL_RECLAIMED = "reclaimed"
FAIL_RUN_ENDED = "run_ended"
FAIL_UNPRICED = "unpriced"
FAIL_COST_UNKNOWN = "cost_unknown"
FAIL_BUILD_ERROR = "build_error"
FAIL_NOT_PROBE_BUILDER = "not_probe_builder"


@dataclass(frozen=True)
class ProbeState:
    """One ticket's probe at one content. ``recorded`` is ``False`` only for a failure the
    chain does not yet hold (the probe's run ended without writing its result), which the
    reader records once."""

    state: str
    run_id: str = ""
    approved_by: str = ""
    questions: tuple[OpenGap, ...] = ()
    reason: str = ""
    recorded: bool = True
    #: ADR-0060: ``"auto"`` when the act that asked for this probe consented to one capped
    #: build after it (the switch was on and an operator acted); the item it was asked for.
    manufacture: str = ""
    item_id: str = ""


NO_PROBE = ProbeState(STATE_NONE)


def _matches(e: Any, kind: str, tracker: str, key: str) -> bool:
    p = e.payload
    return bool(e.kind == kind and str(p.get("tracker")) == tracker and str(p.get("key")) == key)


def probe_state(
    events: Sequence[Any],
    tracker: str,
    key: str,
    content: str,
    run_status: Callable[[str], str | None] | None = None,
) -> ProbeState:
    """The probe of ticket ``key`` at ``content`` (its ``content_revision``), read from the
    chain. ``run_status`` answers a run's status (``None`` when the run does not exist);
    with it, a request whose run has ended — or vanished — without a result is ``failed``
    (``recorded=False``), so a dead probe never holds a ticket for ever."""
    listed = list(events)
    request = None
    at = -1
    for i in range(len(listed) - 1, -1, -1):
        e = listed[i]
        if _matches(e, EV_INTAKE_GAP_PROBE_REQUESTED, tracker, key) and (
            str(e.payload.get("content_revision", "")) == content
        ):
            request, at = e, i
            break
    if request is None:
        return NO_PROBE
    run_id = str(request.payload.get("run_id", ""))
    approved_by = str(request.payload.get("approved_by", ""))
    for e in listed[at + 1 :]:
        if str(e.payload.get("run_id", "")) != run_id:
            continue
        if _matches(e, EV_INTAKE_GAP_PROBE_FINISHED, tracker, key):
            questions = tuple(
                OpenGap(str(q.get("question", "")), str(q.get("decision", "")))
                for q in e.payload.get("questions") or ()
                if isinstance(q, Mapping) and str(q.get("decision", "")) in GAP_DECISIONS
            )
            return ProbeState(
                STATE_DONE,
                run_id,
                approved_by,
                questions,
                manufacture=str(request.payload.get("manufacture", "")),
                item_id=str(getattr(request, "item_id", "") or ""),
            )
        if _matches(e, EV_INTAKE_GAP_PROBE_FAILED, tracker, key):
            return ProbeState(
                STATE_FAILED, run_id, approved_by, reason=str(e.payload.get("reason", ""))
            )
    if run_status is not None:
        status = run_status(run_id)
        if status is None or status in TERMINAL_STATUSES:
            return ProbeState(
                STATE_FAILED, run_id, approved_by, reason=FAIL_RUN_ENDED, recorded=False
            )
    return ProbeState(STATE_PENDING, run_id, approved_by)


def unresolved_request(events: Sequence[Any], tracker: str, key: str) -> bool:
    """Whether ticket ``key``'s latest probe request is not yet acted on: it has no result
    on the chain, or no ``intake.read`` of the ticket came after its result. A read that
    judged this run still pending does not count: its result landed during that pass. The
    poll treats such a ticket as not finished with, whichever act asked for the probe — the
    Register act writes no read, so without this its probe's result would never be acted
    on."""
    listed = list(events)
    for i in range(len(listed) - 1, -1, -1):
        e = listed[i]
        if not _matches(e, EV_INTAKE_GAP_PROBE_REQUESTED, tracker, key):
            continue
        run_id = str(e.payload.get("run_id", ""))
        result = next(
            (
                j
                for j in range(i + 1, len(listed))
                if str(listed[j].payload.get("run_id", "")) == run_id
                and (
                    _matches(listed[j], EV_INTAKE_GAP_PROBE_FINISHED, tracker, key)
                    or _matches(listed[j], EV_INTAKE_GAP_PROBE_FAILED, tracker, key)
                )
            ),
            None,
        )
        if result is None:
            return True
        return not any(
            _matches(later, EV_INTAKE_READ, tracker, key)
            and not (
                str(later.payload.get("gap_probe_run_id", "")) == run_id
                and later.payload.get("gap_probe_state") == STATE_PENDING
            )
            for later in listed[result + 1 :]
        )
    return False


def _one_line(text: str) -> bool:
    return "\n" not in text and "\r" not in text and "```" not in text


def parse_guesses(raw: Any, n: int) -> list[OpenGap]:
    """The builder's reported ``assumptions`` → at most ``n`` questions for the ticket.

    An entry is dropped when its decision is not one of ``GAP_DECISIONS``, when its question
    is empty, spans lines, holds a code fence or is longer than one question may be, or when
    it repeats an earlier question (compared casefolded). Each question is redacted before
    anything else sees it, and the builder's ``guessed`` answer is discarded: the person is
    asked the question, never shown the builder's guess as a default."""
    out: list[OpenGap] = []
    seen: set[str] = set()
    entries: Iterable[Any] = raw if isinstance(raw, (list, tuple)) else ()
    for entry in entries:
        if len(out) >= max(0, int(n)):
            break
        if not isinstance(entry, Mapping):
            continue
        decision = str(entry.get("decision", "")).strip()
        raw_question = entry.get("question")
        if not isinstance(raw_question, str):
            continue
        question = raw_question.strip()
        if decision not in GAP_DECISIONS or not question or not _one_line(question):
            continue
        question = redact(question)
        if len(question) > MAX_QUESTION_CHARS:
            continue
        folded = question.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        out.append(OpenGap(question, decision))
    return out


def probe_brief(
    title: str, description: str, criteria: Sequence[str], facts: Sequence[str] = ()
) -> tuple[str, str]:
    """The probe brief's subject and message: the ticket's title, and its description with
    its acceptance criteria and the structural facts read from them — what a factory build
    of the item is told about the change (``crb.factory.build.factory_brief``), so the probe
    guesses only what the build would have to guess."""
    lines = [description.strip()] if description.strip() else []
    if criteria:
        lines += ["", "Acceptance criteria:"] + [f"  - {c}" for c in criteria]
    if facts:
        lines += ["", "Facts:"] + [f"  - {f}" for f in facts]
    return title, "\n".join(lines) or title


__all__ = [
    "FAIL_BUILD_ERROR",
    "FAIL_COST_UNKNOWN",
    "FAIL_NOT_PROBE_BUILDER",
    "FAIL_RECLAIMED",
    "FAIL_RUN_ENDED",
    "FAIL_UNPRICED",
    "GAP_PROBE_BUILDER",
    "GAP_PROBE_BUILD_ACTION",
    "MAX_QUESTION_CHARS",
    "NO_PROBE",
    "STATE_DONE",
    "STATE_FAILED",
    "STATE_NONE",
    "STATE_PENDING",
    "ProbeState",
    "parse_guesses",
    "probe_brief",
    "probe_state",
    "unresolved_request",
]
