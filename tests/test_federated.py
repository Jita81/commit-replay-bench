"""crb.core.federated — the export boundary (zero I/O, zero network).

Ports the upstream test_federated cases onto crb types:

  (a) ALLOWLIST RATCHET — AbstractCell fields == ABSTRACT_ALLOWLIST and a cell built
      from rows stamped with real identifiers serialises to JSON containing NONE of them;
  (b) k-ANONYMITY — fewer than k DISTINCT orgs ⇒ suppressed; ≥ k ⇒ released;
  (c) pooled aggregation is numerically exact (counts sum; means are n-weighted);
  (d) CARDINAL — any contributor with false_q1 > 0 ⇒ trusted=False, false_q1 summed;
  (e) DIFFERENTIAL PRIVACY — seeded, reproducible, bounded; counts never noised;
  (f) OPT-IN — an opted-out org never contributes nor counts toward the cohort.

Navigation
----------
What it is:   The federated export boundary's test suite — abstract cells only, k-anonymity,
              exact pooling, the cardinal false-Q1 rule, optional differential privacy, opt-in.
What it does: Pins that ``AbstractCell``'s fields equal ``ABSTRACT_ALLOWLIST`` and that a cell
              built from rows stamped with real identifiers serialises to JSON containing none of
              them, that fewer than k DISTINCT organisations suppresses a cell, that pooled counts
              sum and means are n-weighted, that any contributor with false-Q1 > 0 makes the
              shared cell untrusted, that DP noise is seeded, bounded and never applied to counts,
              that an opted-out organisation never contributes, and that consumption of shared
              priors is deliberately not implemented.
How:          Synthetic ``GradeRow`` cells → ``to_abstract_cell`` / ``export_abstract`` /
              ``aggregate_abstract_cells``; zero I/O, zero network.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0007-abstract-cell-export-only.md
Works with:   src/crb/core/federated.py (under test), src/crb/core/ledger.py (``CELL_FIELDS``
              and ``cell_stats`` the abstraction is taken from), tests/test_server_routes_ledger.py
              (the abstract export served), docs/DATA-RETENTION.md (cross-organisation sharing)
Tested by:    tests/test_federated.py
Touch when:   a field is proposed for export (it must be added to the allowlist HERE with an ADR
              amendment — the allowlist test is the ratchet); k or ε defaults change.
"""

from __future__ import annotations

import json
import random

import pytest

from crb.core import federated as fed
from crb.core.ledger import CELL_FIELDS, GradeRow, all_cell_stats, cell_stats

PACK = "d" * 64


def _row(
    *,
    clean: bool = True,
    repo: str = "acme-referral-svc",
    task_id: str = "0123456789abcdef",
    cls: str = "frontend.component.add",
    size: str = "M",
    model: str = "gpt-oss-120b",
    cost: float = 0.0,
    latency: float = 0.0,
    provenance: str = "self-calibrate:acme",
) -> GradeRow:
    return GradeRow(
        repo=repo,
        task_id=task_id,
        clean=clean,
        tests_unmodified=True,
        target_green=clean,
        no_new_failures=True,
        source_changed=True,
        capability_class=cls,
        size=size,
        language="python",
        builder="agentic",
        model=model,
        provider="cerebras",
        run_id="run-acme-2026-07-03",
        actor="alice@acme.example",
        created="2026-07-03T00:00:00+00:00",
        cost_usd=cost,
        latency_s=latency,
        evidence_pack_hash=PACK if clean else "",
        provenance=provenance,
        labels={"story": "STORY-1234"},
    )


def _cell(n: int = 1, clean: int | None = None, **kw: object) -> fed.AbstractCell:
    k = n if clean is None else clean
    rows = [_row(clean=i < k, task_id=f"{i:016x}", **kw) for i in range(n)]  # type: ignore[arg-type]
    return fed.to_abstract_cell(cell_stats(rows))


# ---- (a) ALLOWLIST RATCHET ------------------------------------------------------


def test_abstract_cell_fields_equal_allowlist() -> None:
    assert set(fed.AbstractCell.__dataclass_fields__) == set(fed.ABSTRACT_ALLOWLIST)
    cell = _cell()
    assert list(cell.to_dict()) == list(fed.ABSTRACT_ALLOWLIST)
    assert set(CELL_FIELDS) < set(fed.ABSTRACT_ALLOWLIST)  # the key travels; nothing else does
    for banned in (
        "repo",
        "task_id",
        "created",
        "run_id",
        "actor",
        "provenance",
        "labels",
        "trial",
    ):
        assert banned not in fed.ABSTRACT_ALLOWLIST


def test_identifiers_absent_from_abstract_and_shared_output() -> None:
    secrets = [
        "acme-referral-svc",
        "self-calibrate:acme",
        "STORY-1234",
        "acme",
        "alice",
        "run-",
        "2026-07",
        "0123456789abcdef",
    ]
    cell = _cell()
    cell_json = json.dumps(cell.to_dict())
    for needle in secrets:
        assert needle not in cell_json, f"identifier {needle!r} leaked into AbstractCell"
    shared = fed.aggregate_abstract_cells(
        {f"org-hash-{i}": (cell,) for i in range(3)}, min_cohort_k=3
    )
    assert len(shared) == 1
    shared_json = json.dumps(shared[0].to_dict())
    for needle in secrets:
        assert needle not in shared_json, f"identifier {needle!r} leaked into SharedCell"
    assert "org-hash-0" not in shared_json  # opaque org hashes are never emitted either


def test_export_abstract_is_allowlisted_and_sorted() -> None:
    rows = [_row(model="z"), _row(model="a", task_id="ffffffffffffffff")]
    out = fed.export_abstract(rows)
    assert [d["model"] for d in out] == ["a", "z"]
    assert all(set(d) == set(fed.ABSTRACT_ALLOWLIST) for d in out)
    assert len(out) == len(all_cell_stats(rows))
    assert "acme" not in json.dumps(out)


def test_from_dict_refuses_non_allowlisted_fields() -> None:
    d = _cell().to_dict()
    assert fed.AbstractCell.from_dict(d) == _cell()
    with pytest.raises(ValueError, match="non-allowlisted"):
        fed.AbstractCell.from_dict({**d, "repo": "acme"})


def test_unmeasured_axes_become_none_not_zero() -> None:
    c = _cell()
    assert c.cost_usd_mean is None and c.latency_s_mean is None
    c2 = _cell(cost=0.1, latency=2.0)
    assert c2.cost_usd_mean == 0.1 and c2.latency_s_mean == 2.0


def test_abstract_cell_key_is_the_cell_key() -> None:
    c = _cell()
    assert c.cell.to_tuple() == c.key
    assert c.key == (
        "replay",
        "frontend.component.add",
        "M",
        "python",
        "agentic",
        "gpt-oss-120b",
        "cerebras",
    )


# ---- (b) k-ANONYMITY ------------------------------------------------------------


def test_k_anonymity_suppresses_below_k_keeps_at_k() -> None:
    cell = _cell()
    assert fed.aggregate_abstract_cells({f"t{i}": (cell,) for i in range(2)}, min_cohort_k=3) == []
    kept = fed.aggregate_abstract_cells({f"t{i}": (cell,) for i in range(3)}, min_cohort_k=3)
    assert len(kept) == 1 and kept[0].contributor_count == 3


def test_k_anonymity_counts_distinct_orgs_not_rows() -> None:
    cell = _cell()
    contribs = [
        fed.OrgContribution(org_hash="a", cells=(cell, cell, cell)),
        fed.OrgContribution(org_hash="b", cells=(cell, cell, cell)),
    ]
    assert fed.aggregate_abstract_cells(contribs, min_cohort_k=3) == []


def test_default_cohort_k_is_three_and_validated() -> None:
    assert fed.DEFAULT_MIN_COHORT_K == 3
    with pytest.raises(ValueError, match="min_cohort_k"):
        fed.aggregate_abstract_cells({}, min_cohort_k=0)


# ---- (c) pooled aggregation -----------------------------------------------------


def test_pooled_aggregation_is_exact() -> None:
    a = _cell(1, cost=0.10, latency=2.0)  # n=1 clean=1
    b = _cell(3, clean=2, cost=0.20, latency=4.0)  # n=3 clean=2
    contribs = {"ta": (a,), "tb": (b,), "tc": (a,), "td": (b,), "te": (a,)}
    sc = fed.aggregate_abstract_cells(contribs, min_cohort_k=5)[0]
    assert sc.contributor_count == 5
    assert sc.n == 3 * 1 + 2 * 3 == 9
    assert sc.clean == 3 * 1 + 2 * 2 == 7
    assert sc.point == pytest.approx(7 / 9)
    # n-weighted cost: (3·0.10·1 + 2·0.20·3)/9 ; latency: (3·2·1 + 2·4·3)/9
    assert sc.cost_usd_mean == pytest.approx(1.5 / 9)
    assert sc.latency_s_mean == pytest.approx(30.0 / 9)
    # the interval is recomputed from the pooled counts (its n travels with it)
    assert sc.ci_low < sc.point < sc.ci_high
    assert sc.trusted and sc.false_q1 == 0 and sc.dp_epsilon is None
    assert sc.key == a.key


def test_unmeasured_axis_stays_none_and_does_not_drag_the_mean() -> None:
    costed = _cell(2, cost=0.5)
    uncosted = _cell(2)
    sc = fed.aggregate_abstract_cells(
        {"a": (costed,), "b": (uncosted,), "c": (costed,)}, min_cohort_k=3
    )[0]
    assert sc.cost_usd_mean == pytest.approx(0.5)  # not averaged with a fake 0
    assert sc.latency_s_mean is None


def test_distinct_keys_aggregate_separately() -> None:
    a, b = _cell(model="gpt-oss-120b"), _cell(model="zai-glm-4.7")
    shared = fed.aggregate_abstract_cells({f"t{i}": (a, b) for i in range(3)}, min_cohort_k=3)
    assert [s.model for s in shared] == ["gpt-oss-120b", "zai-glm-4.7"]


# ---- (d) CARDINAL false-Q1 ------------------------------------------------------


def test_any_contributor_false_q1_makes_shared_cell_untrusted() -> None:
    clean = _cell(4)
    dirty = fed.AbstractCell(**{**clean.to_dict(), "false_q1": 2})
    sc = fed.aggregate_abstract_cells(
        {"t0": (clean,), "t1": (clean,), "t2": (dirty,)}, min_cohort_k=3
    )[0]
    assert sc.false_q1 == 2  # summed, not vanished
    assert sc.trusted is False
    ok = fed.aggregate_abstract_cells({f"t{i}": (clean,) for i in range(3)}, min_cohort_k=3)[0]
    assert ok.false_q1 == 0 and ok.trusted is True


def test_abstract_cell_rejects_impossible_counts() -> None:
    d = _cell(2).to_dict()
    with pytest.raises(ValueError, match="exceed"):
        fed.AbstractCell(**{**d, "clean": 3})
    with pytest.raises(ValueError, match="negative"):
        fed.AbstractCell(**{**d, "false_q1": -1})


# ---- (e) DIFFERENTIAL PRIVACY ---------------------------------------------------


def test_dp_none_is_exact() -> None:
    cell = _cell(5, clean=4, cost=0.5, latency=3.0)
    sc = fed.aggregate_abstract_cells({f"t{i}": (cell,) for i in range(3)}, min_cohort_k=3)[0]
    assert sc.point == pytest.approx(0.8) and sc.clean == 12 and sc.n == 15
    assert sc.cost_usd_mean == 0.5 and sc.latency_s_mean == 3.0


def test_dp_perturbs_within_bound_reproducibly_and_never_noises_counts() -> None:
    cell = _cell(5, clean=4, cost=0.5, latency=3.0)
    contribs = {f"t{i}": (cell,) for i in range(3)}
    sc1 = fed.aggregate_abstract_cells(contribs, min_cohort_k=3, dp_epsilon=1.0, seed=42)[0]
    sc2 = fed.aggregate_abstract_cells(contribs, min_cohort_k=3, dp_epsilon=1.0, seed=42)[0]
    assert (sc1.point, sc1.cost_usd_mean, sc1.latency_s_mean) == (
        sc2.point,
        sc2.cost_usd_mean,
        sc2.latency_s_mean,
    )
    assert sc1.dp_epsilon == 1.0
    assert sc1.point != pytest.approx(0.8)  # noise actually applied
    scale = fed.DP_SENSITIVITY / 1.0
    assert abs(sc1.cost_usd_mean - 0.5) <= 40 * scale  # type: ignore[operator]
    assert abs(sc1.latency_s_mean - 3.0) <= 40 * scale  # type: ignore[operator]
    assert 0.0 <= sc1.point <= 1.0 and 0 <= sc1.clean <= sc1.n
    # the released clean count is derived from the noised point (no exact read-back)
    assert sc1.clean == round(sc1.point * sc1.n)
    assert sc1.ci_low <= sc1.point <= sc1.ci_high
    # a passed-in rng is honoured; a different seed ⇒ different noise
    sc3 = fed.aggregate_abstract_cells(
        contribs, min_cohort_k=3, dp_epsilon=1.0, rng=random.Random(7)
    )[0]
    assert sc3.point != sc1.point
    # counts that gate trust and cohort are never noised
    assert sc1.false_q1 == 0 and sc1.contributor_count == 3 and sc1.n == 15


def test_dp_epsilon_must_be_positive() -> None:
    cell = _cell()
    with pytest.raises(ValueError, match="dp_epsilon"):
        fed.aggregate_abstract_cells(
            {f"t{i}": (cell,) for i in range(3)}, min_cohort_k=3, dp_epsilon=0.0
        )


# ---- (f) OPT-IN ----------------------------------------------------------------


def test_opted_out_org_never_contributes() -> None:
    clean = _cell()
    dirty = fed.AbstractCell(**{**clean.to_dict(), "false_q1": 3})
    contribs = [fed.OrgContribution(org_hash=f"in-{i}", cells=(clean,)) for i in range(3)]
    contribs.append(fed.OrgContribution(org_hash="out", cells=(dirty,), opted_in=False))
    sc = fed.aggregate_abstract_cells(contribs, min_cohort_k=3)[0]
    assert sc.trusted is True and sc.false_q1 == 0 and sc.contributor_count == 3


def test_opt_out_can_starve_the_cohort() -> None:
    cell = _cell()
    contribs = [fed.OrgContribution(org_hash=f"in-{i}", cells=(cell,)) for i in range(2)]
    contribs += [
        fed.OrgContribution(org_hash=f"out-{i}", cells=(cell,), opted_in=False) for i in range(10)
    ]
    assert fed.aggregate_abstract_cells(contribs, min_cohort_k=3) == []


def test_org_contribution_requires_hash() -> None:
    with pytest.raises(ValueError, match="org_hash"):
        fed.OrgContribution(org_hash="", cells=())


# ---- designed boundary ------------------------------------------------------------


def test_consumption_of_shared_priors_is_not_implemented() -> None:
    """The boundary is built; consumption is deliberately absent (documented)."""
    assert "NOT IMPLEMENTED" in (fed.__doc__ or "")
    assert not any(
        name.startswith(("consume", "import_shared", "apply_prior")) for name in dir(fed)
    )
