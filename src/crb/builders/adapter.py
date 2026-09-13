"""Adapt the builder registry to the core orchestrator's ``BuildFn`` seam.

:func:`crb.core.run.run` climbs an escalation ladder of *rung labels* and calls
``build_fn(workspace, task, mode, rung_label)`` for each attempt. The core knows
nothing about model SDKs, budgets or the builder registry; this module is the
one place that knows both sides:

* :func:`ladder_from_spec` turns the labels a run carries (``runs.ladder_json``,
  ``--ladder`` on the CLI) into an :class:`~crb.builders.base.EscalationLadder`;
* :func:`ladder_labels` is the inverse — the labels the orchestrator will hand
  back, disambiguated so two rungs never share one;
* :func:`build_fn_for` builds the callable: rung label → builder instance
  (cached per rung), :class:`~crb.builders.base.BuildBrief` from the task, one
  ``builder.build(...)`` call, and a :class:`~crb.core.run.BuildAttempt` back.

Honesty properties
------------------
* The brief is derived with :meth:`BuildBrief.from_task`, so it **never**
  carries ``src_files``; in blind mode it carries no test path and no test
  command (the brief refuses to be constructed otherwise).
* Every failure is a *recorded non-pass*, never a crash and never a pass: an
  unknown rung, a builder that cannot be instantiated, a builder that raises, a
  ``model_error`` stop or a protocol violation all come back as a
  :class:`BuildAttempt` with ``error`` set. The orchestrator grades the worktree
  regardless — an untouched worktree fails belts 2/4 and the row records why.
* A protocol violation (tamper / archaeology / network) is surfaced as an
  ``error`` so the ledger can never credit that attempt ``clean`` (the ledger
  refuses a clean row with an error), independently of belt 1.
* **An attempt with an error yields no admissible patch.** Before the grader
  runs, :func:`discard_source_edits` restores the worktree's non-test files to
  the parent, so an errored attempt grades RED / no-source-change rather than
  clean-with-error — a combination :func:`crb.core.ledger.grade_row_from_result`
  currently turns into a ``FalseQ1Violation`` that would abort the whole run.
  The error string, the builder's metered spend and the (opt-in) transcript
  remain the record of what happened.
* A transcript is never inlined in the attempt: with ``transcript_dir`` set the
  redacted transcript is written to a file and referenced by path.
"""

from __future__ import annotations

import json
import shlex
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, cast

from crb.builders import builder_for_rung
from crb.builders.base import (
    STOP_MODEL_ERROR,
    Budget,
    BuildBrief,
    Builder,
    BuildOutcome,
    EscalationLadder,
    EventFn,
    Rung,
    emit,
)
from crb.builders.budget import budget_for_rung
from crb.core.evidence import BuilderRef
from crb.core.execution import Executor
from crb.core.grade import MODE_SIGHTED
from crb.core.ledger import GradeRow, JsonlLedger
from crb.core.redact import redact_and_cap
from crb.core.run import BuildAttempt, BuildFn
from crb.core.runners.base import BaseRunner
from crb.core.spec import RepoConfig, TaskSpec
from crb.core.workspace import Workspace

#: ``message_for(task) -> str`` — the full commit message (``GitRepo.message(sha)``).
MessageFn = Callable[[TaskSpec], str]

#: Prefix on the actions a builder emits, so a stream can tell the builder's own
#: ``build.attempt`` from the orchestrator's ``build.start`` / ``build.done``.
BUILDER_EVENT_PREFIX = "builder."

_VIOLATION_PREFIXES: tuple[str, ...] = ("tamper:", "archaeology:", "network:")


# ---------------------------------------------------------------------------
# Rung labels ⇄ ladder
# ---------------------------------------------------------------------------


def parse_rung_label(label: str, *, default_provider: str = "") -> Rung:
    """``builder:model[:provider]`` or ``builder:model[@provider]`` → :class:`Rung`.

    Both spellings are accepted because the ladder helpers in
    :mod:`crb.builders.budget` use ``@`` while run parameters use ``:``. When a
    model id itself contains ``:``, write the provider with ``@``. A missing
    provider falls back to ``default_provider`` (may be empty).
    """
    s = label.strip()
    if ":" not in s:
        raise ValueError(f"rung {label!r} must look like builder:model[:provider]")
    builder, rest = s.split(":", 1)
    if "@" in rest:
        model, _, provider = rest.partition("@")
    elif ":" in rest:
        model, _, provider = rest.rpartition(":")
    else:
        model, provider = rest, ""
    return Rung(
        builder=builder.strip(),
        model=model.strip(),
        provider=provider.strip() or default_provider.strip(),
    )


def ladder_from_spec(labels: Sequence[str], default_provider: str = "") -> EscalationLadder:
    """Parse the ladder a run carries (a sequence of rung labels) into a ladder.

    Blank entries are ignored; an empty result is a ``ValueError`` (a run with no
    rung cannot build anything, and :class:`EscalationLadder` refuses it too).
    """
    rungs = tuple(
        parse_rung_label(str(lbl), default_provider=default_provider)
        for lbl in labels
        if str(lbl).strip()
    )
    if not rungs:
        raise ValueError("a ladder needs at least one rung label (builder:model[:provider])")
    return EscalationLadder(rungs)


def _aliases(rung: Rung) -> tuple[str, ...]:
    base = rung.label
    if not rung.provider:
        return (base,)
    return (base, f"{base}@{rung.provider}", f"{base}:{rung.provider}")


def ladder_labels(ladder: EscalationLadder) -> tuple[str, ...]:
    """The labels to put on ``RunSpec.ladder`` — one per rung, in order, unique.

    A rung's label is ``Rung.label`` (``builder:model``). When two rungs share it
    the later one is written ``builder:model@provider``, and if that still
    collides, ``…#<index>``; :func:`rung_index` resolves every spelling back.
    """
    out: list[str] = []
    seen: set[str] = set()
    for i, rung in enumerate(ladder):
        candidates = [rung.label]
        if rung.provider:
            candidates.append(f"{rung.label}@{rung.provider}")
        candidates.append(f"{rung.label}#{i}")
        label = next(c for c in candidates if c not in seen)
        seen.add(label)
        out.append(label)
    return tuple(out)


def rung_index(ladder: EscalationLadder) -> dict[str, Rung]:
    """Every accepted spelling of every rung → the rung (first rung wins a tie)."""
    index: dict[str, Rung] = {}
    for label, rung in zip(ladder_labels(ladder), ladder, strict=True):
        index.setdefault(label, rung)
        for alias in _aliases(rung):
            index.setdefault(alias, rung)
    return index


# ---------------------------------------------------------------------------
# Ledger duck-typing (RunSpec is typed against the JSONL reference ledger)
# ---------------------------------------------------------------------------


class LedgerLike(Protocol):
    """What the orchestrator actually calls on ``RunSpec.ledger``: ``append``.

    :class:`~crb.core.ledger.JsonlLedger` and :class:`crb.store.ledger.DbLedger`
    both satisfy it (same chain-and-validate contract).
    """

    def append(self, row: GradeRow) -> GradeRow: ...


def as_run_ledger(ledger: LedgerLike) -> JsonlLedger:
    """Present any :class:`LedgerLike` as the ``JsonlLedger`` type ``RunSpec`` declares.

    The core only ever calls ``append`` (see :func:`crb.core.run.run_task`), so
    the cast is sound by inspection; it exists so a DB-backed ledger can be
    injected without editing the stdlib core.
    """
    return cast(JsonlLedger, ledger)


# ---------------------------------------------------------------------------
# Outcome → attempt
# ---------------------------------------------------------------------------


def attempt_error(outcome: BuildOutcome) -> str:
    """The ``BuildAttempt.error`` an outcome maps to (``""`` for an honest attempt).

    * a protocol violation (tamper / archaeology / network) → ``protocol violation: …``
      — the ledger then refuses to credit the row clean, whatever the belts say;
    * a ``model_error`` stop (no credential, SDK missing, API failure) → ``model_error: …``;
    * every other stop (done, a budget cap) is a legitimate attempt: no error.
    """
    if outcome.violated:
        found = [e for e in outcome.errors if e.startswith(_VIOLATION_PREFIXES)]
        return redact_and_cap("protocol violation: " + "; ".join(found), max_chars=500)
    if outcome.stop_reason == STOP_MODEL_ERROR:
        detail = "; ".join(outcome.errors) or "builder reported a model error"
        if detail.startswith(f"{STOP_MODEL_ERROR}:"):
            return redact_and_cap(detail, max_chars=500)
        return redact_and_cap(f"{STOP_MODEL_ERROR}: {detail}", max_chars=500)
    return ""


def discard_source_edits(ws: Workspace, config: RepoConfig, protected: Sequence[str]) -> list[str]:
    """Restore every touched NON-test file to the parent (delete new ones).

    Test files — the overlaid oracle in sighted mode, or anything the builder
    wrote under the test layout — are left alone: belt 1 / belt 0 must see them.
    Returns the paths discarded.
    """
    keep = set(protected)
    tracked = set(ws.repo.diff_names("HEAD", cwd=ws.root))
    discarded: list[str] = []
    restore: list[str] = []
    for rel in ws.touched_files():
        if rel in keep or config.is_test(rel):
            continue
        if rel in tracked:
            restore.append(rel)
        else:
            (ws.root / rel).unlink(missing_ok=True)
        discarded.append(rel)
    if restore:
        ws.restore_from_parent(restore)
    return discarded


def _failed_attempt(rung_label: str, mode: str, error: str) -> BuildAttempt:
    return BuildAttempt(
        BuilderRef(name=rung_label, mode=mode), error=redact_and_cap(error, max_chars=500)
    )


def _write_transcript(
    transcript_dir: Path, task: TaskSpec, rung: Rung, outcome: BuildOutcome
) -> str:
    """Persist the (already redacted) transcript; return its reference (path)."""
    if not outcome.transcript:
        return ""
    transcript_dir.mkdir(parents=True, exist_ok=True)
    name = f"{task.short_id}-{rung.builder}-{uuid.uuid4().hex[:8]}.json"
    path = transcript_dir / name
    body = {
        "task_id": task.task_id,
        "repo": task.repo,
        "rung": rung.to_dict(),
        "outcome": outcome.to_dict(include_transcript=True),
    }
    path.write_text(json.dumps(body, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    return str(path)


def sighted_test_command(
    runner: BaseRunner, executor: Executor, root: Path, target_tests: Sequence[str]
) -> str:
    """A human-readable command for the target tests (sighted briefs only).

    Best effort: any runner error yields ``""`` — the brief still lists the test
    files, and agentic adapters run the tests through the injected runner anyway.
    """
    try:
        timeout = int(runner.opts.get("timeout", runner.default_timeout))
        cmd = runner.command(root, tuple(target_tests), executor=executor, timeout=timeout)
    except Exception:
        return ""
    return " ".join(shlex.quote(a) for a in cmd.argv)


# ---------------------------------------------------------------------------
# The BuildFn
# ---------------------------------------------------------------------------


def build_fn_for(
    ladder: EscalationLadder,
    *,
    budget: Budget,
    runner: BaseRunner,
    executor: Executor,
    config: RepoConfig,
    on_event: EventFn | None = None,
    message_for: MessageFn | None = None,
    transcript_dir: str | Path | None = None,
    builder_overrides: Mapping[str, Any] | None = None,
) -> BuildFn:
    """The ``build_fn`` for :func:`crb.core.run.run` over ``ladder``.

    Parameters
    ----------
    budget:
        The base :class:`Budget`; a rung may override fields via its ``config``
        (:func:`~crb.builders.budget.budget_for_rung`).
    runner / executor / config:
        The repo's harness — used for the sighted ``test_command`` and passed to
        the builder through the brief's ``config`` (guards use ``config.is_test``).
    on_event:
        Receives the builder's own events with their actions prefixed
        ``builder.`` (never raises into the build).
    message_for:
        ``task -> full commit message`` (``GitRepo.message``). Defaults to the
        task subject; a failure falls back to the subject too.
    transcript_dir:
        When set, each attempt's redacted transcript is written there and
        referenced from ``BuildAttempt.transcript_ref`` — never inlined.
    builder_overrides:
        Extra constructor kwargs applied to every builder (e.g. a scripted
        ``chat_fn`` in tests, an ``endpoint``).
    """
    index = rung_index(ladder)
    overrides = dict(builder_overrides or {})
    builders: dict[int, Builder] = {}
    tdir = Path(transcript_dir) if transcript_dir else None

    def builder_on_event(action: str, payload: Mapping[str, Any]) -> None:
        emit(on_event, BUILDER_EVENT_PREFIX + action, **dict(payload))

    def instantiate(rung: Rung) -> Builder:
        key = id(rung)
        b = builders.get(key)
        if b is None:
            b = builder_for_rung(rung, **overrides)
            builders[key] = b
        return b

    def message(task: TaskSpec) -> str:
        if message_for is None:
            return task.subject
        try:
            return message_for(task) or task.subject
        except Exception:
            return task.subject

    def discard(ws: Workspace, task: TaskSpec, attempt: BuildAttempt) -> BuildAttempt:
        """An errored attempt leaves no admissible patch (see module docstring)."""
        if not attempt.error:
            return attempt
        try:
            dropped = discard_source_edits(ws, config, task.test_files)
        except Exception as exc:  # cannot even clean up: record it, grade whatever is there
            emit(on_event, BUILDER_EVENT_PREFIX + "discard.error", error=str(exc))
            return attempt
        if dropped:
            emit(on_event, BUILDER_EVENT_PREFIX + "discard", files=dropped, error=attempt.error)
        return attempt

    def build(ws: Workspace, task: TaskSpec, mode: str, rung_label: str) -> BuildAttempt:
        rung = index.get(rung_label)
        if rung is None:
            return _failed_attempt(rung_label, mode, f"unknown rung {rung_label!r} (not on ladder)")
        try:
            builder = instantiate(rung)
        except Exception as exc:
            return _failed_attempt(
                rung_label, mode, f"builder unavailable: {type(exc).__name__}: {exc}"
            )
        test_command = (
            sighted_test_command(runner, executor, ws.root, task.target_tests)
            if mode == MODE_SIGHTED
            else ""
        )
        brief = BuildBrief.from_task(
            task, mode=mode, message=message(task), test_command=test_command, config=config
        )
        rung_budget = budget_for_rung(rung, budget)
        try:
            outcome = builder.build(ws, brief, rung_budget, on_event=builder_on_event)
        except Exception as exc:
            failed = BuildAttempt(
                BuilderRef(
                    name=builder.name,
                    model=builder.model,
                    provider=builder.provider,
                    mode=mode,
                    budget=rung_budget.to_dict(),
                ),
                error=redact_and_cap(f"builder raised {type(exc).__name__}: {exc}", max_chars=500),
            )
            return discard(ws, task, failed)
        ref = _write_transcript(tdir, task, rung, outcome) if tdir is not None else ""
        attempt = BuildAttempt(
            outcome.builder_ref(transcript_ref=ref),
            error=attempt_error(outcome),
            transcript_ref=ref,
        )
        return discard(ws, task, attempt)

    return build


__all__ = [
    "BUILDER_EVENT_PREFIX",
    "LedgerLike",
    "MessageFn",
    "as_run_ledger",
    "attempt_error",
    "build_fn_for",
    "discard_source_edits",
    "ladder_from_spec",
    "ladder_labels",
    "parse_rung_label",
    "rung_index",
    "sighted_test_command",
]
