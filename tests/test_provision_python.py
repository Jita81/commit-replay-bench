"""Python: wheels from a pinned lock, installed with no network, sealed per lockfile (D5).

Without a daemon: the fetch and install argv (wheels only, ``--no-deps``, ``--require-hashes``
exactly when every pin carries one, no ``pip.conf``), and that ``/in/lock.txt`` is written
from the parsed pins — never the repository's own file. With a daemon: a ``file://`` simple
index of fixture wheels, a real fetch and an offline install into two sealed sets (the
parent's lock and the gold's), and the shipped Python sandbox image running each tree's tests
with ``--network=none`` against the set its own lock selects.

Navigation
----------
What it is:   The suite for the Python recipe (``crb.provision.python``) and the pytest runner's
              binding.
What it does: Pins the plans' argv and refusals; proves against a daemon that the parent's and
              the gold's locks each seal their own set (hashes committed for one, recorded for
              the other), that each tree selects its own set and passes offline, and that the
              runner's environment probe finds every locked distribution.
How:          ``pkgmirror.build_pypi`` + ``pyrepo_deps.build`` under ``tests/.cache`` →
              ``SealedProvider.resolve`` → ``PytestRunner`` bound to the selected set on a
              ``DockerExecutor`` over the shipped ``crb-sandbox-python`` image.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/provision/python.py (under test), src/crb/core/runners/pytest_runner.py
              (the binding), tests/fixtures/pkgmirror.py (the wheels),
              tests/fixtures/langs/pyrepo_deps.py (the repository)
Tested by:    tests/test_provision_python.py
Touch when:   the Python recipe's plans, refusals or binding change.
"""

from __future__ import annotations

import importlib
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from crb.core.deps import ProvisionRefused
from crb.core.execution import DockerExecutor, DockerSettings
from crb.core.git import GitRepo
from crb.core.provision import LockInputs
from crb.core.runners import get_runner
from crb.provision import SealedProvider
from crb.provision import python as py_recipe
from crb.provision.config import DEFAULT_PYTHON_IMAGE, ProvisionConfig
from crb.provision.fetch import FetchResult
from crb.provision.store import remove_tree

try:
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover
    import conftest_langs as langs

pyrepo_deps = langs.fixture_module("pyrepo_deps")
pkgmirror = importlib.import_module("fixtures.pkgmirror")


def _inputs(tmp_path: Path) -> tuple[GitRepo, str, LockInputs, LockInputs]:
    root, feat = pyrepo_deps.build(tmp_path)
    repo = GitRepo(root)
    cfg = pyrepo_deps.config()
    return (
        repo,
        feat,
        LockInputs.from_git(repo, repo.parent(feat), cfg),
        LockInputs.from_git(repo, feat, cfg),
    )


def test_pip_fetch_is_wheels_only_from_the_parsed_pins(tmp_path: Path) -> None:
    _, _, parent, gold = _inputs(tmp_path)
    cfg = ProvisionConfig()
    plan = py_recipe.fetch_plan(parent, key="dep_" + "0" * 64, config=cfg, image="py@sha256:x")
    assert plan.argv == (
        "python",
        "-m",
        "pip",
        "download",
        "--only-binary=:all:",
        "--no-deps",
        "--index-url",
        "https://pypi.org/simple",
        "-r",
        "/in/lock.txt",
        "-d",
        "/out/wheels",
    )
    assert plan.env["PIP_CONFIG_FILE"] == "/dev/null" and plan.env["PIP_NO_INPUT"] == "1"
    assert plan.registry_hosts == ("pypi.org", "files.pythonhosted.org")
    assert plan.inputs == {"lock.txt": b"cfxdep==1.0.0\n"}
    committed = py_recipe.fetch_plan(gold, key="dep_" + "0" * 64, config=cfg, image="i")
    assert "--require-hashes" in committed.argv
    assert committed.inputs["lock.txt"] == (
        f"cfxdep==1.1.0 --hash={pkgmirror.wheel_hash('1.1.0')}\n".encode()
    )
    install = py_recipe.install_plan(gold, key="dep_" + "0" * 64, image="i")
    assert install.offline and not install.networked and install.step == "install"
    assert install.argv[:6] == ("python", "-m", "pip", "install", "--no-index", "--find-links")
    assert "--require-hashes" in install.argv and "--only-binary=:all:" in install.argv
    assert install.extra_ro == {"out/wheels": "/wheels"} and install.out_sub == "out/site"
    mirror = py_recipe.fetch_plan(
        parent,
        key="dep_" + "0" * 64,
        config=ProvisionConfig(pypi_index="file:///srv/simple"),
        image="i",
    )
    assert "file:///mirror" in mirror.argv and mirror.registry_hosts == ()


def test_a_source_only_package_is_build_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, feat, _, _ = _inputs(tmp_path)
    provider = SealedProvider(ProvisionConfig(enabled=True, env="dev", store=tmp_path / "deps"))
    monkeypatch.setattr(provider, "image_id", lambda image: "sha256:" + "e" * 64)

    def pip_found_only_an_sdist(plan: object, stage: Path) -> FetchResult:
        raise ProvisionRefused(
            "PROVISION_FETCH_FAILED",
            "fetch exited 1: ERROR: No matching distribution found for cfxdep==1.0.0",
        )

    monkeypatch.setattr(provider, "fetch", pip_found_only_an_sdist)
    with pytest.raises(ProvisionRefused) as ei:
        provider.resolve(repo, pyrepo_deps.config(), gold=feat)
    assert ei.value.code == "PROVISION_BUILD_REQUIRED" and "source distribution" in ei.value.message
    assert not any(provider.store.root.glob("python/dep_*"))


# ---------------------------------------------------------------------------


@pytest.fixture
def scratch() -> Iterator[Path]:
    reason = langs.docker_unavailable_reason()
    if reason:
        pytest.skip(reason)
    langs.require_docker_image(DEFAULT_PYTHON_IMAGE, "the pinned python fetch image")
    root = langs.CACHE_DIR / "provision" / f"py-{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    yield root
    remove_tree(root)


@pytest.mark.docker
@pytest.mark.slow
@pytest.mark.sandbox_images
def test_python_parent_and_gold_each_get_their_sealed_site_and_pass_offline(scratch: Path) -> None:
    image = langs.ensure_shipped_sandbox_image("python")
    index = pkgmirror.build_pypi(scratch / "simple")
    root, feat = pyrepo_deps.build(scratch / "repo")
    repo = GitRepo(root)
    cfg = pyrepo_deps.config()
    provider = SealedProvider(
        ProvisionConfig(
            enabled=True, env="dev", store=scratch / "deps", pypi_index=f"file://{index}"
        )
    )
    deps = provider.resolve(repo, cfg, gold=feat)
    assert deps.parent.key != deps.gold.key and deps.builder.key == deps.parent.key
    assert deps.parent.manifest == ("cfxdep==1.0.0",) and deps.gold.manifest == ("cfxdep==1.1.0",)
    parent_set = provider.store.verify(deps.parent.key)
    gold_set = provider.store.verify(deps.gold.key)
    assert parent_set.manifest["hashes"] == "recorded"
    assert parent_set.manifest["wheels"] == {
        pkgmirror.wheel_name("1.0.0"): pkgmirror.wheel_hash("1.0.0")
    }
    assert gold_set.manifest["hashes"] == "committed"
    assert not (gold_set.path / "wheels").exists(), "only the installed site is sealed"
    assert (gold_set.path / "site" / "cfxdep" / "__init__.py").is_file()

    executor = DockerExecutor(DockerSettings(image=image))
    runner = get_runner(cfg)
    cand = langs.feat_candidate(repo, cfg, feat)
    for role, sources, scope in (
        ("parent", (), ("tests/test_core.py",)),
        ("gold", ("requirements.txt", pyrepo_deps.SRC_BYE), ("tests/test_bye.py",)),
    ):
        ws = (
            langs.trial_worktree(repo, cand, scratch / f"t-{role}", cfg, sources=sources)
            if role == "gold"
            else _parent_tree(repo, feat, scratch / f"t-{role}", cfg)
        )
        try:
            binding = deps.binding_for(ws.root)
            assert binding.role == role and binding.key == getattr(deps, role).key
            with runner.deps_bound(binding):
                probe = runner.probe_environment(executor, ws.root)
                assert probe is not None and probe.ok, probe.combined if probe else ""
                run = runner.run(executor, ws.root, scope)
            assert run.green, (role, run.tail)
        finally:
            ws.remove()


def _parent_tree(repo: GitRepo, feat: str, dest: Path, cfg):  # type: ignore[no-untyped-def]
    from crb.core.workspace import Workspace

    return Workspace.create(repo, feat, dest, config=cfg)


#: A pin whose environment marker excludes it on every supported Python: pip ignores the
#: line at fetch and at install, and the package is on no index at all.
_MARKER_LOCK = 'cfxdep==1.0.0\nnotonindex==9.9.9 ; python_version < "3.0"\n'


def test_the_manifest_holds_what_pip_installed_never_a_pin_its_marker_skipped(
    tmp_path: Path,
) -> None:
    """``installed_manifest``: a pin with a marker and no ``*.dist-info`` in the site was
    skipped by pip on the fetch image — it is recorded as ``marker_skipped``, never as a
    package the set must hold; a pin WITHOUT a marker stays whether or not it is there, so
    the environment probe still reports a set that lost it (CodeRabbit on PR #56)."""
    root, feat = pyrepo_deps.build(tmp_path, parent_requirements=_MARKER_LOCK)
    repo = GitRepo(root)
    parent = LockInputs.from_git(repo, repo.parent(feat), pyrepo_deps.config())
    site = tmp_path / "site"
    (site / "cfxdep-1.0.0.dist-info").mkdir(parents=True)
    packages, skipped = py_recipe.installed_manifest(parent, site)
    assert packages == {"cfxdep==1.0.0": []} and skipped == ["notonindex==9.9.9"]
    (site / "cfxdep-1.0.0.dist-info").rmdir()  # a marker-less pin pip lost: kept, probed
    packages, skipped = py_recipe.installed_manifest(parent, site)
    assert "cfxdep==1.0.0" in packages and skipped == ["notonindex==9.9.9"]


@pytest.mark.docker
@pytest.mark.slow
@pytest.mark.sandbox_images
def test_a_pin_its_marker_excludes_never_fails_the_environment_probe(scratch: Path) -> None:
    """The pip-compile shape (``tomli==… ; python_version < "3.11"``): pip skips the line on
    the 3.12 image at fetch and at install, so the sealed set does not hold it — and the
    probe must not require it, or every task in the repository is ``QUAL_ENV_UNLOADABLE``
    (CodeRabbit on PR #56)."""
    image = langs.ensure_shipped_sandbox_image("python")
    index = pkgmirror.build_pypi(scratch / "simple")
    root, feat = pyrepo_deps.build(scratch / "repo", parent_requirements=_MARKER_LOCK)
    repo = GitRepo(root)
    cfg = pyrepo_deps.config()
    provider = SealedProvider(
        ProvisionConfig(
            enabled=True, env="dev", store=scratch / "deps", pypi_index=f"file://{index}"
        )
    )
    deps = provider.resolve(repo, cfg, gold=feat)
    assert deps.parent.manifest == ("cfxdep==1.0.0",)
    parent_set = provider.store.verify(deps.parent.key)
    assert parent_set.manifest["marker_skipped"] == ["notonindex==9.9.9"]
    ws = _parent_tree(repo, feat, scratch / "t-parent", cfg)
    try:
        runner = get_runner(cfg)
        with runner.deps_bound(deps.binding_for(ws.root)):
            probe = runner.probe_environment(DockerExecutor(DockerSettings(image=image)), ws.root)
        assert probe is not None and probe.ok, probe.combined if probe else ""
    finally:
        ws.remove()
