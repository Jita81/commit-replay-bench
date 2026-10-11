"""P-792: an admitted attempt decides its commit, and nothing a run chooses after admission
can steer which commits leave a reading or what a row says.

docs/PREVENTION.md P-792 (and G-982) records the finding: a round-5 enumeration of the Wave 3
reading found nineteen channels (C1 to C19) through which an operator could choose which
commits leave a campaign reading, or what an admitted row says. The round-5 design spec for
closing them names one test per channel, each reproducing the enumeration's probe and failing
before its fix; this file holds them as the fixes land, one step at a time.

C3 (``builder_config``): a run's ``builder_config`` can carry ``extra_args``, which the Claude
Code builder appends to its argv after the rung's own ``--model`` and ``--max-turns``, and a
``claude_binary``, which replaces the CLI it runs. Part (c) is that the apparatus stamp names
both when they are set, so a row cannot describe the rung's model while the argv ran another.
Parts (a) and (b), the refusals at submit and at claim, are added to the same test later.

The reserved.v1 attempt rule (core, no callers yet): a reading registered under it reads each
enrolled commit by the one row its reservation wrote. C4 (a lint-off row is a miss, never a
hit or a leave), C6 (whatever the reserved attempt's exit — a cancel or kill included — later
rows never change its verdict), C15 (a settled reservation without a row is a miss), C19 (an
arm counts only its own reservation's row) and C7 (a non-loop run spends on the reading's
budget profile, refused otherwise) each have a test here, beside the goldens that pin every
legacy (``first_observed.v0``) reading as it read before and the property that the reserved
rule's hits are a subset of the legacy rule's.

Navigation
----------
What it is:   The P-792 channel tests — one per channel the round-5 enumeration found, each
              failing on the code before its fix.
What it does: C3(c): pins that ``ClaudeCodeBuilder.describe()`` names ``extra_args`` and
              ``claude_binary`` when they are set, that the named ``extra_args`` are exactly
              the argv's tail (the overriding ``--model``), and that a builder with neither
              set describes itself byte for byte as it did before. The legacy goldens: every
              registration variant's id and every scenario's outcome, looks and per-commit
              verdicts, printed from the code before reserved.v1 (the deciding row by its
              index, since a row hash covers its random ``row_id``). reserved.v1: C4, C6
              (every exit, against later rows of other runs, reservations and claims, with
              the legacy control), C15, C19, each check a named miss (replay and forward),
              the registration's ``max_reruns`` 0 and budget profile, the
              ``reading_run_refusal`` whitelist table and the arm each admitted run maps to
              (C3, C5, C7 at the core), and the hypothesis property that a reserved hit is a
              legacy hit and a reserved ``deliver`` a legacy one at the same look or earlier.
How:          Builds the builder directly with the worker's ``CRB_CLAUDE_CODE_*`` defaults
              cleared, and reads its argv for the fixture task from
              ``fixtures.builders_repo``; no model call, no store. The reading tests build
              readings, ``Reservation`` values and chained rows in memory (the reading
              fixture's ``sealed_row`` and the forward suite's ``S2`` row shape) and call the
              pure core; no store, no server.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md,
              docs/adr/0026-the-context-standard.md
Works with:   src/crb/builders/claude_code.py (``describe`` and ``argv``, under test),
              tests/test_builders_claude_code.py (the builder's own suite),
              tests/fixtures/builders_repo.py (the task the argv is built for),
              src/crb/core/reading.py (the reserved.v1 rule, ``reading_run_refusal`` and the
              legacy loop, under test), tests/fixtures/readings.py (the registrations and
              rows the reading tests build on), docs/PREVENTION.md (P-792, the row these
              tests close)
Tested by:    tests/test_p792_reserved.py
Touch when:   never for a new repository; a P-792 channel's fix lands (its test goes here,
              failing first), or a builder gains a constructor option that shapes its argv
              (the stamp names it when set, and ``DEFAULT_STAMP`` stays unchanged); the
              reserved.v1 verdict or the run whitelist changes (its table row here first);
              never to regenerate ``GOLDEN`` — a legacy reading that moves is a regression.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from crb.builders import base
from crb.builders import claude_code as cc
from crb.core.acceptance import (
    RESULT_ERROR,
    RESULT_FAIL,
    RESULT_PASS,
    HeldOutTests,
    held_out_labels,
)
from crb.core.ledger import (
    FAILURE_OUTAGE,
    GENESIS_HASH,
    LABEL_FAILURE_KIND,
    GradeRow,
    lint_could_change,
)
from crb.core.lint import LINT_DISABLED_BY_CONFIG
from crb.core.reading import (
    ATTEMPT_RULE_LEGACY,
    ATTEMPT_RULE_RESERVED,
    LEFT_LINT_DISABLED,
    OUTCOME_CEILING,
    POOL_RULE_ALL,
    REFUSAL_INVALID,
    REFUSAL_RUN_FIELDS,
    RESERVED_RUN_LADDER,
    RESERVED_RUN_PARAMS,
    RULE_LOOK_V1,
    RULE_LOOK_V1_STRICT,
    RULES,
    STATE_DELIVER,
    Reading,
    ReadingRefused,
    Reservation,
    arm_reading,
    enrolled,
    evaluate,
    reading_run_refusal,
    register,
    register_forward,
    with_admissions,
    with_enrolment,
    with_reservations,
)
from crb.core.taxonomy import GLOBAL_CLASS_SET
from fixtures.builders_repo import make_fixture
from fixtures.posture import posture_row
from fixtures.readings import (
    AUTHOR,
    BEFORE,
    CELL,
    HYPOTHESIS,
    REGISTERED_AT,
    REPO,
    S1,
    SEALED,
    SMALLEST_EFFECT,
    commits,
    register_reading,
    rows_for,
    sealed_row,
)

#: What a default Claude Code builder's stamp held before the override keys existed, in its
#: key order: a stamp with neither override set must stay byte-identical to this.
DEFAULT_STAMP = (
    '{"builder": "claude_code", "model": "claude-sonnet-5", "provider": "anthropic", '
    '"process": "claude -p stream-json, tools=Read,Edit,Bash", "effort": "default", '
    '"bare": true, "auth": "api_key"}'
)


@pytest.fixture(autouse=True)
def _worker_defaults_cleared(monkeypatch: pytest.MonkeyPatch) -> None:
    """The builder reads its model and auth defaults from the worker's environment."""
    monkeypatch.delenv(cc.MODEL_ENV, raising=False)
    monkeypatch.delenv(cc.AUTH_ENV, raising=False)


def test_p792_c3_builder_config_refused_and_described(tmp_path: Path) -> None:
    """C3(c): reproduces the describe half of the enumeration's probe
    ``test_builder_config_extra_args_validates_and_overrides_argv``, which found the argv
    carrying a second ``--model`` while ``describe()`` named only the rung's."""
    extra = ["--model", "x"]
    b = cc.ClaudeCodeBuilder(extra_args=extra, claude_binary="/opt/claude")
    d = b.describe()
    assert d["extra_args"] == ["--model", "x"]
    assert d["claude_binary"] == "/opt/claude"
    # the stamp still names the rung's model; the override beside it is what the argv ran
    assert d["model"] == "claude-sonnet-5"
    fx = make_fixture(tmp_path)
    brief = base.BuildBrief.from_task(fx.task, config=fx.config, test_command="pytest")
    argv = b.argv(brief, base.Budget(max_turns=7, max_tool_calls=25), tmp_path / "wt")
    models = [argv[i + 1] for i, a in enumerate(argv) if a == "--model"]
    assert models == ["claude-sonnet-5", "x"]
    assert argv[-len(extra) :] == d["extra_args"]
    # the stamp is JSON: a list, not the tuple the builder keeps
    assert json.loads(json.dumps(d)) == d


def test_p792_describe_unchanged_when_unset() -> None:
    """With neither override set, no existing stamp changes: same keys, same order, same
    values; and an empty ``extra_args`` or ``claude_binary`` is the same as unset."""
    assert json.dumps(cc.ClaudeCodeBuilder().describe()) == DEFAULT_STAMP
    assert json.dumps(cc.ClaudeCodeBuilder(extra_args=[], claude_binary="").describe()) == (
        DEFAULT_STAMP
    )
    sealed = cc.ClaudeCodeBuilder(workdir_alias="/work/").describe()
    assert json.dumps(sealed) == DEFAULT_STAMP[:-1] + ', "container_workdir": "/work"}'


# --- the legacy goldens (first_observed.v0), generated from the code before reserved.v1 ---

_G_HARNESS = "harness: sandbox failed"
_G_OUTAGE = {LABEL_FAILURE_KIND: FAILURE_OUTAGE}


def _g_chain(rows: Sequence[GradeRow]) -> list[GradeRow]:
    """``rows`` chained from genesis, as the ledger writes them, so each has a row hash."""
    out: list[GradeRow] = []
    prev = GENESIS_HASH
    for r in rows:
        c = r.chained(prev)
        out.append(c)
        prev = c.row_hash
    return out


def _g_replay() -> tuple[Reading, list[GradeRow]]:
    """A legacy replay reading (S3 then S1, A0 descriptive of 4) over thirteen commits that
    walk every branch of the first-observed loop."""
    raw = commits(13, prefix="g")
    p = register_reading(raw, budget=0.05).pool  # the seeded order; changes do not move it
    reading = register_reading(
        raw, descriptive=(("A0", 4),), budget=0.05, changes={p[1]: "chg-x", p[10]: "chg-x"}
    )
    assert reading.pool == p
    rows = [
        sealed_row(p[0]),
        sealed_row(p[0], clean=False, arm=S1),
        sealed_row(p[1], clean=False),
        *(sealed_row(p[2], clean=False, error=_G_HARNESS) for _ in range(3)),
        sealed_row(p[3], clean=False, error=_G_HARNESS),
        sealed_row(p[3]),
        sealed_row(p[4], clean=False, labels=dict(_G_OUTAGE)),
        sealed_row(p[4], clean=False),
        sealed_row(p[5], builder_executor="local"),
        sealed_row(p[5], clean=False),
        sealed_row(p[6], change="chg-y", labels={"lint_reason": LINT_DISABLED_BY_CONFIG}),
        sealed_row(p[7], change="chg-y"),
        sealed_row(p[8], clean=False, created=BEFORE),
        sealed_row(p[8]),
        sealed_row(p[9], clean=False, trial="r2"),
        sealed_row(p[10]),
        *(sealed_row(p[11], clean=False, error=_G_HARNESS) for _ in range(2)),
        sealed_row(p[12], clean=False, disqualified=True),
        sealed_row(p[1], arm=S1),
        sealed_row(p[2], arm=S1),
        sealed_row(p[3], clean=False, arm=S1, error=_G_HARNESS),
        sealed_row(p[0], arm="A0"),
        sealed_row(p[1], clean=False, arm="A0"),
        sealed_row(p[2], clean=False, arm="A0", labels=dict(_G_OUTAGE)),
        sealed_row(p[3], arm="A0"),
        sealed_row(p[4], arm="A0"),
        sealed_row(p[5], clean=False, arm="A0"),
    ]
    return reading, _g_chain(rows)


def _g_campaign(*, read: bool) -> tuple[Reading, list[GradeRow]]:
    """A campaign-named reading whose admissions were read (``run-in``) or never read."""
    reading = register_reading(commits(4, prefix="k"), budget=0.05, campaign_id="camp-g")
    p = reading.pool
    rows = [
        sealed_row(p[0], run_id="run-out"),
        sealed_row(p[0], clean=False, run_id="run-in"),
        sealed_row(p[1], clean=False, error=_G_HARNESS, run_id="run-in"),
        sealed_row(p[1], run_id="run-in"),
        sealed_row(p[2], run_id="run-out"),
        sealed_row(p[3], run_id="run-in"),
    ]
    return (with_admissions(reading, ["run-in"]) if read else reading), _g_chain(rows)


def _g_forward() -> tuple[Reading, list[GradeRow]]:
    """A legacy forward reading over nine tickets, one per branch of its loop."""
    pool = commits(20, prefix="f")
    ceiling_reading = register_reading(pool, hierarchy=("S3", S1), budget=0.05)
    ceiling = evaluate(
        ceiling_reading,
        rows_for([True] * 20, pool, arm="S3") + rows_for([True] * 17 + [False] * 3, pool, arm=S1),
    )
    assert ceiling.state == OUTCOME_CEILING
    recs = [_g_record(i) for i in range(9)]
    fwd = register_forward(
        ceiling=ceiling,
        builder="claude_code",
        model="claude-sonnet-5",
        provider="anthropic",
        actor="op-1",
        existing=[ceiling_reading],
        now=_G_FWD_AT,
        budget=0.05,
    )
    reading = with_enrolment(fwd, recs)
    rows = [
        _g_s2(recs[0]),
        _g_s2(recs[0], result=RESULT_FAIL),
        _g_s2(recs[1], result=RESULT_FAIL),
        _g_s2(recs[2], clean=False, error=_G_HARNESS),
        _g_s2(recs[3], clean=False, extra=dict(_G_OUTAGE)),
        _g_s2(recs[4], result=RESULT_ERROR),
        _g_s2(recs[5], model="claude-haiku-5"),
        _g_s2(recs[6], stamp=held_out_labels(recs[7], RESULT_PASS)),
        _g_s2(recs[7], extra={"lint_reason": LINT_DISABLED_BY_CONFIG}),
    ]
    return reading, _g_chain(rows)


_G_FWD_AT = "2026-09-27T12:00:00+00:00"


def _g_record(i: int) -> HeldOutTests:
    return HeldOutTests(
        repo=REPO,
        item_id=f"T-{i}",
        grant=f"grant-{i}",
        files=(("tests/test_held_out.py", f"def test_it():\n    assert {i} == {i}\n"),),
        author="operator:bea",
        written_at="2026-09-27T13:00:00+00:00",
        capability_class="bug.fix",
        size="XS",
        language="go",
    )


def _g_s2(
    rec: HeldOutTests,
    *,
    result: str = RESULT_PASS,
    clean: bool = True,
    stamp: dict[str, str] | None = None,
    extra: dict[str, str] | None = None,
    **kw: Any,
) -> GradeRow:
    """A factory ``S2`` attempt of ``rec``'s ticket (the forward suite's ``_s2_row``)."""
    fields: dict[str, Any] = {
        "repo": REPO,
        "task_id": f"oracle-{rec.item_id}",
        "clean": clean,
        "tests_unmodified": True,
        "target_green": clean,
        "no_new_failures": True,
        "source_changed": True,
        "repo_lint_clean": None,
        "evidence_pack_hash": "h" * 64 if clean else "",
        "apparatus_version": "2.4",
        "created": "2026-09-27T14:00:00+00:00",
        "trial": "r1",
        "mode": "sighted",
        **CELL,
        "process_step": "factory",
        **kw,
    }
    return posture_row(
        **fields,
        labels={
            "posture_class": SEALED,
            "builder_executor": "docker",
            "context_arm": "S2",
            "taxonomy": GLOBAL_CLASS_SET,
            "item_id": rec.item_id,
            "calibration": "true",
            **(held_out_labels(rec, result) if stamp is None else stamp),
            **(extra or {}),
        },
    )


def _g_variant_ids() -> dict[str, str]:
    """The ids of registrations that hash the optional fields a legacy reading may carry."""
    common: dict[str, Any] = {
        "repo": REPO,
        "cell": CELL,
        "apparatus": "2.4",
        "taxonomy": GLOBAL_CLASS_SET,
        "posture_class": SEALED,
        "checks_arm": "off",
        "actor": "op-1",
        "now": REGISTERED_AT,
        "budget": 0.05,
    }
    pool = commits(3, prefix="v")
    return {
        "question": register(
            hierarchy=("S3",),
            pool=pool,
            hypothesis=HYPOTHESIS,
            smallest_effect=SMALLEST_EFFECT,
            **common,
        ).reading_id,
        "strict": register(
            hierarchy=("S3",), pool=pool, rule=RULE_LOOK_V1_STRICT, **common
        ).reading_id,
        "max_reruns_0": register(hierarchy=("S3",), pool=pool, max_reruns=0, **common).reading_id,
        "pool_rule": register(
            hierarchy=("S3",), pool=pool, pool_rule=POOL_RULE_ALL, org_class="acme.fix", **common
        ).reading_id,
    }


def _g_snapshot() -> dict[str, Any]:
    """Every scenario's reading id, outcome, and per arm its look and each commit's
    ``(outcome, left, the index of the row that decided it)`` in the reading's order — the
    row's index in the scenario's rows, since a row's hash covers its random ``row_id``."""
    snap: dict[str, Any] = {"ids": _g_variant_ids()}
    for name, (reading, rows) in {
        "replay": _g_replay(),
        "campaign_read": _g_campaign(read=True),
        "campaign_unread": _g_campaign(read=False),
        "forward": _g_forward(),
    }.items():
        out = evaluate(reading, rows)
        at = {r.row_hash: i for i, r in enumerate(rows)}
        snap[name] = {
            "reading_id": reading.reading_id,
            "state": out.state,
            "arms": {
                arm: (
                    (a.look.state, a.look.counted, a.look.clean, a.look.misses, a.look.needed),
                    [(c.outcome, c.left, at.get(c.row_hash)) for c in a.commits],
                )
                for arm, a in out.arms.items()
            },
        }
    return snap


#: The legacy goldens: ``_g_snapshot()`` printed from the code before reserved.v1 existed.
#: A legacy reading's id, its outcome and every commit's verdict must never move.
GOLDEN: dict[str, Any] = {
    "ids": {
        "question": "rdg_c5396a8975ea3ceca1dea904",
        "strict": "rdg_3e5ce7dcedfc2aa0e8dbb086",
        "max_reruns_0": "rdg_a503889415937047e0eecd8d",
        "pool_rule": "rdg_b9768a34baee70a0b1d8138e",
    },
    "replay": {
        "reading_id": "rdg_bee1449e806a36af95e0cf96",
        "state": "insufficient",
        "arms": {
            "S3": (
                ("insufficient", 5, 2, 3, 0),
                [
                    (True, "", 0),
                    (False, "", 2),
                    (None, "harness", None),
                    (True, "", 7),
                    (False, "", 9),
                    (False, "", 11),
                    (None, "lint_disabled", 12),
                    (None, "same_change", None),
                    (True, "", 15),
                    (None, "", None),
                    (None, "same_change", None),
                    (None, "", None),
                    (False, "", 20),
                ],
            ),
            "S1@claude-opus-5": (
                ("undecided", 3, 2, 1, 18),
                [
                    (False, "", 1),
                    (True, "", 21),
                    (True, "", 22),
                    (None, "", None),
                    (None, "", None),
                    (None, "", None),
                    (None, "", None),
                    (None, "", None),
                    (None, "", None),
                    (None, "", None),
                    (None, "same_change", None),
                    (None, "", None),
                    (None, "", None),
                ],
            ),
            "A0": (
                ("descriptive", 3, 2, 1, 1),
                [
                    (True, "", 24),
                    (False, "", 25),
                    (None, "", None),
                    (True, "", 27),
                    (True, "", 28),
                    (False, "", 29),
                    (None, "", None),
                    (None, "", None),
                    (None, "", None),
                    (None, "", None),
                    (None, "same_change", None),
                    (None, "", None),
                    (None, "", None),
                ],
            ),
        },
    },
    "campaign_read": {
        "reading_id": "rdg_463e1fb905e890ccd177f33c",
        "state": "undecided",
        "arms": {
            "S3": (
                ("undecided", 2, 1, 1, 26),
                [(False, "", 1), (True, "", 3), (None, "", None), (True, "", 5)],
            ),
            "S1@claude-opus-5": (
                ("undecided", 0, 0, 0, 16),
                [(None, "", None), (None, "", None), (None, "", None), (None, "", None)],
            ),
        },
    },
    "campaign_unread": {
        "reading_id": "rdg_463e1fb905e890ccd177f33c",
        "state": "undecided",
        "arms": {
            "S3": (
                ("undecided", 0, 0, 0, 16),
                [(None, "", None), (None, "", None), (None, "", None), (None, "", None)],
            ),
            "S1@claude-opus-5": (
                ("undecided", 0, 0, 0, 16),
                [(None, "", None), (None, "", None), (None, "", None), (None, "", None)],
            ),
        },
    },
    "forward": {
        "reading_id": "rdg_2e4128f424af4fa984e5dee6",
        "state": "look_pending",
        "arms": {
            "S2": (
                ("look_pending", 2, 1, 1, 28),
                [
                    (True, "", 0),
                    (False, "", 2),
                    (None, "harness", 3),
                    (None, "unobserved", 4),
                    (None, "held_out_error", 5),
                    (None, "other_cell", 6),
                    (None, "not_graded", 7),
                    (None, "lint_disabled", 8),
                    (None, "", None),
                ],
            )
        },
    },
}


def test_p792_legacy_reading_ids_and_verdicts_unchanged() -> None:
    """Adding the reserved.v1 fields moved no legacy reading: every registration variant
    hashes to the id it hashed to before, and every scenario of the first-observed loop —
    replay, campaign admissions read and unread, forward — reads the same outcome, the
    same looks and the same per-commit verdicts and rows."""
    assert _g_snapshot() == GOLDEN


# --- reserved.v1: the reserved attempt alone decides its commit (C4, C6, C7, C15, C19) ---

#: The ``Event.id`` of the registration the store loads beside a reserved.v1 reading: a
#: reservation written after it counts; one written before it never does.
REG_EVENT = 10
PROFILE = "default"
T1 = "treat-1"
#: A protocol refusal: the builder was stopped by a guard, and the belts judged an empty
#: patch — the builder's miss (``derive_failure_kind`` rule 3), never the instrument's.
PROTOCOL = "protocol violation: wrote the oracle"


def _reserved_reading(
    pool: Sequence[str],
    *,
    hierarchy: Sequence[str] = ("S3", S1),
    descriptive: Sequence[tuple[str, int]] = (),
    rule: str = RULE_LOOK_V1,
    changes: dict[str, str] | None = None,
    campaign_id: str = "",
    budget_profile: str = PROFILE,
    author_model: str | None = None,
) -> Reading:
    """A reserved.v1 reading of :data:`CELL` on :data:`REPO`, registered at
    :data:`REGISTERED_AT` — the legacy fixture's registration with the attempt rule set. Its
    test author is :data:`AUTHOR` when an ``S1`` arm is in the hierarchy, unless named."""
    if author_model is None:
        author_model = AUTHOR if any(a.startswith("S1@") for a in hierarchy) else ""
    return register(
        repo=REPO,
        cell=CELL,
        hierarchy=hierarchy,
        pool=list(pool),
        apparatus="2.4",
        taxonomy=GLOBAL_CLASS_SET,
        posture_class=SEALED,
        checks_arm="off",
        actor="op-1",
        rule=rule,
        descriptive=descriptive,
        author_model=author_model,
        changes=changes,
        budget=0.05,
        max_reruns=0,
        now=REGISTERED_AT,
        campaign_id=campaign_id,
        attempt_rule=ATTEMPT_RULE_RESERVED,
        budget_profile=budget_profile,
    )


def _res(
    arm: str,
    commit: str,
    *,
    run: str = "run-1",
    event: str = "",
    seq: int = REG_EVENT + 1,
    claim: int = 0,
    treatment: str = T1,
    settled: bool = False,
) -> Reservation:
    """The ``reading.reserved`` event of ``commit`` on ``arm``, as the store loads it."""
    return Reservation(
        arm=arm,
        task_id=commit,
        run_id=run,
        event_id=event or f"ev-{run}-{arm}-{commit[:8]}",
        event_seq_id=seq,
        claim=claim,
        treatment=treatment,
        hold_usd=0.5,
        settled=settled,
    )


def _stamp(res: Reservation, **over: str) -> dict[str, str]:
    """The labels the worker stamps on a reserved ``r1`` row."""
    return {
        "reservation": res.event_id,
        "treatment": res.treatment,
        "claim": str(res.claim),
        **over,
    }


def _reserved_row(res: Reservation, *, labels: dict[str, str] | None = None, **kw: Any) -> GradeRow:
    """The row the reserved attempt wrote: its run, its arm, its stamp."""
    return sealed_row(
        res.task_id, arm=res.arm, run_id=res.run_id, labels={**_stamp(res), **(labels or {})}, **kw
    )


def _read(reading: Reading, reservations: Sequence[Reservation]) -> Reading:
    """``reading`` with its reservations and registration event loaded."""
    return with_reservations(reading, reservations, REG_EVENT)


def _verdicts(
    reading: Reading, arm: str, rows: Sequence[GradeRow]
) -> list[tuple[bool | None, str]]:
    """Each enrolled commit's ``(outcome, reason)`` on ``arm``, in the reading's order."""
    return [(c.outcome, c.reason) for c in arm_reading(reading, arm, rows).commits]


def _reserved_forward(n: int, *, attempt_rule: str = ATTEMPT_RULE_RESERVED) -> Reading:
    """A forward reading of the golden section's ceiling, enrolled with ``n`` tickets."""
    pool = commits(20, prefix="rf")
    ceiling_reading = register_reading(pool, hierarchy=("S3", S1), budget=0.05)
    ceiling = evaluate(
        ceiling_reading,
        rows_for([True] * 20, pool, arm="S3") + rows_for([True] * 17 + [False] * 3, pool, arm=S1),
    )
    assert ceiling.state == OUTCOME_CEILING
    fwd = register_forward(
        ceiling=ceiling,
        builder="claude_code",
        model="claude-sonnet-5",
        provider="anthropic",
        actor="op-1",
        existing=[ceiling_reading],
        now=_G_FWD_AT,
        budget=0.05,
        attempt_rule=attempt_rule,
        budget_profile=PROFILE if attempt_rule == ATTEMPT_RULE_RESERVED else "",
    )
    return with_enrolment(fwd, [_g_record(i) for i in range(n)])


def test_p792_c4_forward_lint_disabled_is_not_a_hit() -> None:
    """C4, the reserved.v1 half (the legacy half, where the ticket leaves
    ``lint_disabled``, is ``test_p792_c4_forward_lint_disabled_is_not_a_hit_legacy`` in
    tests/test_forward_reading.py): a reserved row graded with belt 5 switched off by
    configuration is a MISS on a forward reading and on a replay arm — never a hit, and
    never a leave that hands the commit to a later attempt. Under lint-off a reserved.v1
    reading cannot deliver; that is the conservative direction."""
    lint_off = {"lint_reason": LINT_DISABLED_BY_CONFIG}
    # a replay arm
    reading = _reserved_reading(commits(3, prefix="l"), hierarchy=("S3",))
    c = reading.pool[0]
    res = _res("S3", c, settled=True)
    row = _reserved_row(res, labels=lint_off)
    assert lint_could_change(row)
    got = arm_reading(_read(reading, [res]), "S3", [row]).commits[0]
    assert (got.outcome, got.left, got.reason, got.row_hash) == (
        False,
        "",
        "lint_disabled",
        row.row_hash,
    )
    # a forward reading: the unit is the ticket, the reserved row is its factory S2 attempt
    fwd = _reserved_forward(2)
    assert fwd.attempt_rule == ATTEMPT_RULE_RESERVED and fwd.max_reruns == 0
    r0, r1 = (_res("S2", item, run=f"fac-{i}", settled=True) for i, item in enumerate(fwd.pool))
    rows = [
        _g_s2(_g_record(0), extra={**_stamp(r0), **lint_off}, run_id=r0.run_id),
        _g_s2(_g_record(1), extra=_stamp(r1), run_id=r1.run_id),
    ]
    assert lint_could_change(rows[0])
    assert _verdicts(_read(fwd, [r0, r1]), "S2", rows) == [(False, "lint_disabled"), (True, "")]
    # the same rows on the legacy forward reading: the ticket leaves, as the legacy test pins
    legacy = _reserved_forward(2, attempt_rule="")
    left = arm_reading(legacy, "S2", rows).commits[0]
    assert (left.outcome, left.left) == (None, LEFT_LINT_DISABLED)


#: Each way a reserved attempt can end, as ``(settled, the reserved rows, the reserved
#: verdict, the legacy outcome once a later clean row of another run exists)``. The
#: round-5 enumeration's probe ``test_side_channels_if_belt_values_were_withheld``
#: (round5/enum-replay/tree/tests/test_zz_enum_kill_probe.py) found the event stream before
#: ``ledger.append`` says whether the attempt missed (``grade.control`` is emitted only on a
#: miss), so an operator who peeks can cancel or kill the attempt — leaving a harness row or
#: no row — and let the legacy rule read the next run's clean row instead.
_C6_EXITS: dict[str, tuple[bool, tuple[dict[str, Any], ...], tuple[bool | None, str], bool]] = {
    "clean": (True, ({},), (True, ""), True),
    "miss": (True, ({"clean": False},), (False, "miss"), False),
    "harness": (True, ({"clean": False, "error": _G_HARNESS},), (False, "harness"), True),
    "outage": (True, ({"clean": False, "labels": dict(_G_OUTAGE)},), (False, "outage"), True),
    "error": (True, ({"clean": False, "error": PROTOCOL},), (False, "miss"), False),
    "no_row_terminal": (True, (), (False, "unobserved"), True),
    "no_row_reclaimed": (True, (), (False, "unobserved"), True),
    "no_row_running": (False, (), (None, "pending"), True),
    "cancel_harness": (
        True,
        ({"clean": False, "error": "harness: cancelled by the operator"},),
        (False, "harness"),
        True,
    ),
    "cancel_no_row": (True, (), (False, "unobserved"), True),
}


@pytest.mark.parametrize("exit_", sorted(_C6_EXITS))
def test_p792_c6_reserved_attempt_alone_decides(exit_: str) -> None:
    """C6: whatever the reserved attempt's exit — clean, miss, harness, outage, error, no
    row with its run terminal or reclaimed, a cancel that left a harness row or none — its
    verdict is the reserved row's alone, and later rows of other runs, of other
    reservations, or of a later claim of the same run never change it: a hit iff that row
    is clean. The legacy control reads the same rows and lets the later rows decide."""
    settled, reserved_rows, want, legacy_want = _C6_EXITS[exit_]
    pool = commits(2, prefix="x")
    reading = _reserved_reading(pool, hierarchy=("S3",))
    c = reading.pool[0]
    res = _res("S3", c, settled=settled)
    mine = [_reserved_row(res, **kw) for kw in reserved_rows]

    def later(clean: bool) -> list[GradeRow]:
        return [
            sealed_row(c, clean=clean, run_id="run-2"),  # another run, nothing reserved it
            sealed_row(
                c, clean=clean, run_id="run-3", labels=_stamp(res, reservation="ev-another")
            ),  # another reservation's attempt
            sealed_row(c, clean=clean, run_id=res.run_id, labels=_stamp(res, claim="1")),
            # the same run's later claim, stamped with the same reservation (reclaimed)
        ]

    loaded = _read(reading, [res])
    for tail in ([], later(True), later(False)):
        assert _verdicts(loaded, "S3", [*mine, *tail])[0] == want, tail
    # the legacy control: the same rows, the first observed attempt — later rows decide
    legacy = register_reading(pool, hierarchy=("S3",), budget=0.05)
    got = arm_reading(legacy, "S3", [*mine, *later(True)]).commits[0]
    assert (got.outcome, got.left) == (legacy_want, "")


def test_p792_c15_settled_without_a_row_is_a_miss() -> None:
    """C15: a reservation whose run is settled (terminal, or reclaimed past its claim) and
    wrote no reserved row is a miss — the attempt was admitted and ended without one, so
    the commit is spent. An unsettled one is pending; an unreserved commit is pending; and
    a reading whose reservations (or registration event) were never loaded reads every
    commit pending, never a hit."""
    reading = _reserved_reading(commits(3, prefix="u"), hierarchy=("S3",))
    p = reading.pool
    reservations = [_res("S3", p[0], settled=True), _res("S3", p[1], settled=False)]
    loaded = _read(reading, reservations)
    a = arm_reading(loaded, "S3", [])
    assert [(c.outcome, c.reason) for c in a.commits] == [
        (False, "unobserved"),
        (None, "pending"),
        (None, "pending"),
    ]
    assert (a.look.counted, a.look.misses, a.look.clean) == (1, 1, 0)
    assert a.left == ()
    # never loaded, or loaded without the registration event: every commit pending
    clean_row = _reserved_row(reservations[0])
    for unread in (reading, with_reservations(reading, reservations, 0)):
        assert unread.reservations_unread
        assert _verdicts(unread, "S3", [clean_row]) == [(None, "pending")] * 3
    # a campaign-named reading whose admissions were never read counts no row either
    camp = _read(_reserved_reading(commits(3, prefix="u"), hierarchy=("S3",), campaign_id="c"), [])
    assert camp.admissions_unread
    assert _verdicts(camp, "S3", []) == [(None, "pending")] * 3
    # the legacy control: no row is pending, whatever the run did
    legacy = register_reading(commits(3, prefix="u"), hierarchy=("S3",), budget=0.05)
    assert [c.outcome for c in arm_reading(legacy, "S3", []).commits] == [None] * 3


def test_p792_c19_counts_only_its_own_reservation() -> None:
    """C19: an arm counts only the row its own reservation wrote — the reservation's run,
    rung ``r1``, its event id and its claim. A row stamped with another reading's
    reservation, or an arm's row stamped with the other arm's, decides nothing."""
    reading = _reserved_reading(commits(2, prefix="o"))
    c = reading.pool[0]
    r3 = _res("S3", c, run="run-1", event="ev-s3")
    r1 = _res(S1, c, run="run-2", event="ev-s1")
    loaded = _read(reading, [r3, r1])
    stray = [
        _reserved_row(_res("S3", c, run="run-1", event="ev-other-reading")),
        sealed_row(c, arm=S1, run_id=r1.run_id, labels=_stamp(r3)),
        sealed_row(c, arm="S3", run_id=r3.run_id, labels=_stamp(r1)),
        sealed_row(c, arm="S3", run_id=r3.run_id, trial="r2", labels=_stamp(r3)),
    ]
    assert _verdicts(loaded, "S3", stray)[0] == (None, "pending")
    assert _verdicts(loaded, S1, stray)[0] == (None, "pending")
    own = [_reserved_row(r3, clean=False), _reserved_row(r1)]
    assert _verdicts(loaded, "S3", [*stray, *own])[0] == (False, "miss")
    assert _verdicts(loaded, S1, [*stray, *own])[0] == (True, "")
    # two rows of one reservation: neither is chosen
    dup = [*own, _reserved_row(r1, clean=False)]
    assert _verdicts(loaded, S1, dup)[0] == (False, "duplicate")


def test_p792_reserved_each_check_is_a_named_miss() -> None:
    """Every check the reserved row must pass is a miss named by its reason when it fails —
    never a leave, never a hit — on a replay arm and on a forward reading; each case's
    reserved row is otherwise the clean hit of the first case. A reservation that pins no
    treatment can never be a hit (fail closed)."""
    reading = _reserved_reading(commits(2, prefix="n"), hierarchy=("S3",))
    c = reading.pool[0]
    replay: dict[str, tuple[Reservation, dict[str, Any], tuple[bool | None, str]]] = {
        "hit": (_res("S3", c), {}, (True, "")),
        "treatment": (
            _res("S3", c),
            {"labels": {"treatment": "treat-2"}},
            (False, "treatment_mismatch"),
        ),
        "no_treatment": (
            _res("S3", c, treatment=""),
            {"labels": {"treatment": ""}},
            (False, "treatment_mismatch"),
        ),
        "before_registration": (_res("S3", c, seq=REG_EVENT), {}, (False, "before_registration")),
        "disqualified": (
            _res("S3", c),
            {"clean": False, "disqualified": True},
            (False, "disqualified"),
        ),
        "graded_before": (_res("S3", c), {"created": BEFORE}, (False, "out_of_scope")),
        "local_executor": (_res("S3", c), {"builder_executor": "local"}, (False, "out_of_scope")),
    }
    for name, (res, kw, expect) in replay.items():
        row = _reserved_row(res, **kw)
        got = arm_reading(_read(reading, [res]), "S3", [row]).commits[0]
        assert (got.outcome, got.reason) == expect, name
        assert got.left == "" and got.row_hash == row.row_hash, name
    # a campaign-named reading: a reserved row of a run its campaign never admitted
    camp = _reserved_reading(commits(2, prefix="n"), hierarchy=("S3",), campaign_id="camp-n")
    out = _res("S3", camp.pool[0], run="run-out")
    admitted = _read(with_admissions(camp, ["run-in"]), [out])
    assert _verdicts(admitted, "S3", [_reserved_row(out)])[0] == (False, "not_admitted")
    # a forward reading: the held-out result, the cell and the enrolling record decide too
    fwd = _reserved_forward(1)
    rec = _g_record(0)
    res = _res("S2", fwd.pool[0], run="fac-0", settled=True)
    forward: dict[str, tuple[dict[str, Any], tuple[bool | None, str]]] = {
        "hit": ({}, (True, "")),
        "held_out_fail": ({"result": RESULT_FAIL}, (False, "held_out")),
        "held_out_error": ({"result": RESULT_ERROR}, (False, "held_out")),
        "other_model": ({"model": "claude-haiku-5"}, (False, "other_cell")),
        "other_record": (
            {"stamp": held_out_labels(_g_record(1), RESULT_PASS)},
            (False, "not_graded"),
        ),
        "not_held_out": ({"stamp": {}}, (False, "not_graded")),
        "miss": ({"clean": False}, (False, "miss")),
    }
    for name, (kw, expect) in forward.items():
        row = _g_s2(rec, extra=_stamp(res), run_id=res.run_id, **kw)
        assert _verdicts(_read(fwd, [res]), "S2", [row]) == [expect], name


def test_p792_reserved_requires_max_reruns_zero_and_a_budget_profile() -> None:
    """A reserved.v1 registration has ``max_reruns`` 0 and names a budget profile, or is
    refused ``invalid_reading``; an unknown attempt rule is refused. The rule and the
    profile are hashed; the loaded reservations and registration event never are."""
    pool = commits(3, prefix="q")
    common: dict[str, Any] = {
        "repo": REPO,
        "cell": CELL,
        "hierarchy": ("S3",),
        "pool": pool,
        "apparatus": "2.4",
        "taxonomy": GLOBAL_CLASS_SET,
        "posture_class": SEALED,
        "checks_arm": "off",
        "actor": "op-1",
        "now": REGISTERED_AT,
        "budget": 0.05,
    }
    for bad in (
        {"attempt_rule": ATTEMPT_RULE_RESERVED, "budget_profile": PROFILE},  # max_reruns 2
        {"attempt_rule": ATTEMPT_RULE_RESERVED, "budget_profile": PROFILE, "max_reruns": 1},
        {"attempt_rule": ATTEMPT_RULE_RESERVED, "max_reruns": 0},  # no profile
        {"attempt_rule": ATTEMPT_RULE_RESERVED, "max_reruns": 0, "budget_profile": "  "},
        {"attempt_rule": "first_seen.v9", "max_reruns": 0, "budget_profile": PROFILE},
    ):
        with pytest.raises(ReadingRefused) as exc:
            register(**common, **bad)
        assert exc.value.code == REFUSAL_INVALID, bad
    ok = register(
        **common, attempt_rule=ATTEMPT_RULE_RESERVED, max_reruns=0, budget_profile=PROFILE
    )
    assert (ok.attempt_rule, ok.budget_profile, ok.max_reruns) == (
        ATTEMPT_RULE_RESERVED,
        PROFILE,
        0,
    )
    assert ok.reserved and ok.reservations_unread
    body = ok.body()
    assert (body["attempt_rule"], body["budget_profile"]) == (ATTEMPT_RULE_RESERVED, PROFILE)
    other = register(
        **common, attempt_rule=ATTEMPT_RULE_RESERVED, max_reruns=0, budget_profile="calibrated"
    )
    assert other.reading_id != ok.reading_id
    back = Reading.from_dict(ok.to_dict())
    assert back == ok and back.reading_id == ok.reading_id and back.verify()
    # loaded, never hashed or served: the id, the body and equality are unchanged
    loaded = _read(ok, [_res("S3", ok.pool[0])])
    assert not loaded.reservations_unread and loaded.registered_event_id == REG_EVENT
    assert loaded == ok and loaded.to_dict() == ok.to_dict() and loaded.verify()
    assert "reservations" not in loaded.to_dict() and "registered_event_id" not in loaded.body()
    # the first reservation per (arm, commit) by event id is the one that counts
    first = _res("S3", ok.pool[0], event="ev-first", seq=12)
    later = _res("S3", ok.pool[0], event="ev-later", seq=13)
    assert loaded.reservations is not None
    assert _read(ok, [later, first]).reservations == {("S3", ok.pool[0]): first}
    # a legacy registration: nothing new is hashed; the legacy rule's name is the same rule
    legacy = register(**common)
    named = register(**common, attempt_rule=ATTEMPT_RULE_LEGACY, budget_profile=PROFILE)
    assert named.reading_id == legacy.reading_id and named.attempt_rule == ""
    assert "attempt_rule" not in legacy.body() and "budget_profile" not in legacy.body()
    assert not legacy.reserved and with_reservations(legacy, [], REG_EVENT) == legacy
    # the forward registration under reserved.v1 has no re-run either
    fwd = _reserved_forward(1)
    assert fwd.max_reruns == 0 and fwd.budget_profile == PROFILE
    with pytest.raises(ReadingRefused) as exc:
        _reserved_forward(1, attempt_rule="first_seen.v9")
    assert exc.value.code == REFUSAL_INVALID


#: A blind run's arm is A0, a sighted replay's S3, and ``arm: S1`` on a blind run is the S1
#: arm of the reading's test author; with neither ``learning`` nor ``budget_profile`` the
#: loop is on (``+L``). Every other key a run can carry is refused.
_RUN_OK: dict[str, Any] = {
    "task_ids": ["t"],
    "limit": 0,
    "pool": "",
    "executor": "",
    "timeout": 0,
    "max_cost_usd": 4.0,
    "learning": "off",
    "budget_profile": PROFILE,
    "reading_id": "rdg_x",
    "campaign_id": "camp-w",
    "outage_stop": 3,
    "env_stop": 3,
    "qualify_first": False,
}
_NO_LOOP_KEYS = {k: v for k, v in _RUN_OK.items() if k not in ("learning", "budget_profile")}
_S3_RUN: dict[str, Any] = {"kind": "replay", "mode": "sighted"}
_A0_RUN: dict[str, Any] = {"kind": "blind", "mode": "blind"}
_CELL_RUN: dict[str, Any] = {
    "builder": "claude_code",
    "model": "claude-sonnet-5",
    "provider": "anthropic",
    "ladder": ["r1"],
}
#: ``(name, run fields over _S3_RUN, params, the arm when admitted, the refused fields)``.
_RUN_TABLE: list[tuple[str, dict[str, Any], dict[str, Any], str, list[str]]] = [
    ("s3", {}, _RUN_OK, "S3", []),
    ("a0", _A0_RUN, _RUN_OK, "A0", []),
    (
        "s1_named",
        _A0_RUN,
        {**_RUN_OK, "arm": "S1", "test_author": "claude_code:claude-opus-5"},
        S1,
        [],
    ),
    ("s1_reading_author", _A0_RUN, {**_RUN_OK, "arm": "S1"}, S1, []),
    ("a0_loop", _A0_RUN, _NO_LOOP_KEYS, "A0+L", []),
    ("s3_loop_not_read", {}, _NO_LOOP_KEYS, "", ["arm"]),
    *(
        (f"key_{k}", {}, {**_RUN_OK, k: v}, "", [k])
        for k, v in {
            "builder_config": {"extra_args": ["--model", "x"]},
            "ladder": ["r1"],
            "budget": {"max_turns": 3},
            "retain": {"worktrees": True},
            "preflight": True,
            "escalation": "rung",
            "checks": {"finish_gate": False},
            "taxonomy": "acme@1",
            "unknown": 1,
        }.items()
    ),
    ("timeout", {}, {**_RUN_OK, "timeout": 1}, "", ["timeout"]),
    ("pool", {}, {**_RUN_OK, "pool": "since:2026-09-01"}, "", ["pool"]),
    ("executor", {}, {**_RUN_OK, "executor": "local"}, "", ["executor"]),
    ("ladder_rung", {"ladder": ["claude_code:claude-opus-5"]}, _RUN_OK, "", ["ladder"]),
    ("ladder_two", {"ladder": ["r1", "r2"]}, _RUN_OK, "", ["ladder"]),
    ("ladder_empty", {"ladder": []}, _RUN_OK, "", ["ladder"]),
    ("cell_model", {"model": "claude-haiku-5"}, _RUN_OK, "", ["model"]),
    ("cell_builder", {"builder": "openai_agent"}, _RUN_OK, "", ["builder"]),
    ("cell_provider", {"provider": "bedrock"}, _RUN_OK, "", ["provider"]),
    ("arm_mode", {"mode": "blind"}, _RUN_OK, "", ["mode"]),
    ("arm_kind", {"kind": "factory"}, _RUN_OK, "", ["kind"]),
    ("arm_s1_sighted", {}, {**_RUN_OK, "arm": "S1"}, "", ["arm"]),
    ("arm_other", _A0_RUN, {**_RUN_OK, "arm": "S2"}, "", ["arm"]),
    (
        "arm_author",
        _A0_RUN,
        {**_RUN_OK, "arm": "S1", "test_author": "openai_agent:gpt-9"},
        "",
        ["test_author"],
    ),
    (
        "author_without_s1",
        _A0_RUN,
        {**_RUN_OK, "test_author": "claude_code:claude-opus-5"},
        "",
        ["test_author"],
    ),
    (
        "loop_with_learning",
        _A0_RUN,
        {**_NO_LOOP_KEYS, "learning": "on"},
        "",
        ["budget_profile", "learning"],
    ),
    ("c7_profile", {}, {**_RUN_OK, "budget_profile": "calibrated"}, "", ["budget_profile"]),
    (
        "c7_profile_only",
        {},
        {k: v for k, v in _RUN_OK.items() if k != "learning"},
        "",
        ["learning"],
    ),
    ("learning_on", {}, {**_RUN_OK, "learning": "on"}, "", ["learning"]),
]


@pytest.mark.parametrize(
    ("name", "run", "params", "arm", "refused"), _RUN_TABLE, ids=[t[0] for t in _RUN_TABLE]
)
def test_p792_reading_run_refusal_whitelist(
    name: str, run: dict[str, Any], params: dict[str, Any], arm: str, refused: list[str]
) -> None:
    """C3, C5 and C7 at the core: a run of a reserved.v1 reading may carry only the keys of
    :data:`RESERVED_RUN_PARAMS` — no ``builder_config``, budget, checks, preflight or
    escalation can steer its attempts; ``pool``, ``executor`` and ``timeout`` keep their
    defaults and the ladder is the default ``["r1"]``; it builds on the reading's own cell;
    its arm is one the reading reads; and a non-loop arm runs with the loop off on the
    reading's budget profile (C7) while the ``+L`` arm names neither."""
    reading = _reserved_reading(
        commits(3, prefix="w"), descriptive=(("A0", 2), ("A0+L", 2)), campaign_id="camp-w"
    )
    fields = {**_S3_RUN, **_CELL_RUN, **run}
    code, detail = reading_run_refusal(reading, params=params, **fields)
    if not refused:
        assert (code, detail) == ("", {}), name
        return
    assert code == REFUSAL_RUN_FIELDS, name
    assert detail["fields"] == refused, (name, detail)
    assert set(detail["reasons"]) == set(refused)
    assert all(detail["reasons"][f] for f in refused)
    # a legacy reading is never refused by it: the legacy rule is unchanged
    legacy = register_reading(commits(3, prefix="w"), descriptive=(("A0", 2),), budget=0.05)
    assert reading_run_refusal(legacy, params=params, **fields) == ("", {})
    assert arm == ""


def test_p792_reading_run_refusal_names_the_whitelist() -> None:
    """The whitelist and the one ladder are the core's constants, so the submit check and
    the claim check refuse the same runs; and each admitted run maps to the arm the table
    names — a reading without that arm refuses the run, naming the arm it would have run."""
    whitelist = frozenset(
        {
            "task_ids",
            "limit",
            "pool",
            "executor",
            "timeout",
            "max_cost_usd",
            "budget_profile",
            "learning",
            "arm",
            "test_author",
            "reading_id",
            "campaign_id",
            "outage_stop",
            "env_stop",
            "qualify_first",
        }
    )
    assert whitelist == RESERVED_RUN_PARAMS
    assert RESERVED_RUN_LADDER == ("r1",)
    reading = _reserved_reading(commits(3, prefix="w"), descriptive=(("A0", 2), ("A0+L", 2)))
    for name, run, params, arm, refused in _RUN_TABLE:
        if refused:
            continue
        fields = {**_S3_RUN, **_CELL_RUN, **run}
        assert arm in reading.arms, name
        assert reading_run_refusal(reading, params=params, **fields) == ("", {}), name
        without = _reserved_reading(
            commits(3, prefix="w"),
            hierarchy=[a for a in ("S3", S1) if a != arm],
            descriptive=[(a, 2) for a in ("A0", "A0+L") if a != arm],
            author_model=AUTHOR,
        )
        assert arm not in without.arms, name
        code, detail = reading_run_refusal(without, params=params, **fields)
        assert (code, detail["fields"], detail["arm"]) == (REFUSAL_RUN_FIELDS, ["arm"], arm), name


# --- the reserved rule is strictly more conservative than the legacy one ------------------

#: Each exit the reserved attempt of a commit can take in the property below.
_R_EXITS = (
    "clean",
    "miss",
    "harness",
    "outage",
    "error",
    "lint_clean",
    "disqualified",
    "no_row_settled",
    "no_row_open",
    "treatment",
    "before_registration",
    "unreserved",
)
_LATER = ("clean", "miss", "harness", "outage")
#: The drawn head of the pool: enough for every look of every rule.
_DRAWN = 42
#: The pool: the drawn head, then a clean tail long enough that the legacy pool still holds
#: every look after its leaves (each drawn commit can leave at most once), so the legacy
#: reading is never short of commits where the reserved one decides.
_H_POOL = commits(_DRAWN + 48, prefix="h")


def _r_rows(exit_: str, res: Reservation) -> list[GradeRow]:
    """The reserved attempt's rows for ``exit_`` (none when it wrote none)."""
    shapes: dict[str, dict[str, Any] | None] = {
        "clean": {},
        "miss": {"clean": False},
        "harness": {"clean": False, "error": _G_HARNESS},
        "outage": {"clean": False, "labels": dict(_G_OUTAGE)},
        "error": {"clean": False, "error": PROTOCOL},
        "lint_clean": {"labels": {"lint_reason": LINT_DISABLED_BY_CONFIG}},
        "disqualified": {"clean": False, "disqualified": True},
        "no_row_settled": None,
        "no_row_open": None,
        "treatment": {"labels": {"treatment": "treat-2"}},
        "before_registration": {},
    }
    if exit_ == "unreserved":
        return [sealed_row(res.task_id, run_id=res.run_id)]  # nothing reserved the attempt
    kw = shapes[exit_]
    return [] if kw is None else [_reserved_row(res, **kw)]


def _later_row(commit: str, kind: str, run: str) -> GradeRow:
    shapes: dict[str, dict[str, Any]] = {
        "clean": {},
        "miss": {"clean": False},
        "harness": {"clean": False, "error": _G_HARNESS},
        "outage": {"clean": False, "labels": dict(_G_OUTAGE)},
    }
    return sealed_row(commit, run_id=run, **shapes[kind])


@settings(max_examples=200, database=None, deadline=None)
@given(st.data())
def test_p792_new_hits_subset_of_old(data: st.DataObject) -> None:
    """The round-5 argument, over random worlds: the reserved attempt is one of the
    commit's attempts, so a reserved hit is a legacy hit (the legacy rule's first observed
    attempt is the reserved one when it is clean); the legacy rule only removes commits
    the reserved rule reads as non-hits, so for every prefix ``n`` the legacy hits among
    its first ``n`` kept commits are at least the reserved hits among the first ``n``
    enrolled; and so a reserved ``deliver`` is a legacy ``deliver`` at the same look or
    earlier. Every legacy commit has a final observed row, so the legacy world is complete
    (no re-run left to wait for)."""
    rule = data.draw(st.sampled_from(sorted(RULES)), label="rule")
    order = list(register_reading(_H_POOL, hierarchy=("S3",), budget=0.05).pool)
    changes: dict[str, str] = {}
    pairs = data.draw(
        st.lists(st.tuples(st.integers(0, _DRAWN - 1), st.integers(0, _DRAWN - 1)), max_size=4),
        label="same-change pairs",
    )
    for k, (i, j) in enumerate(pairs):
        if i != j:
            changes[order[i]] = changes[order[j]] = f"dup-{k}"
    if data.draw(st.booleans(), label="dense"):
        exits = data.draw(
            st.lists(st.sampled_from(_R_EXITS), min_size=_DRAWN, max_size=_DRAWN), label="exits"
        )
    else:
        exits = ["clean"] * _DRAWN
        for pos in data.draw(st.lists(st.integers(0, _DRAWN - 1), max_size=6), label="noise"):
            exits[pos] = data.draw(st.sampled_from(_R_EXITS))
    reservations: list[Reservation] = []
    rows: list[GradeRow] = []
    for i, commit in enumerate(order):
        exit_ = exits[i] if i < _DRAWN else "clean"
        res = _res(
            "S3",
            commit,
            run=f"run-{i}",
            seq=REG_EVENT - 5 if exit_ == "before_registration" else REG_EVENT + 1 + i,
            settled=exit_ != "no_row_open",
        )
        if exit_ != "unreserved":
            reservations.append(res)
        rows += _r_rows(exit_, res)
        if i >= _DRAWN:
            continue
        for k, kind in enumerate(data.draw(st.lists(st.sampled_from(_LATER), max_size=3))):
            rows.append(_later_row(commit, kind, f"later-{i}-{k}"))
        rows.append(sealed_row(commit, clean=data.draw(st.booleans()), run_id=f"final-{i}"))
    legacy = register_reading(_H_POOL, hierarchy=("S3",), rule=rule, budget=0.05, changes=changes)
    reserved = _read(
        _reserved_reading(_H_POOL, hierarchy=("S3",), rule=rule, changes=changes), reservations
    )
    old = arm_reading(legacy, "S3", rows)
    new = arm_reading(reserved, "S3", rows)
    assert [c.commit for c in new.commits] == list(enrolled(reserved, "S3"))
    assert [c.commit for c in new.commits] == [
        c.commit for c in old.commits if c.left != "same_change"
    ]
    assert all(not c.left for c in new.commits)
    old_by = {c.commit: c for c in old.commits}
    for c in new.commits:
        if c.outcome is True:
            assert (old_by[c.commit].outcome, old_by[c.commit].left) == (True, "")
    kept = [c for c in old.commits if not c.left]
    assert all(c.outcome is not None for c in kept)  # the legacy world is complete
    assert len(kept) >= max(n for looks in RULES.values() for n in looks)
    for n in range(len(new.commits) + 1):
        old_hits = sum(c.outcome is True for c in kept[:n])
        new_hits = sum(c.outcome is True for c in new.commits[:n])
        assert old_hits >= new_hits, n
    if new.look.state == STATE_DELIVER:
        assert old.look.state == STATE_DELIVER
        assert old.look.decided_at is not None and new.look.decided_at is not None
        assert old.look.decided_at <= new.look.decided_at
