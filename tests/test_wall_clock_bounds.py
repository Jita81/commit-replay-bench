"""No test bounds a wall-clock interval tighter than a loaded machine can keep.

A test that times real work — a process spawn, a scripted daemon, a thread's sleep — and
asserts the interval is under a second or two measures the machine, not the code: under
load a spawn alone can take seconds, and the build goes red for no fault
(docs/PREVENTION.md P-014: the reaper's budget test failed that way, and so did the
cancel-kill test in tests/test_execution.py). Time-budget arithmetic is tested on a fake
clock (``tests/test_server_reaper.py::_FakeDaemon``); where a real interval must be
bounded, the bound only has to tell "bounded" from "unbounded", so it can be generous.

Navigation
----------
What it is:   The ratchet for the test-timing-flake class: a scan of every test module for
              an upper bound on elapsed wall-clock time below :data:`FLOOR_S`.
What it does: Parses each ``tests/**/*.py``; per function it follows names assigned from
              ``time.monotonic()`` / ``time.time()`` / ``time.perf_counter()`` differences
              and names bound to numbers, and refuses a comparison that holds such an
              interval under a resolvable bound below the floor. A planted example proves
              the scan still catches each shape.
How:          ``ast`` walk → per-function symbol table (elapsed names, numeric names) →
              ``Compare`` pairs (``<``, ``<=``, and the mirrored ``>``, ``>=``) → a list of
              ``file:line`` findings.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   tests/test_server_reaper.py (budget tests moved to fake or in-process daemons),
              tests/test_worker.py and tests/test_worker_reaper.py (the same, for the worker),
              tests/test_execution.py (the kill-bound tests given room), docs/PREVENTION.md
              (P-014, the row this closes)
Tested by:    tests/test_wall_clock_bounds.py
Touch when:   never for a new repository; a test needs a wall-clock bound: make it at least the
              floor and wide enough to tell bounded from unbounded, or move the arithmetic onto a
              fake clock.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
#: The tightest wall-clock bound a test may assert, in seconds.
FLOOR_S = 5.0
_CLOCKS = frozenset({"monotonic", "time", "perf_counter"})


def _reads_clock(node: ast.AST) -> bool:
    """``node`` calls ``time.monotonic()`` / ``time.time()`` / ``time.perf_counter()``."""
    return any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in _CLOCKS
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "time"
        for n in ast.walk(node)
    )


class _Scope:
    def __init__(self, fn: ast.AST) -> None:
        self.elapsed: set[str] = set()
        self.numbers: dict[str, float] = {}
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            if self._is_interval(node.value):
                self.elapsed.add(target.id)
            else:
                value = self.number(node.value)
                if value is not None:
                    self.numbers[target.id] = value

    def _is_interval(self, node: ast.AST) -> bool:
        return (
            isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub) and _reads_clock(node.left)
        )

    def interval(self, node: ast.AST) -> bool:
        """``node`` is an elapsed wall-clock interval."""
        if isinstance(node, ast.Name):
            return node.id in self.elapsed
        return self._is_interval(node)

    def number(self, node: ast.AST) -> float | None:
        """The value of a numeric literal, a name bound to one, or arithmetic over them."""
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return float(node.value)
        if isinstance(node, ast.Name):
            return self.numbers.get(node.id)
        if isinstance(node, ast.BinOp):
            left, right = self.number(node.left), self.number(node.right)
            if left is None or right is None:
                return None
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Div) and right:
                return left / right
        return None


def findings(source: str, name: str = "<source>") -> list[str]:
    """Every comparison in ``source`` that holds a wall-clock interval under a bound below
    :data:`FLOOR_S`, as ``name:line``."""
    tree = ast.parse(source)
    lines: set[int] = set()
    functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
    for fn in functions:
        scope = _Scope(fn)
        for node in ast.walk(fn):
            if not isinstance(node, ast.Compare):
                continue
            operands = [node.left, *node.comparators]
            for i, op in enumerate(node.ops):
                a, b = operands[i], operands[i + 1]
                if isinstance(op, ast.Lt | ast.LtE):
                    interval, bound = a, b
                elif isinstance(op, ast.Gt | ast.GtE):
                    interval, bound = b, a
                else:
                    continue
                if not scope.interval(interval):
                    continue
                value = scope.number(bound)
                if value is not None and value < FLOOR_S:
                    lines.add(node.lineno)
    return [f"{name}:{line}" for line in sorted(lines)]


def test_no_test_bounds_a_wall_clock_interval_below_the_floor() -> None:
    found: list[str] = []
    for path in sorted(TESTS.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        found += findings(path.read_text(encoding="utf-8"), rel)
    assert found == [], (
        f"a wall-clock bound under {FLOOR_S:g} s times the machine, not the code "
        f"(docs/PREVENTION.md P-014): {found}"
    )


def test_the_scan_catches_every_shape_of_a_tight_bound() -> None:
    """A planted example of each shape the scan reads — a direct difference, a named
    interval, a named bound, arithmetic over names, a mirrored and a chained comparison."""
    planted = """
import time
def test_a():
    t0 = time.monotonic()
    assert time.monotonic() - t0 < 2.0
def test_b():
    t0 = time.monotonic()
    elapsed = time.monotonic() - t0
    assert elapsed < 1.0, elapsed
def test_c():
    heartbeat_s = 1.0
    t0 = time.perf_counter()
    elapsed = time.perf_counter() - t0
    assert elapsed < heartbeat_s
def test_d():
    heartbeat_s = 1.0
    t0 = time.time()
    assert 3 * heartbeat_s > time.time() - t0
def test_e():
    t0 = time.monotonic()
    elapsed = time.monotonic() - t0
    assert 0.5 <= elapsed < 2.0
"""
    assert findings(planted, "planted") == [
        "planted:5",
        "planted:9",
        "planted:14",
        "planted:18",
        "planted:22",
    ]


def test_the_scan_leaves_generous_and_lower_bounds_alone() -> None:
    allowed = """
import time
def test_ok():
    t0 = time.monotonic()
    elapsed = time.monotonic() - t0
    assert 0.5 <= elapsed < 5.0
    assert elapsed >= 0.1
    assert time.monotonic() - t0 < 30
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        pass
"""
    assert findings(allowed) == []
