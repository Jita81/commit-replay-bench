# The MCP server — driving crb from Claude Code (or any MCP client)

<!--
Navigation
----------
What it is:   The operator guide for `crb mcp`: what the Model Context Protocol server exposes,
              how to connect Claude Code to a deployment, which account it acts as, and the two
              things it deliberately cannot do.
What it does: Lets an assistant answer "what does the map say about this repository?" from the
              ledger, start a measurement under the deployment's RBAC, and read the evidence —
              instead of from memory.
How:          `src/crb/mcp/` is a client of `/api/v1` (never an importer of the server); the
              tools are one-line pass-throughs whose results are the API's JSON unchanged.
Layer:        docs — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0008-stdlib-core-and-downward-layers.md, docs/adr/0013-external-review-is-advisory-and-recorded.md
Works with:   src/crb/mcp/server.py (the tools), src/crb/mcp/client.py (auth), docs/API.md (every
              tool names the route it wraps), docs/EVIDENCE-AND-CLAIMS.md (the claims policy the
              server hands the model), docs/OPERATOR.md (the accounts)
Tested by:    tests/test_mcp_server.py
Touch when:   a tool is added or an environment variable changes.
-->

## 1. What it is

`crb mcp` runs a [Model Context Protocol](https://modelcontextprotocol.io) server on stdio
whose tools are the crb API. Connected to Claude Code, an assistant can:

- read the **capability map** and the **routes** for a repository — every cell with its `n`,
  `n_tasks`, Wilson interval, false-Q1, oracle strength, controls verdict, route and the
  policy (version **and** thresholds) it was decided under;
- read **tasks**, **runs**, **ledger rows**, **evidence packs** and the **factory** state;
- **start a measurement** (mine, oracle, controls, a small sighted replay on named
  `task_ids`) — under the same RBAC the UI has, and with a warning in the tool that it
  spends the operator's model budget;
- verify the ledger's hash chain.

The tools return the API's JSON unchanged, so the assistant sees exactly what the UI shows,
with every method field intact. The server's `instructions` carry the claims policy
([EVIDENCE-AND-CLAIMS](EVIDENCE-AND-CLAIMS.md) §3 and §7) so a model quoting a number
carries its `n`, interval, mode and apparatus, and knows that `deliver` never means "safe
to deploy".

## 2. What it deliberately cannot do

Two things that exist in the API are **not tools**:

| Not a tool | Why |
|---|---|
| Creating a **sign-off** (`POST /signoffs`) | A sign-off is a human attestation that a person examined the evidence and takes responsibility for the routing consequence. A model calling it would be "an AI opinion of AI work" — the thing the product refuses ([EVIDENCE-AND-CLAIMS §2](EVIDENCE-AND-CLAIMS.md#2-clean-semantic-q1-and-false-q1)). The tools can *read* sign-offs and the policy. |
| Filing a **review** (`POST /reviews`) | Same reason: a review is anchored to the diff bytes a human read. |

An assistant that wants either points the operator at the UI or the `crb` CLI.

## 3. Setup

The server needs a **local crb account** — it has no browser to complete an OIDC round-trip.
An organisation that signs in with OIDC creates one local service account for it
(`POST /users` as admin, or the Settings screen) with the lowest role that does the job:

| Role | What the assistant can do |
|---|---|
| `viewer` | read everything (map, routes, tasks, runs, evidence, ledger verify, sign-offs) |
| `operator` | also register/update/probe repositories, start and cancel runs, freeze a factory backlog |
| `approver` | also `deliver_override` on a factory run (recorded as the approver's act) |

Environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `CRB_API_URL` | `http://127.0.0.1:8000/api/v1` | the deployment's API prefix |
| `CRB_MCP_USERNAME` | — | the local account |
| `CRB_MCP_PASSWORD` | — | its password (never logged, never echoed by a tool) |
| `CRB_MCP_TIMEOUT_S` | `60` | HTTP timeout per call |

Install the extra and check the tool list:

```bash
pip install 'commit-replay-bench[mcp]'
crb mcp --list
```

Connect Claude Code (project scope, so the deployment travels with the repository you are
working in):

```bash
claude mcp add crb \
  -e CRB_API_URL=https://crb.your-org.example/api/v1 \
  -e CRB_MCP_USERNAME=svc-assistant \
  -e CRB_MCP_PASSWORD='…' \
  -- crb mcp
```

Then, in Claude Code: *"What does the crb map say about `bug.fix` XS on `cobra`?"* — the
assistant calls `crb_capability_map` and answers with the cell's `n`, interval and route.

For the dev stack on this machine the defaults suffice apart from the account:
`claude mcp add crb -e CRB_MCP_USERNAME=… -e CRB_MCP_PASSWORD=… -- crb mcp`.

## 4. The tools

| Tool | Route | Role |
|---|---|---|
| `crb_whoami` | `GET /auth/me` | viewer |
| `crb_version`, `crb_health` | `GET /version`, `GET /health` | viewer |
| `crb_repos`, `crb_repo`, `crb_repo_profile` | `GET /repos`, `/repos/{name}`, `/repos/{name}/profile` (`refresh` needs operator) | viewer |
| `crb_register_repo`, `crb_update_repo`, `crb_probe_repo` | `POST /repos`, `PUT /repos/{name}`, `POST /repos/{name}/probe` | operator |
| `crb_tasks`, `crb_task` | `GET /repos/{name}/tasks`, `GET /tasks/{repo}/{task_id}` | viewer |
| `crb_runs`, `crb_run`, `crb_run_tasks`, `crb_run_events` | `GET /runs`, `/runs/{id}`, `/runs/{id}/tasks`, `/runs/{id}/events/log` | viewer |
| `crb_start_run` | `POST /runs` — **spends model budget** for replay/blind/factory kinds | operator (`deliver_override`: approver) |
| `crb_cancel_run` | `POST /runs/{id}/cancel` | operator |
| `crb_grades`, `crb_grade`, `crb_evidence`, `crb_grade_patch` | `GET /grades`, `/grades/{row_id}`, `/evidence/{pack_hash}`, `/grades/{row_hash}/patch` | viewer |
| `crb_capability_map`, `crb_routes`, `crb_failure_split` | `GET /capability-map`, `/routes`, `/failure-split` | viewer |
| `crb_oracle`, `crb_controls` | `GET /oracle/{repo}`, `/oracle/{repo}/controls` | viewer |
| `crb_remeasure_plan`, `crb_strengthen_plan`, `crb_refusals`, `crb_forecast` | `GET /learn/remeasure`, `/learn/strengthen`, `/learn/refusals`, `/forecast/build` | viewer |
| `crb_ledger_verify` | `GET /ledger/verify` | viewer |
| `crb_signoffs`, `crb_signoff_policy`, `crb_reviews` | `GET /signoffs`, `/signoffs/policy`, `/reviews` — read only | viewer |
| `crb_factory_backlog`, `crb_factory_tasks`, `crb_factory_evidence` | `GET /factory/{repo}/backlog`, `/tasks`, `/evidence` | viewer |
| `crb_factory_register_backlog` | `POST /factory/{repo}/backlog` | operator |

A refusal by the API (403 for a role, 404 for a name, 409 for a busy backlog, 422 for a bad
body) comes back as `{"error": true, "status", "code", "message", "detail"}` — the API's own
words — rather than as a crash, so the assistant can read it and tell the operator.

## 5. Security notes

- The credentials are the account's; rotate them like any service account. The server
  never prints them; a tool result never contains them.
- The MCP server is a client of the API over HTTP(S): point `CRB_API_URL` at the same
  TLS endpoint the browser uses. Nothing runs on the MCP host that the API would not allow
  the same account to do from the UI.
- A model's reading of the ledger is advisory (ADR-0013); the ledger is the record. Nothing
  the assistant says becomes a row, a route or a sign-off.
