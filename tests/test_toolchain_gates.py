"""Every toolchain and docker skip goes through the one gate, and CI declares what it provides.

The fresh-clone job's first run (2026-09-28) failed 21 tests that should have skipped: its
``cargo`` was a rustup proxy with no toolchain for root, and the skip asked only whether
``cargo`` was on PATH; its docker CLI answered a formatted ``docker info`` with exit 0 and no
version while the daemon was stopped (P-744). The cure is one gate that asks whether the tool
WORKS — ``require_tool`` / ``require_docker`` in tests/conftest_langs.py, run for every
``@pytest.mark.toolchain`` and ``@pytest.mark.docker`` test by tests/conftest.py — and a job
that names the tools it provides in ``CRB_TEST_REQUIRE_TOOLS``, where a tool that does not
work fails instead of skipping (P-745). These ratchets keep both true.

Navigation
----------
What it is:   Ratchets over tests/ and .github/workflows/ci.yml for the toolchain gate.
What it does: Fails when a test skips on its own PATH or version lookup — ``shutil.which``,
              ``has_tool``, ``tool_usable``, ``java_home``, a docker probe or a version command
              run by ``subprocess``, inside a ``skipif`` or in an ``if`` that calls
              ``pytest.skip``, called there or one step away (a helper or name of the same
              module, a string condition, a local) — or reads a gate's reason directly
              (``docker_unavailable_reason``, ``tool_unusable_reason``) instead of calling
              ``require_tool`` / ``require_docker`` or wearing the marker; when a tool a test
              gates on is neither declared by the ``test-shard`` jobs nor named here as one CI
              does not provide; and when the fresh-clone shards declare anything but the
              ``test-shard`` jobs' tools less ``NOT_GIVEN_TO_ROOT``. Each check also runs on
              planted shapes so it cannot pass vacuously.
How:          ``ast`` over every ``tests/**/*.py`` except the gate's own module and its unit
              tests; PyYAML over ci.yml's ``env:`` blocks.
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   tests/conftest_langs.py (the gate), tests/conftest.py (the setup hook that runs it
              for each marker), .github/workflows/ci.yml (``test-shard`` and
              ``fresh-clone-shard``, which declare the tools they provide), docs/PREVENTION.md
              (P-744, P-745, P-747, P-748)
Tested by:    (this is a test file)
Touch when:   never for a new repository's own tests (they are not in this suite); a runner
              for a new language adds a tool — gate on it with ``@pytest.mark.toolchain``, give
              it a probe in tests/conftest_langs.py if ``--version`` does not prove it works,
              and add it to the ``CRB_TEST_REQUIRE_TOOLS`` of every CI job that provides it, or
              to ``NOT_PROVIDED_BY_CI`` here with the reason; a tool the fresh-clone shards
              cannot give root joins ``NOT_GIVEN_TO_ROOT`` with the reason.
"""

from __future__ import annotations

import ast
import warnings
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
#: Tools ``test-shard`` provides that the fresh-clone shards do not give root, and why. The
#: fresh-clone declaration is ``test-shard``'s less exactly these (P-748): its tests skip there
#: with the reason and run in ``test-shard``.
NOT_GIVEN_TO_ROOT = {
    "cargo": "the runner's rustup has no toolchain for root: `cargo --version` exits 1",
    "cargo-fmt": "the rustfmt component of that same rustup, which root does not have",
    "docker": "every fresh-clone part stops the daemon: product.evidence.205 runs with none",
}


def _name(node: ast.AST) -> str:
    """The called name: ``which`` for ``shutil.which(...)``, ``f`` for ``f(...)``."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


#: A version command run by hand in a skip condition is a lookup of its own too: a
#: ``subprocess`` call whose literal argv asks a tool for its version. Any other command
#: (``git show`` of a commit a shallow clone lacks) asks about data, not a tool.
SUBPROCESS = {"run", "call", "check_call", "check_output", "Popen"}
VERSION_ARGS = {"version", "--version", "-version", "-v", "-V"}


def _asks_version(call: ast.Call) -> bool:
    argv = call.args[0] if call.args else None
    return isinstance(argv, ast.List | ast.Tuple) and any(
        isinstance(a, ast.Constant) and a.value in VERSION_ARGS for a in argv.elts
    )


def _probe(call: ast.Call, helpers: set[str]) -> str:
    """The lookup ``call`` makes, or ``""``: a probe, a ``subprocess`` call, or a helper of
    the same module whose body makes one."""
    name = _name(call.func)
    if name in PROBES:
        return name
    if isinstance(call.func, ast.Name) and name in helpers:
        return name
    via = _name(getattr(call.func, "value", call.func))
    if name in SUBPROCESS and via == "subprocess" and _asks_version(call):
        return f"subprocess.{name}"
    return ""


def _lookups(node: ast.AST, helpers: set[str], tainted: set[str]) -> list[str]:
    """Every lookup in ``node``: a probe call, a read of a name assigned from one, and a probe
    written inside a string (``skipif("shutil.which('mvn') is None")``)."""
    out: list[str] = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and (probe := _probe(n, helpers)):
            out.append(f"{probe}()")
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in tainted:
            out.append(n.id)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            try:
                with warnings.catch_warnings():  # a regex in a string is not a condition
                    warnings.simplefilter("ignore", SyntaxWarning)
                    inner = ast.parse(n.value.strip(), mode="eval")
            except (SyntaxError, ValueError):
                continue
            out += _lookups(inner, helpers, tainted)
    return out


def _assigned(body: list[ast.stmt]) -> list[tuple[list[str], ast.AST]]:
    """(names, value) for each assignment in ``body``, nested blocks included."""
    out: list[tuple[list[str], ast.AST]] = []
    for stmt in body:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Assign):
                names = [t.id for t in n.targets if isinstance(t, ast.Name)]
                out.append((names, n.value))
            elif isinstance(n, ast.AnnAssign | ast.NamedExpr) and n.value is not None:
                if isinstance(n.target, ast.Name):
                    out.append(([n.target.id], n.value))
    return out


def _module_lookups(tree: ast.Module) -> tuple[set[str], set[str]]:
    """The module's helpers (functions whose body makes a lookup) and names assigned from a
    lookup, followed to a fixpoint: a helper of a helper, or one that reads such a name, is
    one too."""
    funcs = {s.name: s for s in tree.body if isinstance(s, ast.FunctionDef | ast.AsyncFunctionDef)}
    top = [s for s in tree.body if not isinstance(s, ast.FunctionDef | ast.AsyncFunctionDef)]
    helpers: set[str] = set()
    tainted: set[str] = set()
    while True:
        before = len(helpers) + len(tainted)
        helpers |= {n for n, f in funcs.items() if _lookups(f, helpers, tainted)}
        for names, value in _assigned(top):
            if _lookups(value, helpers, tainted):
                tainted |= set(names)
        if len(helpers) + len(tainted) == before:
            return helpers, tainted


def _local_taint(func: ast.AST, helpers: set[str], tainted: set[str]) -> set[str]:
    """Names a function assigns from a lookup (``node = shutil.which("node")``)."""
    local = set(tainted)
    body = getattr(func, "body", [])
    while True:
        before = len(local)
        for names, value in _assigned(body):
            if _lookups(value, helpers, local):
                local |= set(names)
        if len(local) == before:
            return local


def _calls_skip(body: list[ast.stmt]) -> bool:
    return any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "skip"
        and _name(n.func.value) == "pytest"
        for stmt in body
        for n in ast.walk(stmt)
    )


def _enclosing(tree: ast.Module) -> dict[ast.AST, ast.AST]:
    """Each node → the function it is in, or the module."""
    out: dict[ast.AST, ast.AST] = {}

    def visit(node: ast.AST, scope: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            out[child] = scope
            inner = child if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else scope
            visit(child, inner)

    visit(tree, tree)
    return out


def gate_findings(source: str, where: str) -> list[str]:
    """Every place ``source`` skips on a lookup of its own instead of the one gate: a probe in
    a ``skipif`` or in the test of an ``if`` that skips — called directly, through a helper of
    the same module, through a name assigned from one, inside a string condition, or as a
    version command run by ``subprocess`` (P-744, P-747)."""
    tree = ast.parse(source)
    helpers, tainted = _module_lookups(tree)
    scope_of = _enclosing(tree)
    taint: dict[ast.AST, set[str]] = {tree: tainted}

    def names_in(node: ast.AST) -> set[str]:
        scope = scope_of.get(node, tree)
        if scope not in taint:
            taint[scope] = _local_taint(scope, helpers, tainted)
        return taint[scope]

    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _name(node.func) == "skipif":
            for probe in _lookups(ast.Tuple(elts=node.args), helpers, names_in(node)):
                out.append(
                    f"{where}:{node.lineno}: a skipif on {probe} — use "
                    "@pytest.mark.toolchain(...) / @pytest.mark.docker"
                )
        elif isinstance(node, ast.If) and _calls_skip(node.body):
            for probe in _lookups(node.test, helpers, names_in(node)):
                out.append(
                    f"{where}:{node.lineno}: skips on {probe} — call langs.require_tool(...) "
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
        # one step removed from the skip (P-747): a module-level name or helper that looks
        # the tool up, a condition written as a string, a local the test body checks, and a
        # version command run by hand
        'HAVE_GO = shutil.which("go")\n@pytest.mark.skipif(not HAVE_GO, reason="x")\n'
        "def test_a(): ...\n",
        'GO = shutil.which("go")\n@pytest.mark.skipif(GO is None, reason="x")\ndef test_a(): ...\n',
        'def _no_cargo():\n    return shutil.which("cargo") is None\n'
        '@pytest.mark.skipif(_no_cargo(), reason="x")\ndef test_a(): ...\n',
        'def _go_ok():\n    return shutil.which("go") is not None\n'
        '@pytest.mark.skipif(not _go_ok(), reason="x")\ndef test_a(): ...\n',
        "def _path(): return shutil.which('ruff')\ndef _ruff(): return _path()\n"
        '@pytest.mark.skipif(_ruff() is None, reason="x")\ndef test_a(): ...\n',
        '@pytest.mark.skipif("shutil.which(\'mvn\') is None", reason="x")\ndef test_a(): ...\n',
        'def f():\n    node = shutil.which("node")\n    if node is None:\n'
        '        pytest.skip("no node")\n',
        'def f():\n    if subprocess.run(["helm", "version"]).returncode:\n'
        '        pytest.skip("no helm")\n',
        'def f():\n    r = subprocess.run(["helm", "version"])\n    if r.returncode != 0:\n'
        '        pytest.skip("no helm")\n',
        '@pytest.mark.skipif(subprocess.call(["jq", "--version"]) != 0, reason="x")\n'
        "def test_a(): ...\n",
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
        # a lookup that feeds no skip, and a skip on something that is not a tool
        'def _bin():\n    return shutil.which("ruff") or "ruff"\n'
        'def g():\n    r = subprocess.run([_bin(), "check"])\n    assert r.returncode == 0\n'
        '@pytest.mark.skipif(sys.platform == "win32", reason="posix only")\ndef test_b(): ...\n'
        'def h():\n    if not os.environ.get("CRB_TEST_POSTGRES_URL"):\n'
        '        pytest.skip("no postgres")\n'
        'def k():\n    shown = subprocess.run(["git", "show", "abc:ci.yml"])\n'
        '    if shown.returncode != 0:\n        pytest.skip("a shallow clone")\n'
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


def _declared(job: str, ci_text: str | None = None) -> set[str]:
    text = CI.read_text(encoding="utf-8") if ci_text is None else ci_text
    env = (yaml.safe_load(text)["jobs"][job].get("env") or {}).get(ENV)
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


def fresh_declaration_findings(ci_text: str) -> list[str]:
    """How the fresh-clone shards' declaration differs from what root is given there: exactly
    ``test-shard``'s tools less ``NOT_GIVEN_TO_ROOT``. A subset alone let the declaration
    shrink to ``go`` and bring back the silent JVM skip as root that P-745 stops."""
    fresh = _declared("fresh-clone-shard", ci_text)
    want = _declared("test-shard", ci_text) - set(NOT_GIVEN_TO_ROOT)
    out = [f"the fresh-clone shards leave out {t!r}, which root is given" for t in want - fresh]
    out += [f"the fresh-clone shards declare {t!r}, which root is not given" for t in fresh - want]
    return sorted(out)


def test_the_fresh_clone_shards_declare_exactly_what_root_is_given() -> None:
    """The fresh-clone shards stop the daemon, and root has no rustup toolchain there: they
    declare every tool ``test-shard`` provides but those, so the tests behind what they leave
    out skip with the reason and run in ``test-shard`` — and nothing else skips."""
    assert fresh_declaration_findings(CI.read_text(encoding="utf-8")) == []
    assert set(NOT_GIVEN_TO_ROOT) <= _declared("test-shard")
    assert {"go", "node", "mvn", "jdk"} <= _declared("fresh-clone-shard")


@pytest.mark.parametrize(
    ("what", "old", "new"),
    [
        ("jdk dropped", " mvn jdk helm", " mvn helm"),
        ("mvn dropped", " npm mvn jdk", " npm jdk"),
        ("cut to go", '"go gofmt node npm mvn jdk helm uv jq bash"', '"go"'),
        (
            "docker claimed",
            '"go gofmt node npm mvn jdk helm uv jq bash"',
            '"go gofmt node npm mvn jdk helm uv jq bash docker"',
        ),
    ],
)
def test_the_fresh_clone_declaration_check_refuses_a_changed_declaration(
    what: str, old: str, new: str
) -> None:
    text = CI.read_text(encoding="utf-8")
    fresh_env = 'CRB_TEST_REQUIRE_TOOLS: "go gofmt node npm mvn jdk helm uv jq bash"'
    assert text.count(fresh_env) == 1, "the fresh-clone shards' declaration moved"
    planted = text.replace(fresh_env, fresh_env.replace(old, new), 1)
    assert planted != text, what
    assert fresh_declaration_findings(planted) != [], what
