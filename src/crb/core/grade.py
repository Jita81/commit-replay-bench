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
              silent pass.
How:          Integrity check of the git view → tamper scan (target tests, test infrastructure,
              other tests) → target run → belt-scope run → diff stats → belt 5 plan → result.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0001-four-belts-and-false-q1-at-write.md, docs/adr/0011-repo-lint-belt.md
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
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from crb.core.execution import Executor, SandboxUnavailable
from crb.core.lint import LintRun, run_plan
from crb.core.redact import redact_and_cap
from crb.core.runners.base import BaseRunner, TestRun
from crb.core.spec import RepoConfig, TaskSpec
from crb.core.test_infra import infra_sections_changed, matching_rule
from crb.core.workspace import DiffStats, Workspace

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

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if self.clean and not (self.belts.all_true and not self.disqualified and not self.error):
            raise FalseQ1Violation(
                f"refusing to construct a clean grade for {self.task_id[:10]} with belts="
                f"{self.belts.to_dict()} disqualified={self.disqualified} error={self.error!r}"
            )
        object.__setattr__(self, "extra", dict(self.extra))

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
    )


def grade(
    ws: Workspace,
    task: TaskSpec,
    *,
    config: RepoConfig,
    runner: BaseRunner,
    executor: Executor,
    mode: str = MODE_SIGHTED,
    timeout: int = 0,
    on_event: EventFn | None = None,
    evaluate_lint: bool = True,
) -> GradeResult:
    """Grade the trial worktree ``ws`` for ``task``. Never raises for a test failure;
    raises :class:`SandboxUnavailable` (infrastructure) so the run can stop.

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
    started = time.monotonic()
    belts = Belts()
    kw: dict[str, Any] = {"task_id": task.task_id, "repo": task.repo, "mode": mode}

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

        # --- belt 2: target green -------------------------------------------------
        target_run = runner.run_for(
            executor, ws.root, task.target_tests, timeout=timeout, authored=task.authored
        )
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
            return done(target_run=target_run, note=note)

        # --- belt 3: no new failures vs baseline ----------------------------------
        belt_run = runner.run_for(
            executor, ws.root, task.belt_scope, timeout=timeout, authored=task.authored
        )
        if belt_run.timed_out or belt_run.parse_error:
            no_new = False
            new: set[str] = set()
            note = (
                "belt run timed out"
                if belt_run.timed_out
                else f"belt run unattributed: {belt_run.parse_error}"
            )
        else:
            new = set(belt_run.failing) - set(task.baseline_failing)
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

        # --- belt 4: source actually changed --------------------------------------
        touched = ws.touched_files()
        changed = [f for f in touched if f not in task.test_files and not config.is_test(f)]
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

        diff = ws.diff_stats(exclude=task.test_files)
        clean = belts.all_true and not lint_error
        return done(
            clean=clean,
            note=note,
            error=lint_error,
            new_failures=tuple(sorted(new)[:50]),
            changed_files=tuple(changed[:200]),
            diff=diff,
            target_run=target_run,
            belt_run=belt_run,
            lint_run=lint_run,
        )
    except SandboxUnavailable:
        raise
    except Exception as exc:  # every harness error is a recorded non-pass
        _emit(on_event, "grade.error", task=task.task_id, error=f"{type(exc).__name__}: {exc}")
        return done(error=redact_and_cap(f"{type(exc).__name__}: {exc}", max_chars=2000))
