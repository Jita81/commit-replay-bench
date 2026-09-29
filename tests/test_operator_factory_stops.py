"""OPERATOR §8 names every factory stop the code can reach, each with a way forward (G-978).

The factory stops an item with a status word (``crb.factory.loop``), the delivery preflight
refuses with a reason code (``routes/factory.py``), the route gate withholds a delivery
(``delivery.withheld``) and a fetch that cannot fast-forward refuses the run
(``FetchRefused``). The guide had a numbered section for the test author and one for intake,
but no table an operator could read a stopped run against. §8 now carries a **Factory stop
conditions** table modelled on the intake one, and the Factory screen's About links to it.

Navigation
----------
What it is:   A drift gate between the factory's stop words in the code and OPERATOR §8's
              "Factory stop conditions" table, plus the Factory About's link to it.
What it does: Imports the stop words from ``crb.factory.loop`` (the entry gate's, the
              licence's, readiness and delivery), ``delivery.withheld`` from the metrics
              module's delivery vocabulary, ``read_only`` from the delivery preflight's
              reason codes and ``FetchRefused`` from the worker; parses the §8 table; asserts
              every word is a code span in a row whose cause and way-forward cells are both
              filled, and that ``ui/src/help/help.ts`` gives the ``/factory`` screen a
              ``readMore`` to ``OPERATOR#8-stop-conditions``.
How:          ``re`` over the Markdown between the table's lead and the next blank-line
              paragraph; ``re`` over help.ts's ``/factory`` entry.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (the entry gate's stops)
Works with:   docs/OPERATOR.md#8-stop-conditions (under test), src/crb/factory/loop.py (the
              status words), src/crb/server/routes/factory.py (``DeliveryPreflightOut``'s
              reason codes), src/crb/server/worker.py (``FetchRefused``),
              src/crb/observability/metrics.py (``DELIVERY_OUTCOMES``), ui/src/help/help.ts
              (the ``/factory`` readMore), docs/dod/pages/factory.md (factory.operations.16),
              docs/dod/journeys/manufacture.md (manufacture.operations.10)
Tested by:    (this is a test file)
Touch when:   never for a new repository; a stop word is added to the loop or a reason code to
              the preflight — write its row in OPERATOR §8 first; this test names the missing one.
"""

from __future__ import annotations

import re
from pathlib import Path

from crb.factory import loop
from crb.observability.metrics import DELIVERY_OUTCOMES
from crb.server.worker import FetchRefused

ROOT = Path(__file__).resolve().parent.parent
OPERATOR = ROOT / "docs" / "OPERATOR.md"
HELP = ROOT / "ui" / "src" / "help" / "help.ts"
FACTORY_ROUTES = ROOT / "src" / "crb" / "server" / "routes" / "factory.py"

#: The stop words the loop can end an item with that are the OPERATOR's to act on (a
#: ``not_clean`` or ``rejected`` item is the review's verdict, not an operating stop).
LOOP_STOPS: tuple[str, ...] = (
    loop.STATUS_NOT_READY,
    loop.STATUS_DELIVERY_FAILED,
    loop.STATUS_UNSIGNED_CELL,
    loop.STATUS_NO_PROVEN_STANDARD,
    loop.STATUS_NEEDS_CONTEXT,
    loop.STATUS_GRANULARIZE,
    loop.STATUS_NOT_LICENSED,
    loop.STATUS_SIZE_EXCEEDS_LICENCE,
    loop.STATUS_CELL_NOT_LICENSED,
    loop.STATUS_CALIBRATION_BUILD,
    loop.STATUS_ORACLE_NEEDS_STRENGTHENING,
    loop.STATUS_ORACLE_NOT_SCOREABLE,
)


def _section_8() -> str:
    text = OPERATOR.read_text(encoding="utf-8")
    return text.split("\n## 8. Stop conditions", 1)[1].split("\n## ", 1)[0]


def _factory_table() -> list[list[str]]:
    """The rows of the ``**Factory stop conditions**`` table: the first table after the lead."""
    section = _section_8()
    assert "**Factory stop conditions**" in section, "OPERATOR §8 has no factory table"
    after = section.split("**Factory stop conditions**", 1)[1]
    rows = []
    for line in after.split("\n"):
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells and not all(set(c) <= set(":-") for c in cells):
                rows.append(cells)
        elif rows:
            break  # the table ended
    return rows[1:]  # drop the header


def _preflight_reason_codes() -> set[str]:
    """Every ``reason_code = "…"`` the delivery preflight can answer with."""
    return set(re.findall(r'reason_code = "(\w+)"', FACTORY_ROUTES.read_text(encoding="utf-8")))


def test_section_8_names_every_factory_stop_the_code_can_reach_with_a_way_forward() -> None:
    rows = _factory_table()
    assert rows, "the factory table has no rows"
    assert all(len(r) == 3 for r in rows), [r for r in rows if len(r) != 3]
    by_code: dict[str, list[str]] = {}
    for cells in rows:
        for code in re.findall(r"`([^`]+)`", cells[0]):
            by_code[code] = cells
    preflight = _preflight_reason_codes()
    assert "read_only" in preflight, preflight
    expected = {
        *LOOP_STOPS,
        "delivery.withheld",
        "read_only",
        FetchRefused.__name__,
    }
    assert "delivery.withheld" in DELIVERY_OUTCOMES  # the route gate's event, as metered
    missing = sorted(code for code in expected if code not in by_code)
    assert not missing, f"OPERATOR §8's factory table does not name {missing}"
    for code in sorted(expected):
        cause, forward = by_code[code][1], by_code[code][2]
        assert len(cause) >= 20, f"{code}: the cause cell is too thin: {cause!r}"
        assert len(forward) >= 20, f"{code}: the way-forward cell is too thin: {forward!r}"
    # the lead points at where the factory is explained, not at a numbered section of its own
    lead = _section_8().split("**Factory stop conditions**", 1)[1].split("\n|", 1)[0]
    for anchor in (
        "ONBOARDING-A-REPO.md#step-8",
        "#10-the-factorys-test-author",
        "#11-intake",
        "GITHUB-APP.md#5-what-happens-at-clone-and-at-delivery",
    ):
        assert anchor in lead, f"the table's lead does not point at {anchor}"


def test_the_factory_screen_links_to_the_stop_conditions() -> None:
    """The Factory About's read-more carries the anchor (help.ts: the ``/factory`` entry)."""
    text = HELP.read_text(encoding="utf-8")
    entry = text.split("route: '/factory',", 1)[1].split("route: '", 1)[0]
    assert "to: 'OPERATOR#8-stop-conditions'" in entry, "the /factory readMore lacks §8"
    assert "label: 'Factory stop conditions'" in entry
