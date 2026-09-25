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


# ---------------------------------------------------------------------------
# the measurement half: qualify_task (ADR-0019 §2)
# ---------------------------------------------------------------------------

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from crb.core import qualify as qmod  # noqa: E402
from crb.core.deps import (  # noqa: E402
    DEPS_MODE_HOST_ENV,
    DEPS_MODE_SEALED,
    PROVISION_DISABLED,
    PROVISION_NO_LOCK,
    NullDepsProvider,
    ProvisionRefused,
    TaskDeps,
    refusal,
)
from crb.core.execution import Command, Executor, LocalExecutor  # noqa: E402
from crb.core.posture import resolve_posture  # noqa: E402
from crb.core.runners.base import TestRun as Run  # noqa: E402
from crb.core.runners.pytest_runner import PytestRunner  # noqa: E402
from fixtures import pyrepo as pr  # noqa: E402

A, B, C = "tests/test_a.py::a", "tests/test_b.py::b", "tests/test_c.py::c"


def _green() -> Run:
    return Run(0, frozenset(), "ok")


def _red(*ids: str) -> Run:
    return Run(1, frozenset(ids), "failed")


def _build_failure() -> Run:
    return Run(2, frozenset(), "cannot build", parse_error="unattributed failure (rc=2)")


class _Scripted(PytestRunner):
    """The pytest runner's scopes and lint, with scripted test runs and an optional
    scripted environment probe (``probe``: None — no probe; True/False — its answer)."""

    def __init__(self, config: Any, script: list[Run], probe: bool | None = None) -> None:
        super().__init__(config)
        self.script = list(script)
        self.probe = probe
        self.calls: list[tuple[tuple[str, ...], int]] = []

    def run(self, executor: Any, root: Path, scope: Any, *, timeout: int = 0) -> Run:
        self.calls.append((tuple(scope), timeout))
        return self.script.pop(0)

    def env_probe_command(
        self, root: Path, scope: Any, *, executor: Executor, timeout: int
    ) -> Command | None:
        if self.probe is None:
            return None
        code = "0" if self.probe else "1"
        return Command(
            (sys.executable, "-c", f"import sys; sys.exit({code})"), root, timeout=timeout
        )

    def lint_plan(self, root: Path, executor: Executor) -> Any:
        return None


def _posture(runner: PytestRunner, pyrepo: pr.PyRepo, mode: str = DEPS_MODE_HOST_ENV) -> Posture:
    return resolve_posture(LocalExecutor(), runner, deps_mode=mode, root=pyrepo.path)


def _qualify(pyrepo: pr.PyRepo, runner: PytestRunner, tmp: Path, **kw: Any) -> Qualification:
    mode = kw.pop("mode", DEPS_MODE_HOST_ENV)
    deps = kw.pop("deps", NullDepsProvider())
    return qmod.qualify_task(
        pyrepo.repo,
        pyrepo.config,
        pyrepo.feat_task(gold_clean=None, red_checked=False),
        posture=_posture(runner, pyrepo, mode),
        deps=deps,
        runner=runner,
        executor=LocalExecutor(),
        scratch=tmp,
        **kw,
    )


def test_the_fixture_task_qualifies_on_real_runs(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    q = _qualify(
        pyrepo,
        PytestRunner(pyrepo.config),
        tmp_path,
        on_event=lambda a, p: events.append((a, dict(p))),
    )
    assert q.is_qualified, q.message
    assert q.red["kind"] == qmod.RED_TESTS_FAILED and q.gold["clean"] is True
    assert q.posture_class == "local/inplace/host-env" and q.env_probe == {"ran": False}
    assert [a for a, _ in events][-1] == "qualify.task"


def test_unloadable_module_graph_is_qual_env_unloadable_not_red(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    runner = _Scripted(pyrepo.config, [], probe=False)
    q = _qualify(pyrepo, runner, tmp_path, mode=DEPS_MODE_SEALED)
    assert q.state == qmod.STATE_UNQUALIFIED and q.code == qmod.QUAL_ENV_UNLOADABLE
    assert "provisioning" in q.fix and q.env_probe["ok"] is False
    assert runner.calls == []  # never RED: the target was not even run


def test_a_build_failure_red_counts_only_after_a_green_env_probe(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    tail = [_green(), _green(), _green(), _green(), _green()]  # 2 baselines, gold ×2, belt
    # sealed, no probe: nothing proves the posture can load the dependencies
    no_probe = _Scripted(pyrepo.config, [_build_failure(), *tail], probe=None)
    q = _qualify(pyrepo, no_probe, tmp_path, mode=DEPS_MODE_SEALED)
    assert q.code == qmod.QUAL_ENV_UNLOADABLE and len(no_probe.calls) == 1
    # a green probe: the build failure is the oracle's RED
    probed = _Scripted(pyrepo.config, [_build_failure(), *tail], probe=True)
    q2 = _qualify(pyrepo, probed, tmp_path, mode=DEPS_MODE_SEALED)
    assert q2.is_qualified and q2.red["kind"] == qmod.RED_BUILD_FAILED
    # host-env with no probe: the rule this product always had
    host = _Scripted(pyrepo.config, [_build_failure(), *tail], probe=None)
    assert _qualify(pyrepo, host, tmp_path).is_qualified


def test_two_baseline_runs_give_the_union_and_the_flaky_set(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    runner = _Scripted(
        pyrepo.config,
        [_red(pr.TEST_SUBTRACT), _red(A, B), _red(B, C), _green(), _green(), _red(A, B, C)],
    )
    q = _qualify(pyrepo, runner, tmp_path)
    assert q.is_qualified
    assert q.baseline_failing == (A, B, C) and q.baseline_flaky == (A, C)
    assert q.project(pyrepo.feat_task()).baseline_failing == (A, B, C)


def test_a_gold_that_disagrees_with_itself_is_target_flaky(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    runner = _Scripted(
        pyrepo.config, [_red(pr.TEST_SUBTRACT), _green(), _green(), _green(), _red(A)]
    )
    q = _qualify(pyrepo, runner, tmp_path)
    assert q.code == qmod.QUAL_TARGET_FLAKY and "not deterministic" in q.fix
    both = _Scripted(pyrepo.config, [_red(pr.TEST_SUBTRACT), _green(), _green(), _red(A), _red(A)])
    assert _qualify(pyrepo, both, tmp_path).code == qmod.QUAL_GOLD_NOT_GREEN


def test_the_gold_runs_at_half_the_wall_clock(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    runner = _Scripted(
        pyrepo.config, [_red(pr.TEST_SUBTRACT), _green(), _green(), _green(), _green(), _green()]
    )
    q = _qualify(pyrepo, runner, tmp_path, timeout=300)
    assert q.is_qualified and q.gold["timeout_s"] == 150
    assert [t for _, t in runner.calls] == [300, 300, 300, 150, 150, 150]
    slow = Run(124, frozenset(), "", timed_out=True)
    headroom = _Scripted(pyrepo.config, [_red(pr.TEST_SUBTRACT), _green(), _green(), slow, slow])
    assert _qualify(pyrepo, headroom, tmp_path, timeout=300).code == qmod.QUAL_HEADROOM
    not_red = _Scripted(pyrepo.config, [_green()])
    assert _qualify(pyrepo, not_red, tmp_path).code == qmod.QUAL_NOT_RED


def test_qualification_never_constructs_a_builder(
    pyrepo: pr.PyRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import crb.builders as builders

    def refuse(*a: Any, **k: Any) -> Any:
        raise AssertionError("qualification constructed a builder")

    monkeypatch.setattr(builders, "get_builder", refuse)
    monkeypatch.setattr(builders, "builder_for_rung", refuse)
    q = _qualify(pyrepo, PytestRunner(pyrepo.config), tmp_path)
    assert q.is_qualified
    # and the core module cannot reach one: it imports nothing from crb.builders
    assert not any(
        getattr(v, "__module__", "").startswith("crb.builders") for v in vars(qmod).values()
    )


class _Refusing:
    def __init__(self, code: str) -> None:
        self.code = code

    def mode(self, config: Any, executor_name: str) -> str:
        return DEPS_MODE_SEALED

    def resolve(self, *a: Any, **k: Any) -> TaskDeps:
        raise ProvisionRefused(refusal(self.code, "go.sum missing at 746ef07"))

    def verify(self, deps: TaskDeps) -> None:
        return None


def test_task_scope_refusal_skips_and_run_scope_refusal_stops(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    runner = _Scripted(pyrepo.config, [])
    q = _qualify(pyrepo, runner, tmp_path, deps=_Refusing(PROVISION_NO_LOCK))
    assert q.state == qmod.STATE_UNQUALIFIED and q.code == PROVISION_NO_LOCK
    assert q.fix and runner.calls == []
    with pytest.raises(ProvisionRefused) as exc:
        _qualify(pyrepo, runner, tmp_path, deps=_Refusing(PROVISION_DISABLED))
    assert exc.value.refusal.scope == "run" and "CRB_PROVISION__ENABLED" in exc.value.refusal.fix


def test_delta_against_another_postures_qualification() -> None:
    host = _q(
        qualification_id="h" * 32,
        posture_id="pst_host",
        posture={"posture_class": "local/inplace/host-env"},
        baseline_failing=(),
        baseline_flaky=(),
    )
    sealed = _q(baseline_failing=("cobra::TestDeadcodeElimination",), baseline_flaky=())
    d = qmod.delta_against(sealed, [host, sealed])
    assert d["reference_posture_id"] == "pst_host"
    assert d["only_here"] == ["cobra::TestDeadcodeElimination"] and d["only_there"] == []
    assert d["same_fingerprint"] is False
    assert qmod.delta_against(sealed, [sealed]) == {}  # no other posture, no delta


def test_every_stop_is_a_code_with_a_fix_and_a_guide_that_exists() -> None:
    """ADR-0019 §9: one closed vocabulary served as {code, message, fix, doc}; the guide
    anchor every QUAL_* / POSTURE_* code links to is a heading in the operator guide."""
    import re as _re

    from crb.core.deps import REFUSAL_TEXT

    root = Path(__file__).resolve().parent.parent
    operator = (root / "docs" / "OPERATOR.md").read_text(encoding="utf-8")
    anchor = qmod.OPERATOR_DOC.split("#", 1)[1]
    headings = {
        _re.sub(r"[^\w\- ]", "", h.strip().lower()).replace(" ", "-")
        for h in _re.findall(r"^#+ (.+)$", operator, flags=_re.M)
    }
    assert anchor in headings
    for code, fix in qmod.QUAL_TEXT.items():
        view = qmod.code_view(code, "m")
        assert view == {"code": code, "message": "m", "fix": fix, "doc": qmod.OPERATOR_DOC}
        assert fix and not fix.endswith(".")  # a clause the UI sets in a sentence
    for code in REFUSAL_TEXT:
        view = qmod.code_view(code)
        assert view["fix"] and view["doc"].startswith("docs/DEPLOYMENT.md#")
