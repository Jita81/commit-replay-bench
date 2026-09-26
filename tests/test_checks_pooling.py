"""A row graded with a grader-side switch on is never counted in a cell with one graded without.

The format step makes the graded patch the formatted one, and belt 6 adds a belt: a row graded
with either switched on answers a different question from a row graded with both off, so the
two never share a cell (ADR-0024 "Apparatus impact"). The finish gate changes only what the
builder does before it says done — the belts decide clean — so it pools like any other process
lever. The switches are a hashed stamp on the row (``labels.checks``) and a read filter
(``rows_for_checks``), as ADR-0019 makes posture; ``cell_stats`` refuses a mixed cell.

Navigation
----------
What it is:   The pooling ratchet for the "clean means working" switches.
What it does: Pins the arm vocabulary (a row's arm from its stamp, a run's from its resolved
              switches, the same word both ways); that ``cell_stats`` and the capability map
              refuse rows from two arms and ``all_cell_stats`` splits them; that the read
              filter gives each arm its own cells; that a finish-gate row pools with its
              baseline; that the scorecard's cells and prospective routing never pool arms;
              that the abstract export carries the default instrument only; and that the served
              map reads the repository's own arm by default, another arm on request, and never
              a pooled one.
How:          Hand-built ``GradeRow``s with the labels the adapter stamps; the served half over
              ``make_env`` (the seed is all-off) with one belt-6 row appended and the
              repository's ``checks`` block switched through ``PUT /repos``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0024-working-by-construction.md (the switches, their apparatus impact
              and §6, the arm — the stamp-and-filter pattern ADR-0019 sets for posture on #56)
Works with:   src/crb/core/checks.py (the arm), src/crb/core/ledger.py (``checks_arm``,
              ``rows_for_checks``, the refusal), src/crb/core/value.py (the scorecard's cells
              and routing), src/crb/core/federated.py (the export),
              src/crb/server/routes/capability.py and src/crb/server/prevention_state.py (the
              served default)
Tested by:    tests/test_checks_pooling.py
Touch when:   a switch is added to ``RepoChecks`` (decide which side of the arm it is on, here
              and in ADR-0024) or a new reader groups rows into cells.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from crb.core import capability as cap
from crb.core.checks import ARM_OFF, ARMS, LABEL_CHECKS, RepoChecks, arm_of, resolve
from crb.core.federated import export_abstract
from crb.core.ledger import (
    LABEL_API_STABLE,
    ChecksArmsPooled,
    GradeRow,
    all_cell_stats,
    cell_stats,
    rows_for_checks,
)
from crb.core.value import prospective_routing, value_report, value_row_from_grade
from crb.store.ledger import DbLedger
from fixtures.server_seed import ALPHA, Env, make_env, task_id

#: The stamps the adapter writes (``ResolvedChecks.label``).
OFF_STAMP = "fmt=0:default;gate=0:default;api=0:default;cfg=0123456789ab"
API_STAMP = "fmt=0:default;gate=0:default;api=1:repo;cfg=0123456789ab"
FMT_STAMP = "fmt=1:run;gate=0:default;api=0:default;cfg=default"
GATE_STAMP = "fmt=0:default;gate=1:repo;api=0:default;cfg=0123456789ab"


def _row(i: int, *, stamp: str = "", clean: bool = True, belt6: str | None = None) -> GradeRow:
    labels: dict[str, str] = {}
    if stamp:
        labels[LABEL_CHECKS] = stamp
    if belt6 is not None:
        labels[LABEL_API_STABLE] = belt6
    return GradeRow(
        repo="r",
        task_id=f"{i:016x}",
        clean=clean,
        tests_unmodified=True,
        target_green=clean,
        no_new_failures=True,
        source_changed=True,
        capability_class="bug.fix",
        size="S",
        language="go",
        builder="claude_code",
        model="m",
        provider="p",
        evidence_pack_hash="e" * 64 if clean else "",
        gold_clean=True,
        created=f"2026-09-26T00:00:{i:02d}Z",
        labels=labels,
    )


def _mixed() -> list[GradeRow]:
    off = [_row(i) for i in range(5)]
    api = [_row(10 + i, stamp=API_STAMP, belt6="true") for i in range(3)]
    return off + api


def test_the_arm_is_what_the_grader_judges_under() -> None:
    assert ARMS == ("off", "fmt", "api", "fmt,api")
    assert arm_of(format_step=False, api_stable=False) == ARM_OFF
    assert arm_of(format_step=True, api_stable=True) == "fmt,api"
    # a run's arm and its rows' arm are the same word
    for repo, arm in (
        (RepoChecks(), "off"),
        (RepoChecks(api_stable=True), "api"),
        (RepoChecks(format_step=True), "fmt"),
        (RepoChecks(format_step=True, api_stable=True, finish_gate=True), "fmt,api"),
        (RepoChecks(finish_gate=True), "off"),
    ):
        resolved = resolve(repo, None)
        assert resolved.arm == arm
        assert _row(0, stamp=resolved.label()).checks_arm == arm
    assert resolve(RepoChecks(), {"api_stable": True}).arm == "api"
    # a row written before the switchboard, or with every switch off, is the baseline
    assert _row(0).checks_arm == ARM_OFF
    assert _row(0, stamp=OFF_STAMP).checks_arm == ARM_OFF
    assert _row(0, stamp=FMT_STAMP).checks_arm == "fmt"
    # belt 6 recorded on the row is belt 6 switched on, whatever the stamp says
    assert _row(0, belt6="none").checks_arm == "api"


def test_a_checks_on_row_and_a_checks_off_row_are_never_counted_in_the_same_cell() -> None:
    rows = _mixed()
    with pytest.raises(ChecksArmsPooled, match="the checks arms off, api:"):
        cell_stats(rows)
    for projection in cap.PROJECTIONS.values():
        with pytest.raises(ChecksArmsPooled):
            cap.build_capability_map(rows, projection=projection)
    split = sorted(all_cell_stats(rows), key=lambda s: s.checks_arm)
    assert [(s.checks_arm, s.n) for s in split] == [("api", 3), ("off", 5)]
    for arm, n in (("off", 5), ("api", 3), ("fmt", 0)):
        kept = rows_for_checks(rows, arm)
        assert len(kept) == n and all(r.checks_arm == arm for r in kept)
        cmap = cap.build_capability_map(kept)
        assert sum(c.stats.n for c in cmap.cells if c.stats is not None) == n
        assert all(c.stats.checks_arm == arm for c in cmap.cells if c.stats is not None)
    with pytest.raises(ValueError, match="unknown checks arm"):
        rows_for_checks(rows, "all")


def test_a_finish_gate_row_pools_with_its_baseline() -> None:
    rows = [_row(i) for i in range(4)] + [_row(10 + i, stamp=GATE_STAMP) for i in range(2)]
    stats = cell_stats(rows)
    assert stats.n == 6 and stats.checks_arm == ARM_OFF


def test_the_scorecard_never_pools_arms_in_a_cell_or_a_route() -> None:
    rows = [value_row_from_grade(r) for r in _mixed()]
    cells = value_report(rows, []).cells
    assert sorted((c["checks"], c["attempts"]) for c in cells) == [("api", 3), ("off", 5)]
    off = [r for r in rows if r.checks_arm == ARM_OFF]
    on = [r for r in rows if r.checks_arm != ARM_OFF]
    together = prospective_routing(rows).decisions
    apart = [prospective_routing(off).decisions, prospective_routing(on).decisions]
    assert together == {k: apart[0][k] + apart[1][k] for k in together}


def test_the_abstract_export_carries_the_default_instrument_only() -> None:
    cells = export_abstract(_mixed())
    assert sum(c["n"] for c in cells) == 5


# --- served ---------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path) as e:
        yield e


def _n(env: Env, query: str = "") -> int:
    r = env.get(f"/capability-map?repo={ALPHA}&by=class,size&apparatus=all{query}")
    assert r.status_code == 200, r.text
    return sum(c["n"] for c in r.json()["cells"])


def test_the_map_reads_the_repositorys_own_arm_and_never_a_pooled_one(env: Env) -> None:
    n_off = _n(env)
    assert n_off > 0
    DbLedger(env.factory).append(
        GradeRow(
            repo=ALPHA,
            task_id=task_id(1),
            clean=True,
            tests_unmodified=True,
            target_green=True,
            no_new_failures=True,
            source_changed=True,
            capability_class="bug.fix",
            size="S",
            language="python",
            builder="editblock",
            model="m",
            provider="p",
            run_id="c" * 32,
            trial="r1",
            evidence_pack_hash="e" * 64,
            gold_clean=True,
            labels={LABEL_CHECKS: API_STAMP, LABEL_API_STABLE: "true"},
        )
    )
    # the repository grades with every switch off: its map is the off arm's
    assert _n(env) == n_off == _n(env, "&checks=off")
    assert _n(env, "&checks=api") == 1
    assert env.get(f"/routes?repo={ALPHA}&checks=api").status_code == 200
    # a pooled view does not exist
    for bad in ("all", "gate", "fmt+gate"):
        assert env.get(f"/capability-map?repo={ALPHA}&checks={bad}").status_code == 422
    # the repository switches belt 6 on: its default map is now the belt-6 arm alone
    assert env.put(f"/repos/{ALPHA}", json={"checks": {"api_stable": True}}).status_code == 200
    assert _n(env) == 1
    assert _n(env, "&checks=off") == n_off
