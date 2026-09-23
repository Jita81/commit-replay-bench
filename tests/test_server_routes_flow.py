"""``GET /flow`` — each stream's lead time and spend, and the figures it refuses to invent.

Navigation
----------
What it is:   The route suite of ``GET /flow`` — the reading five screens show their own
              stream's numbers from.
What it does: Pins the reading's shape (six streams, the apparatus, the method sentence), the
              measure stream's spend over the seed (an unpriced imported row is never counted
              as zero), the honest empties with their reasons, the connect stream's
              registration → first PASSED controls report (an escape does not count), the
              decide stream's attested row → signature, the manufacture chain's
              registered → opened → merged, an account recovery on the platform stream, the
              four figures served as not captured with their gap ids, and the 404 / 401 / 409
              answers.
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
Touch when:   a stream's milestone pair changes; a figure moves out of ``not_captured``
              (assert it is measured here and close its gap in the same commit).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

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
from crb.server.factory_state import FactoryHome
from crb.store.models import Event, Grade, User
from fixtures.server_seed import (
    ALPHA,
    BETA,
    DELIVER_CELL,
    RUN_IDS,
    Env,
    envelope,
    login,
    logout,
    make_env,
    user_id,
)
from fixtures.signoff_seed import attested_body, clear_policy

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
        assert body["repo"] == ALPHA and body["apparatus"] == "2.2"
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
        assert s["spend"] == {"usd": 0.528, "rows_priced": 44, "rows_unpriced": 6}
        assert s["spend_label"] == "every graded row recorded for this repository"

    def test_prices_one_routable_cell_from_the_priced_rows(self, env: Env) -> None:
        s = stream(reading(env), "measure")
        # $0.528 of priced rows over the one cell that reached ten rows
        assert s["per_unit"] == 0.528 and s["per_unit_label"] == "per cell that reached 10 rows"

    def test_counts_the_rows_the_graded_runs_and_the_cells_at_the_bar(self, env: Env) -> None:
        s = stream(reading(env), "measure")
        assert s["counts"]["graded_rows"] == 50
        # the two replay runs whose rows are in the ledger (the 35 historical rows name runs
        # the runs table never had, so no run of theirs can be timed)
        assert s["counts"]["runs_graded"] == 2
        # only bug.fix|S has reached ten rows
        assert s["counts"]["cells_at_bar"] == 1
        assert lead(s, "first_row_to_bar")["n"] == 1

    def test_queued_to_graded_is_timed_from_the_runs_own_created_stamp(self, env: Env) -> None:
        s = stream(reading(env), "measure")
        lt = lead(s, "queued_to_graded")
        assert lt["n"] == 2 and lt["median_s"] is not None and lt["dropped"] == 0

    def test_a_repository_with_no_rows_reads_unmeasured_not_zero(self, env: Env) -> None:
        s = stream(reading(env, BETA), "measure")
        assert s["spend"] == {"usd": None, "rows_priced": 0, "rows_unpriced": 0}
        assert lead(s, "queued_to_graded")["median_s"] is None
        assert lead(s, "queued_to_graded")["reason"]


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
        figures = [nc["figure"] for nc in s["not_captured"]]
        assert figures == [
            "the moment a cell first routed deliver",
            "the reviewer minutes each decision cost",
        ]
        assert {nc["gap"] for nc in s["not_captured"]} == {"G-557"}
        assert "POST /reviews" in s["not_captured"][1]["why"]
        assert s["spend"]["usd"] is None

    def test_no_signoff_yet_reads_unmeasured_with_its_reason(self, env: Env) -> None:
        s = stream(reading(env), "decide-and-license")
        assert s["counts"]["signoffs"] == 0
        assert lead(s, "accepted_to_signed")["reason"]

    def test_the_attested_row_graded_clean_to_the_signature_is_measured(self, env: Env) -> None:
        clear_policy(env)
        login(env.client, "approver")
        r = env.post("/signoffs", json=attested_body(env, DELIVER_CELL))
        assert r.status_code == 201, r.text
        s = stream(reading(env), "decide-and-license")
        lt = lead(s, "accepted_to_signed")
        assert lt["n"] == 1 and lt["median_s"] is not None
        assert s["counts"]["signoffs"] == 1
        assert s["counts"]["signoffs_without_an_attested_row"] == 0


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
        assert s["spend"] == {"usd": None, "rows_priced": 0, "rows_unpriced": 0}

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
    def test_the_accounts_are_counted_and_two_figures_are_not_captured(self, env: Env) -> None:
        s = stream(reading(env), "run-the-platform")
        assert s["counts"]["accounts"] == 4 and s["counts"]["admins_active"] == 1
        assert [nc["gap"] for nc in s["not_captured"]] == ["G-558", "G-584"]

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
