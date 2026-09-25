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
* **Sealed container path** (``container=``, ADR-0012). The builder never sees the
  real worktree: it gets a :class:`~crb.builders.container.SealedCheckout` (an export
  of the parent tree with no other object in its store) and, for the agentic
  builders, runs inside a hardened container whose only egress is the allowlisting
  proxy. The result is copied back (regular files only) into the real worktree,
  which the unchanged grader then grades. A sandbox that cannot be provided is
  :class:`~crb.core.execution.SandboxUnavailable` and propagates — the run stops —
  rather than becoming a recorded attempt on the host.

Navigation
----------
What it is:   The seam between the stdlib orchestrator and the builder registry — rung labels
              ⇄ ``EscalationLadder``, and ``build_fn_for``, the ``BuildFn`` the run calls.
What it does: Per attempt: resolves the rung, derives the brief (never ``src_files``; nothing
              test-shaped in blind mode), runs one ``builder.build`` — on the host or against
              a sealed checkout in a container — writes the redacted transcript to a file,
              maps the outcome to a ``BuildAttempt`` and discards the source edits of any
              errored attempt so it can never grade clean-with-error. A sealed attempt whose
              container kill went UNCONFIRMED (cancel / wall clock; the daemon never reported
              it stopped) is never silent: the outcome's errors and ``extra`` say so, the
              attempt's pack notes carry ``kill_confirmed: false``, and ``on_kill_unconfirmed``
              hands the container to the caller (the worker records it and reaps it).
How:          ``ladder_from_spec`` → ``rung_index`` → ``build``: ``sighted_test_command``
              (services up, env prefix) → ``BuildBrief.from_task`` → ``budget_for_rung`` →
              ``builder.build`` / ``sealed_build`` (``SealedCheckout`` + ``ContainerSession``
              + ``copy_back``) → ``attempt_error`` → ``discard``.
Layer:        builders — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md,
              docs/adr/0012-builder-in-a-sealed-container.md,
              docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/core/run.py (defines ``BuildFn``/``BuildAttempt`` and calls this),
              src/crb/builders/base.py (brief, budget, outcome), src/crb/builders/__init__.py
              (``builder_for_rung``), src/crb/builders/container.py (the sealed path;
              ``ContainerSession.unconfirmed_kills``), src/crb/server/reaper.py (what the
              worker does with an ``UnconfirmedKill``),
              src/crb/builders/budget.py (per-rung budget), src/crb/core/ledger.py (why an
              errored attempt must not carry a patch), src/crb/server/worker.py (the caller
              that supplies ``container`` from the environment)
Tested by:    tests/test_builders_adapter.py, tests/test_builders_container.py, tests/test_run.py
Touch when:   never for a new repository (the sighted test command comes from the runner);
              a new builder that must run sealed is added to ``SEALABLE_BUILDERS`` in
              src/crb/builders/container.py; a new attempt error kind must keep its prefix on
              the head (the ledger reads it there) and needs a ledger test.
"""

from __future__ import annotations

import contextlib
import json
import logging
import shlex
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
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
from crb.builders.container import (
    SEALABLE_BUILDERS,
    BuilderContainerSettings,
    ContainerSession,
    SealedCheckout,
    SessionFactory,
    UnconfirmedKill,
)
from crb.core.evidence import BuilderRef
from crb.core.execution import Command, Executor, SandboxUnavailable
from crb.core.grade import MODE_SIGHTED
from crb.core.ledger import GradeRow, JsonlLedger
from crb.core.lint import fix_commands, run_plan
from crb.core.redact import redact_and_cap_head
from crb.core.run import BuildAttempt, BuildFn
from crb.core.runners.base import BaseRunner
from crb.core.spec import RepoConfig, TaskSpec
from crb.core.workspace import Workspace

_LOG = logging.getLogger(__name__)

#: ``message_for(task) -> str`` — the full commit message (``GitRepo.message(sha)``).
MessageFn = Callable[[TaskSpec], str]

#: ``on_kill_unconfirmed(task_id, kill)`` — a sealed attempt's container whose enforced kill
#: the daemon did not confirm (it may still be running). The worker records the event on
#: the run's trace and queues the reaper; the callback must not raise into the build.
KillUnconfirmedFn = Callable[[str, UnconfirmedKill], None]

#: ``BuildOutcome.extra`` keys a sealed attempt stamps when its kill went unconfirmed.
EXTRA_KILL_CONFIRMED = "kill_confirmed"
EXTRA_CONTAINER = "container"


def unconfirmed_kill_error(kill: UnconfirmedKill) -> str:
    """The outcome error an unconfirmed kill adds (prefix ``container:`` — not a
    protocol violation and not a model error, so the attempt is still graded)."""
    return (
        f"container: kill unconfirmed — {kill.container} may still be running "
        f"(the daemon did not report it stopped within {kill.bound_s:g} s)"
    )


def note_unconfirmed_kills(outcome: BuildOutcome, kills: Sequence[UnconfirmedKill]) -> BuildOutcome:
    """The outcome with each unconfirmed kill on its errors and ``extra`` (``kill_confirmed:
    False``, ``container``) — the record an evidence pack and a transcript keep."""
    if not kills:
        return outcome
    return replace(
        outcome,
        errors=(*outcome.errors, *(unconfirmed_kill_error(k) for k in kills)),
        extra={
            **outcome.extra,
            EXTRA_KILL_CONFIRMED: False,
            EXTRA_CONTAINER: kills[-1].container,
        },
    )


def attempt_notes(outcome: BuildOutcome) -> dict[str, Any]:
    """The pack notes an outcome earns: ``{kill_confirmed: False, container}`` when its
    container kill went unconfirmed, else nothing."""
    if outcome.extra.get(EXTRA_KILL_CONFIRMED) is False:
        return {
            EXTRA_KILL_CONFIRMED: False,
            EXTRA_CONTAINER: str(outcome.extra.get(EXTRA_CONTAINER, "")),
        }
    return {}


#: The worker's builder-container posture from ``CRB_BUILDER__*`` (``None`` = host);
#: raises ``SandboxUnavailable`` when ``docker`` is requested but incomplete.
container_settings_from_env = BuilderContainerSettings.from_env

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
    """Every spelling of a rung's label that ``rung_index`` should resolve."""
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
        return _prefixed("protocol violation: ", "; ".join(found))
    if outcome.stop_reason == STOP_MODEL_ERROR:
        detail = "; ".join(outcome.errors) or "builder reported a model error"
        if detail.startswith(f"{STOP_MODEL_ERROR}:"):
            detail = detail[len(STOP_MODEL_ERROR) + 1 :].lstrip()
        return _prefixed(f"{STOP_MODEL_ERROR}: ", detail)
    return ""


def _prefixed(prefix: str, detail: str, *, max_chars: int = 500) -> str:
    """``prefix + detail`` with the *detail* capped head-first, never the prefix: the
    ledger reads an error's kind off its head (``protocol violation:`` / ``model_error:``)."""
    return prefix + redact_and_cap_head(detail, max_chars=max(1, max_chars - len(prefix)))


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
    """An attempt that never reached a builder (unknown rung, un-instantiable builder)."""
    return BuildAttempt(BuilderRef(name=rung_label, mode=mode), error=_prefixed("", error))


def _write_transcript(
    transcript_dir: Path, task: TaskSpec, rung: Rung, outcome: BuildOutcome
) -> str:
    """Persist the (already redacted) transcript; return its reference (path)."""
    if not outcome.transcript:
        return ""
    transcript_dir.mkdir(parents=True, exist_ok=True)
    # the task is inside the file and on the pack that cites it; the name carries no task only
    # so that nothing built from it names a commit. It is not a seal: on the host posture a
    # builder can read this file, and CRB_HOME, outright (DL-053's residual — production
    # refuses the host posture, ADR-0023); the sealed builder sees only its exported checkout
    name = f"{rung.builder}-{uuid.uuid4().hex[:12]}.json"
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
    runner: BaseRunner,
    executor: Executor,
    root: Path,
    target_tests: Sequence[str],
    *,
    authored: str | None = None,
) -> str:
    """A human-readable command for the target tests (sighted briefs only).

    Best effort: any runner error yields ``""`` — the brief still lists the test
    files, and agentic adapters run the tests through the injected runner anyway.

    With services declared (``runner_opts.services``) the era's services are brought
    up HERE, before the builder starts, and their environment is part of the command:
    the grader gets the MESH sandbox, so the builder must too — otherwise it reaches
    for ``docker`` / ``curl localhost:8701`` itself and the sealed posture refuses it
    (mesh-client, 2 of 4 sighted attempts, 2026-09-15).
    """
    try:
        timeout = int(runner.opts.get("timeout", runner.default_timeout))
        cmd = runner.command(root, tuple(target_tests), executor=executor, timeout=timeout)
        env = dict(cmd.env)
        if runner.has_services():
            runner.ensure_services(executor, root, authored=authored)
            env.update(runner.service_env())
    except Exception:
        return ""
    # The runner's environment (PYTHONPATH, GOFLAGS, NODE_PATH …) is part of the command:
    # without it a builder sees ImportErrors and reaches for `pip install`, which the
    # no-network rule then refuses — measured on pallets/click (5/5 attempts errored).
    env_prefix = " ".join(f"{k}={shlex.quote(str(v))}" for k, v in sorted(env.items()))
    argv = " ".join(shlex.quote(a) for a in cmd.argv)
    return f"{env_prefix} {argv}".strip()


# ---------------------------------------------------------------------------
# The BuildFn
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Preflight:
    """Belt-5 pre-flight — the builder's counterpart of DL-024 for the repository's own
    linter/formatter. OFF by default; a run that switches it on is a DIFFERENT arm
    (the builder is recorded as ``<name>+preflight`` so its rows never pool with plain
    rows), stamped ``labels.preflight`` with what happened.

    After an honest build (no violation, no error) and before the grade:

    1. run belt 5's plan on the changed non-test files — clean: nothing to do;
    2. ``fix``: apply the plan's tools in FIX mode (``prettier --write``, ``ruff check
       --fix`` + ``ruff format``, ``gofmt -w``, ``cargo fmt`` … — :func:`fix_commands`)
       and re-run the plan;
    3. still rejected and ``repair_turns`` > 0: ONE more bounded build call with the
       findings (``BuildBrief.repair_note``), then re-run the plan.

    Measured (Stage A, 2026-09-15, four NHS lint misses): the fixers alone flip 2 of 4
    (both prettier); a type error and a ruff rule need the repair turn.
    """

    fix: bool = True
    repair_turns: int = 1
    #: the repair call's budget: the rung's, capped at these
    repair_max_turns: int = 10
    repair_max_tool_calls: int = 15
    repair_wall_clock_s: int = 300

    @property
    def label(self) -> str:
        return f"fix={int(self.fix)},repair={self.repair_turns}"

    @classmethod
    def from_params(cls, raw: Any) -> Preflight | None:
        """``params.preflight``: ``true`` → defaults; an object → fields; else ``None``."""
        if raw is True:
            return cls()
        if isinstance(raw, Mapping):
            return cls(
                fix=bool(raw.get("fix", True)),
                repair_turns=int(raw.get("repair_turns", 1)),
            )
        return None


def _changed_source_files(ws: Workspace, config: RepoConfig) -> list[str]:
    return [f for f in ws.touched_files() if not config.is_test(f) and (ws.root / f).is_file()]


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
    container: BuilderContainerSettings | None = None,
    session_factory: SessionFactory = ContainerSession,
    preflight: Preflight | None = None,
    on_kill_unconfirmed: KillUnconfirmedFn | None = None,
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
    container:
        When set (the worker's ``CRB_BUILDER__EXECUTOR=docker`` posture), every
        rung whose builder is in :data:`SEALABLE_BUILDERS` builds against a
        :class:`SealedCheckout` inside a :class:`ContainerSession`; other builders
        (the test-only gold replay) keep the real worktree. ``session_factory``
        exists for tests.
    on_kill_unconfirmed:
        Receives ``(task_id, UnconfirmedKill)`` for every sealed container whose
        enforced kill the daemon did not confirm — after the attempt, whether the
        builder returned or raised. Without it the kill is still on the outcome and
        the pack, and logged; the container is nobody's to reap.
    """
    index = rung_index(ladder)
    overrides = dict(builder_overrides or {})
    builders: dict[int, Builder] = {}
    tdir = Path(transcript_dir) if transcript_dir else None

    def builder_on_event(action: str, payload: Mapping[str, Any]) -> None:
        emit(on_event, BUILDER_EVENT_PREFIX + action, **dict(payload))

    def instantiate(rung: Rung) -> Builder:
        # One builder per rung for the run (its SDK client is reused across tasks); the
        # sealed path instantiates per attempt instead because the spawn is session-bound.
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

    def sealed_build(
        ws: Workspace,
        task: TaskSpec,
        rung: Rung,
        brief: BuildBrief,
        rung_budget: Budget,
        *,
        carry_files: Sequence[str] = (),
    ) -> BuildOutcome:
        """One attempt against a sealed checkout inside a container session. The
        builder is instantiated per attempt (its spawn/executor belong to the
        session); ``SandboxUnavailable`` propagates. Copy-back happens even when the
        builder raised: whatever it left is the record of the attempt, and an errored
        attempt is discarded by the caller regardless."""
        assert container is not None
        dest = ws.root.parent / f"{ws.root.name}-sealed"
        tests = task.test_files if brief.sighted else ()
        with SealedCheckout.create(ws, dest, test_files=tests, carry_files=carry_files) as sealed:
            emit(
                on_event,
                BUILDER_EVENT_PREFIX + "sealed",
                task=task.task_id,
                commit=sealed.commit,
                image=container.image,
                network="proxy" if container.networked else "none",
            )
            # the run's cancel token (when the executor exposes one) so `docker kill`
            # follows a cancelled run instead of waiting for the wall clock
            cancel = getattr(executor, "cancel_fn", None)
            try:
                with session_factory(
                    container, sealed, cancel=cancel, label=ws.root.name
                ) as session:
                    # the session supplies the container-bound spawn / executor; an
                    # explicit override (a test's fake binary) still wins
                    builder = builder_for_rung(
                        rung, **{**session.overrides_for(rung.builder), **overrides}
                    )
                    try:
                        outcome = builder.build(
                            sealed.workspace(), brief, rung_budget, on_event=builder_on_event
                        )
                    finally:
                        # whether the builder returned or raised: a container the daemon
                        # never reported stopped is handed on, never dropped
                        kills = report_unconfirmed(session, task)
                    outcome = note_unconfirmed_kills(outcome, kills)
            except BaseException:
                # best effort: whatever the builder left is the record of the attempt;
                # the in-flight exception (SandboxUnavailable included) is what matters
                with contextlib.suppress(Exception):
                    sealed.copy_back(ws)
                raise
            try:
                copied = sealed.copy_back(ws)
            except Exception as exc:  # the result is not admissible: an errored attempt
                raise RuntimeError(f"copy_back failed: {type(exc).__name__}: {exc}") from exc
            emit(
                on_event, BUILDER_EVENT_PREFIX + "copy_back", task=task.task_id, **copied.to_dict()
            )
        return outcome

    def report_unconfirmed(session: Any, task: TaskSpec) -> list[UnconfirmedKill]:
        """The session's unconfirmed kills, each handed to ``on_kill_unconfirmed`` (and
        logged); a session double without the method (a test fake) reports none."""
        ask = getattr(session, "unconfirmed_kills", None)
        kills: list[UnconfirmedKill] = list(ask()) if callable(ask) else []
        for kill in kills:
            _LOG.warning(
                "task %s: %s — recorded on the attempt%s",
                task.task_id,
                unconfirmed_kill_error(kill),
                "; handed to the reaper" if on_kill_unconfirmed is not None else "",
            )
            if on_kill_unconfirmed is not None:
                with contextlib.suppress(Exception):  # never into the build
                    on_kill_unconfirmed(task.task_id, kill)
        return kills

    def build(ws: Workspace, task: TaskSpec, mode: str, rung_label: str) -> BuildAttempt:
        """The ``BuildFn``: one attempt of ``task`` on ``rung_label`` in ``mode``."""
        rung = index.get(rung_label)
        if rung is None:
            return _failed_attempt(rung_label, mode, f"unknown rung {rung_label!r} (not on ladder)")
        sealed = container is not None and rung.builder in SEALABLE_BUILDERS
        try:
            builder = instantiate(rung)
        except Exception as exc:
            return _failed_attempt(
                rung_label, mode, f"builder unavailable: {type(exc).__name__}: {exc}"
            )
        test_command = (
            sighted_test_command(
                runner, executor, ws.root, task.target_tests, authored=task.authored
            )
            if mode == MODE_SIGHTED
            else ""
        )
        # the harness command without a scope discloses the environment, never the oracle
        harness_command = sighted_test_command(
            runner, executor, ws.root, (), authored=task.authored
        )
        brief = BuildBrief.from_task(
            task,
            mode=mode,
            message=message(task),
            test_command=test_command,
            harness_command=harness_command,
            config=config,
        )
        rung_budget = budget_for_rung(rung, budget)
        try:
            if sealed:
                outcome = sealed_build(ws, task, rung, brief, rung_budget)
            else:
                outcome = builder.build(ws, brief, rung_budget, on_event=builder_on_event)
        except SandboxUnavailable:
            raise  # the run stops (ADR-0005): never a host-side attempt, never a verdict
        except Exception as exc:
            failed = BuildAttempt(
                BuilderRef(
                    name=builder.name,
                    model=builder.model,
                    provider=builder.provider,
                    mode=mode,
                    budget=rung_budget.to_dict(),
                ),
                error=_prefixed(f"builder raised {type(exc).__name__}: ", str(exc)),
            )
            return discard(ws, task, failed)
        labels: dict[str, str] = {}
        if preflight is not None and not outcome.violated and not attempt_error(outcome):
            outcome, labels = run_preflight(
                ws, task, brief, builder, rung, rung_budget, outcome, sealed=sealed
            )
        ref = _write_transcript(tdir, task, rung, outcome) if tdir is not None else ""
        attempt = BuildAttempt(
            outcome.builder_ref(transcript_ref=ref),
            error=attempt_error(outcome),
            transcript_ref=ref,
            labels=labels,
            notes=attempt_notes(outcome),
        )
        return discard(ws, task, attempt)

    def run_preflight(  # noqa: PLR0917 — one step of the build, many collaborators
        ws: Workspace,
        task: TaskSpec,
        brief: BuildBrief,
        builder: Builder,
        rung: Rung,
        rung_budget: Budget,
        outcome: BuildOutcome,
        *,
        sealed: bool,
    ) -> tuple[BuildOutcome, dict[str, str]]:
        """See :class:`Preflight`. Never raises into the grade: a fixer or repair that
        fails leaves the worktree as it is and the record says so."""
        assert preflight is not None
        pf = preflight
        record: dict[str, Any] = {"policy": pf.label, "before": None, "fixers": [], "repair": 0}
        merged = replace(outcome, builder=f"{outcome.builder}+preflight")
        try:
            files = _changed_source_files(ws, config)
            plan = runner.lint_plan(ws.root, executor) if files else None
            if plan is None:
                record["before"] = "no_plan" if files else "no_changed_files"
                return merged, {"preflight": _preflight_label(record)}
            before = run_plan(plan, executor, ws.root, files)
            record["before"] = _verdict(before)
            if before.ok is not False:
                return merged, {"preflight": _preflight_label(record)}
            emit(
                on_event,
                BUILDER_EVENT_PREFIX + "preflight.rejected",
                task=task.task_id,
                note=before.note,
            )
            if pf.fix:
                for name, argv in fix_commands(plan, files):
                    res = executor.run(
                        Command(argv, ws.root, timeout=plan.timeout, writable_paths=(".",))
                    )
                    record["fixers"].append(f"{name}:{res.returncode}")
                after = run_plan(plan, executor, ws.root, files)
                record["after_fix"] = _verdict(after)
                if after.ok is not False:
                    emit(
                        on_event,
                        BUILDER_EVENT_PREFIX + "preflight.fixed",
                        task=task.task_id,
                        fixers=record["fixers"],
                    )
                    return merged, {"preflight": _preflight_label(record)}
                before = after
            if pf.repair_turns > 0:
                findings = "\n".join(
                    f"[{st.tool}] rc={st.rc}\n{st.tail}"
                    for st in before.steps
                    if st.verdict is not True
                )
                repair_brief = replace(brief, repair_note=findings[-4000:])
                repair_budget = Budget(
                    max_turns=min(rung_budget.max_turns, pf.repair_max_turns),
                    max_tool_calls=min(rung_budget.max_tool_calls, pf.repair_max_tool_calls),
                    max_tokens=rung_budget.max_tokens,
                    max_cost_usd=rung_budget.max_cost_usd,
                    wall_clock_s=min(rung_budget.wall_clock_s, pf.repair_wall_clock_s),
                )
                if sealed:
                    # the repair starts from the first attempt's edits, not the bare parent
                    second = sealed_build(
                        ws, task, rung, repair_brief, repair_budget, carry_files=files
                    )
                else:
                    second = builder.build(
                        ws, repair_brief, repair_budget, on_event=builder_on_event
                    )
                record["repair"] = 1
                merged = _merge_outcomes(merged, second)
                if second.violated:
                    record["after_repair"] = "violated"
                    return merged, {"preflight": _preflight_label(record)}
                after = run_plan(plan, executor, ws.root, _changed_source_files(ws, config))
                record["after_repair"] = _verdict(after)
                emit(
                    on_event,
                    BUILDER_EVENT_PREFIX + "preflight.repaired",
                    task=task.task_id,
                    ok=after.ok,
                    cost_usd=second.cost_usd,
                )
        except SandboxUnavailable:
            raise
        except Exception as exc:  # the grade still runs on whatever is in the worktree
            record["error"] = f"{type(exc).__name__}: {exc}"[:200]
            emit(
                on_event,
                BUILDER_EVENT_PREFIX + "preflight.error",
                task=task.task_id,
                error=record["error"],
            )
        return merged, {"preflight": _preflight_label(record)}

    return build


def _verdict(run: Any) -> str:
    return "clean" if run.ok else ("rejected" if run.ok is False else "not_evaluated")


def _preflight_label(record: Mapping[str, Any]) -> str:
    """A compact, greppable label: ``fix=1,repair=1;before=rejected;fix=prettier:0;after_fix=clean``."""
    parts = [str(record.get("policy", "")), f"before={record.get('before')}"]
    if record.get("fixers"):
        parts.append("fix=" + "+".join(record["fixers"]))
    for k in ("after_fix", "after_repair", "error"):
        if record.get(k) is not None:
            parts.append(f"{k}={record[k]}")
    if record.get("repair"):
        parts.append(f"repair={record['repair']}")
    return ";".join(parts)[:300]


def _merge_outcomes(first: BuildOutcome, second: BuildOutcome) -> BuildOutcome:
    """The two calls of a pre-flight repair as ONE attempt: spend, turns and latency
    summed, errors concatenated, the repair's stop reason kept (it ran last)."""
    return replace(
        first,
        attempts=first.attempts + second.attempts,
        turns=first.turns + second.turns,
        tokens_in=first.tokens_in + second.tokens_in,
        tokens_out=first.tokens_out + second.tokens_out,
        tokens_cached=first.tokens_cached + second.tokens_cached,
        cost_usd=first.cost_usd + second.cost_usd,
        latency_s=first.latency_s + second.latency_s,
        errors=tuple(first.errors) + tuple(second.errors),
        stop_reason=second.stop_reason or first.stop_reason,
        done=second.done,
        transcript=tuple(first.transcript) + tuple(second.transcript),
        # an unconfirmed kill on either call is on the merged attempt
        extra={**first.extra, **attempt_notes(second)},
    )


__all__ = [
    "BUILDER_EVENT_PREFIX",
    "EXTRA_CONTAINER",
    "EXTRA_KILL_CONFIRMED",
    "KillUnconfirmedFn",
    "LedgerLike",
    "MessageFn",
    "Preflight",
    "as_run_ledger",
    "attempt_error",
    "attempt_notes",
    "build_fn_for",
    "container_settings_from_env",
    "discard_source_edits",
    "ladder_from_spec",
    "ladder_labels",
    "note_unconfirmed_kills",
    "parse_rung_label",
    "rung_index",
    "sighted_test_command",
    "unconfirmed_kill_error",
]
