"""Dependency eras for the JavaScript runners (``_NodeBase.ensure_era``).

A worktree at a task commit whose lockfile differs from the clone's must not run
its tests or belt 5 against HEAD's ``node_modules`` (nhsuk-react-components: the
commit's eslint config needs ``@eslint/compat``, absent from HEAD — ``rc=2``,
2026-09-15). The era is installed once per lockfile hash under ``env_dir`` and
the worktree's link re-pointed; an install that fails is a harness error.

No node/npm on the host is needed: the executor is a stub that records the npm
call and fabricates the tree.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from crb.core.execution import Command, ExecResult
from crb.core.runners import get_runner
from crb.core.runners.node_runners import NodeEraError, lock_key
from crb.core.spec import Language, RepoConfig

try:
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover — layout-dependent
    import conftest_langs as langs

_fx = langs
noderepo = langs.fixture_module("noderepo")


class _Npm:
    """Executor stub: ``npm ci`` creates ``node_modules/.bin`` in its cwd (or fails)."""

    name = "local"

    def __init__(self, *, rc: int = 0) -> None:
        self.rc = rc
        self.calls: list[Command] = []

    def tool(self, name: str, host_override: str | None = None) -> str:
        return host_override or name

    def run(self, cmd: Command) -> ExecResult:
        self.calls.append(cmd)
        if self.rc == 0:
            (cmd.root / "node_modules" / ".bin").mkdir(parents=True, exist_ok=True)
            (cmd.root / "node_modules" / ".bin" / "eslint").write_text("", encoding="utf-8")
        return ExecResult(self.rc, "", "boom" if self.rc else "", False, 0.1)

    def describe(self) -> dict[str, object]:
        return {"executor": "stub"}


@pytest.fixture
def clone(tmp_path: Path) -> tuple[Path, Path]:
    """A clone with a fake ``node_modules`` and a worktree-shaped sibling linked to it."""
    root, _ = noderepo.build(tmp_path, "node")
    (root / "node_modules" / ".bin").mkdir(parents=True)
    wt = tmp_path / "wt"
    wt.mkdir()
    for name in ("package.json",):
        (wt / name).write_bytes((root / name).read_bytes())
    (wt / "node_modules").symlink_to(root / "node_modules")
    return root, wt


def _runner(env_dir: Path) -> object:
    cfg = RepoConfig(
        name="era",
        language=Language.JAVASCRIPT,
        runner="jest",
        src_prefix="src/",
        ext=".js",
        test_mode="suffix",
        test_suffix=".test.js",
    )
    r = get_runner(cfg)
    r.env_dir = env_dir
    return r


def test_matching_manifest_keeps_the_clone_link(clone: tuple[Path, Path], tmp_path: Path) -> None:
    root, wt = clone
    r = _runner(tmp_path / "env")
    ex = _Npm()
    assert r.ensure_era(wt, ex) is None
    assert (wt / "node_modules").resolve() == (root / "node_modules").resolve()
    assert ex.calls == []


def test_differing_manifest_installs_an_era_once_and_repoints(
    clone: tuple[Path, Path], tmp_path: Path
) -> None:
    root, wt = clone
    pkg = json.loads((wt / "package.json").read_text(encoding="utf-8"))
    pkg["devDependencies"] = {"@eslint/compat": "1.0.0"}
    (wt / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    assert lock_key(wt) != lock_key(root)
    r = _runner(tmp_path / "env")
    ex = _Npm()
    era = r.ensure_era(wt, ex)
    assert era == tmp_path / "env" / "node_eras" / lock_key(wt)
    assert (wt / "node_modules").resolve() == (era / "node_modules").resolve()
    assert (wt / "node_modules" / ".bin" / "eslint").exists()
    (call,) = ex.calls
    assert call.argv[:2] == ("npm", "install") and "--ignore-scripts" in call.argv
    assert call.root == era.resolve() and call.network is True
    # the clone's tree is untouched, and a second worktree sharing the manifest reuses the era
    assert not (root / "node_modules" / ".bin" / "eslint").exists()
    wt2 = tmp_path / "wt2"
    wt2.mkdir()
    (wt2 / "package.json").write_bytes((wt / "package.json").read_bytes())
    (wt2 / "node_modules").symlink_to(root / "node_modules")
    assert r.ensure_era(wt2, ex) == era and len(ex.calls) == 1
    assert (wt2 / "node_modules").resolve() == (era / "node_modules").resolve()


def test_failed_era_install_is_a_harness_error(clone: tuple[Path, Path], tmp_path: Path) -> None:
    root, wt = clone
    (wt / "package-lock.json").write_text('{"lockfileVersion": 3}', encoding="utf-8")
    r = _runner(tmp_path / "env")
    ex = _Npm(rc=1)
    with pytest.raises(NodeEraError, match=r"npm ci rc=1"):
        r.ensure_era(wt, ex)
    # nothing half-installed is left to be mistaken for a tree; the link still resolves
    assert not (tmp_path / "env" / "node_eras" / lock_key(wt) / "node_modules").exists()
    assert (wt / "node_modules").resolve() == (root / "node_modules").resolve()


def test_no_env_dir_or_real_tree_means_no_era(clone: tuple[Path, Path], tmp_path: Path) -> None:
    _root, wt = clone
    (wt / "package.json").write_text("{}", encoding="utf-8")
    r = _runner(tmp_path / "env")
    r.env_dir = None
    assert r.ensure_era(wt, _Npm()) is None
    r.env_dir = tmp_path / "env"
    os.unlink(wt / "node_modules")
    (wt / "node_modules").mkdir()
    assert r.ensure_era(wt, _Npm()) is None


def test_era_install_refuses_when_the_volume_is_nearly_full(
    clone: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two react-components eras on a nearly full disk took the whole stack down
    (2026-09-15): below ``era_min_free_mb`` the install is refused as a harness error."""
    import shutil as _shutil

    _root, wt = clone
    (wt / "package.json").write_text('{"devDependencies": {"x": "1"}}', encoding="utf-8")
    r = _runner(tmp_path / "env")
    usage = _shutil.disk_usage(tmp_path)
    monkeypatch.setattr(
        "crb.core.runners.node_runners.shutil.disk_usage",
        lambda _p: usage._replace(free=100 * 2**20),
    )
    ex = _Npm()
    with pytest.raises(NodeEraError, match=r"100 MB free .* < 2048 MB"):
        r.ensure_era(wt, ex)
    assert ex.calls == []


def test_eras_are_evicted_lru_beyond_era_keep(clone: tuple[Path, Path], tmp_path: Path) -> None:
    _root, wt = clone
    env = tmp_path / "env"
    eras = env / "node_eras"
    for i, name in enumerate(("old1", "old2", "old3")):
        (eras / name / "node_modules" / ".bin").mkdir(parents=True)
        os.utime(eras / name, (1_000_000 + i, 1_000_000 + i))
    (wt / "package.json").write_text('{"devDependencies": {"y": "1"}}', encoding="utf-8")
    cfg = RepoConfig(
        name="era",
        language=Language.JAVASCRIPT,
        runner="jest",
        src_prefix="src/",
        ext=".js",
        test_mode="suffix",
        test_suffix=".test.js",
        runner_opts={"era_keep": 2},
    )
    r = get_runner(cfg)
    r.env_dir = env
    era = r.ensure_era(wt, _Npm())
    assert era is not None and era.is_dir()
    # keep = 2: the new era + the most recently used old one; the two oldest are gone
    assert sorted(d.name for d in eras.iterdir()) == sorted([era.name, "old3"])
