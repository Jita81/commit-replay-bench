"""``crb route`` — apply the ONE published routing rule to every measured cell.

Navigation
----------
What it is:   ``crb route`` — the ONE routing rule applied to every measured cell of a
              JSONL ledger, with its reason.
What it does: Reads the ledger, rolls rows up into cells, routes each under the default
              policy (or a JSON override whose fields must all be known), prints the
              table, and exits 1 when any cell is ``do_not_ship``. ``load_policy`` is also
              what ``crb learn`` uses for its ``--policy-json``.
How:          ``JsonlLedger.rows`` → ``all_cell_stats`` → ``route`` per cell → table / JSON.
Layer:        cli — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/core/routing.py (``route``, ``RoutingPolicy``), src/crb/core/ledger.py
              (``all_cell_stats``), src/crb/cli/commands/learn.py (imports ``load_policy``),
              src/crb/server/routes/capability.py (the same rule over the database),
              docs/OPERATOR.md#4-read-the-capability-map
Tested by:    tests/test_cli.py, tests/test_cli_learn.py
Touch when:   never for a new repository; a policy threshold is a ``--policy-json`` value
              for an experiment and an ADR + apparatus bump for a change of default.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from crb.cli.commands import (
    EXIT_NEGATIVE,
    EXIT_OK,
    CliError,
    add_common,
    print_json,
    print_lines,
    table,
    workdir_of,
)
from crb.core.ledger import JsonlLedger, all_cell_stats
from crb.core.routing import DEFAULT_POLICY, ROUTE_DO_NOT_SHIP, RoutingPolicy, route


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``crb route``."""
    p = sub.add_parser("route", help="route decision per measured cell")
    p.add_argument("--path", default="", help="ledger path (default <workdir>/ledger.jsonl)")
    p.add_argument(
        "--policy-json",
        default="",
        help="RoutingPolicy overrides: a JSON file path or inline JSON, e.g. '{\"min_n\": 20}'",
    )
    add_common(p)
    p.set_defaults(func=cmd_route)


def load_policy(spec: str) -> RoutingPolicy:
    """``spec`` is empty (default policy), a path to a JSON file, or inline JSON."""
    if not spec:
        return DEFAULT_POLICY
    text = spec.strip()
    if not text.startswith("{"):
        p = Path(text).expanduser()
        if not p.is_file():
            raise CliError(f"--policy-json {p} is not a file (or inline JSON object)")
        text = p.read_text(encoding="utf-8")
    try:
        d = json.loads(text)
    except json.JSONDecodeError as e:
        raise CliError(f"--policy-json is not valid JSON: {e}") from e
    if not isinstance(d, dict):
        raise CliError("--policy-json must be a JSON object")
    known = set(RoutingPolicy.__dataclass_fields__)
    unknown = sorted(set(d) - known)
    if unknown:
        raise CliError(f"--policy-json unknown field(s) {unknown}; known: {sorted(known)}")
    if "granularize_sizes" in d:
        d["granularize_sizes"] = tuple(str(s) for s in d["granularize_sizes"])
    return RoutingPolicy(**d)


def cmd_route(args: argparse.Namespace) -> int:
    """Route every measured cell; exit 1 when any is ``do_not_ship``."""
    wd = workdir_of(args)
    path = Path(args.path).expanduser() if args.path else wd.ledger_path
    policy = load_policy(args.policy_json)
    rows = list(JsonlLedger(path).rows())
    decisions = [route(s, policy=policy) for s in all_cell_stats(rows)]
    decisions.sort(key=lambda d: tuple(d.cell.values()))
    out: dict[str, Any] = {
        "ledger": str(path),
        "rows": len(rows),
        "policy": policy.to_dict(),
        "decisions": [d.to_dict() for d in decisions],
        "summary": {
            r: sum(1 for d in decisions if d.route == r)
            for r in sorted({d.route for d in decisions})
        },
    }
    if args.json:
        print_json(out)
    else:
        headers = (
            "class",
            "size",
            "lang",
            "builder",
            "model",
            "n",
            "point",
            "ci_low",
            "fq1",
            "route",
            "reason",
        )
        body = [
            (
                d.cell["capability_class"],
                d.cell["size"],
                d.cell["language"],
                d.cell["builder"],
                d.cell["model"],
                d.n,
                f"{d.point:.3f}",
                f"{d.ci_low:.3f}",
                d.false_q1,
                d.route,
                d.reason,
            )
            for d in decisions
        ]
        lines = list(table(headers, body))
        lines.append("")
        lines.append(
            f"{len(decisions)} cell(s) from {len(rows)} rows; policy {policy.version} "
            f"(n≥{policy.min_n}, point≥{policy.min_point}, Wilson-low≥{policy.min_ci_low}, "
            f"oracle≥{policy.min_oracle_strength} when measured); summary {out['summary']}"
        )
        print_lines(lines)
    return EXIT_NEGATIVE if any(d.route == ROUTE_DO_NOT_SHIP for d in decisions) else EXIT_OK
