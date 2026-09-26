"""Every "complete list" of what leaves the deployment names every outbound flow (P-103).

Navigation
----------
What it is:   The guard that keeps the three exhaustive egress statements in the operator's
              documents in step with each other and with the flows the product has.
What it does: Reads the tenant-boundary table in SECURITY.md, the deployment-shape invariant
              in DEPLOYMENT §1 and the air-gap outbound list in DEPLOYMENT §7, and fails when
              any of them omits a flow in ``FLOWS``; pins that the provisioning row says what
              a fetch sends and what it never sends.
How:          Slices each statement out of the Markdown by its opening words; a regular
              expression per flow.
Layer:        tests — docs/ARCHITECTURE.md#71-security
ADRs:         docs/adr/0019-qualification-is-posture-relative.md (the provisioning flow)
Works with:   docs/SECURITY.md (the boundary table), docs/DEPLOYMENT.md (§1 and §7),
              src/crb/provision/fetch.py (the fetch the provisioning row describes),
              docs/PREVENTION.md (row P-103)
Tested by:    tests/test_egress_inventory.py
Touch when:   the product gains or loses a flow that leaves the deployment — add it to
              ``FLOWS`` and to all three statements in the same change.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"

#: Every flow that can leave a deployment, and how each statement must name it.
FLOWS: dict[str, str] = {
    "model endpoint": r"model endpoint",
    "git remote": r"git remote|repository'?s? remote",
    "OIDC issuer": r"OIDC issuer",
    "tracker (intake)": r"tracker",
    "package mirror or registry (provisioning)": r"package mirror|package registr",
}


def _slice(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i : text.index(end, i + len(start))]


def _statements() -> dict[str, str]:
    security = (DOCS / "SECURITY.md").read_text(encoding="utf-8")
    deployment = (DOCS / "DEPLOYMENT.md").read_text(encoding="utf-8")
    return {
        "SECURITY.md boundary table": _slice(
            security, "**What crosses the tenant boundary", "The intake flow is the only one"
        ),
        "DEPLOYMENT.md §1 invariant": _slice(
            deployment, "Both enforce the same invariants", "\n\n"
        ),
        "DEPLOYMENT.md §7 outbound list": _slice(
            deployment, "The complete outbound list is", "\n\n"
        ),
    }


@pytest.mark.parametrize("where", sorted(_statements()))
def test_every_complete_egress_list_names_every_flow(where: str) -> None:
    text = " ".join(_statements()[where].split())
    missing = [name for name, rx in FLOWS.items() if not re.search(rx, text, re.IGNORECASE)]
    assert missing == [], f"{where} omits {missing}"


def test_the_provisioning_row_says_what_a_fetch_sends_and_never_sends() -> None:
    table = _statements()["SECURITY.md boundary table"]
    row = next(line for line in table.splitlines() if line.startswith("| Dependency provisioning"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert len(cells) == 4, row
    flow, endpoint, sent, never = cells
    assert "off by default" in flow and "CRB_PROVISION__" in endpoint
    assert "names and versions" in sent and "go.sum" in sent
    assert "source code" in never and "credential" in never
