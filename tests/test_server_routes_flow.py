"""``GET /flow`` — each stream's lead time and spend, and the figures it refuses to invent.

Navigation
----------
What it is:   The route suite of ``GET /flow`` — the reading five screens show their own
              stream's numbers from.
What it does: Pins the reading's shape (six streams, the apparatus, the method sentence), the
              measure stream's spend over the seed (an unpriced imported row is never counted
              as zero), the honest empties with their reasons, the connect stream's
              registration → first PASSED controls report (an escape does not count), the
              measure stream's exact run and bar times and its cost per cell over the first
              ten rows (withheld over a floor), the decide stream's attested row → signature
              and first-deliver → signature to the second (a stamp of another cell, scope,
              repository or later moment never pairs), the account figures an admin's only,
              the manufacture chain's registered → opened → merged, an account recovery on
              the platform stream, the reviewers' stated minutes, the spend counted once
              across the streams, the figures served as not captured with their gap ids, and
              the 404 / 401 / 409 answers.
How:          ``make_env`` over the synthetic seed; events and a factory evidence chain are
              written directly for the cases the seed has no data for; a deliberately
              false-Q1 row proves the read refuses untrusted rows like the map does.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/server/routes/flow.py (under test), src/crb/server/flow.py (the fold),
              src/crb/core/flow.py (the arithmetic, unit-tested in tests/test_flow.py),
              tests/fixtures/server_seed.py (the seed and the role ladder),
              tests/fixtures/signoff_seed.py (the attested sign-off),
              docs/dod/streams/measure.md (the MEASURE criteria this endpoint answers)
Tested by:    tests/test_server_routes_flow.py
Touch when:   never for a new repository; a stream's milestone pair changes; a figure moves out of
              ``not_captured`` (assert it is measured here and close its gap in the same commit).
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from crb.core.capability import WILDCARD
from crb.core.checks import LABEL_CHECKS
from crb.core.flow import parse_ts
from crb.core.ledger import (
    LABEL_COST_KNOWN,
    LABEL_POSTURE_CLASS,
    NEVER_POOL_AXES,
    GradeRow,
)
from crb.core.review import ReviewRecord
from crb.core.signoff import SignoffRecord
from crb.core.version import APPARATUS_VERSION
from crb.factory.evidence import (
    EV_BACKLOG_EVOLVED,
    EV_BACKLOG_FROZEN,
    EV_DELIVERY,
    EV_DELIVERY_CLOSED,
    EV_DELIVERY_MERGED,
    EV_DELIVERY_REFUSED,
    EV_RED_REFUSED,
    FactoryEvent,
    JsonlFactoryStore,
)
from crb.server.app import API_PREFIX, create_app
from crb.server.factory_state import FactoryHome
from crb.server.flow import ADMIN_ONLY, decide_and_license, measure
from crb.server.flow_record import scope_key
from crb.server.routes.signoffs import load_signoff_records
from crb.store.ledger import DbLedger, DbReviewLedger
from crb.store.models import Event, Grade, User
from fixtures.posture import at_apparatus
from fixtures.server_seed import (
    ALPHA,
    BETA,
    DELIVER_CELL,
    RUN_IDS,
    Env,
    add_users,
    envelope,
    login,
    logout,
    make_env,
    make_factory,
    make_settings,
    seed,
    user_id,
)
from fixtures.signoff_seed import attested_body, clear_policy

#: The streams that buy graded rows; their spends partition the repository's.
STREAMS_THAT_SPEND = ("connect-and-prove", "measure", "manufacture-and-deliver")

PASSING_CONTROLS = {
    "schema": "crb.negative_controls.v1",
    "apparatus": {"apparatus_version": "2.2"},
    "n_tasks": 2,
    "n_rows": 14,
    "violations": 0,
    "escapes": 0,
    "not_constructible": 2,
    "skipped": 0,
    "passed": True,
    "escape_rows": [],
    "rows": [],
}


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path) as e:
        yield e


def reading(env: Env, repo: str = ALPHA) -> dict[str, Any]:
    r = env.get(f"/flow?repo={repo}")
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def stream(body: dict[str, Any], name: str) -> dict[str, Any]:
    (found,) = [s for s in body["streams"] if s["stream"] == name]
    return dict(found)


def lead(s: dict[str, Any], key: str) -> dict[str, Any]:
    (found,) = [lt for lt in s["lead_times"] if lt["key"] == key]
    return dict(found)


def write_chain(env: Env, events: list[FactoryEvent]) -> None:
    """A factory evidence chain with stamps this test chose, written where the product keeps
    it (``<home>/factory/<repo>/evidence.jsonl``) and chained by the store itself."""
    home = FactoryHome(env.settings.home, ALPHA)
    home.dir.mkdir(parents=True, exist_ok=True)
    store = JsonlFactoryStore(home.dir / "evidence.jsonl")
    for ev in events:
        store.append(ev)


def add_event(env: Env, **kw: Any) -> None:
    """One event row, written straight into the store (the product writes these from its own
    routes; here the test needs a specific stamp)."""
    with env.factory() as s:
        s.add(Event(**kw))
        s.commit()


class TestShape:
    def test_every_stream_the_definition_of_done_names_is_served_in_order(self, env: Env) -> None:
        body = reading(env)
        assert [s["stream"] for s in body["streams"]] == [
            "connect-and-prove",
            "measure",
            "decide-and-license",
            "manufacture-and-deliver",
            "learn",
            "run-the-platform",
        ]

    def test_the_reading_carries_the_apparatus_and_says_it_is_derived(self, env: Env) -> None:
        body = reading(env)
        assert body["repo"] == ALPHA and body["apparatus"] == APPARATUS_VERSION
        assert body["method"].startswith("derived from the stored")
        assert body["generated"]

    def test_every_figure_carries_an_n_and_a_label(self, env: Env) -> None:
        for s in reading(env)["streams"]:
            assert s["name"] and s["spend_label"]
            for lt in s["lead_times"]:
                assert lt["label"] and isinstance(lt["n"], int)
                # an unmeasured duration is null with its reason, never 0
                assert (lt["median_s"] is None) == (lt["n"] == 0)
                if lt["n"] == 0:
                    assert lt["reason"]


class TestMeasure:
    def test_the_spend_sums_priced_rows_only_and_counts_the_unpriced(self, env: Env) -> None:
        s = stream(reading(env), "measure")
        # 44 native rows at $0.012 each; the 6 imported census rows report no cost and are
        # NOT counted as zero (GradeRow.cost_known)
        assert (s["spend"]["usd"], s["spend"]["rows_priced"], s["spend"]["rows_unpriced"]) == (
            0.528,
            44,
            6,
        )
        assert s["spend_label"] == "the replay and blind attempts graded for this repository"

    def test_prices_one_routable_cell_from_the_priced_rows(self, env: Env) -> None:
        s = stream(reading(env), "measure")
        # the one cell at the bar (bug.fix|S, 40 rows at $0.012) cost $0.12 to reach its tenth
        # row: its first ten rows only — not the stream's whole $0.528, not its rows after ten
        assert s["per_unit"] == 0.12
        assert s["per_unit_label"] == "per cell that reached 10 rows, over its first 10 rows"
        assert s["per_unit_units"] == 1 and s["per_unit_reason"] == ""
        assert s["per_unit_spend"]["rows_priced"] == 10
        assert s["per_unit_spend"]["rows_unpriced"] == 0

    def test_the_bar_is_timed_and_priced_to_the_cells_tenth_row_exactly(self, env: Env) -> None:
        # one cell of twelve rows a minute apart: the tenth lands 9 minutes after the first;
        # the eleventh reports no price and the twelfth cost $1, both AFTER the bar; a second
        # cell of three $5 rows never reaches it. Only the first ten rows are the bar's money.
        base = env.info.rows[0]
        cell = [row_at(base, minute=i, cost=0.01, run_id="run-a") for i in range(10)]
        cell += [row_at(base, minute=10, cost=None, run_id="run-a")]
        cell += [row_at(base, minute=11, cost=1.0, run_id="run-a")]
        thin = [
            row_at(base, minute=20 + i, cost=5.0, run_id="run-b", capability_class="docs.update")
            for i in range(3)
        ]
        flow = measure(cell + thin, {"run-a": "replay", "run-b": "replay"}, RUNS_QUEUED)
        bar = next(lt for lt in flow.lead_times if lt.key == "first_row_to_bar")
        assert (bar.n, bar.median_s, bar.min_s, bar.max_s) == (1, 540.0, 540.0, 540.0)
        assert flow.per_unit == pytest.approx(0.10)
        assert (flow.per_unit_units, flow.per_unit_reason) == (1, "")
        assert (flow.per_unit_spend.rows_priced, flow.per_unit_spend.rows_unpriced) == (10, 0)
        # the stream's own spend is still every priced row, and names the one unpriced
        assert flow.spend.usd == pytest.approx(0.10 + 1.0 + 15.0)
        assert flow.spend.rows_unpriced == 1

    def test_queued_to_graded_runs_from_the_runs_stamp_to_its_last_row(self, env: Env) -> None:
        # run-a was queued at 09:50 and its rows graded 10:00..10:11 → 21 minutes; run-b was
        # queued at 10:15 and its three rows graded 10:20..10:22 → 7 minutes; median 14 min
        base = env.info.rows[0]
        a = [row_at(base, minute=i, cost=0.01, run_id="run-a") for i in range(12)]
        b = [row_at(base, minute=20 + i, cost=0.01, run_id="run-b") for i in range(3)]
        flow = measure(a + b, {"run-a": "replay", "run-b": "blind"}, RUNS_QUEUED)
        lt = next(lt for lt in flow.lead_times if lt.key == "queued_to_graded")
        assert (lt.n, lt.min_s, lt.max_s, lt.median_s) == (2, 420.0, 1260.0, 840.0)

    def test_a_cost_per_cell_over_a_floor_is_withheld_with_the_reason(self, env: Env) -> None:
        base = env.info.rows[0]
        cell = [row_at(base, minute=i, cost=0.01, run_id="run-a") for i in range(9)]
        cell += [row_at(base, minute=9, cost=None, run_id="run-a")]
        flow = measure(cell, {"run-a": "replay"}, RUNS_QUEUED)
        assert flow.per_unit is None
        assert "1 row" in flow.per_unit_reason and "floor" in flow.per_unit_reason
        assert flow.per_unit_spend.rows_unpriced == 1

    def test_counts_the_rows_the_graded_runs_and_the_cells_at_the_bar(self, env: Env) -> None:
        s = stream(reading(env), "measure")
        assert s["counts"]["graded_rows"] == 50
        # the two replay runs whose rows are in the ledger (the 35 historical rows name runs
        # the runs table never had, so no run of theirs can be timed)
        assert s["counts"]["runs_graded"] == 2
        # only bug.fix|S has reached ten rows
        assert s["counts"]["cells_at_bar"] == 1
        assert lead(s, "first_row_to_bar")["n"] == 1

    def test_a_cell_never_reaches_the_bar_on_rows_the_map_would_not_pool(self, env: Env) -> None:
        # ten rows of one class and size — but split across two apparatus versions, or across
        # sighted and blind — are two cells of five to the map, and so to the flow reading
        base = env.info.rows[0]
        ten = [
            dataclasses.replace(base, created=f"2026-09-01T10:{i:02d}:00+00:00") for i in range(10)
        ]
        assert measure(ten, {}, {}).counts["cells_at_bar"] == 1
        split_version = [at_apparatus(r, "2.2") if i % 2 else r for i, r in enumerate(ten)]
        assert measure(split_version, {}, {}).counts["cells_at_bar"] == 0
        split_mode = [
            dataclasses.replace(r, mode="blind") if i % 2 else r for i, r in enumerate(ten)
        ]
        assert measure(split_mode, {}, {}).counts["cells_at_bar"] == 0
        # nor across two posture classes: the map reads one posture class and never blends
        # two (ADR-0019 §8), so neither may the flow's "first row → tenth"
        split_posture = [split_on(r, "posture_class") if i % 2 else r for i, r in enumerate(ten)]
        assert measure(split_posture, {}, {}).counts["cells_at_bar"] == 0

    @pytest.mark.parametrize("axis", NEVER_POOL_AXES)
    def test_every_never_pool_axis_splits_a_cell(self, env: Env, axis: str) -> None:
        """P-184: the flow keyed a cell without the posture class, the one never-pool axis a
        parallel stream added, and nothing named the axes in one place. Every axis in
        ``NEVER_POOL_AXES`` now splits ten rows into two cells of five here — a new axis is
        covered the moment it is named, and :func:`split_on` refuses an axis it cannot split."""
        base = env.info.rows[0]
        ten = [
            dataclasses.replace(base, created=f"2026-09-01T10:{i:02d}:00+00:00") for i in range(10)
        ]
        split = [split_on(r, axis) if i % 2 else r for i, r in enumerate(ten)]
        assert measure(split, {}, {}).counts["cells_at_bar"] == 0

    def test_queued_to_graded_is_timed_from_the_runs_own_created_stamp(self, env: Env) -> None:
        s = stream(reading(env), "measure")
        lt = lead(s, "queued_to_graded")
        assert lt["n"] == 2 and lt["median_s"] is not None and lt["dropped"] == 0

    def test_a_repository_with_no_rows_reads_unmeasured_not_zero(self, env: Env) -> None:
        s = stream(reading(env, BETA), "measure")
        assert s["spend"] == {
            "usd": None,
            "rows_priced": 0,
            "rows_unpriced": 0,
            "apparatus_versions": [],
        }
        assert lead(s, "queued_to_graded")["median_s"] is None
        assert lead(s, "queued_to_graded")["reason"]


def split_on(row: GradeRow, axis: str) -> GradeRow:
    """``row`` moved to another value of one never-pool axis. An axis this helper does not
    know fails the test, so an axis added to ``NEVER_POOL_AXES`` is never silently skipped."""
    # two axes are read from the row's labels, so the split writes the label
    labelled = {
        "posture_class": {
            LABEL_POSTURE_CLASS: "host"
            if row.posture_class == "docker/gvisor/sealed"
            else "docker/gvisor/sealed"
        },
        "checks_arm": {LABEL_CHECKS: "fmt=0" if row.checks_arm == "fmt" else "fmt=1"},
    }
    fields = {
        "apparatus_version": "2.1" if row.apparatus_version == "2.2" else "2.2",
        "mode": "sighted" if row.mode == "blind" else "blind",
    }
    assert axis in labelled or axis in fields, f"split_on cannot split a cell on {axis!r}"
    if axis in labelled:
        out = dataclasses.replace(row, labels={**row.labels, **labelled[axis]})
    elif axis == "apparatus_version":
        # a row moved to another apparatus keeps only that apparatus's labels (P-309)
        out = at_apparatus(row, fields[axis])
    else:
        out = dataclasses.replace(row, **{axis: fields[axis]})
    assert getattr(out, axis) != getattr(row, axis), f"the split did not move {axis!r}"
    return out


#: The queued stamps of the two runs the exact-answer measure tests grade rows for.
RUNS_QUEUED = {"run-a": "2026-09-01T09:50:00+00:00", "run-b": "2026-09-01T10:15:00+00:00"}


def row_at(
    base: GradeRow,
    *,
    minute: int,
    cost: float | None,
    run_id: str,
    capability_class: str = "bug.fix",
) -> GradeRow:
    """A copy of ``base`` graded at 10:``minute`` on 2026-09-01 in ``capability_class``|S, with
    a price (``cost``) or none (``None`` — the row reported no cost)."""
    labels = {**base.labels, LABEL_COST_KNOWN: "false" if cost is None else "true"}
    return dataclasses.replace(
        base,
        run_id=run_id,
        capability_class=capability_class,
        size="S",
        created=f"2026-09-01T10:{minute:02d}:00+00:00",
        cost_usd=cost or 0.0,
        labels=labels,
        row_hash=f"{run_id}-{minute:02d}".ljust(64, "0"),
    )


#: The deliver cell's (class, size) — the key the recorder stamps a cell by.
DELIVER_CLS = (DELIVER_CELL["capability_class"], DELIVER_CELL["size"])


def sign_the_deliver_cell(env: Env) -> SignoffRecord:
    """Sign the seed's deliver cell as the approver, the honest way, and return the record."""
    clear_policy(env)
    login(env.client, "approver")
    r = env.post("/signoffs", json=attested_body(env, DELIVER_CELL))
    assert r.status_code == 201, r.text
    with env.factory() as db:
        (rec,) = load_signoff_records(db, ALPHA)
    return rec


def scope_of(rec: SignoffRecord, **override: str) -> dict[str, str]:
    """The scope fields the recorder writes into a stamp, as the record's own scope, with any
    field overridden — what the worker's ``_served_map`` hands ``record_deliver_transitions``."""
    scope = {
        "apparatus": rec.apparatus_version,
        "posture_class": rec.posture_class,
        "checks_arm": rec.arm,
        **override,
    }
    return {"scope": scope_key(scope), **scope}


def seconds_between(start: str, end: str) -> float:
    a, b = parse_ts(start), parse_ts(end)
    assert a is not None and b is not None
    return (b - a).total_seconds()


def add_factory_row(env: Env, *, cost: float) -> None:
    """One graded row the factory built — a copy of a seeded row with ``process_step``
    ``factory`` and a factory arm (a build on an authored test, ADR-0026 item 1) — appended
    through the ledger, so it chains like any other."""
    base = env.info.succeeded_rows[0]
    row = dataclasses.replace(
        base,
        row_id="f" * 32,
        process_step="factory",
        labels={**base.labels, "context_arm": "S1@claude-opus-5"},
        run_id="factory-run-1",
        cost_usd=cost,
        created="2026-09-02T12:00:00+00:00",
        prev_hash="",
        row_hash="",
    )
    DbLedger(env.factory).append(row)


class TestSpendIsCountedOnce:
    def test_the_streams_spends_add_up_to_the_repository_total(self, env: Env) -> None:
        add_factory_row(env, cost=0.5)
        body = reading(env)
        total = body["spend"]
        parts = [stream(body, name)["spend"] for name in STREAMS_THAT_SPEND]
        assert sum(p["rows_priced"] for p in parts) == total["rows_priced"] == 45
        assert sum(p["rows_unpriced"] for p in parts) == total["rows_unpriced"] == 6
        assert sum(p["usd"] or 0.0 for p in parts) == pytest.approx(total["usd"])
        assert total["usd"] == pytest.approx(0.528 + 0.5)
        # the streams that buy nothing say so and add nothing
        for name in ("decide-and-license", "learn", "run-the-platform"):
            assert stream(body, name)["spend"]["usd"] is None

    def test_a_factory_row_is_the_manufacture_streams_and_never_the_measure_streams(
        self, env: Env
    ) -> None:
        add_factory_row(env, cost=0.5)
        body = reading(env)
        assert stream(body, "manufacture-and-deliver")["spend"]["usd"] == pytest.approx(0.5)
        m = stream(body, "measure")
        assert m["spend"]["usd"] == pytest.approx(0.528)
        assert m["counts"]["graded_rows"] == 50
        # the repository's cumulative spend is on the reading, and the measure panel names it
        assert m["counts"]["repository_rows_priced"] == 45

    def test_the_total_names_the_apparatus_versions_its_rows_span(self, env: Env) -> None:
        body = reading(env)
        versions = body["spend"]["apparatus_versions"]
        assert versions and versions == sorted(versions)
        assert set(stream(body, "measure")["spend"]["apparatus_versions"]) <= set(versions)


class TestConnectAndProve:
    def test_a_controls_report_that_escaped_does_not_count_as_passed(self, env: Env) -> None:
        s = stream(reading(env), "connect-and-prove")
        lt = lead(s, "registered_to_controls")
        assert lt["n"] == 0 and "passed" in lt["reason"]
        assert s["counts"]["controls_passed"] == 0

    def test_registration_to_the_first_passed_report_is_measured(self, env: Env) -> None:
        add_event(
            env,
            event_id="e" * 32,
            trace_id="t" * 32,
            seq=1,
            timestamp="2026-09-01T10:00:00+00:00",
            stage="system",
            action="repo.created",
            status="ok",
            repo=ALPHA,
            payload_json={},
        )
        add_event(
            env,
            event_id="f" * 32,
            trace_id="u" * 32,
            seq=1,
            timestamp="2026-09-01T11:00:00+00:00",
            stage="oracle",
            action="controls.report",
            status="ok",
            repo=ALPHA,
            payload_json=PASSING_CONTROLS,
        )
        s = stream(reading(env), "connect-and-prove")
        lt = lead(s, "registered_to_controls")
        assert lt["n"] == 1 and lt["median_s"] == 3600.0 and lt["reason"] == ""
        assert s["counts"]["controls_passed"] == 1

    def test_the_developer_hours_the_guide_names_are_served_as_not_captured(self, env: Env) -> None:
        s = stream(reading(env), "connect-and-prove")
        (nc,) = s["not_captured"]
        assert "developer hours" in nc["figure"] and nc["gap"] == "G-556"
        assert nc["why"]

    def test_the_mined_tasks_and_the_gold_clean_ones_are_counted(self, env: Env) -> None:
        s = stream(reading(env), "connect-and-prove")
        assert s["counts"]["tasks_mined"] >= s["counts"]["tasks_gold_clean"] > 0


class TestDecideAndLicense:
    def test_the_decisions_start_and_its_cost_are_not_invented(self, env: Env) -> None:
        s = stream(reading(env), "decide-and-license")
        # both halves are recorded now (ADR-0028, DL-067): nothing is served as missing,
        # and with nothing recorded yet each reads unmeasured with its reason, never zero
        assert s["not_captured"] == []
        lt = lead(s, "routed_deliver_to_signed")
        assert lt["n"] == 0 and lt["median_s"] is None and lt["reason"]
        assert s["spend"]["usd"] is None

    def test_a_cell_first_routing_deliver_to_its_signature_is_measured(self, env: Env) -> None:
        rec = sign_the_deliver_cell(env)
        # the true start: this cell, this repository, the record's own scope, before the
        # signature. Every decoy is LATER, so a fold that took any of them as the start (the
        # latest stamp at or before the signature wins) would serve a different number.
        stamps = [
            ("2026-01-01T09:00:00+00:00", ALPHA, DELIVER_CLS, scope_of(rec)),
            # another cell of the same repository and scope
            ("2026-01-02T09:00:00+00:00", ALPHA, ("docs.update", "S"), scope_of(rec)),
            # the same cell stamped in an older apparatus, another posture, another arm
            ("2026-01-03T09:00:00+00:00", ALPHA, DELIVER_CLS, scope_of(rec, apparatus="1.0")),
            (
                "2026-01-04T09:00:00+00:00",
                ALPHA,
                DELIVER_CLS,
                scope_of(rec, posture_class="docker/gvisor/sealed"),
            ),
            ("2026-01-05T09:00:00+00:00", ALPHA, DELIVER_CLS, scope_of(rec, checks_arm="on")),
            # a stamp with no scope at all (it cannot be matched to any signature)
            ("2026-01-06T09:00:00+00:00", ALPHA, DELIVER_CLS, {"scope": "x"}),
            # the same cell of ANOTHER repository
            ("2026-01-07T09:00:00+00:00", BETA, DELIVER_CLS, scope_of(rec)),
            # the same cell after the signature: no signature answers a later transition
            ("2099-01-01T09:00:00+00:00", ALPHA, DELIVER_CLS, scope_of(rec)),
        ]
        for i, (ts, repo, (cls, size), scope) in enumerate(stamps):
            add_event(
                env,
                event_id=f"{i + 1:032x}",
                trace_id="v" * 32,
                seq=i + 1,
                timestamp=ts,
                stage="system",
                action="cell.routed_deliver",
                status="ok",
                repo=repo,
                payload_json={
                    "capability_class": cls,
                    "size": size,
                    "moment": "observed",
                    **scope,
                },
            )
        add_event(
            env,
            event_id="c" * 32,
            trace_id="v" * 32,
            seq=99,
            timestamp="2026-01-01T09:00:00+00:00",
            stage="system",
            action="flow.recorder_started",
            status="ok",
            repo=ALPHA,
            payload_json={"scope": "y", "inherited": [{"capability_class": "a", "size": "S"}]},
        )
        s = stream(reading(env), "decide-and-license")
        lt = lead(s, "routed_deliver_to_signed")
        expected = seconds_between("2026-01-01T09:00:00+00:00", rec.verified_at)
        assert (lt["n"], lt["median_s"], lt["min_s"], lt["max_s"]) == (
            1,
            expected,
            expected,
            expected,
        )
        assert lt["dropped"] == 0 and lt["reason"] == ""
        assert s["counts"]["cells_at_deliver_before_recording"] == 1

    def test_a_stamp_of_another_scope_never_dates_a_signature(self, env: Env) -> None:
        rec = sign_the_deliver_cell(env)
        # the verifier's case: an old apparatus's stamp of the signed cell, 634 days earlier,
        # is the ONLY stamp — no signature of the current scope answers it
        add_event(
            env,
            event_id="e" * 32,
            trace_id="v" * 32,
            seq=1,
            timestamp="2025-01-01T00:00:00+00:00",
            stage="system",
            action="cell.routed_deliver",
            status="ok",
            repo=ALPHA,
            payload_json={
                "capability_class": DELIVER_CLS[0],
                "size": DELIVER_CLS[1],
                "moment": "observed",
                **scope_of(rec, apparatus="1.0", posture_class="docker/gvisor/sealed"),
            },
        )
        lt = lead(stream(reading(env), "decide-and-license"), "routed_deliver_to_signed")
        assert lt["n"] == 0 and lt["median_s"] is None and lt["reason"]

    def test_a_wildcard_signature_is_dated_from_the_latest_stamp_it_answers(self, env: Env) -> None:
        """A signature over every size (``*``) answers a stamp of each size of its class, so
        several stamps can precede it. The rule is the LATEST at or before the signature: the
        transition this signature answered, not the first one the class ever made. Two
        stamps of the class at two sizes, a day apart, both before the signature — the lead
        time starts at the later one."""
        rec = sign_the_deliver_cell(env)
        wild = dataclasses.replace(rec, size=WILDCARD)
        cls = DELIVER_CLS[0]
        early, late = "2026-01-01T09:00:00+00:00", "2026-01-02T09:00:00+00:00"
        for i, (ts, size) in enumerate(((early, "XS"), (late, DELIVER_CLS[1]))):
            add_event(
                env,
                event_id=f"{i + 1:032x}",
                trace_id="w" * 32,
                seq=i + 1,
                timestamp=ts,
                stage="system",
                action="cell.routed_deliver",
                status="ok",
                repo=ALPHA,
                payload_json={
                    "capability_class": cls,
                    "size": size,
                    "moment": "observed",
                    **scope_of(rec),
                },
            )
        with env.factory() as db:
            flow = decide_and_license(db, ALPHA, [wild], env.info.rows)
        lt = next(lt for lt in flow.lead_times if lt.key == "routed_deliver_to_signed")
        expected = seconds_between(late, rec.verified_at)
        assert (lt.n, lt.median_s) == (1, expected)

    def test_the_reviewers_stated_minutes_are_shown_with_their_n(self, env: Env) -> None:
        s = stream(reading(env), "decide-and-license")
        lt = lead(s, "review_minutes")
        assert lt["n"] == 0 and lt["median_s"] is None and "minutes" in lt["reason"]
        rows = env.info.rows
        ledger = DbReviewLedger(env.factory)
        for i, minutes in enumerate((12, None, 30)):
            ledger.append(
                ReviewRecord(
                    grade_row_hash=rows[i].row_hash,
                    repo=ALPHA,
                    task_id=rows[i].task_id,
                    reviewer="op",
                    statement="looked, could not review",
                    verdict="not_reviewed",
                    evidence_pack_hash=rows[i].evidence_pack_hash,
                    minutes=minutes,
                )
            )
        s = stream(reading(env), "decide-and-license")
        lt = lead(s, "review_minutes")
        # two of three reviews stated their minutes; the third is not counted as zero
        assert lt["n"] == 2 and lt["median_s"] == 21 * 60.0
        assert (lt["min_s"], lt["max_s"]) == (720.0, 1800.0)
        assert s["counts"]["human_reviews"] == 3
        assert s["counts"]["reviews_with_minutes"] == 2
        assert s["counts"]["review_minutes_total"] == 42
        assert "the reviewer minutes each decision cost" not in [
            nc["figure"] for nc in s["not_captured"]
        ]

    def test_no_signoff_yet_reads_unmeasured_with_its_reason(self, env: Env) -> None:
        s = stream(reading(env), "decide-and-license")
        assert s["counts"]["signoffs"] == 0
        assert lead(s, "accepted_to_signed")["reason"]

    def test_the_attested_row_graded_clean_to_the_signature_is_measured(self, env: Env) -> None:
        rec = sign_the_deliver_cell(env)
        attested = rec.attestation.reviewed_row_hash if rec.attestation else ""
        # the rows as the fold receives them, each with a stamp this test chose: the attested
        # row was graded at 08:00; every other row later, so pairing any other row — or the
        # signature with itself — serves a different number
        rows = [
            dataclasses.replace(
                r,
                created="2026-01-01T08:00:00+00:00"
                if r.row_hash == attested
                else f"2026-01-0{2 + i % 7}T08:00:00+00:00",
            )
            for i, r in enumerate(env.info.rows)
        ]
        with env.factory() as db:
            flow = decide_and_license(db, ALPHA, load_signoff_records(db, ALPHA), rows)
        lt = next(lt for lt in flow.lead_times if lt.key == "accepted_to_signed")
        expected = seconds_between("2026-01-01T08:00:00+00:00", rec.verified_at)
        assert (lt.n, lt.median_s, lt.min_s, lt.max_s) == (1, expected, expected, expected)
        assert flow.counts["signoffs"] == 1
        assert flow.counts["signoffs_without_an_attested_row"] == 0


class TestManufactureAndDeliver:
    def test_no_chain_yet_reads_unmeasured_with_its_reason(self, env: Env) -> None:
        s = stream(reading(env), "manufacture-and-deliver")
        assert s["counts"] == {
            "items_registered": 0,
            "pull_requests_opened": 0,
            "merged": 0,
            "closed_unmerged": 0,
            "deliveries_refused": 0,
        }
        for lt in s["lead_times"]:
            assert lt["n"] == 0 and lt["reason"]

    def test_registered_to_opened_to_merged_is_folded_from_the_chain(self, env: Env) -> None:
        write_chain(
            env,
            [
                FactoryEvent(
                    kind=EV_BACKLOG_FROZEN,
                    created="2026-09-01T09:00:00+00:00",
                    payload={"item_ids": ["ITEM-1"], "backlog_hash": "h" * 64},
                ),
                FactoryEvent(
                    kind=EV_DELIVERY,
                    item_id="ITEM-1",
                    created="2026-09-01T10:00:00+00:00",
                    payload={"pr_number": 1, "pr_url": "https://example.invalid/pr/1"},
                ),
                FactoryEvent(
                    kind=EV_DELIVERY_MERGED,
                    item_id="ITEM-1",
                    created="2026-09-03T00:00:00+00:00",
                    payload={"pr_number": 1, "merged_at": "2026-09-01T12:00:00+00:00"},
                ),
            ],
        )
        s = stream(reading(env), "manufacture-and-deliver")
        assert s["counts"]["items_registered"] == 1
        assert s["counts"]["pull_requests_opened"] == 1 and s["counts"]["merged"] == 1
        assert lead(s, "registered_to_pr")["median_s"] == 3600.0
        # GitHub's own merge stamp is preferred over the moment the sync recorded it
        assert lead(s, "pr_to_merged")["median_s"] == 7200.0
        assert lead(s, "registered_to_merged")["median_s"] == 10800.0

    def test_the_cost_of_a_certified_change_is_null_while_nothing_is_priced(self, env: Env) -> None:
        write_chain(
            env,
            [
                FactoryEvent(
                    kind=EV_BACKLOG_FROZEN,
                    created="2026-09-01T09:00:00+00:00",
                    payload={"item_ids": ["ITEM-1"], "backlog_hash": "h" * 64},
                ),
                FactoryEvent(
                    kind=EV_DELIVERY,
                    item_id="ITEM-1",
                    created="2026-09-01T10:00:00+00:00",
                    payload={"pr_number": 1},
                ),
                FactoryEvent(
                    kind=EV_DELIVERY_MERGED,
                    item_id="ITEM-1",
                    created="2026-09-01T12:00:00+00:00",
                    payload={"pr_number": 1},
                ),
            ],
        )
        s = stream(reading(env), "manufacture-and-deliver")
        # the seed has no factory run, so the factory's own rows are none: a cost per merged
        # pull request over no priced row is unmeasured, never $0.00
        assert s["per_unit"] is None and s["per_unit_label"] == "per merged pull request"
        assert s["spend"] == {
            "usd": None,
            "rows_priced": 0,
            "rows_unpriced": 0,
            "apparatus_versions": [],
        }

    def test_a_refused_delivery_and_a_closed_pull_request_are_counted(self, env: Env) -> None:
        write_chain(
            env,
            [
                FactoryEvent(
                    kind=EV_DELIVERY_REFUSED,
                    item_id="ITEM-9",
                    created="2026-09-01T09:00:00+00:00",
                    payload={"reason": "the cell does not route deliver"},
                ),
                FactoryEvent(
                    kind=EV_DELIVERY_CLOSED,
                    item_id="ITEM-8",
                    created="2026-09-01T09:30:00+00:00",
                    payload={"pr_number": 7},
                ),
            ],
        )
        s = stream(reading(env), "manufacture-and-deliver")
        assert s["counts"]["deliveries_refused"] == 1 and s["counts"]["closed_unmerged"] == 1


class TestRunThePlatform:
    def test_the_accounts_are_counted_and_only_the_go_live_lines_are_not_captured(
        self, env: Env
    ) -> None:
        s = stream(reading(env), "run-the-platform")
        assert s["counts"]["accounts"] == 4 and s["counts"]["admins_active"] == 1
        assert [nc["gap"] for nc in s["not_captured"]] == ["G-584"]

    def test_the_account_figures_are_an_admins_only(self, env: Env) -> None:
        # the admin-only user list (GET /users) is refused below admin; the same deployment's account
        # counts and the timing of one person's recovery are refused on /flow too
        add_event(
            env,
            event_id="a" * 32,
            trace_id="b" * 32,
            seq=1,
            timestamp="2026-09-01T10:00:00+00:00",
            stage="system",
            action="user.password_set",
            status="ok",
            actor=user_id("root"),
            payload_json={"target": user_id("viewer1")},
        )
        with env.factory() as db:
            user = db.get(User, user_id("viewer1"))
            assert user is not None
            user.last_login = "2026-09-01T10:30:00+00:00"
            db.commit()
        # the env is signed in as the admin, who reads them (before viewer1 signs in again)
        s = stream(reading(env), "run-the-platform")
        assert s["counts"]["admins_active"] == 1 and s["counts"]["recoveries_started"] == 1
        assert lead(s, "password_set_to_signed_in")["median_s"] == 1800.0
        for role in ("viewer", "operator", "approver"):
            login(env.client, role)
            assert env.get("/users").status_code == 403
            s = stream(reading(env), "run-the-platform")
            assert set(s["counts"]) == {"install_recorded"}
            lt = lead(s, "password_set_to_signed_in")
            assert (lt["n"], lt["median_s"], lt["min_s"], lt["max_s"]) == (0, None, None, None)
            assert lt["reason"] == ADMIN_ONLY

    def test_an_install_that_passed_before_recording_is_never_dated(self, env: Env) -> None:
        # the seeded database held rows before the server first started: the install moment
        # is unknown, so install → first green is unmeasured with the reason, never guessed
        s = stream(reading(env), "run-the-platform")
        lt = lead(s, "installed_to_healthy")
        assert lt["n"] == 0 and lt["median_s"] is None
        assert "before this product recorded it" in lt["reason"]
        assert s["counts"]["install_recorded"] == 0

    def test_install_to_the_first_green_health_is_measured(self, tmp_path: Path) -> None:
        factory = make_factory(tmp_path)
        with factory() as s:
            for i, (action, ts, payload) in enumerate(
                [
                    ("deployment.installed", "2026-09-01T10:00:00+00:00", {"moment": "observed"}),
                    ("deployment.first_healthy", "2026-09-01T10:45:00+00:00", {"status": "ok"}),
                ]
            ):
                s.add(
                    Event(
                        event_id=f"{i:032x}",
                        trace_id="w" * 32,
                        seq=i + 1,
                        timestamp=ts,
                        stage="system",
                        action=action,
                        status="ok",
                        payload_json=payload,
                    )
                )
            s.commit()
        seed(factory)
        add_users(factory)
        with TestClient(create_app(make_settings(tmp_path), factory)) as client:
            login(client, "viewer")
            body = client.get(f"{API_PREFIX}/flow?repo={ALPHA}").json()
        s = stream(body, "run-the-platform")
        lt = lead(s, "installed_to_healthy")
        assert lt["n"] == 1 and lt["median_s"] == 2700.0 and lt["reason"] == ""
        assert s["counts"]["install_recorded"] == 1

    def test_a_recovery_is_timed_from_the_reset_to_the_next_sign_in(self, env: Env) -> None:
        target = user_id("viewer1")
        add_event(
            env,
            event_id="a" * 32,
            trace_id="b" * 32,
            seq=1,
            timestamp="2026-09-01T10:00:00+00:00",
            stage="system",
            action="user.password_set",
            status="ok",
            actor=user_id("root"),
            payload_json={"target": target},
        )
        with env.factory() as s:
            user = s.get(User, target)
            assert user is not None
            user.last_login = "2026-09-01T10:30:00+00:00"
            s.commit()
        s2 = stream(reading(env), "run-the-platform")
        lt = lead(s2, "password_set_to_signed_in")
        assert lt["n"] == 1 and lt["median_s"] == 1800.0
        assert s2["counts"]["recoveries_started"] == 1

    def test_a_person_changing_their_own_password_is_not_a_recovery(self, env: Env) -> None:
        target = user_id("viewer1")
        add_event(
            env,
            event_id="c" * 32,
            trace_id="d" * 32,
            seq=1,
            timestamp="2026-09-01T10:00:00+00:00",
            stage="system",
            action="user.password_set",
            status="ok",
            actor=target,
            payload_json={"target": target},
        )
        s = stream(reading(env), "run-the-platform")
        assert s["counts"]["recoveries_started"] == 0

    def test_a_reset_nobody_has_signed_in_after_is_counted_but_not_timed(self, env: Env) -> None:
        add_event(
            env,
            event_id="9" * 32,
            trace_id="8" * 32,
            seq=1,
            timestamp="2026-09-01T10:00:00+00:00",
            stage="system",
            action="user.password_set",
            status="ok",
            actor=user_id("root"),
            payload_json={"target": user_id("viewer1")},
        )
        s = stream(reading(env), "run-the-platform")
        assert s["counts"]["recoveries_started"] == 1
        assert lead(s, "password_set_to_signed_in")["n"] == 0


class TestLearn:
    def test_a_refusal_answered_by_an_evolution_is_timed(self, env: Env) -> None:
        write_chain(
            env,
            [
                FactoryEvent(
                    kind=EV_RED_REFUSED,
                    item_id="ITEM-1",
                    created="2026-09-01T09:00:00+00:00",
                    payload={"reason": "the test did not fail first"},
                ),
                FactoryEvent(
                    kind=EV_BACKLOG_EVOLVED,
                    item_id="ITEM-2",
                    created="2026-09-01T09:45:00+00:00",
                    payload={"supersedes": "ITEM-1", "backlog_hash": "h" * 64},
                ),
            ],
        )
        s = stream(reading(env), "learn")
        assert s["counts"] == {"refusals": 1, "evolutions": 1, "refusals_answered": 1}
        assert lead(s, "refusal_to_strengthening")["median_s"] == 2700.0

    def test_an_evolution_that_answers_no_refusal_is_not_timed(self, env: Env) -> None:
        write_chain(
            env,
            [
                FactoryEvent(
                    kind=EV_BACKLOG_EVOLVED,
                    item_id="ITEM-2",
                    created="2026-09-01T09:45:00+00:00",
                    payload={"supersedes": "", "backlog_hash": "h" * 64},
                )
            ],
        )
        s = stream(reading(env), "learn")
        assert s["counts"]["evolutions"] == 1 and s["counts"]["refusals_answered"] == 0
        assert lead(s, "refusal_to_strengthening")["reason"]


class TestAccess:
    def test_a_viewer_may_read_it_and_an_anonymous_caller_may_not(self, env: Env) -> None:
        logout(env.client)
        r = env.get(f"/flow?repo={ALPHA}")
        assert r.status_code == 401 and envelope(r)["code"] == "unauthenticated"
        login(env.client, "viewer")
        assert env.get(f"/flow?repo={ALPHA}").status_code == 200

    def test_an_unknown_repository_is_a_404(self, env: Env) -> None:
        r = env.get("/flow?repo=nope")
        assert r.status_code == 404 and envelope(r)["code"] == "not_found"

    def test_a_false_q1_row_refuses_the_read_as_the_map_does(self, env: Env) -> None:
        with env.factory() as s:
            s.add(
                Grade(
                    row_id="bad-row",
                    schema="crb.grade.v2",
                    repo=ALPHA,
                    task_id="deadbeef" * 5,
                    run_id=RUN_IDS["succeeded"],
                    created="2026-09-01T00:00:00+00:00",
                    clean=True,
                    tests_unmodified=True,
                    target_green=False,
                    no_new_failures=True,
                    source_changed=True,
                    capability_class="docs.update",
                    size="S",
                    language="python",
                    evidence_pack_hash="p" * 64,
                    apparatus_version="2.0",
                    belt_set="v4",
                    prev_hash="x" * 64,
                    row_hash="y" * 64,
                )
            )
            s.commit()
        r = env.get(f"/flow?repo={ALPHA}")
        assert r.status_code == 409 and envelope(r)["code"] == "false_q1_refused"
