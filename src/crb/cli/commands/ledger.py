"""``crb ledger`` — import history, verify the chain, roll up cells, export.

Every number printed here carries its ``n`` and its method: ``point = clean/n``
over *eligible* trials (graded, not disqualified, oracle judgeable), the interval
is the Wilson 95% score interval, and the apparatus versions present in the cell
are listed so a reader can see when a cell mixes instruments.

Navigation
----------
What it is:   ``crb ledger import-census | import-aggregates | verify | anchor | stats |
              export`` — the JSONL ledger's import, integrity and roll-up verbs.
What it does: Imports the June-2026 census with honest classification (needs the task
              files and repo configs; packs are stored and rows re-chained); imports
              aggregate rows for reference only; walks the chain and re-derives false-Q1 =
              0 (exit 1 on any break or violation) — with ``--store``, the database's
              grade ledger and its audit trail (``events``), printing both heads; prints
              per-cell n / point / Wilson interval / false-Q1 with the apparatus versions
              present; exports rows; ``anchor`` writes the chain heads to a file meant to
              leave the machine, and ``verify --anchor`` checks the ledger still extends it.
How:          ``JsonlLedger`` reads; ``crb.core.legacy`` importers; ``group_by_cell`` +
              ``cell_stats`` for ``stats``; ``verify --store --anchor`` reads every anchored
              row in one ordered pass per chain; every command prints JSON or a plain table.
Layer:        cli — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md,
              docs/adr/0007-abstract-cell-export-only.md,
              docs/adr/0029-the-audit-trail-is-hash-chained.md
Works with:   src/crb/core/ledger.py (``JsonlLedger``, ``cell_stats``, ``false_q1_total``),
              src/crb/core/anchor.py (the anchor file, its checks and its no-overwrite write),
              src/crb/core/legacy.py (the census importers and their provenance stamp),
              src/crb/server/routes/ledger.py (the HTTP twin over the database),
              docs/REPRODUCING-THE-CENSUS.md (the procedure these verbs implement),
              docs/EVIDENCE-AND-CLAIMS.md#5-the-legacy-belt-caveat-on-the-census-ledger
Tested by:    tests/test_cli.py, tests/test_cli_ledger_store.py, tests/test_cli_ledger_anchor.py
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
import contextlib
import datetime as _dt
import json
import os
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
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
from crb.core.anchor import (
    AnchorError,
    ChainHead,
    HashAt,
    LoadedAnchor,
    anchor_dir_lock,
    build_anchor,
    check_anchor,
    check_anchor_links,
    is_inside,
    load_anchor,
    load_anchor_dir,
    write_anchor,
)
from crb.core.checks import ARMS
from crb.core.federated import export_abstract
from crb.core.grade import FalseQ1Violation, MisattributionViolation
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
from crb.core.version import APPARATUS_VERSION, __version__

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
    """Add ``crb ledger import-census | import-aggregates | verify | anchor | stats | export``."""
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
    v.add_argument(
        "--store",
        action="store_true",
        help="verify the database instead: the grade ledger AND the audit trail (events), "
        "and print both heads to record outside the store",
    )
    v.add_argument("--database-url", default=None, help="with --store: overrides CRB_DATABASE_URL")
    v.add_argument(
        "--anchor",
        default="",
        help="also check an anchor file, or every anchor in a directory, written by "
        "`crb ledger anchor`: the ledger must still extend each one (exit 1 if not)",
    )
    add_common(v)
    v.set_defaults(func=cmd_verify)

    an = ls.add_parser(
        "anchor",
        help="write the chain heads to an anchor file, to be kept off this machine",
    )
    an.add_argument(
        "--out",
        required=True,
        help="anchor directory: not inside the ledger's data directory; copy it off the "
        "machine (docs/LEDGER-ANCHORS.md)",
    )
    an.add_argument("--path", default="", help="ledger path (default <workdir>/ledger.jsonl)")
    an.add_argument(
        "--store",
        action="store_true",
        help="anchor the database instead: the grade ledger and the audit trail (events)",
    )
    an.add_argument("--database-url", default=None, help="with --store: overrides CRB_DATABASE_URL")
    an.add_argument(
        "--created-at",
        default="",
        help="the time to record, ISO 8601 with a zone (default: now, UTC)",
    )
    add_common(an)
    an.set_defaults(func=cmd_anchor)

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
    """Walk the chain and re-derive false-Q1 = 0; exit 1 on a break or a violation.
    ``--store`` verifies the database's grade ledger and its audit trail instead."""
    if getattr(args, "store", False):
        return _verify_store(args)
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
    if getattr(args, "anchor", ""):
        out["anchors"] = _anchor_report(args.anchor, "jsonl", _jsonl_hash_at(ledger.path))
        out["ok"] = bool(out.get("ok")) and out["anchors"]["ok"]
    if args.json:
        print_json(out)
        return EXIT_OK if out.get("ok") else EXIT_NEGATIVE
    if out.get("chain_ok"):
        lines = [
            f"{ledger.path}: {out['rows']} rows, chain OK, false-Q1 {out['false_q1']}, "
            f"clean-without-pack {out['clean_without_pack']}, "
            f"apparatus {out['apparatus_versions']}"
        ]
    else:
        lines = [f"{ledger.path}: CHAIN BROKEN — {out['error']}"]
    if "anchors" in out:
        lines.extend(_anchor_lines(out["anchors"]))
    print_lines(lines)
    return EXIT_OK if out.get("ok") else EXIT_NEGATIVE


def _verify_store(args: argparse.Namespace) -> int:
    """The database twin of ``verify`` (the same walk ``GET /ledger/verify`` serves): the
    ``grades`` chain and false-Q1 over its rows, the ``events`` chain (ADR-0029), and the
    head ``row_hash`` of each — the values docs/DEPLOYMENT.md §8 records outside the store.
    Exit 1 when either chain is broken or false-Q1 is not 0."""
    from crb.store.db import database_url, make_engine, make_session_factory  # noqa: PLC0415
    from crb.store.events import verify_events  # noqa: PLC0415
    from crb.store.ledger import DbLedger  # noqa: PLC0415

    url = database_url(getattr(args, "database_url", None))
    engine = make_engine(url)
    try:
        factory = make_session_factory(engine)
        ledger = DbLedger(factory)
        out: dict[str, Any] = {"store": engine.dialect.name}
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
                    "head_row_hash": rows[-1].row_hash if rows else "",
                }
            )
        except LedgerIntegrityError as e:
            out.update({"chain_ok": False, "error": str(e), "head_row_hash": ""})
        except (FalseQ1Violation, MisattributionViolation, ValueError, TypeError) as e:
            # a stored row the reader refuses (edited underneath its triggers): reported,
            # and the audit trail is still walked (P-702)
            out.update(
                {
                    "chain_ok": False,
                    "error": f"a stored row the reader refuses — {type(e).__name__}: {e}",
                    "head_row_hash": "",
                }
            )
        events = verify_events(factory)
        out["events"] = events.to_dict()
        out["ok"] = bool(
            out.get("chain_ok")
            and out.get("false_q1") == 0
            and out.get("clean_without_pack") == 0
            and events.ok
        )
        if getattr(args, "anchor", ""):
            reader = _store_hash_at(factory)
            out["anchors"] = _anchor_report(
                args.anchor, engine.dialect.name, reader, reader.prefetch
            )
            out["ok"] = out["ok"] and out["anchors"]["ok"]
    finally:
        engine.dispose()
    if args.json:
        print_json(out)
    else:
        grades = (
            f"{out['rows']} rows, chain OK, false-Q1 {out['false_q1']}, "
            f"clean-without-pack {out['clean_without_pack']}"
            if out.get("chain_ok")
            else f"CHAIN BROKEN — {out['error']}"
        )
        ev = out["events"]
        trail = (
            f"{ev['rows']} events, events chain OK"
            if ev["chain_ok"]
            else f"events chain BROKEN — {ev['detail']}"
        )
        lines = [
            f"{out['store']} store: {grades}",
            f"audit trail: {trail}",
            f"heads to record outside the store: grades {out['head_row_hash'] or '-'} · "
            f"events {ev['head_row_hash'] or '-'}",
        ]
        if "anchors" in out:
            lines.extend(_anchor_lines(out["anchors"]))
        print_lines(lines)
    return EXIT_OK if out["ok"] else EXIT_NEGATIVE


# ---------------------------------------------------------------------------
# Anchors (docs/LEDGER-ANCHORS.md): read the ledger, never write it
# ---------------------------------------------------------------------------


def _jsonl_hash_at(path: Path) -> HashAt:
    """``hash_at`` over a JSONL ledger: the ``row_hash`` of its n-th non-blank line, the file
    read once on first use. An unreadable line has hash ``""``, so an anchor on it fails
    as rewritten; the chain's own verification names the line."""
    hashes: list[str] | None = None

    def at(chain: str, n: int) -> str | None:
        nonlocal hashes
        if chain != "grades":
            return None
        if hashes is None:
            hashes = JsonlLedger(path).row_hashes()
        return hashes[n - 1] if 0 < n <= len(hashes) else None

    return at


class _StoreHashAt:
    """``hash_at`` over the database: the n-th row of ``grades`` by ``seq`` or of ``events``
    by ``id``. :meth:`prefetch` reads every requested position of a chain in one ordered pass
    (stopping at the highest), so checking many anchors costs one read per chain, not one per
    anchor; a position not prefetched is read the same way on first use. No write."""

    CHAINS = ("grades", "events")

    def __init__(self, factory: Any) -> None:
        self._factory = factory
        self._cache: dict[tuple[str, int], str | None] = {}

    def prefetch(self, wanted: Mapping[str, Iterable[int]]) -> None:
        from sqlalchemy import select  # noqa: PLC0415

        from crb.store.models import Event, Grade  # noqa: PLC0415

        for chain, positions in wanted.items():
            todo = {n for n in positions if n > 0 and (chain, n) not in self._cache}
            if chain not in self.CHAINS or not todo:
                continue
            q = (
                select(Grade.row_hash).order_by(Grade.seq)
                if chain == "grades"
                else select(Event.row_hash).order_by(Event.id)
            )
            found: dict[int, str] = {}
            with self._factory() as s:
                rows = s.execute(q.limit(max(todo)).execution_options(yield_per=1000))
                for i, h in enumerate(rows.scalars(), start=1):
                    if i in todo:
                        found[i] = str(h)
            for n in todo:
                self._cache[(chain, n)] = found.get(n)  # None: past the end of the chain

    def __call__(self, chain: str, n: int) -> str | None:
        if n <= 0 or chain not in self.CHAINS:
            return None
        if (chain, n) not in self._cache:
            self.prefetch({chain: [n]})
        return self._cache[(chain, n)]


def _store_hash_at(factory: Any) -> _StoreHashAt:
    """The database's ``hash_at`` (:class:`_StoreHashAt`)."""
    return _StoreHashAt(factory)


def _wanted_positions(anchors: Iterable[LoadedAnchor], source: str) -> dict[str, set[int]]:
    """Every (chain, row count) the anchors of ``source`` will ask ``hash_at`` for."""
    wanted: dict[str, set[int]] = {}
    for la in anchors:
        if la.anchor.get("source") != source:
            continue  # check_anchor reports the mismatch without reading a row
        for name, head in la.anchor["chains"].items():
            if head["rows"] > 0:
                wanted.setdefault(name, set()).add(head["rows"])
    return wanted


def _anchor_report(
    target_arg: str,
    source: str,
    hash_at: HashAt,
    prefetch: Callable[[Mapping[str, Iterable[int]]], None] | None = None,
) -> dict[str, Any]:
    """Check one anchor file, or every anchor in a directory (and that directory's anchor
    chain), against today's ledger. ``first_broken`` names the oldest anchor that no longer
    holds. ``prefetch``, when given, is handed every position the anchors will read first,
    so the reader can fetch them together."""
    target = Path(target_arg).expanduser()
    try:
        if target.is_dir():
            anchors: list[LoadedAnchor] = load_anchor_dir(target)
            links = check_anchor_links(anchors)
        elif target.is_file():
            anchors, links = [load_anchor(target)], []
        else:
            raise CliError(f"--anchor {target} is neither an anchor file nor a directory")
    except AnchorError as e:
        raise CliError(str(e)) from e
    if prefetch is not None:
        prefetch(_wanted_positions(anchors, source))
    results = []
    for la in anchors:
        faults = check_anchor(la.anchor, source=source, hash_at=hash_at)
        results.append(
            {
                "file": la.path.name,
                "created_at": la.anchor.get("created_at", ""),
                "chains": la.anchor["chains"],
                "holds": not faults,
                "faults": faults,
            }
        )
    first = next((r["file"] for r in results if not r["holds"]), None)
    empty = ["no anchor files (anchor-*.json) in the directory"] if not anchors else []
    return {
        "target": str(target),
        "checked": len(results),
        "ok": first is None and not links and not empty,
        "first_broken": first,
        "anchor_chain_faults": links + empty,
        "results": results,
    }


def _anchor_lines(rep: dict[str, Any]) -> list[str]:
    """The text form of :func:`_anchor_report`: one line when every anchor holds, a loud
    line per fault otherwise."""
    if rep["ok"]:
        return [f"anchors: {rep['checked']} checked in {rep['target']}, every one still holds"]
    lines: list[str] = []
    for r in rep["results"]:
        lines.extend(f"ANCHOR BROKEN — {r['file']}: {f}" for f in r["faults"])
    lines.extend(f"ANCHOR CHAIN BROKEN — {f}" for f in rep["anchor_chain_faults"])
    if rep["first_broken"]:
        lines.append(f"the first anchor that no longer holds: {rep['first_broken']}")
    return lines


@dataclass
class _Anchored:
    """A ledger opened for anchoring: its kind, where its data lives (``None`` when it is not
    a local file), each chain's head, the faults of its own verification and its reader."""

    source: str
    data_dir: Path | None
    heads: dict[str, ChainHead]
    hash_at: HashAt
    faults: list[str] = field(default_factory=list)
    named_dir: Path | None = None  # the folder named on the command line, when the file is a link


@contextlib.contextmanager
def _open_for_anchor(args: argparse.Namespace) -> Iterator[_Anchored]:
    """Verify the ledger (the JSONL file, or with ``--store`` the database's two chains) and
    read its heads. Nothing is written; a missing SQLite file is refused rather than
    created."""
    if not args.store:
        ledger = _ledger(args)
        hash_at = _jsonl_hash_at(ledger.path)
        faults: list[str] = []
        try:
            n = ledger.verify()
        except LedgerIntegrityError as e:
            n, faults = 0, [f"grades: CHAIN BROKEN — {e}"]
        head = (hash_at("grades", n) or "") if n else ""
        yield _Anchored(
            "jsonl",
            ledger.path.resolve().parent,
            {"grades": ChainHead(n, head)},
            hash_at,
            faults,
            ledger.path.absolute().parent,
        )
        return
    from sqlalchemy.engine import make_url  # noqa: PLC0415

    from crb.store.db import database_url, make_engine, make_session_factory  # noqa: PLC0415
    from crb.store.events import verify_events  # noqa: PLC0415
    from crb.store.ledger import DbLedger  # noqa: PLC0415

    url = database_url(getattr(args, "database_url", None))
    parsed = make_url(url)
    data_dir: Path | None = None
    named_dir: Path | None = None
    if parsed.get_backend_name() == "sqlite":
        db = parsed.database or ""
        if not db or db == ":memory:" or not Path(db).is_file():
            raise CliError(f"no SQLite database at {db or '(memory)'}; nothing to anchor")
        data_dir = Path(db).resolve().parent
        named_dir = Path(db).absolute().parent
    engine = make_engine(url)
    try:
        factory = make_session_factory(engine)
        store_hash_at = _store_hash_at(factory)
        faults = []
        try:
            grades_n = DbLedger(factory).verify()
        except (
            LedgerIntegrityError,
            FalseQ1Violation,
            MisattributionViolation,
            ValueError,
            TypeError,
        ) as e:
            grades_n, faults = 0, [f"grades: CHAIN BROKEN — {type(e).__name__}: {e}"]
        events = verify_events(factory)
        if not events.ok:
            faults.append(f"events: CHAIN BROKEN — {events.detail}")
        grades_head = (store_hash_at("grades", grades_n) or "") if grades_n else ""
        heads = {
            "grades": ChainHead(grades_n, grades_head),
            "events": ChainHead(events.rows, events.head if events.rows else ""),
        }
        yield _Anchored(engine.dialect.name, data_dir, heads, store_hash_at, faults, named_dir)
    finally:
        engine.dispose()


def _created_at(value: str) -> str:
    """``--created-at`` as ``YYYY-MM-DDTHH:MM:SSZ``; the current UTC time when not given — the
    one clock read, here at the edge."""
    if not value:
        return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        t = _dt.datetime.fromisoformat(value)
    except ValueError as e:
        raise CliError(f"--created-at {value!r} is not an ISO 8601 time") from e
    if t.tzinfo is None:
        raise CliError(f"--created-at {value!r} has no time zone; add Z or +00:00")
    return t.astimezone(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _same_device(a: Path, b: Path) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def cmd_anchor(args: argparse.Namespace) -> int:
    """Write an anchor of the ledger's heads into ``--out``, chained to the directory's last
    anchor. Refused: an ``--out`` inside the ledger's data directory, a broken chain, a ledger
    that no longer extends the directory's last anchor, a broken anchor chain in the
    directory. Never overwrites. Exit 1 on a finding, 2 on a refusal of the request."""
    out_dir = Path(args.out).expanduser()
    created_at = _created_at(args.created_at)
    created = not out_dir.exists()
    try:
        # one writer per directory, from before the heads are read until the file is written
        with anchor_dir_lock(out_dir):
            try:
                return _anchor_locked(args, out_dir, created_at)
            finally:
                if created:  # a request that wrote nothing leaves no directory behind
                    with contextlib.suppress(OSError):
                        out_dir.rmdir()  # removes it only when empty
    except AnchorError as e:
        raise CliError(str(e)) from e


def _anchor_locked(args: argparse.Namespace, out_dir: Path, created_at: str) -> int:
    """:func:`cmd_anchor` under the directory's lock: read the heads, check the directory,
    write the anchor."""
    with _open_for_anchor(args) as led:
        inside = next(
            (d for d in (led.data_dir, led.named_dir) if d is not None and is_inside(out_dir, d)),
            None,
        )
        if inside is not None:
            raise CliError(
                f"--out {out_dir} is inside the ledger's data directory {inside}: an "
                "anchor kept beside the data it anchors proves nothing. Name a directory "
                "elsewhere, ideally a clone of a repository held off this machine "
                "(docs/LEDGER-ANCHORS.md)."
            )
        if all(h.rows == 0 for h in led.heads.values()) and not led.faults:
            raise CliError("the ledger is empty; there is nothing to anchor")
        result: dict[str, Any] = {
            "source": led.source,
            "chains": {k: v.to_dict() for k, v in sorted(led.heads.items())},
            "out": str(out_dir),
            "written": False,
            "anchor": "",
            "warnings": [],
            "faults": list(led.faults),
        }
        previous: tuple[str, str] | None = None
        if not led.faults:
            try:
                existing = load_anchor_dir(out_dir)
            except AnchorError as e:
                raise CliError(str(e)) from e
            result["faults"].extend(
                f"the anchor chain in {out_dir} is broken — {f}"
                for f in check_anchor_links(existing)
            )
            if existing and not result["faults"]:
                last = existing[-1]
                if last.anchor.get("source") != led.source:
                    raise CliError(
                        f"{out_dir} holds anchors of a {last.anchor.get('source')} ledger; "
                        f"keep one anchor directory per ledger"
                    )
                result["faults"].extend(
                    f"the ledger no longer extends {last.path.name} — {f}"
                    for f in check_anchor(last.anchor, source=led.source, hash_at=led.hash_at)
                )
                previous = (last.path.name, last.sha256)
        if result["faults"]:
            result["ok"] = False
            _print_anchor(args, result)
            return EXIT_NEGATIVE
        anchor = build_anchor(
            source=led.source,
            chains=led.heads,
            apparatus=APPARATUS_VERSION,
            crb_version=__version__,
            created_at=created_at,
            previous=previous,
        )
        try:
            path, written = write_anchor(out_dir, anchor)
        except AnchorError as e:
            raise CliError(str(e)) from e
        result.update({"anchor": str(path), "written": written, "ok": True})
        if written:
            result["previous_anchor"] = anchor["previous_anchor"]
        if led.data_dir is None:
            result["warnings"].append(
                "the database is not a local file, so this command cannot tell whether the "
                "anchor directory shares a machine with it; copy the anchor off this machine"
            )
        elif _same_device(out_dir, led.data_dir):
            result["warnings"].append(
                f"{out_dir} is on the same filesystem as the ledger ({led.data_dir}); the "
                "anchor proves nothing until it is copied off this machine "
                "(docs/LEDGER-ANCHORS.md)"
            )
    _print_anchor(args, result)
    return EXIT_OK


def _print_anchor(args: argparse.Namespace, result: dict[str, Any]) -> None:
    if args.json:
        print_json(result)
        return
    for w in result["warnings"]:
        print(f"warning: {w}", file=sys.stderr)
    if result["faults"]:
        print_lines(
            [*(f"NOT ANCHORED — {f}" for f in result["faults"]), "no anchor file was written"]
        )
        return
    chains = " · ".join(
        f"{name} {c['rows']} rows, head {c['head_row_hash'] or '-'}"
        for name, c in result["chains"].items()
    )
    verb = "anchor written" if result["written"] else "already anchored, nothing written"
    print_lines(
        [
            f"{verb} -> {result['anchor']}",
            f"  {result['source']}: {chains}",
            "  keep it off this machine, held by someone who cannot write the ledger "
            "(docs/LEDGER-ANCHORS.md)",
        ]
    )


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
    # ... and per apparatus, context arm and class-set version (ADR-0025 item 1, ADR-0026):
    # a reading never pools two of any, so each is its own line
    groups = [
        (arm, key, rs)
        for arm in ARMS
        for key, rs in sorted(group_by_cell(rows_for_checks(rows, arm), key_fields=fields).items())
    ]
    split: list[tuple[str, tuple[str, ...], tuple[str, str, str], list[Any]]] = []
    for arm, key, rs in groups:
        by_reading: dict[tuple[str, str, str], list[Any]] = {}
        for r in rs:
            by_reading.setdefault((r.apparatus_version, r.context_arm, r.taxonomy), []).append(r)
        split.extend((arm, key, rk, sub) for rk, sub in sorted(by_reading.items()))
    stats: list[dict[str, Any]] = []
    for arm, key, (apparatus, context_arm, taxonomy), rs in split:
        s = cell_stats(rs)
        d: dict[str, Any] = dict(zip(fields, key, strict=True))
        d.update(
            {
                "apparatus": apparatus,
                "context_arm": context_arm,
                "taxonomy": taxonomy,
                "n_tasks": s.n_tasks,
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
            # the reading key a cell is split by (P-727): two lines of one cell differ here
            "arm",
            "class_set",
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
                d["context_arm"] or "-",
                d["taxonomy"] or "-",
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
