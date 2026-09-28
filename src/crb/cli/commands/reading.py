"""``crb reading register`` — register a reading before its first attempt (ADR-0026 item 2).

A cell is licensed only by a reading registered before its first attempt: the cell, the
hierarchy of context arms (richest first), the look rule, the share of the cell's error budget
it spends, the test author's model and the frozen pool of qualified commits. The CLI writes it
as one JSON line to ``<workdir>/readings.jsonl`` (``--readings`` elsewhere) — the file ``crb
route --readings`` reads — refusing it ``pool_seen`` when a pool commit already has a graded
row under an arm of the hierarchy at this apparatus, and ``budget_spent`` when the cell's
budget cannot cover it. ``crb reading list`` prints what is registered.

Navigation
----------
What it is:   ``crb reading register | list`` — the file workdir's twin of ``POST /readings``.
What it does: Builds the full cell from its flags, freezes the pool by rule — every
              gold-checked task of the cell's class, size and language on file, or every one
              authored since ``--since`` (never a list, DL-097) — refuses an unsealed posture
              for a replayed arm, registers through ``crb.core.reading.register`` against the
              JSONL ledger and the readings already on file, and appends the record; lists the
              registered readings with their spend.
How:          ``Workdir.load_tasks`` → ``register`` (the core's rules, unchanged) → one JSON
              line appended with ``fsync``.
Layer:        cli — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (items 2 to 5)
Works with:   src/crb/core/reading.py (the rules), src/crb/cli/commands/route.py (reads the
              file), src/crb/server/routes/readings.py (the same act over the database)
Tested by:    tests/test_cli_reading.py
Touch when:   never for a new repository; the reading's shape changes (the core first); never for a
              new repository.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from crb.cli.commands import (
    EXIT_OK,
    CliError,
    add_common,
    print_json,
    print_lines,
    table,
    workdir_of,
)
from crb.core.context_arm import BASE_S2, parse_arm
from crb.core.ledger import CELL_FIELDS, LABEL_CHANGE_ID, JsonlLedger, is_sealed_class
from crb.core.reading import RULE_LOOK_V1, RULES, Reading, ReadingRefused, pool_by_rule
from crb.core.reading import register as register_reading
from crb.core.taxonomy import GLOBAL_CLASS_SET
from crb.core.version import APPARATUS_VERSION

#: The file a workdir's readings live in (one JSON object per line).
READINGS_FILE = "readings.jsonl"


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``crb reading``."""
    p = sub.add_parser("reading", help="register a reading before its first attempt")
    rs = p.add_subparsers(dest="reading_cmd", metavar="<subcommand>")
    reg = rs.add_parser("register", help="register a reading (refused pool_seen / budget_spent)")
    reg.add_argument("--repo", required=True)
    reg.add_argument("--class", dest="capability_class", required=True)
    reg.add_argument("--size", required=True)
    reg.add_argument("--language", required=True)
    reg.add_argument("--builder", required=True)
    reg.add_argument("--model", required=True)
    reg.add_argument("--provider", required=True)
    reg.add_argument("--step", default="replay", help="process step (default replay)")
    reg.add_argument(
        "--hierarchy", required=True, help="arms richest first, comma-separated: S3,S1@<author>"
    )
    reg.add_argument(
        "--since",
        default="",
        help="freeze the pool from this ISO time (default: every qualified commit of the cell)",
    )
    reg.add_argument("--rule", default=RULE_LOOK_V1, choices=sorted(RULES))
    reg.add_argument("--posture-class", required=True, help="the sealed class the reading counts")
    reg.add_argument("--author-model", default="")
    reg.add_argument("--checks", default="off")
    reg.add_argument("--path", default="", help="ledger path (default <workdir>/ledger.jsonl)")
    reg.add_argument("--readings", default="", help=f"default <workdir>/{READINGS_FILE}")
    reg.add_argument("--actor", default="", help="who registers (default cli:<os user>)")
    add_common(reg)
    reg.set_defaults(func=cmd_register)
    ls = rs.add_parser("list", help="the registered readings and their spend")
    ls.add_argument("--readings", default="")
    add_common(ls)
    ls.set_defaults(func=cmd_list)
    p.set_defaults(func=lambda args: _usage(p))


def _usage(p: argparse.ArgumentParser) -> int:
    p.print_help()
    return 2


def readings_path(args: argparse.Namespace) -> Path:
    return (
        Path(args.readings).expanduser()
        if getattr(args, "readings", "")
        else workdir_of(args).root / READINGS_FILE
    )


def load_readings(path: Path) -> list[Reading]:
    """Every reading on file; one that does not re-hash is refused, never skipped quietly."""
    if not path.is_file():
        return []
    out: list[Reading] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        reading = Reading.from_dict(json.loads(line))
        if not reading.verify():
            raise CliError(f"{path}:{n}: reading {reading.reading_id!r} does not re-hash")
        out.append(reading)
    return out


def cmd_register(args: argparse.Namespace) -> int:
    """Register one reading and append it; refusals exit 2 with their code."""
    wd = workdir_of(args)
    cell = {
        "process_step": args.step,
        "capability_class": args.capability_class,
        "size": args.size,
        "language": args.language,
        "builder": args.builder,
        "model": args.model,
        "provider": args.provider,
    }
    assert set(cell) == set(CELL_FIELDS)
    hierarchy = [a.strip() for a in args.hierarchy.split(",") if a.strip()]
    try:
        replayed = [a for a in hierarchy if parse_arm(a).base != BASE_S2]
    except ValueError as exc:
        raise CliError(str(exc)) from exc
    if replayed and not is_sealed_class(args.posture_class):
        raise CliError(
            f"a replayed arm counts only rows graded in the sealed posture; {args.posture_class!r}"
            " is not a docker/<tree>/sealed class (ADR-0026 item 2)"
        )
    tasks = {
        t.task_id: t
        for t in wd.load_tasks(args.repo)
        if t.capability_class == args.capability_class
        and t.size == args.size
        and t.gold_clean is True
        and (not t.language or t.language == args.language)
    }
    try:  # the pool is frozen by rule, never by a list (DL-097, P-320)
        pool, pool_rule = pool_by_rule(
            {c: str(t.authored or "") for c, t in tasks.items()}, since=args.since
        )
    except ReadingRefused as exc:
        raise CliError(f"{exc.code}: {exc}") from exc
    if not pool:
        raise CliError(f"no gold-checked task of this cell on file under {pool_rule}")
    ledger = Path(args.path).expanduser() if args.path else wd.ledger_path
    path = readings_path(args)
    try:
        reading = register_reading(
            repo=args.repo,
            cell=cell,
            hierarchy=hierarchy,
            pool=pool,
            apparatus=APPARATUS_VERSION,
            taxonomy=GLOBAL_CLASS_SET,
            posture_class=args.posture_class,
            checks_arm=args.checks,
            actor=args.actor or f"cli:{os.environ.get('USER', 'unknown')}",
            existing=load_readings(path),
            rows=JsonlLedger(ledger).rows(),
            rule=args.rule,
            author_model=args.author_model,
            changes={c: str(tasks[c].labels.get(LABEL_CHANGE_ID, "")) for c in pool},
            pool_rule=pool_rule,
        )
    except ReadingRefused as exc:
        raise CliError(f"{exc.code}: {exc}") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(reading.to_dict(), sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())
    out: dict[str, Any] = {"readings": str(path), **reading.to_dict()}
    if args.json:
        print_json(out)
    else:
        print_lines(
            [
                f"registered {reading.reading_id} on {args.repo} {'|'.join(cell.values())}",
                f"hierarchy {' > '.join(reading.hierarchy)} · rule {reading.rule} · "
                f"spends {reading.spend:.4f} of {reading.budget:.2f} · pool {len(reading.pool)}",
                f"written to {path}",
            ]
        )
    return EXIT_OK


def cmd_list(args: argparse.Namespace) -> int:
    """Print every registered reading."""
    readings = load_readings(readings_path(args))
    if args.json:
        print_json({"readings": [r.to_dict() for r in readings]})
        return EXIT_OK
    rows = [
        (r.reading_id, r.repo, r.cell_key, " > ".join(r.hierarchy), r.rule, f"{r.spend:.4f}")
        for r in readings
    ]
    print_lines(list(table(("reading", "repo", "cell", "hierarchy", "rule", "spend"), rows)))
    return EXIT_OK
