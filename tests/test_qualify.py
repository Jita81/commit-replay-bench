"""crb.core.qualify — a task is proven in the posture that grades it, for no model money.

Navigation
----------
What it is:   The tests for the ``Qualification`` record (the data half) and ``qualify_task``
              (the measurement half) of ADR-0019 §2.
What it does: Pins that a projection carries the in-posture baseline and the posture stamp,
              that the fingerprint ignores timing and ids, that a legacy record is never
              qualified; and, on real pytest runs against the fixture repository and scripted
              runners for what a healthy fixture cannot do, every refusal code the
              measurement can give — unloadable environment, not RED, the flaky set, a gold
              that disagrees with itself, the half wall clock — with no builder constructed.
How:          ``qualify_task`` on the fixture repository with the real ``PytestRunner`` /
              ``LocalExecutor``; a scripted runner wraps it where a failure must be injected.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0019-qualification-is-posture-relative.md
Works with:   src/crb/core/qualify.py (under test), src/crb/core/posture.py (the posture a
              record is keyed to), src/crb/core/deps.py (the bindings and refusals),
              src/crb/core/spec.py (the projected ``TaskSpec``), tests/fixtures/pyrepo.py (the
              fixture repository)
Tested by:    tests/test_qualify.py
Touch when:   a qualification step or refusal code changes (ADR-0019's table and a case here).
"""

from __future__ import annotations

from typing import Any

from crb.core.posture import Posture
from crb.core.qualify import (
    STATE_LEGACY,
    STATE_QUALIFIED,
    Qualification,
    fingerprint_of,
)
from crb.core.spec import TaskSpec

POSTURE = Posture(
    executor="docker",
    image_ref="crb-sandbox-go:t",
    image_id="sha256:" + "1" * 64,
    toolchain="go version go1.26.8 linux/arm64",
    runner="go",
    runner_env="e" * 64,
    tree="readonly",
    network="none",
    deps_mode="sealed",
    limits="mem=2g",
)


def _task(**kw: Any) -> TaskSpec:
    base: dict[str, Any] = {
        "task_id": "b" * 40,
        "repo": "r",
        "subject": "s",
        "authored": "2026-01-01T00:00:00Z",
        "test_files": ("tests/test_x.py",),
        "src_files": ("x.py",),
        "target_tests": ("tests/test_x.py",),
        "belt_scope": ("tests/",),
        "baseline_failing": ("tests/test_host.py::only_on_the_host",),
        "red_checked": True,
        "gold_clean": True,
    }
    base.update(kw)
    return TaskSpec(**base)


def _q(**kw: Any) -> Qualification:
    base: dict[str, Any] = {
        "qualification_id": "q" * 32,
        "repo": "r",
        "task_id": "b" * 40,
        "posture_id": POSTURE.posture_id,
        "posture": POSTURE.to_dict(),
        "state": STATE_QUALIFIED,
        "red": {"kind": "tests_failed", "rc": 1, "failing": ["tests/test_x.py::test_new"]},
        "baseline_failing": ("tests/test_deadcode.py::TestDeadcodeElimination",),
        "baseline_flaky": ("tests/test_net.py::test_sometimes",),
        "gold": {"clean": True, "note": "", "lint": None, "target_runs": 2, "timeout_s": 300},
        "run_id": "run-1",
        "created": "2026-09-25T10:00:00Z",
    }
    base.update(kw)
    return Qualification(**base)


def test_projection_carries_the_in_posture_baseline_and_the_stamp() -> None:
    discovery = _task(gold_clean=None, red_checked=False, gold_note="never checked")
    q = _q()
    spec = q.project(discovery)
    # the in-posture baseline: the union of both runs' failing sets, the flaky ones included
    assert set(spec.baseline_failing) == {
        "tests/test_deadcode.py::TestDeadcodeElimination",
        "tests/test_net.py::test_sometimes",
    }
    assert "tests/test_host.py::only_on_the_host" not in spec.baseline_failing
    assert spec.red_checked is True and spec.gold_clean is True and spec.gold_note == ""
    assert spec.posture_id == POSTURE.posture_id and spec.qualification_ref == q.qualification_id
    # everything else is the task's own
    assert spec.target_tests == discovery.target_tests and spec.src_files == discovery.src_files
    assert Qualification.from_dict(q.to_dict()) == q


def test_fingerprint_ignores_timing_and_ids() -> None:
    a = _q()
    b = _q(
        qualification_id="z" * 32,
        run_id="run-2",
        created="2026-10-01T00:00:00Z",
        gold={"clean": True, "note": "", "lint": None, "target_runs": 2, "timeout_s": 900},
        env_probe={"ran": True, "ok": True, "duration_s": 4.2},
    )
    assert a.fingerprint == b.fingerprint == fingerprint_of(a)
    c = _q(baseline_failing=())
    assert c.fingerprint != a.fingerprint  # the oracle's ground moved
    d = _q(red={"kind": "build_failed", "rc": 1, "failing": []})
    assert d.fingerprint != a.fingerprint


def test_a_legacy_qualification_is_never_qualified() -> None:
    legacy = _q(state=STATE_LEGACY, posture_id="pst_legacy", posture={})
    assert not legacy.is_qualified
    assert _q().is_qualified
    for state in ("unqualified", "revoked"):
        assert not _q(state=state, code="QUAL_NOT_RED").is_qualified
