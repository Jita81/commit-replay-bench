"""THE belt grader. false-Q1 = 0 by construction.

A trial worktree (the commit's parent + the builder's edits) is graded by
independent, mechanical belts. **Every belt that was evaluated must hold** for
the trial to be credited ``clean`` — the four core belts are always evaluated:

1. ``tests_unmodified`` — every target test file is byte-identical to the real
   commit's version, AND no test-infrastructure file (``conftest.py``,
   ``pytest.ini``, ``jest.config.*``, ``go.mod replace``, ``src/test/resources``,
   ``build.rs`` … — the table in :mod:`crb.core.test_infra`) was added, edited or
   deleted. The oracle is the test *run*, not the test *files*; the builder cannot
   move the goalposts or the ground they stand on.
2. ``target_green``     — the previously-RED target tests now pass.
3. ``no_new_failures``  — nothing else in the belt scope broke, relative to the
   baseline captured at the parent with the tests overlaid.
4. ``source_changed``   — the diff against the parent touches at least one
   non-test file. A green with no source change means the target was never
   truly RED (a build-cache ghost) and is not a legitimate observation.
5. ``repo_lint_clean``  — the repository's OWN formatter/linter accepts the
   changed non-test files (ADR-0011; :mod:`crb.core.lint`). Evaluated only when
   the repository configures one (``RepoConfig.lint`` or the runner's detection:
   ``gofmt``, ``ruff``, ``eslint``/``prettier``/``standard``/``tsc``, ``spotless``/
   ``checkstyle``, ``cargo fmt``/``clippy``); otherwise ``None`` — *not evaluated*,
   which is neither a pass nor a fail. ``False`` (rejected or timed out) is never
   clean; a linter that could not run is a harness error.

The clean rule, exactly: ``clean ⇔ belts 1–4 all True ∧ belt 5 is not False ∧
not disqualified ∧ no error``. :attr:`Belts.evaluated` records which belts a
result carries; the ledger's ``belt_set`` records which belts the apparatus had.

Everything else fails closed:

* a harness error, timeout, or sandbox failure → ``clean=False`` with the error
  recorded — never a silent pass;
* a non-zero belt run whose failures cannot be attributed to test ids
  (compile error, crash) → belt 3 ``False``;
* a malformed oracle (a "test" file with no tests), a tampered test file or a
  touched test-infrastructure file → ``disqualified`` — the observation is
  excluded, not counted either way;
* a worktree whose git view is no longer the harness's (``HEAD`` moved, a
  skip-worktree bit, an edited ``info/exclude`` — :meth:`Workspace.enforce_integrity`)
  → ``disqualified`` with ``dq_reason="worktree integrity: …"``. Independently of
  that check, :meth:`Workspace.touched_files` reads the filesystem against the
  parent tree, so nothing the builder does to git's own views can hide a file
  from belts 1b, 1c or 4.

:class:`GradeResult` enforces the invariant in ``__post_init__``: it is
impossible to construct a ``clean=True`` result with any belt not ``True``.
That is the poka-yoke the whole product rests on.

Modes
-----
* ``sighted`` — the builder saw the target tests (they were overlaid before it
  ran). Belt 1 checks it left them alone.
* ``blind``   — the builder saw only the parent + a description; the held-out
  tests are overlaid *at grade time*. Belt 0 (blind-only): the builder must not
  have touched ANY test file pre-overlay, since overlaying would silently erase
  such an edit.

The test-infrastructure check runs in both modes on the pre-run worktree
(alongside belt 0 in blind mode, alongside the byte-identical check in sighted
mode); the task's own test files are excluded from it because the harness overlays
them and belt 1 already holds them byte-for-byte.

Navigation
----------
What it is:   The grader — the one function (``grade``) that turns a trial worktree into a
              ``GradeResult`` under the belts.
What it does: Evaluates belts 1–5 mechanically against the parent tree and the overlaid oracle;
              credits ``clean`` only when every evaluated belt holds; records harness errors,
              tampering and malformed oracles as non-passes or disqualifications — never a
              silent pass. Grades in ONE posture (ADR-0019): belt 3 subtracts the baseline
              measured there, and a verdict that would blame the builder names a witness run
              there first (``MisattributionViolation`` otherwise) — a red one is an
              ``environment:`` error, never a model failure.
How:          Posture check (spec, context, executor) → integrity check of the git view →
              tamper scan (target tests, test infrastructure, other tests) → the dependency
              closure (belt 1b) → the builder's changes and diff, read before any run →
              target run → belt-scope run → belt 5 plan → the witness → result.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md, docs/adr/0011-repo-lint-belt.md,
              docs/adr/0019-qualification-is-posture-relative.md
Works with:   src/crb/core/workspace.py (the trial tree and its integrity), src/crb/core/lint.py
              (belt 5), src/crb/core/ledger.py (the row a result becomes),
              src/crb/core/runners/base.py (the test runs), src/crb/core/test_infra.py (belt 1's
              infrastructure table)
Tested by:    tests/test_grade.py, tests/test_oracle_controls.py, tests/test_runners_node.py
Touch when:   never for a new repository — configure the runner, belt scope and lint in the
              repo config instead (docs/OPERATOR.md); adding a belt or changing what "clean"
              means needs an ADR and an apparatus bump (docs/EVIDENCE-AND-CLAIMS.md).
Claims:       A clean grade is a mechanical observation under the belts, not mergeability
              (docs/EVIDENCE-AND-CLAIMS.md).

"""

from __future__ import annotations

import time
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from crb.core.deps import ClosureViolation, DepsBinding, TaskDeps
from crb.core.execution import Executor, SandboxUnavailable
from crb.core.lint import LintRun, run_plan
from crb.core.posture import Posture, PostureMismatch
from crb.core.redact import redact_and_cap
from crb.core.runners.base import BaseRunner, TestRun
from crb.core.spec import RepoConfig, TaskSpec
from crb.core.test_infra import infra_sections_changed, matching_rule
from crb.core.workspace import DiffStats, Workspace

if TYPE_CHECKING:  # the record type only; crb.core.qualify imports this module
    from crb.core.qualify import Qualification

MODE_SIGHTED = "sighted"
MODE_BLIND = "blind"
MODES = (MODE_SIGHTED, MODE_BLIND)

#: The four belts every grade evaluates. All must be ``True`` for ``clean``.
CORE_BELT_NAMES: tuple[str, ...] = (
    "tests_unmodified",
    "target_green",
    "no_new_failures",
    "source_changed",
)
#: Belts evaluated only when the repository provides the instrument (belt 5: a
#: configured or detected linter). ``None`` = not evaluated; ``False`` is never clean.
OPTIONAL_BELT_NAMES: tuple[str, ...] = ("repo_lint_clean",)
#: Every belt, in belt order (1–5). The ledger's ``belt_set`` says how many a row
#: recorded: ``v3-legacy`` the first three, ``v4`` the first four, ``v5`` all five.
BELT_NAMES: tuple[str, ...] = (*CORE_BELT_NAMES, *OPTIONAL_BELT_NAMES)

EventFn = Callable[[str, Mapping[str, Any]], None]


class FalseQ1Violation(AssertionError):
    """Raised if anything tries to construct a clean grade with a failed belt."""


class MisattributionViolation(AssertionError):
    """Raised if anything tries to blame the model without a witness (ADR-0019 §5): a
    grade whose belts fail the builder's patch must name the control, run in the same
    posture on a tree the builder never touched, that makes the blame true."""


#: The witnesses a blamed verdict may name (``labels.blame_control`` on its row):
#: ``gold_green`` — the gold tree passed the scope the trial failed, now, in this posture;
#: ``env_probe`` — a factory item (no gold): the environment probe passed on a fresh base
#: tree; ``no_source`` — no source file changed (a fact about the diff, no control);
#: ``lint_gold_ok`` — only belt 5 failed and the gold passed belt 5 at qualification.
BLAME_GOLD_GREEN = "gold_green"
BLAME_ENV_PROBE = "env_probe"
BLAME_NO_SOURCE = "no_source"
BLAME_LINT_GOLD_OK = "lint_gold_ok"
BLAME_CONTROLS: tuple[str, ...] = (
    BLAME_GOLD_GREEN,
    BLAME_ENV_PROBE,
    BLAME_NO_SOURCE,
    BLAME_LINT_GOLD_OK,
)
#: A blamed grade made with no witness at all (the negative controls, ``crb grade
#: --adhoc``). Allowed on a ``GradeResult``; the ledger refuses it on a model-failure row.
BLAME_UNWITNESSED = "unwitnessed"

#: The prefix of the error a grade records when the posture, not the patch, failed —
#: the unchanged failure-kind rule reads it as ``harness`` (ADR-0019 §5).
ENVIRONMENT_PREFIX = "environment:"
#: ``labels.env_code`` of a trial whose gold control was red in its own posture.
ENV_CODE_GOLD_CONTROL_RED = "GOLD_CONTROL_RED"
#: ``labels.env_code`` of a lint-only failure whose gold also failed belt 5.
ENV_CODE_GOLD_LINT = "GOLD_LINT_RED"
#: ``labels.env_code`` of a trial whose test run could not be given its ground.
ENV_CODE_TEST_RUN = "TEST_RUN_ENVIRONMENT"


@dataclass(frozen=True)
class ControlRun:
    """One control run by a :class:`Witness`: which witness (``kind`` — a
    :data:`BLAME_CONTROLS` name), the scope, whether it witnessed (``green``), and what
    the toolchain said. ``failing`` / ``timed_out`` / ``parse_error`` say why a red one
    was red."""

    kind: str
    scope: tuple[str, ...]
    green: bool
    rc: int = 0
    tail: str = ""
    duration_s: float = 0.0
    failing: tuple[str, ...] = ()
    timed_out: bool = False
    parse_error: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope", tuple(self.scope))
        object.__setattr__(self, "failing", tuple(sorted(self.failing)))
        object.__setattr__(self, "tail", redact_and_cap(self.tail, max_chars=2000))

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "scope": list(self.scope),
            "green": self.green,
            "rc": self.rc,
            "tail": self.tail,
            "duration_s": round(self.duration_s, 3),
            "failing": list(self.failing[:50]),
            "timed_out": self.timed_out,
            "parse_error": self.parse_error,
        }


class Witness(Protocol):
    """Runs a control NOW, in the trial's posture, on a tree the builder never touched.

    ``allow_failing`` is ``None`` for a target control (green means the run is green) and
    the in-posture baseline for a belt-scope control (green means the run is attributable
    and nothing outside the baseline fails)."""

    def control(
        self, scope: Sequence[str], *, why: str, allow_failing: Collection[str] | None = None
    ) -> ControlRun: ...


@dataclass(frozen=True)
class GradeContext:
    """What a grade needs besides the tree (ADR-0019 §4): the posture it grades in, the
    task's qualification in that posture, the task's dependency bindings, and the witness
    that runs a control when a verdict would blame the model. ``witness=None`` grades
    unwitnessed (the negative controls, ``crb grade --adhoc``) — never a ledger row that
    blames the model."""

    posture: Posture
    qualification: Qualification
    deps: TaskDeps
    witness: Witness | None = None

    def spec(self, task: TaskSpec) -> TaskSpec:
        """The spec to grade ``task`` against: the qualification's projection."""
        return self.qualification.project(task)


@dataclass(frozen=True)
class Belts:
    """The belt values of one grade. ``None`` is *not evaluated*: for a core belt
    that means the grade stopped earlier (never clean); for ``repo_lint_clean`` it
    means the repository has no linter to run (clean is still possible)."""

    tests_unmodified: bool | None = None
    target_green: bool | None = None
    no_new_failures: bool | None = None
    source_changed: bool | None = None
    repo_lint_clean: bool | None = None

    @property
    def all_true(self) -> bool:
        """The clean predicate over the belts: every core belt ``True`` and no
        evaluated optional belt ``False``."""
        return all(getattr(self, b) is True for b in CORE_BELT_NAMES) and all(
            getattr(self, b) is not False for b in OPTIONAL_BELT_NAMES
        )

    @property
    def evaluated(self) -> tuple[str, ...]:
        """The belts this grade actually evaluated (value not ``None``), in belt order."""
        return tuple(b for b in BELT_NAMES if getattr(self, b) is not None)

    def to_dict(self) -> dict[str, bool | None]:
        return {b: getattr(self, b) for b in BELT_NAMES}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Belts:
        return cls(**{b: d.get(b) for b in BELT_NAMES})


@dataclass(frozen=True)
class GradeResult:
    task_id: str
    repo: str
    mode: str
    clean: bool
    belts: Belts
    disqualified: bool = False
    dq_reason: str = ""
    error: str = ""
    note: str = ""
    new_failures: tuple[str, ...] = ()
    tamper_files: tuple[str, ...] = ()
    changed_files: tuple[str, ...] = ()
    diff: DiffStats | None = None
    target_run: TestRun | None = None
    belt_run: TestRun | None = None
    lint_run: LintRun | None = None
    duration_s: float = 0.0
    extra: Mapping[str, Any] = field(default_factory=dict)
    #: The posture stamp (ADR-0019): where this grade ran and which qualification it
    #: subtracted. Empty only on a result built by hand (a test, an import).
    posture_id: str = ""
    posture_class: str = ""
    qualification_id: str = ""
    #: The witness that makes a blamed verdict true (:data:`BLAME_CONTROLS`), or
    #: :data:`BLAME_UNWITNESSED`; empty when nothing is blamed.
    blame_control: str = ""
    #: The control run behind ``blame_control`` (or behind an environment error).
    control: ControlRun | None = None
    #: Why an ``environment:`` error was recorded (``GOLD_CONTROL_RED`` …); else empty.
    env_code: str = ""

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if self.clean and not (self.belts.all_true and not self.disqualified and not self.error):
            raise FalseQ1Violation(
                f"refusing to construct a clean grade for {self.task_id[:10]} with belts="
                f"{self.belts.to_dict()} disqualified={self.disqualified} error={self.error!r}"
            )
        if self.blame_control and self.blame_control not in (*BLAME_CONTROLS, BLAME_UNWITNESSED):
            raise ValueError(
                f"blame_control must be one of {(*BLAME_CONTROLS, BLAME_UNWITNESSED)}, "
                f"got {self.blame_control!r}"
            )
        if self.blamed and not self.blame_control:
            raise MisattributionViolation(
                f"refusing to construct a grade for {self.task_id[:10]} that blames the builder "
                f"(belts={self.belts.to_dict()}) without naming its witness"
            )
        object.__setattr__(self, "extra", dict(self.extra))

    @property
    def blamed(self) -> bool:
        """The verdict charges the builder's patch: not clean, not disqualified, no error,
        and belt 2, 3, 4 or 5 evaluated ``False``."""
        b = self.belts
        return (
            not self.clean
            and not self.disqualified
            and not self.error
            and any(
                v is False
                for v in (b.target_green, b.no_new_failures, b.source_changed, b.repo_lint_clean)
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "repo": self.repo,
            "mode": self.mode,
            "clean": self.clean,
            **self.belts.to_dict(),
            "disqualified": self.disqualified,
            "dq_reason": self.dq_reason,
            "error": self.error,
            "note": self.note,
            "new_failures": list(self.new_failures),
            "tamper_files": list(self.tamper_files),
            "changed_files": list(self.changed_files),
            "diff": self.diff.to_dict() if self.diff else None,
            "target_run": self.target_run.to_dict() if self.target_run else None,
            "belt_run": self.belt_run.to_dict() if self.belt_run else None,
            "lint_run": self.lint_run.to_dict() if self.lint_run else None,
            "duration_s": round(self.duration_s, 3),
            "extra": dict(self.extra),
            # present iff set: a result without a posture hashes as it always did
            **({"posture_id": self.posture_id} if self.posture_id else {}),
            **({"posture_class": self.posture_class} if self.posture_class else {}),
            **({"qualification_id": self.qualification_id} if self.qualification_id else {}),
            **({"blame_control": self.blame_control} if self.blame_control else {}),
            **({"control": self.control.to_dict()} if self.control is not None else {}),
            **({"env_code": self.env_code} if self.env_code else {}),
        }


def derive_clean(belts: Mapping[str, Any], *, disqualified: bool = False, error: str = "") -> bool:
    """The clean rule, exposed so imported/legacy rows can be re-derived and audited:
    every core belt ``True``, no optional belt ``False`` (absent = not evaluated),
    not disqualified, no error."""
    return (
        all(belts.get(b) is True for b in CORE_BELT_NAMES)
        and all(belts.get(b) is not False for b in OPTIONAL_BELT_NAMES)
        and not disqualified
        and not error
    )


def _emit(on_event: EventFn | None, action: str, **payload: Any) -> None:
    if on_event is not None:
        on_event(action, payload)


def infra_tampered(
    ws: Workspace, touched: Sequence[str], *, exclude: Iterable[str], config: RepoConfig
) -> list[str]:
    """Touched files that are test infrastructure for ``config``'s language + runner.

    ``exclude`` is the task's own test files (overlaid by the harness, held
    byte-for-byte by belt 1a). A section-aware file (``pyproject.toml``…) counts
    only when its oracle-relevant sections differ between the parent and the
    worktree; an absent side is the empty document. Sorted, for stable evidence.
    """
    skip = set(exclude)
    language, runner = config.language.value, config.runner
    out: list[str] = []
    for rel in touched:
        if rel in skip:
            continue
        rule = matching_rule(rel, language, runner=runner)
        if rule is None:
            continue
        if rule.partial:
            before = ws.parent_text(rel) or ""
            after = ws.read(rel) if ws.exists(rel) else ""
            if not infra_sections_changed(rel, before, after, language, runner=runner):
                continue
        out.append(rel)
    return sorted(out)


def _redacted(run: TestRun | None) -> TestRun | None:
    if run is None:
        return None
    return TestRun(
        run.returncode,
        run.failing,
        redact_and_cap(run.tail),
        run.timed_out,
        run.duration_s,
        run.parse_error,
        run.services,  # which service instance the oracle ran against (C15)
        run.env_error,
    )


def check_posture(task: TaskSpec, ctx: GradeContext, executor: Executor) -> None:
    """Raise :class:`PostureMismatch` unless the spec, the context and the executor name
    ONE posture and ONE qualification (ADR-0019 §4). Nothing runs before this holds."""
    q = ctx.qualification
    problems = []
    if not task.posture_id or not task.qualification_ref:
        problems.append("the spec was not projected from a qualification")
    if task.posture_id != ctx.posture.posture_id:
        problems.append(f"spec posture {task.posture_id or '-'} ≠ context {ctx.posture.posture_id}")
    if q.posture_id != ctx.posture.posture_id:
        problems.append(f"qualification posture {q.posture_id} ≠ context {ctx.posture.posture_id}")
    if task.qualification_ref != q.qualification_id:
        problems.append(
            f"spec qualification {task.qualification_ref[:12] or '-'} ≠ context "
            f"{q.qualification_id[:12]}"
        )
    if q.task_id != task.task_id:
        problems.append(f"qualification is for {q.task_id[:10]}, not {task.task_id[:10]}")
    if ctx.posture.executor != executor.name:
        problems.append(f"context executor {ctx.posture.executor} ≠ {executor.name}")
    if problems:
        raise PostureMismatch(
            f"posture mismatch for {task.task_id[:10]}: "
            + "; ".join(problems)
            + " — nothing was graded (qualify the task in this posture)"
        )


def grade(
    ws: Workspace,
    task: TaskSpec,
    *,
    ctx: GradeContext,
    config: RepoConfig,
    runner: BaseRunner,
    executor: Executor,
    mode: str = MODE_SIGHTED,
    timeout: int = 0,
    on_event: EventFn | None = None,
    evaluate_lint: bool = True,
) -> GradeResult:
    """Grade the trial worktree ``ws`` for ``task``. Never raises for a test failure;
    raises :class:`SandboxUnavailable` (infrastructure) so the run can stop — and
    :class:`PostureMismatch` (one) before anything runs when ``task`` was not projected
    from ``ctx``'s qualification or ``ctx`` names another executor (ADR-0019 §4).

    ``ctx`` is required: belt 3 subtracts the qualification's baseline (the one measured
    in this posture), every test run gets the task's dependency binding, and a verdict
    that would blame the builder asks ``ctx.witness`` for a control first (§5) — a red
    control turns it into ``error="environment: …"`` (the rule reads ``harness``).

    ``evaluate_lint=False`` leaves belt 5 *not evaluated* (``None``, recorded as such)
    whatever the repository configures. The negative controls use it: they measure
    the four ORACLE belts (ADR-0010) with synthetic edits that are not written in the
    repository's style, so a control's verdict must not turn on the formatter — an
    oracle escape would otherwise read as a lint rejection, and a gold commit that
    predates the repo's linter as an instrument bug. Every builder trial keeps the
    default.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    check_posture(task, ctx, executor)
    started = time.monotonic()
    belts = Belts()
    kw: dict[str, Any] = {
        "task_id": task.task_id,
        "repo": task.repo,
        "mode": mode,
        "posture_id": ctx.posture.posture_id,
        "posture_class": ctx.posture.posture_class,
        "qualification_id": ctx.qualification.qualification_id,
    }
    baseline = ctx.qualification.baseline  # the in-posture union, never the discovery set

    def environment(run: TestRun, **changes: Any) -> GradeResult:
        """The test run could not be given its ground: an environment failure, never a
        verdict about the patch."""
        _emit(on_event, "grade.environment", task=task.task_id, env_error=run.env_error)
        return done(
            error=redact_and_cap(f"{ENVIRONMENT_PREFIX} {run.env_error}", max_chars=2000),
            env_code=ENV_CODE_TEST_RUN,
            **changes,
        )

    def witness(
        scope: Sequence[str], *, why: str, allow_failing: Collection[str] | None
    ) -> dict[str, Any]:
        """Ask the context's witness for a control; the fields the result carries."""
        if ctx.witness is None:
            return {"blame_control": BLAME_UNWITNESSED}
        run = ctx.witness.control(scope, why=why, allow_failing=allow_failing)
        _emit(
            on_event,
            "grade.control",
            task=task.task_id,
            kind=run.kind,
            why=why,
            green=run.green,
            rc=run.rc,
            duration_s=round(run.duration_s, 3),
        )
        if run.green:
            return {"blame_control": run.kind, "control": run}
        tail = redact_and_cap(run.tail or run.parse_error, max_chars=600)
        return {
            "error": redact_and_cap(
                f"{ENVIRONMENT_PREFIX} gold control red in {ctx.posture.posture_id}: {why}: {tail}",
                max_chars=2000,
            ),
            "env_code": ENV_CODE_GOLD_CONTROL_RED,
            "control": run,
            "extra": {"control": run.to_dict()},
        }

    def done(**changes: Any) -> GradeResult:
        merged: dict[str, Any] = {
            "clean": False,
            "belts": belts,
            "duration_s": time.monotonic() - started,
        }
        merged.update(kw)
        merged.update(changes)
        merged["target_run"] = _redacted(merged.get("target_run"))
        merged["belt_run"] = _redacted(merged.get("belt_run"))
        return GradeResult(**merged)

    try:
        # --- pre-flight (both modes): the worktree's git view is still the harness's.
        #     HEAD is the parent, the gitdir is the clone's, no index entry carries a
        #     skip-worktree / assume-unchanged bit, and the shared info/exclude holds
        #     only what the harness wrote (anything else is removed and reported). The
        #     independent review pass (2026-09-14, finding 1) graded a hidden
        #     conftest.py clean by each of these routes. A violation is a DQ, never a
        #     verdict — and touched_files() below reads the tree, not git's views, so
        #     the check is a belt over the ground, not the only thing holding it. ----
        violations = ws.enforce_integrity()
        if violations:
            files = sorted({f for v in violations for f in v.files})
            _emit(
                on_event,
                "grade.tamper",
                task=task.task_id,
                files=files[:10],
                kind="worktree",
                violations=[v.to_dict() for v in violations][:10],
            )
            belts = Belts(tests_unmodified=False)
            return done(
                disqualified=True,
                dq_reason="worktree integrity: " + "; ".join(v.detail for v in violations)[:500],
                tamper_files=tuple(files[:50]),
            )

        # --- belt 1b (both modes, pre-run): no test-infrastructure file touched ---
        touched_pre = ws.touched_files()
        infra = infra_tampered(ws, touched_pre, exclude=task.test_files, config=config)
        if infra:
            _emit(on_event, "grade.tamper", task=task.task_id, files=infra[:10], kind="test_infra")

        # --- belt 0 (blind only): no test file touched before the oracle lands ---
        if mode == MODE_BLIND:
            tampered = [f for f in touched_pre if f in task.test_files or config.is_test(f)]
            if tampered:
                _emit(on_event, "grade.tamper", task=task.task_id, files=tampered[:10])
                belts = Belts(tests_unmodified=False)
                return done(
                    disqualified=True,
                    dq_reason="blind: builder modified test files pre-overlay",
                    tamper_files=tuple(sorted(set(tampered) | set(infra))[:50]),
                )
            if infra:
                belts = Belts(tests_unmodified=False)
                return done(
                    disqualified=True,
                    dq_reason=f"test infrastructure modified: {infra[:5]}",
                    tamper_files=tuple(infra[:50]),
                )
            ws.overlay_tests(task.test_files)

        # --- oracle validity (poka-yoke: a non-test file is never an oracle) -----
        # the oracle is the TARGET set; a support file overlaid with the tests (a mock
        # server, a helpers module) defines no test and is not required to
        targets = set(task.target_tests)
        file_targets = bool(targets) and targets <= set(task.test_files)  # pytest/jest style
        bad = [
            t
            for t in task.test_files
            if (t in targets or not file_targets) and not runner.is_valid_oracle(ws.root, t)
        ]
        if bad:
            _emit(on_event, "grade.malformed_oracle", task=task.task_id, files=bad)
            return done(disqualified=True, dq_reason=f"malformed oracle: {bad[:5]}")

        # --- belt 1c (both modes): no OTHER test file in the repo's test layout touched.
        #     A neighbouring test rewritten to `assert True` hides a regression from belt 3
        #     while the target stays byte-identical — the human-review-guide exercise 3b
        #     graded exactly that clean (2026-09-14). The harness's own overlays are the
        #     task's test files and are excluded; everything else under the test layout
        #     is the oracle's neighbourhood and is off-limits to the builder. ----------
        infra_set = set(infra)  # infra files take the more specific belt-1b reason below
        others = sorted(
            f
            for f in touched_pre
            if f not in task.test_files
            and f not in infra_set
            and config.is_test(f)
            and not ws.harness_unchanged(f)
        )
        if others:
            _emit(
                on_event, "grade.tamper", task=task.task_id, files=others[:10], kind="other_tests"
            )
            belts = Belts(tests_unmodified=False)
            return done(
                disqualified=True,
                dq_reason=f"non-target test files modified: {others[:5]}",
                tamper_files=tuple(sorted(set(others) | set(infra))[:50]),
            )

        # --- belt 1: target tests byte-identical to the commit's own, AND no test
        #     infrastructure touched (1b above). Both must hold. ---------------------
        ok, offending = ws.tests_byte_identical(task.test_files)
        belts = Belts(tests_unmodified=ok and not infra)
        _emit(
            on_event,
            "grade.belt",
            task=task.task_id,
            belt="tests_unmodified",
            value=belts.tests_unmodified,
        )
        if not ok:
            return done(
                disqualified=True,
                dq_reason="target test file modified — disqualified",
                tamper_files=tuple([*offending, *infra][:50]),
            )
        if infra:
            return done(
                disqualified=True,
                dq_reason=f"test infrastructure modified: {infra[:5]}",
                tamper_files=tuple(infra[:50]),
            )

        # --- belt 1b in a provisioned posture: the trial's own manifests select no
        #     dependency outside the task's closure (ADR-0019 §6). A trial that moved the
        #     oracle's ground is disqualified — never credited, never charged. ----------
        try:
            binding: DepsBinding = ctx.deps.binding_for(ws.root)
        except ClosureViolation as cv:
            _emit(on_event, "grade.tamper", task=task.task_id, kind="closure", detail=cv.detail)
            belts = Belts(tests_unmodified=False)
            return done(disqualified=True, dq_reason=f"dependency closure: {cv.detail}"[:500])

        # --- the builder's changes as they stood BEFORE the first test ran: belts 4 and
        #     5 and the diff read these, so a file a test writes is never the builder's
        #     (ADR-0019 §7; the 2026-09-25 finding D5). -------------------------------
        changed = [f for f in touched_pre if f not in task.test_files and not config.is_test(f)]
        diff = ws.diff_stats(exclude=task.test_files)

        # --- belt 2: target green -------------------------------------------------
        target_run = runner.run_for(
            executor,
            ws.root,
            task.target_tests,
            timeout=timeout,
            authored=task.authored,
            deps=binding,
        )
        if target_run.env_error:
            belts = Belts(tests_unmodified=True)
            return environment(target_run, target_run=target_run)
        belts = Belts(tests_unmodified=True, target_green=target_run.green)
        _emit(
            on_event,
            "grade.belt",
            task=task.task_id,
            belt="target_green",
            value=target_run.green,
            rc=target_run.returncode,
            timed_out=target_run.timed_out,
        )
        if not target_run.green:
            note = (
                "target timed out"
                if target_run.timed_out
                else f"target not green (rc={target_run.returncode})"
            )
            return done(
                target_run=target_run,
                note=note,
                diff=diff,
                changed_files=tuple(changed[:200]),
                **witness(task.target_tests, why="belt 2: target not green", allow_failing=None),
            )

        # --- belt 3: no new failures vs the IN-POSTURE baseline ---------------------
        belt_run = runner.run_for(
            executor,
            ws.root,
            task.belt_scope,
            timeout=timeout,
            authored=task.authored,
            deps=binding,
        )
        if belt_run.env_error:
            belts = Belts(tests_unmodified=True, target_green=True)
            return environment(belt_run, target_run=target_run, belt_run=belt_run)
        if belt_run.timed_out or belt_run.parse_error:
            no_new = False
            new: set[str] = set()
            note = (
                "belt run timed out"
                if belt_run.timed_out
                else f"belt run unattributed: {belt_run.parse_error}"
            )
        else:
            new = set(belt_run.failing) - baseline
            no_new = not new
            note = "" if no_new else f"{len(new)} new failure(s)"
        belts = Belts(tests_unmodified=True, target_green=True, no_new_failures=no_new)
        _emit(
            on_event,
            "grade.belt",
            task=task.task_id,
            belt="no_new_failures",
            value=no_new,
            new=sorted(new)[:20],
        )

        # --- belt 4: source actually changed (read before the first run) ------------
        source_changed = bool(changed)
        belts = Belts(
            tests_unmodified=True,
            target_green=True,
            no_new_failures=no_new,
            source_changed=source_changed,
        )
        _emit(
            on_event, "grade.belt", task=task.task_id, belt="source_changed", value=source_changed
        )
        if not source_changed and not note:
            note = "green with no source change — target was not truly RED at the parent"

        # --- belt 5: the repository's own formatter/linter accepts the changed files.
        #     Evaluated only when the repo configures one (else None: not a pass, not a
        #     fail). Deleted files cannot be linted; a tool that cannot run is a harness
        #     error, never a verdict (ADR-0011). --------------------------------------
        lint_run: LintRun | None = None
        lint_error = ""
        plan = runner.lint_plan(ws.root, executor) if evaluate_lint else None
        if plan is not None:
            present = [f for f in changed if ws.exists(f)]
            # the plan's own wall clock (RepoConfig.lint.timeout or the lint default)
            # governs; the test-run timeout is a different budget
            lint_run = run_plan(plan, executor, ws.root, present)
            _emit(
                on_event,
                "grade.belt",
                task=task.task_id,
                belt="repo_lint_clean",
                value=lint_run.ok,
                detected=lint_run.detected,
                note=lint_run.note,
            )
            if lint_run.error:
                lint_error = f"lint: {lint_run.error}"
            elif lint_run.ok is False and not note:
                note = f"lint: {lint_run.note}"
        belts = Belts(
            tests_unmodified=True,
            target_green=True,
            no_new_failures=no_new,
            source_changed=source_changed,
            repo_lint_clean=lint_run.ok if lint_run is not None else None,
        )

        clean = belts.all_true and not lint_error
        blame: dict[str, Any] = {}
        if not clean and not lint_error:
            if no_new is False:
                blame = witness(task.belt_scope, why="belt 3: new failures", allow_failing=baseline)
            elif source_changed is False:
                blame = {"blame_control": BLAME_NO_SOURCE}
            elif belts.repo_lint_clean is False:
                if ctx.qualification.gold.get("lint") is False:
                    # a qualified gold never fails belt 5; a context that says it did cannot
                    # make the builder's lint rejection a witnessed one
                    blame = {
                        "error": f"{ENVIRONMENT_PREFIX} the gold failed belt 5 at qualification",
                        "env_code": ENV_CODE_GOLD_LINT,
                    }
                else:
                    blame = {"blame_control": BLAME_LINT_GOLD_OK}
        final: dict[str, Any] = {
            "clean": clean,
            "note": note,
            "error": lint_error,
            "new_failures": tuple(sorted(new)[:50]),
            "changed_files": tuple(changed[:200]),
            "diff": diff,
            "target_run": target_run,
            "belt_run": belt_run,
            "lint_run": lint_run,
        }
        final.update(blame)
        return done(**final)
    except SandboxUnavailable:
        raise
    except Exception as exc:  # every harness error is a recorded non-pass
        # Redacted BEFORE the callback: the StepEvent envelope redacts too, but the raw
        # ``on_event`` seam may be any callable (a debug sink), so nothing raw leaves here.
        error = redact_and_cap(f"{type(exc).__name__}: {exc}", max_chars=2000)
        _emit(on_event, "grade.error", task=task.task_id, error=error)
        return done(error=error)
