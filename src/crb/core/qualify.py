"""Qualification: a task's oracle, proven in the posture that will grade it (ADR-0019 §2).

A task mined on the host carries three facts — its target was RED at the parent, its
baseline failing set, and that the humans' own patch (the gold) passes — measured by
whatever instrument the mine ran with. The 2026-09-25 finding showed those facts do not
travel: in the sealed sandbox the same target failed to BUILD (no module cache, no
network) and a test that passed on the host failed (a read-only tree), so a replay that
trusted the host's facts charged the model for both.

A :class:`Qualification` is those facts measured again, per task and per posture, for no
model money, and kept as an append-only record: the latest row for a repository, task
and posture is the one in force, and a revocation is a new row. The grader never reads
the discovery values on :class:`~crb.core.spec.TaskSpec` again —
:meth:`Qualification.project` hands the replay path a spec whose baseline and gold fields
are the qualification's and which carries the posture stamp ``grade()`` checks.

Navigation
----------
What it is:   The qualification record, its states and refusal codes, and the projection the
              replay path grades against.
What it does: Holds, for one task in one posture, the state and any refusal code with its
              fix, the dependency bindings, the environment probe, the kind of RED, the
              two-run baseline (union and flaky set), the gold's facts, a fingerprint of what
              the oracle rests on, and how it differs from the task's other postures.
How:          A frozen dataclass with ``to_dict`` / ``from_dict``; ``fingerprint_of`` is a
              SHA-256 over the oracle-relevant facts only; ``project`` returns a
              ``TaskSpec`` via ``TaskSpec.with_``.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0019-qualification-is-posture-relative.md
Works with:   src/crb/core/posture.py (the posture a record is keyed to), src/crb/core/spec.py
              (the ``TaskSpec`` a record projects), src/crb/core/deps.py (the bindings a
              record carries), src/crb/core/mine.py (discovers the tasks this qualifies),
              src/crb/core/evidence.py (canonical JSON, timestamps)
Tested by:    tests/test_qualify.py
Touch when:   a fact the oracle rests on joins the record (add it to the fingerprint too);
              a refusal code is added (``QUAL_TEXT`` and ADR-0019's table together).
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crb.core.deps import (
    DEPS_MODE_SEALED,
    HOST_ENV_DEPS,
    NO_DEPS,
    REFUSAL_TEXT,
    SCOPE_RUN,
    DepsBinding,
    DepsProvider,
    ProvisionRefused,
    TaskDeps,
)
from crb.core.evidence import canonical_json, sha256_text, utc_now_iso
from crb.core.execution import Executor
from crb.core.git import GitRepo
from crb.core.grade import BLAME_ENV_PROBE, BLAME_GOLD_GREEN, ControlRun, GradeContext, Witness
from crb.core.lint import run_plan
from crb.core.posture import Posture, PostureMismatch
from crb.core.redact import redact_and_cap
from crb.core.runners.base import BaseRunner, TestRun, tail_of, with_deps
from crb.core.spec import RepoConfig, TaskSpec
from crb.core.version import APPARATUS_VERSION, __version__
from crb.core.workspace import Workspace

STATE_QUALIFIED = "qualified"
STATE_UNQUALIFIED = "unqualified"
STATE_REVOKED = "revoked"
STATE_LEGACY = "legacy"
STATES: tuple[str, ...] = (STATE_QUALIFIED, STATE_UNQUALIFIED, STATE_REVOKED, STATE_LEGACY)

#: RED kinds: failing test ids were parsed, or the target did not build (accepted only
#: after an environment probe proved the posture can load the parent's dependencies).
RED_TESTS_FAILED = "tests_failed"
RED_BUILD_FAILED = "build_failed"

#: Run-scope codes (the run stops).
POSTURE_UNQUALIFIED = "POSTURE_UNQUALIFIED"
POSTURE_DRIFT = "POSTURE_DRIFT"
POSTURE_CANARY_FAILED = "POSTURE_CANARY_FAILED"
#: Task-scope codes (the task is skipped, with its reason).
QUAL_ENV_UNLOADABLE = "QUAL_ENV_UNLOADABLE"
QUAL_NOT_RED = "QUAL_NOT_RED"
QUAL_RED_TIMEOUT = "QUAL_RED_TIMEOUT"
QUAL_BASELINE_TIMEOUT = "QUAL_BASELINE_TIMEOUT"
QUAL_BASELINE_UNATTRIBUTED = "QUAL_BASELINE_UNATTRIBUTED"
QUAL_GOLD_NOT_GREEN = "QUAL_GOLD_NOT_GREEN"
QUAL_GOLD_NEW_FAILURES = "QUAL_GOLD_NEW_FAILURES"
QUAL_GOLD_LINT = "QUAL_GOLD_LINT"
QUAL_TARGET_FLAKY = "QUAL_TARGET_FLAKY"
QUAL_HEADROOM = "QUAL_HEADROOM"
QUAL_TREE_COPY_FAILED = "QUAL_TREE_COPY_FAILED"
#: A qualification revoked because a trial's gold control was red in its posture.
QUAL_ENV_WITNESS_RED = "QUAL_ENV_WITNESS_RED"

#: Where every code's fix is explained at length.
OPERATOR_DOC = "docs/OPERATOR.md#7a-when-a-posture-is-unqualified"

#: code → the fix sentence (GOV.UK plain English: what to do, not what went wrong).
QUAL_TEXT: dict[str, str] = {
    POSTURE_UNQUALIFIED: (
        "qualify the repository in this posture (crb repo qualify, or leave qualify_first "
        "on); this costs no model money"
    ),
    POSTURE_DRIFT: (
        "the image, toolchain, limits or runner environment changed after qualification: "
        "qualify again"
    ),
    POSTURE_CANARY_FAILED: (
        "the gold did not grade clean here: read the canary's tail (the cause is usually "
        "provisioning or the image)"
    ),
    QUAL_ENV_UNLOADABLE: (
        "the parent cannot load its dependencies offline: switch provisioning on, or fix "
        "the module named"
    ),
    QUAL_NOT_RED: (
        "the target already passes at the parent in this posture, so it cannot judge a patch "
        "here; the Tasks screen shows how it differs from other postures"
    ),
    QUAL_RED_TIMEOUT: (
        "the target ran out of time at the parent in this posture: raise the repository's "
        "timeout, or leave the task out"
    ),
    QUAL_BASELINE_TIMEOUT: (
        "the belt scope ran out of time at the parent in this posture: raise the "
        "repository's timeout, or narrow its belt scope"
    ),
    QUAL_BASELINE_UNATTRIBUTED: (
        "the belt scope failed at the parent without naming a test: fix the build of the "
        "scope named, or narrow the belt scope"
    ),
    QUAL_GOLD_NOT_GREEN: (
        "the humans' own patch does not pass here; the task is excluded, as a task with a "
        "dirty gold always was"
    ),
    QUAL_GOLD_NEW_FAILURES: (
        "the humans' own patch breaks another test here; the task is excluded, as a task "
        "with a dirty gold always was"
    ),
    QUAL_GOLD_LINT: (
        "the humans' own patch fails the repository's linter here; the task is excluded, as "
        "a task with a dirty gold always was"
    ),
    QUAL_TARGET_FLAKY: (
        "the gold's 2 target runs disagreed: the oracle is not deterministic in this posture"
    ),
    QUAL_HEADROOM: "the gold needed more than half the wall clock: raise the repository's timeout",
    QUAL_TREE_COPY_FAILED: (
        "the tree did not fit the copy: raise work_size, or choose sandbox_tree: readonly"
    ),
    QUAL_ENV_WITNESS_RED: (
        "the gold failed here during a replay, so the posture changed under the "
        "qualification: qualify again (the cause is usually provisioning or the image)"
    ),
}

#: The codes whose scope is the whole run.
RUN_SCOPE_QUAL_CODES: frozenset[str] = frozenset(
    {POSTURE_UNQUALIFIED, POSTURE_DRIFT, POSTURE_CANARY_FAILED}
)


def code_view(code: str, message: str = "") -> dict[str, str]:
    """``{code, message, fix, doc}`` — the one shape every stop is served in (ADR-0019 §9).
    A provisioning code is looked up in :mod:`crb.core.deps`."""
    if code in QUAL_TEXT:
        return {"code": code, "message": message, "fix": QUAL_TEXT[code], "doc": OPERATOR_DOC}
    fix, doc = REFUSAL_TEXT.get(code, ("", ""))
    return {"code": code, "message": message, "fix": fix, "doc": doc}


def _sorted_tuple(items: Sequence[str] | None) -> tuple[str, ...]:
    return tuple(sorted({str(i) for i in (items or ())}))


def fingerprint_of(q: Qualification) -> str:
    """SHA-256 over the facts the oracle rests on — the kind of RED and its failing ids,
    the baseline and its flaky set, whether the gold is clean and its lint verdict. Timing,
    ids, the run and the probe's duration are not part of it: two postures whose
    fingerprints match judge a patch on the same ground (ADR-0019 §8)."""
    red = dict(q.red)
    gold = dict(q.gold)
    return sha256_text(
        canonical_json(
            {
                "red_kind": str(red.get("kind", "")),
                "red_failing": sorted(str(x) for x in red.get("failing") or ()),
                "baseline_failing": list(q.baseline_failing),
                "baseline_flaky": list(q.baseline_flaky),
                "gold_clean": gold.get("clean"),
                "gold_lint": gold.get("lint"),
            }
        )
    )


@dataclass(frozen=True)
class Qualification:
    """One task's oracle facts in one posture (see the module docstring)."""

    qualification_id: str
    repo: str
    task_id: str
    posture_id: str
    posture: Mapping[str, Any]
    state: str
    code: str = ""
    message: str = ""
    fix: str = ""
    deps: Mapping[str, Any] = field(default_factory=dict)
    env_probe: Mapping[str, Any] = field(default_factory=dict)
    red: Mapping[str, Any] = field(default_factory=dict)
    baseline_failing: tuple[str, ...] = ()
    baseline_flaky: tuple[str, ...] = ()
    gold: Mapping[str, Any] = field(default_factory=dict)
    fingerprint: str = ""
    delta: Mapping[str, Any] = field(default_factory=dict)
    apparatus_version: str = APPARATUS_VERSION
    crb_version: str = __version__
    run_id: str = ""
    created: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if self.state not in STATES:
            raise ValueError(f"qualification state must be one of {STATES}, got {self.state!r}")
        if self.state == STATE_QUALIFIED and self.code:
            raise ValueError("a qualified record carries no refusal code")
        if self.state in (STATE_UNQUALIFIED, STATE_REVOKED) and not self.code:
            raise ValueError(f"a {self.state} record names its refusal code")
        if not self.qualification_id:
            object.__setattr__(self, "qualification_id", uuid.uuid4().hex)
        for name in ("posture", "deps", "env_probe", "red", "gold", "delta"):
            object.__setattr__(self, name, dict(getattr(self, name)))
        object.__setattr__(self, "baseline_failing", _sorted_tuple(self.baseline_failing))
        object.__setattr__(self, "baseline_flaky", _sorted_tuple(self.baseline_flaky))
        if self.code and not self.fix:
            object.__setattr__(self, "fix", code_view(self.code)["fix"])
        if not self.fingerprint:
            object.__setattr__(self, "fingerprint", fingerprint_of(self))

    @property
    def is_qualified(self) -> bool:
        """``True`` only for a ``qualified`` record — a legacy, unqualified or revoked one
        never satisfies the gate (ADR-0019 §10)."""
        return self.state == STATE_QUALIFIED

    @property
    def posture_class(self) -> str:
        """The class of the posture this record was measured in (``""`` for legacy)."""
        return str(self.posture.get("posture_class", ""))

    @property
    def baseline(self) -> frozenset[str]:
        """What belt 3 subtracts: both baseline runs' failing sets, the flaky ids included."""
        return frozenset(self.baseline_failing) | frozenset(self.baseline_flaky)

    def project(self, task: TaskSpec) -> TaskSpec:
        """The spec the replay path grades against: the task's own shape, with the
        in-posture baseline (the union), ``red_checked`` / ``gold_clean`` from this record,
        and the posture stamp ``grade()`` checks (``posture_id``, ``qualification_ref``)."""
        if task.task_id != self.task_id:
            raise ValueError(
                f"qualification {self.qualification_id[:8]} is for {self.task_id[:10]}, "
                f"not {task.task_id[:10]}"
            )
        return task.with_(
            baseline_failing=sorted(self.baseline),
            red_checked=True,
            gold_clean=True,
            gold_note="",
            posture_id=self.posture_id,
            qualification_ref=self.qualification_id,
        )

    def view(self) -> dict[str, str]:
        """The refusal as ``{code, message, fix, doc}`` (empty code when qualified)."""
        return code_view(self.code, self.message) if self.code else {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "qualification_id": self.qualification_id,
            "repo": self.repo,
            "task_id": self.task_id,
            "posture_id": self.posture_id,
            "posture": dict(self.posture),
            "state": self.state,
            "code": self.code,
            "message": self.message,
            "fix": self.fix,
            "deps": dict(self.deps),
            "env_probe": dict(self.env_probe),
            "red": dict(self.red),
            "baseline_failing": list(self.baseline_failing),
            "baseline_flaky": list(self.baseline_flaky),
            "gold": dict(self.gold),
            "fingerprint": self.fingerprint,
            "delta": dict(self.delta),
            "apparatus_version": self.apparatus_version,
            "crb_version": self.crb_version,
            "run_id": self.run_id,
            "created": self.created,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Qualification:
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        for k in ("baseline_failing", "baseline_flaky"):
            if k in known:
                known[k] = tuple(known[k] or ())
        return cls(**known)


# ---------------------------------------------------------------------------
# Grade contexts and witnesses (ADR-0019 §4, §5)
# ---------------------------------------------------------------------------


def context_for(
    task: TaskSpec,
    *,
    posture: Posture,
    qualification: Qualification,
    deps: TaskDeps,
    witness: Witness | None,
) -> GradeContext:
    """The grade context for ``task`` in ``posture``: refused (:class:`PostureMismatch`)
    unless ``qualification`` is a ``qualified`` record for this task in this posture —
    a legacy, unqualified or revoked record, or one from another posture, never
    satisfies the gate (ADR-0019 §3)."""
    if qualification.task_id != task.task_id:
        raise PostureMismatch(
            f"qualification {qualification.qualification_id[:8]} is for "
            f"{qualification.task_id[:10]}, not {task.task_id[:10]}"
        )
    if qualification.posture_id != posture.posture_id:
        raise PostureMismatch(
            f"{task.task_id[:10]} was qualified in {qualification.posture_id}, not in "
            f"{posture.posture_id} — {QUAL_TEXT[POSTURE_DRIFT]}"
        )
    if not qualification.is_qualified:
        raise PostureMismatch(
            f"{task.task_id[:10]} is {qualification.state} in {posture.posture_id}"
            + (f" ({qualification.code})" if qualification.code else "")
            + f" — {QUAL_TEXT[POSTURE_UNQUALIFIED]}"
        )
    return GradeContext(posture=posture, qualification=qualification, deps=deps, witness=witness)


def adhoc_posture(executor: Executor) -> Posture:
    """A posture named from the executor's facts alone (no toolchain probe) — for a grade
    that writes no row: the negative controls and ``crb grade --adhoc``."""
    facts = executor.posture_facts()
    return Posture(
        executor=facts.get("executor", executor.name),
        image_ref=facts.get("image_ref", ""),
        image_id=facts.get("image_id", ""),
        toolchain="(not probed: ad hoc)",
        tree=facts.get("tree", ""),
        network=facts.get("network", ""),
        deps_mode="adhoc",
        limits=facts.get("limits", ""),
    )


def adhoc_context(
    task: TaskSpec,
    *,
    executor: Executor,
    deps: TaskDeps | None = None,
    posture: Posture | None = None,
) -> tuple[TaskSpec, GradeContext]:
    """An UNWITNESSED context from the task's own discovery values: a ``legacy`` record
    that never satisfies a gate and a grade whose blamed verdicts read ``unwitnessed``,
    which the ledger refuses on a model-failure row. For the negative controls (which
    write no row) and ``crb grade --adhoc`` (which never appends one)."""
    pst = posture or adhoc_posture(executor)
    q = Qualification(
        qualification_id=ADHOC_PREFIX + uuid.uuid4().hex,
        repo=task.repo,
        task_id=task.task_id,
        posture_id=pst.posture_id,
        posture=pst.to_dict(),
        state=STATE_LEGACY,
        red={"kind": "discovery", "failing": []},
        baseline_failing=task.baseline_failing,
        gold={"clean": task.gold_clean, "note": task.gold_note, "lint": None},
    )
    binding = NO_DEPS if executor.name == "docker" else HOST_ENV_DEPS
    ctx = GradeContext(
        posture=pst, qualification=q, deps=deps or TaskDeps.uniform(binding), witness=None
    )
    return q.project(task), ctx


#: The id prefix of an ad hoc (unwitnessed, never ledgered) qualification.
ADHOC_PREFIX = "adhoc-"


def control_from_run(
    kind: str, scope: Sequence[str], run: TestRun, allow_failing: Collection[str] | None
) -> ControlRun:
    """A :class:`ControlRun` from a test run: green when the run is green (a target
    control), or — for a belt-scope control — when it is attributable and nothing
    outside ``allow_failing`` (the in-posture baseline) fails."""
    if allow_failing is None:
        green = run.green
    else:
        green = (
            not run.timed_out
            and not run.parse_error
            and not run.env_error
            and set(run.failing) <= set(allow_failing)
        )
    return ControlRun(
        kind=kind,
        scope=tuple(scope),
        green=green,
        rc=run.returncode,
        tail=run.tail,
        duration_s=run.duration_s,
        failing=tuple(run.failing),
        timed_out=run.timed_out,
        parse_error=run.parse_error or run.env_error,
    )


class GoldWitness:
    """The replay witness: the gold tree — the parent, the tests and the commit's own
    sources, with the GOLD's dependency binding — runs the scope the trial failed, now,
    in the trial's posture (ADR-0019 §5). A green control makes the blame true; a red one
    means the posture, not the patch, failed."""

    def __init__(
        self,
        repo: GitRepo,
        config: RepoConfig,
        task: TaskSpec,
        *,
        runner: BaseRunner,
        executor: Executor,
        scratch: Path,
        binding: DepsBinding,
        timeout: int = 0,
    ) -> None:
        self.repo, self.config, self.task = repo, config, task
        self.runner, self.executor = runner, executor
        self.scratch, self.binding, self.timeout = Path(scratch), binding, timeout
        #: Every control this witness ran (a canary or a test reads them back).
        self.runs: list[ControlRun] = []

    def control(
        self, scope: Sequence[str], *, why: str, allow_failing: Collection[str] | None = None
    ) -> ControlRun:
        dest = (
            self.scratch / f"witness-{self.config.name}-{self.task.short_id}-{uuid.uuid4().hex[:6]}"
        )
        with Workspace.create(self.repo, self.task.task_id, dest, config=self.config) as ws:
            ws.overlay_tests(self.task.test_files)
            ws.overlay_sources(self.task.src_files)
            run = self.runner.run_for(
                self.executor,
                ws.root,
                tuple(scope),
                timeout=self.timeout,
                authored=self.task.authored,
                deps=self.binding,
            )
        out = control_from_run(BLAME_GOLD_GREEN, scope, run, allow_failing)
        self.runs.append(out)
        return out


class EnvProbeWitness:
    """The factory witness (a factory item has no gold): a FRESH base tree proves the
    posture can load what the tests need — the runner's offline environment probe when
    it has one (Go: ``go list -deps -test``), else the scope itself run on the base tree
    with the oracle overlaid, which must at least be attributable (failing ids parsed, no
    timeout, no build error the parser could not name)."""

    def __init__(
        self,
        make_tree: Callable[[], Workspace],
        *,
        runner: BaseRunner,
        executor: Executor,
        binding: DepsBinding,
        test_files: Sequence[str] = (),
        timeout: int = 0,
    ) -> None:
        self.make_tree = make_tree
        self.runner, self.executor, self.binding = runner, executor, binding
        self.test_files, self.timeout = tuple(test_files), timeout
        self.runs: list[ControlRun] = []

    def control(
        self, scope: Sequence[str], *, why: str, allow_failing: Collection[str] | None = None
    ) -> ControlRun:
        t = self.timeout or int(self.runner.opts.get("timeout", self.runner.default_timeout))
        with self.make_tree() as ws:
            # the runner reads the bound set to build its probe (a Python or Node probe
            # checks the set's own manifest), so bind it while the command is made
            with self.runner.deps_bound(self.binding):
                probe = self.runner.env_probe_command(
                    ws.root, (), executor=self.executor, timeout=t
                )
            if probe is not None:
                res = self.executor.run(with_deps(probe, self.binding, self.executor.name))
                out = ControlRun(
                    kind=BLAME_ENV_PROBE,
                    scope=tuple(probe.argv[1:]),
                    green=res.ok and not res.env_error,
                    rc=res.returncode,
                    tail=(res.combined or "")[-2000:],
                    duration_s=res.duration_s,
                    timed_out=res.timed_out,
                    parse_error=res.env_error,
                )
            else:
                if self.test_files:
                    ws.overlay_tests(self.test_files)
                run = self.runner.run_for(
                    self.executor,
                    ws.root,
                    tuple(scope),
                    timeout=t,
                    authored=None,
                    deps=self.binding,
                )
                attributable = not run.timed_out and not run.parse_error and not run.env_error
                out = ControlRun(
                    kind=BLAME_ENV_PROBE,
                    scope=tuple(scope),
                    green=attributable,
                    rc=run.returncode,
                    tail=run.tail,
                    duration_s=run.duration_s,
                    failing=tuple(run.failing),
                    timed_out=run.timed_out,
                    parse_error=run.parse_error or run.env_error,
                )
        self.runs.append(out)
        return out


# ---------------------------------------------------------------------------
# The measurement: qualify one task in one posture, for no model money
# ---------------------------------------------------------------------------

EventFn = Callable[[str, Mapping[str, Any]], None]


def _emit(on_event: EventFn | None, action: str, **payload: Any) -> None:
    if on_event is not None:
        on_event(action, payload)


def _tail(text: str, n: int = 12) -> str:
    return redact_and_cap(tail_of(text, n), max_chars=1500)


def qualify_task(
    repo: GitRepo,
    config: RepoConfig,
    task: TaskSpec,
    *,
    posture: Posture,
    deps: TaskDeps | DepsProvider,
    runner: BaseRunner,
    executor: Executor,
    scratch: Path,
    timeout: int = 0,
    run_id: str = "",
    on_event: EventFn | None = None,
) -> Qualification:
    """Measure ``task``'s oracle in ``posture`` and return the record (ADR-0019 §2).

    Never constructs a builder and never calls a model. In order, each step refusing with
    its code (a task-scope refusal is an ``unqualified`` record, never an exception):

    1. the environment probe at the parent (``runner.env_probe_command``, offline, with
       the parent's dependency binding) — ``QUAL_ENV_UNLOADABLE`` when it fails;
    2. RED once with the tests overlaid — ``QUAL_NOT_RED`` / ``QUAL_RED_TIMEOUT``; a RED
       with no parsed failing id is a build failure, accepted only after a GREEN probe
       (or, in the host-env mode with no probe, under the rule this product always had);
    3. the belt scope twice — the union is the baseline, the difference the flaky set —
       ``QUAL_BASELINE_TIMEOUT``, or ``QUAL_BASELINE_UNATTRIBUTED`` when the target built;
    4. the gold (a fresh worktree with the tests and the commit's sources, the GOLD's
       binding): the target twice and the belt scope once at HALF the wall clock, then
       belt 5 — ``QUAL_GOLD_NOT_GREEN`` / ``QUAL_TARGET_FLAKY`` / ``QUAL_HEADROOM`` /
       ``QUAL_GOLD_NEW_FAILURES`` / ``QUAL_GOLD_LINT``.

    A tree the executor could not copy is ``QUAL_TREE_COPY_FAILED`` at any step. ``deps``
    may be a provider: its task-scope refusal is an ``unqualified`` record with the code;
    a run-scope one (a deployment setting) is re-raised.
    """
    started = time.monotonic()
    t = timeout or int(runner.opts.get("timeout", runner.default_timeout))
    half = max(1, t // 2)
    common: dict[str, Any] = {
        "qualification_id": "",
        "repo": config.name,
        "task_id": task.task_id,
        "posture_id": posture.posture_id,
        "posture": posture.to_dict(),
        "run_id": run_id,
    }
    facts: dict[str, Any] = {}

    def finish(q: Qualification) -> Qualification:
        _emit(
            on_event,
            "qualify.task",
            task=task.task_id,
            posture_id=posture.posture_id,
            posture_class=posture.posture_class,
            state=q.state,
            code=q.code,
            message=q.message[:300],
            fingerprint=q.fingerprint,
            duration_s=round(time.monotonic() - started, 3),
        )
        return q

    def refuse(code: str, message: str) -> Qualification:
        return finish(
            Qualification(
                **common,
                state=STATE_UNQUALIFIED,
                code=code,
                message=redact_and_cap(message, max_chars=500),
                **facts,
            )
        )

    if not isinstance(deps, TaskDeps):
        try:
            deps = deps.resolve(
                repo,
                config,
                parent=repo.parent(task.task_id),
                gold=task.task_id,
                executor_name=executor.name,
                on_event=on_event,
            )
        except ProvisionRefused as exc:
            if exc.refusal.scope == SCOPE_RUN:
                raise
            return refuse(exc.refusal.code, exc.refusal.message)
    facts["deps"] = deps.to_dict()
    sealed = posture.deps_mode == DEPS_MODE_SEALED

    def copy_failed(run: TestRun) -> Qualification:
        return refuse(QUAL_TREE_COPY_FAILED, f"the tree could not be prepared: {run.env_error}")

    # --- 1 + 2 + 3: the parent -------------------------------------------------
    dest = Path(scratch) / f"qual-{config.name}-{task.short_id}-{uuid.uuid4().hex[:6]}"
    with Workspace.create(repo, task.task_id, dest, config=config) as ws:
        env_probe: dict[str, Any] = {"ran": False}
        with runner.deps_bound(deps.parent):
            probe = runner.env_probe_command(ws.root, (), executor=executor, timeout=t)
        if probe is not None:
            res = executor.run(with_deps(probe, deps.parent, executor.name))
            if res.env_error:
                return refuse(
                    QUAL_TREE_COPY_FAILED, f"the tree could not be prepared: {res.env_error}"
                )
            env_probe = {
                "ran": True,
                "ok": res.ok,
                "rc": res.returncode,
                "duration_s": round(res.duration_s, 3),
                "tail": "" if res.ok else _tail(res.combined),
            }
            facts["env_probe"] = env_probe
            if not res.ok:
                return refuse(
                    QUAL_ENV_UNLOADABLE,
                    "the parent cannot load its dependencies offline in this posture: "
                    + _tail(res.combined, 4),
                )
        facts["env_probe"] = env_probe

        ws.overlay_tests(task.test_files)
        red = runner.run_for(
            executor,
            ws.root,
            task.target_tests,
            timeout=t,
            authored=task.authored,
            deps=deps.parent,
        )
        if red.env_error:
            return copy_failed(red)
        if red.timed_out:
            return refuse(QUAL_RED_TIMEOUT, "target timeout at parent")
        if red.green:
            return refuse(QUAL_NOT_RED, "target green at parent")
        kind = RED_TESTS_FAILED if red.failing else RED_BUILD_FAILED
        facts["red"] = {
            "kind": kind,
            "rc": red.returncode,
            "failing": sorted(red.failing),
            "duration_s": round(red.duration_s, 3),
        }
        # a build-failure RED needs a green probe; host-env with no probe keeps the rule
        # this product always had (accepted)
        if kind == RED_BUILD_FAILED and not env_probe.get("ok") and (probe is not None or sealed):
            return refuse(
                QUAL_ENV_UNLOADABLE,
                "the target did not build at the parent and nothing proves this posture "
                "can load its dependencies: " + _tail(red.tail, 4),
            )

        runs = [
            runner.run_for(
                executor,
                ws.root,
                task.belt_scope,
                timeout=t,
                authored=task.authored,
                deps=deps.parent,
            )
            for _ in range(2)
        ]
        for b in runs:
            if b.env_error:
                return copy_failed(b)
            if b.timed_out:
                return refuse(QUAL_BASELINE_TIMEOUT, "baseline timeout")
        if kind == RED_TESTS_FAILED and any(b.parse_error for b in runs):
            bad = next(b for b in runs if b.parse_error)
            return refuse(
                QUAL_BASELINE_UNATTRIBUTED,
                f"the belt scope failed at the parent without naming a test: {bad.parse_error}",
            )
        unattributed = next((b.parse_error for b in runs if b.parse_error), "")
        if unattributed:
            # explained by the build-failure RED; recorded, never a baseline id
            facts["red"] = {**facts["red"], "baseline_parse_error": unattributed[:300]}
        union = frozenset(runs[0].failing) | frozenset(runs[1].failing)
        flaky = frozenset(runs[0].failing) ^ frozenset(runs[1].failing)
        facts["baseline_failing"] = tuple(sorted(union))
        facts["baseline_flaky"] = tuple(sorted(flaky))

    # --- 4: the gold, in a fresh worktree, at half the wall clock ---------------
    gdest = Path(scratch) / f"qual-gold-{config.name}-{task.short_id}-{uuid.uuid4().hex[:6]}"
    with Workspace.create(repo, task.task_id, gdest, config=config) as gws:
        gws.overlay_tests(task.test_files)
        gws.overlay_sources(task.src_files)
        targets = [
            runner.run_for(
                executor,
                gws.root,
                task.target_tests,
                timeout=half,
                authored=task.authored,
                deps=deps.gold,
            )
            for _ in range(2)
        ]
        gold: dict[str, Any] = {
            "clean": False,
            "note": "",
            "lint": None,
            "target_runs": 2,
            "timeout_s": half,
            "duration_s": round(sum(r.duration_s for r in targets), 3),
        }
        facts["gold"] = gold
        for r in targets:
            if r.env_error:
                return copy_failed(r)
        reds = [r for r in targets if r.red]
        if reds:
            if all(r.timed_out for r in reds):
                gold["note"] = f"gold target needed more than half the wall clock ({half}s)"
                return refuse(QUAL_HEADROOM, gold["note"])
            if len(reds) < len(targets):
                gold["note"] = "the gold's 2 target runs disagreed"
                return refuse(QUAL_TARGET_FLAKY, gold["note"])
            gold["note"] = f"gold target not green (rc={reds[0].returncode})"
            return refuse(QUAL_GOLD_NOT_GREEN, gold["note"])
        belt = runner.run_for(
            executor,
            gws.root,
            task.belt_scope,
            timeout=half,
            authored=task.authored,
            deps=deps.gold,
        )
        if belt.env_error:
            return copy_failed(belt)
        if belt.timed_out:
            gold["note"] = f"gold belt scope needed more than half the wall clock ({half}s)"
            return refuse(QUAL_HEADROOM, gold["note"])
        if belt.parse_error:
            gold["note"] = f"gold belt unattributed: {belt.parse_error}"
            return refuse(QUAL_GOLD_NEW_FAILURES, gold["note"])
        new = set(belt.failing) - union
        if new:
            gold["note"] = f"gold introduced {len(new)} belt failure(s)"
            return refuse(QUAL_GOLD_NEW_FAILURES, gold["note"] + ": " + ", ".join(sorted(new)[:5]))
        # belt 5 on the gold: the plan a builder's patch would face
        plan = runner.lint_plan(gws.root, executor)
        if plan is not None:
            present = [f for f in task.src_files if gws.exists(f)]
            lint_run = run_plan(plan, executor, gws.root, present)
            gold["lint"] = lint_run.ok
            if lint_run.error:
                gold["note"] = f"gold lint could not run ({lint_run.detected}): {lint_run.error}"[
                    :300
                ]
                return refuse(QUAL_GOLD_LINT, gold["note"])
            if lint_run.ok is False:
                gold["note"] = f"gold fails belt 5 ({lint_run.detected}): {lint_run.note}"[:300]
                return refuse(QUAL_GOLD_LINT, gold["note"])
        gold["clean"] = True
    return finish(Qualification(**common, state=STATE_QUALIFIED, **facts))


def delta_against(q: Qualification, others: Sequence[Qualification]) -> dict[str, Any]:
    """How ``q`` differs from the task's latest qualified record in ANOTHER posture —
    what the Tasks screen shows when a task qualifies in one posture and not another
    (the 2026-09-25 finding D5 reads ``only_here: [TestDeadcodeElimination]``)."""
    ref = next(
        (
            o
            for o in sorted(others, key=lambda o: o.created, reverse=True)
            if o.posture_id != q.posture_id and o.is_qualified and o.task_id == q.task_id
        ),
        None,
    )
    if ref is None:
        return {}
    return {
        "reference_posture_id": ref.posture_id,
        "reference_posture_class": ref.posture_class,
        "same_fingerprint": ref.fingerprint == q.fingerprint,
        "only_here": sorted(q.baseline - ref.baseline),
        "only_there": sorted(ref.baseline - q.baseline),
        "red_kind": {"here": q.red.get("kind", ""), "there": ref.red.get("kind", "")},
    }


class JsonlQualifications:
    """The portable, append-only qualification record (the CLI's workdir; the server keeps
    the same records in ``task_qualifications``). The latest row for a task and posture is
    the one in force; nothing is ever rewritten."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, q: Qualification) -> Qualification:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(q.to_dict(), sort_keys=True) + "\n")
        return q

    def rows(self) -> Iterator[Qualification]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield Qualification.from_dict(json.loads(line))

    def latest(self, task_id: str, posture_id: str) -> Qualification | None:
        found: Qualification | None = None
        for q in self.rows():
            if q.task_id == task_id and q.posture_id == posture_id:
                found = q
        return found

    def for_task(self, task_id: str) -> list[Qualification]:
        return [q for q in self.rows() if q.task_id == task_id]


__all__ = [
    "ADHOC_PREFIX",
    "OPERATOR_DOC",
    "POSTURE_CANARY_FAILED",
    "POSTURE_DRIFT",
    "POSTURE_UNQUALIFIED",
    "QUAL_BASELINE_TIMEOUT",
    "QUAL_BASELINE_UNATTRIBUTED",
    "QUAL_ENV_UNLOADABLE",
    "QUAL_ENV_WITNESS_RED",
    "QUAL_GOLD_LINT",
    "QUAL_GOLD_NEW_FAILURES",
    "QUAL_GOLD_NOT_GREEN",
    "QUAL_HEADROOM",
    "QUAL_NOT_RED",
    "QUAL_RED_TIMEOUT",
    "QUAL_TARGET_FLAKY",
    "QUAL_TEXT",
    "QUAL_TREE_COPY_FAILED",
    "RED_BUILD_FAILED",
    "RED_TESTS_FAILED",
    "RUN_SCOPE_QUAL_CODES",
    "STATES",
    "STATE_LEGACY",
    "STATE_QUALIFIED",
    "STATE_REVOKED",
    "STATE_UNQUALIFIED",
    "EnvProbeWitness",
    "GoldWitness",
    "JsonlQualifications",
    "Qualification",
    "adhoc_context",
    "adhoc_posture",
    "code_view",
    "context_for",
    "control_from_run",
    "delta_against",
    "fingerprint_of",
    "qualify_task",
]
