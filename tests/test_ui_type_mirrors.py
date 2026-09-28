"""The UI types that mirror an API response whole carry every field the API serves.

Navigation
----------
What it is:   A ratchet between ``src/crb/server/schemas.py`` and ``ui/src/api/types.ts``.
What it does: For each registered pair (``MIRRORS``) — a response whose every part a screen
              reads to tell the reader what holds and what failed — pins that the TypeScript
              interface names exactly the pydantic model's fields. A field the API adds fails
              here until the UI type carries it and a person decides how the screens show
              it (P-243: ``/ledger/verify`` began to fail on the audit trail's chain through
              ``ok``, the UI type had no ``events`` and the Ledger page reported the break
              as the grade chain's, "broken at row ?").
How:          Reads the model's ``model_fields`` and the interface's top-level field names
              from ``types.ts`` (a two-space-indented ``name:`` or ``name?:`` line inside
              ``export interface <Name> {``).
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0029-the-audit-trail-is-hash-chained.md
Works with:   src/crb/server/schemas.py (the models), ui/src/api/types.ts (the interfaces),
              ui/src/screens/Ledger/LedgerPage.tsx and ui/src/screens/Posture/PosturePage.tsx
              (the screens that read ``LedgerVerify``)
Tested by:    tests/test_ui_type_mirrors.py
Touch when:   a screen starts to read a response whole (register it), or a registered model
              gains or loses a field (change the interface and the screens with it).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from crb.server import schemas

TYPES = Path(__file__).resolve().parent.parent / "ui" / "src" / "api" / "types.ts"

#: pydantic model → the TypeScript interface that mirrors it field for field.
MIRRORS: dict[str, str] = {
    "LedgerVerifyOut": "LedgerVerify",
    "EventsVerifyOut": "EventsVerify",
    "AdequacyPolicyOut": "AdequacyPolicy",
    "RoutingPolicyOut": "RoutingPolicy",
    "RunFactoryOut": "RunFactory",
    "StepEventOut": "StepEvent",
}


def interface_fields(source: str, name: str) -> set[str]:
    m = re.search(
        rf"^export interface {name}(?: extends [^{{]+)? \{{\n(.*?)^\}}", source, re.S | re.M
    )
    assert m, f"ui/src/api/types.ts has no `export interface {name}`"
    return set(re.findall(r"^  (?:readonly )?(\w+)\??:", m.group(1), re.M))


@pytest.mark.parametrize(("model", "interface"), sorted(MIRRORS.items()))
def test_the_ui_type_names_every_field_the_api_serves(model: str, interface: str) -> None:
    served = set(getattr(schemas, model).model_fields)
    typed = interface_fields(TYPES.read_text(encoding="utf-8"), interface)
    assert served - typed == set(), f"{interface} lacks {sorted(served - typed)} ({model})"
    assert typed - served == set(), f"{interface} names {sorted(typed - served)} not in {model}"


def test_the_ratchet_reads_a_field_it_would_miss() -> None:
    """Not vacuous: an interface without one of the model's fields is reported."""
    source = "export interface LedgerVerify {\n  rows: number\n  ok: boolean\n}\n"
    assert interface_fields(source, "LedgerVerify") == {"rows", "ok"}
    assert "events" in set(schemas.LedgerVerifyOut.model_fields)
