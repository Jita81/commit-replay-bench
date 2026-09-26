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
              fail closed without a model, and that explicit labels mix with bare ones. Also
              the use-time clone-path rule (D2): a symbolic link off ``<home>/repos`` — planted
              on the stored path, in ``config_json["path"]``, swapped in after registration, or
              at the clone destination — is refused before any git process starts; the clone
              destination is held to identity (exactly ``<root>/<name>``, never a link, in five
              link shapes); an AST ratchet holds every use site to ``confined_clone_path``; and
              a discovery test keeps that list equal to every function in ``crb.server`` that
              opens git.
How:          ``fixtures.remote.bare_remote`` over ``pyrepo`` with the developer switch;
              ``RecordingBuilder`` captures its constructor kwargs; ``test_worker``'s harness;
              ``_spy_git`` records every git process ``crb.core.git`` starts.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/server/worker.py (under test), src/crb/core/git.py (``clone_repo`` and
              the policy), src/crb/server/routes/repos.py (``confined_clone_path``), tests/fixtures/remote.py, tests/test_server_routes_w3b.py (the API's
              half), tests/test_git_clone.py (the policy's own suite), tests/test_worker.py
Tested by:    tests/test_worker_clone.py
Touch when:   the clone destination or the URL policy changes (mirror the route and CLI suites);
              a builder gains a config key the worker must pass through; a new place opens a
              stored clone path (add it to ``_USE_SITES``; any other git opener in
              ``crb.server`` goes on ``_NOT_A_STORED_CLONE`` with its reason).
"""

from __future__ import annotations

import ast
import shutil
from pathlib import Path
from typing import Any, ClassVar

import pytest

import crb.builders as builders_pkg
import crb.core.git as git_mod
from crb.core.git import LOCAL_CLONE_ENV, GitRepo, clone_repo
from crb.observability.events import StepStatus
from crb.server.routes.repos import clone_root, confined_clone_path
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
    # `github_app` says whether an installation token was minted for the clone (ADR-0014)
    assert start.stage == "system"
    assert start.payload == {"url": remote, "dest": str(dest), "github_app": False}
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


def test_a_clone_path_that_escapes_the_root_at_use_time_fails_the_run(
    h: Harness, tmp_path: Path
) -> None:
    """D2 follow-up: registration checks the path as written; a symbolic link planted on it
    afterwards (for example by another repository's clone) must not send a run to a
    repository elsewhere on the host. The worker re-applies the rule before it reads."""
    later = h.home / "repos" / "alpha-clone" / "link"
    add_url_repo(h, "", clone_path=str(later))  # accepted at registration: nothing there yet
    later.parent.mkdir(parents=True)
    later.symlink_to(h.pyrepo.path, target_is_directory=True)  # a git repo off the root
    assert GitRepo(later).is_repo()
    with pytest.raises(LookupError, match="clone_path_escapes"):
        h.worker._load_repo(pr.REPO_NAME)
    h.add_task(h.pyrepo.feat_task())
    run = h.queue.enqueue(Run(repo=pr.REPO_NAME, kind="probe", actor="tester"))
    done = h.run_one()
    assert done.status == STATUS_FAILED
    assert "clone_path_escapes" in (done.error or "")
    assert not [e for e in h.events(run.id) if e.action == "probe.start"]


def _spy_git(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Record the argv of every process ``crb.core.git`` starts from now on (each still
    runs). Called AFTER a test's setup, so only the code under test is counted."""
    calls: list[list[str]] = []
    real_run = git_mod.subprocess.run

    def spy(argv: Any, *a: Any, **kw: Any) -> Any:
        calls.append([str(x) for x in argv])
        return real_run(argv, *a, **kw)

    monkeypatch.setattr(git_mod.subprocess, "run", spy)
    return calls


def _clone_in_root(h: Harness, remote: str) -> Path:
    """A real clone of the fixture at ``<home>/repos/<name>`` — where the worker puts one."""
    dest = h.home / "repos" / pr.REPO_NAME
    clone_repo(remote, dest)
    return dest


def _swap_for_link(path: Path, target: Path) -> None:
    """Replace the directory at ``path`` with a symbolic link to ``target``."""
    shutil.rmtree(path)
    path.symlink_to(target, target_is_directory=True)


def test_a_link_at_the_clone_destination_is_refused_before_any_git_command(
    h: Harness, remote: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CodeRabbit on PR #52: a row with a URL and no usable clone is cloned into
    ``<home>/repos/<name>``; a symbolic link planted THERE (not on the stored path) was
    followed — ``clone_repo`` reused the repository behind it, ran git in it, and the link
    was persisted as the clone. The destination is confined like any stored path."""
    monkeypatch.setenv(LOCAL_CLONE_ENV, "1")
    add_url_repo(h, remote)  # no clone yet: the worker will clone into repos/<name>
    dest = h.home / "repos" / pr.REPO_NAME
    dest.parent.mkdir(parents=True)
    dest.symlink_to(h.pyrepo.path, target_is_directory=True)  # a git repo off the root
    calls = _spy_git(monkeypatch)
    with pytest.raises(LookupError, match="clone_path_escapes"):
        h.worker._load_repo(pr.REPO_NAME)
    assert calls == []  # refused before git ran anywhere — in the link's target above all
    row = h.repo_row()
    assert row.clone_path == "" and row.config_json["path"] == ""  # the link is not adopted


@pytest.mark.parametrize("column", ["clone_path", "config_path"])
def test_an_escaping_path_planted_after_registration_is_refused_before_any_git_command(
    h: Harness, remote: str, tmp_path: Path, column: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repository registered with a sound clone whose STORED path is later changed to one
    under the repositories directory that leads out of it — on the row's ``clone_path`` or
    in ``config_json["path"]`` (which the worker reads when the column is empty). The worker
    refuses it on the next run before any git process starts."""
    monkeypatch.setenv(LOCAL_CLONE_ENV, "1")
    good = _clone_in_root(h, remote)
    add_url_repo(h, "", clone_path=str(good))
    assert h.worker._load_repo(pr.REPO_NAME)[1].path == good.resolve()
    planted = h.home / "repos" / "other" / "link"
    planted.parent.mkdir(parents=True)
    planted.symlink_to(h.pyrepo.path, target_is_directory=True)
    with h.factory() as s:
        row = s.get(Repo, pr.REPO_NAME)
        assert row is not None
        if column == "clone_path":
            row.clone_path = str(planted)
        else:
            row.clone_path = ""
            row.config_json = {**dict(row.config_json or {}), "path": str(planted)}
        s.commit()
    calls = _spy_git(monkeypatch)
    with pytest.raises(LookupError, match="clone_path_escapes"):
        h.worker._load_repo(pr.REPO_NAME)
    assert calls == []


def test_a_link_swapped_in_after_registration_is_refused_before_any_git_command(
    h: Harness, remote: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stored path does not change, but the directory it names is replaced by a
    symbolic link to a repository elsewhere after registration (and after a good run).
    The next run refuses it before any git process starts."""
    monkeypatch.setenv(LOCAL_CLONE_ENV, "1")
    good = _clone_in_root(h, remote)
    add_url_repo(h, "", clone_path=str(good))
    assert h.worker._load_repo(pr.REPO_NAME)[1].path == good.resolve()
    _swap_for_link(good, h.pyrepo.path)
    calls = _spy_git(monkeypatch)
    with pytest.raises(LookupError, match="clone_path_escapes"):
        h.worker._load_repo(pr.REPO_NAME)
    assert calls == []
    # and through the queue: the run fails closed, nothing of the probe starts
    h.add_task(h.pyrepo.feat_task())
    run = h.queue.enqueue(Run(repo=pr.REPO_NAME, kind="probe", actor="tester"))
    done = h.run_one()
    assert done.status == STATUS_FAILED and "clone_path_escapes" in (done.error or "")
    assert not [e for e in h.events(run.id) if e.action == "probe.start"]


def _plant_destination_link(h: Harness, remote: str, shape: str) -> None:
    """Put a symbolic link of ``shape`` at the worker's clone destination
    ``<home>/repos/<name>`` — every one of them a way for "the clone" to be some other
    directory than the one the worker persists."""
    root = h.home / "repos"
    dest = root / pr.REPO_NAME
    root.mkdir(parents=True)
    if shape == "outside_repo":  # a git repository off the root
        dest.symlink_to(h.pyrepo.path, target_is_directory=True)
    elif shape == "inside_repo":  # ANOTHER repository's clone, inside the root
        clone_repo(remote, root / "other")
        dest.symlink_to(root / "other", target_is_directory=True)
    elif shape == "inside_empty_dir":  # an empty directory inside the root
        (root / "elsewhere").mkdir()
        dest.symlink_to(root / "elsewhere", target_is_directory=True)
    elif shape == "inside_dangling":  # a link to a name inside the root that is not there yet
        dest.symlink_to(root / "not-yet", target_is_directory=True)
    elif shape == "chained":  # a link inside the root, to a link inside the root, to a clone
        clone_repo(remote, root / "other")
        (root / "hop").symlink_to(root / "other", target_is_directory=True)
        dest.symlink_to(root / "hop", target_is_directory=True)
    else:  # pragma: no cover - a typo in the parametrisation
        raise AssertionError(shape)


#: Every shape of link at the clone destination. The first is the one the PR #52 review found
#: on c179260; the rest are the class, found by the review of 7d5a619 (a target inside the
#: root was confined as "inside the root" and then adopted as this repository's clone).
_DESTINATION_LINKS = [
    "outside_repo",
    "inside_repo",
    "inside_empty_dir",
    "inside_dangling",
    "chained",
]


@pytest.mark.parametrize("shape", _DESTINATION_LINKS)
def test_every_link_at_the_clone_destination_is_refused_before_any_git_command(
    h: Harness, remote: str, shape: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CodeRabbit on PR #52 (7d5a619): the destination was confined by where it LEADS, so a
    link to another repository's clone INSIDE ``<home>/repos`` passed, ``clone_repo`` was
    handed the resolved directory (no longer a link) and reused it, and the worker persisted
    ``<home>/repos/<name>`` — the link — as this repository's clone. The worker creates the
    destination itself, so the rule for it is identity: a real directory at
    ``<root>/<name>`` or nothing there yet, never a link, wherever the link goes."""
    monkeypatch.setenv(LOCAL_CLONE_ENV, "1")
    add_url_repo(h, remote)  # no clone yet: the worker will clone into repos/<name>
    _plant_destination_link(h, remote, shape)
    calls = _spy_git(monkeypatch)
    with pytest.raises(LookupError, match="clone_path_escapes"):
        h.worker._load_repo(pr.REPO_NAME)
    assert calls == []  # refused before git ran anywhere
    row = h.repo_row()
    assert row.clone_path == "" and row.config_json["path"] == ""  # the link is not adopted


def test_a_real_destination_is_still_cloned_into(
    h: Harness, remote: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control for the case above: with no link anywhere, an existing empty directory at
    the destination is cloned into and persisted, and git opens that directory."""
    monkeypatch.setenv(LOCAL_CLONE_ENV, "1")
    add_url_repo(h, remote)
    dest = h.home / "repos" / pr.REPO_NAME
    dest.mkdir(parents=True)
    _config, git = h.worker._load_repo(pr.REPO_NAME)
    assert git.path == dest.resolve() and git.is_repo()
    assert h.repo_row().clone_path == str(dest)


@pytest.mark.parametrize("shape", _DESTINATION_LINKS)
def test_the_destination_rule_is_identity_not_containment(
    h: Harness, remote: str, shape: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rule itself, without the worker: ``confined_clone_path(…, inside_root=True)``
    returns a path only when that path IS ``<root>/<the written name>`` — the directory the
    caller persists — so "resolves somewhere inside the root" can never again stand in for
    "is the destination"."""
    monkeypatch.setenv(LOCAL_CLONE_ENV, "1")
    _plant_destination_link(h, remote, shape)
    root = clone_root(h.home)
    assert confined_clone_path(h.home / "repos" / pr.REPO_NAME, h.home, inside_root=True) is None
    (h.home / "repos" / "real").mkdir()
    assert confined_clone_path(h.home / "repos" / "real", h.home, inside_root=True) == root / "real"
    absent = confined_clone_path(h.home / "repos" / "absent", h.home, inside_root=True)
    assert absent == root / "absent"


# ---------------------------------------------------------------------------
# The prevention ratchet: a stored clone path reaches git only through the use-time rule
# ---------------------------------------------------------------------------

_SRC = Path(__file__).resolve().parents[1] / "src" / "crb"
_CONFINERS = {"_confined_clone", "confined_clone_path"}
#: (module, function) → where a stored clone path is turned into a git handle
_USE_SITES = [("server/worker.py", "_load_repo"), ("server/routes/repos.py", "compute_profile")]


def _func(tree: ast.AST, name: str) -> ast.FunctionDef:
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


def _call_name(call: ast.Call) -> str:
    f = call.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""


def _is_confined(value: ast.expr) -> bool:
    """``confiner(…)``, or ``confiner(…) if … else None`` (nothing to open)."""
    if isinstance(value, ast.IfExp):
        none = isinstance(value.orelse, ast.Constant) and value.orelse.value is None
        return none and _is_confined(value.body)
    return isinstance(value, ast.Call) and _call_name(value) in _CONFINERS


@pytest.mark.parametrize(("module", "function"), _USE_SITES)
def test_git_opens_only_the_confined_path_at_every_use_site(module: str, function: str) -> None:
    """PR #52 review, as a class: the rule was applied to the stored path but git was
    handed a different one (the clone destination) — and the path it opened was the
    WRITTEN one, not the one checked. At each use site every ``GitRepo(…)`` and the
    destination of every ``clone_repo(…)`` is a name bound to the confiner's result."""
    fn = _func(ast.parse((_SRC / module).read_text(encoding="utf-8")), function)
    confined = {
        t.id
        for n in ast.walk(fn)
        if isinstance(n, ast.Assign) and _is_confined(n.value)
        for t in n.targets
        if isinstance(t, ast.Name)
    }
    opened = [
        (n.lineno, n.args[{"GitRepo": 0, "clone_repo": 1}[_call_name(n)]])
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and _call_name(n) in {"GitRepo", "clone_repo"}
    ]
    assert opened, f"{module}:{function} no longer opens a clone — move this ratchet"
    bad = [
        (line, ast.unparse(arg))
        for line, arg in opened
        if not (isinstance(arg, ast.Name) and arg.id in confined)
    ]
    assert not bad, f"{module}:{function} opens git on an unconfined path: {bad}"


#: server functions that open git on something that is NOT a stored clone path, and why
_NOT_A_STORED_CLONE = {
    ("server/routes/grades.py", "retained_patch_text"): "a retained worktree under scratch",
}


def _git_openers_in_server() -> set[tuple[str, str]]:
    """Every function under ``crb.server`` that calls ``GitRepo(…)`` or ``clone_repo(…)``."""
    found = set()
    for path in (_SRC / "server").rglob("*.py"):
        for fn in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef) and any(
                isinstance(n, ast.Call) and _call_name(n) in {"GitRepo", "clone_repo"}
                for n in ast.walk(fn)
            ):
                found.add((path.relative_to(_SRC).as_posix(), fn.name))
    return found


def test_the_use_site_list_is_every_place_the_server_opens_git() -> None:
    """PR #52 review (DL-053's "every use site"): ``_USE_SITES`` is a hand-kept list, so the
    ratchet above is only as complete as the list. Every function in ``crb.server`` that
    opens git is on it or named here as not a stored clone — a new one fails until someone
    decides which it is."""
    unlisted = _git_openers_in_server() - set(_USE_SITES) - set(_NOT_A_STORED_CLONE)
    assert not unlisted, f"a server function opens git and is on neither list: {unlisted}"
    stale = (set(_USE_SITES) | set(_NOT_A_STORED_CLONE)) - _git_openers_in_server()
    assert not stale, f"listed but no longer opens git: {stale}"


def test_the_link_rule_is_called_only_inside_the_confiners() -> None:
    """``clone_path_escapes`` on its own checks a path but does not say which path git
    should open; outside the write-time rule and the use-time confiner it is a check that
    the next line can walk around."""
    allowed = {("server/routes/repos.py", f) for f in ("confine_clone_path", "confined_clone_path")}
    found = set()
    for path in _SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for n in ast.walk(fn):
                if isinstance(n, ast.Call) and _call_name(n) == "clone_path_escapes":
                    found.add((path.relative_to(_SRC).as_posix(), fn.name))
    assert found - allowed == set()
    assert found == allowed  # both confiners still apply it
