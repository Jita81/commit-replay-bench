"""The prevention chain — the loop's only state, hash-chained and tamper-evident.

Navigation
----------
What it is:   The prevention record chain's test suite (ADR-0020 §3, §4).
What it does: Pins that records chain and verify (a memory store and the JSONL twin), that
              editing any record after it was written breaks the chain, that the switch is the
              last ``switched`` record, and that ``off`` suspends every change while
              ``context`` suspends the switches but keeps the lines — nothing is lost, and
              switching back resumes them.
How:          Records built directly; stores from src/crb/core/prevention.py; the fold
              ``in_force`` over the chain.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0020-a-bug-is-closed-by-prevention.md,
              docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/core/prevention.py (under test), tests/prevention_fixtures.py (records),
              src/crb/core/ledger.py (the chain discipline and ``LedgerIntegrityError``),
              src/crb/server/prevention_state.py (the events-table store the same chain lives
              in on a stack), tests/test_server_routes_prevention.py (that store's round trip)
Tested by:    tests/test_prevention_store.py
Touch when:   a record kind or a record field is added (the chain must still verify after a
              JSON round trip).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crb.core.ledger import GENESIS_HASH, LedgerIntegrityError
from crb.core.prevention import (
    AUTO_CONFIG,
    AUTO_CONTEXT,
    AUTO_OFF,
    JsonlPreventionStore,
    PreventionRecord,
    changes,
    in_force,
    snapshot,
    switch_state,
    verify_records,
)
from prevention_fixtures import REPO, at, store_of, switched


def _applied(
    lever: str, family: str, *, i: float, cid: str, what: dict[str, object]
) -> PreventionRecord:
    return PreventionRecord(
        "applied",
        REPO,
        {
            "change_id": cid,
            "lever_id": lever,
            "family": family,
            "level": "gate" if family == "config" else "advisory",
            "targets": ["protocol:network:go mod"],
            "stratum": {"mode": "blind"},
            "key": "2.2|claude_code|claude-sonnet-5|crb.prevention.sig.v1",
            "what": what,
            "before": {"protocol:network:go mod": {"k0": 3, "n0": 10}},
        },
        actor="loop",
        on_behalf_of="op-1",
        created=at(i),
    )


LINE = {
    "line_id": "abc123abc123",
    "template_id": "T-NET",
    "signature": "protocol:network:go mod",
    "text": "No network: `go mod` is refused and ends the attempt.",
    "taught_by_tasks": ["a", "b", "c"],
}
GATE = {"section": "checks", "key": "finish_gate", "value": True}


def test_records_chain_and_verify() -> None:
    store = store_of(
        [
            switched(AUTO_CONTEXT, i=1),
            _applied("line:T-NET", "context", i=2, cid="c1", what=LINE),
        ]
    )
    recs = store.records()
    assert recs[0].prev_hash == GENESIS_HASH
    assert recs[1].prev_hash == recs[0].row_hash
    assert verify_records(recs) == 2
    # every record carries the rule versions and the apparatus
    assert set(recs[0].rules) == {"signature", "decision", "apparatus"}
    # a JSON round trip (what an events payload column returns) still verifies
    back = [PreventionRecord.from_dict(json.loads(json.dumps(r.to_dict()))) for r in recs]
    assert verify_records(back) == 2


def test_an_edited_record_breaks_the_chain() -> None:
    recs = store_of([switched(AUTO_OFF, i=1), switched(AUTO_CONFIG, i=2, reason="go")]).records()
    d = recs[1].to_dict()
    d["payload"]["auto_apply"] = "context"  # somebody rewrites what the operator chose
    edited = PreventionRecord.from_dict(d)
    with pytest.raises(LedgerIntegrityError, match="edited after it was written"):
        verify_records([recs[0], edited])
    # dropping a record breaks the links too
    with pytest.raises(LedgerIntegrityError, match="chain broken"):
        verify_records([recs[1]])


def test_jsonl_store_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "prevention.jsonl"
    store = JsonlPreventionStore(path)
    a = store.append(switched(AUTO_CONTEXT, i=1))
    b = store.append(_applied("line:T-NET", "context", i=2, cid="c1", what=LINE))
    assert [r.row_hash for r in store.records()] == [a.row_hash, b.row_hash]
    assert JsonlPreventionStore(path).records()[1].payload["what"]["line_id"] == "abc123abc123"
    lines = path.read_text(encoding="utf-8").splitlines()
    d = json.loads(lines[0])
    d["reason"] = "tampered"
    path.write_text(json.dumps(d) + "\n" + lines[1] + "\n", encoding="utf-8")
    with pytest.raises(LedgerIntegrityError):
        JsonlPreventionStore(path).records()


def test_switch_state_is_the_last_switched_record() -> None:
    assert switch_state([]).auto_apply == AUTO_OFF
    recs = store_of(
        [
            switched(AUTO_CONFIG, i=1, actor="op-1", reason="try it"),
            switched(AUTO_CONTEXT, i=2, actor="op-2", reason="lines only for now"),
        ]
    ).records()
    st = switch_state(recs)
    assert (st.auto_apply, st.switched_by, st.reason) == (
        AUTO_CONTEXT,
        "op-2",
        "lines only for now",
    )
    assert st.switched_at == at(2)


def test_off_suspends_every_change_and_context_suspends_switches() -> None:
    base = [
        _applied("line:T-NET", "context", i=2, cid="c1", what=LINE),
        _applied("finish_gate", "config", i=3, cid="c2", what=GATE),
    ]
    chs = changes(store_of(base).records())
    ids = lambda xs: sorted(c.change_id for c in xs)  # noqa: E731
    assert ids(in_force(chs, switch=AUTO_CONFIG)) == ["c1", "c2"]
    assert ids(in_force(chs, switch=AUTO_CONTEXT)) == ["c1"]
    assert ids(in_force(chs, switch=AUTO_OFF)) == []
    # off then back: nothing lost, the same changes resume
    recs = store_of(
        [switched(AUTO_CONFIG, i=1), *base, switched(AUTO_OFF, i=4), switched(AUTO_CONFIG, i=5)]
    ).records()
    assert snapshot(recs[:3], repo=REPO).auto_apply == AUTO_CONFIG
    off = snapshot(recs[:4], repo=REPO)
    assert off.auto_apply == AUTO_OFF and off.changes == () and off.lines == ()
    back = snapshot(recs, repo=REPO)
    assert ids(back.changes) == ["c1", "c2"] and back.overlay == {"checks": {"finish_gate": True}}
    assert [ln.line_id for ln in back.lines] == ["abc123abc123"]
