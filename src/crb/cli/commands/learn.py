"""``crb learn`` — the learning half of the loop, as three reports over the ledger.

* ``crb learn refusals [--apply <decisions.json>]`` — protocol rows → candidate
  guard-corpus lines (every verdict ``unsure``); ``--apply`` appends what a named
  human decided, with provenance, to ``tests/fixtures/shell_corpus*.txt``.
* ``crb learn strengthen [--oracle <report.json>] [--out backlog.json]`` — oracle-held
  cells → ``test.add`` items in the frozen-backlog shape (validated through the
  factory's ``BacklogItem`` + DoR gate before they are written).
* ``crb learn remeasure [--apparatus X]`` — cells whose rows predate the apparatus →
  the ``POST /runs`` bodies an operator can queue. Nothing is queued.

The ledger is read the way ``crb route`` reads it: ``--path`` or ``<workdir>/ledger.jsonl``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from crb.cli.commands import (
    EXIT_OK,
    CliError,
    Workdir,
    add_common,
    print_json,
    print_lines,
    workdir_of,
)
from crb.cli.commands.route import load_policy
from crb.core.capability import PROJECTIONS, build_capability_map
from crb.core.learn import (
    RefusalDecision,
    apply_triage,
    dumps,
    load_decisions,
    load_oracle_scores,
    remeasure_plan,
    render_refusals,
    render_remeasure,
    render_strengthen,
    strengthening_backlog,
    triage_refusals,
)
from crb.core.ledger import JsonlLedger
from crb.core.version import APPARATUS_VERSION
from crb.factory.backlog import BacklogItem
from crb.factory.readiness import ROUTE_BUILD, assess

DEFAULT_CORPUS_DIR = "tests/fixtures"


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("learn", help="refusal triage, strengthening backlog, re-measurement plan")
    ls = p.add_subparsers(dest="learn_command", metavar="<report>")

    r = ls.add_parser(
        "refusals",
        help="protocol rows → candidate guard-corpus lines (a human decides; --apply writes)",
    )
    _ledger_args(r)
    r.add_argument(
        "--apply",
        default="",
        metavar="DECISIONS.json",
        help='{"decided_by": "<name>", "decisions": [{"group_id", "verdict": honest|refuse|unsure, '
        '"note", "command", "prefix"}]} — appends the accepted lines with provenance',
    )
    r.add_argument(
        "--corpus-dir",
        default=DEFAULT_CORPUS_DIR,
        help=f"where shell_corpus.txt / shell_corpus_refused.txt live (default {DEFAULT_CORPUS_DIR})",
    )
    r.add_argument("--date", default="", help="provenance date (default: today, UTC)")
    r.add_argument("--out", default="", help="also write the report JSON here")
    add_common(r)
    r.set_defaults(func=cmd_refusals)

    s = ls.add_parser(
        "strengthen",
        help="oracle-held cells → 'strengthen the target tests' backlog items (frozen-backlog shape)",
    )
    _ledger_args(s)
    s.add_argument(
        "--oracle",
        default="",
        metavar="REPORT.json",
        help="an oracle-strength report (to_report() JSON, a list of per-task scores, or "
        "oracle.score event payloads) — supplies the escaped mutants per task",
    )
    s.add_argument("--repo", default="", help="subjects from <workdir>/tasks/<repo>.jsonl")
    s.add_argument(
        "--by",
        default="class_size",
        choices=sorted(PROJECTIONS),
        help="capability-map projection the cells are flagged on (default class_size)",
    )
    s.add_argument(
        "--since",
        default="",
        metavar="APPARATUS",
        help="only cells/scores stamped with an apparatus >= this version",
    )
    s.add_argument(
        "--registered",
        default="",
        help="the items' 'registered' stamp (default: now; pass a fixed value for a reproducible file)",
    )
    s.add_argument("--out", default="", help="write the items as an (unfrozen) Backlog JSON")
    add_common(s)
    s.set_defaults(func=cmd_strengthen)

    m = ls.add_parser(
        "remeasure",
        help="cells stamped with an older apparatus → n needed, cost, POST /runs bodies",
    )
    _ledger_args(m)
    m.add_argument(
        "--apparatus",
        default=APPARATUS_VERSION,
        help=f"the current apparatus version (default {APPARATUS_VERSION})",
    )
    m.add_argument("--out", default="", help="also write the plan JSON here")
    add_common(m)
    m.set_defaults(func=cmd_remeasure)

    add_common(p)  # so `crb learn --workdir X` parses and prints the sub-command help
    p.set_defaults(func=lambda args: _usage(p))


def _usage(parser: argparse.ArgumentParser) -> int:
    parser.print_help()
    return 2


def _ledger_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--path", default="", help="ledger path (default <workdir>/ledger.jsonl)")
    p.add_argument(
        "--policy-json",
        default="",
        help="RoutingPolicy overrides: a JSON file path or inline JSON, e.g. '{\"min_n\": 20}'",
    )


def _rows(args: argparse.Namespace) -> tuple[Path, list[Any]]:
    wd = workdir_of(args)
    path = Path(args.path).expanduser() if args.path else wd.ledger_path
    return path, list(JsonlLedger(path).rows())


def _read_json(spec: str, *, what: str) -> Any:
    p = Path(spec).expanduser()
    if not p.is_file():
        raise CliError(f"{what} {p} is not a file")
    text = p.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # JSON lines (e.g. exported oracle.score events)
    items: list[Any] = []
    for line in text.splitlines():
        if line.strip():
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise CliError(f"{what} {p}: not valid JSON (or JSON lines): {e}") from e
    return items


def _write(spec: str, text: str) -> Path:
    p = Path(spec).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------


def cmd_refusals(args: argparse.Namespace) -> int:
    path, rows = _rows(args)
    report = triage_refusals(rows)
    out: dict[str, Any] = {"ledger": str(path), **report.to_dict()}
    if args.out:
        _write(args.out, dumps(out))
    if args.apply:
        raw = _read_json(args.apply, what="--apply")
        if not isinstance(raw, dict):
            raise CliError("--apply must be a JSON object with 'decided_by' and 'decisions'")
        who, decisions = load_decisions(raw)
        applied = apply_triage(
            decisions, report, corpus_dir=args.corpus_dir, decided_by=who, date=args.date
        )
        out["applied"] = applied.to_dict()
        if args.json:
            print_json(out)
        else:
            lines = [
                f"applied {len(decisions)} decision(s) by {who}:",
                f"  honest  +{len(applied.honest_added)} → {applied.honest_path}",
                f"  refused +{len(applied.refused_added)} → {applied.refused_path}",
                f"  skipped (already present) {len(applied.skipped)} · unsure (not written) "
                f"{len(applied.unsure)}",
                "run the guard corpus tests to make the new line(s) bind: "
                "pytest tests/test_builders_guard_corpus.py -q",
            ]
            print_lines(lines)
        return EXIT_OK
    if args.json:
        print_json(out)
    else:
        print_lines([render_refusals(report), "", f"ledger: {path}"])
    return EXIT_OK


# ---------------------------------------------------------------------------
# strengthen
# ---------------------------------------------------------------------------


def _subjects(wd: Workdir, repo: str) -> dict[str, str]:
    if not repo:
        return {}
    return {t.task_id: t.subject for t in wd.load_tasks(repo)}


def validate_items(items: list[dict[str, Any]]) -> list[str]:
    """Round-trip every item through the factory's ``BacklogItem`` and the DoR gate.
    Returns the ids that are NOT ready for ``build`` (should be none: every item
    fills only structural slots); raises ``CliError`` on a malformed item."""
    not_ready: list[str] = []
    for d in items:
        try:
            item = BacklogItem.from_dict(d)
        except ValueError as e:
            raise CliError(f"item {d.get('id')!r} is not a valid BacklogItem: {e}") from e
        r = assess(item)
        if not r.ready or r.route_hint != ROUTE_BUILD:
            not_ready.append(item.id)
    return not_ready


def cmd_strengthen(args: argparse.Namespace) -> int:
    path, rows = _rows(args)
    wd = workdir_of(args)
    policy = load_policy(args.policy_json)
    cmap = build_capability_map(rows, projection=PROJECTIONS[args.by], policy=policy)
    scores = load_oracle_scores(_read_json(args.oracle, what="--oracle")) if args.oracle else []
    backlog = strengthening_backlog(
        cmap,
        scores,
        policy=policy,
        subjects=_subjects(wd, args.repo),
        since=args.since,
        generated_at=args.registered,
    )
    payload = backlog.to_dict()
    not_ready = validate_items(payload["items"])
    if not_ready:  # a poka-yoke on our own output: never hand the factory a blocked item
        raise CliError(f"strengthening item(s) would not pass the DoR gate: {not_ready}")
    out: dict[str, Any] = {"ledger": str(path), "projection": args.by, **payload}
    if args.out:
        _write(args.out, dumps(backlog.to_backlog_dict(repo=args.repo)))
        out["written"] = str(Path(args.out).expanduser())
    if args.json:
        print_json(out)
    else:
        lines = [render_strengthen(backlog), "", f"ledger: {path}"]
        if args.out:
            lines.append(f"backlog (unfrozen) written to {out['written']}")
        print_lines(lines)
    return EXIT_OK


# ---------------------------------------------------------------------------
# remeasure
# ---------------------------------------------------------------------------


def cmd_remeasure(args: argparse.Namespace) -> int:
    path, rows = _rows(args)
    policy = load_policy(args.policy_json)
    plan = remeasure_plan(rows, current_apparatus=args.apparatus, policy=policy)
    out: dict[str, Any] = {"ledger": str(path), **plan.to_dict()}
    if args.out:
        _write(args.out, dumps(out))
    if args.json:
        print_json(out)
    else:
        print_lines([render_remeasure(plan), "", f"ledger: {path}"])
    return EXIT_OK


__all__ = ["RefusalDecision", "cmd_refusals", "cmd_remeasure", "cmd_strengthen", "register"]
