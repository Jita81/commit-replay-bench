"""crb.core.quote — the mapping quote: tasks, cost, time and precision before any spend.

Navigation
----------
What it is:   The core mapping quote's test suite — what a first mapping of a repository would
              run, cost and take, and the precision it would buy, priced from recorded rows.
What it does: Pins the Wilson half-width at p = 0.5 against ``wilson_interval``; tasks capped
              at what is available with the shortfall and what is left; the basis tiers (this
              repository, the deployment, a declared band, unknown) and that unknown is never
              zero; that a row which metered nothing is never a $0 basis; newest apparatus
              only; that other builders, models, modes, steps, rungs and arms never enter a
              basis; one hand-computed band; cell selection; that more tasks never cost less;
              totals over one set of cells; byte-stable output; and the two blinding proofs
              (a field whitelist and invariance to outcome fields).
How:          ``types.SimpleNamespace`` rows carrying only the fifteen ``CostRow`` fields (so a
              read of any other field fails), and real ``GradeRow``s for the perturbation proof.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0058-mapping-quote.md
Works with:   src/crb/core/quote.py (under test), src/crb/core/stats.py (``wilson_interval``,
              the reference for the half-width), tests/test_server_routes_quote.py (the same
              quote served), tests/fixtures/readings.py (``live_labels`` for real rows)
Tested by:    tests/test_quote.py
Touch when:   never for a new repository; the basis tiers, the range method or a fixed
              statement of the quote changes (mirror docs/adr/0058-mapping-quote.md).
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import random
from types import SimpleNamespace
from typing import Any

import pytest

from crb.core import quote as q
from crb.core.stats import wilson_interval
from fixtures.posture import posture_row
from fixtures.readings import live_labels

BUILDER = "claude_code"
MODEL = "claude-sonnet-5"
REPO = "todo"


def _ns(
    *,
    repo: str = REPO,
    cls: str = "bug.fix",
    size: str = "S",
    builder: str = BUILDER,
    model: str = MODEL,
    mode: str = "sighted",
    step: str = "replay",
    trial: str = "r1",
    arm: str = "S3",
    apparatus: str = "2.6",
    cost_known: bool = True,
    cost: float = 0.1,
    tokens_in: int = 1000,
    tokens_out: int = 100,
    latency: float = 60.0,
) -> SimpleNamespace:
    """A row carrying ONLY the fifteen ``CostRow`` fields: a read of any other attribute
    raises ``AttributeError``."""
    return SimpleNamespace(
        repo=repo,
        capability_class=cls,
        size=size,
        builder=builder,
        model=model,
        mode=mode,
        process_step=step,
        trial=trial,
        context_arm=arm,
        apparatus_version=apparatus,
        cost_known=cost_known,
        cost_usd=cost,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_s=latency,
    )


def _rows(n: int, *, cost: float = 0.1, sd: float = 0.02, **kw: Any) -> list[SimpleNamespace]:
    """``n`` rows whose costs alternate ``cost ± sd`` and whose times alternate 60 ± 10 s."""
    return [
        _ns(cost=cost + (sd if i % 2 else -sd), latency=60.0 + (10 if i % 2 else -10), **kw)
        for i in range(n)
    ]


def _quote(**kw: Any) -> q.MappingQuote:
    base: dict[str, Any] = {
        "repo": REPO,
        "builder": BUILDER,
        "model": MODEL,
        "available": {("bug.fix", "S"): 30},
        "availability_source": q.AVAILABILITY_MINED,
        "own_rows": [],
        "other_rows": [],
        "n_default": 20,
        "selection": None,
        "declared": None,
    }
    base.update(kw)
    return q.mapping_quote(**base)


def _cell(quote: q.MappingQuote, label: str = "bug.fix/S") -> dict[str, Any]:
    cells = {c["label"]: c for c in quote.to_dict()["cells"]}
    return dict(cells[label])


# ---------------------------------------------------------------------------
# precision
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [2, 10, 20, 40])
def test_half_width_at_half_matches_wilson_for_even_n(n: int) -> None:
    assert q.half_width_at_half(n) == pytest.approx(wilson_interval(n // 2, n).width / 2)


def test_half_width_shrinks_as_n_grows() -> None:
    widths = [q.half_width_at_half(n) for n in range(0, 101)]
    assert widths[0] == 0.5
    assert all(b < a for a, b in itertools.pairwise(widths))


# ---------------------------------------------------------------------------
# tasks
# ---------------------------------------------------------------------------


def test_tasks_to_run_capped_at_available_with_shortfall_and_left_after() -> None:
    c = _cell(_quote(available={("bug.fix", "S"): 12}, n_default=20, own_rows=_rows(4)))
    assert c["requested"] == 20 and c["available"] == 12
    assert c["tasks_to_run"] == 12 and c["shortfall"] == 8 and c["left_after"] == 0
    assert c["attempts"] == 12
    assert c["wilson_half_width_p50"] == pytest.approx(round(q.half_width_at_half(12), 6))
    c = _cell(_quote(available={("bug.fix", "S"): 30}, n_default=20, own_rows=_rows(4)))
    assert c["tasks_to_run"] == 20 and c["shortfall"] == 0 and c["left_after"] == 10


# ---------------------------------------------------------------------------
# the basis tiers
# ---------------------------------------------------------------------------


def test_repo_cell_basis_wins_over_deployment_rows() -> None:
    quote = _quote(own_rows=_rows(4, cost=0.1), other_rows=_rows(6, cost=5.0, repo="other"))
    c = _cell(quote)
    assert c["basis"]["tier"] == q.TIER_REPO
    assert c["basis"]["n_rows"] == 4 and c["basis"]["n_repos"] == 1
    assert c["basis"]["cost_per_attempt"]["value"] == pytest.approx(0.1)
    assert c["cost_usd"]["expected"] == pytest.approx(2.0)  # 20 attempts at $0.10


def test_deployment_basis_when_repo_has_fewer_than_two_known_rows() -> None:
    other = _rows(4, cost=0.2, repo="other-a") + _rows(2, cost=0.2, repo="other-b")
    c = _cell(_quote(own_rows=_rows(1), other_rows=other))
    b = c["basis"]
    assert b["tier"] == q.TIER_DEPLOYMENT and b["n_rows"] == 6 and b["n_repos"] == 2
    assert b["tag"].startswith("[hypothesis]")
    assert c["cost_usd"]["expected"] == pytest.approx(4.0)


def test_declared_band_only_without_rows_and_has_no_expected_or_minutes() -> None:
    c = _cell(_quote(declared=(0.05, 0.5)))
    assert c["basis"]["tier"] == q.TIER_DECLARED and c["basis"]["n_rows"] == 0
    assert c["cost_usd"]["low"] == pytest.approx(1.0) and c["cost_usd"]["high"] == pytest.approx(10)
    assert c["cost_usd"]["expected"] is None
    assert c["minutes"]["low"] is None and c["minutes"]["expected"] is None
    assert c["minutes"]["reason"]
    # a declared band never overrides a row basis
    c = _cell(_quote(declared=(0.05, 0.5), own_rows=_rows(4)))
    assert c["basis"]["tier"] == q.TIER_REPO


def test_no_basis_is_unknown_with_reason_never_zero() -> None:
    quote = _quote(own_rows=[], other_rows=_rows(1, repo="other"))
    c = _cell(quote)
    assert c["basis"]["tier"] == q.TIER_UNKNOWN
    for band in (c["cost_usd"], c["minutes"]):
        assert band["low"] is None and band["expected"] is None and band["high"] is None
        assert band["reason"]
    assert "any other on this deployment (1, needs 2)" in c["basis"]["reason"]
    t = quote.to_dict()["totals"]
    assert t["unpriced"] == ["bug.fix/S"] and t["cells_unknown"] == 1
    assert t["cost_usd_low"] is None and t["cost_usd_high"] is None
    assert t["cost_usd_expected"] is None and t["tasks_priced"] == 0


def test_unknown_cost_rows_never_read_as_zero() -> None:
    rows = _rows(3, cost=0.3, sd=0.0) + [_ns(cost=0.0, cost_known=False) for _ in range(10)]
    c = _cell(_quote(own_rows=rows))
    assert c["basis"]["n_rows"] == 3
    assert c["basis"]["cost_per_attempt"]["value"] == pytest.approx(0.3)
    # only unknown rows: no basis at all, never a $0 basis
    c = _cell(_quote(own_rows=[_ns(cost=0.0, cost_known=False) for _ in range(10)]))
    assert c["basis"]["tier"] == q.TIER_UNKNOWN and c["cost_usd"]["low"] is None


def test_row_that_metered_nothing_is_never_a_zero_basis() -> None:
    # a refused call (an outage row): a builder is named, so its $0 reads "known", but it
    # metered no token: it observed no cost, and never prices a cell at $0
    refused = [_ns(cost=0.0, tokens_in=0, tokens_out=0) for _ in range(3)]
    c = _cell(_quote(own_rows=refused))
    assert c["basis"]["tier"] == q.TIER_UNKNOWN and c["cost_usd"]["expected"] is None
    assert _quote(own_rows=refused).to_dict()["totals"]["cost_usd_expected"] is None
    # nor does it keep the cell from the deployment tier
    c = _cell(_quote(own_rows=refused, other_rows=_rows(3, cost=0.4, sd=0.0, repo="other")))
    assert c["basis"]["tier"] == q.TIER_DEPLOYMENT
    assert c["cost_usd"]["expected"] == pytest.approx(20 * 0.4)
    # a metered $0 (tokens on a subscription) is a real zero and counts
    free = [_ns(cost=0.0, tokens_in=500, tokens_out=0) for _ in range(3)]
    c = _cell(_quote(own_rows=free))
    assert c["basis"]["tier"] == q.TIER_REPO and c["cost_usd"]["expected"] == 0


def test_negative_cost_row_never_enters_a_basis() -> None:
    # a negative cost with tokens is cost_known on the row, but it is not a price: two of
    # them used to price a cell at low 0, expected -1, high -1, an inverted band
    bad = [_ns(cost=-1.0) for _ in range(2)]
    c = _cell(_quote(own_rows=bad, selection={("bug.fix", "S"): 1}))
    assert c["basis"]["tier"] == q.TIER_UNKNOWN and c["cost_usd"]["low"] is None
    # mixed with real rows, only the real rows count and the band stays ordered
    c = _cell(_quote(own_rows=[*bad, *_rows(3, cost=0.2, sd=0.0)]))
    assert c["basis"]["n_rows"] == 3
    band = c["cost_usd"]
    assert 0 <= band["low"] <= band["expected"] <= band["high"]


def test_totals_note_never_claims_a_joint_interval() -> None:
    # one priced cell with identical rows: the summed range has zero width, so it is not
    # "wider than a joint 95% interval"; the note says only that it is not one
    t = _quote(own_rows=_rows(3, cost=0.1, sd=0.0)).to_dict()["totals"]
    assert t["cost_usd_low"] == t["cost_usd_high"]
    assert "wider" not in t["note"] and "not a calibrated joint 95% interval" in t["note"]


def test_newest_apparatus_only_never_pooled() -> None:
    rows = [_ns(apparatus="2.6", cost=9.0), *_rows(10, apparatus="2.5")]
    c = _cell(_quote(own_rows=rows, other_rows=_rows(3, cost=0.4, sd=0.0, repo="other")))
    # the one 2.6 row is not enough and 2.5 is never searched: the deployment tier speaks
    assert c["basis"]["tier"] == q.TIER_DEPLOYMENT
    assert c["basis"]["apparatus_version"] == "2.6"
    assert c["basis"]["cost_per_attempt"]["value"] == pytest.approx(0.4)
    # 2.10 is newer than 2.9 (numeric, not text, order)
    rows = _rows(2, apparatus="2.10", cost=1.0, sd=0.0) + _rows(5, apparatus="2.9", cost=7.0)
    c = _cell(_quote(own_rows=rows))
    assert c["basis"]["apparatus_version"] == "2.10" and c["basis"]["n_rows"] == 2


def test_other_builder_model_mode_or_step_never_enter_basis() -> None:
    noise = (
        _rows(5, builder="editblock", cost=9.0)
        + _rows(5, model="other-model", cost=9.0)
        + _rows(5, mode="blind", cost=9.0)
        + _rows(5, step="factory", cost=9.0)
        + _rows(5, cls="test.add", cost=9.0)
        + _rows(5, size="M", cost=9.0)
        # a later rung holds only the tasks that failed r1: harder, costlier
        + _rows(5, trial="r2", cost=9.0)
        # other arms carry bigger briefs; a context-set arm is measurement only
        + _rows(5, arm="S3+L", cost=9.0)
        + _rows(5, arm="S1@claude-opus", cost=9.0)
        + _rows(5, arm="S3+library@ctx.v1", cost=9.0)
        # a 2.4+ row with no arm is not a first mapping's row
        + _rows(5, arm="", cost=9.0)
    )
    c = _cell(_quote(own_rows=noise))
    assert c["basis"]["tier"] == q.TIER_UNKNOWN
    c = _cell(_quote(own_rows=noise + _rows(2, cost=0.1, sd=0.0)))
    assert c["basis"]["n_rows"] == 2
    assert c["basis"]["cost_per_attempt"]["value"] == pytest.approx(0.1)
    # a row from before 2.4 carries no arm: kept, at its own apparatus
    c = _cell(_quote(own_rows=_rows(2, arm="", apparatus="2.3", cost=0.1, sd=0.0)))
    assert c["basis"]["tier"] == q.TIER_REPO and c["basis"]["apparatus_version"] == "2.3"


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------


def test_selection_limits_cells_and_star_expands_class() -> None:
    available = {("bug.fix", "S"): 9, ("bug.fix", "M"): 4, ("test.add", "XS"): 7}
    quote = _quote(available=available, selection={("bug.fix", ""): 5, ("test.add", "XS"): 3})
    cells = quote.to_dict()["cells"]
    assert [c["label"] for c in cells] == ["bug.fix/S", "bug.fix/M", "test.add/XS"]
    assert [c["requested"] for c in cells] == [5, 5, 3]
    assert [c["tasks_to_run"] for c in cells] == [5, 4, 3]
    # no selection: every cell with a task, at the default n
    quote = _quote(available={**available, ("docs.update", "S"): 0}, n_default=6)
    cells = quote.to_dict()["cells"]
    assert [c["label"] for c in cells] == ["bug.fix/S", "bug.fix/M", "test.add/XS"]
    assert [c["tasks_to_run"] for c in cells] == [6, 4, 6]
    # a size named on its own beats the class's star, whichever comes first
    sel = {("bug.fix", "M"): 2, ("bug.fix", ""): 5}
    cells = _quote(available=available, selection=sel).to_dict()["cells"]
    assert [(c["label"], c["requested"]) for c in cells] == [("bug.fix/S", 5), ("bug.fix/M", 2)]


def test_selected_cell_with_no_tasks_listed_with_zero_and_no_cost() -> None:
    quote = _quote(selection={("docs.update", "S"): 5}, own_rows=_rows(4))
    c = _cell(quote, "docs.update/S")
    assert c["available"] == 0 and c["tasks_to_run"] == 0 and c["shortfall"] == 5
    assert c["cost_usd"]["low"] == 0 and c["cost_usd"]["high"] == 0
    assert c["minutes"]["expected"] == 0 and "nothing" in c["cost_usd"]["reason"]
    assert c["wilson_half_width_p50"] == 0.5


# ---------------------------------------------------------------------------
# the range
# ---------------------------------------------------------------------------


def test_more_n_never_costs_less() -> None:
    own = _rows(5, cost=0.2, sd=0.15)
    other = _rows(3, cost=0.3, sd=0.2, cls="test.add", size="XS", repo="other")
    available = {("bug.fix", "S"): 100, ("test.add", "XS"): 100}
    prev: dict[str, float] | None = None
    for n in range(1, 61):
        d = _quote(available=available, n_default=n, own_rows=own, other_rows=other).to_dict()
        now: dict[str, float] = {}
        for c in d["cells"]:
            for axis in ("cost_usd", "minutes"):
                for k in ("low", "expected", "high"):
                    now[f"{c['label']}:{axis}:{k}"] = c[axis][k]
        t = d["totals"]
        for k in ("cost_usd_low", "cost_usd_expected", "cost_usd_high"):
            now[k] = t[k]
        for k in ("minutes_low", "minutes_expected", "minutes_high"):
            now[k] = t[k]
        if prev is not None:
            worse = {k: (prev[k], v) for k, v in now.items() if v < prev[k]}
            assert not worse, (n, worse)
        prev = now


def test_hand_computed_band() -> None:
    # 7 tasks; costs 0.1/0.2/0.3 (m 0.2, s 0.1), times 30/60/90 s (m 60, s 30); t975(2) 4.3027
    # half = 4.3027 * s * sqrt(7 + 49/3)
    own = [_ns(cost=c, latency=t) for c, t in ((0.1, 30.0), (0.2, 60.0), (0.3, 90.0))]
    c = _cell(_quote(own_rows=own, available={("bug.fix", "S"): 7}, n_default=20))
    assert (c["tasks_to_run"], c["shortfall"], c["left_after"]) == (7, 13, 0)
    assert c["wilson_half_width_p50"] == pytest.approx(0.297628, abs=1e-6)
    cost, minutes = c["cost_usd"], c["minutes"]
    assert (cost["low"], cost["expected"]) == (0.0, pytest.approx(1.4))
    assert cost["high"] == pytest.approx(3.478379, abs=1e-6)
    assert (minutes["low"], minutes["expected"]) == (0.0, pytest.approx(7.0))
    assert minutes["high"] == pytest.approx(17.391894, abs=1e-6)
    assert "thin basis of 3 rows" in cost["reason"]


def test_band_reason_flags_a_basis_with_no_spread() -> None:
    c = _cell(_quote(own_rows=_rows(6, cost=0.2, sd=0.0)))
    assert c["cost_usd"]["low"] == c["cost_usd"]["high"]
    assert "identical" in c["cost_usd"]["reason"] and "not certainty" in c["cost_usd"]["reason"]
    # spread and five rows or more: no caution
    c = _cell(_quote(own_rows=_rows(6, cost=0.2, sd=0.05)))
    assert c["cost_usd"]["reason"] == "" and c["minutes"]["reason"] == ""


def test_time_never_falls_through_to_another_tier() -> None:
    own = [_ns(cost=0.1, latency=0.0), _ns(cost=0.2, latency=0.0)]
    other = _rows(8, repo="other")
    c = _cell(_quote(own_rows=own, other_rows=other))
    assert c["basis"]["tier"] == q.TIER_REPO and c["basis"]["n_time_rows"] == 0
    assert c["minutes"]["low"] is None and c["minutes"]["expected"] is None
    assert "never falls through" in c["minutes"]["reason"]
    assert c["cost_usd"]["expected"] == pytest.approx(20 * 0.15)


def test_range_contains_expected_and_low_floors_at_zero() -> None:
    wide = [_ns(cost=c) for c in (0.01, 0.01, 0.01, 2.0)]
    c = _cell(_quote(own_rows=wide, n_default=1, available={("bug.fix", "S"): 5}))
    band = c["cost_usd"]
    assert band["low"] == 0.0 and band["low"] <= band["expected"] <= band["high"]
    s = q.sum_range([0.1, 0.12, 0.08, 0.11], 20)
    assert 0 <= s.low <= s.expected <= s.high and s.k == 4
    assert s.expected == pytest.approx(20 * 0.1025)
    with pytest.raises(ValueError):
        q.sum_range([0.1], 3)


# ---------------------------------------------------------------------------
# stability and blinding
# ---------------------------------------------------------------------------


def test_output_is_byte_stable() -> None:
    own = _rows(7, cost=0.13, sd=0.05)
    other = _rows(5, cost=0.2, sd=0.07, cls="test.add", size="XS", repo="other")
    available = {("bug.fix", "S"): 12, ("test.add", "XS"): 3, ("bug.fix", "M"): 2}
    a = json.dumps(_quote(available=available, own_rows=own, other_rows=other).to_dict())
    b = json.dumps(_quote(available=available, own_rows=own, other_rows=other).to_dict())
    assert a == b
    rng = random.Random(7)
    for _ in range(5):
        own2, other2 = own[:], other[:]
        rng.shuffle(own2)
        rng.shuffle(other2)
        items = list(available.items())
        rng.shuffle(items)
        c = json.dumps(_quote(available=dict(items), own_rows=own2, other_rows=other2).to_dict())
        assert c == a
    assert "as_of" not in a and "2026-" not in a


def test_reads_only_cost_fields() -> None:
    # SimpleNamespace rows with only the CostRow fields: any other read raises AttributeError
    own = _rows(4)
    other = _rows(4, cls="test.add", size="XS", repo="other")
    d = _quote(
        available={("bug.fix", "S"): 9, ("test.add", "XS"): 9}, own_rows=own, other_rows=other
    ).to_dict()
    assert {c["basis"]["tier"] for c in d["cells"]} == {q.TIER_REPO, q.TIER_DEPLOYMENT}
    assert set(vars(own[0])) == set(q.COST_ROW_FIELDS)


def _real(i: int, **kw: Any) -> Any:
    labels = kw.pop("labels", {})
    live = live_labels(f"{i:016x}", arm=kw.pop("arm", "S3"))
    live["labels"] = {**live["labels"], **labels}
    clean = kw.pop("clean", True)
    return posture_row(
        repo=REPO,
        task_id=f"{i:016x}",
        clean=clean,
        tests_unmodified=True,
        target_green=clean,
        no_new_failures=True,
        source_changed=True,
        capability_class="bug.fix",
        size="S",
        language="python",
        builder=BUILDER,
        model=MODEL,
        provider="anthropic",
        cost_usd=0.05 + 0.01 * (i % 3),
        latency_s=50.0 + i,
        tokens_in=1000,
        evidence_pack_hash="c" * 64 if clean else "",
        gold_clean=True,
        **{**live, **kw},
    )


def test_blind_to_outcomes() -> None:
    base = [_real(i, clean=(i % 3 != 0)) for i in range(9)]

    def body(rows: list[Any]) -> str:
        return json.dumps(_quote(own_rows=rows).to_dict(), sort_keys=True)

    want = body(base)
    assert _cell(_quote(own_rows=base))["basis"]["n_rows"] == 9
    flips = [
        [_real(i, clean=True) for i in range(9)],
        [_real(i, clean=False) for i in range(9)],
        [_real(i, clean=False, disqualified=True, dq_reason="tampered") for i in range(9)],
        [dataclasses.replace(r, oracle_strength=0.1, attempts=3) for r in base],
        [dataclasses.replace(r, run_id="9" * 32) for r in base],
        [_real(i, clean=(i % 3 != 0), labels={"checks": "fmt"}) for i in range(9)],
        [
            _real(i, clean=(i % 3 != 0), labels={"reading": "r-1", "campaign": "c"})
            for i in range(9)
        ],
    ]
    for rows in flips:
        assert body(rows) == want
    # the rung and the arm are filters, not outcomes: a later rung or another arm is not a
    # first mapping's row, so it leaves the basis (and names no arm in the body)
    for rows in (
        [dataclasses.replace(r, trial="r2") for r in base],
        [_real(i, clean=(i % 3 != 0), arm="S3+L") for i in range(9)],
    ):
        assert _cell(_quote(own_rows=rows))["basis"]["tier"] == q.TIER_UNKNOWN


def test_totals_add_priced_cells_only_and_name_unpriced() -> None:
    available = {("bug.fix", "S"): 10, ("test.add", "XS"): 10, ("docs.update", "S"): 10}
    own = _rows(4, cost=0.1, sd=0.0)  # bug.fix/S: $1.00 for 10
    quote = _quote(available=available, n_default=10, own_rows=own)
    d = quote.to_dict()
    t = d["totals"]
    assert t["cells"] == 3 and t["cells_priced"] == 1 and t["cells_unknown"] == 2
    assert t["tasks_to_run"] == 30 and t["tasks_priced"] == 10
    assert t["cost_usd_low"] == pytest.approx(1.0) and t["cost_usd_high"] == pytest.approx(1.0)
    assert t["cost_usd_expected"] == pytest.approx(1.0)
    assert t["unpriced"] == ["docs.update/S", "test.add/XS"]
    assert t["untimed"] == ["docs.update/S", "test.add/XS"]
    assert t["no_expected"] == []
    assert t["note"]
    # a declared band adds to low and high; it has no expected figure, so the expected total
    # is null rather than a sum over fewer cells (which sat below the low total)
    d = _quote(available=available, n_default=10, own_rows=own, declared=(0.1, 0.2)).to_dict()
    t = d["totals"]
    assert t["cells_priced"] == 3 and t["unpriced"] == []
    assert t["cost_usd_low"] == pytest.approx(3.0) and t["cost_usd_high"] == pytest.approx(5.0)
    assert t["cost_usd_expected"] is None
    assert t["no_expected"] == ["docs.update/S", "test.add/XS"]
    # a declared cell with nothing to run has an expected figure (0): the total stands
    d = _quote(
        available={("bug.fix", "S"): 10},
        selection={("bug.fix", "S"): 10, ("docs.update", "S"): 5},
        own_rows=own,
        declared=(0.1, 0.2),
    ).to_dict()
    assert d["totals"]["cost_usd_expected"] == pytest.approx(1.0)
    assert d["totals"]["no_expected"] == []


def test_fixed_statements_and_run_shape() -> None:
    d = _quote(own_rows=_rows(3)).to_dict()
    assert d["schema"] == q.QUOTE_SCHEMA
    assert d["run"] == {
        "kind": "replay",
        "mode": "sighted",
        "ladder": ["r1"],
        "attempts_per_task": 1,
        "look_rule": "look.v1",
        "first_look": 20,
    }
    assert d["claim"].startswith("[hypothesis]") and "not a provider invoice" in d["estimate_of"]
    assert "pool_seen" in d["seen_note"] and "one after another" in d["time_basis"]
    assert "[gap]" in d["seen_note"] and "r1" in d["basis_rows"] and "S3" in d["basis_rows"]
    assert q.default_n() == 20
