"""The value wave wired end to end — a bug class is registered, the loop removes it through a
stream W or stream K configuration lever, and stream S's learning curve shows it stop.

The operator's rule for the loop: "we should be learning from a bug and then going back to
update our process or context to remove it moving forward". These tests hold the merged
product to it across the four streams' seams: L's register and rule, W's ``checks`` surface,
K's ``spend`` surface and S's curve. Each seam that two streams named separately is pinned
here so the two names can never drift apart.

Navigation
----------
What it is:   The cross-stream test suite of the value wave (streams K, W, L, S, D merged).
What it does: Pins the seam constants two streams share (the five statuses, the runner-tool
              prefix, first attempt vs escalated trial, the formatter names, the writable
              switches vs what ships); runs a recurring class through the loop with the
              merged mechanisms until a W lever (the finish gate) closes it and S's curve
              shows its recurrences before and none after; runs a budget class to K's
              calibrated budget; refuses the calibrated budget where K's rule cannot calibrate;
              and runs the worker so the loop's levers reach a real run's row through the
              repository's ``checks`` and ``spend`` surfaces.
How:          ``tests/prevention_fixtures.py`` (the chained fixture ledger), the loop's pure
              ``build_register`` / ``tick`` / ``snapshot``, ``crb.server.prevention_state.
              mechanisms`` (the merged seam) and ``crb.core.value.learning_curve``; the worker
              half uses ``Harness`` and ``FakeBuilder`` from tests/test_worker.py. No model call.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0020-a-bug-is-closed-by-prevention.md (the loop),
              docs/adr/0024-working-by-construction.md (the W switches)
Works with:   src/crb/server/prevention_state.py (``mechanisms`` — the seam under test),
              src/crb/core/prevention.py (register, rule, snapshot), src/crb/core/value.py
              (``default_register``, the curve), src/crb/core/checks.py and
              src/crb/core/spend.py (the surfaces the levers write), src/crb/server/worker.py
              (applies the overlay to a run)
Tested by:    tests/test_value_wiring.py
Touch when:   a stream's seam changes (a status, a writable switch, a shipped mechanism, the
              register's inputs); never for a new repository.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import crb.builders as builders_pkg
from crb.builders.toolcheck import RUNNER_TOOL_MISSING
from crb.core.checks import LABEL_CHECKS, RepoChecks
from crb.core.checks import resolve as resolve_checks
from crb.core.formatting import FORMATTER_WRITE
from crb.core.ledger import GradeRow
from crb.core.prevention import (
    AUTO_CONFIG,
    FORMATTER_TOOLS,
    K_SECTION,
    RUNNER_TOOL_MISSING_PREFIX,
    STATUSES,
    W_SECTION,
    WRITABLE,
    MemoryPreventionStore,
    PreventionRecord,
    build_register,
    is_first_attempt,
    snapshot,
    tick,
)
from crb.core.spend import (
    LABEL_BUDGET_PROFILE,
    PROFILE_CALIBRATED,
    is_escalated_trial,
    resolve_policy,
    validate_spend_config,
)
from crb.core.value import CLASS_STATUSES, default_register, learning_curve, value_row_from_grade
from crb.server.prevention_state import SHIPPED, EventsPreventionStore, mechanisms
from crb.store.jobs import STATUS_SUCCEEDED
from fixtures import pyrepo as pr
from prevention_fixtures import (
    LADDER_PROTOCOL,
    NET_SIG,
    REPO,
    at,
    attempt,
    change_labels,
    exposed_to,
    ladder_before,
    ledger,
    switched,
    task,
)
from test_worker import FakeBuilder, Harness

# --- the seams two streams named separately ------------------------------------------------


def test_the_register_and_the_scorecard_share_the_five_statuses() -> None:
    assert STATUSES == CLASS_STATUSES


def test_the_loop_parses_the_refusal_the_pre_check_writes() -> None:
    assert RUNNER_TOOL_MISSING_PREFIX == RUNNER_TOOL_MISSING


@pytest.mark.parametrize("trial", ["r1", "r2", "r3", "r10", "w1r1", "", "R2", "rx"])
def test_a_first_attempt_is_exactly_what_the_escalation_rule_does_not_call_a_retry(
    trial: str,
) -> None:
    assert is_first_attempt(trial) is (not is_escalated_trial(trial))


def test_every_formatter_the_format_step_writes_is_a_format_class_to_the_loop() -> None:
    # ``standard`` is a linter with a fix mode: its rejections stay lint classes
    assert set(FORMATTER_WRITE) - {"standard"} <= set(FORMATTER_TOOLS)


def test_every_writable_switch_ships_and_lands_on_a_surface_that_accepts_it() -> None:
    assert {w.lever_id for w in WRITABLE} == SHIPPED
    for w in WRITABLE:
        if w.section == W_SECTION:
            assert getattr(RepoChecks.from_config({w.key: w.value}), w.key) is True
        else:
            assert w.section == K_SECTION
            assert validate_spend_config({w.key: w.value}) == {w.key: w.value}
    assert mechanisms().on_by_default == frozenset()  # each waits for the Phase B A/B


# --- a recurring class, removed by a W lever, and the curve bends ---------------------------


def _loop(rows: list[GradeRow]) -> tuple[MemoryPreventionStore, list[GradeRow]]:
    store = MemoryPreventionStore()
    store.append(switched(AUTO_CONFIG, i=40))
    return store, ledger(rows)


def _tick(store: MemoryPreventionStore, rows: list[GradeRow], i: float) -> list[PreventionRecord]:
    mech = mechanisms(rows=rows, repo=REPO)
    reg = build_register(rows, records=store.records(), repo=REPO, mechanisms=mech)
    return [store.append(r) for r in tick(reg, store.records(), now=at(i), mechanisms=mech)]


def test_a_recurring_class_is_closed_by_the_finish_gate_and_the_curve_shows_it_stop() -> None:
    # 1. registered: 9 network refusals in 30 blind first attempts, on 6 tasks
    store, rows = _loop(ladder_before())
    entry = build_register(rows, repo=REPO, mechanisms=mechanisms(rows=rows, repo=REPO)).entry(
        NET_SIG
    )
    assert entry is not None and entry.actionable and entry.occurrences == 9
    # 2. the loop picks W's finish gate (a process lever) — it ships now — and applies it
    appended = _tick(store, rows, 100)
    gate = [r for r in appended if r.kind == "applied" and NET_SIG in r.payload["targets"]]
    assert [r.payload["lever_id"] for r in gate] == ["finish_gate"]
    assert gate[0].payload["what"] == {"section": W_SECTION, "key": "finish_gate", "value": True}
    # 3. the change lands on W's surface: the next run resolves the finish gate ON, from the
    #    repository's block, and the row's config version moves with it
    snap = snapshot(store.records(), repo=REPO, params={}, base_config={})
    resolved = resolve_checks(RepoChecks.from_config(snap.config_section(W_SECTION, {})), None)
    assert resolved.finish_gate and resolved.sources["finish_gate"] == "repo"
    assert "gate=1:repo" in resolved.label()
    # 4. the attempts that ran under it (their own labels name the change) do not recur
    ids = sorted(r.payload["change_id"] for r in store.records() if r.kind == "applied")
    labels = change_labels(*ids)
    rows = ledger(
        [
            *ladder_before(),
            *exposed_to(start=151, n=12, recur=set(), first_task=20, labels=labels, run="r-4"),
            *exposed_to(start=171, n=8, recur=set(), first_task=20, labels=labels, run="r-5"),
        ]
    )
    _tick(store, rows[:42], 170)
    _tick(store, rows, 190)
    verdicts = [
        r.payload["verdict"]
        for r in store.records()
        if r.kind == "decided" and r.payload["signature"] == NET_SIG
    ]
    assert verdicts[0] == "keep"
    # 5. stream S's curve reads L's register: the class recurred before and not after, and
    #    the register counts it closed by process
    curve = learning_curve(
        [value_row_from_grade(r) for r in rows],
        window=10,
        register=default_register(store.records()),
    ).to_dict()
    (net,) = [c for c in curve["classes"] if c["signature"] == NET_SIG and c["repo"] == REPO]
    before, after = net["counts"][:3], net["counts"][3:]
    assert sum(c or 0 for c in before) == len(LADDER_PROTOCOL) - 1  # 8 recurrences
    assert after == [0, 0]
    reg = curve["register"]
    assert reg["source"] == "crb.prevention.register.v1"
    assert reg["by_status"]["closed"] >= 1 and reg["removed_by_process"] >= 1
    assert reg["removed_by_process_share"] == 1.0


def _budget_before(clean_after: int = 30) -> list[GradeRow]:
    return [
        attempt(
            i=i,
            task_id=task(i % 10),
            kind="budget" if i in LADDER_PROTOCOL else "clean",
            run=f"run-{i // 10}",
        )
        for i in range(clean_after)
    ]


def test_a_recurring_budget_class_gets_the_calibrated_budget_on_ks_surface() -> None:
    store, rows = _loop(_budget_before())
    appended = _tick(store, rows, 100)
    applied = [r for r in appended if r.kind == "applied"]
    assert [r.payload["lever_id"] for r in applied] == ["budget_calibrated"]
    assert applied[0].payload["what"] == {
        "section": K_SECTION,
        "key": "budget_profile",
        "value": PROFILE_CALIBRATED,
    }
    snap = snapshot(store.records(), repo=REPO, params={}, base_config={})
    policy = resolve_policy({}, snap.config_section(K_SECTION, {}))
    assert policy.budget_profile == PROFILE_CALIBRATED
    # a run's own parameter still wins over the loop's overlay — the value AND where it came
    # from (a bare object is always truthy: the old line held whatever won)
    ran = resolve_policy({"budget_profile": "default"}, snap.config_section(K_SECTION, {}))
    assert (ran.budget_profile, ran.sources["budget_profile"]) == ("default", "run")


def test_the_loop_never_applies_a_calibrated_budget_k_cannot_calibrate() -> None:
    # 9 budget stops and only 3 clean completions: below K's minimum of 8 clean in the cell
    rows = [
        attempt(i=i, task_id=task(i % 10), kind="clean" if i < 3 else "budget", run=f"r-{i // 6}")
        for i in range(12)
    ]
    store, rows = _loop(rows)
    reg = build_register(
        rows, records=store.records(), repo=REPO, mechanisms=mechanisms(rows=rows, repo=REPO)
    )
    (entry,) = [e for e in reg.entries if e.signature.startswith("budget")]
    reasons = {lever: why for lever, _level, why in entry.recommendation.passed_over}
    assert reasons["budget_calibrated"].startswith("cannot calibrate")
    assert not any(r.kind == "applied" for r in _tick(store, rows, 100))


# --- the worker: the levers reach a real run through the repository's surfaces --------------


@pytest.fixture(autouse=True)
def _fake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(builders_pkg._REGISTRY, "fake", FakeBuilder)
    FakeBuilder.briefs = []
    FakeBuilder.hook = None


def _record(kind: str, payload: dict[str, Any], i: int) -> PreventionRecord:
    return PreventionRecord(
        kind,
        pr.REPO_NAME,
        payload,
        actor="op-1" if kind == "switched" else "loop",
        on_behalf_of="op-1",
        reason="fixture",
        created=f"2026-01-01T00:00:{i:02d}+00:00",
    )


def _applied(lever: str, what: dict[str, Any], i: int, cid: str) -> PreventionRecord:
    return _record(
        "applied",
        {
            "change_id": cid,
            "lever_id": lever,
            "family": "config",
            "level": "mistake-proofing",
            "targets": [NET_SIG],
            "stratum": {"mode": "blind"},
            "key": "2.2|fake|m|crb.prevention.sig.v1",
            "what": what,
            "before": {NET_SIG: {"k0": 3, "n0": 10, "decisive_n": 11}},
        },
        i,
    )


def test_the_worker_runs_under_the_loops_w_and_k_levers(tmp_path: Path, pyrepo: pr.PyRepo) -> None:
    h = Harness(tmp_path, pyrepo)
    h.add_repo()
    h.add_task(pyrepo.feat_task())
    with h.factory() as s:
        store = EventsPreventionStore(s, pr.REPO_NAME)
        store.append(_record("switched", {"auto_apply": "config"}, 1))
        store.append(
            _applied(
                "format_step", {"section": "checks", "key": "format_step", "value": True}, 2, "w1"
            )
        )
        store.append(
            _applied(
                "budget_calibrated",
                {"section": "spend", "key": "budget_profile", "value": "calibrated"},
                3,
                "k1",
            )
        )
        s.commit()
    run = h.enqueue("replay")
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    (row,) = h.worker.ledger.rows(run_id=run.id)
    # W: the format step is ON from the repository's block (the loop wrote it there)
    assert "fmt=1:repo" in row.labels[LABEL_CHECKS]
    # K: the attempt ran under the calibrated profile, recorded on the row and the apparatus
    assert row.labels[LABEL_BUDGET_PROFILE] == PROFILE_CALIBRATED
    assert done.apparatus_json["extra"]["spend"]["budget_profile"] == PROFILE_CALIBRATED
    assert row.labels["learn_changes"] == "k1,w1"
    # a run that opts out of the loop runs as the repository is configured: everything OFF
    off = h.enqueue("replay", params_json={"learning": "off"})
    assert h.run_one().status == STATUS_SUCCEEDED
    (plain,) = h.worker.ledger.rows(run_id=off.id)
    assert LABEL_CHECKS not in plain.labels
    assert plain.labels.get(LABEL_BUDGET_PROFILE, "default") != PROFILE_CALIBRATED
