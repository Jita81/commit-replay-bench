"""No test module reads the calendar at import — a day boundary is read per test.

``tests/test_server_routes_golive.py`` computed ``YESTERDAY`` and ``TOMORROW`` once, when the
module was imported, so the whole suite carried the day its first test ran. A run that crossed
00:00 UTC then dated six attestations two days before the deployment's install (refused,
``invalid_attestation``) and its "future" day only one day ahead (accepted, so the refusal
test failed) — P-770. The fix reads the day inside each test; this test makes that shape the
rule for every test module: a module-level assignment whose value calls a clock
(``datetime.now``, ``date.today``, ``utcnow``) is refused, wherever the module keeps it.

Navigation
----------
What it is:   The ratchet over the calendar clock in ``tests/``: no module-level constant may be
              computed from the current date or time.
What it does: Parses every ``tests/**/*.py``, walks each module-level assignment for a call to
              ``now``, ``today`` or ``utcnow``, and fails naming every file and line it finds.
How:          ``ast.parse`` + ``ast.walk`` over ``Assign``/``AnnAssign`` statements in
              ``Module.body``; a call inside a function or fixture body is not module-level.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   tests/test_server_routes_golive.py (the module that carried the constants, now
              ``day()``), src/crb/server/golive.py (``_check_day``: the one-day bounds a stale
              day falls outside), docs/PREVENTION.md (P-770)
Tested by:    (this is a test file)
Touch when:   never for a new repository; never — a test that needs a day reads it in its own
              body or from a fixture.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
#: The names a call must not have at module level: each reads the wall clock.
CLOCKS: frozenset[str] = frozenset({"now", "today", "utcnow"})


def module_level_clock_reads(source: str) -> list[int]:
    """The lines of the module-level assignments in ``source`` whose value calls a clock."""
    lines: list[int] = []
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                func = sub.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if name in CLOCKS:
                    lines.append(node.lineno)
                    break
    return lines


def test_the_reader_names_an_import_time_clock_and_passes_a_per_test_one() -> None:
    frozen = (
        "import datetime as _dt\n"
        "YESTERDAY = (_dt.datetime.now(_dt.UTC).date() - _dt.timedelta(days=1)).isoformat()\n"
        "TOMORROW: str = _dt.date.today().isoformat()\n"
        "def day(offset: int) -> str:\n"
        "    return (_dt.datetime.now(_dt.UTC).date() + _dt.timedelta(days=offset)).isoformat()\n"
    )
    assert module_level_clock_reads(frozen) == [2, 3]
    assert module_level_clock_reads("import time\n_T0 = 1_700_000_000\n") == []


def test_no_test_module_reads_the_clock_at_import() -> None:
    found = [
        f"{path.relative_to(ROOT)}:{line}"
        for path in sorted(TESTS.rglob("*.py"))
        for line in module_level_clock_reads(path.read_text(encoding="utf-8"))
    ]
    assert found == [], (
        "a module-level constant reads the clock at import, so a run that crosses midnight "
        f"carries a stale day (P-770); read it inside the test or a fixture: {found}"
    )
