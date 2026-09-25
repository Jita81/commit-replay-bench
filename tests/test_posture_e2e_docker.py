"""The sealed posture end to end: provisioned per task, qualified, replayed, and never blaming
the model when its dependencies go (ADR-0019, streams Q and D together).

This is the integration the two streams could not prove apart. A Go repository with a
third-party module is qualified through the run's own gate in the shipped sandbox image
with ``--network=none``, its modules provisioned for THIS task from a ``file://`` mirror
(no network at all) into one sealed, read-only cache; the gold replays clean through the
run loop; then the cache is emptied and the same run is refused ``BUNDLE_INTEGRITY``
before any builder is called, a trial graded past the gate is an environment row
(``harness``), never ``builder_red``, and a second qualification is ``QUAL_ENV_UNLOADABLE``.

Navigation
----------
What it is:   The docker-marked end-to-end proof of the sealed posture: per-task provisioning
              (stream D) under posture-relative qualification and the blame witness
              (stream Q).
What it does: Builds the fixture repository and its module mirror, resolves the live posture,
              admits the task through ``PostureGate`` (qualify-first), replays the gold
              through ``crb.core.run.run`` and asserts a clean row; empties the sealed cache and
              asserts the refusal before any builder call, the witnessed environment row and
              the unloadable re-qualification.
How:          Real ``docker`` (colima locally, CI's sandbox-images job), the shipped Go
              sandbox image and the pinned Go fetch image; a counting build function stands in
              for a builder, so nothing reaches a model.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0019-qualification-is-posture-relative.md,
              docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/server/posture_gate.py (``PostureGate``: admission and ``context_for``),
              src/crb/provision/__init__.py (``SealedProvider``), src/crb/core/qualify.py,
              src/crb/core/grade.py (the witness), src/crb/core/run.py (the run loop),
              tests/fixtures/goproxy.py and tests/fixtures/langs/gorepo_deps.py (the
              repository and its mirror), tests/conftest_langs.py (the images)
Tested by:    tests/test_posture_e2e_docker.py
Touch when:   the sealed posture's contract changes — provisioning, qualification, the gate or
              the witness; docs/reviews/2026-09-25-sealed-posture.md repeats this proof on
              cobra.
"""

from __future__ import annotations

import importlib
import os
import stat
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from crb.core import ledger as lg
from crb.core.deps import ProvisionRefused
from crb.core.evidence import BuilderRef
from crb.core.execution import DockerExecutor, DockerSettings
from crb.core.git import GitRepo
from crb.core.grade import grade
from crb.core.qualify import QUAL_ENV_UNLOADABLE, qualify_task
from crb.core.run import BuildAttempt, RunSpec, run
from crb.core.runners import get_runner
from crb.core.spec import TaskSpec
from crb.core.workspace import Workspace
from crb.provision import SealedProvider, make_deps_provider
from crb.provision.config import DEFAULT_GO_IMAGE, ProvisionConfig
from crb.provision.store import remove_tree
from crb.server.posture_gate import PostureGate, resolve_run_posture

try:
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover
    import conftest_langs as langs

gorepo_deps = langs.fixture_module("gorepo_deps")
goproxy = importlib.import_module("fixtures.goproxy")

pytestmark = [pytest.mark.docker, pytest.mark.slow, pytest.mark.sandbox_images]


@pytest.fixture
def scratch() -> Iterator[Path]:
    reason = langs.docker_unavailable_reason()
    if reason:
        pytest.skip(reason)
    langs.require_docker_image(DEFAULT_GO_IMAGE, "the pinned Go fetch image")
    root = langs.CACHE_DIR / "provision" / f"e2e-{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    yield root
    remove_tree(root)


def _empty(sealed: Path) -> int:
    """Remove every file under a sealed set's module cache, keeping it read-only: the
    cache the qualification saw is gone, the manifest still names it."""
    n = 0
    for d, _dirs, _files in os.walk(sealed):
        Path(d).chmod(Path(d).stat().st_mode | stat.S_IWUSR)
    for d, dirs, files in os.walk(sealed, topdown=False):
        for f in files:
            (Path(d) / f).unlink()
            n += 1
        for sd in dirs:
            (Path(d) / sd).rmdir()
    sealed.chmod(0o555)
    return n


def test_the_sealed_posture_provisions_qualifies_replays_and_never_blames_the_model(
    scratch: Path,
) -> None:
    image = langs.ensure_shipped_sandbox_image("go")
    mirror = goproxy.build(scratch / "mirror")
    root, feat = gorepo_deps.build(scratch / "repo")
    repo = GitRepo(root)
    config = gorepo_deps.config()
    runner = get_runner(config)
    executor = DockerExecutor(DockerSettings(image=image))  # the default tree: a copy
    store = scratch / "deps"
    provider = make_deps_provider(
        ProvisionConfig(enabled=True, env="dev", store=store, go_proxy=f"file://{mirror}"),
        executor_kind="docker",
        probe_image=image,
    )
    assert isinstance(provider, SealedProvider)
    posture = resolve_run_posture(executor, runner, config, provider, root=root)
    assert posture.posture_class == "docker/copy/sealed" and posture.network == "none"

    cand = langs.feat_candidate(repo, config, feat)
    task = TaskSpec(
        task_id=feat,
        repo=config.name,
        subject="feat: bye",
        authored=repo.author_date(feat),
        test_files=cand.test_files,
        src_files=tuple(f for f in cand.files if f not in cand.test_files),
        target_tests=runner.target_scope(cand.test_files),
        belt_scope=(),
        language="go",
    )
    events: list[str] = []

    def gate() -> PostureGate:
        return PostureGate(
            repo=repo,
            config=config,
            runner=runner,
            executor=executor,
            scratch=scratch / "work",
            provider=provider,
            posture=posture,
            timeout=600,
            run_id="e2e",
            on_event=lambda a, p: events.append(a),
        )

    def spec(g: PostureGate, name: str) -> RunSpec:
        return RunSpec(
            run_id=f"e2e-{name}",
            config=config,
            runner=runner,
            executor=executor,
            scratch=scratch / "work",
            ledger=lg.JsonlLedger(scratch / f"ledger-{name}.jsonl"),
            evidence_dir=scratch / f"evidence-{name}",
            context_for=g.context_for,
            posture=posture.to_dict(),
        )

    calls: list[str] = []

    def gold_fn(ws: Workspace, t: TaskSpec, mode: str, rung: str) -> BuildAttempt:
        calls.append("gold")
        ws.overlay_sources(t.src_files)
        return BuildAttempt(BuilderRef(name="fixture_gold", model="gold", mode=mode))

    def counting_fn(ws: Workspace, t: TaskSpec, mode: str, rung: str) -> BuildAttempt:
        calls.append("counting")
        return BuildAttempt(BuilderRef(name="counting", model="none", mode=mode))

    # (a) qualified in the sealed posture, its dependencies provisioned for THIS task
    g1 = gate()
    admitted = g1.admit([task])
    q = g1.qualifications[feat]
    assert admitted == [task], f"{q.code}: {q.message}"
    assert q.posture_id == posture.posture_id and q.env_probe["ok"] is True
    assert q.deps["mode"] == "sealed" and q.deps["keys"]
    assert events.count("provision.seal") == 2  # the union cache and the builder's
    # (b) the baseline was measured HERE: the test that writes into its package is green in
    # the throwaway copy, so it is not in the baseline (D5)
    assert q.red["kind"] in {"build_failed", "tests_failed"}
    assert gorepo_deps.WRITER_TEST_ID not in q.baseline

    # the gold replays clean through the run loop in the same posture
    summary = run(spec(g1, "gold"), repo, admitted, gold_fn)
    rows = list(lg.JsonlLedger(scratch / "ledger-gold.jsonl").rows())
    assert summary.clean == 1 and calls == ["gold"], [r.error for r in rows]
    assert rows[0].clean and rows[0].labels["posture_id"] == posture.posture_id
    ctx = g1.context_for(task)
    deps = g1.deps_for(task)

    # (c) the environment breaks: the sealed module cache is emptied
    assert _empty(store / "go" / deps.gold.key / "gomod") > 0

    # the run's gate refuses BEFORE any builder call, and writes no row
    g2 = gate()
    admitted2 = g2.admit([task], known={feat: q})
    with pytest.raises(ProvisionRefused) as refused:
        run(spec(g2, "broken"), repo, admitted2, counting_fn)
    assert refused.value.code == "BUNDLE_INTEGRITY" and refused.value.scope == "run"
    assert "counting" not in calls
    assert not (scratch / "ledger-broken.jsonl").exists()

    # past the gate, the grade itself: the do-nothing trial and the gold are both red in
    # this posture — an environment row, never builder_red
    ws = Workspace.create(repo, feat, scratch / "work" / "noop", config=config)
    try:
        ws.overlay_tests(task.test_files)
        res = grade(ws, ctx.spec(task), ctx=ctx, config=config, runner=runner, executor=executor)
    finally:
        ws.remove()
    row = lg.grade_row_from_result(res, ctx.spec(task), pack_hash="c" * 64)
    assert res.error.startswith(f"environment: gold control red in {posture.posture_id}")
    assert not res.blamed and row.failure_kind == lg.FAILURE_HARNESS
    assert row.failure_kind != lg.FAILURE_BUILDER_RED

    # and a second qualification in the broken environment refuses the task
    q2 = qualify_task(
        repo,
        config,
        task,
        posture=posture,
        deps=provider,
        runner=runner,
        executor=executor,
        scratch=scratch / "work",
        timeout=600,
    )
    assert q2.state == "unqualified" and q2.code == QUAL_ENV_UNLOADABLE, q2.message
