"""The worker's posture rules: production refuses the unsealed posture, and the posture gate.

Navigation
----------
What it is:   The worker's posture tests (ADR-0023, ADR-0019), moved out of tests/test_worker.py
              so the suite's shards stay inside their time budget (files are the shard unit).
What it does: Pins (ADR-0023) that a production worker stamps the unsealed-production override
              into every run's apparatus and every pack, refuses a run that asks for the local
              executor without it, and refuses a factory run because factory builds run on the
              host; and (ADR-0019) that a replay with no qualified task fails before spend,
              qualify-first qualifies then replays only the qualified, posture drift and a canary
              that is not clean fail at zero spend, two environment rows stop the run and revoke
              the qualifications (only a control that ran red revokes), the gate hashes each
              sealed set once and fails closed, a qualify run spends nothing, and a mine in
              docker without provisioning says what to do.
How:          The ``Harness`` and ``h`` fixture of tests/test_worker.py, with its live-posture
              and qualification seeds; no docker, no network, no model.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0019-qualification-is-posture-relative.md,
              docs/adr/0023-production-refuses-the-unsealed-posture.md
Works with:   src/crb/server/worker.py (under test), src/crb/server/posture_gate.py (the gate),
              src/crb/core/qualify.py (the records), tests/test_worker.py (the shared harness)
Tested by:    tests/test_worker_posture.py
Touch when:   never for a new repository; the posture gate or the unsealed-production override
              changes.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

import crb.builders as builders_pkg
from crb.core.execution import LocalExecutor
from crb.core.runners.pytest_runner import PytestRunner
from crb.store.jobs import STATUS_FAILED, STATUS_SUCCEEDED
from crb.store.models import Task
from fixtures import pyrepo as pr
from test_worker import FakeBuilder, Harness, _live_posture, _multiply_backlog, _seed_qualified


@pytest.fixture(autouse=True)
def _register(monkeypatch: pytest.MonkeyPatch) -> None:
    """``test_worker``'s autouse registration is module-local; restore ``fake`` per test."""
    monkeypatch.setitem(builders_pkg._REGISTRY, "fake", FakeBuilder)
    FakeBuilder.briefs = []
    FakeBuilder.hook = None


@pytest.fixture
def h(tmp_path: Path, pyrepo: pr.PyRepo) -> Harness:
    """The worker harness with the repo registered and its one mined task on file."""
    harness = Harness(tmp_path, pyrepo)
    harness.add_repo()
    harness.add_task(pyrepo.feat_task())
    return harness


# --- ADR-0023: production refuses the unsealed posture ------------------------------------------

OVERRIDE_STAMP = {
    "env": "prod",
    "sandbox_executor": "local",
    "builder_executor": "host",
    "override": "CRB_ALLOW_UNSEALED_PROD",
    "adr": "0023",
}


def test_a_prod_worker_stamps_the_unsealed_override_into_the_run_and_every_pack(
    h: Harness,
) -> None:
    h.worker.settings = replace(h.settings, unsealed_override=OVERRIDE_STAMP)
    run = h.enqueue("replay")
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    assert done.apparatus_json["extra"]["unsealed_prod_override"] == OVERRIDE_STAMP
    (row,) = list(h.worker.ledger.rows(run_id=run.id))
    pack = h.worker.evidence_dir / f"{row.evidence_pack_hash}.json"
    body = json.loads(pack.read_text(encoding="utf-8"))
    assert body["apparatus"]["extra"]["unsealed_prod_override"] == OVERRIDE_STAMP
    # the other kinds carry it on their apparatus too
    h.enqueue("probe")
    probe = h.run_one()
    assert probe.apparatus_json["unsealed_prod_override"] == OVERRIDE_STAMP


def test_a_sealed_worker_stamps_nothing(h: Harness) -> None:
    run = h.enqueue("replay")
    done = h.run_one()
    assert done.id == run.id and "unsealed_prod_override" not in done.apparatus_json["extra"]


def test_a_prod_worker_refuses_a_run_that_asks_for_the_local_executor(h: Harness) -> None:
    h.worker.settings = replace(h.settings, executor="docker", refuse_unsealed=True)
    run = h.enqueue("replay", params_json={"executor": "local"})
    done = h.run_one()
    assert done.status == STATUS_FAILED
    assert done.error.startswith("sandbox unavailable") and "CRB_ALLOW_UNSEALED_PROD" in done.error
    assert list(h.worker.ledger.rows(run_id=run.id)) == [] and FakeBuilder.briefs == []


def _sealed_sandbox_stand_in(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """The test executor a sealed prod worker would use, stood in by a local one: the subject
    here is where the factory's BUILDER runs, not where the tests run."""
    monkeypatch.setattr(h.worker, "_executor", lambda ctx: LocalExecutor())


def test_a_prod_worker_refuses_a_factory_run_because_factory_builds_run_on_the_host(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A factory build is handed a host worktree and never a container (``_run_factory``
    passes none to the builder), so a sealed prod posture must not run one: /health says
    "sealed", and a factory run on the host would make that untrue (ADR-0023)."""
    _multiply_backlog(h)
    FakeBuilder.briefs = []
    _sealed_sandbox_stand_in(h, monkeypatch)
    h.worker.settings = replace(h.settings, refuse_unsealed=True, builder_executor="docker")
    run = h.enqueue("factory", ladder_json=["fake:m0"])
    done = h.run_one()
    assert done.status == STATUS_FAILED
    assert done.error.startswith("sandbox unavailable"), done.error
    assert "factory" in done.error and "CRB_ALLOW_UNSEALED_PROD" in done.error
    assert list(h.worker.ledger.rows(run_id=run.id)) == [] and FakeBuilder.briefs == []


def test_a_prod_worker_under_the_override_stamps_every_factory_run(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the override, a factory run may build on the host, and its apparatus says so —
    even on a worker whose replay posture is sealed and so carries no override of its own."""
    _multiply_backlog(h)
    _sealed_sandbox_stand_in(h, monkeypatch)
    h.worker.settings = replace(
        h.settings,
        env="prod",
        executor="docker",
        builder_executor="docker",
        unsealed_override={},
        unsealed_override_ack={"by": "root", "reason": "evaluation"},
    )
    h.enqueue("factory", ladder_json=["fake:m0"])
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    stamp = done.apparatus_json["unsealed_prod_override"]
    assert stamp["builder_executor"] == "host" and stamp["run_kind"] == "factory"
    assert stamp["override"] == "CRB_ALLOW_UNSEALED_PROD" and stamp["adr"] == "0023"
    # G-663: the admin who set the override is named beside it on every run it admits
    assert stamp["acknowledged_by"] == "root"


def test_a_sealed_prod_worker_under_the_override_stamps_a_run_that_asks_for_local(
    h: Harness,
) -> None:
    """P-256: a worker whose defaults are sealed (docker and docker) but that starts under
    the override admits a run asking for the local executor in its own parameters. That run
    executes unsealed, so its apparatus must carry the override and the name of the admin
    who set it — the worker-wide stamp is empty because the DEFAULTS are sealed."""
    h.worker.settings = replace(
        h.settings,
        env="prod",
        executor="docker",
        builder_executor="docker",
        refuse_unsealed=False,
        unsealed_override={},
        unsealed_override_ack={"by": "root", "reason": "evaluation"},
    )
    h.enqueue("probe", params_json={"executor": "local"})
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    stamp = done.apparatus_json["unsealed_prod_override"]
    assert stamp["sandbox_executor"] == "local" and stamp["acknowledged_by"] == "root"
    assert stamp["override"] == "CRB_ALLOW_UNSEALED_PROD" and stamp["adr"] == "0023"
    # a run that keeps the sealed default stamps nothing: it ran sealed
    h.enqueue("probe")
    sealed = h.run_one()
    assert "unsealed_prod_override" not in (sealed.apparatus_json or {})


def test_a_dev_worker_stamps_no_override_on_a_factory_run(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    _multiply_backlog(h)
    _sealed_sandbox_stand_in(h, monkeypatch)
    h.enqueue("factory", ladder_json=["fake:m0"])
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    assert "unsealed_prod_override" not in done.apparatus_json


# --- ADR-0019: the posture gate --------------------------------------------------------------


def _records(h: Harness) -> list[Any]:
    from crb.core.qualify import Qualification
    from crb.store.models import TaskQualification

    with h.factory() as s:
        rows = s.execute(select(TaskQualification).order_by(TaskQualification.seq)).scalars().all()
        return [Qualification.from_dict(r.body_json) for r in rows]


def test_replay_with_no_qualified_task_fails_before_spend(h: Harness) -> None:
    run = h.enqueue("replay", params_json={"qualify_first": False})
    done = h.run_one()
    assert done.status == STATUS_FAILED
    assert done.error.startswith("POSTURE_UNQUALIFIED: 0 of 1 task(s) qualified")
    assert "crb repo qualify" in done.error and "no model money" in done.error
    assert FakeBuilder.briefs == []  # no builder was called
    assert list(h.worker.ledger.rows(run_id=run.id)) == []
    ev = h.events(run.id)
    refused = next(e for e in ev if e.action == "run.posture_refused")
    assert refused.payload["code"] == "POSTURE_UNQUALIFIED"
    assert refused.payload["refusals"][0]["code"] == "POSTURE_UNQUALIFIED"
    assert refused.payload["refusals"][0]["fix"]
    assert any(e.action == "run.posture" for e in ev)


def test_qualify_first_qualifies_then_replays_only_the_qualified(h: Harness) -> None:
    green = h.pyrepo.add_green_commit()
    h.add_task(
        h.pyrepo.feat_task(
            task_id=green,
            test_files=[pr.TEST_CALC],
            target_tests=[pr.TEST_CALC],
            baseline_failing=[],
            subject="refactor: green at parent",
        )
    )
    run = h.enqueue("replay")
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    assert done.counts_json["tasks"] == 1 and done.counts_json["clean"] == 1
    assert done.counts_json["refusals"] == {"QUAL_NOT_RED": 1}
    records = _records(h)
    assert sorted(q.state for q in records) == ["qualified", "unqualified"]
    (row,) = list(h.worker.ledger.rows(run_id=run.id))
    assert row.labels["qualification_id"] == next(
        q.qualification_id for q in records if q.is_qualified
    )
    assert row.labels["posture_id"] == _live_posture(h).posture_id
    ev = h.events(run.id)
    canary = next(e for e in ev if e.action == "run.canary")
    assert canary.payload["clean"] is True
    assert sum(1 for e in ev if e.action == "qualify.task") == 2


def test_posture_drift_fails_at_zero_spend(h: Harness) -> None:
    _seed_qualified(h, h.pyrepo.feat_task(), posture_id="pst_" + "d" * 24)
    run = h.enqueue("replay", params_json={"qualify_first": False})
    done = h.run_one()
    assert done.status == STATUS_FAILED and done.error.startswith("POSTURE_DRIFT:")
    assert "qualify again" in done.error
    assert FakeBuilder.briefs == [] and list(h.worker.ledger.rows(run_id=run.id)) == []


def test_canary_not_clean_fails_before_the_first_build(h: Harness) -> None:
    bad = h.pyrepo.add_bad_gold_commit()
    task = h.pyrepo.feat_task(
        task_id=bad,
        test_files=[pr.TEST_MULTIPLY],
        target_tests=[pr.TEST_MULTIPLY],
        baseline_failing=[],
        subject="feat: add multiply (breaks add)",
    )
    with h.factory() as s:
        s.query(Task).delete()
        s.commit()
    h.add_task(task)
    # qualified here once — the posture then moved under it (the gold now breaks belt 3)
    _seed_qualified(h, task)
    run = h.enqueue("replay")
    done = h.run_one()
    assert done.status == STATUS_FAILED and done.error.startswith("POSTURE_CANARY_FAILED:")
    assert FakeBuilder.briefs == [] and list(h.worker.ledger.rows(run_id=run.id)) == []
    canary = next(e for e in h.events(run.id) if e.action == "run.canary")
    assert canary.payload["clean"] is False


def test_two_environment_rows_stop_the_run_and_revoke_the_qualifications(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from crb.core.grade import BLAME_GOLD_GREEN, ControlRun
    from crb.server import posture_gate

    class RedGold:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        def control(self, scope: Any, *, why: str, allow_failing: Any = None) -> ControlRun:
            return ControlRun(BLAME_GOLD_GREEN, tuple(scope), False, rc=1, tail="lookup failed")

    monkeypatch.setattr(posture_gate, "GoldWitness", RedGold)
    monkeypatch.setitem(
        builders_pkg._REGISTRY, "fake", lambda **cfg: FakeBuilder(behaviour="noop", **cfg)
    )
    bad = h.pyrepo.add_bad_gold_commit()
    second = h.pyrepo.feat_task(
        task_id=bad,
        test_files=[pr.TEST_MULTIPLY],
        target_tests=[pr.TEST_MULTIPLY],
        baseline_failing=[],
    )
    h.add_task(second)
    _seed_qualified(h, h.pyrepo.feat_task())
    _seed_qualified(h, second)
    run = h.enqueue(
        "replay",
        ladder_json=["fake:m0", "fake:m1"],
        params_json={"canary": False, "task_ids": [h.pyrepo.feat_sha, bad]},
    )
    done = h.run_one()
    assert done.status == STATUS_FAILED and done.error.startswith("environment: 2 consecutive")
    rows = list(h.worker.ledger.rows(run_id=run.id))
    assert len(rows) == 2 and all(r.failure_kind == "harness" for r in rows)
    assert all(r.labels["env_code"] == "GOLD_CONTROL_RED" for r in rows)
    assert all(r.trial == "r1" for r in rows)  # each ladder stopped at its first rung
    states = [q.state for q in _records(h)]
    assert states.count("revoked") == 2  # both qualifications revoked, as new records
    assert any(e.action == "run.environment_stop" for e in h.events(run.id))


def test_only_a_control_that_ran_red_revokes_a_qualification(tmp_path: Path) -> None:
    """QUAL_ENV_WITNESS_RED says the gold failed here during a replay, so only a row whose
    control RAN red (``env_code`` ``GOLD_CONTROL_RED``) may revoke. An environment row no
    control witnessed (``TEST_RUN_ENVIRONMENT``) leaves the record in force."""
    from types import SimpleNamespace

    from crb.core.execution import LocalExecutor
    from crb.server.posture_gate import PostureGate
    from fixtures.posture import discovery_qualification

    task = pr.build(tmp_path / "repo").feat_task()
    q = discovery_qualification(task, LocalExecutor())
    gate = PostureGate(
        repo=None,  # type: ignore[arg-type]  # on_environment reads none of these
        config=None,  # type: ignore[arg-type]
        runner=None,  # type: ignore[arg-type]
        executor=None,  # type: ignore[arg-type]
        scratch=tmp_path,
        provider=None,  # type: ignore[arg-type]
        posture=None,  # type: ignore[arg-type]
    )
    gate.qualifications[task.task_id] = q
    unwitnessed = SimpleNamespace(
        error="environment: tree_copy_failed", labels={"env_code": "TEST_RUN_ENVIRONMENT"}
    )
    gate.on_environment(task, unwitnessed)  # type: ignore[arg-type]
    assert gate.qualifications[task.task_id] is q and q.is_qualified
    red = SimpleNamespace(
        error="environment: gold control red in pst_x: belt 2",
        labels={"env_code": "GOLD_CONTROL_RED"},
    )
    gate.on_environment(task, red)  # type: ignore[arg-type]
    revoked = gate.qualifications[task.task_id]
    assert revoked.state == "revoked" and revoked.code == "QUAL_ENV_WITNESS_RED"


def test_the_gate_hashes_each_sealed_set_once_and_fails_closed_on_first_use(
    tmp_path: Path,
) -> None:
    """CodeRabbit on PR #56: ``context_for`` re-hashed every sealed set for every task, so
    N tasks sharing one lockfile hashed the same ``node_modules`` N times. The gate verifies
    a key once; a set that fails is never remembered as verified, so every use of it keeps
    stopping the run ``BUNDLE_INTEGRITY`` (the mount's own write-bit check,
    ``validate_mount``, still runs at every use)."""
    from crb.core.deps import DepsBinding, ProvisionRefused, TaskDeps
    from crb.core.qualify import adhoc_posture
    from crb.server.posture_gate import PostureGate
    from fixtures.posture import discovery_qualification

    repo = pr.build(tmp_path / "repo")
    first = repo.feat_task()
    second = replace(first, task_id="f" * 40)
    ex = LocalExecutor()

    class CountingProvider:
        deps_mode = "host-env"

        def __init__(self) -> None:
            self.verified: list[tuple[str, ...]] = []
            self.broken = False

        def resolve(self, *a: Any, **k: Any) -> TaskDeps:
            shared = DepsBinding(role="gold", lang="python", key="k-shared", digest="sha256:0")
            return TaskDeps.uniform(shared, mode="host-env", lang="python")

        def verify(self, deps: TaskDeps) -> None:
            self.verified.append(deps.keys)
            if self.broken:
                raise ProvisionRefused("BUNDLE_INTEGRITY", "k-shared: digest does not match")

    provider = CountingProvider()
    gate = PostureGate(
        repo=repo.repo,
        config=repo.config,
        runner=PytestRunner(repo.config),
        executor=ex,
        scratch=tmp_path / "scratch",
        provider=provider,  # type: ignore[arg-type]
        posture=adhoc_posture(ex),
    )
    for t in (first, second):  # two tasks citing one set (one lockfile), resolved once each
        gate.qualifications[t.task_id] = discovery_qualification(t, ex)
        gate._deps[t.task_id] = provider.resolve()
    for t in (first, second, first):
        gate.context_for(t)
    assert provider.verified == [("k-shared",)]  # one hash for three uses of one set

    broken = CountingProvider()
    broken.broken = True
    gate.provider = broken  # type: ignore[assignment]
    gate._verified.clear()
    for _ in range(2):  # fail-closed on first use, and a failure is never remembered
        with pytest.raises(ProvisionRefused, match="BUNDLE_INTEGRITY"):
            gate.context_for(first)
    assert broken.verified == [("k-shared",), ("k-shared",)]


def test_qualify_run_spends_nothing(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*a: Any, **k: Any) -> Any:
        raise AssertionError("a qualify run constructed a builder")

    monkeypatch.setattr(builders_pkg, "get_builder", refuse)
    monkeypatch.setattr(builders_pkg, "builder_for_rung", refuse)
    run = h.enqueue("qualify")
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    assert done.counts_json["qualified"] == 1 and done.counts_json["unqualified"] == 0
    assert done.counts_json["cost_usd"] == 0.0 and done.counts_json["by_code"] == {}
    assert done.counts_json["posture_id"] == _live_posture(h).posture_id
    assert list(h.worker.ledger.rows(run_id=run.id)) == []  # no grade row: nothing was built
    (q,) = _records(h)
    assert q.is_qualified and q.run_id == run.id
    assert any(e.action == "qualify.done" for e in h.events(run.id))


def test_mine_in_docker_without_provisioning_says_what_to_do(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sealed posture as shipped cannot load a module graph (ADR-0019 D1): the mine's
    qualification refuses each candidate QUAL_ENV_UNLOADABLE and the run stops with what to
    do, instead of mining tasks every replay would then charge to the model. (The real
    sealed image is exercised in tests/test_posture_docker.py.)"""
    import sys as _sys

    from crb.core.execution import Command

    def unloadable(self: Any, root: Path, scope: Any, *, executor: Any, timeout: int) -> Command:
        return Command((_sys.executable, "-c", "import sys; sys.exit(1)"), root, timeout=timeout)

    monkeypatch.setattr(PytestRunner, "env_probe_command", unloadable)
    for i in range(3):
        pr._write(h.pyrepo.path, pr.SRC, pr.SRC_FEAT.replace("A tiny calculator.", f"v{i}."))
        pr._write(
            h.pyrepo.path,
            pr.TEST_CALC,
            pr.TEST_CALC_SRC + f"\n\ndef test_zero_{i}():\n    assert add(0, 0) == 0\n",
        )
        pr._commit(h.pyrepo.path, f"refactor: v{i}")
    run = h.enqueue("mine", params_json={"target": 5})
    done = h.run_one()
    assert done.status == STATUS_FAILED
    assert "QUAL_ENV_UNLOADABLE" in done.error
    assert "switch provisioning on and qualify" in done.error
    skips = [e for e in h.events(run.id) if e.action == "mine.skip"]
    assert skips and all(e.payload.get("code") == "QUAL_ENV_UNLOADABLE" for e in skips)
