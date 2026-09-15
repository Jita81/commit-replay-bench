"""The worker clones a URL-registered repo on its first run (W3-B): into
``<home>/repos/<name>``, persisted on the row, ``repo.clone.start`` / ``repo.clone.done``
on the run's trace, credentials never in an event or an error, policy-refused sources
fail the run closed, and a second run reuses the clone. Also: ``params.builder_config``
reaches the builder as constructor overrides and is stamped into the apparatus.

Navigation
----------
What it is:   The worker's clone-on-first-run test suite (W3-B) and ``params.builder_config``
              reaching the builder.
What it does: Pins that a URL-registered repo is cloned into ``<home>/repos/<name>`` on its first
              run with the path persisted and ``repo.clone.start`` / ``repo.clone.done`` on the
              trace, that an unusable clone path with a URL is re-cloned, that a policy-refused
              URL fails the run closed, that no URL and no clone keeps the old errors, that
              credentials in the URL never reach events or errors; and that ``builder_config``
              reaches the builder as constructor overrides and is stamped into the apparatus
              (absent means none), that bare rung labels mean the run's own builder / model and
              fail closed without a model, and that explicit labels mix with bare ones.
How:          ``fixtures.remote.bare_remote`` over ``pyrepo`` with the developer switch;
              ``RecordingBuilder`` captures its constructor kwargs; ``test_worker``'s harness.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/server/worker.py (under test), src/crb/core/git.py (``clone_repo`` and
              the policy), tests/fixtures/remote.py, tests/test_server_routes_w3b.py (the API's
              half), tests/test_git_clone.py (the policy's own suite), tests/test_worker.py
Tested by:    tests/test_worker_clone.py
Touch when:   the clone destination or the URL policy changes (mirror the route and CLI suites);
              a builder gains a config key the worker must pass through.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest

import crb.builders as builders_pkg
from crb.core.git import LOCAL_CLONE_ENV, GitRepo
from crb.observability.events import StepStatus
from crb.store.jobs import STATUS_FAILED, STATUS_SUCCEEDED
from crb.store.models import Repo, Run
from fixtures import pyrepo as pr
from fixtures.remote import bare_remote
from test_worker import FakeBuilder, Harness


@pytest.fixture
def remote(pyrepo: pr.PyRepo, tmp_path: Path) -> str:
    """A bare ``file://`` remote of ``pyrepo`` (each case sets the developer switch itself)."""
    return bare_remote(pyrepo.path, tmp_path / "remote.git")


@pytest.fixture
def h(tmp_path: Path, pyrepo: pr.PyRepo) -> Harness:
    """An EMPTY worker harness (no repo registered — the cases register URL repos themselves)."""
    return Harness(tmp_path, pyrepo)


def add_url_repo(h: Harness, url: str, *, clone_path: str = "") -> None:
    """Register the fixture repository by ``url`` with the given (possibly empty) ``clone_path``."""
    cfg = h.pyrepo.config.to_dict()
    cfg["path"] = clone_path
    cfg["url"] = url
    with h.factory() as s:
        s.add(
            Repo(
                name=pr.REPO_NAME,
                language="python",
                runner="pytest",
                clone_path=clone_path,
                url=url,
                config_json=cfg,
            )
        )
        s.commit()


def test_first_run_clones_by_url_and_persists_the_path(
    h: Harness, remote: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(LOCAL_CLONE_ENV, "1")
    add_url_repo(h, remote)  # the fixture's config (src/ layout + python) is what the row carries
    h.add_task(h.pyrepo.feat_task())
    run = h.queue.enqueue(Run(repo=pr.REPO_NAME, kind="probe", actor="tester"))
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    dest = h.home / "repos" / pr.REPO_NAME
    assert GitRepo(dest).is_repo() and GitRepo(dest).rev_parse() == h.pyrepo.docs_sha
    assert GitRepo(dest).log_shas(10) == [
        h.pyrepo.docs_sha,
        h.pyrepo.feat_sha,
        h.pyrepo.initial_sha,
    ]
    row = h.repo_row()
    assert row.clone_path == str(dest) and row.config_json["path"] == str(dest)
    assert row.url == remote
    # events, in order, on the run's trace, stage=system
    ev = h.events(run.id)
    actions = [e.action for e in ev]
    assert actions[:3] == ["run.claimed", "repo.clone.start", "repo.clone.done"]
    start = ev[1]
    assert start.stage == "system" and start.payload == {"url": remote, "dest": str(dest)}
    finish = ev[2]
    assert finish.stage == "system" and finish.status is StepStatus.OK
    assert finish.duration_ms is not None and finish.duration_ms >= 0
    assert finish.payload["head"] == h.pyrepo.docs_sha and finish.payload["dest"] == str(dest)
    # the probe ran against the fresh clone
    probe_start = next(e for e in ev if e.action == "probe.start")
    assert probe_start.payload["path"] == str(dest)
    # a second run finds the persisted clone: no clone events, same path
    run2 = h.queue.enqueue(Run(repo=pr.REPO_NAME, kind="probe", actor="tester"))
    done2 = h.run_one()
    assert done2.status == STATUS_SUCCEEDED, done2.error
    assert not [e for e in h.events(run2.id) if e.action.startswith("repo.clone")]
    assert sorted(p.name for p in (h.home / "repos").iterdir()) == [pr.REPO_NAME]


def test_unusable_clone_path_with_url_is_recloned(
    h: Harness, remote: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A row whose ``clone_path`` points at nothing (or a plain directory) but carries a
    URL is cloned rather than failed — the path is stale, the URL is the truth."""
    monkeypatch.setenv(LOCAL_CLONE_ENV, "1")
    stale = tmp_path / "stale"
    stale.mkdir()
    add_url_repo(h, remote, clone_path=str(stale))
    h.queue.enqueue(Run(repo=pr.REPO_NAME, kind="probe", actor="tester"))
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    assert h.repo_row().clone_path == str(h.home / "repos" / pr.REPO_NAME)


def test_policy_refused_url_fails_the_run_closed(
    h: Harness, remote: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(LOCAL_CLONE_ENV, raising=False)
    add_url_repo(h, remote)  # file:// without the dev switch
    run = h.queue.enqueue(Run(repo=pr.REPO_NAME, kind="probe", actor="tester"))
    done = h.run_one()
    assert (
        done.status == STATUS_FAILED and "refused" in done.error and LOCAL_CLONE_ENV in done.error
    )
    assert not (h.home / "repos" / pr.REPO_NAME).exists()
    assert h.repo_row().clone_path == ""
    ev = h.events(run.id)
    clone_done = next(e for e in ev if e.action == "repo.clone.done")
    assert clone_done.status is StepStatus.ERROR and clone_done.error_code == "CloneUrlError"


def test_no_url_and_no_clone_keeps_the_old_errors(h: Harness) -> None:
    add_url_repo(h, "")
    h.queue.enqueue(Run(repo=pr.REPO_NAME, kind="probe", actor="tester"))
    done = h.run_one()
    assert done.status == STATUS_FAILED and "has no clone path" in done.error


def test_credentials_in_the_url_never_reach_events_or_errors(h: Harness) -> None:
    url = "https://alice:s3cretT0ken@127.0.0.1:1/org/repo.git"  # nothing listens: fails fast
    add_url_repo(h, url)
    run = h.queue.enqueue(Run(repo=pr.REPO_NAME, kind="probe", actor="tester"))
    done = h.run_one()
    assert (
        done.status == STATUS_FAILED
        and "clone of https://127.0.0.1:1/org/repo.git failed" in done.error
    )
    assert "s3cretT0ken" not in done.error and "alice" not in done.error
    for e in h.events(run.id):
        blob = repr(e.to_dict())
        assert "s3cretT0ken" not in blob and "alice:" not in blob
    start = next(e for e in h.events(run.id) if e.action == "repo.clone.start")
    assert start.payload["url"] == "https://127.0.0.1:1/org/repo.git"


# --- builder_config passthrough --------------------------------------------------------------


class RecordingBuilder(FakeBuilder):
    """A fake that records the constructor kwargs the adapter hands it."""

    name = "recording"
    seen: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, *, model: str, provider: str = "", **kw: Any) -> None:
        super().__init__(model=model, provider=provider, behaviour=str(kw.pop("behaviour", "gold")))
        RecordingBuilder.seen.append({"model": model, "provider": provider, **kw})


@pytest.fixture
def hr(tmp_path: Path, pyrepo: pr.PyRepo, monkeypatch: pytest.MonkeyPatch) -> Harness:
    """The harness with the repo and task on file and ``RecordingBuilder`` registered as
    ``recording`` (its ``seen`` list reset).
    """
    monkeypatch.setitem(builders_pkg._REGISTRY, "recording", RecordingBuilder)
    RecordingBuilder.seen = []
    harness = Harness(tmp_path, pyrepo)
    harness.add_repo()
    harness.add_task(pyrepo.feat_task())
    return harness


def test_builder_config_reaches_the_builder_and_the_apparatus(hr: Harness) -> None:
    cfg = {"auth": "cli", "effort": "high", "extra_args": ["--x"]}
    run = hr.enqueue("replay", ladder_json=["recording:m@p"], params_json={"builder_config": cfg})
    done = hr.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    assert RecordingBuilder.seen == [{"model": "m", "provider": "p", **cfg}]
    assert done.apparatus_json["extra"]["builder_config"] == cfg
    (row,) = hr.worker.ledger.rows(run_id=run.id)
    assert row.clean and row.model == "m"


def test_builder_config_absent_means_no_overrides(hr: Harness) -> None:
    hr.enqueue("replay", ladder_json=["recording:m@p"])
    done = hr.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    assert RecordingBuilder.seen == [{"model": "m", "provider": "p"}]
    assert done.apparatus_json["extra"]["builder_config"] == {}


# --- bare rung labels (the API's default ladder) ----------------------------------------------


def test_bare_rung_labels_mean_the_runs_own_builder_model(hr: Harness) -> None:
    """``POST /runs`` stores ``ladder_json=["r1"]`` by default; the worker resolves a bare
    label to the run's ``builder:model@provider`` (found by the UI walkthrough: every
    API-created replay used to fail with ``rung 'r1' must look like builder:model``)."""
    run = hr.enqueue(
        "replay", builder="recording", model="m", provider="p", ladder_json=["r1", "r2"]
    )
    done = hr.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    assert done.ladder_json == ["r1", "r2"]  # the declared ladder is kept as written
    rows = list(hr.worker.ledger.rows(run_id=run.id))
    # rung 1 already clean → one attempt; the rung climbed only on a non-clean attempt
    assert [(r.trial, r.builder, r.model, r.provider) for r in rows] == [
        ("r1", "recording", "m", "p")
    ]
    assert rows[0].labels["rung"] == "r1" and rows[0].clean


def test_bare_rung_labels_without_a_model_fail_closed(hr: Harness) -> None:
    hr.enqueue("replay", builder="recording", model="", ladder_json=["r1"])
    done = hr.run_one()
    assert done.status == STATUS_FAILED and "needs builder + model" in done.error


def test_explicit_labels_mix_with_bare_ones(hr: Harness) -> None:
    builders_pkg._REGISTRY["recording"] = lambda **cfg: RecordingBuilder(
        behaviour="noop" if cfg["model"] == "m" else "gold", **cfg
    )
    run = hr.enqueue(
        "replay", builder="recording", model="m", ladder_json=["r1", "recording:strong@q"]
    )
    done = hr.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    rows = list(hr.worker.ledger.rows(run_id=run.id))
    assert [(r.trial, r.model, r.provider, r.clean) for r in rows] == [
        ("r1", "m", "", False),
        ("r2", "strong", "q", True),
    ]
