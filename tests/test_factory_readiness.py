"""crb.factory.readiness — structural gaps block, value gaps route, sign-offs are ledgered."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crb.core.ledger import LedgerIntegrityError
from crb.core.spec import ALL_CLASSES
from crb.factory import readiness as rd
from crb.factory.backlog import KIND_CODE, KIND_OPERATOR, BacklogItem


def _item(cls: str = "backend.route.add", facts: tuple[str, ...] = (), **kw: object) -> BacklogItem:
    base: dict[str, object] = {
        "id": "I-1",
        "title": "add health route",
        "kind": KIND_CODE,
        "capability_class": cls,
        "structural_facts": facts,
    }
    base.update(kw)
    return BacklogItem(**base)  # type: ignore[arg-type]


ROUTE_FACTS = (
    "method_path: GET /health",
    "request_shape: no params",
    "response_shape: 200 {status: str}",
    "error_contract: none",
)


# --- catalogue shape --------------------------------------------------------------


def test_catalogue_covers_every_class_with_structural_slots() -> None:
    for cls in ALL_CLASSES:
        slots = rd.slots_for(cls)
        assert slots, cls
        assert any(s.kind == rd.SLOT_STRUCTURAL for s in slots), cls
        assert len({s.name for s in slots}) == len(slots), cls


def test_parse_facts_only_fills_slot_prefixed_lines() -> None:
    facts = rd.parse_facts(["method_path: GET /x", "free text", "response_shape = 200", "k:"])
    assert facts == {"method_path": "GET /x", "response_shape": "200"}


# --- structural gap blocks, value gap routes ---------------------------------------


def test_unfilled_structural_gap_blocks_and_routes_human() -> None:
    r = rd.assess(_item(facts=("method_path: GET /health",)))
    assert not r.ready
    assert r.route_hint == rd.ROUTE_HUMAN
    assert {g.slot for g in r.blocking_gaps} == {
        "request_shape",
        "response_shape",
        "error_contract",
    }
    assert all(g.kind == rd.SLOT_STRUCTURAL for g in r.blocking_gaps)
    qs = rd.open_questions(r)
    assert qs[0]["ref"].startswith("I-1::backend.route.add::")
    assert {q["severity"] for q in qs} == {"blocking", "routed"}
    with pytest.raises(rd.NotReady, match="unsigned structural gap"):
        rd.require_ready(_item(facts=("method_path: GET /health",)))


def test_value_gap_never_blocks_and_routes_test_first() -> None:
    r = rd.assess(_item(facts=ROUTE_FACTS))
    assert r.ready
    assert r.route_hint == rd.ROUTE_TEST_FIRST
    assert [g.slot for g in r.gaps] == ["example_payload"]
    assert r.value_gaps and not r.blocking_gaps
    assert rd.require_ready(_item(facts=ROUTE_FACTS)).ready


def test_all_slots_filled_routes_build() -> None:
    r = rd.assess(_item(facts=(*ROUTE_FACTS, "example_payload: GET /health -> {status: ok}")))
    assert r.ready and r.route_hint == rd.ROUTE_BUILD and not r.gaps
    assert r.fact_lines()[0] == "method_path: GET /health"


def test_readiness_cannot_claim_ready_with_blocking_gap() -> None:
    with pytest.raises(ValueError):
        rd.Readiness(
            "I",
            "bug.fix",
            True,
            (rd.Gap("reproduction", "?", rd.SLOT_STRUCTURAL),),
            rd.ROUTE_BUILD,
            "",
        )


def test_operator_kind_weak_oracle_and_uncatalogued_route_human() -> None:
    op = rd.assess(_item(kind=KIND_OPERATOR, facts=(*ROUTE_FACTS, "example_payload: x")))
    assert op.route_hint == rd.ROUTE_HUMAN and "operator" in op.reason
    weak = rd.assess(_item(cls="docs.update", facts=("doc_target: README quickstart",)))
    assert weak.ready and weak.route_hint == rd.ROUTE_HUMAN and "weak oracle" in weak.reason
    unknown = rd.assess(_item(cls="(unclassified)"))
    assert unknown.ready and not unknown.catalogued and unknown.route_hint == rd.ROUTE_HUMAN


# --- sign-offs ---------------------------------------------------------------------


def test_signoff_fills_structural_gap_and_is_ledgered(tmp_path: Path) -> None:
    ledger = rd.JsonlGapSignoffLedger(tmp_path / "gaps.jsonl")
    item = _item(facts=("method_path: GET /health",))
    for slot, ans in (
        ("request_shape", "no params"),
        ("response_shape", "200 {status}"),
        ("error_contract", "none"),
    ):
        rd.sign(ledger, item, slot, ans, verifier="po@example")
    recs = ledger.for_item(item.id)
    r = rd.assess(item, recs)
    assert r.ready and r.signed_slots == ("error_contract", "request_shape", "response_shape")
    assert r.facts["response_shape"] == "200 {status}"
    assert ledger.verify() == 3
    # value-kind sign-off is recorded with its kind
    rd.sign(ledger, item, "example_payload", "{status: ok}", verifier="po@example")
    assert ledger.for_item(item.id)[-1].kind == rd.SLOT_VALUE
    assert rd.assess(item, ledger.for_item(item.id)).route_hint == rd.ROUTE_BUILD


def test_revocation_reopens_gap_latest_wins(tmp_path: Path) -> None:
    ledger = rd.JsonlGapSignoffLedger(tmp_path / "gaps.jsonl")
    item = _item(facts=ROUTE_FACTS[1:])
    rd.sign(ledger, item, "method_path", "GET /health", verifier="po")
    assert rd.assess(item, ledger.for_item(item.id)).ready
    ledger.append(rd.GapSignoff(item_id=item.id, slot="method_path", verifier="po", revoked=True))
    r = rd.assess(item, ledger.for_item(item.id))
    assert not r.ready and [g.slot for g in r.blocking_gaps] == ["method_path"]


def test_signoff_record_validation_and_redaction() -> None:
    with pytest.raises(ValueError):
        rd.GapSignoff(item_id="I", slot="s", verifier="")
    with pytest.raises(ValueError, match="answer"):
        rd.GapSignoff(item_id="I", slot="s", verifier="v")
    rec = rd.GapSignoff(item_id="I", slot="s", verifier="v", answer="token=ghp_" + "a" * 40)
    assert "ghp_" not in rec.answer


def test_gap_ledger_chain_detects_tamper(tmp_path: Path) -> None:
    p = tmp_path / "gaps.jsonl"
    ledger = rd.JsonlGapSignoffLedger(p)
    item = _item()
    rd.sign(ledger, item, "method_path", "GET /a", verifier="po")
    rd.sign(ledger, item, "request_shape", "none", verifier="po")
    lines = p.read_text().splitlines()
    d = json.loads(lines[0])
    d["answer"] = "GET /b"
    p.write_text("\n".join([json.dumps(d), lines[1]]) + "\n")
    with pytest.raises(LedgerIntegrityError):
        ledger.verify()
