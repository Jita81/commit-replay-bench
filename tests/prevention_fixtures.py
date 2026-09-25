"""The prevention loop's fixture ledger — invariant-valid rows, chained in memory.

Every prevention test builds its ledger here, so a row the loop reads is a row the product
could have written: ``GradeRow`` runs its false-Q1 and belt-set invariants on each one, the
rows are chained (``verify_chain``), and the loop's own records are chained through a
``MemoryPreventionStore``. Timestamps are fixed (``at(i)`` = 2026-10-01T00:00:00+00:00 plus
``i`` minutes), so every register is byte-identical from run to run.

THE LADDER is the scenario ADR-0020 is judged by: a recurring class is registered, a
playbook line is applied, measured and retired, the class escalates to the finish gate, the
gate is kept and the class closes — see :func:`ladder_before` and friends.

Navigation
----------
What it is:   Test helpers — the fixture ledger (``attempt``, ``ledger``), the loop's own
              records (``switched``, ``store_of``) and the ladder scenario's rounds.
What it does: Builds invariant-valid ``GradeRow``s of every kind the register classes
              (clean, protocol, budget, lint, format, target red, no source change, a refusal
              before spend, harness, outage, disqualified), chains them, and lays out the
              ladder: 30 before rows (9 network refusals on 6 tasks), 22 rows exposed to the
              line (5 recur), 20 rows exposed to the finish gate (none recur).
How:          ``attempt`` → ``ledger`` (chain) → the scenario functions return rows; the
              tests append records through ``store_of`` and call ``tick``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0020-a-bug-is-closed-by-prevention.md
Works with:   src/crb/core/prevention.py (the loop under test), src/crb/core/ledger.py (the row
              invariants every fixture passes), tests/test_prevention_rule.py (the ladder),
              tests/test_prevention_gaming.py (the attacks built on the same rows)
Tested by:    tests/test_prevention_rule.py, tests/test_prevention_gaming.py,
              tests/test_prevention_store.py, tests/test_prevention_signatures.py
Touch when:   a failure kind or a belt is added (add its kind here so the register sees it);
              never for a new repository.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from crb.core.ledger import GENESIS_HASH, GradeRow, verify_chain
from crb.core.prevention import (
    LABEL_CHANGES,
    LABEL_LEARN,
    LABEL_LINES,
    MemoryPreventionStore,
    PreventionRecord,
)

REPO = "fx"
T0 = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
PACK = "c" * 64
BUILDER = "claude_code"
MODEL = "claude-sonnet-5"

NET_ERR = (
    "protocol violation: network: 'go' is not allowed (no network access) (attempted: go mod tidy)"
)
ARCH_ERR = (
    "protocol violation: archaeology: git history is off limits (attempted: git log --oneline -5)"
)
BLOCKED_ERR = "runner tool missing: jest — the node runner's test command starts with jest"
OUTAGE_ERR = "model_error: You've hit your limit · resets 3am"


def at(i: float) -> str:
    """Fixed ISO timestamps: 2026-10-01T00:00:00+00:00 plus ``i`` minutes."""
    return (T0 + dt.timedelta(minutes=i)).isoformat()


def task(i: int) -> str:
    """A 40-hex task id, distinct per ``i``."""
    return f"{i:04x}" * 10


def lint_pack(steps: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """A pack as ``GradeResult.to_dict`` writes belt 5 (``grade.lint_run.steps``)."""
    return {"grade": {"lint_run": {"detected": "fixture", "ok": False, "steps": list(steps)}}}


def attempt(
    *,
    i: float,
    task_id: str,
    kind: str = "clean",
    mode: str = "blind",
    repo: str = REPO,
    trial: str = "r1",
    run: str = "run-a",
    labels: Mapping[str, str] | None = None,
    apparatus: str = "2.2",
    builder: str = BUILDER,
    model: str = MODEL,
    error: str = "",
    cost: float = 0.1,
    size: str = "S",
) -> GradeRow:
    """One invariant-valid row of ``kind``: clean, protocol (the network refusal of
    ``go mod tidy``), archaeology, budget (``max_turns``), lint, target_red,
    no_source_change, regression, blocked (a refusal before spend, $0), harness (``error``),
    outage, disqualified."""
    lab = dict(labels or {})
    belts = {
        "tests_unmodified": True,
        "target_green": True,
        "no_new_failures": True,
        "source_changed": True,
    }
    extra: dict[str, Any] = {}
    lint_ok: bool | None = True if apparatus >= "2.2" else None
    clean = False
    if kind == "clean":
        clean = True
        extra["evidence_pack_hash"] = PACK
    elif kind in ("protocol", "archaeology"):
        belts.update(target_green=False, source_changed=False)
        extra["error"] = error or (NET_ERR if kind == "protocol" else ARCH_ERR)
        lint_ok = None
    elif kind == "budget":
        belts.update(target_green=False)
        lab.setdefault("stop_reason", "max_turns")
        lab.setdefault("failure_kind", "budget")
        lint_ok = None
    elif kind == "lint":
        lint_ok = False
        extra["evidence_pack_hash"] = PACK
    elif kind == "target_red":
        belts.update(target_green=False)
    elif kind == "no_source_change":
        belts.update(target_green=False, source_changed=False)
    elif kind == "regression":
        belts.update(no_new_failures=False)
    elif kind == "blocked":
        belts.update(target_green=False, source_changed=False)
        extra["error"] = error or BLOCKED_ERR
        cost = 0.0
        lint_ok = None
    elif kind == "harness":
        belts.update(target_green=False)
        extra["error"] = error or "grader exception: something broke"
        lint_ok = None
    elif kind == "outage":
        belts.update(target_green=False, source_changed=False)
        extra["error"] = OUTAGE_ERR
        cost = 0.0
        lint_ok = None
    elif kind == "disqualified":
        extra["disqualified"] = True
        extra["dq_reason"] = "target test file modified — disqualified"
        belts.update(tests_unmodified=False)
        lint_ok = None
    else:  # pragma: no cover - a fixture typo
        raise ValueError(f"unknown fixture kind {kind!r}")
    return GradeRow(
        repo=repo,
        task_id=task_id,
        clean=clean,
        repo_lint_clean=lint_ok,
        mode=mode,
        builder=builder,
        model=model,
        provider="anthropic",
        run_id=run,
        trial=trial,
        created=at(i),
        cost_usd=cost,
        apparatus_version=apparatus,
        belt_set="v5" if apparatus >= "2.2" else "v4",
        size=size,
        capability_class="bug.fix",
        language="go",
        labels=lab,
        **belts,
        **extra,
    )


def ledger(rows: Iterable[GradeRow]) -> list[GradeRow]:
    """Chain the rows in the order given (the ledger's own discipline) and verify."""
    out: list[GradeRow] = []
    prev = GENESIS_HASH
    for r in rows:
        c = r.chained(prev)
        out.append(c)
        prev = c.row_hash
    verify_chain(out)
    return out


def extend(chained: Sequence[GradeRow], rows: Iterable[GradeRow]) -> list[GradeRow]:
    """Append ``rows`` to an already-chained ledger (a row, once written, keeps its hash)."""
    out = list(chained)
    prev = out[-1].row_hash if out else GENESIS_HASH
    for r in rows:
        c = r.chained(prev)
        out.append(c)
        prev = c.row_hash
    verify_chain(out)
    return out


def switched(
    mode: str, *, i: float, actor: str = "op-1", reason: str = "fixture", repo: str = REPO
) -> PreventionRecord:
    """An operator's throw of the switch (``PUT /learn/switch``)."""
    return PreventionRecord(
        "switched",
        repo,
        {"auto_apply": mode},
        actor=actor,
        on_behalf_of=actor,
        reason=reason,
        created=at(i),
    )


def store_of(records: Iterable[PreventionRecord]) -> MemoryPreventionStore:
    """A chained in-memory store holding ``records`` in order."""
    s = MemoryPreventionStore()
    for r in records:
        s.append(r)
    return s


# ---------------------------------------------------------------------------
# THE LADDER — ADR-0020's required scenario
# ---------------------------------------------------------------------------

#: The before window: 30 first attempts on tasks 0–9 in 3 runs; 9 network refusals on 6
#: tasks (p0 = 0.30, decisive n = 11), 4 target-red rows on 2 tasks, 17 clean.
LADDER_PROTOCOL = {0, 1, 2, 3, 4, 5, 10, 11, 12}
LADDER_TARGET_RED = {6, 7, 16, 17}
NET_SIG = "protocol:network:go mod"
RED_SIG = "builder_red:target_red"


def ladder_before() -> list[GradeRow]:
    rows: list[GradeRow] = []
    for i in range(30):
        kind = "clean"
        if i in LADDER_PROTOCOL:
            kind = "protocol"
        elif i in LADDER_TARGET_RED:
            kind = "target_red"
        rows.append(attempt(i=i, task_id=task(i % 10), kind=kind, run=f"run-{i // 10}"))
    return rows


def exposed_to(
    *,
    start: float,
    n: int,
    recur: set[int],
    first_task: int,
    labels: Mapping[str, str],
    run: str,
    kind_else: str = "clean",
    tasks: int = 10,
) -> list[GradeRow]:
    """``n`` first attempts after ``start`` carrying ``labels``; positions in ``recur`` are
    the network refusal again, the rest ``kind_else``."""
    return [
        attempt(
            i=start + j,
            task_id=task(first_task + (j % tasks)),
            kind="protocol" if j in recur else kind_else,
            run=run,
            labels=dict(labels),
        )
        for j in range(n)
    ]


def line_labels(line_id: str, mode: str = "context") -> dict[str, str]:
    return {LABEL_LEARN: mode, LABEL_LINES: line_id}


def change_labels(*change_ids: str, mode: str = "config") -> dict[str, str]:
    return {LABEL_LEARN: mode, LABEL_CHANGES: ",".join(sorted(change_ids))}
