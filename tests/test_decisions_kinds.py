"""The inbox's kinds are one list, on both sides of the wire (G-535, F6).

Navigation
----------
What it is:   A ratchet over ``src/crb/server/decisions.py`` and
              ``ui/src/screens/Decisions/decisions.ts``: the kinds, their order, their labels
              and the strengthening reasons.
What it does: Pins that the reasons a ``strengthen`` row is raised for are exactly
              ``crb.core.learn.STRENGTHEN_REASONS`` on the server AND in the screen's
              ``STRENGTHEN_REASONS`` literal; that every kind the server serves has the same rank
              in the screen's ``ORDER`` and a label in ``KIND_LABEL`` (a served row the screen
              could not name would render blank); and that the screen names no kind the server
              never serves.
How:          Reads the TypeScript source as text and parses the three literals; no build.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/server/decisions.py (``ORDER``, ``STRENGTHEN_KIND_REASONS``),
              src/crb/core/learn.py (``STRENGTHEN_REASONS``),
              ui/src/screens/Decisions/decisions.ts (``ORDER``, ``KIND_LABEL``,
              ``STRENGTHEN_REASONS``)
Tested by:    tests/test_decisions_kinds.py
Touch when:   never for a new repository; a human act is added to the product (a kind on both
              sides).
"""

from __future__ import annotations

import re
from pathlib import Path

from crb.core.learn import STRENGTHEN_REASONS
from crb.server import decisions as dec

TS = Path(__file__).resolve().parents[1] / "ui/src/screens/Decisions/decisions.ts"


def _block(src: str, head: str) -> str:
    """The text between ``head``'s opening brace or bracket and its matching close."""
    start = src.index(head)
    opener = min(i for i in (src.find("{", start), src.find("[", start)) if i != -1)
    close = "}" if src[opener] == "{" else "]"
    depth = 0
    for i in range(opener, len(src)):
        if src[i] == src[opener]:
            depth += 1
        elif src[i] == close:
            depth -= 1
            if depth == 0:
                return src[opener + 1 : i]
    raise AssertionError(f"{head} is not closed in {TS}")


def _record(src: str, head: str) -> dict[str, str]:
    return {
        k: v.strip() for k, v in re.findall(r"^\s*(\w+):\s*(.+?),?\s*$", _block(src, head), re.M)
    }


def test_the_inbox_strengthen_reasons_match_STRENGTHEN_REASONS() -> None:  # noqa: N802 — the constant's name
    """G-535: a held cell is a ``strengthen`` row exactly when the routing reason is one
    test-strengthening work can move. The server raises it for ``STRENGTHEN_REASONS``; the
    Results page's own fold reads the literal in ``decisions.ts``. Both must be the core tuple,
    in its order, or one surface would call a cell held that the other routes to a person."""
    src = TS.read_text(encoding="utf-8")
    literal = re.findall(r"'([a-z_]+)'", _block(src, "export const STRENGTHEN_REASONS"))
    assert tuple(literal) == STRENGTHEN_REASONS
    assert dec.STRENGTHEN_KIND_REASONS == STRENGTHEN_REASONS
    assert set(STRENGTHEN_REASONS) == {"oracle_weak", "controls_escapes", "controls_thin"}


def test_every_served_kind_has_the_screens_rank_and_a_label() -> None:
    """F6: the server derives and orders the rows; the screen labels and renders them. A kind
    the server serves with no ``KIND_LABEL`` would render an empty tag, and a rank that differs
    would sort the Results page's panel differently from the inbox."""
    src = TS.read_text(encoding="utf-8")
    order = {k: int(v) for k, v in _record(src, "export const ORDER").items()}
    labels = _record(src, "export const KIND_LABEL")
    assert order == dec.ORDER
    assert set(labels) == set(dec.ORDER)
    assert all(v.strip("'") for v in labels.values())
