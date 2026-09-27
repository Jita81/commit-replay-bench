"""``crb ledger`` — import history, verify the chain, roll up cells, export.

Every number printed here carries its ``n`` and its method: ``point = clean/n``
over *eligible* trials (graded, not disqualified, oracle judgeable), the interval
is the Wilson 95% score interval, and the apparatus versions present in the cell
are listed so a reader can see when a cell mixes instruments.

Navigation
----------
What it is:   ``crb ledger import-census | import-aggregates | verify | stats | export`` —
              the JSONL ledger's import, integrity and roll-up verbs.
What it does: Imports the June-2026 census with honest classification (needs the task
              files and repo configs; packs are stored and rows re-chained); imports
              aggregate rows for reference only; walks the chain and re-derives false-Q1 =
              0 (exit 1 on any break or violation); prints per-cell n / point / Wilson
              interval / false-Q1 with the apparatus versions present; exports rows.
How:          ``JsonlLedger`` reads; ``crb.core.legacy`` importers; ``group_by_cell`` +
              ``cell_stats`` for ``stats``; every command prints JSON or a plain table.
Layer:        cli — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md,
              docs/adr/0007-abstract-cell-export-only.md
Works with:   src/crb/core/ledger.py (``JsonlLedger``, ``cell_stats``, ``false_q1_total``),
              src/crb/core/legacy.py (the census importers and their provenance stamp),
              src/crb/server/routes/ledger.py (the HTTP twin over the database),
              docs/REPRODUCING-THE-CENSUS.md (the procedure these verbs implement),
              docs/EVIDENCE-AND-CLAIMS.md#5-the-legacy-belt-caveat-on-the-census-ledger
Tested by:    tests/test_cli.py
Touch when:   never for a new repository; when a ``stats`` grouping field is added
              (``GROUP_ALIASES`` here and ``BY_ALIASES`` in
              src/crb/server/routes/capability.py); ``export --abstract`` is the same export the API serves —
              see FINDINGS.
Claims:       ``verify`` exit 0 = chain intact and false-Q1 = 0 over the rows on disk; the
              census rows it imports carry ``v3-legacy`` and are never blended with
              current-apparatus rows in a claim
              (docs/EVIDENCE-AND-CLAIMS.md#4-the-apparatus-stamp--evidence-expires).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from crb.cli.commands import (
    EXIT_NEGATIVE,
    EXIT_OK,
    CliError,
    add_common,
    event_printer,
    print_json,
    print_lines,
    table,
    workdir_of,
)
from crb.core.checks import ARMS
from crb.core.federated import export_abstract
from crb.core.ledger import (
    CELL_FIELDS,
    GradeRow,
    JsonlLedger,
    LedgerIntegrityError,
    cell_stats,
    false_q1_total,
    group_by_cell,
    rows_for_checks,
)
from crb.core.legacy import (
    CENSUS_PROVENANCE,
    import_benchmark_ledger,
    import_census,
    import_census_tasks,
    import_repo_configs,
)
from crb.core.spec import TaskSpec

_CENSUS_HOME = Path("~/.expansion-bench").expanduser()

#: ``--by`` aliases → GradeRow attributes. Any listed attribute may be grouped on.
GROUP_ALIASES: dict[str, str] = {
    "class": "capability_class",
    "capability_class": "capability_class",
    "size": "size",
    "language": "language",
    "lang": "language",
    "model": "model",
    "builder": "builder",
    "provider": "provider",
    "step": "process_step",
    "process_step": "process_step",
    "mode": "mode",
    "belt_set": "belt_set",
    "repo": "repo",
    "pool": "pool",
    "provenance": "provenance",
    "apparatus": "apparatus_version",
}


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``crb ledger import-census | import-aggregates | verify | stats | export``."""
    p = sub.add_parser("ledger", help="import, verify, summarise and export the grade ledger")
    ls = p.add_subparsers(dest="ledger_cmd", metavar="<subcommand>")

    ic = ls.add_parser(
        "import-census", help="import the expansion-bench census (configs + tasks + grades)"
    )
    ic.add_argument("--grades", default=str(_CENSUS_HOME / "state" / "grades.jsonl"))
    ic.add_argument("--tasks-dir", default=str(_CENSUS_HOME / "state"))
    ic.add_argument("--configs", default=str(_CENSUS_HOME / "configs.json"))
    ic.add_argument("--path", default="", help="ledger path (default <workdir>/ledger.jsonl)")
    ic.add_argument("--no-packs", action="store_true", help="do not write imported evidence packs")
    ic.add_argument("--events", action="store_true", help="stream legacy.* events on stderr")
    add_common(ic)
    ic.set_defaults(func=cmd_import_census)

    ia = ls.add_parser(
        "import-aggregates",
        help="import an Athena benchmark_ledger.jsonl as reference-only AggregateRows",
    )
    ia.add_argument("source", help="path to benchmark_ledger.jsonl")
    add_common(ia)
    ia.set_defaults(func=cmd_import_aggregates)

    v = ls.add_parser("verify", help="walk the hash chain and re-check false-Q1 = 0")
    v.add_argument("--path", default="", help="ledger path (default <workdir>/ledger.jsonl)")
    add_common(v)
    v.set_defaults(func=cmd_verify)

    st = ls.add_parser("stats", help="cell statistics (n, point, Wilson CI, false-Q1)")
    st.add_argument("--path", default="", help="ledger path (default <workdir>/ledger.jsonl)")
    st.add_argument(
        "--by",
        default="class,size",
        help=f"comma-separated grouping: {', '.join(sorted(set(GROUP_ALIASES)))}",
    )
    add_common(st)
    st.set_defaults(func=cmd_stats)

    ex = ls.add_parser("export", help="export ledger rows as JSON lines")
    ex.add_argument("--path", default="", help="ledger path (default <workdir>/ledger.jsonl)")
    ex.add_argument("--out", default="", help="write to this file instead of stdout")
    ex.add_argument(
        "--abstract",
        action="store_true",
        help="cell-level abstract export (no ids, no code) — see crb.core.federated",
    )
    add_common(ex)
    ex.set_defaults(func=cmd_export)

    p.set_defaults(func=lambda args: _usage(p))


def _usage(p: argparse.ArgumentParser) -> int:
    """``crb ledger`` with no subcommand: help + usage-error exit."""
    p.print_help()
    return 2


def _ledger(args: argparse.Namespace) -> JsonlLedger:
    """The ledger at ``--path``, else ``<workdir>/ledger.jsonl``."""
    wd = workdir_of(args)
    path = Path(args.path).expanduser() if getattr(args, "path", "") else wd.ledger_path
    return JsonlLedger(path)


def _existing_pack_hashes(ledger: JsonlLedger) -> set[str]:
    """Pack hashes already cited by the ledger (an import skips their rows)."""
    return {r.evidence_pack_hash for r in ledger.rows() if r.evidence_pack_hash}


def cmd_import_census(args: argparse.Namespace) -> int:
    """Import the census: configs → tasks → grades (classified from the task files),
    packs written under their hash, rows re-chained, the chain verified afterwards."""
    wd = workdir_of(args)
    grades, tasks_dir, configs = (
        Path(args.grades).expanduser(),
        Path(args.tasks_dir).expanduser(),
        Path(args.configs).expanduser(),
    )
    for p, what in ((grades, "--grades"), (configs, "--configs")):
        if not p.is_file():
            raise CliError(f"{what} {p} is not a file")
    if not tasks_dir.is_dir():
        raise CliError(f"--tasks-dir {tasks_dir} is not a directory")
    ledger = _ledger(args)
    on_event = event_printer(sys.stderr) if args.events else None

    # 1. configs → repos/ (config-only; no clone path is known to the census)
    configs_written = 0
    for name, config in import_repo_configs(configs).items():
        if not wd.repo_file(name).exists():
            wd.save_repo(config, None)
            configs_written += 1

    # 2. tasks → tasks/<repo>.jsonl (idempotent by task_id)
    tasks_by_repo: dict[str, list[TaskSpec]] = {}
    for t in import_census_tasks(tasks_dir, configs, on_event=on_event):
        tasks_by_repo.setdefault(t.repo, []).append(t)
    tasks_written = sum(wd.append_tasks(repo, ts) for repo, ts in tasks_by_repo.items())

    # 3. grades → ledger (idempotent by evidence-pack hash) + packs
    existing = _existing_pack_hashes(ledger)
    skips: Counter[str] = Counter()

    def on_skip(action: str, payload: Any) -> None:
        if action == "legacy.skip":
            skips[str(payload.get("reason", "?"))] += 1
        if on_event is not None:
            on_event(action, payload)

    read = imported = already = packs = 0
    belt_sets: Counter[str] = Counter()
    modes: Counter[str] = Counter()
    for ig in import_census(grades, tasks_dir, configs, on_event=on_skip):
        read += 1
        if ig.pack_hash in existing:
            already += 1
            continue
        if not args.no_packs:
            wd.write_pack(ig.pack_hash, ig.pack)
            packs += 1
        ledger.append(ig.row)
        existing.add(ig.pack_hash)
        imported += 1
        belt_sets[ig.row.belt_set] += 1
        modes[ig.row.mode] += 1

    rows = list(ledger.rows())
    fq1 = false_q1_total(rows)
    verified = ledger.verify()
    out = {
        "source": {"grades": str(grades), "tasks_dir": str(tasks_dir), "configs": str(configs)},
        "provenance": CENSUS_PROVENANCE,
        "configs_imported": configs_written,
        "tasks_imported": tasks_written,
        "grades_read": read,
        "grades_imported": imported,
        "grades_already_present": already,
        "grades_skipped": dict(skips),
        "packs_written": packs,
        "belt_sets": dict(belt_sets),
        "modes": dict(modes),
        "ledger": str(ledger.path),
        "ledger_rows": len(rows),
        "chain_verified_rows": verified,
        "false_q1": fq1,
    }
    if args.json:
        print_json(out)
    else:
        print_lines(
            [
                f"census import -> {ledger.path}",
                f"  configs {configs_written}, tasks {tasks_written}, grades read {read}: "
                f"imported {imported}, already present {already}, skipped {sum(skips.values())}",
                f"  belt sets {dict(belt_sets)}; modes {dict(modes)}; packs written {packs}",
                f"  ledger rows {len(rows)}, chain verified {verified}, false-Q1 {fq1}",
            ]
        )
    return EXIT_OK if fq1 == 0 else EXIT_NEGATIVE


def cmd_import_aggregates(args: argparse.Namespace) -> int:
    """Import aggregate rows for reference only — they never enter the graded ledger."""
    wd = workdir_of(args)
    src = Path(args.source).expanduser()
    if not src.is_file():
        raise CliError(f"{src} is not a file")
    rows = list(import_benchmark_ledger(src))
    wd.root.mkdir(parents=True, exist_ok=True)
    existing: set[str] = set()
    if wd.aggregates_path.exists():
        with wd.aggregates_path.open("r", encoding="utf-8") as f:
            existing = {str(json.loads(ln).get("raw_hash", "")) for ln in f if ln.strip()}
    written = 0
    with wd.aggregates_path.open("a", encoding="utf-8") as f:
        for r in rows:
            if r.raw_hash in existing:
                continue
            f.write(json.dumps(r.to_dict(), sort_keys=True, ensure_ascii=False) + "\n")
            existing.add(r.raw_hash)
            written += 1
    out = {
        "source": str(src),
        "read": len(rows),
        "written": written,
        "already_present": len(rows) - written,
        "file": str(wd.aggregates_path),
        "untrusted": sum(1 for r in rows if not r.trusted),
        "note": (
            "AggregateRows are reference-only: they carry no per-trial belts or evidence "
            "pack and never enter the grade ledger, cell statistics or routing."
        ),
    }
    if args.json:
        print_json(out)
    else:
        print_lines(
            [
                f"imported {written} aggregate row(s) from {src} -> {wd.aggregates_path} "
                f"({len(rows) - written} already present; {out['untrusted']} untrusted)",
                f"  {out['note']}",
            ]
        )
    return EXIT_OK


def cmd_verify(args: argparse.Namespace) -> int:
    """Walk the chain and re-derive false-Q1 = 0; exit 1 on a break or a violation."""
    ledger = _ledger(args)
    out: dict[str, Any] = {"ledger": str(ledger.path)}
    try:
        n = ledger.verify()
        rows = list(ledger.rows())
        fq1 = false_q1_total(rows)
        no_pack = sum(1 for r in rows if r.clean and not r.evidence_pack_hash)
        out.update(
            {
                "rows": n,
                "chain_ok": True,
                "false_q1": fq1,
                "clean_without_pack": no_pack,
                "belt_sets": dict(Counter(r.belt_set for r in rows)),
                "apparatus_versions": sorted({r.apparatus_version for r in rows}),
                "ok": fq1 == 0 and no_pack == 0,
            }
        )
    except LedgerIntegrityError as e:
        out.update({"chain_ok": False, "ok": False, "error": str(e)})
    if args.json:
        print_json(out)
    elif out.get("chain_ok"):
        print_lines(
            [
                f"{ledger.path}: {out['rows']} rows, chain OK, false-Q1 {out['false_q1']}, "
                f"clean-without-pack {out['clean_without_pack']}, "
                f"apparatus {out['apparatus_versions']}"
            ]
        )
    else:
        print_lines([f"{ledger.path}: CHAIN BROKEN — {out['error']}"])
    return EXIT_OK if out.get("ok") else EXIT_NEGATIVE


def _group_fields(by: str) -> tuple[str, ...]:
    """``--by`` aliases → cell fields; empty means the full cell key."""
    fields: list[str] = []
    for token in by.split(","):
        t = token.strip().lower()
        if not t:
            continue
        if t not in GROUP_ALIASES:
            raise CliError(f"unknown --by field {token!r}; choose from {sorted(GROUP_ALIASES)}")
        fields.append(GROUP_ALIASES[t])
    return tuple(fields) or CELL_FIELDS


def cmd_stats(args: argparse.Namespace) -> int:
    """Per-cell statistics (n, point, Wilson CI, false-Q1, apparatus versions)."""
    ledger = _ledger(args)
    rows = list(ledger.rows())
    fields = _group_fields(args.by)
    # one cell per key AND checks arm: rows graded with the format step or belt 6 on are
    # never pooled with rows graded without (ADR-0024)
    groups = [
        (arm, key, rs)
        for arm in ARMS
        for key, rs in sorted(group_by_cell(rows_for_checks(rows, arm), key_fields=fields).items())
    ]
    stats: list[dict[str, Any]] = []
    for arm, key, rs in groups:
        s = cell_stats(rs)
        d: dict[str, Any] = dict(zip(fields, key, strict=True))
        d.update(
            {
                "checks": arm,
                "n": s.n,
                "clean": s.clean,
                "point": round(s.point, 4),
                "ci_low": round(s.ci.low, 4),
                "ci_high": round(s.ci.high, 4),
                "disqualified": s.disqualified,
                "errors": s.errors,
                "false_q1": s.false_q1,
                "cost_usd_mean": round(s.cost_usd_mean, 6),
                "latency_s_mean": round(s.latency_s_mean, 3),
                "belt_sets": sorted({r.belt_set for r in rs}),
                "apparatus_versions": list(s.apparatus_versions),
            }
        )
        stats.append(d)
    method = {
        "n": "eligible trials (graded, not disqualified, gold_clean is not False)",
        "point": "clean / n",
        "ci": "Wilson score interval, 95%",
        "false_q1": "clean rows whose recorded belts are not all True (must be 0)",
        "belt_sets": (
            "v5 = five belts (repo_lint_clean may be null: no linter configured); "
            "v4 = four belts; v3-legacy = three belts (source_changed not measured)"
        ),
    }
    out = {
        "ledger": str(ledger.path),
        "rows": len(rows),
        "by": list(fields),
        "false_q1_total": false_q1_total(rows),
        "method": method,
        "cells": stats,
    }
    if args.json:
        print_json(out)
    else:
        headers = [
            *fields,
            "n",
            "clean",
            "point",
            "ci_low",
            "ci_high",
            "dq",
            "err",
            "fq1",
            "belts",
            "apparatus",
            "checks",
        ]
        body = [
            [
                *(d[f] for f in fields),
                d["n"],
                d["clean"],
                f"{d['point']:.3f}",
                f"{d['ci_low']:.3f}",
                f"{d['ci_high']:.3f}",
                d["disqualified"],
                d["errors"],
                d["false_q1"],
                "+".join(d["belt_sets"]),
                "+".join(d["apparatus_versions"]),
                d["checks"],
            ]
            for d in stats
        ]
        lines = list(table(headers, body))
        lines.append("")
        lines.append(
            f"{len(rows)} rows in {ledger.path}; false-Q1 total {out['false_q1_total']}; "
            f"point = clean/n over eligible trials; CI = Wilson 95%"
        )
        print_lines(lines)
    return EXIT_OK


def cmd_export(args: argparse.Namespace) -> int:
    """Rows as JSON lines to stdout or ``--out``; ``--abstract`` writes the allowlisted
    cell-level export instead (no ids, no code — ADR-0007; the same
    :func:`crb.core.federated.export_abstract` the API serves at ``/ledger/export/abstract``)."""
    ledger = _ledger(args)
    rows: list[GradeRow] = list(ledger.rows())
    if args.abstract:
        cells = export_abstract(rows)
        lines = [json.dumps(c, sort_keys=True, ensure_ascii=False) for c in cells]
        rows = []  # nothing row-level leaves an abstract export
    else:
        lines = [json.dumps(r.to_dict(), sort_keys=True, ensure_ascii=False) for r in rows]
    if args.out:
        out_path = Path(args.out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        if args.json:
            print_json({"ledger": str(ledger.path), "lines": len(lines), "out": str(out_path)})
        else:
            print_lines([f"exported {len(lines)} line(s) -> {out_path}"])
    else:
        print_lines(lines)
    return EXIT_OK
