"""crb.core.capability — the capability map, config pick, change profile and TAC.

Ports the upstream cases (test_benchmark_capability / test_automation_framework /
test_benchmark_ledger pareto+best_config) onto crb types. Every verdict here is
``crb.core.routing.route`` applied unchanged; the tests pin the honest states:

* honest-empty — a cell with no rows is NOT_YET_MEASURED, never a fabricated row;
* the ONE rule — deliver needs n≥10 ∧ point≥0.90 ∧ Wilson-lower≥0.80 ∧ false-Q1=0;
* σ is advisory (a 0.95 cell with a wide σ still routes to deliver);
* cheapest+fastest pick — Pareto over PASSING configs only; false-Q1 excluded first;
* TAC is volume-weighted over the repo's real change profile;
* the REAL census ledger: false-Q1 = 0 everywhere, no deliver claim under n=10.

Navigation
----------
What it is:   The capability map's test suite — honest cells, config pick, change profile and
              the total automation coverage (TAC).
What it does: Pins that an unmeasured cell is ``not_yet_measured`` (never a fabricated row), that
              every verdict is ``crb.core.routing.route`` applied unchanged, that σ is advisory,
              that disqualified and gold-dirty rows leave the denominator, that legacy belt sets
              are a separate apparatus, the cheapest-then-fastest config pick over PASSING configs
              only, that TAC is volume-weighted over the repository's real change profile, the
              failure split next to the point, and — on the real census ledger when present —
              false-Q1 = 0 everywhere with no deliver claim under n = 10.
How:          Synthetic ``GradeRow`` lists → ``build_capability_map`` and friends; one case
              histograms a tiny git repository; the census case imports ``data/`` inline.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0003-one-routing-rule.md, docs/adr/0001-four-belts-and-false-q1-at-write.md
Works with:   src/crb/core/capability.py (under test), src/crb/core/routing.py (the verdicts),
              src/crb/core/ledger.py (``CELL_FIELDS`` — the projection basis), src/crb/core/spec.py
              (``classify_commit`` / ``size_tier`` for the profile), tests/test_forecast.py (the
              forecast built on the map), tests/test_server_routes_capability.py (the map served)
Tested by:    tests/test_capability.py
Touch when:   a cell field is added (``CELL_FIELDS`` and every projection here); the config pick
              gains a criterion; the profile classifier changes.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from crb.core import capability as cap
from crb.core.git import GitRepo
from crb.core.ledger import CELL_FIELDS, CellKey, GradeRow
from crb.core.legacy import import_census
from crb.core.reading import register
from crb.core.routing import (
    ROUTE_CALIBRATE,
    ROUTE_DELIVER,
    ROUTE_DO_NOT_SHIP,
    ROUTE_GRANULARIZE,
    ROUTE_HUMAN,
    ControlsVerdict,
)
from crb.core.spec import Language, RepoConfig, classify_commit, size_tier
from crb.core.taxonomy import GLOBAL_CLASS_SET
from fixtures.posture import posture_row

PACK = "a" * 64
#: routing.v2 (ADR-0025 as ADR-0026 amends it): a cell delivers only on its standard arm, read
#: by a registered reading in the sealed posture with a measured oracle and controls at 2.4.
#: The rows here are that world by default — sealed 2.4 rows on one certifying arm — and
#: ``build`` / ``best`` / ``candidates`` / ``tac`` hand the map a reading per full cell, an
#: oracle score per task and a passing controls report at 2.4, so the map's own mechanics
#: (projections, picks, coverage, tiers) are what these tests exercise.
LIVE = "2.4"
AUTHOR = "claude-opus-5"
ARM = f"S1@{AUTHOR}"
SEALED = "docker/copy/sealed"
REGISTERED_AT = "2026-09-27T10:00:00+00:00"
GRADED_AT = "2026-09-27T11:00:00+00:00"
PASSED = ControlsVerdict(
    passed=True, constructible=56, total=56, escapes=0, run_id="c" * 32, apparatus_version=LIVE
)


def _row(
    *,
    clean: bool = True,
    cls: str = "bug.fix",
    size: str = "S",
    language: str = "python",
    builder: str = "agentic",
    model: str = "m1",
    provider: str = "p1",
    process_step: str = "replay",
    repo: str = "r",
    task_id: str = "0123456789abcdef",
    cost: float = 0.0,
    latency: float = 0.0,
    oracle_strength: float | None = None,
    disqualified: bool = False,
    gold_clean: bool | None = True,
    belt_set: str = "",
    apparatus_version: str = LIVE,
    provenance: str = "measured",
    labels: dict[str, str] | None = None,
) -> GradeRow:
    belts = (True, True, True, True) if clean else (True, False, True, True)
    belt_set = belt_set or ("v5" if apparatus_version == LIVE else "v4")
    if belt_set == "v3-legacy":
        belts = (*belts[:3], None)
    live = apparatus_version == LIVE and provenance == "measured"
    extra: dict[str, object] = (
        {
            "created": GRADED_AT,
            "trial": "r1",
            "labels": {
                "posture_class": SEALED,
                "builder_executor": "docker",
                "context_arm": ARM,
                "taxonomy": GLOBAL_CLASS_SET,
                "change_id": f"change-{task_id}",
                **(labels or {}),
            },
        }
        if live
        else ({"labels": dict(labels)} if labels else {})
    )
    return posture_row(
        repo=repo,
        task_id=task_id,
        clean=clean and not disqualified,
        tests_unmodified=belts[0],
        target_green=belts[1],
        no_new_failures=belts[2],
        source_changed=belts[3],
        capability_class=cls,
        size=size,
        language=language,
        builder=builder,
        model=model,
        provider=provider,
        process_step=process_step,
        cost_usd=cost,
        latency_s=latency,
        oracle_strength=oracle_strength,
        disqualified=disqualified,
        dq_reason="dq" if disqualified else "",
        gold_clean=gold_clean,
        evidence_pack_hash=PACK if clean else "",
        belt_set=belt_set,
        apparatus_version=apparatus_version,
        provenance=provenance,
        **extra,
    )


def _book(rows: list[GradeRow]) -> cap.ReadingBook:
    """One reading per full cell of the live rows, registered before any of them was graded,
    over the cell's commits: the arm ``ARM`` alone in its hierarchy (it certifies)."""
    groups: dict[tuple[str, CellKey], list[str]] = {}
    for r in rows:
        if r.context_arm and r.apparatus_version == LIVE:
            groups.setdefault((r.repo, r.cell), []).append(r.task_id)
    readings = [
        register(
            repo=repo,
            cell=cell.to_dict(),
            hierarchy=(ARM,),
            pool=list(dict.fromkeys(ids)),
            apparatus=LIVE,
            taxonomy=GLOBAL_CLASS_SET,
            posture_class=SEALED,
            checks_arm="off",
            actor="op",
            author_model=AUTHOR,
            now=REGISTERED_AT,
        )
        for (repo, cell), ids in groups.items()
    ]
    return cap.ReadingBook.evaluate(readings, rows)


def _world(rows: list[GradeRow], oracle: float | None, kw: dict[str, object]) -> dict[str, object]:
    """The readings, the per-task oracle and the controls a map of ``rows`` is routed under."""
    world: dict[str, object] = {
        "readings": _book(rows),
        "oracle_by_task": {} if oracle is None else {r.task_id: oracle for r in rows},
        "controls": PASSED,
    }
    world.update(kw)
    return world


def build(rows: list[GradeRow], *, oracle: float | None = 0.9, **kw: object) -> cap.CapabilityMap:
    rs = list(rows)
    return cap.build_capability_map(rs, **_world(rs, oracle, kw))  # type: ignore[arg-type]


def best(
    rows: list[GradeRow], *, oracle: float | None = 0.9, **kw: object
) -> cap.ConfigPick | None:
    rs = list(rows)
    return cap.best_config(rs, **_world(rs, oracle, kw))  # type: ignore[arg-type]


def candidates(
    rows: list[GradeRow], *, oracle: float | None = 0.9, **kw: object
) -> list[cap.CapabilityCell]:
    rs = list(rows)
    return cap.config_candidates(rs, **_world(rs, oracle, kw))  # type: ignore[arg-type]


def tac(profile: cap.RepoChangeProfile, rows: list[GradeRow], **kw: object) -> cap.CoverageSummary:
    rs = list(rows)
    world = _world(rs, 0.9, {})
    del world["controls"]
    return cap.trusted_autonomy_coverage(profile, rs, **{**world, **kw})  # type: ignore[arg-type]


def _rows(n: int, clean: int, **kw: object) -> list[GradeRow]:
    return [_row(clean=i < clean, task_id=f"{i:016x}", **kw) for i in range(n)]  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# projections + honest-empty
# ---------------------------------------------------------------------------


def test_projected_key_wildcards_non_projected_fields() -> None:
    k = _row().cell
    p = cap.projected_key(k, cap.PROJECTION_CLASS_SIZE)
    assert p.capability_class == "bug.fix" and p.size == "S"
    assert (p.language, p.builder, p.model, p.provider, p.process_step) == ("*",) * 5
    assert cap.projected_key(k, cap.PROJECTION_CELL) == k


def test_projection_must_be_cell_fields() -> None:
    with pytest.raises(ValueError, match="unknown cell-key field"):
        build([_row()], projection=("repo",))
    with pytest.raises(ValueError, match="at least one"):
        build([_row()], projection=())


def test_empty_map_and_absent_cell_are_honest_empty() -> None:
    m = build([])
    assert m.cells == () and m.rows == 0 and m.false_q1_total == 0
    c = m.get(capability_class="bug.fix", size="S")
    assert c.route == cap.NOT_YET_MEASURED
    assert c.stats is None and c.decision is None and c.verification_tier is None
    assert c.n == 0 and c.point is None and not c.measured
    assert c.to_dict()["stats"] is None
    assert "no rows" in cap.render_markdown(m)


def test_get_rejects_fields_outside_projection() -> None:
    m = build([_row()])
    with pytest.raises(ValueError, match="not in projection"):
        m.get(model="m1")


def test_capability_views_cover_all_named_projections() -> None:
    rows = _rows(12, 12) + _rows(3, 3, language="go", model="m2")
    views = cap.capability_views(rows)
    assert set(views) == set(cap.PROJECTIONS)
    assert len(views["class_size"].cells) == 1  # both languages collapse
    assert len(views["class_size_language"].cells) == 2
    assert len(views["class_size_model"].cells) == 2
    assert len(views["cell"].cells) == 2
    assert views["class_size"].cells[0].n == 15


# ---------------------------------------------------------------------------
# the ONE rule, unchanged
# ---------------------------------------------------------------------------


def test_thin_cell_routes_to_calibrate_not_deliver() -> None:
    m = build(_rows(5, 5))  # 100%, but the pool ends before the look at 20
    c = m.cells[0]
    assert c.route == ROUTE_CALIBRATE
    assert c.decision is not None and c.decision.reason_code == "undecided"
    assert c.verification_tier == cap.TIER_AUTOMATED_PASS


def test_deliver_when_rule_is_met() -> None:
    m = build(_rows(40, 39))
    c = m.cells[0]
    assert c.route == ROUTE_DELIVER
    assert c.decision is not None and c.decision.policy_version == m.policy.version
    assert c.decision.standard == ARM and c.decision.counted in (20, 30, 40)


def test_below_point_routes_to_human() -> None:
    # 30 of 40: the third miss comes before any look delivers — insufficient, never read again
    m = build(_rows(40, 30))
    assert m.cells[0].route == ROUTE_HUMAN and m.cells[0].reason_code == "insufficient"


def test_a_pool_short_of_the_first_look_routes_calibrate_even_at_point() -> None:
    # 10/11 = 0.909 point, but eleven commits never reach the look at 20 → undecided.
    m = build(_rows(11, 10))
    c = m.cells[0]
    assert c.point is not None and c.point >= 0.90
    assert c.route == ROUTE_CALIBRATE
    assert c.decision is not None and c.decision.reason_code == "undecided"


def test_sigma_is_advisory_not_a_gate() -> None:
    # 38/40 = 0.95 with Bernoulli σ ≈ 0.22 > 0.10 — the SPC gate would refuse; we deliver.
    m = build(_rows(40, 38))
    c = m.cells[0]
    assert c.sigma is not None and c.sigma > 0.10
    assert c.route == ROUTE_DELIVER


def test_xl_routes_to_granularize() -> None:
    m = build(_rows(40, 40, size="XL"))
    assert m.cells[0].route == ROUTE_GRANULARIZE


def test_weak_oracle_routes_to_human_even_when_green() -> None:
    m = build(_rows(40, 40), oracle=0.5)
    c = m.cells[0]
    assert c.route == ROUTE_HUMAN
    assert c.decision is not None and "oracle strength" in c.decision.reason
    # the rows' own oracle_strength column never routes (ADR-0025 item 3)
    assert build(_rows(40, 40, oracle_strength=0.1)).cells[0].route == ROUTE_DELIVER


def test_false_q1_is_structurally_impossible_and_untrusted_if_forced() -> None:
    # The ledger refuses a false-Q1 row at write. Simulate one bypassing __post_init__
    # to prove the map's read-time re-check still refuses to trust it.
    bad = _row(clean=True)
    object.__setattr__(bad, "target_green", False)
    rows = [*_rows(40, 40), bad]
    m = build(rows)
    c = m.cells[0]
    assert m.false_q1_total == 1
    assert c.false_q1 == 1
    assert c.route == ROUTE_DO_NOT_SHIP
    assert c.verification_tier == cap.TIER_UNTRUSTED
    with pytest.raises(ValueError, match="untrusted"):
        c.with_tier(cap.TIER_HUMAN_VERIFIED)


def test_disqualified_rows_do_not_count_in_denominator() -> None:
    rows = [*_rows(12, 12), _row(disqualified=True, task_id="ffffffffffffffff")]
    c = build(rows).cells[0]
    assert c.rows == 13 and c.n == 12
    assert c.stats is not None and c.stats.disqualified == 1


def test_gold_dirty_rows_do_not_count_in_denominator() -> None:
    # a 2.4 replay row must be gold-checked clean (ADR-0025 item 6): the rule is shown at 2.0
    old = {"apparatus_version": "2.0"}
    rows = [
        *_rows(12, 12, **old),
        _row(clean=False, gold_clean=False, task_id="ffffffffffffffff", **old),  # type: ignore[arg-type]
    ]
    c = build(rows).cells[0]
    assert c.n == 12 and c.point == 1.0


def test_legacy_belt_set_is_a_separate_apparatus_and_never_pooled() -> None:
    old = _rows(6, 6, apparatus_version="2.0")
    legacy = _rows(
        6, 6, belt_set="v3-legacy", apparatus_version="1.0-census", provenance="imported:census"
    )
    # ADR-0025 item 1: a reading has one apparatus — two are refused, each is its own map
    with pytest.raises(ValueError, match="apparatus version"):
        build(old + legacy)
    assert build(old).cells[0].belt_sets == ("v4",)
    m = build(legacy)
    assert m.apparatus_versions == ("1.0-census",) and m.cells[0].belt_sets == ("v3-legacy",)


def test_repos_counts_distinct_contributing_repos() -> None:
    rows = _rows(6, 6, repo="a") + _rows(6, 6, repo="b")
    assert build(rows).cells[0].repos == 2


def test_cell_invariants_enforced_at_construction() -> None:
    k = cap.projected_key(_row().cell, cap.PROJECTION_CLASS_SIZE)
    empty = cap.empty_cell(k, cap.PROJECTION_CLASS_SIZE)
    with pytest.raises(ValueError, match="unmeasured cell cannot carry"):
        cap.CapabilityCell(**{**empty.__dict__, "verification_tier": cap.TIER_AUTOMATED_PASS})
    with pytest.raises(ValueError, match="both present or both absent"):
        cap.CapabilityCell(**{**empty.__dict__, "decision": cap.route(cap.cell_stats(_rows(1, 1)))})
    with pytest.raises(ValueError, match="no tier to change"):
        empty.with_tier(cap.TIER_HUMAN_VERIFIED)


def test_render_markdown_is_a_table_with_n_and_method() -> None:
    m = build(_rows(40, 39) + _rows(3, 1, cls="docs.update"))
    out = cap.render_markdown(m)
    assert out.splitlines()[4].startswith("| capability_class | size | n | clean | point | 95% CI")
    assert "`bug.fix`" in out and "`docs.update`" in out
    assert "**deliver**" in out and "**calibrate**" in out
    assert "policy=routing.v2" in out and "apparatus=2.4" in out
    assert m.render_markdown() == out


def test_map_to_dict_carries_counts_by_route() -> None:
    m = build(_rows(40, 39) + _rows(3, 1, cls="docs.update"))
    d = m.to_dict()
    assert d["cells_by_route"][ROUTE_DELIVER] == 1
    assert d["cells_by_route"][ROUTE_CALIBRATE] == 1
    assert d["policy"]["version"] == "routing.v2"
    assert d["cells"][0]["stats"]["n"] == 40


# ---------------------------------------------------------------------------
# cheapest + fastest passing config (pareto + best_config semantics)
# ---------------------------------------------------------------------------


def _config(
    model: str, *, cost: float, latency: float, clean: int = 38, n: int = 40, **kw: object
) -> list[GradeRow]:
    return _rows(n, clean, model=model, cost=cost, latency=latency, **kw)


def test_best_config_is_cheapest_then_fastest() -> None:
    rows = _config("cheap-slow", cost=0.01, latency=9.0, provider="cerebras") + _config(
        "dear-fast", cost=0.02, latency=1.0, provider="anthropic"
    )
    pick = best(rows, capability_class="bug.fix", size="S")
    assert pick is not None
    assert pick.cell.key.model == "cheap-slow"
    assert pick.selection == cap.SELECTION_COST_THEN_LATENCY
    assert pick.cost_usd == 0.01 and pick.latency_s == 9.0
    assert pick.label == "agentic/cheap-slow@cerebras"
    assert pick.candidates == 2
    # both are non-dominated (one cheaper, one faster) → both on the frontier, cheapest first
    assert pick.frontier == (
        "replay|bug.fix|S|agentic|cheap-slow|cerebras",
        "replay|bug.fix|S|agentic|dear-fast|anthropic",
    )
    assert pick.to_dict()["config"] == "agentic/cheap-slow@cerebras"


def test_cost_tie_breaks_to_fastest() -> None:
    rows = _config("tie-slow", cost=0.01, latency=8.0) + _config("tie-fast", cost=0.01, latency=2.0)
    pick = best(rows, capability_class="bug.fix", size="S")
    assert pick is not None and pick.cell.key.model == "tie-fast"
    assert pick.latency_s == 2.0


def test_pareto_frontier_drops_dominated_and_untrusted() -> None:
    rows = (
        _config("cheap-fast", cost=0.01, latency=1.0)
        + _config("dear-slow", cost=0.02, latency=2.0)  # dominated
        + _config("cheapest-slow", cost=0.005, latency=5.0)  # non-dominated
    )
    cells = candidates(rows, capability_class="bug.fix", size="S")
    frontier = {c.key.model for c in cap.pareto_frontier(cells)}
    assert frontier == {"cheap-fast", "cheapest-slow"}
    # an UNTRUSTED config never reaches the frontier even if it would dominate
    bad = _row(model="dirty", cost=0.001, latency=0.1)
    object.__setattr__(bad, "target_green", False)
    dirty = [*_config("dirty", cost=0.001, latency=0.1), bad]
    cells2 = candidates(rows + dirty, capability_class="bug.fix", size="S")
    assert "dirty" not in {c.key.model for c in cells2}
    assert "dirty" not in {c.key.model for c in cap.pareto_frontier(cells2)}


def test_only_passing_configs_are_candidates() -> None:
    rows = (
        _config("passing", cost=0.05, latency=5.0)
        + _config("thin", cost=0.001, latency=0.1, n=5, clean=5)  # calibrate: n<10
        + _config("weak", cost=0.001, latency=0.1, clean=30)  # calibrate: 75%
    )
    cands = {c.key.model for c in candidates(rows, capability_class="bug.fix", size="S")}
    assert cands == {"passing"}
    pick = best(rows, capability_class="bug.fix", size="S")
    assert pick is not None and pick.cell.key.model == "passing"


def test_no_passing_config_returns_none_not_best_effort() -> None:
    rows = _config("weak", cost=0.001, latency=0.1, clean=30)
    assert best(rows, capability_class="bug.fix", size="S") is None
    assert best([], capability_class="bug.fix", size="S") is None


def test_uncosted_configs_fall_back_to_point_selection() -> None:
    # rows whose builder reported no price: the cost is unknown, not $0 (F35)
    imported = {"labels": {"cost_known": "false"}}
    rows = _config("a", cost=0.0, latency=0.0, clean=38, **imported) + _config(
        "b", cost=0.0, latency=0.0, clean=40, **imported
    )
    pick = best(rows, capability_class="bug.fix", size="S")
    assert pick is not None
    assert pick.selection == cap.SELECTION_POINT
    assert pick.cell.key.model == "b"
    assert pick.cost_usd is None and pick.latency_s is None and pick.frontier == ()
    # a builder that REPORTED $0 (a fixture, a subscription) is a known $0, never unknown
    known_zero = best(
        _config("z", cost=0.0, latency=0.0, clean=40), capability_class="bug.fix", size="S"
    )
    assert known_zero is not None and known_zero.cost_usd == 0.0
    assert known_zero.latency_s is None  # 0 s is "not recorded", never instant
    # a costed config is preferred on the frontier when one exists
    pick2 = best(rows + _config("c", cost=0.5, latency=9.0), capability_class="bug.fix", size="S")
    assert pick2 is not None and pick2.cell.key.model == "c"
    assert pick2.selection == cap.SELECTION_COST_THEN_LATENCY


def test_best_config_filters_language_and_rejects_unknown_selection() -> None:
    rows = _config("py", cost=0.01, latency=1.0, language="python") + _config(
        "go", cost=0.001, latency=0.1, language="go"
    )
    pick = best(rows, capability_class="bug.fix", size="S", language="python")
    assert pick is not None and pick.cell.key.model == "py"
    with pytest.raises(ValueError, match="selection must be"):
        best(rows, capability_class="bug.fix", size="S", selection="latency_only")


def test_point_selection_prefers_evidence_over_a_thin_perfect_score() -> None:
    # 20/20 delivers at the first look (Wilson lower 0.839) and so does 39/40 (0.871): with no
    # cost recorded the pick is by evidence, and the better-measured config wins.
    rows = _rows(20, 20, model="thin-perfect") + _rows(40, 39, model="well-measured")
    pick = best(rows, capability_class="bug.fix", size="S")
    assert pick is not None and pick.selection == cap.SELECTION_POINT
    assert pick.cell.key.model == "well-measured"


def test_config_pools_languages_unless_pinned() -> None:
    # One model: 28/28 on go, 20/40 on python. As an unpinned config it is judged on
    # ALL its evidence (48/68 → calibrate), never on its best-looking slice.
    rows = _rows(28, 28, language="go", cost=0.01, latency=1.0) + _rows(
        40, 20, language="python", cost=0.01, latency=1.0
    )
    assert cap.config_projection(size="S", language=None) == (
        "process_step",
        "capability_class",
        "size",
        "builder",
        "model",
        "provider",
    )
    assert best(rows, capability_class="bug.fix", size="S") is None
    go = best(rows, capability_class="bug.fix", size="S", language="go")
    assert go is not None and go.cell.n == 28 and go.cell.key.language == "go"
    assert best(rows, capability_class="bug.fix", size="S", language="python") is None


def test_config_pick_must_route_to_deliver() -> None:
    thin = build(_rows(3, 3), projection=cap.PROJECTION_CELL).cells[0]
    with pytest.raises(ValueError, match="routes to deliver"):
        cap.ConfigPick(cell=thin, selection=cap.SELECTION_POINT, frontier=(), candidates=1)


# ---------------------------------------------------------------------------
# repo change profile (real git)
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@x",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@x",
    }
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)


def _commit(repo: Path, files: dict[str, str], msg: str) -> None:
    for rel, body in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)


def test_profile_repo_histograms_class_by_size(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    _commit(
        repo, {"src/pkg/__init__.py": "", "README.md": "x\n"}, "root"
    )  # root: skipped (no parent)
    _commit(repo, {"src/pkg/core.py": "def f():\n    return 1\n"}, "bug.fix XS")  # 2 lines → XS
    _commit(
        repo,
        {"src/pkg/api/routes.py": "\n".join(f"x{i} = {i}" for i in range(20)) + "\n"},
        "route S",
    )
    _commit(repo, {"docs/guide.md": "hello\n"}, "docs only: no src → skipped")
    _commit(repo, {"tests/test_core.py": "def test_f():\n    assert True\n"}, "test only → skipped")
    _commit(repo, {"src/pkg/core.py": "def f():\n    return 2\n"}, "bug.fix XS again")

    config = RepoConfig(name="r", language=Language.PYTHON, src_prefix="src/", test_prefix="tests/")
    profile = cap.profile_repo(GitRepo(repo), config, log_n=50)
    assert profile.repo == "r"
    assert profile.examined == 6
    assert profile.cells == {("bug.fix", "XS"): 2, ("backend.route.add", "S"): 1}
    assert profile.n_commits == 3 and profile.skipped == 3
    assert profile.class_totals() == {"bug.fix": 2, "backend.route.add": 1}
    assert profile.size_totals() == {"XS": 2, "S": 1}
    assert profile.ranked()[0] == (("bug.fix", "XS"), 2)
    # JSON round trip
    again = cap.RepoChangeProfile.from_dict(json.loads(json.dumps(profile.to_dict())))
    assert again == profile
    assert "`bug.fix`" in cap.render_profile(profile)
    # the same class/size the miner would assign to these commits
    assert classify_commit(["src/pkg/api/routes.py"]) == "backend.route.add"
    assert size_tier(20) == "S"


def test_profile_rejects_inconsistent_counts() -> None:
    with pytest.raises(ValueError, match="n_commits"):
        cap.RepoChangeProfile(
            repo="r", n_commits=5, examined=5, skipped=0, cells={("bug.fix", "S"): 2}
        )


# ---------------------------------------------------------------------------
# Trusted Autonomy Coverage
# ---------------------------------------------------------------------------


def _profile(cells: dict[tuple[str, str], int]) -> cap.RepoChangeProfile:
    n = sum(cells.values())
    return cap.RepoChangeProfile(repo="fixture", n_commits=n, examined=n, skipped=0, cells=cells)


def test_tac_weights_by_change_volume_not_cells() -> None:
    rows = _rows(40, 39, cls="test.add", size="XS", cost=0.01, latency=1.0) + _rows(
        40, 30, cls="backend.route.add", size="M"
    )
    profile = _profile({("test.add", "XS"): 8, ("backend.route.add", "M"): 2})
    s = tac(profile, rows, cells=build(rows))
    assert s.total_volume == 10 and s.deliver_volume == 8
    assert s.coverage == 0.8  # 8/10 by volume, not 1/2 by cells
    assert s.earned_volume == 0 and s.earned_coverage == 0.0  # nothing human-verified yet
    # 30 of 40 reads insufficient under the look rule: a person, not more attempts
    assert s.volume_by_route[ROUTE_DELIVER] == 8 and s.volume_by_route[ROUTE_HUMAN] == 2
    by = {(c.capability_class, c.size): c for c in s.cells}
    assert by[("test.add", "XS")].deliverable and by[("test.add", "XS")].pick is not None
    assert by[("test.add", "XS")].pick.label == "agentic/m1@p1"  # type: ignore[union-attr]
    assert not by[("backend.route.add", "M")].deliverable
    assert "**80%**" in cap.render_coverage(s)
    assert s.to_dict()["coverage"] == 0.8


def test_tac_unmeasured_cells_are_not_yet_measured() -> None:
    s = tac(_profile({("docs.update", "S"): 4}), [])
    assert s.coverage == 0.0
    assert s.cells[0].route == cap.NOT_YET_MEASURED
    assert s.cells[0].to_dict()["why"] == "no rows for this cell"
    assert s.volume_by_route[cap.NOT_YET_MEASURED] == 4


def test_tac_false_q1_cell_never_counts() -> None:
    bad = _row(cls="backend.route.add", size="M")
    object.__setattr__(bad, "target_green", False)
    rows = [*_rows(40, 40, cls="backend.route.add", size="M"), bad]
    s = tac(_profile({("backend.route.add", "M"): 7}), rows)
    assert s.deliver_volume == 0
    assert s.cells[0].route == ROUTE_DO_NOT_SHIP
    assert s.cells[0].cell.verification_tier == cap.TIER_UNTRUSTED


def test_tac_empty_profile_is_zero_without_crash() -> None:
    s = tac(_profile({}), [])
    assert s.total_volume == 0 and s.coverage == 0.0 and s.cells == ()


def test_tac_requires_class_size_map() -> None:
    m = build([], projection=cap.PROJECTION_CLASS)
    with pytest.raises(ValueError, match="class x size"):
        tac(_profile({}), [], cells=m)


# ---------------------------------------------------------------------------
# The shipped census through the SHIPPED importer (always runs; no private copy)
# ---------------------------------------------------------------------------

_CENSUS_DATA = Path(__file__).resolve().parents[1] / "data" / "census-2026-07-08"


def test_real_census_map_has_zero_false_q1_and_licenses_nothing() -> None:
    """The 1,071-row census, imported by ``crb.core.legacy.import_census`` (the importer
    the product ships — a private re-implementation here could not catch an importer
    regression; CodeRabbit on PR #5, 2026-09-16). ``tests/test_census_gate.py`` is the
    invariant gate on the same data; this case pins what the capability map says about it:
    no false-Q1, and — under routing.v2 — nothing licensed, since no reading was registered
    over it and its apparatus is history (ADR-0025 item 15)."""
    rows = [
        g.row
        for g in import_census(
            _CENSUS_DATA / "grades.jsonl", _CENSUS_DATA / "tasks", _CENSUS_DATA / "configs.json"
        )
    ]
    assert len(rows) >= 1000
    assert len({r.apparatus_version for r in rows}) == 1
    for name, m in cap.capability_views(rows).items():
        assert m.false_q1_total == 0, name
        for c in m.cells:
            assert c.false_q1 == 0, (name, c.label)
            assert c.verification_tier != cap.TIER_UNTRUSTED, (name, c.label)
            assert c.route != ROUTE_DELIVER, (name, c.label)
    cs = cap.build_capability_map(rows)
    assert cs.rows == len(rows)
    assert "v3-legacy" in {b for c in cs.cells for b in c.belt_sets}
    assert cap.render_markdown(cs).count("\n") > len(cs.cells)


def test_cell_fields_are_the_projection_basis() -> None:
    assert cap.PROJECTION_CELL == CELL_FIELDS
    assert isinstance(cap.projected_key(_row().cell, cap.PROJECTION_CLASS), CellKey)


# ---------------------------------------------------------------------------
# the controls gate on the map (ADR-0003 amendment) + the failure split on cells
# ---------------------------------------------------------------------------


def _verdict(**kw: object) -> ControlsVerdict:
    base: dict[str, object] = {
        "passed": True,
        "constructible": 56,
        "total": 56,
        "escapes": 0,
        "run_id": "c" * 32,
        "created": "2026-09-13T00:00:00+00:00",
        "apparatus_version": LIVE,
    }
    base.update(kw)
    return ControlsVerdict(**base)  # type: ignore[arg-type]


def test_map_without_a_verdict_reads_it_as_unmeasured() -> None:
    m = cap.build_capability_map(_rows(40, 39), readings=_book(_rows(40, 39)), oracle_by_task={})
    assert m.controls is None and m.to_dict()["controls"] is None
    c = m.cells[0]
    assert c.route == ROUTE_CALIBRATE
    assert c.decision is not None and c.decision.controls is not None
    assert not c.decision.controls.measured
    assert c.decision.controls_policy == "controls-gate.v2"
    assert "controls_unmeasured" in {sf.code for sf in c.decision.shortfalls}


def test_green_cell_routes_human_under_a_failed_gate() -> None:
    m = build(_rows(40, 39), controls=_verdict(passed=False))
    c = m.cells[0]
    assert c.route == ROUTE_HUMAN and c.reason_code == "controls_failed"
    assert "instrument defect" in c.reason
    assert m.controls is not None and not m.controls.passed
    d = c.to_dict()
    assert d["reason_code"] == "controls_failed" and d["decision"]["controls"]["passed"] is False
    # by_route + TAC see the same verdict: nothing delivers on a failed gate
    assert m.by_route()[ROUTE_HUMAN] == [c] and m.by_route()[ROUTE_DELIVER] == []


def test_green_cell_calibrates_under_thin_or_unmeasured_controls() -> None:
    thin = build(_rows(40, 39), controls=_verdict(constructible=24, total=56))
    assert thin.cells[0].route == ROUTE_CALIBRATE
    assert thin.cells[0].reason_code == "controls_thin"
    absent = build(_rows(40, 39), controls=ControlsVerdict.unmeasured())
    assert absent.cells[0].route == ROUTE_CALIBRATE
    assert absent.cells[0].reason_code == "controls_unmeasured"
    assert absent.to_dict()["controls"]["measured"] is False


def test_green_cell_delivers_only_with_passed_majority_and_zero_escapes() -> None:
    ok = build(_rows(40, 39), controls=_verdict())
    c = ok.cells[0]
    assert c.route == ROUTE_DELIVER and c.reason_code == "deliver"
    assert c.decision is not None and c.decision.controls_policy == "controls-gate.v2"
    assert c.decision.controls is not None and c.decision.controls.run_id == "c" * 32
    escaped = build(_rows(40, 39), controls=_verdict(escapes=2))
    assert escaped.cells[0].route == ROUTE_HUMAN
    assert escaped.cells[0].reason_code == "controls_escapes"


def test_config_pick_and_tac_are_routed_under_the_maps_verdict() -> None:
    rows = _config("a", cost=0.01, latency=5.0) + _config("b", cost=0.02, latency=6.0)
    assert best(rows, capability_class="bug.fix") is not None
    assert best(rows, capability_class="bug.fix", controls=_verdict(passed=False)) is None
    assert candidates(rows, capability_class="bug.fix", controls=_verdict(constructible=1)) == []
    pick = best(rows, capability_class="bug.fix", controls=_verdict())
    assert pick is not None and pick.label.startswith("agentic/a@")
    profile = cap.RepoChangeProfile(
        repo="r", n_commits=10, examined=10, skipped=0, cells={("bug.fix", "S"): 10}
    )
    # the class × size map failed the gate → the config pick is never consulted, coverage 0
    failed = build(rows, controls=_verdict(passed=False))
    s = tac(profile, rows, cells=failed)
    assert s.coverage == 0.0 and s.volume_by_route[ROUTE_HUMAN] == 10
    assert s.cells[0].to_dict()["reason_code"] == "controls_failed"
    # one config per class × size cell: a cell that pooled two models' rows would be licensed
    # by neither model's reading (ADR-0025 item 12), so coverage counts config "a" alone
    only_a = _config("a", cost=0.01, latency=5.0)
    passed = build(only_a, controls=_verdict())
    assert tac(profile, only_a, cells=passed).coverage == 1.0


def _kind_rows() -> list[GradeRow]:
    """8 clean · 2 builder_red · 1 budget · 1 protocol · 2 harness · 1 DQ (n = 14) — rows of
    2.0, whose labels a test may replace wholesale (a 2.4 row pins its own)."""
    out = _rows(10, 8, apparatus_version="2.0")
    out[8] = GradeRow.from_dict(
        {**out[8].to_dict(), "labels": {"failure_kind": "budget", "stop_reason": "wall_clock"}}
    )
    out += [
        GradeRow.from_dict(
            {
                **_row(clean=False, task_id="aa" * 8, apparatus_version="2.0").to_dict(),
                "error": "protocol violation: network: curl",
            }
        ),
        GradeRow.from_dict(
            {
                **_row(clean=False, task_id="bb" * 8, apparatus_version="2.0").to_dict(),
                "error": "SandboxUnavailable: docker",
            }
        ),
        GradeRow.from_dict(
            {
                **_row(clean=False, task_id="cc" * 8, apparatus_version="2.0").to_dict(),
                "error": "TimeoutError: belt",
            }
        ),
        _row(clean=False, disqualified=True, task_id="dd" * 8, apparatus_version="2.0"),
    ]
    return out


def test_cell_carries_the_failure_split_and_model_point_next_to_the_point() -> None:
    m = build(_kind_rows())
    c = m.cells[0]
    assert c.n == 13 and c.point == pytest.approx(8 / 13)
    assert (c.n_builder_red, c.n_budget, c.n_protocol, c.n_harness, c.n_disqualified) == (
        1,
        1,
        1,
        2,
        1,
    )
    assert c.model_n == 9 and c.model_point == pytest.approx(8 / 9)
    assert c.point is not None and c.model_point is not None and c.point < c.model_point
    d = c.to_dict()
    assert d["failure_split"] == {
        "builder_red": 1,
        "budget": 1,
        "protocol": 1,
        "harness": 2,
        "outage": 0,
        "disqualified": 1,
    }
    assert d["model_n"] == 9 and d["model_point"] == round(8 / 9, 4)
    assert d["stats"]["n_harness"] == 2 and d["stats"]["model_point"] == round(8 / 9, 4)
    # rows of 2.0 are history: outside the sealed posture, never read by a reading
    assert c.route == ROUTE_CALIBRATE and c.reason_code == "posture_unsealed"
    # the honest-empty cell has no split and no model point
    e = cap.empty_cell(c.key)
    assert e.model_point is None and e.model_n == 0 and e.n_harness == 0
    assert e.to_dict()["model_point"] is None and e.reason == "no rows for this cell"
    # a cell of only instrument errors: point 0, model point None (no fair attempt to speak of)
    only = build(
        [
            GradeRow.from_dict(
                {
                    **_row(clean=False, task_id=f"{i:016x}", apparatus_version="2.0").to_dict(),
                    "error": "OSError: x",
                }
            )
            for i in range(3)
        ]
    ).cells[0]
    assert only.point == 0.0 and only.model_point is None and only.n_harness == 3


def test_render_markdown_shows_the_split_the_model_point_and_the_controls_state() -> None:
    m = build(_kind_rows(), controls=_verdict(constructible=3, total=7))
    out = cap.render_markdown(m)
    assert "| model | split r·b·p·h·dq |" in out.splitlines()[4]
    assert "controls=thin (3/7 constructible, 0 escape(s))" in out
    assert "| 1·1·1·2·1 |" in out and "(n=9)" in out
    assert "controls=not evaluated" in cap.render_markdown(cap.build_capability_map(_kind_rows()))
    assert "controls=unmeasured" in cap.render_markdown(
        build(_kind_rows(), controls=ControlsVerdict.unmeasured())
    )
    assert "controls=failed (7/7" in cap.render_markdown(
        build(_kind_rows(), controls=_verdict(passed=False, constructible=7, total=7))
    )
