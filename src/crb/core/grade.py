"""THE four-belt grader. false-Q1 = 0 by construction.

A trial worktree (the commit's parent + the builder's edits) is graded by four
independent, mechanical belts. **All four must hold** for the trial to be
credited ``clean``:

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

Everything else fails closed:

* a harness error, timeout, or sandbox failure → ``clean=False`` with the error
  recorded — never a silent pass;
* a non-zero belt run whose failures cannot be attributed to test ids
  (compile error, crash) → belt 3 ``False``;
* a malformed oracle (a "test" file with no tests), a tampered test file or a
  touched test-infrastructure file → ``disqualified`` — the observation is
  excluded, not counted either way.

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
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from crb.core.execution import Executor, SandboxUnavailable
from crb.core.redact import redact_and_cap
from crb.core.runners.base import BaseRunner, TestRun
from crb.core.spec import RepoConfig, TaskSpec
from crb.core.test_infra import infra_sections_changed, matching_rule
from crb.core.workspace import DiffStats, Workspace

MODE_SIGHTED = "sighted"
MODE_BLIND = "blind"
MODES = (MODE_SIGHTED, MODE_BLIND)

BELT_NAMES: tuple[str, ...] = (
    "tests_unmodified",
    "target_green",
    "no_new_failures",
    "source_changed",
)

EventFn = Callable[[str, Mapping[str, Any]], None]


class FalseQ1Violation(AssertionError):
    """Raised if anything tries to construct a clean grade with a failed belt."""


@dataclass(frozen=True)
class Belts:
    tests_unmodified: bool | None = None
    target_green: bool | None = None
    no_new_failures: bool | None = None
    source_changed: bool | None = None

    @property
    def all_true(self) -> bool:
        return all(getattr(self, b) is True for b in BELT_NAMES)

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
            "duration_s": round(self.duration_s, 3),
            "extra": dict(self.extra),
        }


def derive_clean(belts: Mapping[str, Any], *, disqualified: bool = False, error: str = "") -> bool:
    """The clean rule, exposed so imported/legacy rows can be re-derived and audited."""
    return all(belts.get(b) is True for b in BELT_NAMES) and not disqualified and not error


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
) -> GradeResult:
    """Grade the trial worktree ``ws`` for ``task``. Never raises for a test failure;
    raises :class:`SandboxUnavailable` (infrastructure) so the run can stop."""
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
        bad = [t for t in task.test_files if not runner.is_valid_oracle(ws.root, t)]
        if bad:
            _emit(on_event, "grade.malformed_oracle", task=task.task_id, files=bad)
            return done(disqualified=True, dq_reason=f"malformed oracle: {bad[:5]}")

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
        target_run = runner.run(executor, ws.root, task.target_tests, timeout=timeout)
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
        belt_run = runner.run(executor, ws.root, task.belt_scope, timeout=timeout)
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

        diff = ws.diff_stats(exclude=task.test_files)
        clean = belts.all_true
        return done(
            clean=clean,
            note=note,
            new_failures=tuple(sorted(new)[:50]),
            changed_files=tuple(changed[:200]),
            diff=diff,
            target_run=target_run,
            belt_run=belt_run,
        )
    except SandboxUnavailable:
        raise
    except Exception as exc:  # every harness error is a recorded non-pass
        _emit(on_event, "grade.error", task=task.task_id, error=f"{type(exc).__name__}: {exc}")
        return done(error=redact_and_cap(f"{type(exc).__name__}: {exc}", max_chars=2000))
