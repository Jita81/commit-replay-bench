"""The crb MCP server — the instrument's API as Model Context Protocol tools.

Navigation
----------
What it is:   ``build_server(api)`` returns an ``MCPServer`` whose tools are one-line
              pass-throughs to ``/api/v1``: repositories, tasks, runs, evidence, the
              capability map and routes, the oracle and controls, the ledger, sign-offs
              (read), the factory. ``main()`` runs it on stdio so Claude Code (or any MCP
              client) can drive a crb deployment: ``claude mcp add crb -- crb mcp``.
What it does: Lets an assistant *read the instrument* and *start measurements* under the
              same RBAC the UI has (the tools act as the local account the operator
              configured — a viewer can only read; starting a run needs operator). Two
              things are deliberately NOT tools: creating a sign-off, and creating a review
              — those are a human's attestation anchored to the diff bytes, and a model
              calling them would be exactly the "AI opinion of AI work" the product refuses
              (docs/EVIDENCE-AND-CLAIMS.md §2). The server's ``instructions`` carry the
              claims policy so a model quoting a number carries its ``n``, interval, mode
              and apparatus.
How:          ``mcp`` 2.x ``MCPServer``; each tool calls ``CrbApi`` and returns the API's
              JSON unchanged (an ``CrbApiError`` becomes ``{"error": true, code, message,
              detail}`` so the client reads the refusal instead of a stack trace). Read tools
              are annotated ``read_only_hint``; ``crb_start_run`` is annotated as
              non-idempotent because it spends the operator's model budget.
Layer:        mcp — docs/ARCHITECTURE.md#44-outer-layers (an outer surface beside the CLI;
              a client of the server layer over HTTP, never an importer of it)
ADRs:         docs/adr/0008-stdlib-core-and-downward-layers.md,
              docs/adr/0013-external-review-is-advisory-and-recorded.md (the same principle:
              a model's reading is advisory; the ledger is the record)
Works with:   src/crb/mcp/client.py (auth, CSRF, errors), src/crb/cli/commands/service.py
              (``crb mcp``), docs/MCP.md (operator setup, the tool list, the two omissions),
              docs/API.md (every tool names the route it wraps), src/crb/server/routes/*.py
              (the routes)
Tested by:    tests/test_mcp_server.py — every tool called through ``MCPServer.call_tool``
              against the seeded app: RBAC refusals surface as errors, the sign-off tools do
              not exist, the instructions carry the claims policy
Touch when:   a route is added that an assistant should reach (one function, one line);
              never for a new repository.
Claims:       none of its own — it relays the API's numbers with their method fields.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

import httpx

from crb.core.version import APPARATUS_VERSION, __version__
from crb.mcp.client import CrbApi, CrbApiError
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

#: What a model driving the instrument must know before it quotes a number. Mirrors
#: docs/EVIDENCE-AND-CLAIMS.md §3 and §7 and README "What it is not".
INSTRUCTIONS = f"""Commit Replay Bench (crb {__version__}, apparatus {APPARATUS_VERSION}) — an \
instrument that replays a repository's real commits, grades an AI builder against the \
repository's own held-out tests under mechanical belts, records every verdict in an \
append-only hash-chained ledger and routes each (class x size) cell under one published rule.

Claims policy — apply it to everything you say from these tools:
- Every rate carries its n, its Wilson interval, the mode (sighted/blind), the builder+model \
and the apparatus version. A rate without them is not a claim.
- `clean` is a mechanical result (the suite passed under the belts), not proof of semantic \
correctness. `deliver` on a cell means the factory MAY open a branch and a pull request for \
that class of change in that repository under human review; it never means safe to merge \
or deploy.
- Sighted and blind rows are different measurements; never pool them. Rows from different \
apparatus versions are never blended.
- A cell is a statement about one repository; it says nothing about a cell that was not \
measured. Never extrapolate a small-n result.
- Hash-chained means unaltered since it was written, not verified true.
- You cannot sign a cell off or file a review through these tools: those are a human's \
attestations. Point the operator at the UI or `crb` CLI for them.
- Starting a run spends the operator's model budget; say so before you do it, and prefer \
the smallest run that answers the question (task_ids, limit)."""

READ = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, idempotent_hint=False, open_world_hint=False)
SPENDS = ToolAnnotations(
    title="Starts a measurement (spends model budget)",
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=True,
)


def _safe(fn: Callable[[], Any]) -> Any:
    """Run a call; an API refusal comes back as data the model can read and act on."""
    try:
        return fn()
    except CrbApiError as e:
        return e.to_dict()


def build_server(api: CrbApi) -> MCPServer[Any]:
    """The server with every tool bound to ``api``."""
    s: MCPServer[Any] = MCPServer(
        name="crb",
        title="Commit Replay Bench",
        instructions=INSTRUCTIONS,
        version=__version__,
    )

    # --- the instrument ------------------------------------------------------------
    @s.tool(
        annotations=READ,
        description="Who the tools act as (username, role) — the RBAC every tool is under.",
    )
    def crb_whoami() -> Any:
        return _safe(api.me)

    @s.tool(
        annotations=READ,
        description="Package, apparatus and routing-policy versions of the deployment (GET /version).",
    )
    def crb_version() -> Any:
        return _safe(lambda: api.get("/version"))

    @s.tool(
        annotations=READ,
        description="Health probes: db, append-only triggers, ledger false-Q1, sandbox, toolchains, builders, worker (GET /health).",
    )
    def crb_health() -> Any:
        return _safe(lambda: api.get("/health"))

    # --- repositories and tasks --------------------------------------------------------
    @s.tool(
        annotations=READ,
        description="The registered repositories with their config and probe/profile stamps (GET /repos).",
    )
    def crb_repos() -> Any:
        return _safe(lambda: api.get("/repos"))

    @s.tool(
        annotations=READ,
        description="One repository's config, counts and stamps (GET /repos/{name}).",
    )
    def crb_repo(name: str) -> Any:
        return _safe(lambda: api.get(f"/repos/{name}"))

    @s.tool(
        annotations=WRITE,
        description="Register a repository (POST /repos; operator). Fields as docs/ONBOARDING-A-REPO.md: name, language, clone_path or url, runner, src_prefix, test_prefix, ext, test_mode, test_suffix, belt_scope, probe, layer, runner_opts, sandbox_image, mining.",
    )
    def crb_register_repo(config: dict[str, Any]) -> Any:
        return _safe(lambda: api.post("/repos", json=config))

    @s.tool(
        annotations=WRITE,
        description="Update a repository's config (PUT /repos/{name}; operator) — same fields as registration.",
    )
    def crb_update_repo(name: str, config: dict[str, Any]) -> Any:
        return _safe(lambda: api.put(f"/repos/{name}", json=config))

    @s.tool(
        annotations=WRITE,
        description="Queue a probe of the repository's toolchain and runner (POST /repos/{name}/probe; operator).",
    )
    def crb_probe_repo(name: str) -> Any:
        return _safe(lambda: api.post(f"/repos/{name}/probe"))

    @s.tool(
        annotations=READ,
        description="The repository's change profile: class x size histogram of recent history (GET /repos/{name}/profile). refresh needs operator.",
    )
    def crb_repo_profile(name: str, refresh: bool = False, log_n: int = 0) -> Any:
        return _safe(
            lambda: api.get(f"/repos/{name}/profile", refresh=refresh or None, log_n=log_n or None)
        )

    @s.tool(
        annotations=READ,
        description="Mined tasks: pool, size, class, gold status (GET /repos/{name}/tasks). Filters: pool (standard|hard), size (XS..XL), capability_class, gold_clean.",
    )
    def crb_tasks(
        name: str,
        *,
        pool: str | None = None,
        size: str | None = None,
        capability_class: str | None = None,
        gold_clean: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Any:
        return _safe(
            lambda: api.get(
                f"/repos/{name}/tasks",
                pool=pool,
                size=size,
                capability_class=capability_class,
                gold_clean=gold_clean,
                limit=limit,
                offset=offset,
            )
        )

    @s.tool(
        annotations=READ,
        description="One task's spec and grade history (GET /tasks/{repo}/{task_id}).",
    )
    def crb_task(repo: str, task_id: str) -> Any:
        return _safe(lambda: api.get(f"/tasks/{repo}/{task_id}"))

    # --- runs ---------------------------------------------------------------------------
    @s.tool(
        annotations=READ,
        description="Runs, newest first (GET /runs). Filters: repo, kind (mine|replay|blind|oracle|controls|probe|label|factory), status (queued|running|succeeded|failed|cancelled).",
    )
    def crb_runs(
        repo: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Any:
        return _safe(
            lambda: api.get(
                "/runs", repo=repo, kind=kind, status=status, limit=limit, offset=offset
            )
        )

    @s.tool(
        annotations=READ,
        description="One run: status, counts, apparatus stamp, error (GET /runs/{run_id}).",
    )
    def crb_run(run_id: str) -> Any:
        return _safe(lambda: api.get(f"/runs/{run_id}"))

    @s.tool(
        annotations=READ,
        description="A run's per-task rows: belts, clean, failure kind, cost, latency (GET /runs/{run_id}/tasks).",
    )
    def crb_run_tasks(run_id: str, limit: int = 100, offset: int = 0) -> Any:
        return _safe(lambda: api.get(f"/runs/{run_id}/tasks", limit=limit, offset=offset))

    @s.tool(
        annotations=READ,
        description="A run's event log after a sequence number (GET /runs/{run_id}/events/log) — progress, refusals, outages.",
    )
    def crb_run_events(run_id: str, after: int = 0, limit: int = 200) -> Any:
        return _safe(lambda: api.get(f"/runs/{run_id}/events/log", after=after, limit=limit))

    @s.tool(
        annotations=SPENDS,
        description=(
            "Start a run (POST /runs; operator). SPENDS the operator's model budget for replay/blind/factory kinds — say so first and keep it small "
            "(task_ids or limit). Body as docs/API.md: repo, kind (mine|replay|blind|oracle|controls|probe|label|factory), mode (sighted|blind), builder, model, provider, "
            "ladder [{builder, model, provider, ...}], budget, task_ids, limit, pool, executor, timeout, builder_config, preflight, outage_stop, retain; factory: deliver, deliver_override (approver), max_rework."
        ),
    )
    def crb_start_run(request: dict[str, Any]) -> Any:
        return _safe(lambda: api.post("/runs", json=request))

    @s.tool(
        annotations=WRITE,
        description="Ask a queued or running run to stop (POST /runs/{run_id}/cancel; operator). Rows already graded stay on the ledger.",
    )
    def crb_cancel_run(run_id: str) -> Any:
        return _safe(lambda: api.post(f"/runs/{run_id}/cancel"))

    # --- grades and evidence --------------------------------------------------------------
    @s.tool(
        annotations=READ,
        description="Ledger rows (GET /grades). Filters: repo, run_id, task_id, clean, mode, builder, model, provider, capability_class, size, language, pool, process_step, belt_set, disqualified.",
    )
    def crb_grades(
        *,
        repo: str | None = None,
        run_id: str | None = None,
        task_id: str | None = None,
        clean: bool | None = None,
        mode: str | None = None,
        builder: str | None = None,
        model: str | None = None,
        capability_class: str | None = None,
        size: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Any:
        return _safe(
            lambda: api.get(
                "/grades",
                repo=repo,
                run_id=run_id,
                task_id=task_id,
                clean=clean,
                mode=mode,
                builder=builder,
                model=model,
                capability_class=capability_class,
                size=size,
                limit=limit,
                offset=offset,
            )
        )

    @s.tool(
        annotations=READ,
        description="One ledger row by id, with its belts, hashes and evidence pack hash (GET /grades/{row_id}).",
    )
    def crb_grade(row_id: str) -> Any:
        return _safe(lambda: api.get(f"/grades/{row_id}"))

    @s.tool(
        annotations=READ,
        description="An evidence pack by hash: spec, belts, redacted test output, diff stats, builder ref, apparatus (GET /evidence/{pack_hash}).",
    )
    def crb_evidence(pack_hash: str) -> Any:
        return _safe(lambda: api.get(f"/evidence/{pack_hash}"))

    @s.tool(
        annotations=READ,
        description="The patch a graded attempt produced, when retained (GET /grades/{row_hash}/patch).",
    )
    def crb_grade_patch(row_hash: str) -> Any:
        return _safe(lambda: api.get(f"/grades/{row_hash}/patch"))

    # --- the map, the routes, the oracle ---------------------------------------------------
    @s.tool(
        annotations=READ,
        description="The capability map (GET /capability-map): cells with n, n_tasks, point, Wilson interval, false-Q1, oracle strength, controls, route + reason. by = class,size (default) or a comma list of cell fields; apparatus = current (default) or all.",
    )
    def crb_capability_map(repo: str, by: str | None = None, apparatus: str = "current") -> Any:
        return _safe(lambda: api.get("/capability-map", repo=repo, by=by, apparatus=apparatus))

    @s.tool(
        annotations=READ,
        description="Route decisions per cell with the evidence and the policy (version AND thresholds) each was decided under (GET /routes).",
    )
    def crb_routes(repo: str, by: str | None = None, apparatus: str = "current") -> Any:
        return _safe(lambda: api.get("/routes", repo=repo, by=by, apparatus=apparatus))

    @s.tool(
        annotations=READ,
        description="Non-clean rows split by failure kind — builder_red, lint, budget, protocol, harness, outage, disqualified (GET /failure-split).",
    )
    def crb_failure_split(repo: str, run_id: str = "") -> Any:
        return _safe(lambda: api.get("/failure-split", repo=repo, run_id=run_id or None))

    @s.tool(
        annotations=READ,
        description="Oracle adequacy: per-task mutation strength and the repo's band (GET /oracle/{repo}).",
    )
    def crb_oracle(repo: str) -> Any:
        return _safe(lambda: api.get(f"/oracle/{repo}"))

    @s.tool(
        annotations=READ,
        description="The negative-controls verdict: rows, violations, escapes, not-constructible, passed (GET /oracle/{repo}/controls).",
    )
    def crb_controls(repo: str) -> Any:
        return _safe(lambda: api.get(f"/oracle/{repo}/controls"))

    # --- learning loop ----------------------------------------------------------------------
    @s.tool(
        annotations=READ,
        description="Which cells are stale on the current apparatus and what re-measuring them would cost (GET /learn/remeasure).",
    )
    def crb_remeasure_plan(repo: str) -> Any:
        return _safe(lambda: api.get("/learn/remeasure", repo=repo))

    @s.tool(
        annotations=READ,
        description="Cells that would move a route with more evidence, and the items that would strengthen them (GET /learn/strengthen).",
    )
    def crb_strengthen_plan(repo: str, by: str = "class_size", since: str = "") -> Any:
        return _safe(lambda: api.get("/learn/strengthen", repo=repo, by=by, since=since or None))

    @s.tool(
        annotations=READ,
        description="Refusals the instrument recorded for the repo (services, guards, disqualifications) (GET /learn/refusals).",
    )
    def crb_refusals(repo: str) -> Any:
        return _safe(lambda: api.get("/learn/refusals", repo=repo))

    @s.tool(
        annotations=READ,
        description="Cost/latency forecast for a change mix on the measured map (GET /forecast/build). mix = 'class:size=count,...'.",
    )
    def crb_forecast(repo: str, mix: str) -> Any:
        return _safe(lambda: api.get("/forecast/build", repo=repo, mix=mix))

    # --- ledger and sign-offs (read) ------------------------------------------------------------
    @s.tool(
        annotations=READ,
        description="Verify the ledger's hash chain and the false-Q1 invariant over every row (GET /ledger/verify).",
    )
    def crb_ledger_verify() -> Any:
        return _safe(lambda: api.get("/ledger/verify"))

    @s.tool(
        annotations=READ,
        description="Sign-offs on the repo's cells — who, when, under which policy, with what attestation (GET /signoffs). Creating one is a human act: not a tool.",
    )
    def crb_signoffs(repo: str | None = None, include_revoked: bool = False) -> Any:
        return _safe(lambda: api.get("/signoffs", repo=repo, include_revoked=include_revoked))

    @s.tool(annotations=READ, description="The sign-off policy in force (GET /signoffs/policy).")
    def crb_signoff_policy() -> Any:
        return _safe(lambda: api.get("/signoffs/policy"))

    @s.tool(
        annotations=READ,
        description="Human reviews of graded attempts, anchored to the diff bytes (GET /reviews). Filing one is a human act: not a tool.",
    )
    def crb_reviews(
        repo: str | None = None,
        task_id: str | None = None,
        verdict: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Any:
        return _safe(
            lambda: api.get(
                "/reviews", repo=repo, task_id=task_id, verdict=verdict, limit=limit, offset=offset
            )
        )

    # --- factory ---------------------------------------------------------------------------------
    @s.tool(
        annotations=READ,
        description="The active frozen backlog for the repo (GET /factory/{repo}/backlog).",
    )
    def crb_factory_backlog(repo: str) -> Any:
        return _safe(lambda: api.get(f"/factory/{repo}/backlog"))

    @s.tool(
        annotations=WRITE,
        description="Register (freeze) a backlog for the repo (POST /factory/{repo}/backlog; operator). items: [{id, title, kind, capability_class, size_estimate, structural_facts, ...}] as docs/API.md.",
    )
    def crb_factory_register_backlog(repo: str, backlog: dict[str, Any]) -> Any:
        return _safe(lambda: api.post(f"/factory/{repo}/backlog", json=backlog))

    @s.tool(
        annotations=READ,
        description="Factory items with their latest readiness, route, build, delivery and verdict (GET /factory/{repo}/tasks).",
    )
    def crb_factory_tasks(repo: str) -> Any:
        return _safe(lambda: api.get(f"/factory/{repo}/tasks"))

    @s.tool(
        annotations=READ,
        description="The factory evidence chain, verified on read (GET /factory/{repo}/evidence). item_id narrows it.",
    )
    def crb_factory_evidence(
        repo: str, item_id: str | None = None, limit: int = 200, offset: int = 0
    ) -> Any:
        return _safe(
            lambda: api.get(
                f"/factory/{repo}/evidence", item_id=item_id, limit=limit, offset=offset
            )
        )

    return s


def tool_names(server: MCPServer[Any]) -> list[str]:
    """The registered tool names (for the docs and the tests)."""

    async def _names() -> list[str]:
        return sorted(t.name for t in await server.list_tools())

    return asyncio.run(_names())


def main(environ: dict[str, str] | None = None) -> int:
    """``crb mcp`` — stdio transport; the credentials from the environment (docs/MCP.md)."""
    # stdout is the protocol channel; keep httpx's per-request INFO lines off stderr too so
    # a client's log pane shows refusals and crashes, not every GET
    logging.getLogger("httpx").setLevel(logging.WARNING)
    api = CrbApi.from_env(environ)
    server = build_server(api)
    try:
        server.run(transport="stdio")
    finally:
        api.close()
    return 0


def describe() -> str:
    """A one-screen description of the tools, for ``crb mcp --list``."""
    api = CrbApi(httpx.Client(base_url="http://invalid"))
    server = build_server(api)
    return json.dumps(tool_names(server), indent=2)
