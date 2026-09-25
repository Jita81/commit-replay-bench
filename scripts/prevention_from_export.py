#!/usr/bin/env python3
"""The prevention register over an exported ledger — what the loop would see, from a file.

    python scripts/prevention_from_export.py LEDGER.psv [--reviews REVIEWS.psv]
        [--repos cobra,click,koa] [--assume-shipped finish_gate,format_step,budget_calibrated]
        [--json]

The operator's stack exports its ledger (``GET /ledger/export``) as one row per graded attempt;
this script rebuilds each row as a ``GradeRow`` the product's own rules can read and prints the
register ``crb.core.prevention.build_register`` computes for each repository: every class, its
occurrences on first attempts, whether it is actionable, the lever the loop would choose and at
what level, the items it would file, and the repository's largest blind class. It is the
offline twin of ``GET /learn/register`` for a file someone was handed; it writes nothing and
the export itself is never committed (it is the operator's ledger).

**What the export cannot carry, said rather than guessed.** The PSV has no error text, no stop
reason, no lint pack, no builder, no model and no row hash. So:

* the error class (``errclass``) is mapped by the product's own rule — ``U`` provider refusal
  (outage, never a class), ``K``/``EJ``/``EP``/``LT``/``H`` harness, ``PN``/``PA``/``PO``
  protocol (network / archaeology / other) — and each row is given a *placeholder* error text
  that carries only that class (``EXPORT_ERRORS``), so the signature resolves to family level:
  ``protocol:network:-``, ``budget:unrecorded``, ``lint:*``;
* every row gets the builder and model ``export`` (one comparability key for the whole file);
* a clean row gets a placeholder pack hash (the invariant "no pack, no clean" is the product's,
  and the export does not name the pack);
* the review export has no row hash, so review findings are counted per repository, unanchored.

Navigation
----------
What it is:   The offline register builder over an exported ledger (PSV), for the value
              wave's baseline numbers (ADR-0020's "What the register would do today").
What it does: Reads the export, rebuilds invariant-valid rows by the product's failure rule,
              builds each repository's prevention register with the shipped mechanisms given,
              and prints (or emits as JSON) every class with its occurrences, stratum, lever,
              level and proposals, plus each repository's largest blind class. Writes nothing.
How:          ``read_export`` (csv, ``|``) → ``row_from_export`` (errclass → placeholder error +
              pinned failure kind) → ``crb.core.prevention.build_register`` per repository →
              ``summarise`` → text or JSON.
Layer:        deploy — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         docs/adr/0020-a-bug-is-closed-by-prevention.md
Works with:   src/crb/core/prevention.py (the register it builds), src/crb/core/ledger.py (the
              failure rule the rows are read by), docs/LEARNING-LOOP.md (§7, what the numbers
              mean), scripts/claims_check.py (the same stdlib-script idiom)
Tested by:    tests/test_prevention_from_export.py
Touch when:   the export's columns change (``COLUMNS``), or the product's error classes do
              (``EXPORT_ERRORS`` must map each to the kind the product's rule gives it).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from crb.core.ledger import GradeRow, parse_apparatus_version
from crb.core.prevention import Mechanisms, Register, build_register, is_first_attempt

#: The export's columns (``GET /ledger/export`` as the operator pulled it on 2026-09-25).
COLUMNS = [
    "seq",
    "created",
    "repo",
    "class",
    "size",
    "mode",
    "step",
    "clean",
    "dq",
    "failure_kind",
    "trial",
    "run",
    "task",
    "cost",
    "latency",
    "apparatus",
    "gold_clean",
    "oracle",
    "rung",
    "tests_unmod",
    "target_green",
    "no_new",
    "lint",
    "errclass",
]

#: errclass → (failure kind, a placeholder error text that carries only that class). The text
#: is what the product's rule and the harness table read; it is labelled as a placeholder.
EXPORT_ERRORS: dict[str, tuple[str, str]] = {
    "U": ("outage", "model_error: usage limit (export placeholder)"),
    "K": ("harness", "model_error: API key not set (export placeholder)"),
    "EJ": ("harness", "sh: jest: not found (export placeholder)"),
    "EP": ("harness", "pip install: network is unreachable (export placeholder)"),
    "LT": ("harness", "lint: linter could not run (export placeholder)"),
    "H": ("harness", "harness error (export placeholder: detail not exported)"),
    "PN": ("protocol", "protocol violation: network: refused (export placeholder)"),
    "PA": ("protocol", "protocol violation: archaeology: refused (export placeholder)"),
    "PO": ("protocol", "protocol violation: refused (export placeholder)"),
}
#: A clean row's pack hash — the export does not name it; the product refuses a clean row
#: without one, so the rebuilt row carries this placeholder.
PLACEHOLDER_PACK = "e" * 64
BUILDER = MODEL = "export"


def _bool(v: str) -> bool | None:
    return {"1": True, "0": False, "true": True, "false": False}.get(v.strip().lower())


def read_export(path: Path) -> list[dict[str, str]]:
    """The export's rows as dicts (a header line is expected and checked)."""
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="|"))
    if rows and set(COLUMNS) - set(rows[0]):
        missing = sorted(set(COLUMNS) - set(rows[0]))
        raise SystemExit(f"{path}: not the ledger export shape (missing columns {missing})")
    return rows


def row_from_export(d: Mapping[str, str], index: int) -> GradeRow:
    """One export row as an invariant-valid ``GradeRow`` read by the product's rule."""
    clean = d["clean"] == "1"
    dq = d["dq"] == "1"
    apparatus = d["apparatus"] or "2.2"
    parsed = parse_apparatus_version(apparatus)
    v5 = parsed is not None and parsed >= (2, 2)
    labels: dict[str, str] = {}
    error = ""
    code = d.get("errclass", "")
    if not clean and not dq and code in EXPORT_ERRORS:
        kind, error = EXPORT_ERRORS[code]
        labels["failure_kind"] = kind
    elif not clean and d["failure_kind"] in ("budget", "builder_red", "lint", "disqualified"):
        labels["failure_kind"] = d["failure_kind"]
    if dq:
        labels["failure_kind"] = "disqualified"
    lint = _bool(d["lint"]) if v5 else None
    tests_unmod = _bool(d["tests_unmod"])
    target = _bool(d["target_green"])
    no_new = _bool(d["no_new"])
    if clean:
        tests_unmod = target = no_new = True
        lint = lint if lint is not False else None
    return GradeRow(
        repo=d["repo"],
        task_id=d["task"] or f"row{index}",
        clean=clean,
        tests_unmodified=tests_unmod,
        target_green=target,
        no_new_failures=no_new,
        source_changed=True if clean else None,
        repo_lint_clean=lint,
        capability_class=d["class"],
        size=d["size"],
        mode=d["mode"] or "sighted",
        process_step=d["step"] or "replay",
        builder=BUILDER,
        model=MODEL,
        run_id=d["run"],
        trial=d["rung"] or d["trial"] or "r1",
        created=d["created"],
        disqualified=dq,
        dq_reason="export placeholder" if dq else "",
        error=error,
        cost_usd=float(d["cost"] or 0.0),
        latency_s=float(d["latency"] or 0.0),
        gold_clean=_bool(d["gold_clean"]),
        evidence_pack_hash=PLACEHOLDER_PACK if clean else "",
        apparatus_version=apparatus,
        belt_set="v5" if v5 else "v4",
        labels=labels,
    )


def registers(
    rows: Iterable[GradeRow], *, repos: Iterable[str] = (), shipped: Iterable[str] = ()
) -> dict[str, Register]:
    """One register per repository (all of them, or the ones named)."""
    rs = list(rows)
    names = sorted({r.repo for r in rs}) if not repos else list(repos)
    mech = Mechanisms(shipped=frozenset(shipped))
    return {name: build_register(rs, repo=name, mechanisms=mech) for name in names}


def largest_blind_class(reg: Register, *, first_only: bool = True) -> tuple[str, int]:
    """The class with the most blind occurrences — on first attempts (the loop's unit) by
    default, or on every row (every rung) with ``first_only=False``; ties by name."""
    counts: Counter[str] = Counter()
    for r in reg.index.rows:
        if r.mode == "blind" and (is_first_attempt(r.trial) or not first_only):
            for sig in reg.index.of(r):
                counts[sig] += 1
    if not counts:
        return "", 0
    sig, n = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    return sig, n


def summarise(reg: Register) -> dict[str, Any]:
    """The numbers the brief asks for, per repository: every class with its occurrences on
    first attempts by mode, its stratum, actionability, lever, level and what the loop would
    file."""
    first = [r for r in reg.index.rows if is_first_attempt(r.trial) and r.failure_kind != "outage"]
    blind = sum(1 for r in first if r.mode == "blind")
    first_by: dict[str, Counter[str]] = {}
    for r in first:
        for s in reg.index.of(r):
            first_by.setdefault(s, Counter())[r.mode] += 1
    sig, n = largest_blind_class(reg)
    sig_rows, n_rows = largest_blind_class(reg, first_only=False)
    return {
        "repo": reg.repo,
        "first_attempts": len(first),
        "blind_first_attempts": blind,
        "sighted_first_attempts": len(first) - blind,
        "largest_blind_class": {"signature": sig, "first_attempts": n},
        "largest_blind_class_all_rungs": {"signature": sig_rows, "rows": n_rows},
        "classes": [
            {
                "signature": e.signature,
                "occurrences": e.occurrences,
                "first_attempts": e.first_attempts,
                "first_attempts_by_mode": dict(
                    sorted(first_by.get(e.signature, Counter()).items())
                ),
                "stratum": f"{e.stratum_k} of {e.stratum_n} {e.stratum_mode} (apparatus "
                f"{e.key.split('|')[0] if e.key else '-'})",
                "tasks": e.tasks,
                "cost_usd": round(e.cost_usd, 2),
                "actionable": e.actionable,
                "lever": e.recommendation.lever_id,
                "level": e.recommendation.level,
                "would_file": list(e.recommendation.propose),
                "status": e.status,
                "qualifiers": list(e.qualifiers),
            }
            for e in reg.entries
        ],
    }


def review_counts(path: Path) -> dict[str, dict[str, int]]:
    """Review findings per repository, unanchored (the review export names no row hash)."""
    out: dict[str, Counter[str]] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for d in csv.DictReader(f, delimiter="|"):
            c = out.setdefault(d["repo"], Counter())
            kinds = [k for k in (d.get("finding_kinds") or "").split(",") if k]
            for k in kinds:
                c[f"review:{k}"] += 1
            if not kinds and (d.get("mergeable_flag") or "").lower() == "false":
                c["review:not_mergeable"] += 1
    return {k: dict(sorted(v.items())) for k, v in sorted(out.items())}


def render(summaries: list[dict[str, Any]], shipped: list[str]) -> list[str]:
    lines = [
        "The prevention register over the export (family level: the export carries no error "
        "text, stop reason or lint pack).",
        f"Mechanisms assumed shipped: {', '.join(shipped) if shipped else 'none (this branch)'}.",
    ]
    for s in summaries:
        lines.append("")
        lines.append(
            f"{s['repo']}: {s['first_attempts']} first attempts ({s['blind_first_attempts']} blind, "
            f"{s['sighted_first_attempts']} sighted); largest blind class "
            f"{s['largest_blind_class']['signature'] or '-'} "
            f"({s['largest_blind_class']['first_attempts']} first attempts; on every rung "
            f"{s['largest_blind_class_all_rungs']['signature'] or '-'}, "
            f"{s['largest_blind_class_all_rungs']['rows']} rows)"
        )
        for c in s["classes"]:
            lever = f"{c['lever']} ({c['level']})" if c["lever"] else "-"
            filed = f"; would file {', '.join(c['would_file'])}" if c["would_file"] else ""
            quals = f" [{', '.join(c['qualifiers'])}]" if c["qualifiers"] else ""
            lines.append(
                f"  {c['signature']}: {c['first_attempts']} first attempts "
                f"{c['first_attempts_by_mode']}, stratum {c['stratum']}, {c['tasks']} tasks, "
                f"${c['cost_usd']:.2f}; actionable {c['actionable']}; lever {lever}{filed}; "
                f"{c['status']}{quals}"
            )
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("ledger", type=Path)
    ap.add_argument("--reviews", type=Path, default=None)
    ap.add_argument("--repos", default="", help="comma-separated (default: every repository)")
    ap.add_argument(
        "--assume-shipped",
        default="",
        help="mechanisms to treat as shipped (finish_gate, format_step, budget_calibrated)",
    )
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    raw = read_export(args.ledger)
    rows = [row_from_export(d, i) for i, d in enumerate(raw)]
    repos = [r for r in args.repos.split(",") if r]
    shipped = [s for s in args.assume_shipped.split(",") if s]
    regs = registers(rows, repos=repos, shipped=shipped)
    summaries = [summarise(regs[name]) for name in regs]
    reviews = review_counts(args.reviews) if args.reviews else {}
    if args.json:
        json.dump(
            {"shipped": shipped, "repositories": summaries, "reviews_unanchored": reviews},
            sys.stdout,
            indent=1,
            sort_keys=True,
        )
        sys.stdout.write("\n")
        return 0
    for line in render(summaries, shipped):
        print(line)
    if reviews:
        print("")
        print("Review findings (unanchored: the review export names no row hash):")
        for repo, counts in reviews.items():
            print(f"  {repo}: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
