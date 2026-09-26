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
              that the abstract export carries the default instrument only; that the served
              map reads the repository's own arm by default, another arm on request, and never
              a pooled one; that a sign-off is measured, stamped and lifted on one arm (the
              preview and the write read the repository's own, a record made before a switch
              lifts nothing after it, the v3 chain still verifies); and that the scorecard's
              headline and the failure split read one arm.
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
              served default), src/crb/core/signoff.py and src/crb/server/routes/signoffs.py
              (the sign-off's arm), src/crb/server/routes/value.py (the headline's arm)
Tested by:    tests/test_checks_pooling.py
Touch when:   a switch is added to ``RepoChecks`` (decide which side of the arm it is on, here
              and in ADR-0024) or a new reader groups rows into cells.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import select

from crb.core import capability as cap
from crb.core.checks import ARM_OFF, ARMS, LABEL_CHECKS, RepoChecks, arm_of, resolve
from crb.core.federated import export_abstract
from crb.core.ledger import (
    GENESIS_HASH,
    LABEL_API_STABLE,
    ChecksArmsPooled,
    GradeRow,
    all_cell_stats,
    cell_stats,
    rows_for_checks,
)
from crb.core.signoff import (
    SIGNOFF_SCHEMA_V3,
    SignoffRecord,
    apply_signoffs,
    stamp_evidence,
)
from crb.core.value import prospective_routing, value_report, value_row_from_grade
from crb.store.ledger import DbLedger
from crb.store.models import Signoff
from fixtures.server_seed import ALPHA, Env, make_env, task_id
from fixtures.signoff_seed import attested_body, clear_policy

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


def test_every_served_cell_names_the_arm_it_was_read_on(env: Env) -> None:
    """``checks=current`` resolves to the repository's own arm, and nothing in the response
    said which: a reader could not tell an ``off`` cell from an ``api`` one (CodeRabbit,
    PR #57). Each cell carries ``checks_arm``, from ``CellStats`` itself."""

    def arms(query: str = "") -> set[str]:
        r = env.get(f"/capability-map?repo={ALPHA}&by=class,size&apparatus=all{query}")
        assert r.status_code == 200, r.text
        return {c["checks_arm"] for c in r.json()["cells"]}

    assert arms() == {"off"}
    assert env.put(f"/repos/{ALPHA}", json={"checks": {"api_stable": True}}).status_code == 200
    assert arms("&checks=off") == {"off"}
    rows = [r for r in DbLedger(env.factory).rows(repo=ALPHA) if r.checks_arm == "off"]
    assert cell_stats(rows[:1]).to_dict()["checks_arm"] == "off"


# --- sign-offs, the scorecard's headline and the failure split read one arm ------------------


def test_a_signoff_lifts_only_the_cell_of_the_arm_it_was_made_on() -> None:
    rows = _mixed()
    off_map = cap.build_capability_map(
        rows_for_checks(rows, "off"), projection=cap.PROJECTION_CLASS_SIZE
    )
    api_map = cap.build_capability_map(
        rows_for_checks(rows, "api"), projection=cap.PROJECTION_CLASS_SIZE
    )
    (off_cell,) = off_map.cells
    (api_cell,) = api_map.cells
    signed = stamp_evidence(
        SignoffRecord(repo="r", capability_class="bug.fix", size="S", verifier="v"), off_cell
    )
    assert signed.checks_arm == "off"
    (lifted,) = apply_signoffs([off_cell], [signed], repo="r")
    (kept,) = apply_signoffs([api_cell], [signed], repo="r")
    assert lifted.verification_tier == "human-verified"
    assert kept.verification_tier != "human-verified" and signed.is_stale(api_cell)
    # a record from before the switchboard carries no arm: it was signed on ``off``
    legacy = replace(signed, checks_arm="")
    assert legacy.arm == "off" and legacy.covers_arm(off_cell) and not legacy.covers_arm(api_cell)
    with pytest.raises(ValueError, match="checks_arm must be one of"):
        replace(signed, checks_arm="all")


def test_a_v3_signoff_chain_still_verifies_after_v4_added_the_arm() -> None:
    rec = SignoffRecord(
        repo="r", capability_class="bug.fix", verifier="v", schema=SIGNOFF_SCHEMA_V3
    ).chained(GENESIS_HASH)
    stored = rec.to_dict()
    del stored["checks_arm"]  # a v3 record on disk never carried the field
    back = SignoffRecord.from_dict(stored)
    assert back.checks_arm == "" and back.verify_hash()
    assert "checks_arm" not in back.body()
    assert "checks_arm" in SignoffRecord(repo="r", capability_class="c", verifier="v").body()


def test_the_scorecards_headline_reads_one_arm() -> None:
    rows = [replace(value_row_from_grade(r), mode="blind", cost_usd=1.0) for r in _mixed()]
    rep = value_report(rows, [], apparatus="all").to_dict()
    assert rep["checks"] == "off" and rep["rows"] == 5
    assert rep["north_star"]["n_valid"] == 5 and rep["north_star"]["spend_usd"] == 5.0
    assert rep["rates"]["blind"]["n"] == 5
    api = value_report(rows, [], apparatus="all", checks="api").to_dict()
    assert api["checks"] == "api" and api["north_star"]["n_valid"] == 3
    # the cells are keyed by arm and read every arm, side by side
    assert sorted((c["checks"], c["attempts"]) for c in api["cells"]) == [("api", 3), ("off", 5)]
    with pytest.raises(ValueError, match="unknown checks arm"):
        value_report(rows, [], checks="all")


def _append_api_rows(
    env: Env, n: int, *, mode: str = "sighted", cell: tuple[str, str] = ("bug.fix", "S")
) -> list[GradeRow]:
    """Append ``n`` belt-6 rows (the adapter's stamp) cloned from a clean seeded row of
    ``cell`` — sighted, current apparatus — through the write path."""
    ledger = DbLedger(env.factory)
    template = next(
        r
        for r in ledger.rows(repo=ALPHA)
        if r.clean and (r.capability_class, r.size) == cell and r.mode == "sighted"
    )
    out = []
    for i in range(n):
        d = template.to_dict()
        d.update({"row_id": "", "prev_hash": "", "row_hash": "", "mode": mode, "cost_usd": 0.5})
        d["task_id"] = f"a{mode[0]}{i:038d}"
        d["labels"] = {**d.get("labels", {}), LABEL_CHECKS: API_STAMP, LABEL_API_STABLE: "true"}
        d.pop("failure_kind", None)
        d.pop("cost_known", None)
        out.append(ledger.append(GradeRow.from_dict(d)))
    return out


@pytest.fixture
def approver_env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path, role="approver") as e:
        yield e


DELIVER = {"capability_class": "bug.fix", "size": "S"}
PREVIEW = f"/signoffs/preview?repo={ALPHA}&capability_class=bug.fix&size=S"


def test_a_signoff_reads_the_repositorys_own_arm(approver_env: Env) -> None:
    env = approver_env
    clear_policy(env)
    before = env.get(PREVIEW)
    assert before.status_code == 200, before.text
    n_off = before.json()["evidence"]["n"]
    (api_row,) = _append_api_rows(env, 1)
    r = env.get(PREVIEW)
    assert r.status_code == 200, r.text  # never ChecksArmsPooled
    ev = r.json()["evidence"]
    assert ev["n"] == n_off and ev["checks_arm"] == "off"
    assert r.json()["would_record"]["checks_arm"] == "off"
    assert api_row.row_hash not in {a["row_hash"] for a in r.json()["accepted_rows"]}
    # the approver cannot attest to a row the other instrument graded
    bad = attested_body(env, DELIVER)
    bad["attestation"]["reviewed_row_hash"] = api_row.row_hash
    refused = env.post("/signoffs", json=bad)
    assert refused.status_code == 422 and "checks arm" in refused.text
    made = env.post("/signoffs", json=attested_body(env, DELIVER))
    assert made.status_code == 201, made.text
    d = made.json()
    assert d["checks_arm"] == "off" and d["checks_arm_current"] == "off"
    assert d["evidence"]["n"] == n_off and d["schema"] == "crb.signoff.v4"
    with env.factory() as s:
        row = s.execute(select(Signoff).order_by(Signoff.seq.desc())).scalars().first()
        assert row is not None and row.cell_json["evidence_checks_arm"] == "off"


def _tier(env: Env, query: str = "") -> str:
    r = env.get(f"/capability-map?repo={ALPHA}&by=class,size{query}")
    assert r.status_code == 200, r.text
    (cell,) = [
        c for c in r.json()["cells"] if (c["capability_class"], c["size"]) == ("bug.fix", "S")
    ]
    return str(cell["verification_tier"])


def test_a_signoff_on_one_arm_never_lifts_the_cell_of_another(approver_env: Env) -> None:
    env = approver_env
    clear_policy(env)
    assert env.post("/signoffs", json=attested_body(env, DELIVER)).status_code == 201
    assert _tier(env) == "human-verified"
    # the repository switches belt 6 on and grades three rows under it
    assert env.put(f"/repos/{ALPHA}", json={"checks": {"api_stable": True}}).status_code == 200
    _append_api_rows(env, 3)
    assert _tier(env) != "human-verified"  # the attestation saw the other instrument's rows
    assert _tier(env, "&checks=off") == "human-verified"  # … and still covers them
    (listed,) = env.get(f"/signoffs?repo={ALPHA}").json()["items"]
    assert listed["stale"] is True and listed["active"] is False
    assert (listed["checks_arm"], listed["checks_arm_current"]) == ("off", "api")
    # the preview now reads the belt-6 arm alone
    ev = env.get(PREVIEW).json()["evidence"]
    assert (ev["n"], ev["checks_arm"]) == (3, "api")


def test_the_served_scorecard_and_failure_split_read_one_arm(env: Env) -> None:
    def ns(query: str = "") -> int:
        r = env.get(f"/value?repo={ALPHA}{query}")
        assert r.status_code == 200, r.text
        return int(r.json()["north_star"]["n_valid"])

    def split(query: str = "") -> int:
        r = env.get(f"/failure-split?repo={ALPHA}{query}")
        assert r.status_code == 200, r.text
        return int(r.json()["n"])

    n_split = split()
    assert ns() == 0
    _append_api_rows(env, 4, mode="blind")
    assert ns() == 0 and env.get(f"/value?repo={ALPHA}").json()["checks"] == "off"
    assert ns("&checks=api") == 4
    assert env.get("/value").json()["checks"] == "off"
    assert env.get(f"/value?repo={ALPHA}&checks=all").status_code == 422
    assert split() == n_split and split("&checks=api") == 4
    assert env.put(f"/repos/{ALPHA}", json={"checks": {"api_stable": True}}).status_code == 200
    assert ns() == 4 and split() == 4
