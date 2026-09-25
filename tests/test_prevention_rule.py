"""The prevention rule — apply, measure, decide (``crb.prevention.rule.v1``), on a fixture ledger.

THE LADDER is the scenario the operator's instruction asks for, end to end: a recurring
class is registered with its evidence; a playbook line is applied and measured on the first
attempts whose own labels name it; it does not reduce recurrence and is retired; the class
escalates to the finish gate; the gate is kept at the first look and the class closes after
a zero run. Every other test here is one clause of ADR-0020 §6 held to its words.

Navigation
----------
What it is:   The prevention rule's test suite over the fixture ledger (ADR-0020 §5, §6).
What it does: Pins registration with evidence, watch below the actionable bar, the ladder
              (line → retire → escalate → finish gate → keep → close), a switch that fails
              escalating to the filed item, the deterministic formatter step deciding in
              three, harm at the tenth attempt, reopen, refusals before spend that contain but
              never close, inconclusive on a moved key, capability classes never closed,
              displacement, first attempts only, harness rows in the denominator, zero at the
              first look always keeping, two looks only, a frozen before window, dormant
              classes never credited, prospective links, byte-identical registers and the five
              statuses.
How:          ``Loop`` holds a chained fixture ledger and a chained record store; each round
              appends rows, builds the register and runs ``tick`` at a fixed time.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0020-a-bug-is-closed-by-prevention.md
Works with:   src/crb/core/prevention.py (under test), tests/prevention_fixtures.py (the
              ledger and the ladder), src/crb/core/playbook.py (the line the ladder applies),
              docs/LEARNING-LOOP.md (§7 explains the numbers pinned here)
Tested by:    tests/test_prevention_rule.py
Touch when:   a threshold of the rule changes (bump ``DECISION_RULE`` with it and update the
              expected numbers here).
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from typing import Any

import pytest

from crb.core.ledger import GradeRow
from crb.core.prevention import (
    ACTIONABLE_MIN_N,
    ALPHA_LOOK,
    AUTO_CONFIG,
    AUTO_CONTEXT,
    QUALIFIERS,
    STATUSES,
    Mechanisms,
    MemoryPreventionStore,
    PreventionRecord,
    PreventionRegister,
    Register,
    binom_cdf,
    binom_sf,
    build_register,
    decisive_n,
    link_record,
    tick,
    verify_decisions,
)
from prevention_fixtures import (
    LADDER_PROTOCOL,
    NET_SIG,
    RED_SIG,
    REPO,
    at,
    attempt,
    change_labels,
    exposed_to,
    extend,
    ladder_before,
    ledger,
    line_labels,
    lint_pack,
    switched,
    task,
)

FMT_PACK = lint_pack([{"tool": "gofmt", "verdict": False, "tail": "cmd/root.go\n"}])


class Loop:
    """A repository's ledger and the loop's chain, advanced round by round."""

    def __init__(
        self,
        rows: Iterable[GradeRow],
        *,
        mechanisms: Mechanisms | None = None,
        packs: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self.rows = ledger(rows)
        self.store = MemoryPreventionStore()
        self.mech = mechanisms or Mechanisms()
        self.packs = dict(packs or {})

    def switch(self, mode: str, i: float) -> None:
        self.store.append(switched(mode, i=i))

    def add(self, rows: Iterable[GradeRow]) -> None:
        self.rows = extend(self.rows, rows)

    def register(self) -> Register:
        return build_register(
            self.rows,
            records=self.store.records(),
            repo=REPO,
            mechanisms=self.mech,
            packs=self.packs.get if self.packs else None,
        )

    def tick(self, i: float) -> list[PreventionRecord]:
        out = tick(self.register(), self.store.records(), now=at(i), mechanisms=self.mech)
        return [self.store.append(r) for r in out]

    def records(self, kind: str = "") -> list[PreventionRecord]:
        return [r for r in self.store.records() if not kind or r.kind == kind]

    def applied(self, lever: str, sig: str = NET_SIG) -> PreventionRecord:
        return [
            r
            for r in self.records("applied")
            if r.payload["lever_id"] == lever and sig in r.payload["targets"]
        ][-1]

    def decided(self, sig: str = NET_SIG) -> list[Mapping[str, Any]]:
        return [r.payload for r in self.records("decided") if r.payload["signature"] == sig]


def _ladder_to_line() -> tuple[Loop, str]:
    """Round 1: the before window, the switch to context, the tick that applies the line."""
    loop = Loop(ladder_before())
    loop.switch(AUTO_CONTEXT, 40)
    loop.tick(100)
    return loop, loop.applied("line:T-NET").payload["what"]["line_id"]


def _ladder_to_gate() -> tuple[Loop, str]:
    """Rounds 1–3: the line retires; finish_gate ships; the switch goes to config."""
    loop, line_id = _ladder_to_line()
    loop.add(
        exposed_to(
            start=101,
            n=22,
            recur={0, 4, 8, 13, 18},
            first_task=10,
            labels=line_labels(line_id),
            run="run-3",
        )
    )
    loop.tick(130)
    loop.mech = Mechanisms(shipped=frozenset({"finish_gate"}))
    loop.switch(AUTO_CONFIG, 140)
    loop.tick(150)
    return loop, loop.applied("finish_gate").payload["change_id"]


def _gate_labels(loop: Loop) -> dict[str, str]:
    ids = [
        r.payload["change_id"] for r in loop.records("applied") if r.payload["family"] == "config"
    ]
    return change_labels(*ids)


def _ladder_to_closed() -> Loop:
    loop, _ = _ladder_to_gate()
    labels = _gate_labels(loop)
    loop.add(exposed_to(start=151, n=12, recur=set(), first_task=20, labels=labels, run="run-4"))
    loop.tick(170)
    loop.add(exposed_to(start=171, n=8, recur=set(), first_task=20, labels=labels, run="run-5"))
    loop.tick(190)
    return loop


# ---------------------------------------------------------------------------


def test_a_recurring_class_is_registered_with_its_evidence_rows() -> None:
    loop = Loop(ladder_before())
    reg = loop.register()
    e = reg.entry(NET_SIG)
    assert e is not None
    protocol_rows = [r for r in loop.rows if r.failure_kind == "protocol"]
    assert (e.occurrences, e.first_attempts, e.tasks, e.runs) == (9, 9, 6, 2)
    assert e.refs == tuple(r.row_hash for r in protocol_rows) and e.refs_total == 9
    assert (e.first_seen, e.last_seen) == (at(0), at(12))
    assert e.by_mode == {"blind": 9} and e.by_apparatus == {"2.2": 9}
    assert math.isclose(e.cost_usd, 0.9)
    assert e.actionable and (e.stratum_k, e.stratum_n, e.stratum_tasks) == (9, 30, 6)
    # with the switch off the register still says what the loop would do, and does nothing
    assert e.status == "open" and e.recommendation.lever_id == "line:T-NET"
    assert "switch is off" in e.next
    assert tick(reg, loop.store.records(), now=at(99)) == []
    d = reg.to_dict()["entries"][0]
    assert d["signature"] == NET_SIG and d["refs_total"] == 9


def test_below_two_occurrences_on_two_tasks_the_class_is_watch() -> None:
    rows = [attempt(i=i, task_id=task(i), kind="clean") for i in range(12)]
    rows += [
        attempt(i=20, task_id=task(1), kind="protocol"),
        attempt(i=21, task_id=task(1), kind="protocol"),
    ]
    loop = Loop(rows)
    loop.switch(AUTO_CONFIG, 30)
    e = loop.register().entry(NET_SIG)
    assert e is not None and not e.actionable
    assert (e.status, e.qualifiers) == ("open", ("watch",))
    assert "2 of 2 occurrences on 1 of 2 tasks" in e.next
    assert loop.tick(40) == []
    # below the stratum's ten first attempts it is watch too
    few = Loop([attempt(i=i, task_id=task(i), kind="protocol") for i in range(3)])
    assert few.register().entry(NET_SIG).qualifiers == ("watch",)  # type: ignore[union-attr]
    assert ACTIONABLE_MIN_N == 10


def test_the_ladder_line_retired_escalates_to_the_finish_gate_which_is_kept_and_closes() -> None:
    # --- round 1: registered, a line applied (context), a code item proposed ----------------
    loop, line_id = _ladder_to_line()
    kinds = [(r.kind, r.payload.get("lever_id")) for r in loop.records()[1:]]
    assert ("proposed", "item:refused-call") in kinds and ("applied", "line:T-NET") in kinds
    line = loop.applied("line:T-NET").payload
    assert line["level"] == "advisory" and line["targets"] == [NET_SIG]
    assert (line["before"][NET_SIG]["k0"], line["before"][NET_SIG]["n0"]) == (9, 30)
    assert line["before"][NET_SIG]["decisive_n"] == 11 == decisive_n(0.3)
    assert "`go mod`" in line["what"]["text"]
    e = loop.register().entry(NET_SIG)
    assert (e.status, e.lever_kind) == ("applied", "context")  # type: ignore[union-attr]

    # --- round 2: 22 exposed, 5 recur (3 in the first 11) — continue, then retire -------------
    loop.add(
        exposed_to(
            start=101,
            n=22,
            recur={0, 4, 8, 13, 18},
            first_task=10,
            labels=line_labels(line_id),
            run="run-3",
        )
    )
    m = loop.register().entry(NET_SIG).measurement  # type: ignore[union-attr]
    assert m is not None and (m.exposed_k, m.exposed_n) == (5, 22)
    assert binom_sf(3, 10, 0.3) == pytest.approx(0.617, abs=1e-3)  # no harm at the tenth
    loop.tick(130)
    looks = [(d["look"], d["verdict"], d["k1"], d["n1"]) for d in loop.decided()]
    assert looks == [("1", "continue", 3, 11), ("2", "retire", 5, 22)]
    assert loop.decided()[0]["p_keep"] == pytest.approx(0.5696, abs=1e-4)
    assert loop.decided()[1]["p_keep"] == pytest.approx(0.3134, abs=1e-4)
    reverted = loop.records("reverted")[-1]
    assert reverted.actor == "loop" and reverted.payload["by"] == "loop"
    assert reverted.on_behalf_of == "op-1"  # the person who threw the switch
    e = loop.register().entry(NET_SIG)
    assert e.status == "escalated"  # type: ignore[union-attr]  # finish_gate not shipped

    # --- round 3: the finish gate ships; config; the gate is applied (process) -----------------
    loop.mech = Mechanisms(shipped=frozenset({"finish_gate"}))
    loop.switch(AUTO_CONFIG, 140)
    loop.tick(150)
    gate = loop.applied("finish_gate").payload
    b = gate["before"][NET_SIG]
    assert (b["k0"], b["n0"], b["decisive_n"]) == (14, 52, 12)
    assert gate["level"] == "mistake-proofing" and gate["what"] == {
        "section": "checks",
        "key": "finish_gate",
        "value": True,
    }
    assert loop.register().entry(NET_SIG).lever_kind == "process"  # type: ignore[union-attr]

    # --- round 4: 12 exposed, none recur — kept at look 1 -------------------------------------
    labels = _gate_labels(loop)
    loop.add(exposed_to(start=151, n=12, recur=set(), first_task=20, labels=labels, run="run-4"))
    loop.tick(170)
    keep = loop.decided()[-1]
    assert (keep["look"], keep["verdict"], keep["k1"], keep["n1"]) == ("1", "keep", 0, 12)
    assert keep["p_keep"] == pytest.approx(0.0232, abs=1e-4) and keep["p_keep"] <= ALPHA_LOOK
    assert loop.register().entry(NET_SIG).status == "applied"  # type: ignore[union-attr]

    # --- round 5: 8 more, none recur — a zero run of 20 = max(20, 12): closed -------------------
    loop.add(exposed_to(start=171, n=8, recur=set(), first_task=20, labels=labels, run="run-5"))
    loop.tick(190)
    assert loop.decided()[-1]["verdict"] == "closed"
    reg = loop.register()
    e = reg.entry(NET_SIG)
    assert (e.status, e.lever_kind) == ("closed", "process")  # type: ignore[union-attr]
    assert reg.share_closed_by_process == 1.0
    statuses = {s.signature: s for s in PreventionRegister(loop.records()).statuses(loop.rows)}
    assert (statuses[NET_SIG].status, statuses[NET_SIG].lever) == ("closed", "process")
    # the chain re-derives every decision from the ledger it read
    assert verify_decisions(loop.records(), loop.rows) == []
    # a second tick over the same state appends nothing
    assert loop.tick(191) == []


def test_a_context_line_that_does_not_reduce_recurrence_is_retired_and_escalates() -> None:
    loop, line_id = _ladder_to_line()
    loop.add(
        exposed_to(
            start=101,
            n=22,
            recur={0, 4, 8, 13, 18},
            first_task=10,
            labels=line_labels(line_id),
            run="run-3",
        )
    )
    loop.tick(130)
    assert [d["verdict"] for d in loop.decided()] == ["continue", "retire"]
    reg = loop.register()
    e = reg.entry(NET_SIG)
    assert e is not None and e.status == "escalated" and e.change is not None
    assert e.change.state == "retired"
    # the line is withdrawn from every later run and never re-applied under this apparatus
    assert reg.playbook == ()
    assert ("line:T-NET", "advisory", "retired for this class under apparatus 2.2") in (
        e.recommendation.passed_over
    )
    assert loop.tick(131) == []


def test_a_switch_that_fails_escalates_to_the_filed_item() -> None:
    loop, _ = _ladder_to_gate()
    labels = _gate_labels(loop)
    loop.add(
        exposed_to(
            start=151, n=24, recur={1, 5, 9, 14, 17, 21, 23}, first_task=20, labels=labels, run="r4"
        )
    )
    loop.tick(180)
    verdicts = [d["verdict"] for d in loop.decided()]
    assert verdicts[-2:] == ["continue", "retire"]
    e = loop.register().entry(NET_SIG)
    assert e is not None and e.status == "escalated"
    pending = [p for p in e.proposals if not p.registered]
    assert {p.lever_id for p in pending} >= {"item:refused-call", "item:offline-deps"}
    assert "register the filed item" in e.next
    assert loop.tick(181) == []


def test_the_formatter_step_decides_in_three_attempts() -> None:
    rows = [attempt(i=i, task_id=task(i), kind="clean") for i in range(12)]
    rows.append(attempt(i=12, task_id=task(12), kind="lint"))  # one gofmt rejection
    loop = Loop(
        rows,
        mechanisms=Mechanisms(shipped=frozenset({"format_step"})),
        packs={"c" * 64: FMT_PACK},
    )
    loop.switch(AUTO_CONFIG, 20)
    e = loop.register().entry("format:gofmt")
    assert e is not None and not e.actionable  # one occurrence — but the lever is deterministic
    loop.tick(30)
    gate = loop.applied("format_step", "format:gofmt").payload
    assert gate["level"] == "construction" and gate["before"]["format:gofmt"]["decisive_n"] == 3
    loop.add(
        [
            attempt(i=31 + j, task_id=task(40 + j), labels=change_labels(gate["change_id"]))
            for j in range(3)
        ]
    )
    loop.tick(40)
    d = loop.decided("format:gofmt")
    assert [(x["look"], x["verdict"], x["n1"]) for x in d] == [("1", "keep", 3)]


def test_harm_retires_at_the_tenth_exposed_attempt() -> None:
    rows = [
        attempt(i=i, task_id=task(i % 10), kind="protocol" if i in (0, 11, 22) else "clean")
        for i in range(30)
    ]
    loop = Loop(rows)
    loop.switch(AUTO_CONTEXT, 40)
    loop.tick(50)
    line_id = loop.applied("line:T-NET").payload["what"]["line_id"]
    assert decisive_n(0.1) == 36
    loop.add(
        exposed_to(
            start=51,
            n=10,
            recur={0, 2, 4, 6, 8},
            first_task=20,
            labels=line_labels(line_id),
            run="x",
        )
    )
    loop.tick(70)
    d = loop.decided()
    assert [(x["look"], x["verdict"], x["n1"]) for x in d] == [("harm", "harm", 10)]
    assert d[0]["p_harm"] == pytest.approx(0.00163, abs=1e-5)
    assert loop.records("reverted")[-1].payload["verdict"] == "harm"


def test_a_closed_class_reopens_on_one_exposed_recurrence() -> None:
    loop = _ladder_to_closed()
    labels = _gate_labels(loop)
    loop.add(exposed_to(start=191, n=3, recur={1}, first_task=30, labels=labels, run="run-6"))
    loop.tick(200)
    reopen = loop.decided()[-1]
    recurring = next(r for r in loop.rows if r.created == at(192))
    assert (reopen["verdict"], reopen["row"]) == ("reopened", recurring.row_hash)
    e = loop.register().entry(NET_SIG)
    assert e is not None and e.status == "applied" and "reopened" in e.qualifiers
    # a later zero run closes it again — a fresh window after the recurrence
    loop.add(exposed_to(start=201, n=20, recur=set(), first_task=30, labels=labels, run="run-7"))
    loop.tick(230)
    assert loop.decided()[-1]["verdict"] == "closed"


def test_refusals_before_spend_contain_and_never_close() -> None:
    sig = "harness:runner-tool-missing:jest"
    rows = [
        attempt(i=i, task_id=task(i), kind="blocked" if i in (2, 7, 12) else "clean")
        for i in range(20)
    ]
    loop = Loop(rows)
    loop.switch(AUTO_CONFIG, 30)
    loop.tick(31)
    e = loop.register().entry(sig)
    assert e is not None and "contained" in e.qualifiers and e.blocked == 3
    assert any(p.lever_id == "item:env-provision" for p in e.proposals)
    # a person links the pre-check (stream D); its exposure starts at the link
    link = link_record(loop.register(), targets=[sig], ref="P-004", actor="op-1", now=at(35))
    loop.store.append(link)
    # the pre-check keeps refusing before spend: $0 rows, but each is the class recurring
    later = [
        attempt(i=40 + j, task_id=task(40 + j), kind="blocked" if j in (3, 30, 50, 57) else "clean")
        for j in range(60)
    ]
    loop.add(later)
    loop.tick(120)
    e = loop.register().entry(sig)
    assert e is not None and e.measurement is not None
    assert e.measurement.exposed_k == 4  # counted, although nothing was spent on them
    assert "closed" not in [d["verdict"] for d in loop.decided(sig)]
    assert e.status != "closed" and "contained" in e.qualifiers


def test_inconclusive_when_the_apparatus_moves_inside_the_window() -> None:
    loop, line_id = _ladder_to_line()
    loop.add(
        [
            attempt(i=101 + j, task_id=task(10 + j), apparatus="2.3", labels=line_labels(line_id))
            for j in range(12)
        ]
    )
    loop.tick(130)
    d = loop.decided()
    assert [x["verdict"] for x in d] == ["inconclusive"]
    assert "comparability key moved" in d[0]["why"]
    # a line is withdrawn (context is not free); nothing was counted across the boundary
    assert loop.records("reverted")[-1].payload["verdict"] == "inconclusive"
    assert d[0]["n1"] == 0

    # a switch stays, marked unproven
    loop2, _ = _ladder_to_gate()
    labels = _gate_labels(loop2)
    loop2.add(
        [
            attempt(i=151 + j, task_id=task(20 + j), apparatus="2.3", labels=labels)
            for j in range(12)
        ]
    )
    loop2.tick(170)
    e = loop2.register().entry(NET_SIG)
    assert e is not None and e.status == "applied" and "unproven" in e.qualifiers
    assert e.change is not None and e.change.state == "in_force"


def test_capability_classes_are_never_closed_by_recurrence() -> None:
    rows = [
        attempt(i=i, task_id=task(i % 10), kind="target_red" if i % 5 == 0 else "clean")
        for i in range(30)
    ]
    loop = Loop(rows, mechanisms=Mechanisms(shipped=frozenset({"finish_gate"})))
    loop.switch(AUTO_CONFIG, 40)
    loop.tick(50)
    gate = loop.applied("finish_gate", RED_SIG)
    assert gate.payload["targets"] == [RED_SIG]
    labels = change_labels(gate.payload["change_id"])
    loop.add(exposed_to(start=51, n=120, recur=set(), first_task=20, labels=labels, run="run-9"))
    loop.tick(300)
    assert loop.decided(RED_SIG) == []
    e = loop.register().entry(RED_SIG)
    assert e is not None and e.status == "applied" and "capability" in e.qualifiers
    assert e.measurement is not None and e.measurement.exposed_n == 120
    assert "never decided by recurrence" in e.next


def test_displacement_blocks_closure_and_names_the_successor() -> None:
    rows = [
        attempt(i=i, task_id=task(i % 10), kind="protocol" if i in LADDER_PROTOCOL else "clean")
        for i in range(30)
    ]
    loop = Loop(rows, mechanisms=Mechanisms(shipped=frozenset({"finish_gate"})))
    loop.switch(AUTO_CONFIG, 40)
    loop.tick(50)
    gate = loop.applied("finish_gate").payload
    labels = change_labels(gate["change_id"])
    exposed = [
        attempt(
            i=51 + j,
            task_id=task(20 + j % 10),
            kind="budget" if j >= 11 else "clean",
            labels=labels,
        )
        for j in range(20)
    ]
    loop.add(exposed)
    loop.tick(80)
    d = loop.decided()
    assert [x["verdict"] for x in d] == ["keep", "displaced"]
    assert d[-1]["successor"] == "budget:max_turns"
    e = loop.register().entry(NET_SIG)
    assert e is not None and e.status == "applied" and "displaced" in e.qualifiers
    assert "budget:max_turns" in e.next
    assert loop.register().counts["closed"] == 0


def test_escalated_rungs_do_not_move_the_rate() -> None:
    base = ladder_before()
    retries = [
        attempt(i=30 + j, task_id=task(j), kind="clean", trial="r2", run="run-2") for j in range(40)
    ]
    loop = Loop(base + retries)  # 40 clean retries would dilute p0 from 0.30 to 0.13
    e = loop.register().entry(NET_SIG)
    assert e is not None and (e.stratum_k, e.stratum_n) == (9, 30)
    loop.switch(AUTO_CONTEXT, 80)
    loop.tick(90)
    line = loop.applied("line:T-NET").payload
    assert (line["before"][NET_SIG]["k0"], line["before"][NET_SIG]["n0"]) == (9, 30)
    lid = line["what"]["line_id"]
    loop.add(
        [
            attempt(
                i=91 + j, task_id=task(50 + j), kind="protocol", trial="r3", labels=line_labels(lid)
            )
            for j in range(15)
        ]
        + exposed_to(start=110, n=4, recur=set(), first_task=60, labels=line_labels(lid), run="z")
    )
    m = loop.register().entry(NET_SIG).measurement  # type: ignore[union-attr]
    assert m is not None and (m.exposed_k, m.exposed_n) == (0, 4)


def test_harness_rows_stay_in_the_denominator() -> None:
    loop, line_id = _ladder_to_line()
    loop.add(
        [
            attempt(
                i=101 + j,
                task_id=task(10 + j),
                kind="harness" if j % 2 else "clean",
                labels=line_labels(line_id),
            )
            for j in range(11)
        ]
    )
    m = loop.register().entry(NET_SIG).measurement  # type: ignore[union-attr]
    assert m is not None and m.exposed_n == 11  # moving failures into harness cannot shrink n
    loop.tick(130)
    assert loop.decided()[0]["n1"] == 11


def test_zero_recurrences_at_the_first_look_keeps() -> None:
    worst = 0
    for n0 in range(ACTIONABLE_MIN_N, 101):
        for k0 in range(2, n0 + 1):
            p0 = k0 / n0
            dn = decisive_n(p0)
            worst = max(worst, dn)
            assert binom_cdf(0, dn, p0) <= ALPHA_LOOK, (k0, n0, dn)
    assert worst == 183


def test_decisions_are_taken_only_at_the_two_looks() -> None:
    loop, line_id = _ladder_to_line()
    recur = {0, 4, 8, 13, 18}
    for j in range(24):
        loop.add(
            [
                attempt(
                    i=101 + j,
                    task_id=task(10 + j % 10),
                    kind="protocol" if j in recur else "clean",
                    labels=line_labels(line_id),
                )
            ]
        )
        loop.tick(101.5 + j)
    assert [(d["look"], d["n1"]) for d in loop.decided()] == [("1", 11), ("2", 22)]


def test_the_before_window_is_frozen_when_later_rows_arrive() -> None:
    loop, _ = _ladder_to_line()
    frozen = loop.applied("line:T-NET").payload["before"][NET_SIG]
    # late rows stamped BEFORE the change (a run that started earlier), recurring
    loop.add([attempt(i=50 + j, task_id=task(j), kind="protocol") for j in range(10)])
    m = loop.register().entry(NET_SIG).measurement  # type: ignore[union-attr]
    assert m is not None
    assert (m.before_k, m.before_n, m.before_digest) == (9, 30, frozen["digest"])
    assert m.exposed_n == 0


def test_a_quiet_class_with_no_change_is_dormant_and_never_credited() -> None:
    rows = [attempt(i=i, task_id=task(i), kind="protocol") for i in range(3)]
    rows += [attempt(i=10 + i, task_id=task(10 + i), kind="clean") for i in range(25)]
    loop = Loop(rows, mechanisms=Mechanisms(shipped=frozenset({"finish_gate"})))
    loop.switch(AUTO_CONFIG, 50)
    e = loop.register().entry(NET_SIG)
    assert e is not None and (e.status, e.qualifiers) == ("open", ("dormant",))
    assert not e.actionable and "quiet" in e.why_not
    assert loop.tick(60) == []
    reg = loop.register()
    assert reg.counts["closed"] == 0 and reg.share_closed == 0.0


def test_a_link_is_prospective_and_never_crosses_the_apparatus() -> None:
    sig = "harness:no-credential"
    err = "model_error: ANTHROPIC_API_KEY not set — API key is not set"
    old = [
        attempt(
            i=i,
            task_id=task(i),
            apparatus="2.0",
            kind="harness" if i < 5 else "clean",
            error=err if i < 5 else "",
        )
        for i in range(10)
    ]
    cur = [
        attempt(
            i=20 + i,
            task_id=task(20 + i),
            kind="harness" if i in (1, 4, 7) else "clean",
            error=err if i in (1, 4, 7) else "",
        )
        for i in range(20)
    ]
    loop = Loop(old + cur)
    link = link_record(loop.register(), targets=[sig], ref="P-003", actor="op-1", now=at(45))
    loop.store.append(link)
    # rows before the link — and every 2.0 row — are never exposure
    m = loop.register().entry(sig).measurement  # type: ignore[union-attr]
    assert m is not None and m.exposed_n == 0 and (m.before_k, m.before_n) == (3, 20)
    loop.add([attempt(i=50 + j, task_id=task(50 + j)) for j in range(5)])
    m = loop.register().entry(sig).measurement  # type: ignore[union-attr]
    assert m is not None and m.exposed_n == 5 and m.key_moved == 0
    # a row under another apparatus after the link is not pooled: the window is inconclusive
    loop.add([attempt(i=60, task_id=task(60), apparatus="2.3")])
    m = loop.register().entry(sig).measurement  # type: ignore[union-attr]
    assert m is not None and m.exposed_n == 5 and m.key_moved == 1
    loop.switch(AUTO_CONFIG, 61)
    loop.tick(62)
    assert [d["verdict"] for d in loop.decided(sig)] == ["inconclusive"]


def test_register_is_byte_identical_for_the_same_input() -> None:
    loop = _ladder_to_closed()
    a = json.dumps(loop.register().to_dict(), sort_keys=True)
    b = json.dumps(
        build_register(
            tuple(loop.rows), records=tuple(loop.store.records()), repo=REPO, mechanisms=loop.mech
        ).to_dict(),
        sort_keys=True,
    )
    assert a == b
    # rows arrive in ledger order; the register sorts them by time, ties by position, so a
    # store that returns them in another order still gives the same bytes
    shuffled = sorted(loop.rows, key=lambda r: r.row_hash)
    c = json.dumps(
        build_register(
            shuffled, records=loop.store.records(), repo=REPO, mechanisms=loop.mech
        ).to_dict(),
        sort_keys=True,
    )
    assert c == a


def test_statuses_are_the_scorecards_five() -> None:
    assert STATUSES == ("open", "applied", "closed", "retired", "escalated")
    loop = _ladder_to_closed()
    reg = loop.register()
    for e in reg.entries:
        assert e.status in STATUSES
        assert set(e.qualifiers) <= set(QUALIFIERS)
        assert e.lever_kind in ("process", "context", "")
    assert set(reg.counts) == set(STATUSES)
