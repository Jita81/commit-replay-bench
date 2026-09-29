"""Every package a test imports is one CI installs from ``uv.lock``, or the import is guarded.

A Wave 2 test did a bare ``import openai`` to raise a provider's refusal. The shared developer
environment carried the SDK, so every local run passed; CI installs only the ``server``,
``postgres``, ``mcp`` and ``dev`` extras from the lock, none of which reaches ``openai``, so the
test failed on a fresh clone with ``ModuleNotFoundError`` — and it was the typed evidence of a
met criterion (docs/PREVENTION.md P-330). This gate reads what CI resolves, not what the
developer's environment happens to hold.

Navigation
----------
What it is:   The gate between the suite's imports and the packages CI installs.
What it does: Resolves, from ``uv.lock``, every distribution the extras of the jobs that run
              the whole suite (``test-shard`` and ``fresh-clone-shard`` in
              ``.github/workflows/ci.yml``) reach, and fails when a module under ``tests/``
              imports a third-party package outside that set without a guard
              (``pytest.importorskip`` of it, or a ``try`` whose handler catches
              ``ImportError``). The check runs on a planted bare import so it cannot pass
              vacuously.
How:          ``tomllib`` reads the lock and walks each package's dependencies and the extras
              named on each edge; PyYAML reads the jobs' ``uv sync`` lines; ``ast`` finds every
              import in every test module; ``importlib.metadata.packages_distributions`` maps
              an import name to its distribution.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   uv.lock (the resolved set it reads), pyproject.toml (the extras),
              .github/workflows/ci.yml (the jobs' installs), tests/test_ci_lock.py (holds CI
              to installing from the lock), docs/PREVENTION.md (P-330)
Tested by:    (this is a test file)
Touch when:   never for a new repository; a job that runs the whole suite installs other
              extras; a test needs a package only an optional extra carries (guard it with
              ``pytest.importorskip``, and cite no met criterion's evidence on it).
"""

from __future__ import annotations

import ast
import importlib.metadata as md
import re
import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
#: The jobs that run the whole suite; the extras every one of them installs are what a test
#: may import unguarded.
SUITE_JOBS = ("test-shard", "fresh-clone-shard")
PROJECT = "commit-replay-bench"


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def ci_extras() -> set[str]:
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))["jobs"]
    sets = []
    for name in SUITE_JOBS:
        runs = " ".join(str(st.get("run", "")) for st in jobs[name].get("steps", []))
        installs = re.findall(r"uv sync[^\n]*--locked[^\n]*", runs)
        assert installs, f"{name} installs nothing from the lock"
        sets.append({x for line in installs for x in re.findall(r"--extra\s+(\S+)", line)})
    return set.intersection(*sets)


def resolved(extras: set[str]) -> set[str]:
    """Every distribution the project with ``extras`` reaches in ``uv.lock`` (markers are
    ignored, so the set is, if anything, too large — never too small)."""
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    by_name = {_norm(p["name"]): p for p in lock["package"]}
    seen: set[str] = set()
    todo: list[tuple[str, frozenset[str]]] = [(PROJECT, frozenset(extras))]
    visited: set[tuple[str, frozenset[str]]] = set()
    while todo:
        name, want = todo.pop()
        if (name, want) in visited:
            continue
        visited.add((name, want))
        seen.add(name)
        pkg = by_name[name]
        edges = list(pkg.get("dependencies", []))
        for extra in want:
            edges += pkg.get("optional-dependencies", {}).get(extra, [])
        for e in edges:
            dep = _norm(e["name"])
            if dep == PROJECT:
                continue
            todo.append((dep, frozenset(e.get("extra", []))))
    return seen


def _local_names() -> set[str]:
    names = {"crb", "tests", "conftest", "fixtures"}
    for p in TESTS.rglob("*.py"):
        names.add(p.stem)
    for p in TESTS.rglob("__init__.py"):
        names.add(p.parent.name)
    return names


def _guarded(tree: ast.AST) -> set[int]:
    """Line numbers of imports inside a ``try`` whose handler catches ``ImportError``."""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        caught = " ".join(ast.unparse(h.type) for h in node.handlers if h.type is not None)
        if "ImportError" in caught or "ModuleNotFoundError" in caught:
            for inner in node.body:
                for sub in ast.walk(inner):
                    if isinstance(sub, ast.Import | ast.ImportFrom):
                        lines.add(sub.lineno)
    return lines


def unguarded_imports(source: str) -> list[tuple[int, str]]:
    """``(line, top-level module)`` of every import ``source`` makes that no guard covers."""
    tree = ast.parse(source)
    skipped = set(re.findall(r"importorskip\(\s*[\"']([\w.]+)[\"']", source))
    skipped = {s.split(".")[0] for s in skipped}
    guarded = _guarded(tree)
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods = [node.module]
        else:
            continue
        for m in mods:
            top = m.split(".")[0]
            if node.lineno not in guarded and top not in skipped:
                out.append((node.lineno, top))
    return out


def findings(sources: dict[str, str], allowed: set[str]) -> list[str]:
    dists = md.packages_distributions()
    local = _local_names()
    bad: list[str] = []
    for rel, src in sources.items():
        for line, top in unguarded_imports(src):
            if top in sys.stdlib_module_names or top in local or top == "__future__":
                continue
            owners = {_norm(d) for d in dists.get(top, [])}
            if not owners & allowed:
                bad.append(f"{rel}:{line} imports {top!r}, which CI's extras do not install")
    return bad


def test_every_test_import_is_installed_by_the_jobs_that_run_the_suite() -> None:
    allowed = resolved(ci_extras())
    sources = {
        str(p.relative_to(ROOT)): p.read_text(encoding="utf-8") for p in sorted(TESTS.rglob("*.py"))
    }
    assert not findings(sources, allowed), findings(sources, allowed)


def test_the_check_refuses_a_planted_bare_import_of_an_optional_extra() -> None:
    allowed = resolved(ci_extras())
    assert "openai" not in allowed and "pytest" in allowed and "sqlalchemy" in allowed
    planted = "def f():\n    import openai\n    return openai\n"
    assert findings({"tests/test_planted.py": planted}, allowed)
    guarded = "import pytest\nopenai = pytest.importorskip('openai')\n"
    assert not findings({"tests/test_planted.py": guarded}, allowed)
    tried = "try:\n    import openai\nexcept ImportError:\n    openai = None\n"
    assert not findings({"tests/test_planted.py": tried}, allowed)
    assert unguarded_imports(planted) == [(2, "openai")]
