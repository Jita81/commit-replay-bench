"""Ratchet: no builder path renders or runs a test or gate command with no dependency
binding (P-800, finding F87-1).

Under the sealed docker posture a command that runs with no binding mounts no dependency set
and, for Go, reads an empty ``GOMODCACHE=/tmp/gomod`` with the network off, so nothing builds:
the ``S1`` RED, the brief's test command and the finish gate's baseline were all rendered or
run that way on ``88ce5b4a``, and each one turned an infrastructure fault into a reading (every
authored test "not RED", a brief that told the builder to empty its own module cache, an
A0+L ``go vet`` gate red at every baseline and so never gating).

Navigation
----------
What it is:   The static half of P-800: an AST scan of ``src/crb/builders/`` and
              ``src/crb/core/finish_gate.py`` that fails on any call rendering or running a
              test or gate command with no dependency binding.
What it does: Flags a runner method that renders or runs the test command (``run``,
              ``command``, ``probe_environment``, ``run_for``, ``gate_run``,
              ``run_belt_for`` on a ``runner`` / ``self.runner`` receiver) and the gate and
              brief functions (``command_baseline``, ``_run_command``, ``verify``,
              ``sighted_test_command``) unless the call passes ``deps=`` (anything but the
              literal ``None``) or sits inside a ``with`` whose item calls ``deps_bound``. A
              finding passes only when :data:`ALLOWED` names it with its reason; an allowance
              nothing matches any more fails too. Proves the scan bites: planted unbound
              shapes are flagged, their bound twins are not, and stripping the binding from
              every bound call in the real modules is caught, mutant by mutant.
How:          ``ast`` over the files on disk, keyed by (path, enclosing function, callee).
              The root is this file's repository, so a copy of this file run inside an older
              tree (``git archive 88ce5b4a``) scans that tree. Blind spots (named in P-800):
              that the binding passed is the right one (the session's set, the parent's) is
              the behaviour tests' job; a command reached through an alias, a plain
              ``executor.run`` and the lint plan's ``run_plan`` (which takes no binding) are
              not followed.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0019-qualification-is-posture-relative.md
Works with:   src/crb/builders/adapter.py (the scanned call sites: ``author_s1``,
              ``sighted_test_command``, the finish gate's baseline), src/crb/core/finish_gate.py
              (``command_baseline`` / ``verify`` / ``_run_command`` — the gate's commands),
              src/crb/core/runners/base.py (``deps_bound`` and the ``deps=`` the runner
              methods take — what counts as bound), src/crb/builders/openai_agent.py (an
              allowance: its sealed tool loop mounts no set), src/crb/builders/toolcheck.py
              (an allowance: a host-only pre-check that can only refuse),
              tests/test_builders_sealed_deps.py (the behaviour: the env the commands carry),
              docs/PREVENTION.md (P-800)
Tested by:    tests/test_ratchet_sealed_deps.py
Touch when:   never for a new repository; a finding is reported (pass the binding the
              command runs under; allow it only with a reason that holds under the sealed
              posture); a new way to render or run a test or gate command appears in a builder.
"""

from __future__ import annotations

import ast
import copy
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
#: What the scan reads: every builder, and the finish gate the builders' adapter runs.
SCANNED = ("src/crb/builders", "src/crb/core/finish_gate.py")
#: The runner methods that render or run the task's test command (``BaseRunner``).
RUNNER_METHODS = ("run", "command", "probe_environment", "run_for", "gate_run", "run_belt_for")
#: The gate and brief functions that render or run a command under a binding they are given.
GATE_FUNCTIONS = ("command_baseline", "_run_command", "verify", "sighted_test_command")
#: The context manager that binds a runner for the calls inside it.
BINDS = "deps_bound"

#: (path, enclosing function, callee) → why that unbound call is right under the sealed posture.
ALLOWED: dict[tuple[str, str, str], str] = {
    ("src/crb/builders/openai_agent.py", "_Tools.run_target_tests", "runner.run"): (
        "the openai-agent tool loop's sealed executor (`tools_executor`) mounts no dependency "
        "set, so binding the runner alone would point the command at a set that is not there; "
        "openai-agent is not a Wave 3 builder (the registration names claude_code), and the "
        "fix (a deps-aware tools executor) is the known gap P-800 records"
    ),
    ("src/crb/builders/toolcheck.py", "runner_tool_missing", "runner.command"): (
        "the tool pre-check runs only under the local executor (it returns at once for a "
        "sandbox executor), where no sealed container session runs, and it can only refuse "
        "an attempt `harness` before any builder call — never move a verdict toward deliver"
    ),
}

#: Call sites that must be found bound — the scan is blind if one goes missing.
KNOWN_BOUND = (
    ("src/crb/builders/adapter.py", "sighted_test_command", "runner.command"),
    ("src/crb/core/finish_gate.py", "command_baseline", "_run_command"),
    ("src/crb/core/finish_gate.py", "verify", "_run_command"),
)


@dataclass(frozen=True)
class Call:
    path: str
    function: str
    callee: str
    line: int
    bound: bool

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.path, self.function, self.callee)


def _is_runner(node: ast.expr) -> bool:
    return (isinstance(node, ast.Name) and node.id == "runner") or (
        isinstance(node, ast.Attribute) and node.attr == "runner"
    )


def callee(call: ast.Call) -> str:
    """The scanned name ``call`` invokes (``runner.run``, ``command_baseline`` …), or ``""``."""
    f = call.func
    if isinstance(f, ast.Attribute) and f.attr in RUNNER_METHODS and _is_runner(f.value):
        return f"runner.{f.attr}"
    if isinstance(f, ast.Name) and f.id in GATE_FUNCTIONS:
        return f.id
    if isinstance(f, ast.Attribute) and f.attr in GATE_FUNCTIONS and f.attr != "verify":
        return f.attr  # ``finish_gate.command_baseline(...)``; ``x.verify`` is anyone's
    return ""


def _passes_deps(call: ast.Call) -> bool:
    return any(
        kw.arg == "deps" and not (isinstance(kw.value, ast.Constant) and kw.value.value is None)
        for kw in call.keywords
    )


def _binds(item: ast.withitem) -> bool:
    """A ``with`` item that calls ``deps_bound`` — directly or in a conditional expression
    (``runner.deps_bound(d) if d is not None else nullcontext()``)."""
    return any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == BINDS
        for n in ast.walk(item.context_expr)
    )


class _Scan(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.stack: list[str] = []
        self.bound_depth = 0
        self.found: list[Call] = []

    def _scope(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        # a nested def runs later, outside the ``with`` it is written in
        depth, self.bound_depth = self.bound_depth, 0
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()
        self.bound_depth = depth

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scope(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._scope(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope(node)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            self.visit(item)
        binds = any(_binds(i) for i in node.items)
        self.bound_depth += binds
        for stmt in node.body:
            self.visit(stmt)
        self.bound_depth -= binds

    def visit_Call(self, node: ast.Call) -> None:
        name = callee(node)
        if name:
            function = ".".join(self.stack) or "<module>"
            bound = self.bound_depth > 0 or _passes_deps(node)
            self.found.append(Call(self.path, function, name, node.lineno, bound))
        self.generic_visit(node)


def scan_tree(tree: ast.AST, path: str) -> list[Call]:
    """Every scanned call in ``tree``, bound or not."""
    s = _Scan(path)
    s.visit(tree)
    return s.found


def unbound(tree: ast.AST, path: str) -> list[Call]:
    return [c for c in scan_tree(tree, path) if not c.bound]


def _modules() -> dict[str, ast.Module]:
    out: dict[str, ast.Module] = {}
    for entry in SCANNED:
        p = ROOT / entry
        for f in sorted(p.rglob("*.py")) if p.is_dir() else [p]:
            rel = f.relative_to(ROOT).as_posix()
            out[rel] = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
    return out


def _scan_all() -> list[Call]:
    return [c for path, tree in _modules().items() for c in scan_tree(tree, path)]


# ---------------------------------------------------------------------------
# The ratchet
# ---------------------------------------------------------------------------


def test_the_scan_sees_the_calls_it_guards() -> None:
    bound = {c.key for c in _scan_all() if c.bound}
    missing = [k for k in KNOWN_BOUND if k not in bound]
    assert not missing, f"the scan no longer sees these bound calls: {missing} — it is blind"


def test_no_builder_renders_or_runs_a_command_without_a_binding() -> None:
    bad = [c for c in _scan_all() if not c.bound and c.key not in ALLOWED]
    assert not bad, (
        "a test or gate command rendered or run with no dependency binding mounts no set "
        "under the sealed posture — for Go an empty /tmp/gomod with the network off, so "
        "nothing builds and an infrastructure fault reads as a verdict (P-800, F87-1). Pass "
        "the binding it runs under (`deps=`, or inside `with runner.deps_bound(...)`), or add "
        "it to ALLOWED with the reason it is right under the sealed posture:\n"
        + "\n".join(f"  {c.path}:{c.line} {c.function}: {c.callee}" for c in bad)
    )


def test_every_allowance_still_matches_an_unbound_call() -> None:
    seen = {c.key for c in _scan_all() if not c.bound}
    stale = [k for k in ALLOWED if k not in seen]
    assert not stale, f"remove the allowances nothing matches any more: {stale}"
    assert all(len(why) > 60 for why in ALLOWED.values()), "an allowance needs its reason"


# ---------------------------------------------------------------------------
# The scan bites — planted shapes, then mutants of the real modules
# ---------------------------------------------------------------------------

UNBOUND = {
    "runner.run": "def f(runner, ex, root):\n    return runner.run(ex, root, ())\n",
    "self.runner.run": "class C:\n    def f(self):\n        return self.runner.run(1, 2, 3)\n",
    "runner.command": "def f(runner, root):\n    return runner.command(root, ())\n",
    "runner.probe_environment": "def f(runner, ex, r):\n    runner.probe_environment(ex, r)\n",
    "run_for no deps": "def f(runner, ex, r):\n    return runner.run_for(ex, r, ())\n",
    "run_for deps=None": "def f(runner, ex, r):\n    return runner.run_for(ex, r, (), deps=None)\n",
    "gate_run": "def f(runner, ex, r):\n    return runner.gate_run(ex, r, ())\n",
    "run_belt_for": "def f(runner, ex, r):\n    return runner.run_belt_for(ex, r, ())\n",
    "command_baseline": "def f(c, ex, root):\n    return command_baseline(c, ex, root)\n",
    "fg.command_baseline": "def f(c, ex, r):\n    return fg.command_baseline(c, ex, r)\n",
    "_run_command": "def f(c, ex, root):\n    return _run_command(c, ex, root)\n",
    "verify": "def f(p, c, ex, r):\n    return verify(p, c, ex, r, [])\n",
    "sighted_test_command": "def f(rn, ex, r):\n    return sighted_test_command(rn, ex, r, ())\n",
    "after the with": (
        "def f(runner, d, r):\n    with runner.deps_bound(d):\n        pass\n"
        "    return runner.command(r, ())\n"
    ),
    "a def inside the with": (
        "def f(runner, d, r):\n    with runner.deps_bound(d):\n"
        "        def later():\n            return runner.command(r, ())\n    return later\n"
    ),
    "with another manager": (
        "def f(runner, r, lock):\n    with lock:\n        return runner.command(r, ())\n"
    ),
}

BOUND = {
    "run_for deps=": "def f(runner, ex, r, d):\n    return runner.run_for(ex, r, (), deps=d)\n",
    "command_baseline deps=": (
        "def f(c, ex, root, d):\n    return command_baseline(c, ex, root, deps=d)\n"
    ),
    "_run_command deps=": "def f(c, ex, r, b):\n    return _run_command(c, ex, r, deps=b.deps)\n",
    "with deps_bound": (
        "def f(runner, d, r):\n    with runner.deps_bound(d):\n"
        "        return runner.command(r, ())\n"
    ),
    "with deps_bound if": (
        "import contextlib\ndef f(runner, d, r):\n"
        "    with runner.deps_bound(d) if d else contextlib.nullcontext():\n"
        "        return runner.run(1, r, ())\n"
    ),
    "with deps_bound among items": (
        "def f(runner, d, r, lock):\n    with lock, runner.deps_bound(d):\n"
        "        return runner.probe_environment(1, r)\n"
    ),
    "another receiver's run": "def f(repo):\n    return repo.run('show', 'HEAD')\n",
    "an executor's run": "def f(executor, cmd):\n    return executor.run(cmd)\n",
    "someone's verify": "def f(sig):\n    return sig.verify(b'x')\n",
    "a definition": "def command_baseline(commands, executor, root, *, deps):\n    return {}\n",
}


@pytest.mark.parametrize("shape", sorted(UNBOUND))
def test_a_planted_unbound_call_is_flagged(shape: str) -> None:
    assert unbound(ast.parse(UNBOUND[shape]), "planted.py"), f"{shape} was not flagged"


@pytest.mark.parametrize("shape", sorted(BOUND))
def test_a_planted_bound_call_is_not_flagged(shape: str) -> None:
    assert unbound(ast.parse(BOUND[shape]), "planted.py") == [], f"{shape} was flagged"


class _StripBinding(ast.NodeTransformer):
    """Remove the ``nth`` binding in a module: a ``deps=`` keyword on a scanned call, or a
    ``deps_bound`` call in a ``with`` item (made ``nullcontext()``)."""

    def __init__(self, nth: int) -> None:
        self.nth = nth
        self.seen = 0

    def _hit(self) -> bool:
        self.seen += 1
        return self.seen - 1 == self.nth

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.func, ast.Attribute) and node.func.attr == BINDS and self._hit():
            return ast.Call(ast.Name("nullcontext", ast.Load()), [], [])
        if callee(node) and _passes_deps(node) and self._hit():
            node.keywords = [kw for kw in node.keywords if kw.arg != "deps"]
        return node


def _bindings(tree: ast.AST) -> int:
    counter = _StripBinding(-1)
    counter.visit(copy.deepcopy(tree))
    return counter.seen


def _mutants() -> list[tuple[str, int]]:
    return [(path, n) for path, tree in _modules().items() for n in range(_bindings(tree))]


def test_the_real_modules_carry_bindings_to_strip() -> None:
    paths = {path for path, _ in _mutants()}
    assert {"src/crb/builders/adapter.py", "src/crb/core/finish_gate.py"} <= paths


@pytest.mark.parametrize(("path", "nth"), _mutants())
def test_stripping_a_real_binding_is_caught(path: str, nth: int) -> None:
    tree = _modules()[path]
    before = len(unbound(tree, path))
    mutant = _StripBinding(nth).visit(copy.deepcopy(tree))
    assert len(unbound(mutant, path)) > before, (
        f"stripping binding #{nth} in {path} left no new unbound call: the scan is blind to it"
    )
