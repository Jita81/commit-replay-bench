"""``crb learn`` — the learning half of the loop, as three reports over the ledger.

* ``crb learn refusals [--apply <decisions.json>]`` — protocol rows → candidate
  guard-corpus lines (every verdict ``unsure``); ``--apply`` appends what a named
  human decided, with provenance, to ``tests/fixtures/shell_corpus*.txt``.
* ``crb learn strengthen [--oracle <scores.json>] [--controls <report.json>] [--out
  backlog.json]`` — oracle-held cells → ``test.add`` items in the frozen-backlog shape
  (validated through the factory's ``BacklogItem`` + DoR gate before they are written).
* ``crb learn remeasure [--apparatus X]`` — cells whose rows predate the apparatus →
  the ``POST /runs`` bodies an operator can queue. Nothing is queued.

The ledger is read the way ``crb route`` reads it: ``--path`` or ``<workdir>/ledger.jsonl``.

What a ledger export cannot carry
---------------------------------
A ``GET /ledger/export`` JSONL is the rows alone. Two things the server routes
``/learn/strengthen`` on live elsewhere in the store: the per-task oracle scores
(``oracle.score`` events of the repo's oracle runs — ``counts_json`` keeps only the
per-cell roll-up) and the repo's negative-controls verdict (its latest
``controls.report``). Over a bare export the CLI can therefore see neither an
``oracle_weak`` task nor a ``controls_escapes`` / ``controls_thin`` cell, and
``strengthen`` honestly flags nothing. ``--oracle`` and ``--controls`` hand it those
two exports — ``GET /oracle/{repo}`` (or a run's ``events/log``) and
``GET /oracle/{repo}/controls`` — so the CLI and the route produce the same items
with the same ids from the same evidence.

Navigation
----------
What it is:   ``crb learn refusals | strengthen | remeasure`` — the learning loop's three
              reports over a JSONL ledger, plus the one write a human authorises.
What it does: Triages protocol rows into candidate guard-corpus lines (``--apply`` appends
              a named human's decisions with provenance); derives ``test.add`` backlog
              items for oracle-weak cells from the ledger plus the oracle / controls
              exports the server holds (validated through the factory's ``BacklogItem``
              and DoR gate before they are written); plans re-measurement for cells on an
              older apparatus. Queues nothing.
How:          ``_rows`` → the ``crb.core.learn`` derivation → ``render_*`` / JSON; exports
              are read by ``_read_json`` (JSON or JSON lines) and reduced by
              ``load_oracle_export`` / ``load_controls_export`` exactly as the routes do.
Layer:        cli — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/core/learn.py (the derivations and renderers),
              src/crb/server/routes/learn.py (the HTTP twin — same ids over the same
              evidence), src/crb/factory/backlog.py (``BacklogItem`` + ``assess`` for the
              strengthening items), src/crb/cli/commands/route.py (``load_policy``),
              docs/LEARNING-LOOP.md (the contract, incl. what a bare export cannot carry)
Tested by:    tests/test_cli_learn.py
Touch when:   never for a new repository; when a new derivation lands in
              src/crb/core/learn.py (add the subcommand, the route, and the
              docs/LEARNING-LOOP.md section together); when the server's oracle / controls
              export shapes change (``load_*_export`` must follow).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
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
    OracleTaskScore,
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
from crb.core.routing import ControlsVerdict
from crb.core.version import APPARATUS_VERSION
from crb.factory.backlog import BacklogItem
from crb.factory.readiness import ROUTE_BUILD, assess

DEFAULT_CORPUS_DIR = "tests/fixtures"

#: The event actions whose payload is ONE task's oracle score: the worker's
#: ``oracle.score`` and the core's own ``oracle.mutation.scored``. Mirrors
#: ``crb.server.routes.oracle.SCORE_ACTIONS`` (the CLI cannot import the server
#: package; ``tests/test_cli_learn.py`` pins the two equal). An exported event log
#: carries every stage's events — a ``grade.belt`` event is not a score, and read
#: as one it would become an "unscoreable" item.
ORACLE_SCORE_ACTIONS: frozenset[str] = frozenset({"oracle.score", "oracle.mutation.scored"})


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``crb learn refusals | strengthen | remeasure``."""
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
        metavar="SCORES.json",
        help="per-task oracle scores, in any shape the server exports them: GET /oracle/<repo> "
        "JSON, a run's GET /runs/<id>/events/log page or JSONL of its oracle.score events, "
        "an oracle-strength report (to_report() JSON), or a list of per-task scores",
    )
    s.add_argument(
        "--controls",
        default="",
        metavar="CONTROLS.json",
        help="the repo's negative-controls verdict (GET /oracle/<repo>/controls JSON, or a "
        "'controls' run's counts) — without it cells are routed with controls NOT evaluated, "
        "so no controls_escapes / controls_thin cell can be flagged from a bare ledger export",
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
    """``crb learn`` with no subcommand: help + usage-error exit."""
    parser.print_help()
    return 2


def _ledger_args(p: argparse.ArgumentParser) -> None:
    """``--path`` and ``--policy-json`` — the same pair ``crb route`` takes."""
    p.add_argument("--path", default="", help="ledger path (default <workdir>/ledger.jsonl)")
    p.add_argument(
        "--policy-json",
        default="",
        help="RoutingPolicy overrides: a JSON file path or inline JSON, e.g. '{\"min_n\": 20}'",
    )


def _rows(args: argparse.Namespace) -> tuple[Path, list[Any]]:
    """``(ledger path, rows)`` for the command line."""
    wd = workdir_of(args)
    path = Path(args.path).expanduser() if args.path else wd.ledger_path
    return path, list(JsonlLedger(path).rows())


def _read_json(spec: str, *, what: str) -> Any:
    """A JSON document, or a JSON-lines file as a list — ``CliError`` otherwise."""
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
    """Write ``text`` to ``spec`` (parents created); returns the path."""
    p = Path(spec).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------


def cmd_refusals(args: argparse.Namespace) -> int:
    """Triage the protocol rows; with ``--apply`` append a human's decisions to the corpus."""
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
    """``task_id → commit subject`` from the workdir's task file (empty when no ``--repo``)."""
    if not repo:
        return {}
    return {t.task_id: t.subject for t in wd.load_tasks(repo)}


def load_oracle_export(raw: Any) -> list[OracleTaskScore]:
    """Per-task oracle scores from whatever the product exports them as:

    * ``GET /oracle/{repo}`` — ``{"repo": …, "tasks": [OracleTaskOut…]}`` (the latest
      score per task; ``repo`` is carried onto every score so item ids match the
      server's);
    * a ``GET /runs/{id}/events/log`` page — ``{"items": [StepEvent…]}`` — or a JSONL
      of those events: only :data:`ORACLE_SCORE_ACTIONS` are scores, the envelope's
      ``task_id`` / ``repo`` sit beside the ``payload``;
    * an oracle-strength report (``to_report()``: ``{"tasks": [...]}``);
    * a bare list of per-task score dicts.

    An empty export (``tasks: []``, an event log with no score) is an honest empty
    list. A file that has entries but not one per-task score in them — the wrong
    export, a controls report, a replay run's log — is a :class:`CliError`, never a
    silent empty list that would make every held cell read "without scores".
    """
    default_repo = ""
    if isinstance(raw, Mapping):
        default_repo = str(raw.get("repo") or "")
        if isinstance(raw.get("items"), list):
            raw = raw["items"]
        elif isinstance(raw.get("tasks"), list):
            raw = raw["tasks"]
        else:
            raw = [raw]
    if not isinstance(raw, list):
        raise CliError("--oracle must be a JSON object, a list, or JSON lines of per-task scores")
    scores: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        action = item.get("action")
        if action is not None and str(action) not in ORACLE_SCORE_ACTIONS:
            continue
        d: dict[str, Any] = dict(item)
        payload = d.get("payload")
        if isinstance(payload, Mapping):  # a StepEvent envelope around the score
            d = {
                **payload,
                "task_id": d.get("task_id") or payload.get("task_id", ""),
                "repo": d.get("repo") or payload.get("repo", ""),
            }
        if not d.get("repo") and default_repo:
            d["repo"] = default_repo
        scores.append(d)
    loaded = load_oracle_scores(scores)
    if raw and not loaded:
        raise CliError(
            f"--oracle: {len(raw)} entr{'y' if len(raw) == 1 else 'ies'} but no per-task oracle "
            "score among them (a score has a task_id; an event's action is one of "
            f"{sorted(ORACLE_SCORE_ACTIONS)}) — export GET /oracle/<repo> or an ORACLE run's "
            "events/log"
        )
    return loaded


def load_controls_export(raw: Any) -> ControlsVerdict:
    """The repo's negative-controls verdict from ``GET /oracle/{repo}/controls`` (a
    ``controls.report`` payload: ``passed``, ``escapes``, ``n_rows``…, plus ``run_id`` /
    ``reported_at``) or from a ``controls`` run body (``GET /runs/{id}`` → ``counts``).
    Reduced by the same :meth:`ControlsVerdict.from_counts` the server routes on."""
    if isinstance(raw, Mapping) and isinstance(raw.get("counts"), Mapping):
        counts: Mapping[str, Any] = raw["counts"]
        if "passed" in counts:
            return ControlsVerdict.from_counts(
                counts,
                run_id=str(raw.get("id", "") or ""),
                created=str(raw.get("finished", "") or ""),
            )
    if not isinstance(raw, Mapping) or "passed" not in raw:
        raise CliError(
            "--controls must be a controls report (GET /oracle/<repo>/controls) or a "
            "'controls' run body with counts — no 'passed' field found"
        )
    return ControlsVerdict.from_counts(raw)


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
    """Derive ``test.add`` items for oracle-held cells; validate them before writing."""
    path, rows = _rows(args)
    wd = workdir_of(args)
    policy = load_policy(args.policy_json)
    controls = (
        load_controls_export(_read_json(args.controls, what="--controls"))
        if args.controls
        else None
    )
    cmap = build_capability_map(
        rows, projection=PROJECTIONS[args.by], policy=policy, controls=controls
    )
    scores = load_oracle_export(_read_json(args.oracle, what="--oracle")) if args.oracle else []
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
    out: dict[str, Any] = {
        "ledger": str(path),
        "projection": args.by,
        "controls": controls.to_dict() if controls is not None else None,
        **payload,
    }
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
    """Plan re-measurement for cells on an older apparatus; nothing is queued."""
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


__all__ = [
    "ORACLE_SCORE_ACTIONS",
    "RefusalDecision",
    "cmd_refusals",
    "cmd_remeasure",
    "cmd_strengthen",
    "load_controls_export",
    "load_oracle_export",
    "register",
]
