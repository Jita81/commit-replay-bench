#!/usr/bin/env python3
"""Recompute the value scorecard from an exported ledger — the baseline without the stack.

The operator exports the ledger (``GET /ledger/export``) and the review store; this script
reads the files and runs ``crb.core.value.value_report`` over them, so the baseline page is
recomputed by the product's own code rather than by hand. The data files are the operator's
and are never committed; the page this prints is.

    PYTHONPATH=src python scripts/value_baseline.py --ledger ledger.psv --reviews reviews.psv
    PYTHONPATH=src python scripts/value_baseline.py --ledger ledger.jsonl --format json

Two ledger shapes are read:

* **JSONL** (``GET /ledger/export?format=jsonl``) — each line through ``GradeRow.from_dict``,
  so an untrusted row refuses to load exactly as it would in the store;
* **pipe-separated** (the hand projection the 2026-09-25 baseline was exported as) — one row
  per graded attempt with an ``errclass`` code. Its ``failure_kind`` column is a crude
  projection and is NEVER read as the answer: each row's kind is recomputed with the
  product's rule (``crb.core.ledger.derive_failure_kind``) from the error class (``ERRCLASS``),
  the budget stop, the lint belt and the disqualification flag. The projection carries no
  ``source_changed`` column, so a lint-only failure is read as belts 1–3 held and belt 5
  failed; it carries no stop reason, so a budget stop at or over 900 s is named
  ``wall_clock`` and any other ``other_cap``.

Reviews come from the review store's projection (``repo|task|grade_clean|verdict|
mergeable_flag|finding_kinds|statement_head``). Two records in the 2026-09-25 store say
"Mergeable" in the statement and store ``mergeable=false`` (stream K fixes the source); the
operator's export marks them ``(FLAG DEFECT`` and this reader corrects them and counts the
corrections. The three cobra patches the 2026-09-13 critical-friend review read are added
from ``docs/reviews/2026-09-13-critical-friend.md`` §3 unless ``--no-critical-friend``.

Navigation
----------
What it is:   The export reader for the value scorecard — turns an exported ledger and review
              file into ``ValueRow`` / ``ReviewVerdict`` and prints the scorecard as Markdown or
              JSON.
What it does: Recomputes every row's failure kind with the product's rule (never the export's
              column), refuses an unknown error class, corrects the two flagged review records
              and says how many it corrected, and renders every figure with its n, its method
              and its apparatus.
How:          ``read_ledger`` (JSONL → ``GradeRow`` → ``value_row_from_grade``; PSV →
              ``ERRCLASS`` → ``derive_failure_kind``) + ``read_reviews`` → ``value_report`` →
              ``render_markdown`` / ``json.dumps``.
Layer:        deploy — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   src/crb/core/value.py (the report), src/crb/core/ledger.py (the failure rule),
              docs/reviews/2026-09-25-value-baseline.md (the page it regenerates),
              docs/reviews/2026-09-13-critical-friend.md (the three cobra verdicts)
Tested by:    tests/test_value_baseline_script.py
Touch when:   the export gains a column or an error class (add it to ``ERRCLASS``); the
              baseline page is regenerated after a campaign (run it, paste the output, keep
              the tags).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from crb.core.ledger import BUDGET_STOP_REASONS, GradeRow, derive_failure_kind
from crb.core.value import (
    DEFAULT_USD_PER_GBP,
    DEFAULT_WINDOW,
    ReviewVerdict,
    ValueRow,
    value_report,
    value_row_from_grade,
)

#: errclass → (the error text the product's rule reads, the sub-class the stub register names).
#: The texts are chosen to hit the rule's branch the class belongs to: ``model_error: … usage
#: limit`` is an outage, ``protocol violation: …`` a protocol refusal, anything else harness.
ERRCLASS: dict[str, tuple[str, str]] = {
    "": ("", ""),
    "U": ("model_error: usage limit", "usage-limit"),
    "K": ("harness: builder api key not set", "api-key-missing"),
    "PN": ("protocol violation: network", "network"),
    "PA": ("protocol violation: archaeology", "archaeology"),
    "PO": ("protocol violation: other", "other"),
    "EJ": ("harness: runner tool missing: jest", "runner-tool-missing:jest"),
    "EP": ("harness: pip or venv needed the network", "network:pip"),
    "LT": ("harness: the linter could not run", "linter-could-not-run"),
    "H": ("harness: other", "other"),
}
#: A budget stop at or beyond this many seconds hit the builder's wall clock.
WALL_CLOCK_S = 900.0
#: docs/reviews/2026-09-13-critical-friend.md §3.1–3.3: three clean cobra patches, none mergeable.
CRITICAL_FRIEND: tuple[ReviewVerdict, ...] = (
    ReviewVerdict("", "cobra", "#2241", True, False, "defect", ("defect",)),
    ReviewVerdict("", "cobra", "#1559", True, False, "defect", ("defect", "style")),
    ReviewVerdict("", "cobra", "shellcompdirective", True, False, "api_change", ("api_change",)),
)


def _b(v: str) -> bool | None:
    return {"1": True, "0": False, "true": True, "false": False}.get(v.strip().lower())


def _psv_row(d: dict[str, str]) -> ValueRow:
    err = d.get("errclass", "").strip()
    if err not in ERRCLASS:
        raise ValueError(f"unknown error class {err!r} (known: {sorted(ERRCLASS)})")
    error, detail = ERRCLASS[err]
    protocol = error.startswith("protocol violation:")
    latency = float(d.get("latency") or 0)
    stop = ""
    if d.get("failure_kind") == "budget":
        stop = "wall_clock" if latency >= WALL_CLOCK_S else BUDGET_STOP_REASONS[0]
        detail = detail or ("wall_clock" if stop == "wall_clock" else "other_cap")
    clean = _b(d["clean"]) is True
    lint_only = _b(d.get("lint", "")) is False and all(
        _b(d.get(k, "")) is True for k in ("tests_unmod", "target_green", "no_new")
    )
    kind = derive_failure_kind(
        clean=clean,
        disqualified=_b(d.get("dq", "")) is True,
        error="" if protocol else error,
        builder_error=error if protocol else "",
        stop_reason=stop,
        lint_only=lint_only,
    )
    return ValueRow(
        row_hash="",
        repo=d["repo"],
        task_id=d["task"],
        created=d["created"],
        capability_class=d["class"],
        size=d["size"],
        mode=d["mode"],
        clean=clean,
        failure_kind=kind,
        cost_usd=float(d.get("cost") or 0),
        apparatus_version=d["apparatus"],
        gold_clean=_b(d.get("gold_clean", "")),
        repo_lint_clean=_b(d.get("lint", "")),
        oracle_strength=float(d["oracle"]) if d.get("oracle") else None,
        detail=detail if kind != "" else "",
        process_step=d.get("step") or "replay",
        trial=d.get("rung") or d.get("trial", ""),
    )


def read_ledger(path: Path) -> list[ValueRow]:
    """Rows from a JSONL export (through ``GradeRow``) or the pipe-separated projection."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl" or text.lstrip().startswith("{"):
        return [
            value_row_from_grade(GradeRow.from_dict(json.loads(line)))
            for line in text.splitlines()
            if line.strip()
        ]
    return [_psv_row(d) for d in csv.DictReader(text.splitlines(), delimiter="|")]


def read_reviews(
    path: Path | None, *, critical_friend: bool = True
) -> tuple[list[ReviewVerdict], int]:
    """Verdicts from the review projection (+ the three critical-friend cobra verdicts) and
    how many stored ``mergeable`` flags the reader corrected from a ``(FLAG DEFECT`` mark."""
    out: list[ReviewVerdict] = []
    corrected = 0
    if path is not None:
        for d in csv.DictReader(path.read_text(encoding="utf-8").splitlines(), delimiter="|"):
            flag = _b(d.get("mergeable_flag", ""))
            if flag is False and "(FLAG DEFECT" in d.get("statement_head", ""):
                flag = True
                corrected += 1
            kinds = tuple(k for k in (d.get("finding_kinds") or "").split(",") if k)
            out.append(
                ReviewVerdict(
                    grade_row_hash="",
                    repo=d["repo"],
                    task_id=d["task"],
                    grade_clean=_b(d.get("grade_clean", "")) is True,
                    mergeable=flag,
                    verdict=d.get("verdict", ""),
                    finding_kinds=kinds,
                )
            )
    if critical_friend:
        out.extend(CRITICAL_FRIEND)
    return out, corrected


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.1f}%"


def _rate(d: dict[str, object]) -> str:
    if not d.get("n"):
        return "— (n = 0)"
    return f"{d['k']} / {d['n']} = {_pct(d['point'])} (Wilson 95% {_pct(d['ci_low'])}-{_pct(d['ci_high'])})"  # type: ignore[arg-type]


def render_markdown(
    rows: Sequence[ValueRow],
    verdicts: Sequence[ReviewVerdict],
    *,
    apparatus: str = "all",
    corrected: int = 0,
    window: int = DEFAULT_WINDOW,
    usd_per_gbp: float = DEFAULT_USD_PER_GBP,
) -> str:
    """The scorecard as the Markdown the baseline page carries."""
    rep = value_report(
        rows, verdicts, apparatus=apparatus, window=window, usd_per_gbp=usd_per_gbp
    ).to_dict()
    scoped = [r for r in rows if apparatus == "all" or r.apparatus_version == rep["apparatus"]]
    app = f"apparatus {', '.join(rep['apparatus_versions']) or '—'}" + (
        " (pooled)" if rep["pooled"] else ""
    )
    ns, pr, pl = rep["north_star"], rep["precision"], rep["process_loss"]
    lc, rt, rates = rep["learning_curve"], rep["routing"], rep["rates"]
    valid = [r for r in scoped if r.valid]
    kinds: dict[str, int] = {}
    for r in valid:
        if not r.clean:
            kinds[r.failure_kind] = kinds.get(r.failure_kind, 0) + 1
    budget = [r for r in scoped if r.failure_kind == "budget"]
    rungs = [r for r in valid if r.trial in ("r2", "r3")]
    method = "method: the product's failure rule (`derive_failure_kind`) over the export"
    lines = [
        f"| measure | value | n / method / {app} |",
        "|---|---|---|",
        f"| rows / valid observations | {rep['rows']} / {rates['all']['n']} | n = {rep['rows']} rows; valid = not outage, harness, disqualified or a failed gold; {method} |",
        f"| clean, all valid | {_rate(rates['all'])} | n = {rates['all']['n']}; {method} |",
        f"| clean, sighted | {_rate(rates['sighted'])} | n = {rates['sighted']['n']}; {method} |",
        f"| clean, blind | {_rate(rates['blind'])} | n = {rates['blind']['n']}; {method} |",
    ]
    for size, r in rates["blind_by_size"].items():
        lines.append(f"| clean, blind {size} | {_rate(r)} | n = {r['n']}; {method} |")
    lines += [
        f"| non-clean valid by kind | {', '.join(f'{k} {v}' for k, v in sorted(kinds.items(), key=lambda kv: -kv[1]))} | n = {sum(kinds.values())} non-clean valid rows; {method} |",
        f"| spend on budget-stopped attempts | ${sum(r.cost_usd for r in budget):.2f} of ${pl['all_usd']:.2f}; {sum(1 for r in budget if r.detail == 'wall_clock')} at the {WALL_CLOCK_S:.0f} s wall clock | n = {len(budget)} budget rows; cost as recorded on the row |",
        f"| escalation rungs r2 / r3, clean | {sum(1 for r in rungs if r.clean)} / {len(rungs)} | n = {len(rungs)} valid rows on rungs r2-r3; {method} |",
        f"| process loss (budget + protocol + harness + outage) | {pl['rows']} of {pl['all_rows']} rows ({_pct(pl['rows_share'])}); ${pl['usd']:.2f} of ${pl['all_usd']:.2f} ({_pct(pl['usd_share'])}) = £{pl['gbp']:.2f} | n = {pl['all_rows']} rows; £ at {usd_per_gbp} USD per GBP (fixed) |",
        f"| budget + protocol, share of valid failures | {_pct(pl['budget_protocol_share_of_valid_failures'])} | n = {pl['valid_failures']} non-clean valid rows; {method} |",
        f"| reviewed clean patches judged mergeable | {_rate(pr['review'])} | n = {pr['review']['n']} reviews (by verdict: {', '.join(f'{k} {v}' for k, v in pr['review']['by_verdict'].items())}); {corrected} stored flag(s) corrected from the statement |",
        f"| proxy: clean patches lint-clean with no API break | {_rate(pr['proxy'])}; {pr['proxy']['unknown']} unknown (belt 5 not recorded) | n = {pr['proxy']['n']} clean valid rows; method: the deterministic proxy, unknown counted as not working |",
        f"| **working rate, blind** (clean x precision) | {_pct(ns['working_rate'])} ({_pct(ns['working_rate_low'])}-{_pct(ns['working_rate_high'])}) | n = {ns['n_valid']} blind valid x n = {ns['precision']['n']} {ns['precision_basis']} verdicts; method: product of two rates and of their Wilson bounds — an estimate |",
        f"| **working changes per pound, blind** | {ns['per_pound'] if ns['per_pound'] is not None else '—'} per £ ({ns['per_pound_low']}-{ns['per_pound_high']}); ≈ {ns['working_estimate']} working of {ns['n_valid']} valid for £{ns['spend_gbp']:.2f} | n = {ns['n_attempts']} blind attempts (all spend counted); £ at {usd_per_gbp} USD per GBP (fixed) |",
        f"| deliver decisions made prospectively, clean | {_rate(rt['deliver'])} | n = {rt['rows_scored']} rows routed from prior rows only (`routing.v1`, controls not evaluated) |",
        f"| bug classes closed (register: `{lc['register']['source']}`) | {lc['register']['closed']} of {lc['register']['n_classes']} | n = {lc['register']['n_classes']} classes; the register is a stub until stream L is wired |",
    ]
    lines += [
        "",
        f"Recurrence of previously-seen bug classes per window of {lc['window']} attempts "
        f"(n = {lc['attempts']} attempts, time-ordered, prior data only; {app}):",
        "",
        "| window | attempts | new classes | recurrences | recurrence rate (Wilson 95%) |",
        "|---|---|---|---|---|",
    ]
    for w in lc["windows"]:
        lines.append(
            f"| {w['index'] + 1} | {w['start']}-{w['end']}{' (partial)' if w['partial'] else ''} | {w['new']} | {w['recurrences']} | {_rate(w['rate'])} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--ledger", type=Path, required=True)
    ap.add_argument("--reviews", type=Path, default=None)
    ap.add_argument("--apparatus", default="all", help="current | <version> | all (default all)")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    ap.add_argument("--usd-per-gbp", type=float, default=DEFAULT_USD_PER_GBP)
    ap.add_argument("--no-critical-friend", action="store_true")
    ap.add_argument("--format", choices=("md", "json"), default="md")
    args = ap.parse_args(argv)
    rows = read_ledger(args.ledger)
    verdicts, corrected = read_reviews(args.reviews, critical_friend=not args.no_critical_friend)
    if args.format == "json":
        rep = value_report(
            rows,
            verdicts,
            apparatus=args.apparatus,
            window=args.window,
            usd_per_gbp=args.usd_per_gbp,
        ).to_dict()
        rep["reviews_corrected"] = corrected
        print(json.dumps(rep, indent=2, sort_keys=True))
    else:
        sys.stdout.write(
            render_markdown(
                rows,
                verdicts,
                apparatus=args.apparatus,
                corrected=corrected,
                window=args.window,
                usd_per_gbp=args.usd_per_gbp,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
