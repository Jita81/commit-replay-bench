"""Belt 5 under docker: the commit's pinned ruff, sealed (ADR-0011 §5).

The sandbox images carry no linter, so belt 5 under docker ran a bare ``ruff`` that
resolved nowhere: every pallets/click task was ``QUAL_GOLD_LINT`` (rc 127) at Wave 3 step 7
(2026-10-25), and ``grade.py`` runs the same belt on every Python trial. The fix seals the
ruff the commit itself pins as a read-only set at ``/deps/lint`` and runs it from there;
the label is the set manifest's version; a missing set or a wrong version is refused inside
the sandbox, as a pin mismatch is on the host.

Navigation
----------
What it is:   The suite for the sealed lint set: the pin, the set, the binding and the plan.
What it does: Pins that the ONE ruff version is read from the commit (a frozen pre-commit
              rev, an exact pin, a range only through ``uv.lock``), from a worktree or a
              commit's object store alike; that the recipe seals exactly that wheel (a wrong
              wheel is a note, a stored set holding the wrong tool under the key is
              quarantined and sealed afresh, a run-scope refusal stops the run) and the
              provider puts the sets on all three roles under
              docker only; that the task's keys cite them (re-hashed, revocable); and the
              break-and-restore: a missing set or a wrong version is REFUSED — a harness
              error, never a label — and the restored set runs ``/deps/lint/bin/ruff``
              read-only, labelled ``ruff@<version>``.
How:          Synthetic repositories committed under ``tmp_path``, a ``SealedProvider`` whose
              fetch is faked (the pure layer), ``FakeExecutor`` for the plan, and — with a
              daemon, the shipped Python image and the package index — the real ruff wheel
              sealed and run in the sandbox on a click-shaped tree.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0011-repo-lint-belt.md
Works with:   src/crb/core/lint.py (``sealed_ruff_version``, ``python_plan(sealed=…)``),
              src/crb/provision/python.py (``lint_sets``), src/crb/provision/__init__.py (the
              resolve hook), src/crb/core/deps.py (``LintSet``, ``TaskDeps.keys``),
              src/crb/core/provision.py (``uv_locked``), src/crb/core/runners/pytest_runner.py
              (``detect_lint`` under docker)
Tested by:    tests/test_lint_sealed_ruff.py
Touch when:   onboarding a Python repository whose ruff pin lives somewhere the evidence does
              not read (add the source and a case here); a language gains a sealed lint
              recipe; the lint set's mount or label changes.
"""

from __future__ import annotations

import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from crb.core import lint as lint_mod
from crb.core.deps import (
    BUNDLE_INTEGRITY,
    SCOPE_RUN,
    BundleMount,
    DepsBinding,
    LintSet,
    ProvisionRefused,
    TaskDeps,
    register_store_root,
)
from crb.core.execution import Command, DockerExecutor, DockerSettings, ExecResult
from crb.core.git import GitRepo
from crb.core.miners import MineSource, _TreeFiles
from crb.core.provision import uv_locked
from crb.core.runners import get_runner
from crb.core.spec import Language, RepoConfig
from crb.provision import LINT_RECIPES, SealedProvider
from crb.provision import python as py_recipe
from crb.provision.config import DEFAULT_PYTHON_IMAGE, ProvisionConfig
from crb.provision.fetch import FetchResult
from crb.provision.store import remove_tree

try:
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover
    import conftest_langs as langs

#: pallets/click's own shape (``pre-commit autoupdate --freeze``): a sha rev, the version in
#: the comment.
CLICK_PRECOMMIT = (
    "repos:\n"
    "  - repo: https://github.com/astral-sh/ruff-pre-commit\n"
    "    rev: c60c980e561ed3e73101667fe8365c609d19a438  # frozen: v0.15.9\n"
    "    hooks:\n"
    "      - id: ruff\n"
    "      - id: ruff-format\n"
)
H1, H2 = "sha256:" + "a" * 64, "sha256:" + "b" * 64


def _uv_lock(version: str = "0.15.9", hashes: tuple[str, ...] = (H1, H2), **src: str) -> str:
    source = src or {"registry": "https://pypi.org/simple"}
    wheels = ",\n".join(
        f'    {{ url = "https://files.pythonhosted.org/ruff-{version}-{i}.whl", hash = "{h}" }}'
        for i, h in enumerate(hashes)
    )
    kind, where = next(iter(source.items()))
    return (
        'version = 1\nrequires-python = ">=3.10"\n\n'
        f'[[package]]\nname = "ruff"\nversion = "{version}"\n'
        f'source = {{ {kind} = "{where}" }}\nwheels = [\n{wheels},\n]\n'
    )


def _uv_universal(*entries: tuple[str, str]) -> str:
    """A universal lock holding ruff once per ``(version, hash)`` — uv writes one package at
    several versions when disjoint ``resolution-markers`` resolve it differently."""
    head = 'version = 1\nrequires-python = ">=3.10"\n\n'
    return head + "\n".join(_uv_lock(v, (h,)).split("\n\n", 1)[1] for v, h in entries)


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@crb.invalid", "-c", "user.name=t", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit(root: Path, files: dict[str, str], message: str) -> str:
    _write(root, files)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def _repo(tmp_path: Path, parent: dict[str, str], gold: dict[str, str]) -> tuple[GitRepo, str, str]:
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    base = {"src/pkg/__init__.py": "", "tests/test_x.py": "def test_x() -> None:\n    pass\n"}
    p = _commit(root, {**base, **parent}, "parent")
    g = _commit(root, gold, "gold")
    return GitRepo(root), p, g


class FakeExecutor:
    """Scripted results; records every command; ``name`` picks the posture."""

    def __init__(self, *results: ExecResult, name: str = "docker") -> None:
        self.name = name
        self._results = list(results)
        self.commands: list[Command] = []

    def run(self, cmd: Command) -> ExecResult:
        self.commands.append(cmd)
        return self._results.pop(0)

    def tool(self, name: str, host_override: str | None = None) -> str:
        return host_override or name

    def describe(self) -> dict[str, Any]:
        return {"executor": "fake"}


def _ok() -> ExecResult:
    return ExecResult(0, "", "", False, 0.01)


def _lint_set(tmp_path: Path, version: str, tag: str = "a") -> LintSet:
    """A set as the store names one: ``<store>/python/<key>/site`` at ``/deps/lint``."""
    store = register_store_root(tmp_path / "store")
    key = "dep_" + (tag * 64)[:64]
    host = store / "python" / key / "site"
    host.mkdir(parents=True, exist_ok=True)
    mount = BundleMount(host_path=host, container_path=py_recipe.LINT_INSIDE, key=key)
    return LintSet("ruff", version, key, "sha256:" + "d" * 64, mount)


# ---------------------------------------------------------------------------
# 1. the pin: one version, read from the commit
# ---------------------------------------------------------------------------


def test_uv_locked_is_the_public_index_wheel_pin_or_nothing() -> None:
    pin = uv_locked(_uv_lock(), "ruff")
    assert pin is not None and pin.version == "0.15.9" and pin.hashes == (H1, H2)
    assert uv_locked(_uv_lock(), "black") is None
    assert uv_locked(_uv_lock(hashes=(H1, "md5:x")), "ruff") is None  # every wheel hashed
    assert uv_locked(_uv_lock(hashes=()), "ruff") is None
    assert uv_locked(_uv_lock(registry="https://mirror.example/simple"), "ruff") is None
    assert uv_locked(_uv_lock(git="https://github.com/astral-sh/ruff"), "ruff") is None
    assert uv_locked("not [toml", "ruff") is None and uv_locked("", "ruff") is None


def test_a_universal_lock_gives_the_entry_the_pin_names_not_the_first() -> None:
    """``accept`` passes over the entries the pin rejects; without it the first entry is
    the answer, as before."""
    lock = _uv_universal(("0.14.0", H1), ("0.15.9", H2))
    first = uv_locked(lock, "ruff")
    assert first is not None and (first.version, first.hashes) == ("0.14.0", (H1,))
    pin = uv_locked(lock, "ruff", lambda v: v == "0.15.9")
    assert pin is not None and (pin.version, pin.hashes) == ("0.15.9", (H2,))
    assert uv_locked(lock, "ruff", lambda v: v == "0.16.0") is None


@pytest.mark.parametrize(
    ("files", "version", "why"),
    [
        ({".pre-commit-config.yaml": CLICK_PRECOMMIT}, "0.15.9", ""),
        (
            {
                ".pre-commit-config.yaml": CLICK_PRECOMMIT.replace(
                    "c60c980e561ed3e73101667fe8365c609d19a438  # frozen: v0.15.9", "v0.4.4"
                )
            },
            "0.4.4",
            "",
        ),
        ({"requirements-dev.txt": "pytest\nruff==0.6.1\n"}, "0.6.1", ""),
        # a hashed pin: the continuation and the inline option are not part of the spec
        ({"requirements-dev.txt": f"ruff==0.6.1 \\\n    --hash=sha256:{H1}\n"}, "0.6.1", ""),
        ({"requirements.txt": f"ruff==0.6.2 --hash=sha256:{H1}\n"}, "0.6.2", ""),
        # a range names a version only through the lock, and only one that satisfies it
        (
            {
                "pyproject.toml": '[project]\nname = "x"\nversion = "0"\n'
                '[dependency-groups]\ndev = ["ruff>=0.15,<0.16"]\n',
                "uv.lock": _uv_lock("0.15.9"),
            },
            "0.15.9",
            "",
        ),
        (
            {
                "pyproject.toml": '[project]\nname = "x"\nversion = "0"\n'
                '[dependency-groups]\ndev = ["ruff>=0.16"]\n',
                "uv.lock": _uv_lock("0.15.9"),
            },
            "",
            "the repository's pin ruff>=0.16 names no exact version and uv.lock holds none",
        ),
        (
            {
                "pyproject.toml": '[project]\nname = "x"\nversion = "0"\n'
                '[dependency-groups]\ndev = ["ruff>=0.15"]\n'
            },
            "",
            "the repository's pin ruff>=0.15 names no exact version and uv.lock holds none",
        ),
        ({"uv.lock": _uv_lock("0.15.2")}, "0.15.2", ""),  # the lock IS a pin
        # a universal lock: the entry within the range, wherever it sits; two within it, none
        (
            {
                "pyproject.toml": '[project]\nname = "x"\nversion = "0"\n'
                '[dependency-groups]\ndev = ["ruff>=0.15,<0.16"]\n',
                "uv.lock": _uv_universal(("0.14.0", H1), ("0.15.9", H2)),
            },
            "0.15.9",
            "",
        ),
        (
            {
                "pyproject.toml": '[project]\nname = "x"\nversion = "0"\n'
                '[dependency-groups]\ndev = ["ruff>=0.14"]\n',
                "uv.lock": _uv_universal(("0.14.0", H1), ("0.15.9", H2)),
            },
            "",
            "uv.lock holds ruff 0.14.0 and 0.15.9 within the pin ruff>=0.14 under different "
            "markers; which one judges is not decided here",
        ),
        (
            {"uv.lock": _uv_universal(("0.14.0", H1), ("0.15.9", H2))},
            "",
            "uv.lock holds ruff 0.14.0 and 0.15.9 under different markers; which one judges "
            "is not decided here",
        ),
        (
            {"ruff.toml": "line-length = 88\n"},
            "",
            "the repository pins no ruff version (pre-commit, pyproject, requirements, uv.lock)",
        ),
    ],
)
def test_sealed_ruff_version_names_one_version_or_says_why(
    tmp_path: Path, files: dict[str, str], version: str, why: str
) -> None:
    """The version a set holds is the commit's — never "latest", never a host binary's."""
    _write(tmp_path, files)
    assert lint_mod.sealed_ruff_version(tmp_path) == (version, why)


def test_the_pin_reads_a_commit_as_it_reads_a_worktree(tmp_path: Path) -> None:
    """``pinned_ruff_spec`` / ``sealed_ruff_version`` over :class:`ConfigFiles`: a worktree
    (``DirFiles``), a commit's object store (the provisioner's ``_CommitFiles``) and a mine
    source (``_TreeFiles``) give the same answer, and ``files_under("")`` is the root's
    FILES as bare names (a directory named ``requirements`` is not one)."""
    files = {
        "requirements-dev.txt": "ruff==0.6.1\n",
        "requirements/tests.txt": "ruff==9.9.9\n",  # not at the root: not evidence
        "uv.lock": _uv_lock("0.15.9"),
    }
    repo, _, gold = _repo(tmp_path, {}, files)
    on_disk = lint_mod.DirFiles(repo.path)
    commit = py_recipe._CommitFiles(repo, gold)
    blobs = {f: (repo.path / f).read_bytes() for f in _git(repo.path, "ls-files").splitlines()}
    mined = _TreeFiles(MineSource("r", gold, blobs, blobs.get))
    for view in (on_disk, commit, mined):
        assert lint_mod.pinned_ruff_spec(view) == "==0.6.1"
        assert lint_mod.sealed_ruff_version(view) == ("0.6.1", "")
        assert view.files_under("") == ["requirements-dev.txt", "uv.lock"]
        assert view.files_under("requirements") == ["requirements/tests.txt"]
    # the commit, not the worktree: an edit on disk changes nothing the provisioner reads
    (repo.path / "requirements-dev.txt").write_text("ruff==0.7.0\n", encoding="utf-8")
    assert lint_mod.sealed_ruff_version(commit) == ("0.6.1", "")
    assert lint_mod.sealed_ruff_version(on_disk) == ("0.7.0", "")
    assert commit.is_file("uv.lock") and not commit.is_file("requirements")
    assert commit.text("nope.txt") == "" and commit.files_under("nope") == []


# ---------------------------------------------------------------------------
# 2. the set: exactly the pinned wheel, sealed; on every role under docker only
# ---------------------------------------------------------------------------


@pytest.fixture
def provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SealedProvider:
    p = SealedProvider(ProvisionConfig(enabled=True, env="dev", store=tmp_path / "deps"))
    monkeypatch.setattr(p, "image_id", lambda image: "sha256:" + "e" * 64)
    return p


def _fake_pip(
    provider: SealedProvider,
    monkeypatch: pytest.MonkeyPatch,
    *,
    installs: str | None = None,
    with_bin: bool = True,
) -> list[str]:
    """A fetch that writes one wheel and an install that writes ``ruff-<v>.dist-info`` and
    ``bin/ruff`` — ``installs`` overrides the version pip "installed". Returns the steps."""
    steps: list[str] = []

    def fetch(plan: Any, stage: Path) -> FetchResult:
        steps.append(plan.step)
        lock = plan.inputs.get("lock.txt", b"").decode() if plan.step == "fetch" else ""
        if plan.step == "fetch":
            wheels = stage / "out" / "wheels"
            wheels.mkdir(parents=True, exist_ok=True)
            version = lock.split("==", 1)[1].split()[0]
            (wheels / f"ruff-{version}-py3-none-any.whl").write_bytes(lock.encode())
            steps.append(lock)
        else:
            version = next((stage / "out" / "wheels").glob("*.whl")).name.split("-")[1]
            site = stage / "out" / "site"
            (site / f"ruff-{installs or version}.dist-info").mkdir(parents=True)
            if with_bin:
                (site / "bin").mkdir()
                (site / "bin" / "ruff").write_text("#!/bin/sh\n", encoding="utf-8")
        return FetchResult(stage, "", "", 0.0)

    monkeypatch.setattr(provider, "fetch", fetch)
    return steps


def test_the_recipe_seals_exactly_the_commits_ruff_and_reuses_it(
    tmp_path: Path, provider: SealedProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, parent, gold = _repo(
        tmp_path, {".pre-commit-config.yaml": CLICK_PRECOMMIT, "uv.lock": _uv_lock()}, {"a": "1"}
    )
    steps = _fake_pip(provider, monkeypatch)
    sets, note = py_recipe.lint_sets(provider, repo, (parent, gold))
    assert note == "" and len(sets) == 1, "one version, one set"
    (s,) = sets
    assert (s.name, s.version, s.bin) == ("ruff", "0.15.9", "/deps/lint/bin/ruff")
    assert s.mount.container_path == "/deps/lint" and s.mount.key == s.key
    # the committed hashes go to pip: --require-hashes on both steps
    assert steps[:2] == ["fetch", f"ruff==0.15.9 --hash={H1} --hash={H2}\n"]
    assert steps[2] == "install"
    sealed = provider.store.verify(s.key)
    assert sealed.digest == s.digest
    assert (sealed.manifest["recipe"], sealed.manifest["tool"]) == ("py.lint.v1", "ruff")
    assert sealed.manifest["version"] == "0.15.9" and sealed.manifest["hashes"] == "committed"
    assert (sealed.path / "site" / "bin" / "ruff").is_file()
    assert not (sealed.path / "wheels").exists()
    # a second resolve reuses the set: no fetch
    steps.clear()
    again, _ = py_recipe.lint_sets(provider, repo, (parent, gold))
    assert again == sets and steps == []


def test_an_exact_pin_takes_the_hashes_of_its_own_entry_in_a_universal_lock(
    tmp_path: Path, provider: SealedProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pinned version's entry is second in the lock: its hashes still go to pip — the
    first entry is another version and is never a reason to install by version alone."""
    lock = _uv_universal(("0.14.0", H1), ("0.15.9", H2))
    repo, parent, gold = _repo(
        tmp_path, {".pre-commit-config.yaml": CLICK_PRECOMMIT, "uv.lock": lock}, {"a": "1"}
    )
    steps = _fake_pip(provider, monkeypatch)
    sets, note = py_recipe.lint_sets(provider, repo, (parent, gold))
    assert note == "" and [s.version for s in sets] == ["0.15.9"]
    assert steps[:2] == ["fetch", f"ruff==0.15.9 --hash={H2}\n"]
    assert provider.store.verify(sets[0].key).manifest["hashes"] == "committed"


def test_parent_and_gold_pinning_different_ruffs_get_one_set_each(
    tmp_path: Path, provider: SealedProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    bumped = CLICK_PRECOMMIT.replace(
        "c60c980e561ed3e73101667fe8365c609d19a438  # frozen: v0.15.9", "v0.15.10"
    )
    repo, parent, gold = _repo(
        tmp_path,
        {".pre-commit-config.yaml": CLICK_PRECOMMIT},
        {".pre-commit-config.yaml": bumped},
    )
    _fake_pip(provider, monkeypatch)
    sets, note = py_recipe.lint_sets(provider, repo, (parent, gold))
    assert note == "" and [s.version for s in sets] == ["0.15.10", "0.15.9"]
    assert len({s.key for s in sets}) == 2


def test_a_commit_that_pins_no_ruff_or_a_wrong_wheel_is_a_note_never_a_set(
    tmp_path: Path, provider: SealedProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    unpinned = {"pyproject.toml": '[project]\nname="x"\nversion="0"\n[tool.ruff]\nline-length=88\n'}
    repo, parent, gold = _repo(tmp_path, unpinned, {"a": "1"})
    steps = _fake_pip(provider, monkeypatch)
    sets, note = py_recipe.lint_sets(provider, repo, (parent, gold))
    assert sets == () and steps == []
    assert note == (
        f"{parent[:12]}: the repository pins no ruff version (pre-commit, pyproject, "
        f"requirements, uv.lock); {gold[:12]}: the repository pins no ruff version "
        "(pre-commit, pyproject, requirements, uv.lock)"
    )
    # a commit that configures no ruff at all asks for nothing and says nothing
    repo2, p2, g2 = _repo(tmp_path / "plain", {"setup.cfg": "[metadata]\n"}, {"a": "1"})
    assert py_recipe.lint_sets(provider, repo2, (p2, g2)) == ((), "")
    # pip installed another version, or no executable: refused, nothing sealed
    repo3, p3, g3 = _repo(tmp_path / "w", {".pre-commit-config.yaml": CLICK_PRECOMMIT}, {"a": "1"})
    for installs, with_bin, held in (("0.16.0", True, "['0.16.0']"), (None, False, "['0.15.9']")):
        _fake_pip(provider, monkeypatch, installs=installs, with_bin=with_bin)
        sets, note = py_recipe.lint_sets(provider, repo3, (p3, g3))
        assert sets == () and note.startswith("ruff==0.15.9: PROVISION_FETCH_FAILED: ")
        assert f"installed {held}" in note
        assert not any(provider.store.root.glob("python/dep_*")), "nothing sealed"


def test_a_set_under_the_key_holding_another_tool_is_quarantined_and_sealed_afresh(
    tmp_path: Path, provider: SealedProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stored set under the lint key whose manifest is not ``ruff==<pin>`` is damaged: it
    goes to quarantine and the pinned ruff is sealed afresh — never labelled, and never a
    store that refuses every later run."""
    repo, parent, gold = _repo(tmp_path, {".pre-commit-config.yaml": CLICK_PRECOMMIT}, {"a": "1"})
    steps = _fake_pip(provider, monkeypatch)
    (good,), _ = py_recipe.lint_sets(provider, repo, (parent, gold))
    provider.store.quarantine(good.key, "test: make room for a damaged set")
    stage = provider.store.stage()
    (stage / "out" / "site" / "bin").mkdir(parents=True)
    (stage / "out" / "site" / "bin" / "ruff").write_text("#!/bin/sh\n", encoding="utf-8")
    provider.store.seal(
        stage, {"lang": "python", "key": good.key, "tool": "black", "version": "24.1.0"}
    )
    steps.clear()
    (again,), note = py_recipe.lint_sets(provider, repo, (parent, gold))
    assert note == "" and (again.key, again.version) == (good.key, "0.15.9")
    assert steps[0] == "fetch", "sealed afresh, not reused"
    assert provider.store.verify(again.key).manifest["tool"] == "ruff"
    reasons = [str(r["reason"]) for r in provider.store.quarantined()]
    assert f"lint set {good.key} holds black==24.1.0, not ruff==0.15.9" in reasons


def test_a_fresh_set_the_manifest_check_rejects_is_bundle_integrity(
    provider: SealedProvider,
) -> None:
    """Defence in depth: a build whose manifest the caller rejects is quarantined at once
    and refused as ``BUNDLE_INTEGRITY`` naming the key (run scope) — never returned."""
    key = "dep_" + "c" * 64

    def build(stage: Path) -> dict[str, Any]:
        (stage / "out" / "f").write_text("x", encoding="utf-8")
        return {"tool": "black"}

    def accept(manifest: Any) -> str:
        return "" if manifest.get("tool") == "ruff" else "holds black"

    with pytest.raises(ProvisionRefused) as ei:
        provider.seal_or_reuse("python", key, build, accept)
    assert ei.value.code == BUNDLE_INTEGRITY and ei.value.keys == (key,)
    assert provider.store.find(key) is None
    assert [r["reason"] for r in provider.store.quarantined()] == ["holds black"]


def test_a_run_scope_refusal_refuses_the_run_never_a_note(
    tmp_path: Path, provider: SealedProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a task-scope refusal (the wheel would not fetch) becomes the lint step's note; a
    run-scope one (a store the daemon cannot see, a damaged set) stops the run."""
    repo, parent, gold = _repo(tmp_path, {".pre-commit-config.yaml": CLICK_PRECOMMIT}, {"a": "1"})

    def fetch(plan: Any, stage: Path) -> FetchResult:
        raise ProvisionRefused("PROVISION_STORE_NOT_VISIBLE", "the daemon sees another store")

    monkeypatch.setattr(provider, "fetch", fetch)
    with pytest.raises(ProvisionRefused) as ei:
        py_recipe.lint_sets(provider, repo, (parent, gold))
    assert ei.value.code == "PROVISION_STORE_NOT_VISIBLE" and ei.value.scope == SCOPE_RUN


def test_the_provider_puts_the_sets_on_every_role_under_docker_only(
    tmp_path: Path, provider: SealedProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _, gold = _repo(tmp_path, {".pre-commit-config.yaml": CLICK_PRECOMMIT}, {"a": "1"})
    s = _lint_set(tmp_path, "0.15.9")
    calls: list[tuple[str, ...]] = []

    def recipe(p: SealedProvider, r: GitRepo, shas: tuple[str, ...]) -> tuple[Any, str]:
        calls.append(shas)
        return (s,), "a note"

    monkeypatch.setitem(LINT_RECIPES, "python", recipe)
    config = RepoConfig(name="r", language=Language.PYTHON)
    deps = provider.resolve(repo, config, gold=gold, executor_name="docker")
    assert calls == [(repo.parent(gold), gold)]
    for b in (deps.parent, deps.gold, deps.builder):
        assert b.lint == (s,) and b.lint_note == "a note"
    assert s.key in deps.keys and deps.digests[s.key] == s.digest
    local = provider.resolve(repo, config, gold=gold, executor_name="local")
    assert len(calls) == 1, "no lint set is provisioned for the host"
    assert all(b.lint == () for b in (local.parent, local.gold, local.builder))


def test_the_task_cites_its_lint_sets_so_a_damaged_one_revokes(tmp_path: Path) -> None:
    """``TaskDeps.keys`` is what a qualification records and ``revoke_citing`` matches;
    ``to_dict`` carries the sets (the evidence) only when there are any."""
    s = _lint_set(tmp_path, "0.15.9")
    site = DepsBinding(role="parent", lang="python", key="dep_" + "1" * 64, digest="sha256:1")
    bare = DepsBinding(role="gold", lang="python")
    assert "lint" not in bare.to_dict() and "lint_note" not in bare.to_dict()
    with_lint = DepsBinding(role="gold", lang="python", lint=(s,), lint_note="n")
    assert with_lint.lint == (s,)
    assert with_lint.to_dict()["lint"] == [s.to_dict()] and with_lint.to_dict()["lint_note"] == "n"
    deps = TaskDeps("sealed", "python", site, with_lint, DepsBinding(role="builder", lint=(s,)))
    assert deps.keys == (site.key, s.key)
    assert deps.digests == {site.key: site.digest, s.key: s.digest}


# ---------------------------------------------------------------------------
# 3. break-and-restore: missing or wrong ruff is REFUSED, not labelled
# ---------------------------------------------------------------------------


@pytest.fixture
def click_tree(tmp_path: Path) -> Path:
    root = tmp_path / "click"
    _write(root, {".pre-commit-config.yaml": CLICK_PRECOMMIT, "src/click/core.py": "x = 1\n"})
    return root


def _refused(plan: lint_mod.LintPlan | None, root: Path) -> tuple[lint_mod.LintRun, FakeExecutor]:
    assert plan is not None
    ex = FakeExecutor()
    run = lint_mod.run_plan(plan, ex, root, ["src/click/core.py"])
    return run, ex


def test_break_and_restore_the_sealed_ruff(click_tree: Path, tmp_path: Path) -> None:
    good = _lint_set(tmp_path, "0.15.9", "a")
    wrong = _lint_set(tmp_path, "0.16.0", "b")

    # restored: the commit's ruff, from the set, read-only, labelled with its version
    plan = lint_mod.python_plan(click_tree, None, sealed=(wrong, good))
    assert plan is not None and plan.detected == "ruff@0.15.9+ruff-format"
    for tool in plan.tools:
        assert tool.argv[0] == "/deps/lint/bin/ruff" and not tool.refuse
        assert tool.ro_mounts == (good.mount,) and tool.env == {"RUFF_NO_CACHE": "true"}
    ex = FakeExecutor(_ok(), _ok())
    run = lint_mod.run_plan(plan, ex, click_tree, ["src/click/core.py"])
    assert run.ok is True and run.error == ""
    assert [c.argv[:2] for c in ex.commands] == [
        ("/deps/lint/bin/ruff", "check"),
        ("/deps/lint/bin/ruff", "format"),
    ]
    assert all(c.ro_mounts == (good.mount,) for c in ex.commands)
    assert all(c.env["RUFF_NO_CACHE"] == "true" for c in ex.commands)

    # break 1: no set at all — refused with the provisioner's reason; no version is claimed
    plan = lint_mod.python_plan(
        click_tree, None, sealed=(), sealed_note="ruff==0.15.9: PROVISION_FETCH_FAILED: x"
    )
    assert plan is not None and plan.detected == "ruff+ruff-format"
    assert all(t.argv[0] == "ruff" and t.ro_mounts == () for t in plan.tools)
    run, ex = _refused(plan, click_tree)
    assert ex.commands == [], "a refused step never runs"
    assert run.ok is False and run.error.startswith("no sealed ruff for this commit")
    assert "PROVISION_FETCH_FAILED" in run.error
    (step,) = run.steps
    assert (step.rc, step.verdict) == (127, None), "a harness error, not a rejection"

    # break 2: a set, but not the pinned version — refused, the tag says so
    plan = lint_mod.python_plan(click_tree, None, sealed=(wrong,))
    assert plan is not None and plan.detected == "ruff@0.16.0!pin==0.15.9+ruff-format"
    run, ex = _refused(plan, click_tree)
    assert ex.commands == [] and run.ok is False and run.steps[0].verdict is None
    assert "no sealed ruff satisfies the repository's pin ruff==0.15.9 (sealed: 0.16.0)" in (
        run.error
    )
    assert lint_mod.fix_commands(plan, ["src/click/core.py"]) == [], "no fixer either"
    # ...and the provisioner's reason the pinned set is absent stays in the refusal
    plan = lint_mod.python_plan(
        click_tree, None, sealed=(wrong,), sealed_note="ruff==0.15.9: PROVISION_FETCH_FAILED: x"
    )
    run, ex = _refused(plan, click_tree)
    assert ex.commands == [] and run.steps[0].verdict is None
    assert "(sealed: 0.16.0); ruff==0.15.9: PROVISION_FETCH_FAILED: x" in run.error

    # break 3: the commit pins nothing — refused with that reason, whatever is sealed
    unpinned = tmp_path / "unpinned"
    _write(unpinned, {"ruff.toml": "line-length = 88\n", "src/a.py": "x = 1\n"})
    plan = lint_mod.python_plan(unpinned, None, sealed=(good,))
    assert plan is not None and plan.detected == "ruff"
    run, ex = _refused(plan, unpinned)
    assert ex.commands == [] and run.ok is False and run.steps[0].verdict is None
    assert "the repository pins no ruff version" in run.error

    # restored again
    plan = lint_mod.python_plan(click_tree, None, sealed=(good,))
    assert plan is not None and plan.detected == "ruff@0.15.9+ruff-format"
    assert lint_mod.fix_commands(plan, ["src/click/core.py"])[0][1][:2] == (
        "/deps/lint/bin/ruff",
        "check",
    )


def test_the_runner_reads_the_bound_sets_under_docker_and_the_host_ruff_locally(
    click_tree: Path, tmp_path: Path
) -> None:
    good = _lint_set(tmp_path, "0.15.9")
    runner = get_runner(RepoConfig(name="click", language=Language.PYTHON))
    binding = DepsBinding(role="gold", lang="python", lint=(good,))
    plan = runner.lint_plan(click_tree, FakeExecutor(), deps=binding)
    assert plan is not None and plan.detected == "ruff@0.15.9+ruff-format"
    assert runner.deps is None, "the binding is restored after the plan"
    unbound = runner.lint_plan(click_tree, FakeExecutor())
    assert unbound is not None and unbound.detected == "ruff+ruff-format"
    assert all(t.refuse.startswith("no sealed ruff for this commit") for t in unbound.tools)
    host = runner.lint_plan(click_tree, FakeExecutor(name="local"), deps=binding)
    assert host is None or all(t.ro_mounts == () for t in host.tools), "never a set on the host"


# ---------------------------------------------------------------------------
# 4. the real thing: click's ruff sealed from the index, run in the sandbox
# ---------------------------------------------------------------------------


@pytest.fixture
def scratch() -> Iterator[Path]:
    langs.require_docker()
    langs.require_docker_image(DEFAULT_PYTHON_IMAGE, "the pinned python fetch image")
    root = langs.CACHE_DIR / "provision" / f"lint-{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    yield root
    remove_tree(root)


@pytest.mark.docker
@pytest.mark.slow
@pytest.mark.network("pypi.org", "files.pythonhosted.org")
@pytest.mark.sandbox_images
def test_clicks_pinned_ruff_is_sealed_and_judges_in_the_sandbox(scratch: Path) -> None:
    """The step-7 fault, end to end: the image has no ruff; the commit's frozen v0.15.9 is
    fetched, sealed and mounted; a clean file passes, a misformatted one is rejected — the
    verdicts are ruff's, under the version the label names."""
    image = langs.ensure_shipped_sandbox_image("python")
    repo, _, gold = _repo(
        scratch,
        {".pre-commit-config.yaml": CLICK_PRECOMMIT, "src/click/core.py": "x = 1\n"},
        {"src/click/core.py": "x = 1\ny = 2\n"},
    )
    provider = SealedProvider(
        ProvisionConfig(
            enabled=True,
            env="dev",
            store=scratch / "deps",
            proxy_image=DEFAULT_PYTHON_IMAGE,
            fetch_timeout_s=300,
        )
    )
    deps = provider.resolve(
        repo, RepoConfig(name="click", language=Language.PYTHON), gold=gold, executor_name="docker"
    )
    assert deps.gold.lint_note == "" and [s.version for s in deps.gold.lint] == ["0.15.9"]
    sealed = provider.store.verify(deps.gold.lint[0].key)
    assert sealed.manifest["version"] == "0.15.9"
    executor = DockerExecutor(DockerSettings(image=image))
    runner = get_runner(RepoConfig(name="click", language=Language.PYTHON))
    tree = scratch / "tree"
    _git(repo.path, "worktree", "add", "-q", "--detach", str(tree), gold)
    try:
        plan = runner.lint_plan(tree, executor, deps=deps.gold)
        assert plan is not None and plan.detected == "ruff@0.15.9+ruff-format"
        run = lint_mod.run_plan(plan, executor, tree, ["src/click/core.py"])
        assert run.ok is True, run
        (tree / "src/click/core.py").write_text("x=1\ny =    2\n", encoding="utf-8")
        run = lint_mod.run_plan(plan, executor, tree, ["src/click/core.py"])
        assert run.ok is False and run.error == "", run
    finally:
        _git(repo.path, "worktree", "remove", "--force", str(tree))
