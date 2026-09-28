"""Every toolchain and docker skip goes through the one gate, and CI declares what it provides.

The fresh-clone job's first run (2026-09-28) failed 21 tests that should have skipped: its
``cargo`` was a rustup proxy with no toolchain for root, and the skip asked only whether
``cargo`` was on PATH; its docker CLI answered a formatted ``docker info`` with exit 0 and no
version while the daemon was stopped (P-741). The cure is one gate that asks whether the tool
WORKS — ``require_tool`` / ``require_docker`` in tests/conftest_langs.py, run for every
``@pytest.mark.toolchain`` and ``@pytest.mark.docker`` test by tests/conftest.py — and a job
that names the tools it provides in ``CRB_TEST_REQUIRE_TOOLS``, where a tool that does not
work fails instead of skipping (P-742). These ratchets keep both true.

Navigation
----------
What it is:   Ratchets over tests/ and .github/workflows/ci.yml for the toolchain gate.
What it does: Fails when a test skips on its own PATH or version lookup — ``shutil.which``,
              ``has_tool``, ``tool_usable``, ``java_home`` or a docker probe inside a
              ``skipif`` or in an ``if`` that calls ``pytest.skip`` — or reads a gate's reason
              directly (``docker_unavailable_reason``, ``tool_unusable_reason``) instead of
              calling ``require_tool`` / ``require_docker`` or wearing the marker; when a tool a
              test gates on is neither declared by the ``test-shard`` jobs nor named here as one
              CI does not provide; and when a fresh-clone shard declares a tool the ``test-shard``
              jobs do not, or docker, whose daemon it stops. Each check also runs on planted
              shapes so it cannot pass vacuously.
How:          ``ast`` over every ``tests/**/*.py`` except the gate's own module and its unit
              tests; PyYAML over ci.yml's ``env:`` blocks.
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   tests/conftest_langs.py (the gate), tests/conftest.py (the setup hook that runs it
              for each marker), .github/workflows/ci.yml (``test-shard`` and
              ``fresh-clone-shard``, which declare the tools they provide), docs/PREVENTION.md
              (P-741, P-742)
Tested by:    (this is a test file)
Touch when:   never for a new repository's own tests (they are not in this suite); a runner
              for a new language adds a tool — gate on it with ``@pytest.mark.toolchain``, give
              it a probe in tests/conftest_langs.py if ``--version`` does not prove it works,
              and add it to the ``CRB_TEST_REQUIRE_TOOLS`` of every CI job that provides it, or
              to ``NOT_PROVIDED_BY_CI`` here with the reason.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
CI = ROOT / ".github" / "workflows" / "ci.yml"
ENV = "CRB_TEST_REQUIRE_TOOLS"

#: The gate itself, its unit tests, and this file: the only places the probes are called.
EXEMPT = {"conftest_langs.py", "test_conftest_langs.py", "test_toolchain_gates.py"}
#: A call to one of these in a skip condition is a lookup of its own, not the gate.
PROBES = {
    "which",
    "has_tool",
    "tool_usable",
    "tool_unusable_reason",
    "docker_available",
    "docker_unavailable_reason",
    "java_home",
}
#: The gate's reasons: read directly, they become ``if reason: pytest.skip(reason)``, which a
#: job's declaration can never turn into a failure.
REASONS = {"has_tool", "docker_available", "docker_unavailable_reason", "tool_unusable_reason"}
#: Tools a test may gate on that no CI job provides, and why. Each is a skip wherever it runs.
NOT_PROVIDED_BY_CI = {
    "tsc": "TypeScript is not installed globally on the hosted runner; the UI's own tsc runs "
    "in ui-unit, from ui/node_modules",
    "claude": "the Claude Code CLI is a live-model builder; its test runs only with a key",
}


def _name(node: ast.AST) -> str:
    """The called name: ``which`` for ``shutil.which(...)``, ``f`` for ``f(...)``."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _probe_calls(node: ast.AST) -> list[str]:
    return [
        _name(n.func) for n in ast.walk(node) if isinstance(n, ast.Call) and _name(n.func) in PROBES
    ]


def _calls_skip(body: list[ast.stmt]) -> bool:
    return any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "skip"
        and _name(n.func.value) == "pytest"
        for stmt in body
        for n in ast.walk(stmt)
    )


def gate_findings(source: str, where: str) -> list[str]:
    """Every place ``source`` skips on a lookup of its own instead of the one gate."""
    tree = ast.parse(source)
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _name(node.func) == "skipif":
            for probe in _probe_calls(node):
                out.append(
                    f"{where}:{node.lineno}: a skipif on {probe}() — use "
                    "@pytest.mark.toolchain(...) / @pytest.mark.docker"
                )
        elif isinstance(node, ast.If) and _calls_skip(node.body):
            for probe in _probe_calls(node.test):
                out.append(
                    f"{where}:{node.lineno}: skips on {probe}() — call langs.require_tool(...) "
                    "/ langs.require_docker()"
                )
        elif isinstance(node, ast.Name | ast.Attribute) and _name(node) in REASONS:
            out.append(
                f"{where}:{node.lineno}: reads {_name(node)} — the gate's reason is for "
                "require_tool / require_docker, which fail where the job declares the tool"
            )
    return out


def _test_sources() -> list[Path]:
    return sorted(
        p for p in TESTS.rglob("*.py") if p.name not in EXEMPT and ".cache" not in p.parts
    )


def test_no_test_skips_on_a_lookup_of_its_own() -> None:
    found = [
        f
        for p in _test_sources()
        for f in gate_findings(p.read_text(encoding="utf-8"), str(p.relative_to(ROOT)))
    ]
    assert found == []
    assert len(_test_sources()) > 100  # the scan saw the suite


@pytest.mark.parametrize(
    "planted",
    [
        '@pytest.mark.skipif(shutil.which("cargo") is None, reason="x")\ndef test_a(): ...\n',
        '@pytest.mark.skipif(not langs.has_tool("go"), reason="x")\ndef test_a(): ...\n',
        'pytestmark = [pytest.mark.skipif(not jvmrepo.java_home(), reason="no JDK")]\n',
        'def f():\n    if not shutil.which("docker"):\n        pytest.skip("no docker")\n',
        'def f():\n    if langs.tool_usable("go") is False:\n        pytest.skip("no")\n',
        "def f():\n    reason = langs.docker_unavailable_reason()\n    if reason:\n"
        "        pytest.skip(reason)\n",
        'def f():\n    return langs.has_tool("node")\n',
    ],
)
def test_the_scan_finds_each_shape_the_gate_replaced(planted: str) -> None:
    assert gate_findings(planted, "planted") != [], planted


def test_the_scan_leaves_the_gate_and_a_branch_alone() -> None:
    """Resolving a binary's path, branching on whether a tool works, and the gate itself are
    not skips of their own."""
    fine = (
        'RUFF = shutil.which("ruff") or "ruff"\n'
        '@pytest.mark.toolchain("cargo", "cargo-fmt")\ndef test_a(): ...\n'
        'def f():\n    langs.require_tool("go")\n    langs.require_docker()\n'
        '    if langs.tool_usable("cargo-fmt"):\n        assert True\n'
    )
    assert gate_findings(fine, "fine") == []


# --- what CI declares it provides -------------------------------------------------------------


def _gated_tools() -> dict[str, str]:
    """Every tool a test gates on (a ``toolchain`` marker or a ``require_tool`` call) → where."""
    out: dict[str, str] = {}
    for p in [*_test_sources(), TESTS / "conftest_langs.py"]:
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and _name(node.func) in ("toolchain", "require_tool"):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        out.setdefault(arg.value, f"{p.relative_to(ROOT)}:{node.lineno}")
    return out


def _declared(job: str) -> set[str]:
    env = (yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"][job].get("env") or {}).get(ENV)
    return set(str(env or "").replace(",", " ").split())


def test_every_tool_a_test_gates_on_is_provided_by_ci_or_named_as_not_provided() -> None:
    """A tool no CI job declares is a skip on every run — the tests behind it never run where
    anyone looks. A new one must join the ``test-shard`` jobs' declaration, or this list with
    the reason."""
    gated = _gated_tools()
    shard = _declared("test-shard")
    missing = {t: at for t, at in gated.items() if t not in shard and t not in NOT_PROVIDED_BY_CI}
    assert missing == {}
    assert {"go", "node", "mvn", "cargo", "docker"} <= shard
    assert not set(NOT_PROVIDED_BY_CI) & shard, "a tool cannot be both provided and not"


def test_the_fresh_clone_shards_declare_only_what_root_is_given() -> None:
    """The fresh-clone shards stop the daemon, and root has no rustup toolchain there: they
    declare a subset of what ``test-shard`` provides, never docker, so the tests behind what
    they leave out skip with the reason and run in ``test-shard``."""
    fresh = _declared("fresh-clone-shard")
    assert fresh and fresh <= _declared("test-shard")
    assert "docker" not in fresh
