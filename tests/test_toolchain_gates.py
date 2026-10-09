"""Every toolchain and docker skip goes through the one gate, and CI declares what it provides.

The fresh-clone job's first run (2026-09-28) failed 21 tests that should have skipped: its
``cargo`` was a rustup proxy with no toolchain for root, and the skip asked only whether
``cargo`` was on PATH; its docker CLI answered a formatted ``docker info`` with exit 0 and no
version while the daemon was stopped (P-744). The cure is one gate that asks whether the tool
WORKS — ``require_tool`` / ``require_docker`` in tests/conftest_langs.py, run for every
``@pytest.mark.toolchain`` and ``@pytest.mark.docker`` test by tests/conftest.py — and a job
that names the tools it provides in ``CRB_TEST_REQUIRE_TOOLS``, where a tool that does not
work fails instead of skipping (P-745). These ratchets keep both true, and the same for the
history: the suite jobs hold all of it, so a test that cannot read a commit fails, naming the
fetch, instead of skipping the proof it was written to make (P-753).

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
              ``test-shard`` jobs' tools less ``NOT_GIVEN_TO_ROOT``; and when a Python package
              a test skips on (``pytest.importorskip``) is not installed by the suite jobs'
              ``uv sync`` extras nor named here as one CI does not install (P-707); and when a
              test skips on what a ``git`` command said, or a suite job holds less than the
              whole history (P-753). Each check also runs on planted shapes so it cannot pass
              vacuously.
How:          ``ast`` over every ``tests/**/*.py`` except the gate's own module and its unit
              tests; PyYAML over ci.yml's ``env:`` blocks.
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   tests/conftest_langs.py (the gate), tests/conftest.py (the setup hook that runs it
              for each marker), .github/workflows/ci.yml (``test-shard`` and
              ``fresh-clone-shard``, which declare the tools they provide, whose ``uv sync``
              extras install the packages and whose checkouts hold the whole history),
              pyproject.toml (the extras' packages), docs/PREVENTION.md (P-707, P-744, P-745,
              P-747, P-748, P-753)
Tested by:    (this is a test file)
Touch when:   never for a new repository's own tests (they are not in this suite); a runner
              for a new language adds a tool — gate on it with ``@pytest.mark.toolchain``, give
              it a probe in tests/conftest_langs.py if ``--version`` does not prove it works,
              and add it to the ``CRB_TEST_REQUIRE_TOOLS`` of every CI job that provides it, or
              to ``NOT_PROVIDED_BY_CI`` here with the reason; a tool the fresh-clone shards
              cannot give root joins ``NOT_GIVEN_TO_ROOT`` with the reason; a test that skips on
              a package (``pytest.importorskip``) needs that package in the extras the suite
              jobs install, or an entry in ``NOT_INSTALLED_BY_CI`` with the reason; a test
              that needs a commit fails, naming the fetch, when the clone lacks it.
"""

from __future__ import annotations

import ast
import re
import tomllib
import warnings
from collections.abc import Collection
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
    "gitleaks": "the security job installs the pinned scanner and runs it over the history; "
    "the shards do not download it, so the planted-credential test runs where it is installed",
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
#: (``git show`` of a commit a shallow clone lacks) asks about data, not a tool — and a skip
#: on that is refused by ``history_skip_findings`` below (P-753).
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


def _dotted(node: ast.AST) -> str:
    """``self.head`` for an attribute chain on a name, or ``""``."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    return ".".join([node.id, *reversed(parts)]) if isinstance(node, ast.Name) and parts else ""


def _targets(node: ast.AST | None) -> list[str]:
    """The names a target binds: ``a``, each of ``a, (b, *c)``, and ``self.head``."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Tuple | ast.List):
        return [name for e in node.elts for name in _targets(e)]
    if isinstance(node, ast.Starred):
        return _targets(node.value)
    path = _dotted(node) if isinstance(node, ast.Attribute) else ""
    return [path] if path else []


def _assigned(body: list[ast.stmt]) -> list[tuple[list[str], ast.AST]]:
    """(names, value) for each binding in ``body``, nested blocks included: an assignment to
    any target (a tuple unpacked, an attribute), a ``with … as`` and a ``for`` target."""
    out: list[tuple[list[str], ast.AST]] = []
    for stmt in body:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Assign):
                out.append(([name for t in n.targets for name in _targets(t)], n.value))
            elif isinstance(n, ast.AnnAssign | ast.AugAssign | ast.NamedExpr):
                if n.value is not None:
                    out.append((_targets(n.target), n.value))
            elif isinstance(n, ast.withitem) and n.optional_vars is not None:
                out.append((_targets(n.optional_vars), n.context_expr))
            elif isinstance(n, ast.For | ast.AsyncFor | ast.comprehension):
                out.append((_targets(n.target), n.iter))
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


#: The skips, however spelled: ``pytest.skip`` and ``pytest.xfail`` (or imported bare, or
#: under an alias), ``raise unittest.SkipTest`` or ``pytest.skip.Exception``, and a skip or
#: xfail mark applied at run time (``request.applymarker(pytest.mark.skip(…))``).
SKIPS = {"skip", "xfail"}
PYTEST: tuple[frozenset[str], frozenset[str]] = (frozenset({"pytest"}), frozenset())


def _pytest_names(tree: ast.Module) -> tuple[frozenset[str], frozenset[str]]:
    """The names a module binds to pytest, and to its ``skip`` and ``xfail``."""
    mods, funcs = {"pytest"}, set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.asname or a.name for a in n.names if a.name == "pytest"}
        elif isinstance(n, ast.ImportFrom) and n.module == "pytest":
            funcs |= {a.asname or a.name for a in n.names if a.name in SKIPS}
    return frozenset(mods), frozenset(funcs)


def _skips(
    node: ast.AST, names: tuple[frozenset[str], frozenset[str]] = PYTEST, via: Collection[str] = ()
) -> bool:
    """Whether ``node`` skips: in any spelling above, or by calling ``via``, a function of the
    module whose body does."""
    mods, funcs = names
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and (
            (
                isinstance(n.func, ast.Attribute)
                and n.func.attr in SKIPS
                and _name(n.func.value) in mods
            )
            or (isinstance(n.func, ast.Name) and (n.func.id in funcs or n.func.id in via))
        ):
            return True
        if isinstance(n, ast.Raise) and n.exc is not None:
            exc = n.exc.func if isinstance(n.exc, ast.Call) else n.exc
            if _name(exc) == "SkipTest" or (
                _name(exc) == "Exception" and _name(getattr(exc, "value", exc)) in SKIPS
            ):
                return True
        if isinstance(n, ast.Attribute) and n.attr in SKIPS and _name(n.value) == "mark":
            return True
    return False


def _calls_skip(
    body: list[ast.stmt],
    names: tuple[frozenset[str], frozenset[str]] = PYTEST,
    via: Collection[str] = (),
) -> bool:
    return any(_skips(stmt, names, via) for stmt in body)


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
        # a lookup that feeds no skip, and a skip on something that is not a tool (the last,
        # a skip on a commit, is the history scan's to refuse: P-753)
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


#: Packages a test skips on (``pytest.importorskip``) that no suite job installs, and why.
#: Empty on purpose: a package a test needs is one the suite jobs install (P-707).
NOT_INSTALLED_BY_CI: dict[str, str] = {}
#: An import name whose distribution is called something else in pyproject.toml.
DIST_OF = {"claude_agent_sdk": "claude-agent-sdk", "importlinter": "import-linter"}
#: The jobs that run the hermetic suite; every package a test skips on is installed by both.
SUITE_JOBS = ("test-shard", "fresh-clone-shard")


def _importorskips_in(text: str, where: str) -> dict[str, str]:
    """Every package ``text`` skips on (``pytest.importorskip("x")``, by top-level name) → where."""
    out: dict[str, str] = {}
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Call) and _name(node.func) == "importorskip" and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                out.setdefault(arg.value.split(".")[0], f"{where}:{node.lineno}")
    return out


def _importorskips() -> dict[str, str]:
    out: dict[str, str] = {}
    for p in _test_sources():
        for pkg, at in _importorskips_in(
            p.read_text(encoding="utf-8"), str(p.relative_to(ROOT))
        ).items():
            out.setdefault(pkg, at)
    return out


def _dist(requirement: str) -> str:
    """The distribution name a requirement string names, normalised as pyproject spells it."""
    return re.split(r"[\[><=!~;@ ]", requirement.strip(), maxsplit=1)[0].lower().replace("_", "-")


def _installed_by(job: str, ci_text: str | None = None) -> set[str]:
    """The distributions ``job``'s ``uv sync`` installs: the project's dependencies and each
    ``--extra`` it names, read from pyproject.toml (a self-reference such as
    ``commit-replay-bench[openai]`` brings that extra's packages in)."""
    text = CI.read_text(encoding="utf-8") if ci_text is None else ci_text
    runs = "\n".join(
        str(step.get("run") or "") for step in yaml.safe_load(text)["jobs"][job]["steps"]
    )
    sync = re.search(r"uv sync[^\n]*", runs)
    assert sync, f"{job} has no `uv sync` step"
    extras = list(re.findall(r"--extra (\S+)", sync.group(0)))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    optional = project.get("optional-dependencies", {})
    reqs = list(project.get("dependencies", []))
    seen: set[str] = set()
    while extras:
        extra = extras.pop()
        if extra in seen:
            continue
        seen.add(extra)
        reqs += optional.get(extra, [])
    names: set[str] = set()
    for req in reqs:
        if _dist(req) == _dist(project["name"]):
            inner = re.search(r"\[([^\]]*)\]", req)
            for extra in inner.group(1).split(",") if inner else []:
                if extra.strip() not in seen:
                    seen.add(extra.strip())
                    reqs += optional.get(extra.strip(), [])
            continue
        names.add(_dist(req))
    return names


def importorskip_findings(skips: dict[str, str], ci_text: str | None = None) -> list[str]:
    """Every package a test skips on that a suite job does not install and this file does not
    name as not installed: a skip on every run there, so its tests never run where anyone
    looks (P-707)."""
    out: list[str] = []
    for job in SUITE_JOBS:
        installed = _installed_by(job, ci_text)
        for pkg, at in sorted(skips.items()):
            if (
                pkg not in NOT_INSTALLED_BY_CI
                and DIST_OF.get(pkg, pkg).replace("_", "-") not in installed
            ):
                out.append(f"{job} does not install {pkg!r}, which {at} skips on")
    return out


def test_every_package_a_test_skips_on_is_installed_by_the_suite_jobs() -> None:
    """``pytest.importorskip`` is a skip on every run where the package is missing. The
    endpoint suite — the evidence for product.truth.26 and .27 — skipped in every CI run
    because ``openai`` is its own extra and no suite job installed it (P-707); a package a
    test skips on is installed by both suite jobs, or named in ``NOT_INSTALLED_BY_CI``."""
    skips = _importorskips()
    assert "openai" in skips, "the endpoint suite's importorskip is the case this guards"
    assert importorskip_findings(skips) == []
    assert not set(NOT_INSTALLED_BY_CI) & _installed_by("test-shard"), "cannot be both"


def test_a_package_the_suite_jobs_stop_installing_is_caught() -> None:
    """The check is not vacuous: the real ci.yml with ``--extra openai`` removed from the
    suite jobs' installs is refused, naming the job, the package and the test that skips."""
    text = CI.read_text(encoding="utf-8")
    assert text.count("--extra openai ") >= 2
    findings = importorskip_findings(_importorskips(), text.replace("--extra openai ", ""))
    assert findings and all("'openai'" in f for f in findings), findings
    assert {f.split(" ")[0] for f in findings} == set(SUITE_JOBS)
    planted = _importorskips_in('import pytest\npytest.importorskip("mystery.sub")\n', "planted.py")
    assert planted == {"mystery": "planted.py:2"}


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


# --- the history CI provides ------------------------------------------------------------------


#: What runs ``git``: an argv whose first item is the git executable (``"git"``,
#: ``"/usr/bin/git"``, or a name holding it: ``GIT``, ``git_exe``); a command string given to a
#: runner (``subprocess.run("git show …", shell=True)``, ``os.system``); and a call through
#: anything named for git (``Git(root).show_file(…)``, ``git_repo.commit()``). A ``GitHub`` or
#: ``GitLab`` client is not git, nor is ``digit``, nor a type (``tuple[GitRepo, str]``).
_GIT_EXE = re.compile(r"^(?:\S*/)?git(?:\s|$)")
_GIT_NAME = re.compile(r"(?:^|_)(?:git|GIT)(?:_|$)")
_GITISH = re.compile(rf"{_GIT_NAME.pattern}|(?:^|_|[a-z])Git(?!Hub|Lab)(?:[A-Z_]|$)")
RUNNERS = SUBPROCESS | {"system", "popen", "getoutput", "getstatusoutput"}


def _chain(node: ast.AST) -> list[str]:
    """Every name along an attribute chain, outermost first: ``["show", "repo", "self"]``."""
    out: list[str] = []
    while isinstance(node, ast.Attribute):
        out.append(node.attr)
        node = node.value
    return [*out, node.id] if isinstance(node, ast.Name) else out


def _says_git(node: ast.AST) -> bool:
    """A string that starts a ``git`` command, or a name that holds the executable."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return bool(_GIT_EXE.match(node.value))
    if isinstance(node, ast.JoinedStr) and node.values:
        return _says_git(node.values[0])
    return any(_GIT_NAME.search(name) for name in _chain(node))


def _git_argv(node: ast.AST) -> bool:
    """A ``git`` command: an argv whose first item says git, or a runner given a command string
    that starts with ``git``."""
    if isinstance(node, ast.List | ast.Tuple):
        return bool(node.elts) and _says_git(node.elts[0])
    return (
        isinstance(node, ast.Call)
        and _name(node.func) in RUNNERS
        and bool(node.args)
        and isinstance(node.args[0], ast.Constant | ast.JoinedStr)
        and _says_git(node.args[0])
    )


def _loaded(node: ast.AST) -> str:
    """The name or attribute path ``node`` reads (``out``, ``self.out``), or ``""``."""
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
        return _dotted(node)
    return ""


def _reads_git(node: ast.AST, helpers: Collection[str], tainted: Collection[str]) -> bool:
    """Whether ``node`` runs ``git``, calls something named for it or a function of the module
    that does (``f()``, ``self.f()``), or reads a name assigned from any of them (``out``,
    ``self.out``)."""
    for n in ast.walk(node):
        if _git_argv(n):
            return True
        if isinstance(n, ast.Call):
            chain = _chain(n.func)
            if any(_GITISH.search(name) for name in chain):
                return True
            if chain and chain[0] in helpers and chain[1:] in ([], ["self"], ["cls"]):
                return True
        elif _loaded(n) in tainted:
            return True
    return False


def _git_taint(body: list[ast.stmt], helpers: Collection[str], tainted: set[str]) -> set[str]:
    """``tainted`` and every name ``body`` assigns from what ``git`` said, to a fixpoint."""
    names = set(tainted)
    while True:
        before = len(names)
        for assigned, value in _assigned(body):
            if _reads_git(value, helpers, names):
                names |= set(assigned)
        if len(names) == before:
            return names


#: Every dotted name a module or package under ``tests/`` can be imported by: pytest puts
#: ``tests/`` on the path (``test_worker``, ``fixtures.langs``), and a test may put a folder
#: under it there too (``builders_repo`` from ``tests/fixtures``), so each slice of the path.
_TEST_MODULES = frozenset(
    ".".join(parts[i:j])
    for p in TESTS.rglob("*.py")
    if ".cache" not in p.parts
    for parts in [p.relative_to(TESTS).with_suffix("").parts]
    for i in range(len(parts))
    for j in range(i + 1, len(parts) + 1)
    if parts[j - 1] != "__init__"
)


def _from_a_test_module(node: ast.ImportFrom) -> bool:
    """Whether ``node`` imports from another test module — a relative import, ``tests.…``, or
    a module or package under ``tests/`` (``test_worker``, ``fixtures.langs``,
    ``builders_repo``) — so a name it brings in can be that module's git helper. A name from the package under test or a
    library never is, whatever it is called: ``from crb.core import lint`` is not
    ``test_formatting``'s ``lint``."""
    return (
        bool(node.level)
        or (node.module or "").split(".")[0] == "tests"
        or (node.module in _TEST_MODULES)
    )


def _git_scope(tree: ast.Module, extern: Collection[str] = ()) -> tuple[set[str], set[str]]:
    """The module's git helpers — functions of any depth (a method, a fixture) that run git,
    and names it imports from a test module that holds one (``extern``) — and the names that
    hold what git said: assigned at module level, or to an attribute (``self.out``) in any
    function, to a fixpoint."""
    funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
    top = [s for s in tree.body if not isinstance(s, ast.FunctionDef | ast.AsyncFunctionDef)]
    imported = {
        a.asname or a.name
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and _from_a_test_module(n)
        for a in n.names
        if a.name in extern
    }
    helpers, tainted = set(imported), set(imported)
    while True:  # a function that calls one, or reads such a name, is one too
        before = len(helpers) + len(tainted)
        helpers |= {f.name for f in funcs if _reads_git(f, helpers, tainted)}
        tainted = _git_taint(top, helpers, tainted)
        for f in funcs:
            tainted |= {n for n in _git_taint(f.body, helpers, tainted) if "." in n}
        if len(helpers) + len(tainted) == before:
            return helpers, tainted


def git_helpers(tree: ast.Module, extern: Collection[str] = ()) -> set[str]:
    """What another test module can import from this one, or a test receive from it as a
    fixture, that holds what git said: its top-level git helpers and names."""
    helpers, tainted = _git_scope(tree, extern)
    top = {s.name for s in tree.body if isinstance(s, ast.FunctionDef | ast.AsyncFunctionDef)}
    return (helpers & top) | {n for n in tainted if "." not in n}


def _conditions(mark: ast.Call) -> list[ast.expr]:
    """A ``skipif`` or ``xfail`` mark's conditions — its positional arguments and
    ``condition=`` — and each string among them parsed as the expression pytest evaluates."""
    out = [*mark.args, *(k.value for k in mark.keywords if k.arg == "condition")]
    for n in list(out):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            try:
                with warnings.catch_warnings():  # a regex in a string is not a condition
                    warnings.simplefilter("ignore", SyntaxWarning)
                    out.append(ast.parse(n.value.strip(), mode="eval").body)
            except (SyntaxError, ValueError):
                continue
    return out


def _branches(node: ast.AST) -> list[ast.AST]:
    """What an ``if`` or a conditional expression runs, on either side of its test."""
    if isinstance(node, ast.If):
        return [*node.body, *node.orelse]
    if isinstance(node, ast.IfExp):
        return [node.body, node.orelse]
    return []


def history_skip_findings(source: str, where: str, extern: Collection[str] = ()) -> list[str]:
    """Every place a test skips, or passes having proved nothing, on what a ``git`` command
    said (P-753):

    - a ``skipif`` or ``xfail`` mark whose condition (a string one too) reads git;
    - an ``if`` or a conditional expression that reads git and skips in either branch;
    - an ``and`` / ``or`` that skips on git (``r.returncode and pytest.skip(…)``);
    - an ``except`` that skips around a git command;
    - a ``return`` from a test in an ``if`` that reads git.

    A skip is any spelling (``pytest.skip`` or ``xfail`` however imported, ``SkipTest``,
    ``pytest.skip.Exception``, a skip mark applied at run time, or a call to a function of the
    module that skips). Git is read directly, through a function of any depth that reads it
    (a method, a fixture the test takes), through a name assigned from one (a tuple unpacked,
    ``self.out``, a ``with … as``), or through ``extern``, the git helpers of the other test
    modules. The suite jobs hold the whole history, so a commit a test cannot read is a clone
    to deepen: the test fails, naming the fetch, and never skips the proof it was written to
    make."""
    tree = ast.parse(source)
    helpers, tainted = _git_scope(tree, extern)
    names = _pytest_names(tree)
    funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
    skippers: set[str] = set()
    while True:  # a function that calls one that skips skips too
        grown = {f.name for f in funcs if _calls_skip(f.body, names, skippers)}
        if grown == skippers:
            break
        skippers = grown
    scope_of = _enclosing(tree)
    local: dict[ast.AST, set[str]] = {tree: tainted}

    def git(node: ast.AST) -> bool:
        scope = scope_of.get(node, tree)
        if scope not in local:  # and the fixtures the function takes that read git
            args = getattr(scope, "args", None)
            given = {a.arg for a in ast.walk(args) if isinstance(a, ast.arg)} if args else set()
            seed = tainted | (given & (helpers | set(extern)))
            local[scope] = _git_taint(getattr(scope, "body", []), helpers, seed)
        return _reads_git(node, helpers, local[scope])

    def skips(*nodes: ast.AST) -> bool:
        return any(_skips(n, names, skippers) for n in nodes)

    fix = "pytest.fail, naming the fetch that deepens the clone"
    out: list[str] = []
    for node in ast.walk(tree):
        scope = scope_of.get(node, tree)
        if isinstance(node, ast.Call) and (
            _name(node.func) == "skipif"
            or (_name(node.func) == "xfail" and _name(getattr(node.func, "value", node)) == "mark")
        ):
            if any(git(c) for c in _conditions(node)):
                out.append(f"{where}:{node.lineno}: a {_name(node.func)} on what git said — {fix}")
        elif (branches := _branches(node)) and skips(*branches) and git(node.test):
            out.append(f"{where}:{node.lineno}: skips on what git said — {fix}")
        elif isinstance(node, ast.BoolOp) and any(skips(v) for v in node.values):
            if any(git(v) for v in node.values if not skips(v)):
                out.append(f"{where}:{node.lineno}: skips on what git said — {fix}")
        elif (
            isinstance(node, ast.Try)
            and any(skips(*h.body) for h in node.handlers)
            and any(git(s) for s in node.body)
        ):
            out.append(f"{where}:{node.lineno}: skips when git fails — {fix}")
        elif (
            isinstance(node, ast.If)
            and isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef)
            and scope.name.startswith("test")
            and any(isinstance(n, ast.Return) for s in node.body for n in ast.walk(s))
            and git(node.test)
        ):
            out.append(
                f"{where}:{node.lineno}: returns early on what git said, so the test passes "
                f"having proved nothing — {fix}"
            )
    return out


def test_no_test_skips_on_what_git_said() -> None:
    """The proof that ``workflow_jobs.json`` is the pull-request workflows at its commit
    skipped on a clone that lacked the commit, so a shallow checkout passed it having proved
    nothing (P-753). The suite jobs hold the whole history: a test that cannot read a commit
    fails, naming the fetch. A helper or fixture of another test module counts: the scan
    follows them across modules to a fixpoint."""
    trees = {p: ast.parse(p.read_text(encoding="utf-8")) for p in _test_sources()}
    extern: set[str] = set()
    while True:
        grown = {n for tree in trees.values() for n in git_helpers(tree, extern)}
        if grown == extern:
            break
        extern = grown
    found = [
        f
        for p in trees
        for f in history_skip_findings(
            p.read_text(encoding="utf-8"), str(p.relative_to(ROOT)), extern
        )
    ]
    assert found == []


#: Each shape of a skip on git the scan refuses — the one P-753 found, and each a review
#: planted against the first scan and found it passed.
HISTORY_SKIPS = {
    "nested-helper-local-exit-code": (
        'def test_a():\n    def git(*a):\n        return subprocess.run(["git", *a])\n'
        '    listed = git("ls-tree", "abc")\n    if listed.returncode != 0:\n'
        '        pytest.skip("a shallow clone")\n'
    ),
    "if-on-the-result": (
        'def f():\n    shown = subprocess.run(["git", "show", "abc:ci.yml"])\n'
        '    if shown.returncode != 0:\n        pytest.skip("a shallow clone")\n'
    ),
    "skipif-on-a-helper": (
        'def _has(c):\n    return subprocess.run(["git", "cat-file", "-e", c]).returncode == 0\n'
        '@pytest.mark.skipif(not _has("abc"), reason="x")\ndef test_a(): ...\n'
    ),
    "module-constant": (
        'HEAD = subprocess.run(("git", "rev-parse", "HEAD")).stdout\n'
        'def f():\n    if not HEAD:\n        pytest.skip("no history")\n'
    ),
    "except-around-git": (
        'def f():\n    try:\n        subprocess.run(["git", "show", "abc"], check=True)\n'
        '    except subprocess.CalledProcessError:\n        pytest.skip("a shallow clone")\n'
    ),
    "skip-in-the-else": (
        'def test_a():\n    r = subprocess.run(["git", "cat-file", "-e", "abc"])\n'
        '    if r.returncode == 0:\n        check(r)\n    else:\n        pytest.skip("shallow")\n'
    ),
    "skip-through-a-helper": (
        'def _shallow():\n    pytest.skip("a shallow clone")\n'
        'def test_a():\n    r = subprocess.run(["git", "show", "abc:ci.yml"])\n'
        "    if r.returncode != 0:\n        _shallow()\n"
    ),
    "helper-checks-and-skips": (
        'def _need(c):\n    if subprocess.run(["git", "cat-file", "-e", c]).returncode:\n'
        '        pytest.skip("a shallow clone")\ndef test_a():\n    _need("abc")\n'
    ),
    "skip-imported-bare": (
        'from pytest import skip\ndef test_a():\n    r = subprocess.run(["git", "show", "abc"])\n'
        '    if r.returncode:\n        skip("a shallow clone")\n'
    ),
    "pytest-under-an-alias": (
        'import pytest as pt\ndef test_a():\n    r = subprocess.run(["git", "show", "abc"])\n'
        '    if r.returncode:\n        pt.skip("a shallow clone")\n'
    ),
    "raise-SkipTest": (
        'def test_a():\n    r = subprocess.run(["git", "show", "abc"])\n'
        '    if r.returncode:\n        raise unittest.SkipTest("a shallow clone")\n'
    ),
    "raise-skip-Exception": (
        'def test_a():\n    r = subprocess.run(["git", "show", "abc"])\n'
        '    if r.returncode:\n        raise pytest.skip.Exception("a shallow clone")\n'
    ),
    "xfail": (
        'def test_a():\n    r = subprocess.run(["git", "show", "abc"])\n'
        '    if r.returncode:\n        pytest.xfail("a shallow clone")\n'
    ),
    "xfail-mark": (
        'def _has(c):\n    return subprocess.run(["git", "cat-file", "-e", c]).returncode == 0\n'
        '@pytest.mark.xfail(condition=not _has("abc"), reason="x")\ndef test_a(): ...\n'
    ),
    "tuple-unpacked": (
        'def _git(*a):\n    p = subprocess.run(["git", *a], capture_output=True, text=True)\n'
        '    return p.returncode, p.stdout\ndef test_a():\n    code, out = _git("ls-tree", "abc")\n'
        '    if code:\n        pytest.skip("a shallow clone")\n'
    ),
    "method-helper": (
        "class TestHistory:\n    def _has(self, c):\n"
        '        return subprocess.run(["git", "cat-file", "-e", c]).returncode == 0\n'
        '    def test_a(self):\n        if not self._has("abc"):\n            pytest.skip("x")\n'
    ),
    "fixture-the-test-takes": (
        '@pytest.fixture\ndef listed():\n    return subprocess.run(["git", "ls-tree", "abc"])\n'
        'def test_a(listed):\n    if listed.returncode != 0:\n        pytest.skip("shallow")\n'
    ),
    "fixture-that-skips": (
        '@pytest.fixture\ndef history():\n    r = subprocess.run(["git", "cat-file", "-e", "a"])\n'
        '    if r.returncode:\n        pytest.skip("a shallow clone")\n'
    ),
    "shell-string": (
        'def test_a():\n    r = subprocess.run("git cat-file -e abc", shell=True)\n'
        '    if r.returncode:\n        pytest.skip("a shallow clone")\n'
    ),
    "f-string-command": (
        'def test_a():\n    r = subprocess.run(f"git cat-file -e {C}", shell=True)\n'
        '    if r.returncode:\n        pytest.skip("a shallow clone")\n'
    ),
    "argv0-a-name": (
        'GIT = shutil.which("git") or "git"\ndef test_a():\n'
        '    r = subprocess.run([GIT, "cat-file", "-e", "abc"])\n'
        '    if r.returncode:\n        pytest.skip("a shallow clone")\n'
    ),
    "argv0-a-path": (
        'def test_a():\n    r = subprocess.run(["/usr/bin/git", "cat-file", "-e", "abc"])\n'
        '    if r.returncode:\n        pytest.skip("a shallow clone")\n'
    ),
    "os-system": (
        'def test_a():\n    if os.system("git cat-file -e abc"):\n        pytest.skip("shallow")\n'
    ),
    "the-product-Git": (
        "from crb.core.git import Git\ndef test_a():\n"
        '    if Git(ROOT).show_file("8fa2d73a", "ci.yml") is None:\n        pytest.skip("x")\n'
    ),
    "the-product-Git-through-a-local": (
        'from crb.core.git import Git\ndef test_a():\n    names = Git(ROOT).tree_names("8fa2d73a")\n'
        '    if not names:\n        pytest.skip("a shallow clone")\n'
    ),
    "skipif-string": (
        "@pytest.mark.skipif(\"subprocess.run(['git', 'cat-file', '-e', 'a']).returncode\", "
        'reason="x")\ndef test_a(): ...\n'
    ),
    "conditional-expression": (
        'def test_a():\n    r = subprocess.run(["git", "show", "abc"])\n'
        '    pytest.skip("a shallow clone") if r.returncode else None\n'
    ),
    "and-or": (
        'def test_a():\n    r = subprocess.run(["git", "show", "abc"])\n'
        '    r.returncode and pytest.skip("a shallow clone")\n'
    ),
    "with-as": (
        'def test_a():\n    with subprocess.Popen(["git", "show", "abc"]) as p:\n'
        '        if p.wait():\n            pytest.skip("a shallow clone")\n'
    ),
    "self-attribute": (
        "class TestH:\n    def setup_method(self):\n"
        '        self.r = subprocess.run(["git", "show", "abc"])\n'
        '    def test_a(self):\n        if self.r.returncode:\n            pytest.skip("x")\n'
    ),
    "skip-mark-applied-at-run-time": (
        'def test_a(request):\n    r = subprocess.run(["git", "show", "abc"])\n'
        '    if r.returncode:\n        request.applymarker(pytest.mark.skip(reason="shallow"))\n'
    ),
    "early-return": (
        'def test_a():\n    r = subprocess.run(["git", "ls-tree", "abc"])\n'
        "    if r.returncode != 0:\n        return\n    assert parse(r.stdout) == EXPECTED\n"
    ),
    "check-output-in-a-try": (
        'def test_a():\n    try:\n        out = subprocess.check_output(["git", "show", "abc"])\n'
        '    except subprocess.CalledProcessError:\n        pytest.skip("a shallow clone")\n'
    ),
    "on-its-output": (
        'def test_a():\n    out = subprocess.check_output(["git", "rev-list", "--count", "HEAD"])\n'
        '    if int(out) < 100:\n        pytest.skip("a shallow clone")\n'
    ),
}


@pytest.mark.parametrize("planted", HISTORY_SKIPS.values(), ids=HISTORY_SKIPS.keys())
def test_the_history_scan_finds_each_shape_of_a_skip_on_git(planted: str) -> None:
    assert history_skip_findings(planted, "planted"), planted


def test_the_history_scan_follows_a_helper_or_fixture_of_another_module() -> None:
    """A conftest fixture or a helper another module exports is followed: ``git_helpers``
    names it, and a test that takes or imports it and skips on it is refused. A name of the
    same spelling imported from the package under test is not that helper."""
    conftest = ast.parse(
        '@pytest.fixture\ndef history():\n    return subprocess.run(["git", "ls-tree", "a"])\n'
        'def has_commit(c):\n    return Git(ROOT).show_file(c, "x") is not None\n'
    )
    extern = git_helpers(conftest)
    assert extern == {"history", "has_commit"}
    taken = 'def test_a(history):\n    if history.returncode:\n        pytest.skip("shallow")\n'
    imported = (
        "from tests.helpers import has_commit\ndef test_a():\n"
        '    if not has_commit("abc"):\n        pytest.skip("shallow")\n'
    )
    sibling = imported.replace("tests.helpers", "test_worker")
    package = imported.replace("tests.helpers", "fixtures.langs")
    on_path = imported.replace("tests.helpers", "builders_repo")
    relative = imported.replace("tests.helpers", ".helpers")
    for planted in (taken, imported, sibling, package, on_path, relative):
        assert history_skip_findings(planted, "planted") == [], planted
        assert history_skip_findings(planted, "planted", extern), planted
    # A name from the package under test is never another module's helper, whatever it is
    # called. The scan read ``from crb.core import lint as lint_mod`` as test_formatting's git
    # helper ``lint``, and refused a test's return on ``lint_mod.LINT_NOT_REQUESTED``.
    product = (
        "from crb.core import has_commit as hc\ndef test_a(status):\n"
        "    if status == hc.NOT_REQUESTED:\n        return\n"
    )
    assert history_skip_findings(product, "planted", extern) == []


def test_the_history_scan_passes_a_fail_and_a_skip_on_something_else() -> None:
    fine = (
        'def f():\n    shown = subprocess.run(["git", "show", "abc"])\n'
        '    if shown.returncode != 0:\n        pytest.fail("git fetch origin abc")\n'
        'def g():\n    r = subprocess.run(["git", "log"])\n    assert r.returncode == 0\n'
        '    if not os.environ.get("CRB_TEST_POSTGRES_URL"):\n        pytest.skip("no postgres")\n'
        'def test_h():\n    if digit() or GitHub(token).ok or legit:\n        pytest.skip("x")\n'
        '    r = subprocess.run(["git", "show", "abc"])\n    if r.returncode:\n'
        '        pytest.fail("git fetch origin abc")\n'
        'def test_i(tmp_path):\n    if not os.environ.get("CI"):\n        return\n'
        "def built() -> tuple[GitRepo, str]:\n    return make()\n"
        "def test_j(built):\n    if not built:\n        return\n"
        '    if shutil.which("git") is None:\n        pytest.skip("the gate\'s job, not this scan\'s")\n'
        '    subprocess.run(["git", "init", tmp_path])\n'
    )
    assert history_skip_findings(fine, "fine") == []


#: A ``git clone`` / ``fetch`` / ``pull`` that cuts the history it takes, wherever its
#: options sit (``git -c k=v clone``, ``git -C dir fetch --depth=1``).
_CUT = re.compile(
    r"\bgit\b[^\n]*?\b(?:clone|fetch|pull)\b[^\n]*?--(?:depth|shallow|single-branch|deepen)"
)
#: A pytest command, by its last path part, and the arguments after it on that command.
_PYTEST = re.compile(r"(?:^|[\s;&|(\"'])(?:\S*/)?pytest(?=[\s\"']|$)([^\n;&|]*)")


def _runs(step: dict[str, object]) -> str:
    """A step's ``run`` with its continued lines joined and its comment lines dropped."""
    text = re.sub(r"\\\n\s*", " ", str(step.get("run") or ""))
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def suite_jobs(ci_text: str) -> set[str]:
    """Every job that runs the suite: one whose pytest names no test file and is not
    ``--version`` or ``--help``, so it collects every test under ``tests/``."""
    return {
        job
        for job, spec in yaml.safe_load(ci_text)["jobs"].items()
        for step in spec.get("steps") or []
        for args in _PYTEST.findall(_runs(step))
        if not re.search(r"\S+\.py\b|--(?:version|help)\b", args)
    }


def shallow_suite_findings(ci_text: str) -> list[str]:
    """Each suite job that holds less than the whole history: a checkout without
    ``fetch-depth: 0``, or a ``git clone`` / ``fetch`` / ``pull`` cut by ``--depth``,
    ``--deepen``, ``--shallow-*`` or ``--single-branch`` (P-753). It reads ``SUITE_JOBS`` and
    every job ``suite_jobs`` finds, so a new suite job is read before anyone names it, and a
    renamed one is reported gone."""
    jobs = yaml.safe_load(ci_text)["jobs"]
    out: list[str] = []
    for job in sorted(set(SUITE_JOBS) | suite_jobs(ci_text)):
        if job not in jobs:
            out.append(f"{job} is gone — SUITE_JOBS names a job ci.yml no longer has")
            continue
        steps = jobs[job].get("steps") or []
        checkouts = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout@")]
        if not checkouts or any((s.get("with") or {}).get("fetch-depth") != 0 for s in checkouts):
            out.append(f"{job} does not check out the whole history (fetch-depth: 0)")
        if any(_CUT.search(_runs(s)) for s in steps):
            out.append(f"{job} cuts the history it clones or fetches")
    return out


def test_the_suite_jobs_hold_the_whole_history() -> None:
    """Every job that runs the suite checks out the whole history, and the fresh-clone
    shards' clone of it is whole too: the proofs that read a commit run there (P-753)."""
    assert shallow_suite_findings(CI.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    ("what", "old", "new", "job"),
    [
        (
            "test-shard shallow",
            "fetch-depth: 0 # fixture replays and mining tests walk git history",
            "fetch-depth: 1",
            "test-shard",
        ),
        (
            "fresh-clone-shard depth dropped",
            "          fetch-depth: 0 # mining tests walk the history\n",
            "",
            "fresh-clone-shard",
        ),
        (
            "fresh clone cut",
            'git clone -q --no-local "$SRC" /root/fresh',
            'git clone -q --depth 1 --no-local "$SRC" /root/fresh',
            "fresh-clone-shard",
        ),
        (
            "clone cut after a git option",
            'git clone -q --no-local "$SRC" /root/fresh',
            'git -c protocol.file.allow=always clone -q --depth 1 --no-local "$SRC" /root/fresh',
            "fresh-clone-shard",
        ),
        (
            "clone cut on a continued line",
            'git clone -q --no-local "$SRC" /root/fresh',
            'git clone -q --no-local \\\n          --depth 1 "$SRC" /root/fresh',
            "fresh-clone-shard",
        ),
        (
            "fetch cut in another directory",
            'git fetch -q "$SRC" HEAD',
            'git -C /root/fresh fetch -q --depth=1 "$SRC" HEAD',
            "fresh-clone-shard",
        ),
        (
            "pull cut",
            'git fetch -q "$SRC" HEAD',
            'git pull -q --depth 1 "$SRC" HEAD',
            "fresh-clone-shard",
        ),
        (
            "a new suite job on a default checkout",
            "\n  test:\n",
            "\n  test-extra:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - uses: actions/checkout@v4\n      - run: .venv/bin/pytest -q\n"
            "\n  test:\n",
            "test-extra",
        ),
    ],
)
def test_the_history_check_refuses_a_shallow_suite_job(
    what: str, old: str, new: str, job: str
) -> None:
    text = CI.read_text(encoding="utf-8")
    assert old in text, f"{what}: the line moved"
    findings = shallow_suite_findings(text.replace(old, new))
    assert findings and all(f.startswith(job) for f in findings), (what, findings)


def test_suite_jobs_is_what_ci_runs_the_suite_in() -> None:
    """``SUITE_JOBS`` is checked against ci.yml, never only kept by hand: a job whose pytest
    names no test file runs the suite, so it must install what the suite skips on and hold
    the whole history (P-707, P-753)."""
    assert suite_jobs(CI.read_text(encoding="utf-8")) == set(SUITE_JOBS)


def test_the_history_check_reports_a_renamed_suite_job() -> None:
    text = CI.read_text(encoding="utf-8")
    renamed = text.replace("\n  test-shard:\n", "\n  unit-shard:\n")
    assert renamed != text, "the test-shard job moved"
    findings = shallow_suite_findings(renamed)
    assert "test-shard is gone — SUITE_JOBS names a job ci.yml no longer has" in findings
    assert suite_jobs(renamed) == {"unit-shard", "fresh-clone-shard"}
