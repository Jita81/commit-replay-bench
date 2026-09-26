#!/usr/bin/env python3
"""The spend numbers from a ledger export — budget stops, escalation yield, and what the
spend rules would decide — computed by the product's own rules, not a re-implementation.

    python scripts/spend_from_export.py ledger.psv            # JSON on stdout
    python scripts/spend_from_export.py ledger.psv --markdown # the same, as tables

The input is the pipe-separated export the value programme measured from (columns
``seq|created|repo|class|size|mode|step|clean|dq|failure_kind|trial|run|task|cost|latency|
apparatus|gold_clean|oracle|rung|tests_unmod|target_green|no_new|lint|errclass``). The data
file is the operator's ledger and is never committed; this script is.

The export's ``failure_kind`` column is a crude projection, so each row is re-classified
by :func:`crb.core.ledger.derive_failure_kind` — THE rule — from ``errclass`` (``U``
provider usage limit → an ``model_error: usage limit`` error, an outage; ``K`` / ``EJ`` /
``EP`` / ``LT`` / ``H`` → an instrument error, harness; ``PN`` / ``PA`` / ``PO`` → a
``protocol violation:``), the export's ``budget`` flag (→ a budget stop reason) and its
``lint`` flag (→ lint-only). Valid = not outage, not harness (the rows that observed the
builder), as :func:`crb.core.spend.observation_from_row` counts them.

It reports, all over valid rows:

* per ``mode × size``: clean completions (n; latency p50 / p90 / max; cost p50 / p90) and
  budget stops (n; latency p50; how many hit the 900 s wall clock; their cost);
* the escalation rungs (trial ``r2`` / ``r3``): n, clean, cost, cost per clean patch, next to
  ``r1`` in the same mode;
* what :func:`crb.core.spend.calibrate` would set per ``mode × size`` at the default floor
  (the export carries no turns, so only the wall clock can move — said in the output);
* what :func:`crb.core.spend.escalation_decision` would decide per ``mode × size`` for the
  export's builder and model.

Navigation
----------
What it is:   The spend analysis over a ledger export — the numbers stream K's rules were set
              from, recomputed by those rules.
What it does: Parses the export, re-derives each row's failure kind with the product's rule,
              and reports budget-stop and escalation economics per mode × size plus the
              calibrated caps and escalation decisions the rules would make.
How:          ``read_export`` → ``ExportRow`` → ``derive_failure_kind`` →
              ``SpendObservation`` → ``summarise`` (nearest-rank quantiles, sums) →
              ``calibrate`` / ``escalation_decision`` per cell → JSON or Markdown.
Layer:        scripts — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/core/spend.py (the rules), src/crb/core/ledger.py (the failure rule),
              tests/test_spend_from_export.py (pins what this prints)
Tested by:    tests/test_spend_from_export.py
Touch when:   the export's columns change; a spend rule gains an input the export carries.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crb.core.ledger import (
    FAILURE_BUDGET,
    FAILURE_CLEAN,
    FAILURE_HARNESS,
    FAILURE_OUTAGE,
    derive_failure_kind,
)
from crb.core.spend import (
    ESCALATION_MEASURED,
    SpendObservation,
    calibrate,
    escalation_decision,
    quantile,
)

#: ``errclass`` → the error text the product would have recorded (only its PREFIX and
#: markers matter to the rule).
ERRCLASS_ERROR: Mapping[str, str] = {
    "U": "model_error: usage limit reached",
    "K": "harness: API key not set",
    "EJ": "harness: jest missing",
    "EP": "harness: pip/venv network",
    "LT": "lint: linter could not run",
    "H": "harness: other",
    "PN": "protocol violation: network",
    "PA": "protocol violation: archaeology",
    "PO": "protocol violation: other",
}
#: The default floor the export's rows ran under (``Budget()``: 25 / 25 / 900).
DEFAULT_FLOOR: Mapping[str, int] = {"wall_clock_s": 900, "max_turns": 25, "max_tool_calls": 25}
MODES: tuple[str, ...] = ("sighted", "blind")
SIZES: tuple[str, ...] = ("XS", "S", "M", "L")


@dataclass(frozen=True)
class ExportRow:
    """One export line, re-classified by the product's rule."""

    repo: str
    mode: str
    size: str
    trial: str
    cost: float
    latency: float
    kind: str

    @property
    def valid(self) -> bool:
        return self.kind not in (FAILURE_OUTAGE, FAILURE_HARNESS)

    @property
    def clean(self) -> bool:
        return self.kind == FAILURE_CLEAN


def classify(line: Mapping[str, str]) -> str:
    """The product's failure kind for one export line (module docstring)."""
    err = line.get("errclass", "") or ""
    return derive_failure_kind(
        clean=line.get("clean") == "1",
        disqualified=line.get("dq") == "1",
        error=ERRCLASS_ERROR.get(err, "harness: unknown" if err else ""),
        stop_reason="max_turns" if line.get("failure_kind") == FAILURE_BUDGET else "",
        lint_only=line.get("failure_kind") == "lint",
    )


def read_export(path: Path) -> list[ExportRow]:
    with path.open(encoding="utf-8", newline="") as fh:
        return [
            ExportRow(
                repo=line["repo"],
                mode=line["mode"],
                size=line["size"],
                trial=line["trial"],
                cost=float(line["cost"] or 0.0),
                latency=float(line["latency"] or 0.0),
                kind=classify(line),
            )
            for line in csv.DictReader(fh, delimiter="|")
        ]


def observations(rows: Iterable[ExportRow], *, builder: str, model: str) -> list[SpendObservation]:
    """The export as the spend rules read it (one builder and model — the export's)."""
    return [
        SpendObservation(
            repo=r.repo,
            mode=r.mode,
            size=r.size,
            builder=builder,
            model=model,
            trial=r.trial,
            clean=r.clean,
            valid=r.valid,
            latency_s=r.latency,
            cost_usd=r.cost,
        )
        for r in rows
    ]


def _q(values: Sequence[float], q: float) -> float | None:
    return round(quantile(values, q), 4) if values else None


def summarise(rows: Sequence[ExportRow], *, builder: str = "b", model: str = "m") -> dict[str, Any]:
    valid = [r for r in rows if r.valid]
    kinds: dict[str, int] = {}
    for r in valid:
        if not r.clean:
            kinds[r.kind] = kinds.get(r.kind, 0) + 1
    cells: list[dict[str, Any]] = []
    obs = observations(rows, builder=builder, model=model)
    for mode in MODES:
        for size in SIZES:
            cell = [r for r in valid if r.mode == mode and r.size == size]
            clean = [r for r in cell if r.clean]
            budget = [r for r in cell if r.kind == FAILURE_BUDGET]
            lat = [r.latency for r in clean]
            cost = [r.cost for r in clean]
            cal = calibrate(
                obs,
                repo="*",
                mode=mode,
                size=size,
                builder=builder,
                model=model,
                floor=DEFAULT_FLOOR,
            )
            esc = escalation_decision(
                obs,
                policy=ESCALATION_MEASURED,
                repo="*",
                mode=mode,
                size=size,
                builder=builder,
                model=model,
            )
            cells.append(
                {
                    "mode": mode,
                    "size": size,
                    "valid": len(cell),
                    "clean": {
                        "n": len(clean),
                        "latency_s": {
                            "p50": _q(lat, 0.5),
                            "p90": _q(lat, 0.9),
                            "max": max(lat) if lat else None,
                        },
                        "cost_usd": {"p50": _q(cost, 0.5), "p90": _q(cost, 0.9)},
                        "at_wall_clock": sum(1 for x in lat if x >= DEFAULT_FLOOR["wall_clock_s"]),
                    },
                    "budget_stops": {
                        "n": len(budget),
                        "latency_s_p50": _q([r.latency for r in budget], 0.5),
                        "at_wall_clock": sum(
                            1 for r in budget if r.latency >= DEFAULT_FLOOR["wall_clock_s"]
                        ),
                        "cost_usd": round(sum(r.cost for r in budget), 2),
                    },
                    "calibrated": {
                        "applied": cal.applied,
                        "caps": dict(cal.caps),
                        "label": cal.labels()["budget_calibration"],
                    },
                    "escalation": dict(esc.labels),
                }
            )
    rungs: dict[str, dict[str, Any]] = {}
    for mode in MODES:
        for trial in ("r1", "r2", "r3"):
            rr = [r for r in valid if r.mode == mode and r.trial == trial]
            if not rr:
                continue
            n_clean = sum(1 for r in rr if r.clean)
            spend = sum(r.cost for r in rr)
            rungs[f"{mode}:{trial}"] = {
                "n": len(rr),
                "clean": n_clean,
                "yield": round(n_clean / len(rr), 4),
                "cost_usd": round(spend, 2),
                "cost_per_clean_usd": round(spend / n_clean, 2) if n_clean else None,
            }
    stopped = {
        (c["mode"], c["size"]) for c in cells if c["escalation"].get("escalation") == "stopped"
    }
    withheld = [r for r in valid if r.trial in ("r2", "r3") and (r.mode, r.size) in stopped]
    escalated = [r for r in valid if r.trial in ("r2", "r3")]
    esc_clean = sum(1 for r in escalated if r.clean)
    esc_cost = sum(r.cost for r in escalated)
    return {
        "rows": len(rows),
        "valid": len(valid),
        "clean": sum(1 for r in valid if r.clean),
        "non_clean_by_kind": dict(sorted(kinds.items())),
        "cost_usd_all_rows": round(sum(r.cost for r in rows), 2),
        "cost_usd_budget_stops": round(sum(r.cost for r in valid if r.kind == FAILURE_BUDGET), 2),
        "escalation": {
            "n": len(escalated),
            "clean": esc_clean,
            "cost_usd": round(esc_cost, 2),
            "cost_per_clean_usd": round(esc_cost / esc_clean, 2) if esc_clean else None,
        },
        # IN-SAMPLE: the rule decided from the same rows it is scored on — a ceiling on
        # what it would have saved, not a prospective measurement
        "escalation_withheld_in_sample": {
            "cells": sorted(f"{m}|{z}" for m, z in stopped),
            "n": len(withheld),
            "clean_forgone": sum(1 for r in withheld if r.clean),
            "cost_usd_saved": round(sum(r.cost for r in withheld), 2),
        },
        "rungs": rungs,
        "cells": cells,
        "note": "the export carries no turns: a calibrated turn cap stays at the floor here",
    }


def to_markdown(s: Mapping[str, Any]) -> str:
    out = [
        f"rows {s['rows']}, valid {s['valid']}, clean {s['clean']}; "
        f"non-clean by kind {s['non_clean_by_kind']}; cost ${s['cost_usd_all_rows']} "
        f"(budget stops ${s['cost_usd_budget_stops']})",
        "",
        "| mode | size | valid | clean n | clean s p50/p90/max | clean $ p50/p90 | budget n | budget s p50 | at 900 s | budget $ | calibrated caps | escalation |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in s["cells"]:
        cl, b = c["clean"], c["budget_stops"]
        caps = c["calibrated"]["caps"]
        out.append(
            f"| {c['mode']} | {c['size']} | {c['valid']} | {cl['n']} | "
            f"{cl['latency_s']['p50']}/{cl['latency_s']['p90']}/{cl['latency_s']['max']} | "
            f"{cl['cost_usd']['p50']}/{cl['cost_usd']['p90']} | {b['n']} | {b['latency_s_p50']} | "
            f"{b['at_wall_clock']} | {b['cost_usd']} | "
            f"{caps['max_tool_calls']}/{caps['max_turns']}/{caps['wall_clock_s']} "
            f"({c['calibrated']['label']}) | {c['escalation'].get('escalation_rule', '')} |"
        )
    out += ["", "| rung | n | clean | yield | $ | $ per clean |", "|---|---|---|---|---|---|"]
    for key, r in s["rungs"].items():
        out.append(
            f"| {key} | {r['n']} | {r['clean']} | {r['yield']} | {r['cost_usd']} | {r['cost_per_clean_usd']} |"
        )
    e = s["escalation"]
    w = s["escalation_withheld_in_sample"]
    out += [
        "",
        f"escalation r2+r3: {e['clean']}/{e['n']} clean, ${e['cost_usd']}, "
        f"${e['cost_per_clean_usd']} per clean",
        f"measured rule, in sample: withholds {w['n']} attempts in {w['cells']}, "
        f"saving ${w['cost_usd_saved']} and forgoing {w['clean_forgone']} clean",
        "",
    ]
    return "\n".join(out)


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("export", type=Path, help="the pipe-separated ledger export")
    p.add_argument("--markdown", action="store_true", help="print tables instead of JSON")
    args = p.parse_args(argv)
    summary = summarise(read_export(args.export))
    sys.stdout.write(
        to_markdown(summary) if args.markdown else json.dumps(summary, indent=2) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
