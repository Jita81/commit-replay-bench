"""``crb route`` — apply the ONE published routing rule to every measured cell.

Navigation
----------
What it is:   ``crb route`` — the ONE routing rule applied to every measured cell of a
              JSONL ledger, with its reason.
What it does: Reads ONE reading of the ledger (the current apparatus, sighted, context arm
              ``S3`` and the global class set by default; ``--apparatus all`` refused; two
              posture classes exit 2), routes each full cell under routing.v2 with the
              registered readings, oracle scores and controls report it is handed, prints
              each cell's shortfalls with their next act, and exits 1 when any cell is
              ``do_not_ship``. ``--help`` quotes the published bar. ``load_policy`` is also
              what ``crb learn`` uses for its ``--policy-json``.
How:          ``JsonlLedger.rows`` → ``rows_for_reading`` → ``build_capability_map`` (with a
              ``ReadingBook``) → table / JSON.
Layer:        cli — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0025-routing-v2.md, docs/adr/0026-the-context-standard.md
Works with:   src/crb/core/routing.py (``route``, ``RoutingPolicy``), src/crb/core/ledger.py
              (``all_cell_stats``), src/crb/cli/commands/learn.py (imports ``load_policy``),
              src/crb/server/routes/capability.py (the same rule over the database),
              docs/OPERATOR.md#4-read-the-capability-map
Tested by:    tests/test_cli.py, tests/test_cli_learn.py, tests/test_cli_route.py
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
from crb.core.capability import PROJECTION_CELL, ReadingBook, build_capability_map
from crb.core.checks import ARM_OFF, ARMS
from crb.core.context_arm import is_arm
from crb.core.ledger import DEFAULT_READ_ARM, JsonlLedger, rows_for_checks, rows_for_reading
from crb.core.reading import Reading
from crb.core.routing import DEFAULT_POLICY, ROUTE_DO_NOT_SHIP, RoutingPolicy
from crb.core.version import APPARATUS_VERSION


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``crb route``."""
    p = sub.add_parser(
        "route",
        help="route decision per measured cell (routing.v2)",
        description="The published bar: " + DEFAULT_POLICY.describe(),
    )
    p.add_argument("--path", default="", help="ledger path (default <workdir>/ledger.jsonl)")
    p.add_argument(
        "--policy-json",
        default="",
        help="RoutingPolicy overrides: a JSON file path or inline JSON, e.g. "
        '\'{"rule": "look.v1-strict"}\' — a looser bar must name its own version',
    )
    p.add_argument(
        "--checks",
        default=ARM_OFF,
        choices=ARMS,
        help="route only rows graded under this 'clean means working' arm (default off) — "
        "rows of two arms never share a cell (ADR-0024)",
    )
    p.add_argument(
        "--apparatus",
        default="current",
        help="the one apparatus version to read (default current; two are never pooled, "
        "and 'all' is refused — ADR-0025 item 1)",
    )
    p.add_argument(
        "--mode",
        default="sighted",
        choices=("sighted", "blind"),
        help="rows of one mode (default sighted); rows of 2.4 also split by context arm",
    )
    p.add_argument(
        "--arm",
        default=DEFAULT_READ_ARM,
        help="the one context arm to route (default S3 — a ceiling, never deliver; ADR-0026)",
    )
    p.add_argument(
        "--oracle",
        default="",
        help="per-task oracle scores (GET /oracle/<repo> export, or an oracle run's events "
        "log) — without it every cell reads oracle_unmeasured",
    )
    p.add_argument(
        "--controls",
        default="",
        help="the controls report (GET /oracle/<repo>/controls) — without it every cell reads "
        "controls_unmeasured",
    )
    p.add_argument(
        "--readings",
        default="",
        help="registered readings (JSON lines written by 'crb reading register') — without "
        "them every cell reads reading_unregistered",
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
    try:
        return RoutingPolicy(**d)
    except ValueError as e:
        # a policy looser than the published rule must carry its own "version" — every
        # decision names the bar it cleared (external review 2026-09-16, point 9)
        raise CliError(f"--policy-json: {e}") from e


def _read_json(spec: str, *, what: str) -> Any:
    """A JSON document or JSON lines from ``spec`` (a path)."""
    path = Path(spec).expanduser()
    if not path.is_file():
        raise CliError(f"{what} {path} is not a file")
    text = path.read_text(encoding="utf-8").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return [json.loads(line) for line in text.splitlines() if line.strip()]
        except json.JSONDecodeError as e:
            raise CliError(f"{what} is neither JSON nor JSON lines: {e}") from e


def oracle_minimums(spec: str, apparatus: str) -> dict[str, float | None]:
    """Each task's MINIMUM scoreable strength at ``apparatus`` from an oracle export
    (ADR-0025 item 3) — a score of another apparatus is history and never read."""
    if not spec:
        return {}
    from crb.cli.commands.learn import load_oracle_export  # noqa: PLC0415 — learn imports route

    out: dict[str, float | None] = {}
    for sc in load_oracle_export(_read_json(spec, what="--oracle")):
        if sc.strength is None or (sc.apparatus_version and sc.apparatus_version != apparatus):
            continue
        prior = out.get(sc.task_id)
        out[sc.task_id] = sc.strength if prior is None else min(prior, sc.strength)
    return out


def load_readings_file(spec: str) -> list[Reading]:
    """The readings a ``--readings`` JSON-lines file holds; a record that does not re-hash
    is refused (a reading licenses nothing it cannot prove)."""
    if not spec:
        return []
    raw = _read_json(spec, what="--readings")
    items = raw if isinstance(raw, list) else [raw]
    out: list[Reading] = []
    for d in items:
        reading = Reading.from_dict(d.get("payload", d) if isinstance(d, dict) else {})
        if not reading.verify():
            raise CliError(f"--readings: reading {reading.reading_id!r} does not re-hash")
        out.append(reading)
    return out


def cmd_route(args: argparse.Namespace) -> int:
    """Route every measured cell of one reading (one checks arm, apparatus, mode, context arm
    and class-set version); exit 1 when any is ``do_not_ship`` or when the ledger has rows but
    none of the selected reading (unmeasured is never a successful route); exit 2 when the
    selection still spans two posture classes (never pooled — ADR-0019 §8)."""
    wd = workdir_of(args)
    path = Path(args.path).expanduser() if args.path else wd.ledger_path
    policy = load_policy(args.policy_json)
    if args.apparatus == "all":
        raise CliError("--apparatus all is refused: a reading has one apparatus (ADR-0025 item 1)")
    if not is_arm(args.arm):
        raise CliError(f"--arm {args.arm!r} is outside the context-arm grammar (ADR-0026 item 1)")
    apparatus = APPARATUS_VERSION if args.apparatus in ("", "current") else args.apparatus
    every = list(JsonlLedger(path).rows())
    by_checks = rows_for_checks(every, args.checks)
    rows = [
        r
        for r in rows_for_reading(by_checks, apparatus=apparatus, arm=args.arm)
        if r.mode == args.mode or r.context_arm
    ]
    by_arm: dict[str, int] = {}
    for r in every:
        by_arm[r.checks_arm] = by_arm.get(r.checks_arm, 0) + 1
    postures = sorted({r.posture_class for r in rows if r.posture_class})
    if len(postures) > 1:
        raise CliError(
            f"the selected rows span {len(postures)} posture classes ({', '.join(postures)}) — "
            "a reading has one (ADR-0019 §8); filter the ledger to one class first"
        )
    unmeasured = bool(every) and not rows
    controls = None
    if args.controls:
        from crb.cli.commands.learn import (  # noqa: PLC0415 — learn imports route
            load_controls_export,
        )

        controls = load_controls_export(_read_json(args.controls, what="--controls"))
    book = ReadingBook.evaluate(load_readings_file(args.readings), every)
    scores = oracle_minimums(args.oracle, apparatus)
    cmap = build_capability_map(
        rows,
        projection=PROJECTION_CELL,
        policy=policy,
        controls=controls,
        oracle_by_task=scores,
        readings=book,
    )
    decisions = [c.decision for c in cmap.cells if c.decision is not None]
    decisions.sort(key=lambda d: tuple(d.cell.values()))
    out: dict[str, Any] = {
        "ledger": str(path),
        "checks": args.checks,
        "apparatus": apparatus,
        "mode": args.mode,
        "arm": args.arm,
        "rows": len(rows),
        "rows_by_arm": dict(sorted(by_arm.items())),
        "unmeasured": unmeasured,
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
            "commits",
            "look",
            "route",
            "reason",
            "next",
        )
        body = [
            (
                d.cell["capability_class"],
                d.cell["size"],
                d.cell["language"],
                d.cell["builder"],
                d.cell["model"],
                d.n,
                d.n_tasks,
                d.look_state,
                d.route,
                d.reason_code,
                "; ".join(
                    f"{s.code}: {s.next}{f' x{s.count}' if s.count else ''}"
                    f"{' ($)' if s.model_money else ''}"
                    for s in d.shortfalls
                ),
            )
            for d in decisions
        ]
        lines = list(table(headers, body))
        lines.append("")
        if unmeasured:
            others = ", ".join(f"{arm}: {n}" for arm, n in sorted(by_arm.items()))
            lines.append(
                f"no rows graded under the checks arm {args.checks!r} at apparatus {apparatus}, "
                f"mode {args.mode}, context arm {args.arm} — that reading is unmeasured, not "
                f"routed. The ledger's rows by checks arm: {others}; pass --checks with one of "
                "them to route it."
            )
        lines.append(
            f"{len(decisions)} cell(s) from {len(rows)} rows; policy {policy.version}: "
            f"{policy.describe()} Summary {out['summary']}"
        )
        print_lines(lines)
    if unmeasured:
        return EXIT_NEGATIVE
    return EXIT_NEGATIVE if any(d.route == ROUTE_DO_NOT_SHIP for d in decisions) else EXIT_OK
