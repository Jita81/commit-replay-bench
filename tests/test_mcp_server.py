"""crb.mcp — the MCP tools are the API under the API's RBAC; sign-offs are not tools.

Navigation
----------
What it is:   The MCP server's test suite — every tool called through ``MCPServer.call_tool``
              against the seeded app (FastAPI's ``TestClient`` is an ``httpx.Client``, so the
              server's HTTP client runs unchanged over the real routes).
What it does: Pins that the tools relay the API's JSON with its method fields intact
              (``n``, ``ci_low``, ``policy_thresholds``, apparatus); that a viewer account
              can read but not start a run and the refusal comes back as data, not a crash;
              that the CSRF double-submit header is carried on writes so an operator CAN
              start a run; that a missing credential is a readable error; that no tool can
              create a sign-off or a review; and that the instructions carry the claims
              policy the model must apply.
How:          ``make_env`` (tests/fixtures/server_seed.py) → ``CrbApi(env.client, prefix=
              API_PREFIX, username, password)`` → ``build_server`` → ``asyncio.run(
              server.call_tool(...))``; the structured content is the tool's return value.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0008-stdlib-core-and-downward-layers.md
Works with:   src/crb/mcp/server.py, src/crb/mcp/client.py (under test),
              tests/fixtures/server_seed.py (the seeded app and accounts),
              src/crb/server/routes/*.py (what the tools wrap)
Tested by:    tests/test_mcp_server.py
Touch when:   a tool is added (add it to ``EXPECTED_TOOLS`` and one call); the seed's cells
              change (the map assertions name the seeded cobra-like cell).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from crb.mcp import INSTRUCTIONS, CrbApi, CrbApiError, build_server, tool_names
from crb.server.app import API_PREFIX
from fixtures.server_seed import ALPHA, ROOT_PW, USER_PW, USERS, make_env

pytestmark = pytest.mark.timeout(120)

EXPECTED_TOOLS = {
    "crb_whoami",
    "crb_version",
    "crb_health",
    "crb_repos",
    "crb_repo",
    "crb_register_repo",
    "crb_update_repo",
    "crb_probe_repo",
    "crb_repo_profile",
    "crb_tasks",
    "crb_task",
    "crb_runs",
    "crb_run",
    "crb_run_tasks",
    "crb_run_events",
    "crb_start_run",
    "crb_cancel_run",
    "crb_grades",
    "crb_grade",
    "crb_evidence",
    "crb_grade_patch",
    "crb_capability_map",
    "crb_routes",
    "crb_failure_split",
    "crb_oracle",
    "crb_controls",
    "crb_remeasure_plan",
    "crb_strengthen_plan",
    "crb_refusals",
    "crb_forecast",
    "crb_ledger_verify",
    "crb_signoffs",
    "crb_signoff_policy",
    "crb_reviews",
    "crb_factory_backlog",
    "crb_factory_register_backlog",
    "crb_factory_tasks",
    "crb_factory_evidence",
}


def _api(env: Any, role: str = "admin") -> CrbApi:
    """A fresh, NOT-yet-logged-in client over the seeded app as ``role``'s local account.
    The env's client is logged in by the fixture; the MCP client must do its own login, so
    the fixture's cookies are cleared first."""
    env.client.cookies.clear()
    env.client.headers.pop("X-CSRF-Token", None)
    return CrbApi(
        env.client,
        prefix=API_PREFIX,
        username=USERS[role],
        password=ROOT_PW if role == "admin" else USER_PW,
    )


def call(server: Any, tool: str, **args: Any) -> Any:
    """Call one tool the way an MCP client does and decode what the client would see: the
    tools return ``Any``, which the SDK serialises as one JSON text content block."""
    result = asyncio.run(server.call_tool(tool, args))
    assert not result.is_error, result.content
    text = "".join(c.text for c in result.content)
    return json.loads(text)


def test_tool_set_and_no_signoff_or_review_creation(tmp_path: Path) -> None:
    with make_env(tmp_path) as env:
        server = build_server(_api(env))
        names = set(tool_names(server))
        assert names == EXPECTED_TOOLS
        # a model may READ attestations; it may never make one (EVIDENCE-AND-CLAIMS §2)
        assert not [
            n for n in names if "signoff" in n and n not in {"crb_signoffs", "crb_signoff_policy"}
        ]
        assert "crb_review" not in names and "crb_create_review" not in names
        for must in (
            "Wilson interval",
            "never means safe to merge",
            "cannot sign a cell off",
            "spends the operator's model budget",
        ):
            assert must in INSTRUCTIONS


def test_reads_relay_the_api_with_method_fields(tmp_path: Path) -> None:
    with make_env(tmp_path) as env:
        server = build_server(_api(env))
        who = call(server, "crb_whoami")
        assert who["role"] == "admin" and who["display_name"] == USERS["admin"]
        v = call(server, "crb_version")
        assert v["crb"] and v["apparatus"] and v["policy"] == "routing.v1"
        repos = call(server, "crb_repos")
        assert any(r["name"] == ALPHA for r in repos["items"])
        cmap = call(server, "crb_capability_map", repo=ALPHA)
        cell = next(c for c in cmap["cells"] if c["n"] > 0)
        # the method fields travel: n, interval, apparatus and the route with its reason
        for key in (
            "n",
            "n_tasks",
            "point",
            "ci_low",
            "ci_high",
            "false_q1",
            "route",
            "reason_code",
        ):
            assert key in cell, key
        assert cell["apparatus_versions"] and cell["belt_sets"]
        routes = call(server, "crb_routes", repo=ALPHA)
        assert routes["policy"]["version"] == "routing.v1"
        d = routes["decisions"][0]
        assert d["policy_version"] == "routing.v1" and d["policy_thresholds"]["min_n"] == 10
        verify = call(server, "crb_ledger_verify")
        assert verify["ok"] is True and verify["chain_ok"] is True and verify["false_q1_total"] == 0
        tasks = call(server, "crb_tasks", name=ALPHA, limit=5)
        assert tasks["total"] > 0 and len(tasks["items"]) <= 5
        grades = call(server, "crb_grades", repo=ALPHA, clean=True, limit=3)
        assert grades["items"] and all(g["clean"] for g in grades["items"])
        one = call(server, "crb_grade", row_id=grades["items"][0]["row_id"])
        assert one["row_hash"] == grades["items"][0]["row_hash"]
        assert call(server, "crb_signoff_policy")["policy_version"].startswith("signoff-policy")
        assert "items" in call(server, "crb_signoffs", repo=ALPHA)


def test_refusals_come_back_as_data_not_exceptions(tmp_path: Path) -> None:
    with make_env(tmp_path, role=None) as env:
        # a viewer may read the map but not start a run: the 403 is returned, not raised
        server = build_server(_api(env, "viewer"))
        assert call(server, "crb_capability_map", repo=ALPHA)["repo"] == ALPHA
        out = call(server, "crb_start_run", request={"repo": ALPHA, "kind": "mine"})
        assert out["error"] is True and out["status"] == 403 and out["code"] == "forbidden"
        assert out["detail"]["required"] == "operator"
        # an unknown repo is the API's 404, in the API's words
        missing = call(server, "crb_repo", name="nope")
        assert missing["error"] is True and missing["status"] == 404


def test_operator_can_start_and_cancel_a_run_with_csrf_carried(tmp_path: Path) -> None:
    with make_env(tmp_path, role=None) as env:
        server = build_server(_api(env, "operator"))
        # a POST needs the double-submit header; the client copies it from the cookie
        created = call(server, "crb_start_run", request={"repo": ALPHA, "kind": "mine"})
        assert created.get("error") in ("", None) and created["status"] == "queued", created
        got = call(server, "crb_run", run_id=created["id"])
        assert got["id"] == created["id"] and got["kind"] == "mine"
        cancelled = call(server, "crb_cancel_run", run_id=created["id"])
        assert cancelled["status"] in {"cancelled", "cancelling", "queued"}
        listed = call(server, "crb_runs", repo=ALPHA, kind="mine", limit=5)
        assert any(r["id"] == created["id"] for r in listed["items"])


def test_missing_credentials_and_bad_password_are_readable_errors(tmp_path: Path) -> None:
    with make_env(tmp_path, role=None) as env:
        env.client.cookies.clear()
        api = CrbApi(env.client, prefix=API_PREFIX)
        with pytest.raises(CrbApiError, match="CRB_MCP_USERNAME"):
            api.login()
        server = build_server(api)
        out = call(server, "crb_repos")
        assert out["error"] is True and out["code"] == "no_credentials"
        bad = CrbApi(
            env.client, prefix=API_PREFIX, username=USERS["viewer"], password="wrong-password-xx"
        )
        with pytest.raises(CrbApiError, match="invalid_credentials"):
            bad.login()


def test_from_env_reads_the_documented_variables() -> None:
    api = CrbApi.from_env(
        {
            "CRB_API_URL": "https://crb.example.org/api/v1/",
            "CRB_MCP_USERNAME": "svc-assistant",
            "CRB_MCP_PASSWORD": "x" * 16,
            "CRB_MCP_TIMEOUT_S": "5",
        }
    )
    try:
        assert str(api.client.base_url).rstrip("/") == "https://crb.example.org/api/v1"
        assert api.username == "svc-assistant" and not api.logged_in
        assert api.client.timeout.read == 5.0
        assert "x" * 16 not in repr(api) and "x" * 16 not in str(vars(api).get("username"))
    finally:
        api.close()


def test_cli_lists_the_tools_without_connecting(capsys: pytest.CaptureFixture[str]) -> None:
    from crb.cli.main import main

    assert main(["mcp", "--list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert set(listed) == EXPECTED_TOOLS
