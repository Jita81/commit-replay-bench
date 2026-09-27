"""Every "complete list" of what leaves the deployment names every outbound flow (P-103).

Navigation
----------
What it is:   The guard that keeps the three exhaustive egress statements in the operator's
              documents in step with each other, with the flows the product has, and with
              every setting that points the product at an address outside the deployment.
What it does: Discovers every endpoint-shaped setting (the ``Settings`` model walked field by
              field, plus every ``CRB_…`` / ``AZURE_OPENAI_…`` endpoint name a source file
              reads) and fails when one belongs to no flow in ``FLOWS`` and is not listed in
              ``NOT_EGRESS`` with its reason; fails when the SECURITY.md boundary table's
              rows and ``FLOWS`` are not one to one, when a flow's row does not name the
              settings that point it, or when the table, DEPLOYMENT §1 or DEPLOYMENT §7
              omits a flow; pins that the provisioning row says what a fetch sends and what
              it never sends.
How:          ``pydantic`` field walk plus a regular expression over ``src/crb``; the
              statements are sliced out of the Markdown by their opening words; a regular
              expression per flow.
Layer:        tests — docs/ARCHITECTURE.md#71-security
ADRs:         docs/adr/0019-qualification-is-posture-relative.md (the provisioning flow),
              docs/adr/0014-github-app-is-the-connection.md (the GitHub API flow)
Works with:   docs/SECURITY.md (the boundary table), docs/DEPLOYMENT.md (§1 and §7),
              src/crb/server/settings.py (``Settings``, the walked model),
              src/crb/provision/fetch.py (the fetch the provisioning row describes),
              docs/PREVENTION.md (row P-103)
Tested by:    tests/test_egress_inventory.py
Touch when:   the product gains or loses a flow that leaves the deployment, or a setting
              that points at an address — the discovery test fails until the setting has a
              flow (and that flow a row in all three statements) or a ``NOT_EGRESS`` reason.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import BaseModel

from crb.server.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SRC = ROOT / "src" / "crb"


@dataclass(frozen=True)
class Flow:
    #: how the flow's row in the SECURITY.md boundary table begins
    row: str
    #: how each of the three complete lists must name the flow
    rx: str
    #: every setting that points the flow at an address; the row must name each one
    endpoints: tuple[str, ...]


#: Every flow that can leave a deployment.
FLOWS: dict[str, Flow] = {
    "model endpoint": Flow(
        "Builder / labeller / reviewer calls",
        r"model endpoint",
        (
            "CRB_OPENAI_BASE_URL",
            "CRB_AZURE_ENDPOINT",
            "AZURE_OPENAI_ENDPOINT",
            "CRB_BUILDER__ALLOW_HOSTS",
        ),
    ),
    # the address is the repository row's ``repos.url``, a column, not a setting
    "git remote": Flow("Repository clone and fetch", r"git remote|repository'?s? remote", ()),
    "GitHub API": Flow("GitHub API", r"GitHub API", ("CRB_GITHUB__API_URL",)),
    "OIDC issuer": Flow("Sign-in", r"OIDC issuer", ("CRB_OIDC__ISSUER",)),
    "tracker (intake)": Flow("Intake", r"tracker", ("CRB_INTAKE__URL",)),
    "package mirror or registry (provisioning)": Flow(
        "Dependency provisioning",
        r"package mirror|package registr",
        (
            "CRB_PROVISION__GO_PROXY",
            "CRB_PROVISION__GO_SUMDB",
            "CRB_PROVISION__PYPI_INDEX",
            "CRB_PROVISION__PYPI_FILES_HOST",
            "CRB_PROVISION__NPM_REGISTRY",
            "CRB_PROVISION__EXTRA_ALLOW_HOSTS",
        ),
    ),
    "image registry": Flow(
        "Container images",
        r"image registr",
        (
            "CRB_SANDBOX__IMAGE",
            "CRB_SANDBOX_IMAGE",
            "CRB_BUILDER__IMAGE",
            "CRB_BUILDER__PROXY_IMAGE",
            "CRB_PROVISION__PROXY_IMAGE",
            "CRB_PROVISION__GO_IMAGE",
            "CRB_PROVISION__PYTHON_IMAGE",
            "CRB_PROVISION__NODE_IMAGE",
        ),
    ),
}

#: Endpoint-shaped settings that do NOT send anything out of the deployment, and why.
NOT_EGRESS: dict[str, str] = {
    "CRB_BIND_HOST": "the address the API listens on (inbound)",
    "CRB_METRICS_HOST": "the address the worker's metrics listener binds (inbound)",
    "CRB_DATABASE_URL": "the deployment's own database",
    "CRB_PUBLIC_URL": "the deployment's own address, used to build links",
    "CRB_API_URL": "the MCP client's address for this deployment's own API",
    "CRB_OIDC__REDIRECT_URL": "the deployment's own callback; the browser returns to it",
    "CRB_GITHUB__WEB_URL": "a link the admin's browser follows to install the app; "
    "the product never calls it",
}

#: The last word of a setting that holds an address or an image reference.
_SHAPE = r"(?:URL|ENDPOINT|ISSUER|HOSTS?|REGISTRY|INDEX|PROXY|SUMDB|IMAGE)"
_SOURCE_NAME = re.compile(rf'"((?:CRB|AZURE_OPENAI|OPENAI|ANTHROPIC)_[A-Z0-9_]*{_SHAPE})"')


def _model_names(model: type[BaseModel], prefix: str) -> Iterator[str]:
    for name, field in model.model_fields.items():
        env = f"{prefix}{name.upper()}"
        ann = field.annotation
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            yield from _model_names(ann, f"{env}__")
        elif re.search(rf"{_SHAPE}$", env):
            yield env


def _discovered() -> set[str]:
    names = set(_model_names(Settings, "CRB_"))
    for path in SRC.rglob("*.py"):
        names |= set(_SOURCE_NAME.findall(path.read_text(encoding="utf-8")))
    return names


def _declared() -> set[str]:
    return {e for f in FLOWS.values() for e in f.endpoints} | set(NOT_EGRESS)


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


def _table_rows() -> list[list[str]]:
    table = _statements()["SECURITY.md boundary table"]
    rows = [line for line in table.splitlines() if line.startswith("| ")]
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    return [c for c in cells if c[0] != "Flow"]  # drop the header row


def test_every_endpoint_setting_belongs_to_a_flow_or_says_why_it_is_not_egress() -> None:
    unclaimed = sorted(_discovered() - _declared())
    assert unclaimed == [], (
        f"{unclaimed} point at an address but belong to no flow in FLOWS and are not in "
        "NOT_EGRESS: add each to its flow (and the flow to SECURITY.md, DEPLOYMENT §1 and §7) "
        "or to NOT_EGRESS with the reason nothing leaves the deployment"
    )


def test_no_declared_endpoint_is_stale() -> None:
    stale = sorted(_declared() - _discovered())
    assert stale == [], f"{stale} are declared here but no longer read by the product"


def test_the_boundary_table_has_exactly_one_row_per_flow() -> None:
    firsts = [row[0] for row in _table_rows()]
    for first in firsts:
        owners = [k for k, f in FLOWS.items() if first.startswith(f.row)]
        assert len(owners) == 1, f"table row {first!r} matches {owners} in FLOWS, not one"
    for key, flow in FLOWS.items():
        rows = [first for first in firsts if first.startswith(flow.row)]
        assert len(rows) == 1, f"FLOWS[{key!r}] has {len(rows)} rows in the table, not one"


def _names(cell: str, env: str) -> bool:
    if env in cell:
        return True
    section, sep, leaf = env.rpartition("__")
    return bool(sep) and f"{section}__" in cell and re.search(rf"\b{leaf}\b", cell) is not None


@pytest.mark.parametrize("key", sorted(FLOWS))
def test_each_flow_row_names_the_settings_that_point_it(key: str) -> None:
    flow = FLOWS[key]
    row = next(r for r in _table_rows() if r[0].startswith(flow.row))
    endpoint_cell = row[1]
    missing = [e for e in flow.endpoints if not _names(endpoint_cell, e)]
    assert missing == [], f"the {flow.row!r} row's endpoint cell does not name {missing}"


@pytest.mark.parametrize("where", sorted(_statements()))
def test_every_complete_egress_list_names_every_flow(where: str) -> None:
    text = " ".join(_statements()[where].split())
    missing = [k for k, f in FLOWS.items() if not re.search(f.rx, text, re.IGNORECASE)]
    assert missing == [], f"{where} omits {missing}"


def test_the_provisioning_row_says_what_a_fetch_sends_and_never_sends() -> None:
    row = next(r for r in _table_rows() if r[0].startswith("Dependency provisioning"))
    assert len(row) == 4, row
    flow, endpoint, sent, never = row
    assert "off by default" in flow and "CRB_PROVISION__" in endpoint
    assert "names and versions" in sent and "go.sum" in sent
    assert "source code" in never and "credential" in never
