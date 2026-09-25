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

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from crb.core.deps import REFUSAL_TEXT
from crb.core.evidence import canonical_json, sha256_text, utc_now_iso
from crb.core.spec import TaskSpec
from crb.core.version import APPARATUS_VERSION, __version__

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


__all__ = [
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
    "Qualification",
    "code_view",
    "fingerprint_of",
]
