"""Dependency inputs come from git objects; every refused source is refused (ADR-0019, D1).

Pure: no daemon, no toolchain, no network. Each test builds a tiny hermetic git repository
and reads it through :meth:`crb.core.provision.LockInputs.from_git`.

Navigation
----------
What it is:   The suite for the pure half of dependency provisioning — lockfile readers over git
              objects, refusals, bundle keys and the closure selector.
What it does: Pins that editing a worktree changes neither the inputs nor the key; that the Go
              key covers the parent's and the gold's blobs together; that URL, VCS, path, index,
              foreign-host, unpinned, ``go.work``, yarn/pnpm/uv, install-script and JVM inputs
              are each refused with their code and scope; that ``.npmrc``, ``pip.conf`` and
              ``go.env`` are never read; that a trial never makes the selector read outside its
              tree (an escaping replace or a linked manifest); and that a trial selects the
              parent's or the gold's set
              or raises ``ClosureViolation`` naming what was outside.
How:          ``two_commit_repo`` / ``init_repo`` + ``commit_all`` → ``LockInputs.from_git`` → assert;
              a spy ``GitRepo`` records every path asked for.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         none
Works with:   src/crb/core/provision.py (under test), src/crb/core/deps.py (the refusal
              vocabulary and the selector), tests/fixtures/goproxy.py (real go.sum lines),
              tests/fixtures/langs/gorepo_deps.py (the D4 shape)
Tested by:    tests/test_provision.py
Touch when:   a lock format or a refusal rule changes in src/crb/core/provision.py.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from crb.core import provision as pv
from crb.core.deps import SCOPE_RUN, SCOPE_TASK, ClosureViolation, ProvisionRefused
from crb.core.git import GitRepo
from crb.core.spec import Language, RepoConfig

try:
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover
    import conftest_langs as langs

gorepo_deps = langs.fixture_module("gorepo_deps")  # also puts tests/ on sys.path
goproxy = importlib.import_module("fixtures.goproxy")
_fx = importlib.import_module("fixtures.langs")
commit_all, git, init_repo, write_files = _fx.commit_all, _fx.git, _fx.init_repo, _fx.write_files

IMAGE = "sha256:" + "a" * 64


def _repo(root: Path, *commits: dict[str, str]) -> tuple[GitRepo, list[str]]:
    init_repo(root)
    shas = []
    for i, files in enumerate(commits):
        write_files(root, files)
        shas.append(commit_all(root, f"c{i}"))
    return GitRepo(root), shas


def _cfg(runner: str, **opts: object) -> RepoConfig:
    lang = {"go": Language.GO, "pytest": Language.PYTHON, "maven": Language.JVM}.get(
        runner, Language.JAVASCRIPT
    )
    return RepoConfig(name="fx", language=lang, runner=runner, runner_opts=dict(opts))


def _refused(code: str, fn, *a, **k) -> ProvisionRefused:  # type: ignore[no-untyped-def]
    with pytest.raises(ProvisionRefused) as ei:
        fn(*a, **k)
    assert ei.value.code == code, ei.value
    return ei.value


def _npm_lock(entries: dict[str, dict[str, object]], version: int = 3) -> str:
    return json.dumps(
        {"name": "x", "lockfileVersion": version, "packages": {"": {"name": "x"}, **entries}}
    )


_PKG = json.dumps({"name": "x", "devDependencies": {"left": "1.0.0"}})
_GOOD = {
    "resolved": "https://registry.npmjs.org/left/-/left-1.0.0.tgz",
    "integrity": "sha512-" + "A" * 86 + "==",
    "version": "1.0.0",
}


# ---------------------------------------------------------------------------


def test_lock_inputs_are_read_from_git_objects_not_the_worktree(tmp_path: Path) -> None:
    root, feat = gorepo_deps.build(tmp_path)
    repo = GitRepo(root)
    cfg = gorepo_deps.config()
    before = pv.LockInputs.from_git(repo, feat, cfg)
    assert before.recipe == pv.RECIPE_GO
    assert before.pins == (f"{goproxy.MODULE}@v1.1.0",)
    # the builder (or anyone) rewrites the worktree's lockfiles …
    (root / "go.sum").write_text("example.com/evil v6.6.6 h1:bogus=\n", encoding="utf-8")
    (root / "go.mod").write_text(gorepo_deps.go_mod("v9.9.9"), encoding="utf-8")
    after = pv.LockInputs.from_git(repo, feat, cfg)
    # … and neither what is fetched nor its key moves
    assert after == before
    assert pv.bundle_key(pv.RECIPE_GO, IMAGE, after.blobs) == pv.bundle_key(
        pv.RECIPE_GO, IMAGE, before.blobs
    )


def test_go_key_is_the_union_of_parent_and_gold(tmp_path: Path) -> None:
    root, feat = gorepo_deps.build(tmp_path)
    repo = GitRepo(root)
    cfg = gorepo_deps.config()
    parent = pv.LockInputs.from_git(repo, repo.parent(feat), cfg)
    gold = pv.LockInputs.from_git(repo, feat, cfg)
    assert parent.pins == (f"{goproxy.MODULE}@v1.0.0",)
    assert gold.pins == (f"{goproxy.MODULE}@v1.1.0",)
    union, parent_only = pv.go_keys(parent, gold, IMAGE)
    assert union == pv.bundle_key(pv.RECIPE_GO, IMAGE, {*parent.blobs, *gold.blobs})
    assert parent_only == pv.bundle_key(pv.RECIPE_GO, IMAGE, parent.blobs)
    assert union != parent_only  # D4: the gold's go.sum differs from its parent's
    # an unchanged lock: one key serves both
    same_union, same_parent = pv.go_keys(parent, parent, IMAGE)
    assert same_union == same_parent
    # the key moves with the recipe and with the fetch image
    assert pv.bundle_key("go.modcache.v2", IMAGE, parent.blobs) != parent_only
    assert pv.bundle_key(pv.RECIPE_GO, "sha256:" + "b" * 64, parent.blobs) != parent_only
    assert union.startswith("dep_") and len(union) == 4 + 64


def test_npm_foreign_resolved_host_is_refused(tmp_path: Path) -> None:
    bad = {**_GOOD, "resolved": "https://evil.example.com/left/-/left-1.0.0.tgz"}
    repo, (sha,) = _repo(
        tmp_path / "r",
        {"package.json": _PKG, "package-lock.json": _npm_lock({"node_modules/left": bad})},
    )
    err = _refused("PROVISION_SOURCE_REFUSED", pv.LockInputs.from_git, repo, sha, _cfg("node"))
    assert "evil.example.com" in err.message and err.scope == SCOPE_TASK
    # the configured registry's host is the only one admitted
    ok = pv.LockInputs.from_git(repo, sha, _cfg("node"), npm_registry_host="evil.example.com")
    assert ok.recipe == pv.RECIPE_NODE


@pytest.mark.parametrize(
    "entry",
    [
        {**_GOOD, "resolved": "file:../left"},
        {**_GOOD, "resolved": "git+ssh://git@github.com/x/left.git#abc"},
        {"link": True, "resolved": "../left"},
    ],
    ids=["file", "git", "link"],
)
def test_npm_file_git_and_link_entries_are_refused(tmp_path: Path, entry: dict) -> None:
    repo, (sha,) = _repo(
        tmp_path / "r",
        {"package.json": _PKG, "package-lock.json": _npm_lock({"node_modules/left": entry})},
    )
    _refused("PROVISION_SOURCE_REFUSED", pv.LockInputs.from_git, repo, sha, _cfg("node"))


def test_npm_entry_without_integrity_is_unpinned(tmp_path: Path) -> None:
    entry = {k: v for k, v in _GOOD.items() if k != "integrity"}
    repo, (sha,) = _repo(
        tmp_path / "r",
        {"package.json": _PKG, "package-lock.json": _npm_lock({"node_modules/left": entry})},
    )
    err = _refused("PROVISION_UNPINNED", pv.LockInputs.from_git, repo, sha, _cfg("node"))
    assert "node_modules/left" in err.message


def test_npm_install_script_needs_to_be_named_and_old_or_foreign_locks_are_unsupported(
    tmp_path: Path,
) -> None:
    scripted = {"node_modules/left": {**_GOOD, "hasInstallScript": True}}
    repo, (sha,) = _repo(
        tmp_path / "a", {"package.json": _PKG, "package-lock.json": _npm_lock(scripted)}
    )
    _refused("PROVISION_BUILD_REQUIRED", pv.LockInputs.from_git, repo, sha, _cfg("node"))
    named = pv.LockInputs.from_git(repo, sha, _cfg("node", deps_build_scripts=["left"]))
    assert named.node_pkgs[0].install_script is True
    v1 = json.dumps({"name": "x", "lockfileVersion": 1, "dependencies": {}})
    repo, (sha,) = _repo(tmp_path / "b", {"package.json": _PKG, "package-lock.json": v1})
    _refused("PROVISION_LOCK_UNSUPPORTED", pv.LockInputs.from_git, repo, sha, _cfg("node"))
    for lock in ("yarn.lock", "pnpm-lock.yaml"):
        repo, (sha,) = _repo(tmp_path / lock, {"package.json": _PKG, lock: "x\n"})
        _refused("PROVISION_LOCK_UNSUPPORTED", pv.LockInputs.from_git, repo, sha, _cfg("jest"))
    repo, (sha,) = _repo(tmp_path / "nolock", {"package.json": _PKG})
    _refused("PROVISION_NO_LOCK", pv.LockInputs.from_git, repo, sha, _cfg("mocha"))
    repo, (sha,) = _repo(tmp_path / "nodeps", {"package.json": json.dumps({"name": "x"})})
    assert not pv.LockInputs.from_git(repo, sha, _cfg("node")).declares_dependencies


@pytest.mark.parametrize(
    "line",
    [
        "left @ https://example.com/left-1.0.0.tar.gz",
        "https://example.com/left-1.0.0-py3-none-any.whl",
        "git+https://github.com/x/left.git@v1#egg=left",
        "./vendor/left",
        "-e .",
        "--index-url https://evil.example.com/simple",
        "--extra-index-url https://evil.example.com/simple",
        "--find-links https://evil.example.com/wheels",
        "-i https://evil.example.com/simple",
    ],
)
def test_pip_url_vcs_path_and_index_lines_are_refused(tmp_path: Path, line: str) -> None:
    repo, (sha,) = _repo(tmp_path / "r", {"requirements.txt": f"left==1.0.0\n{line}\n"})
    err = _refused("PROVISION_SOURCE_REFUSED", pv.LockInputs.from_git, repo, sha, _cfg("pytest"))
    assert "requirements.txt:2" in err.message


@pytest.mark.parametrize("line", ["left>=1.0", "left", "left~=1.0", "left==1.*", "left<2,>1"])
def test_pip_range_is_unpinned(tmp_path: Path, line: str) -> None:
    repo, (sha,) = _repo(tmp_path / "r", {"requirements.txt": f"{line}\n"})
    _refused("PROVISION_UNPINNED", pv.LockInputs.from_git, repo, sha, _cfg("pytest"))


def test_pip_includes_hashes_and_alternative_locks(tmp_path: Path) -> None:
    h = "sha256:" + "0" * 64
    repo, (sha,) = _repo(
        tmp_path / "a",
        {
            "requirements.txt": f"-r reqs/base.txt\nright==2.0.0 --hash={h}  # pinned\n",
            "reqs/base.txt": f"left==1.0.0 \\\n    --hash={h}\n",
        },
    )
    got = pv.LockInputs.from_git(repo, sha, _cfg("pytest"))
    assert got.pins == ("left==1.0.0", "right==2.0.0")
    assert got.require_hashes is True
    assert set(got.lock_paths) == {"requirements.txt", "reqs/base.txt"}
    repo, (sha,) = _repo(
        tmp_path / "b", {"uv.lock": "x\n", "pyproject.toml": "[project]\nname='x'\n"}
    )
    err = _refused("PROVISION_LOCK_UNSUPPORTED", pv.LockInputs.from_git, repo, sha, _cfg("pytest"))
    assert "uv.lock" in err.message
    repo, (sha,) = _repo(
        tmp_path / "c", {"pyproject.toml": "[project]\nname='x'\ndependencies=['left']\n"}
    )
    _refused("PROVISION_NO_LOCK", pv.LockInputs.from_git, repo, sha, _cfg("pytest"))
    repo, (sha,) = _repo(tmp_path / "d", {"pyproject.toml": "[project]\nname='x'\n"})
    assert pv.LockInputs.from_git(repo, sha, _cfg("pytest")).recipe == pv.RECIPE_NONE
    repo, (sha,) = _repo(tmp_path / "e", {"locks/test.txt": "left==1.0.0\n"})
    assert pv.LockInputs.from_git(repo, sha, _cfg("pytest", deps_lock=["locks/test.txt"])).pins == (
        "left==1.0.0",
    )


def test_go_work_is_unsupported(tmp_path: Path) -> None:
    repo, (sha,) = _repo(
        tmp_path / "r", {"go.mod": "module example.com/x\n\ngo 1.22\n", "go.work": "go 1.22\n"}
    )
    err = _refused("PROVISION_LOCK_UNSUPPORTED", pv.LockInputs.from_git, repo, sha, _cfg("go"))
    assert "go.work" in err.message


def test_go_local_replace_vendor_and_missing_sum(tmp_path: Path) -> None:
    base = {
        "go.mod": (
            "module example.com/x\n\ngo 1.22\n\nrequire (\n\texample.com/lib v0.0.0 // local\n"
            f"\t{goproxy.MODULE} v1.0.0\n)\n\nreplace example.com/lib => ./lib\n"
        ),
        "go.sum": goproxy.go_sum(["v1.0.0"]),
        "lib/go.mod": "module example.com/lib\n\ngo 1.22\n",
    }
    repo, (sha,) = _repo(tmp_path / "a", base)
    got = pv.LockInputs.from_git(repo, sha, _cfg("go"))
    assert got.pins == (f"{goproxy.MODULE}@v1.0.0",)  # the local replace is not a fetch
    assert "lib/go.mod" in got.lock_paths
    repo, (sha,) = _repo(
        tmp_path / "b", {**base, "go.mod": base["go.mod"].replace("./lib", "../outside")}
    )
    _refused("PROVISION_SOURCE_REFUSED", pv.LockInputs.from_git, repo, sha, _cfg("go"))
    repo, (sha,) = _repo(tmp_path / "c", {**base, "vendor/modules.txt": "# vendored\n"})
    assert pv.LockInputs.from_git(repo, sha, _cfg("go")).recipe == pv.RECIPE_GO_VENDOR
    repo, (sha,) = _repo(tmp_path / "d", {"go.mod": gorepo_deps.go_mod("v1.0.0")})
    _refused("PROVISION_NO_LOCK", pv.LockInputs.from_git, repo, sha, _cfg("go"))
    repo, (sha,) = _repo(tmp_path / "e", {"go.mod": "module example.com/x\n\ngo 1.22\n"})
    assert not pv.LockInputs.from_git(repo, sha, _cfg("go")).declares_dependencies


def test_jvm_and_rust_are_refused_with_run_scope() -> None:
    err = _refused("PROVISION_UNSUPPORTED_LANGUAGE", pv.lang_of, _cfg("maven"))
    assert err.scope == SCOPE_RUN and "local posture" in err.fix


class _SpyRepo(GitRepo):
    """Records every path the provisioning reader asks the object store for."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.asked: list[str] = []

    def show_blob(self, sha: str, path: str) -> bytes | None:
        self.asked.append(path)
        return super().show_blob(sha, path)


def test_repository_config_files_are_never_read(tmp_path: Path) -> None:
    config_files = {
        ".npmrc": "registry=https://evil.example.com/\n",
        "pip.conf": "[global]\nindex-url = https://evil.example.com/simple\n",
        "go.env": "GOPROXY=https://evil.example.com\n",
        ".pypirc": "[distutils]\n",
    }
    files = {
        **config_files,
        "go.mod": gorepo_deps.go_mod("v1.0.0"),
        "go.sum": goproxy.go_sum(["v1.0.0"]),
        "requirements.txt": "left==1.0.0\n",
        "package.json": _PKG,
        "package-lock.json": _npm_lock({"node_modules/left": _GOOD}),
    }
    init_repo(tmp_path / "r")
    write_files(tmp_path / "r", files)
    sha = commit_all(tmp_path / "r", "all")
    spy = _SpyRepo(tmp_path / "r")
    for runner in ("go", "pytest", "node"):
        got = pv.LockInputs.from_git(spy, sha, _cfg(runner))
        assert got.declares_dependencies
    assert spy.asked, "nothing was read"
    assert not {Path(p).name for p in spy.asked} & set(config_files), spy.asked
    assert set(config_files) <= pv.NEVER_READ


def test_a_trial_outside_the_closure_raises_closure_violation(tmp_path: Path) -> None:
    root, feat = gorepo_deps.build(tmp_path)
    repo = GitRepo(root)
    cfg = gorepo_deps.config()
    parent = pv.LockInputs.from_git(repo, repo.parent(feat), cfg)
    gold = pv.LockInputs.from_git(repo, feat, cfg)
    sel = pv.closure_selector("go", modules={*parent.pins, *gold.pins})
    # the tree at the gold (and at the parent) stays inside the closure
    assert sel.select(root) == "gold"
    (root / "go.mod").write_text(gorepo_deps.go_mod("v1.0.0"), encoding="utf-8")
    assert sel.select(root) == "gold"  # one cache serves both
    # a trial that requires a version from outside the closure is refused, by name
    (root / "go.mod").write_text(gorepo_deps.go_mod("v1.2.0"), encoding="utf-8")
    with pytest.raises(ClosureViolation) as ei:
        sel.select(root)
    assert ei.value.outside == (f"{goproxy.MODULE}@v1.2.0",)
    assert "dependency closure" in str(ei.value)
    # python: a lock that is neither the parent's nor the gold's
    prepo, (p0, p1) = _repo(
        tmp_path / "py",
        {"requirements.txt": "left==1.0.0\n"},
        {"requirements.txt": "left==1.1.0\n"},
    )
    pp = pv.LockInputs.from_git(prepo, p0, _cfg("pytest"))
    pg = pv.LockInputs.from_git(prepo, p1, _cfg("pytest"))
    psel = pv.closure_selector("python", parent=pp, gold=pg)
    (tmp_path / "py" / "requirements.txt").write_text("left==6.6.6\n", encoding="utf-8")
    with pytest.raises(ClosureViolation):
        psel.select(tmp_path / "py")


def test_a_trial_never_makes_the_selector_read_outside_its_tree(tmp_path: Path) -> None:
    """The selector reads the BUILDER's tree at grade time. A local replace that leaves
    the tree, or a manifest that is a link, is a violation (the fetch side refuses the
    same); the file outside is never read, so its contents never reach an error."""
    root, feat = gorepo_deps.build(tmp_path / "repo")
    repo = GitRepo(root)
    cfg = gorepo_deps.config()
    parent = pv.LockInputs.from_git(repo, repo.parent(feat), cfg)
    gold = pv.LockInputs.from_git(repo, feat, cfg)
    sel = pv.closure_selector("go", modules={*parent.pins, *gold.pins})
    other = tmp_path / "other"
    other.mkdir()
    (other / "go.mod").write_text(
        "module x.io/y\n\ngo 1.22\n\nrequire private.corp/secret-thing v1.2.3\n",
        encoding="utf-8",
    )
    original = (root / "go.mod").read_text(encoding="utf-8")
    for target in ("../other", str(other), "./sub/../../other"):
        (root / "go.mod").write_text(original + f"\nreplace x.io/y => {target}\n", encoding="utf-8")
        with pytest.raises(ClosureViolation) as ei:
            sel.select(root)
        assert "points outside the tree" in str(ei.value)
        assert "secret-thing" not in str(ei.value)
    # a go.mod that is a link — out of the tree, or to a file inside it — is refused
    (root / "go.mod").unlink()
    (root / "go.mod").symlink_to(other / "go.mod")
    with pytest.raises(ClosureViolation) as ei:
        sel.select(root)
    assert "is a link" in str(ei.value) and "secret-thing" not in str(ei.value)
    # a local replace whose go.mod is a link out of the tree is refused too
    (root / "go.mod").unlink()
    (root / "go.mod").write_text(original + "\nreplace x.io/y => ./sub\n", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "go.mod").symlink_to(other / "go.mod")
    with pytest.raises(ClosureViolation) as ei:
        sel.select(root)
    assert "sub/go.mod is a link" in str(ei.value) and "secret-thing" not in str(ei.value)
    # python: a lockfile that is a link out of the tree reads as absent, never as the file
    prepo, (p0, p1) = _repo(
        tmp_path / "py",
        {"requirements.txt": "left==1.0.0\n"},
        {"requirements.txt": "left==1.1.0\n"},
    )
    psel = pv.closure_selector(
        "python",
        parent=pv.LockInputs.from_git(prepo, p0, _cfg("pytest")),
        gold=pv.LockInputs.from_git(prepo, p1, _cfg("pytest")),
    )
    outside = tmp_path / "gold-requirements.txt"
    outside.write_text("left==1.1.0\n", encoding="utf-8")  # the gold's bytes, outside
    (tmp_path / "py" / "requirements.txt").unlink()
    (tmp_path / "py" / "requirements.txt").symlink_to(outside)
    with pytest.raises(ClosureViolation):
        psel.select(tmp_path / "py")


def test_a_trial_with_the_parent_or_gold_lock_selects_its_set(tmp_path: Path) -> None:
    root = tmp_path / "py"
    repo, (p0, p1) = _repo(
        root, {"requirements.txt": "left==1.0.0\n"}, {"requirements.txt": "left==1.1.0\n"}
    )
    sel = pv.closure_selector(
        "python",
        parent=pv.LockInputs.from_git(repo, p0, _cfg("pytest")),
        gold=pv.LockInputs.from_git(repo, p1, _cfg("pytest")),
    )
    assert sel.select(root) == "gold"
    git(root, "checkout", "-q", p0)
    assert sel.select(root) == "parent"
    lock1 = _npm_lock({"node_modules/left": _GOOD})
    lock2 = _npm_lock({"node_modules/left": {**_GOOD, "version": "1.1.0"}})
    nroot = tmp_path / "node"
    nrepo, (n0, n1) = _repo(
        nroot,
        {"package.json": _PKG, "package-lock.json": lock1},
        {"package-lock.json": lock2},
    )
    nsel = pv.closure_selector(
        "node",
        parent=pv.LockInputs.from_git(nrepo, n0, _cfg("node")),
        gold=pv.LockInputs.from_git(nrepo, n1, _cfg("node")),
    )
    assert nsel.select(nroot) == "gold"
    git(nroot, "checkout", "-q", n0)
    assert nsel.select(nroot) == "parent"



def test_a_node_lockfile_that_is_a_link_is_a_violation_never_read(tmp_path: Path) -> None:
    """Node's closure key reads the builder's tree like Go's and Python's do: a lockfile
    that is a link — here to the gold's own bytes, outside the tree — is a
    ``ClosureViolation``, never read and never matched to a role (CodeRabbit on PR #56)."""
    lock1 = _npm_lock({"node_modules/left": _GOOD})
    lock2 = _npm_lock({"node_modules/left": {**_GOOD, "version": "1.1.0"}})
    nroot = tmp_path / "node"
    nrepo, (n0, n1) = _repo(
        nroot,
        {"package.json": _PKG, "package-lock.json": lock1},
        {"package-lock.json": lock2},
    )
    nsel = pv.closure_selector(
        "node",
        parent=pv.LockInputs.from_git(nrepo, n0, _cfg("node")),
        gold=pv.LockInputs.from_git(nrepo, n1, _cfg("node")),
    )
    outside = tmp_path / "gold-lock.json"
    outside.write_text(lock2, encoding="utf-8")  # the gold's bytes, outside the tree
    (nroot / "package-lock.json").unlink()
    (nroot / "package-lock.json").symlink_to(outside)
    with pytest.raises(ClosureViolation, match=r"package-lock\.json is a link"):
        nsel.select(nroot)
    # a link to a file INSIDE the tree is refused as well: the key is the tree's own file
    (nroot / "package-lock.json").unlink()
    (nroot / "lock-copy.json").write_text(lock2, encoding="utf-8")
    (nroot / "package-lock.json").symlink_to(nroot / "lock-copy.json")
    with pytest.raises(ClosureViolation, match="is a link"):
        nsel.select(nroot)

def test_refusals_carry_scope_fix_and_doc() -> None:
    err = ProvisionRefused("PROVISION_DISABLED", "cobra declares go modules")
    d = err.to_dict()
    assert d["scope"] == SCOPE_RUN and "CRB_PROVISION__ENABLED" in d["fix"]
    assert d["doc"].startswith("docs/DEPLOYMENT.md#34")
    with pytest.raises(KeyError):
        ProvisionRefused("PROVISION_MADE_UP", "x")
