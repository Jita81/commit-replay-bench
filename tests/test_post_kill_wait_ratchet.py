"""Ratchet: no module that kills a process waits on anything without a bound (P-774).

A kill does not end every process holding a pipe or a wait: a process outside the killed
group (one that called ``setsid``) keeps the output pipes open, on macOS so does a member
forked as the ``killpg`` is sent (until the group is killed again),
and a process stuck in the kernel does not exit. So in a module that kills, a
``Thread.join()``, ``Popen.wait()``, ``communicate()`` or ``select()`` with no timeout, a
``waitpid`` without ``WNOHANG``, iterating or reading a ``stdout`` / ``stderr`` pipe, or
``with Popen(...)`` (whose exit waits with no timeout) can hang its caller as long as that
process lives — defect I-09, a test that waited 60 s for a sleep its cancel had not reached.

Navigation
----------
What it is:   The static half of P-774: an AST scan of every ``src/crb`` module that kills —
              calls ``kill`` / ``killpg`` / ``terminate`` / ``send_signal`` or a helper named
              for a kill (``_kill_group``, ``kill_again``), or builds a ``docker kill`` /
              ``rm -f`` argv — failing on any wait in it that has no bound.
What it does: Finds the kill modules; in each, flags ``.join()`` / ``.wait()`` /
              ``.select()`` with no timeout (or ``None``; ``select.select`` takes it fourth),
              ``.communicate()`` with no timeout, ``waitpid`` / ``wait4`` / ``waitid`` without
              ``WNOHANG``, a ``for`` / comprehension / ``yield from`` over ``X.stdout`` /
              ``X.stderr``, any reference to ``X.stdout.read*`` (called, or handed on as in
              ``iter(p.stdout.readline, "")``), a pipe handed to an iterating consumer
              (``list``, ``json.load``, ``"".join`` …), and ``with Popen(...)``. A finding
              passes only when :data:`ALLOWED` names it with its justification; an allowance
              nothing matches any more fails too. Proves the scan bites: planted unbounded
              shapes are flagged, their bounded twins are not, each way to kill makes a module
              scanned, and stripping the timeout from every bounded wait and select in the real
              kill modules is caught, mutant by mutant.
How:          ``ast`` over the files on disk, keyed by (path, enclosing function, kind); the
              whole module is scanned because its kills run on other threads (a watchdog, a
              cancel poller), so any wait in it can follow one. Blind spots (named in P-774):
              a pipe or a wait reached through an alias or handed to a function it does not
              list, and a timeout that is a bound in name only (``join(1e9)``).
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/core/execution.py (``OutputDrain``, ``read_lines``, ``reap_after_kill`` —
              the bounded helpers a finding is fixed with), src/crb/builders/claude_code.py (a
              kill module: the claude CLI transport), src/crb/provision/fetch.py (a kill module:
              the fetch runner), src/crb/core/mine.py (the one allowance),
              tests/test_execution_post_kill.py (the behaviour), docs/PREVENTION.md (P-774)
Tested by:    tests/test_post_kill_wait_ratchet.py
Touch when:   never for a new repository; a finding is reported (bound the wait with the
              helpers; allow it only with a reason that holds for a process the kill did not
              reach); a new way to kill, to wait or to read a pipe appears in a kill module.
"""

from __future__ import annotations

import ast
import copy
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "crb"

#: A call that sends a process a signal, or calls a helper named for one (``_kill_group``,
#: ``kill_again``, ``pthread_kill``): the module it is in "kills".
KILL_CALL = re.compile(r"_?kill(?:_\w+)?|\w+_kill|killpg|terminate|send_signal")
#: Methods that wait for a thread or a process and take a ``timeout``.
WAITS = ("join", "wait")
PIPES = ("stdout", "stderr")
#: A pipe's methods that read until data or EOF — no argument bounds their time.
READS = ("read", "read1", "readinto", "readinto1", "readline", "readlines")
#: Calls that read a pipe they are handed until EOF: iteration and the stdlib consumers.
#: A pipe handed to any other function is not followed (docs/PREVENTION.md P-774, gaps).
CONSUMERS = (
    "iter", "next", "list", "tuple", "set", "sorted", "enumerate", "zip", "map", "filter",
    "join", "load", "copyfileobj", "TextIOWrapper", "reader", "DictReader",
)  # fmt: skip
#: ``waitpid`` / ``wait4`` / ``waitid`` and where their options are: without ``WNOHANG``
#: they block until the process exits.
OS_WAITS = {"waitpid": 1, "wait4": 1, "waitid": 2}

#: (path, enclosing function, kind) → why that unbounded wait cannot hang after a kill.
ALLOWED: dict[tuple[str, str, str], str] = {
    ("src/crb/core/mine.py", "_patch_ids", "with Popen"): (
        "Popen.__exit__ waits on `git log`, a direct child with no children of its own, "
        "after `log.kill()` SIGKILLed it by pid and its stdout was closed — nothing outside "
        "a group holds anything, and a SIGKILLed process with no pipe to drain exits."
    ),
}

#: The modules that must be found as killing — the scan is wrong if one goes missing.
KNOWN_KILL_MODULES = (
    "src/crb/core/execution.py",
    "src/crb/provision/fetch.py",
    "src/crb/builders/claude_code.py",
)


@dataclass(frozen=True)
class Finding:
    path: str
    function: str
    kind: str
    line: int

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.path, self.function, self.kind)


def _callee(call: ast.Call) -> str:
    f = call.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


def _is_none(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _timeout_of(call: ast.Call, position: int) -> ast.expr | None:
    """The ``timeout`` argument, by keyword or at ``position``; ``None`` when absent."""
    for kw in call.keywords:
        if kw.arg == "timeout":
            return kw.value
    if len(call.args) > position:
        return call.args[position]
    return None


def _timeout_position(call: ast.Call) -> int | None:
    """Where ``call`` takes its timeout, when it is a wait that takes one."""
    f = call.func
    if not isinstance(f, ast.Attribute):
        return None
    if f.attr in WAITS:
        return 0
    if f.attr == "communicate":
        return 1
    if f.attr == "select":  # select.select(r, w, x, timeout) or a selector's select(timeout)
        return 3 if isinstance(f.value, ast.Name) and f.value.id == "select" else 0
    return None


def _mentions(node: ast.expr | None, name: str) -> bool:
    return node is not None and any(
        (isinstance(n, ast.Name) and n.id == name)
        or (isinstance(n, ast.Attribute) and n.attr == name)
        for n in ast.walk(node)
    )


def _unbounded(call: ast.Call) -> str:
    """The kind of unbounded wait ``call`` is, or ``""``."""
    if not isinstance(call.func, ast.Attribute):
        return ""
    name = call.func.attr
    position = _timeout_position(call)
    if position is not None:
        timeout = _timeout_of(call, position)
        if timeout is None or _is_none(timeout):
            return f"{name}()"
    if name in OS_WAITS:
        options = OS_WAITS[name]
        given = call.args[options] if len(call.args) > options else None
        if not _mentions(given, "WNOHANG"):
            return f"{name}() without WNOHANG"
    return ""


def _is_pipe(node: ast.expr) -> bool:
    """``X.stdout`` / ``X.stderr`` — a child's pipe; ``sys.stdout`` is this process's own."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr in PIPES
        and not (isinstance(node.value, ast.Name) and node.value.id == "sys")
    )


def _pipe_read(node: ast.Attribute) -> bool:
    """``X.stdout.read`` / ``.readline`` / ``.read1`` / ``.readinto`` … — called or handed
    on (``iter(p.stdout.readline, "")``): no argument bounds its time."""
    return node.attr in READS and _is_pipe(node.value)


def _kills_by_argv(tree: ast.AST) -> bool:
    """An argv literal that kills a container: ``[docker, "kill", …]`` or ``rm -f``."""
    for n in ast.walk(tree):
        if isinstance(n, (ast.List, ast.Tuple)):
            words = {e.value for e in n.elts if isinstance(e, ast.Constant)}
            if "kill" in words or ("rm" in words and words & {"-f", "--force"}):
                return True
    return False


def kills(tree: ast.AST) -> bool:
    return _kills_by_argv(tree) or any(
        isinstance(n, ast.Call) and KILL_CALL.fullmatch(_callee(n)) for n in ast.walk(tree)
    )


class _Scan(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.stack: list[str] = []
        self.found: list[Finding] = []

    def _add(self, kind: str, node: ast.AST) -> None:
        function = ".".join(self.stack) or "<module>"
        self.found.append(Finding(self.path, function, kind, getattr(node, "lineno", 0)))

    def _scope(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scope(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._scope(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope(node)

    def visit_Call(self, node: ast.Call) -> None:
        kind = _unbounded(node)
        if kind:
            self._add(kind, node)
        if _callee(node) in CONSUMERS and any(_is_pipe(a) for a in node.args):
            self._add("pipe consumed", node)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if _pipe_read(node):
            self._add("pipe read", node)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        if _is_pipe(node.iter):
            self._add("for over pipe", node)
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        if _is_pipe(node.iter):
            self._add("for over pipe", node.iter)
        self.generic_visit(node)

    def visit_YieldFrom(self, node: ast.YieldFrom) -> None:
        if _is_pipe(node.value):
            self._add("for over pipe", node)
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            expr = item.context_expr
            if isinstance(expr, ast.Call) and _callee(expr) == "Popen":
                self._add("with Popen", node)
        self.generic_visit(node)


def scan_tree(tree: ast.AST, path: str) -> list[Finding]:
    """Every unbounded wait in ``tree`` — empty when the module kills nothing."""
    if not kills(tree):
        return []
    s = _Scan(path)
    s.visit(tree)
    return s.found


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def _kill_modules() -> dict[str, ast.Module]:
    out: dict[str, ast.Module] = {}
    for p in sorted(SRC.rglob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        if kills(tree):
            out[_rel(p)] = tree
    return out


def _scan_all() -> list[Finding]:
    return [f for path, tree in _kill_modules().items() for f in scan_tree(tree, path)]


# ---------------------------------------------------------------------------
# The ratchet
# ---------------------------------------------------------------------------


def test_the_scan_finds_the_modules_that_kill() -> None:
    found = set(_kill_modules())
    missing = [m for m in KNOWN_KILL_MODULES if m not in found]
    assert not missing, f"the kill scan no longer sees {missing}: it is blind"


def test_no_module_that_kills_waits_without_a_bound() -> None:
    bad = [f for f in _scan_all() if f.key not in ALLOWED]
    assert not bad, (
        "an unbounded wait in a module that kills a process can hang its caller for as long "
        "as a process the kill did not reach holds the pipe (P-774). Bound it — "
        "crb.core.execution.OutputDrain / read_lines / reap_after_kill, or a timeout — or "
        "add it to ALLOWED with the reason it cannot hang:\n"
        + "\n".join(f"  {f.path}:{f.line} {f.function}: {f.kind}" for f in bad)
    )


def test_every_allowance_still_matches_something() -> None:
    seen = {f.key for f in _scan_all()}
    stale = [k for k in ALLOWED if k not in seen]
    assert not stale, f"remove the allowances nothing matches any more: {stale}"
    assert all(len(why) > 40 for why in ALLOWED.values()), "an allowance needs its reason"


# ---------------------------------------------------------------------------
# The scan bites — planted shapes, then mutants of the real modules
# ---------------------------------------------------------------------------

_KILLER = "import os, signal, subprocess\n\ndef stop(p):\n    os.killpg(p.pid, signal.SIGKILL)\n\n"

UNBOUNDED = {
    "join()": "def f(t):\n    t.join()\n",
    "join(None)": "def f(t):\n    t.join(None)\n",
    "wait()": "def f(p):\n    p.wait()\n",
    "wait(timeout=None)": "def f(p):\n    p.wait(timeout=None)\n",
    "communicate()": "def f(p):\n    p.communicate()\n",
    "communicate(input)": "def f(p):\n    p.communicate('x')\n",
    "communicate(timeout=None)": "def f(p):\n    p.communicate(timeout=None)\n",
    "for over stdout": "def f(p):\n    for line in p.stdout:\n        print(line)\n",
    "yield from stderr": "def f(p):\n    yield from p.stderr\n",
    "stdout.read()": "def f(p):\n    return p.stdout.read()\n",
    "stderr.readline()": "def f(p):\n    return p.stderr.readline()\n",
    "with Popen": "def f(a):\n    with subprocess.Popen(a) as p:\n        p.kill()\n",
    "nested def": "def f(p):\n    def g():\n        p.wait()\n    return g\n",
    "method": "class C:\n    def f(self):\n        self._t.join()\n",
    "selector.select()": "def f(sel):\n    return sel.select()\n",
    "selector.select(None)": "def f(sel):\n    return sel.select(timeout=None)\n",
    "select.select no timeout": "import select\ndef f(fd):\n    select.select([fd], [], [])\n",
    "waitpid(pid, 0)": "def f(pid):\n    os.waitpid(pid, 0)\n",
    "waitid no WNOHANG": "def f(pid):\n    os.waitid(os.P_PID, pid, os.WEXITED)\n",
    "stdout.read1()": "def f(p):\n    return p.stdout.read1(10)\n",
    "stderr.readinto()": "def f(p, b):\n    return p.stderr.readinto(b)\n",
    "iter(stdout.readline)": "def f(p):\n    return iter(p.stdout.readline, '')\n",
    "comprehension over stderr": "def f(p):\n    return [x for x in p.stderr]\n",
    "list(stdout)": "def f(p):\n    return list(p.stdout)\n",
    "json.load(stdout)": "import json\ndef f(p):\n    return json.load(p.stdout)\n",
    "str.join(stdout)": "def f(p):\n    return ''.join(p.stdout)\n",
}

BOUNDED = {
    "join(1)": "def f(t):\n    t.join(1)\n",
    "join(timeout=)": "def f(t):\n    t.join(timeout=2.0)\n",
    "wait(timeout=)": "def f(p):\n    p.wait(timeout=5)\n",
    "communicate(timeout=)": "def f(p):\n    p.communicate(timeout=3)\n",
    "communicate(input, t)": "def f(p):\n    p.communicate(None, 3)\n",
    "str.join": "def f(xs):\n    return ', '.join(xs)\n",
    "for over a list": "def f(p):\n    for x in p.args:\n        print(x)\n",
    "file read": "def f(fh):\n    return fh.read()\n",
    "selector.select(t)": "def f(sel):\n    return sel.select(0.1)\n",
    "select.select(t)": "import select\ndef f(fd):\n    select.select([fd], [], [], 0.5)\n",
    "waitpid WNOHANG": "def f(pid):\n    os.waitpid(pid, os.WNOHANG)\n",
    "waitid WNOHANG": "def f(pid):\n    os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG)\n",
    "read_lines(stdout)": "def f(p, k):\n    yield from read_lines(p.stdout, killed_at=k)\n",
    "stdout.readable()": "def f(p):\n    return p.stdout.readable()\n",
    "own sys.stdout": "import sys\ndef f():\n    return list(sys.stdout.readlines())\n",
    "CompletedProcess.stdout": "def f(r):\n    return parse(r.stdout.strip())\n",
}

#: A module "kills" by any of these, alone — each one makes the planted wait a finding.
KILLERS = {
    "os.killpg": "import os\ndef stop(p):\n    os.killpg(p.pid, 9)\n",
    "Popen.terminate": "def stop(p):\n    p.terminate()\n",
    "send_signal": "def stop(p):\n    p.send_signal(9)\n",
    "a _kill helper": "def stop(p):\n    _kill_group(p)\n",
    "a kill_again hook": "def stop(h):\n    h.kill_again()\n",
    "pthread_kill": "import signal\ndef stop(t):\n    signal.pthread_kill(t, 9)\n",
    "docker kill argv": "def stop(run, n):\n    run(['docker', 'kill', n])\n",
    "docker rm -f argv": "def stop(run, n):\n    run(('docker', 'rm', '-f', n))\n",
}


@pytest.mark.parametrize("shape", sorted(UNBOUNDED))
def test_a_planted_unbounded_wait_is_flagged(shape: str) -> None:
    tree = ast.parse(_KILLER + UNBOUNDED[shape])
    assert scan_tree(tree, "planted.py"), f"{shape} was not flagged"


@pytest.mark.parametrize("shape", sorted(BOUNDED))
def test_a_planted_bounded_wait_is_not_flagged(shape: str) -> None:
    tree = ast.parse(_KILLER + BOUNDED[shape])
    assert scan_tree(tree, "planted.py") == [], f"{shape} was flagged"


def test_a_module_that_kills_nothing_is_not_scanned() -> None:
    assert scan_tree(ast.parse(UNBOUNDED["join()"]), "planted.py") == []
    benign = "def f(run, n):\n    run(['docker', 'rm', n])\n    return ('skill', 'killer')\n"
    assert scan_tree(ast.parse(benign + UNBOUNDED["join()"]), "planted.py") == []


@pytest.mark.parametrize("killer", sorted(KILLERS))
def test_every_way_to_kill_makes_a_module_scanned(killer: str) -> None:
    tree = ast.parse(KILLERS[killer] + UNBOUNDED["wait()"])
    assert scan_tree(tree, "planted.py"), f"a module that kills by {killer} was not scanned"


def _not_a_wait(receiver: ast.expr) -> bool:
    """``", ".join(…)`` and ``os.path.join(…)`` share the name and are no wait."""
    return isinstance(receiver, ast.Constant) or (
        isinstance(receiver, ast.Attribute) and receiver.attr == "path"
    )


def _bounded_waits(tree: ast.AST) -> list[ast.Call]:
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute):
            continue
        position = _timeout_position(n)
        if position is None or _not_a_wait(n.func.value) or _unbounded(n):
            continue
        if _timeout_of(n, position) is not None:
            out.append(n)
    return out


def _strip_timeout(call: ast.Call) -> None:
    position = _timeout_position(call)
    assert position is not None
    call.args = call.args[:position]
    call.keywords = [kw for kw in call.keywords if kw.arg != "timeout"]


def test_every_bound_in_the_real_kill_modules_is_load_bearing_for_the_scan() -> None:
    """Mutation: take each bounded join/wait/communicate/select in the real kill modules,
    strip its timeout, and the scan must flag the mutant at that line."""
    mutants = selects = 0
    for path, tree in _kill_modules().items():
        for target in _bounded_waits(tree):
            mutant = copy.deepcopy(tree)
            twin = next(
                n
                for n in ast.walk(mutant)
                if isinstance(n, ast.Call)
                and (n.lineno, n.col_offset) == (target.lineno, target.col_offset)
            )
            _strip_timeout(twin)
            flagged = {f.line for f in scan_tree(mutant, path) if f.key not in ALLOWED}
            assert target.lineno in flagged, f"{path}:{target.lineno} stripped and not caught"
            mutants += 1
            selects += _callee(target) == "select"
    # execution.py alone bounds the drain joins, the reaps and the stream's waits
    assert mutants >= 10, f"only {mutants} bounded waits found: the mutation set is too thin"
    # the drain's and read_lines' selects: without their wake-up an abandoned reader never
    # sees it was stopped, so it holds its pipes for as long as the process the kill missed
    assert selects >= 2, f"only {selects} bounded selects mutated: the drains are not covered"
