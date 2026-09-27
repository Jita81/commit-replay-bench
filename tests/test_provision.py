"""Dependency inputs come from git objects; every refused source is refused (ADR-0019, D1).

Pure: no daemon, no toolchain, no network. Each test builds a tiny hermetic git repository
and reads it through :meth:`crb.core.provision.LockInputs.from_git`.

Navigation
----------
What it is:   The suite for the pure half of dependency provisioning — lockfile readers over git
              objects, refusals, bundle keys and the closure selector.
What it does: Pins that editing a worktree changes neither the inputs nor the key; that the Go
              key covers the parent's and the gold's blobs together; that URL, VCS, path, index,
              foreign-host, unpinned, ``go.work``, yarn/pnpm/poetry, install-script and JVM
              inputs are each refused with their code and scope; that a ``uv.lock`` is read
              into hashed, marked pins for the named groups (extras, forks and marker paths
              followed; any other index, a wheel-less package every environment needs, a
              workspace or another lock version refused), with the groups in the bundle key;
              that ``deps_lock`` alternatives provision a lock that moved across a history;
              that ``.npmrc``, ``pip.conf`` and ``go.env`` are never read; that a trial never
              makes the selector read outside its tree (an escaping replace or a linked
              manifest); and that a trial selects the parent's or the gold's set or raises
              ``ClosureViolation`` naming what was outside.
How:          ``two_commit_repo`` / ``init_repo`` + ``commit_all`` → ``LockInputs.from_git`` →
              assert;
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
        tmp_path / "b", {"poetry.lock": "x\n", "pyproject.toml": "[project]\nname='x'\n"}
    )
    err = _refused("PROVISION_LOCK_UNSUPPORTED", pv.LockInputs.from_git, repo, sha, _cfg("pytest"))
    assert "poetry.lock" in err.message
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


# ---------------------------------------------------------------------------
# uv.lock, and a lock that moved across a repository's history (G-951, G-962)
# ---------------------------------------------------------------------------

_PYPI = 'source = { registry = "https://pypi.org/simple" }'


def _h(c: str) -> str:
    return "sha256:" + c * 64


def _uv_pkg(
    name: str,
    version: str,
    *,
    deps: str = "",
    wheels: tuple[str, ...] = ("1",),
    source: str = _PYPI,
    extra: str = "",
) -> str:
    """One ``[[package]]`` of a uv.lock; ``wheels`` are the hash characters of its wheels."""
    body = f'[[package]]\nname = "{name}"\nversion = "{version}"\n{source}\n'
    if deps:
        body += f"dependencies = [\n{deps}]\n"
    body += (
        f'sdist = {{ url = "https://files.pythonhosted.org/{name}.tar.gz", hash = "{_h("f")}" }}\n'
    )
    if wheels:
        body += (
            "wheels = [\n"
            + "".join(
                f'    {{ url = "https://files.pythonhosted.org/{name}-{c}.whl", hash = "{_h(c)}" }},\n'
                for c in wheels
            )
            + "]\n"
        )
    return body + extra + "\n"


def _uv_lock(root_deps: str = "", groups: str = "", *packages: str, version: int = 1) -> str:
    root = '[[package]]\nname = "proj"\nversion = "1.0"\nsource = { editable = "." }\n'
    if root_deps:
        root += f"dependencies = [\n{root_deps}]\n"
    if groups:
        root += f"\n[package.dev-dependencies]\n{groups}"
    return f'version = {version}\nrevision = 3\nrequires-python = ">=3.10"\n\n' + "\n".join(
        [root, *packages]
    )


#: click's shape at 05f6fd0^: no runtime dependencies, pytest in the ``tests`` group.
_CLICK_UV = _uv_lock(
    "",
    'tests = [\n    { name = "pytest" },\n]\ndev = [\n    { name = "ruff" },\n]\n',
    _uv_pkg(
        "pytest",
        "8.4.2",
        deps='    { name = "colorama", marker = "sys_platform == \'win32\'" },\n'
        '    { name = "iniconfig" },\n'
        '    { name = "tomli", marker = "python_full_version < \'3.11\'" },\n',
        wheels=("2",),
    ),
    _uv_pkg("colorama", "0.4.6", wheels=("3",)),
    _uv_pkg("iniconfig", "2.1.0", wheels=("4",)),
    _uv_pkg("tomli", "2.2.1", wheels=("5", "6")),
    _uv_pkg("ruff", "0.14.0", wheels=("7",)),
)


def _pin_lines(got: pv.LockInputs) -> list[tuple[str, str, str, tuple[str, ...]]]:
    return [(p.norm, p.version, p.marker, p.hashes) for p in got.py_pins]


def test_a_uv_lock_is_provisioned_hash_pinned_for_the_named_groups(tmp_path: Path) -> None:
    """uv.lock at the root is read like a hashed requirements lock: the project's own
    dependencies, plus the groups ``runner_opts.deps_groups`` names, closed over their
    dependencies, each pin carrying every wheel's hash and the marker of the path that
    reached it. A group nobody named (``dev``) is never fetched."""
    repo, (sha,) = _repo(
        tmp_path / "a", {"uv.lock": _CLICK_UV, "pyproject.toml": "[project]\nname='proj'\n"}
    )
    bare = pv.LockInputs.from_git(repo, sha, _cfg("pytest"))
    assert bare.recipe == pv.RECIPE_NONE and bare.py_pins == ()
    got = pv.LockInputs.from_git(repo, sha, _cfg("pytest", deps_groups=["tests"]))
    assert got.recipe == pv.RECIPE_PY
    assert got.lock_paths == ("uv.lock",)
    assert got.require_hashes is True
    assert _pin_lines(got) == [
        ("colorama", "0.4.6", "; sys_platform == 'win32'", (_h("3"),)),
        ("iniconfig", "2.1.0", "", (_h("4"),)),
        ("pytest", "8.4.2", "", (_h("2"),)),
        ("tomli", "2.2.1", "; python_full_version < '3.11'", (_h("5"), _h("6"))),
    ]
    assert got.pins == ("colorama==0.4.6", "iniconfig==2.1.0", "pytest==8.4.2", "tomli==2.2.1")


def test_the_groups_a_uv_lock_is_read_for_are_part_of_the_sets_key(tmp_path: Path) -> None:
    """One uv.lock read for two different group selections is two different sets: the
    selection is in the bundle key, so a set sealed for one never serves the other. The lock
    identity a trial is matched on is still the file's alone."""
    uv = _uv_lock(
        '    { name = "iniconfig" },\n',
        'tests = [\n    { name = "pytest" },\n]\n',
        _uv_pkg("iniconfig", "2.1.0"),
        _uv_pkg("pytest", "8.4.2", wheels=("2",)),
    )
    repo, (sha,) = _repo(tmp_path / "a", {"uv.lock": uv})
    runtime = pv.LockInputs.from_git(repo, sha, _cfg("pytest"))
    tests = pv.LockInputs.from_git(repo, sha, _cfg("pytest", deps_groups="tests"))
    assert runtime.pins == ("iniconfig==2.1.0",)
    assert tests.pins == ("iniconfig==2.1.0", "pytest==8.4.2")
    assert pv.bundle_key(pv.RECIPE_PY, IMAGE, runtime.blobs) != pv.bundle_key(
        pv.RECIPE_PY, IMAGE, tests.blobs
    )
    assert runtime.lock_key == tests.lock_key


def test_a_uv_lock_follows_extras_forks_and_joins_markers_down_the_path(tmp_path: Path) -> None:
    """An edge's extra pulls that extra's dependencies; a forked package is pinned once per
    version under its own marker; a package reached only under a marker keeps the
    conjunction of every marker on its path, and one reached unconditionally by any path
    has none; an edge back to the project is the tree itself and is never fetched."""
    uv = _uv_lock(
        '    { name = "srv", extra = ["std"] },\n'
        '    { name = "np", version = "1.0", source = { registry = "https://pypi.org/simple" }, marker = "python_full_version < \'3.11\'" },\n'
        '    { name = "np", version = "2.0", source = { registry = "https://pypi.org/simple" }, marker = "python_full_version >= \'3.11\'" },\n',
        "",
        _uv_pkg(
            "srv",
            "0.30",
            deps='    { name = "proj" },\n',
            extra='[package.optional-dependencies]\nstd = [\n    { name = "watch", marker = "sys_platform != \'win32\'" },\n    { name = "h11" },\n]\n',
        ),
        _uv_pkg(
            "watch",
            "1.0",
            deps='    { name = "deep", marker = "python_full_version < \'3.13\'" },\n',
        ),
        _uv_pkg("deep", "3.0"),
        _uv_pkg("h11", "0.16", deps='    { name = "deep" },\n'),
        _uv_pkg("np", "1.0", wheels=("8",)),
        _uv_pkg("np", "2.0", wheels=("9",)),
    )
    repo, (sha,) = _repo(tmp_path / "a", {"uv.lock": uv})
    got = pv.LockInputs.from_git(repo, sha, _cfg("pytest"))
    markers = {(p.norm, p.version): p.marker for p in got.py_pins}
    assert markers == {
        ("deep", "3.0"): "",  # also reached unconditionally through h11
        ("h11", "0.16"): "",
        ("np", "1.0"): "; python_full_version < '3.11'",
        ("np", "2.0"): "; python_full_version >= '3.11'",
        ("srv", "0.30"): "",
        ("watch", "1.0"): "; sys_platform != 'win32'",
    }
    only_watch = uv.replace('    { name = "h11" },\n', "")
    repo, (sha,) = _repo(tmp_path / "b", {"uv.lock": only_watch})
    deep = {p.norm: p.marker for p in pv.LockInputs.from_git(repo, sha, _cfg("pytest")).py_pins}
    assert deep["deep"] == "; (python_full_version < '3.13') and (sys_platform != 'win32')"


@pytest.mark.parametrize(
    "source",
    [
        'source = { git = "https://github.com/x/y?rev=1#abc" }',
        'source = { url = "https://example.test/y-1.0.tar.gz" }',
        'source = { path = "../y" }',
        'source = { directory = "vendor/y" }',
        'source = { editable = "libs/y" }',
        'source = { registry = "https://mirror.example.test/simple" }',
    ],
)
def test_a_uv_lock_source_other_than_the_public_index_is_refused(
    tmp_path: Path, source: str
) -> None:
    uv = _uv_lock('    { name = "y" },\n', "", _uv_pkg("y", "1.0", source=source))
    repo, (sha,) = _repo(tmp_path / "a", {"uv.lock": uv})
    err = _refused("PROVISION_SOURCE_REFUSED", pv.LockInputs.from_git, repo, sha, _cfg("pytest"))
    assert "y" in err.message


def test_a_uv_lock_that_cannot_be_hash_pinned_is_refused_never_loosened(tmp_path: Path) -> None:
    """A package with no wheel that every environment needs must be built:
    ``PROVISION_BUILD_REQUIRED`` before any fetch. One only another platform needs keeps its
    source hash and its marker, so pip skips it here. A lock format, a workspace or an
    ambiguous fork this reader does not know is ``PROVISION_LOCK_UNSUPPORTED``; a group the
    lock does not carry is ``PROVISION_NO_LOCK``."""
    no_wheel = _uv_lock('    { name = "y" },\n', "", _uv_pkg("y", "1.0", wheels=()))
    repo, (sha,) = _repo(tmp_path / "a", {"uv.lock": no_wheel})
    _refused("PROVISION_BUILD_REQUIRED", pv.LockInputs.from_git, repo, sha, _cfg("pytest"))
    win_only = _uv_lock(
        '    { name = "y", marker = "sys_platform == \'win32\'" },\n',
        "",
        _uv_pkg("y", "1.0", wheels=()),
    )
    repo, (sha,) = _repo(tmp_path / "b", {"uv.lock": win_only})
    (pin,) = pv.LockInputs.from_git(repo, sha, _cfg("pytest")).py_pins
    assert (pin.marker, pin.hashes) == ("; sys_platform == 'win32'", (_h("f"),))
    cases = {
        "c": _uv_lock('    { name = "y" },\n', "", _uv_pkg("y", "1.0"), version=2),
        "d": _uv_lock("", "", _uv_pkg("y", "1.0", source='source = { editable = "." }')),
        "e": _uv_lock('    { name = "y" },\n', "", _uv_pkg("y", "1.0"), _uv_pkg("y", "2.0")),
        "f": "not = [toml\n",
    }
    for name, text in cases.items():
        repo, (sha,) = _repo(tmp_path / name, {"uv.lock": text})
        err = _refused(
            "PROVISION_LOCK_UNSUPPORTED", pv.LockInputs.from_git, repo, sha, _cfg("pytest")
        )
        assert "uv.lock" in err.message
    repo, (sha,) = _repo(tmp_path / "g", {"uv.lock": _CLICK_UV})
    err = _refused(
        "PROVISION_NO_LOCK",
        pv.LockInputs.from_git,
        repo,
        sha,
        _cfg("pytest", deps_groups=["tests", "typing"]),
    )
    assert "typing" in err.message


def test_one_declaration_provisions_a_lock_that_moved_across_the_history(tmp_path: Path) -> None:
    """click kept ``requirements/tests.txt`` until May 2025 and ``uv.lock`` after it. A
    ``deps_lock`` entry that is a list names alternatives: each commit reads the first it
    carries, so one configuration provisions both eras; a commit that carries none is
    refused naming every alternative. A plain entry must still be carried by every commit."""
    tests_txt = (
        "#\n# This file is autogenerated by pip-compile\n#\n"
        "iniconfig==1.0.0          # via pytest\npytest==6.0.1             # via -r tests.in\n"
    )
    root = tmp_path / "click"
    repo, (old, new) = _repo(
        root,
        {"requirements/tests.txt": tests_txt, "setup.py": "from setuptools import setup\n"},
        {"uv.lock": _CLICK_UV, "pyproject.toml": "[project]\nname='proj'\n"},
    )
    git(root, "rm", "-q", "requirements/tests.txt", "setup.py")
    uv_only = commit_all(root, "the requirements lock retired")
    git(root, "rm", "-q", "uv.lock")
    gone = commit_all(root, "neither lock")
    cfg = _cfg("pytest", deps_lock=[["uv.lock", "requirements/tests.txt"]], deps_groups=["tests"])
    was = pv.LockInputs.from_git(repo, old, cfg)
    assert (was.recipe, was.lock_paths) == (pv.RECIPE_PY, ("requirements/tests.txt",))
    assert was.pins == ("iniconfig==1.0.0", "pytest==6.0.1")
    for sha in (new, uv_only):  # the first alternative wins while both are carried
        now = pv.LockInputs.from_git(repo, sha, cfg)
        assert now.lock_paths == ("uv.lock",)
        assert "pytest==8.4.2" in now.pins
    err = _refused("PROVISION_NO_LOCK", pv.LockInputs.from_git, repo, gone, cfg)
    assert "uv.lock" in err.message and "requirements/tests.txt" in err.message
    strict = _cfg("pytest", deps_lock=["requirements/tests.txt"])
    _refused("PROVISION_NO_LOCK", pv.LockInputs.from_git, repo, uv_only, strict)
    for bad in ({"a": 1}, [["uv.lock", 3]], [[]], ""):
        _refused(
            "PROVISION_NO_LOCK", pv.LockInputs.from_git, repo, new, _cfg("pytest", deps_lock=bad)
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
