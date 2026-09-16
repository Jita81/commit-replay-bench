"""crb.factory.backlog — frozen, hashed, evolvable-only-through-the-front-door.

Navigation
----------
What it is:   The factory backlog's test suite — frozen, hashed, evolvable only through the front
              door.
What it does: Pins item validation and round trip, that freezing computes a hash ``verify``
              holds, that the hash is canonical and order-sensitive, that a tampered frozen
              record fails, that an empty or malformed backlog cannot freeze, that an evolution
              supersedes without mutating the frozen record (refusals included) and chains with
              tamper detection, and that ordering is topological with cycle detection.
How:          In-memory ``BacklogItem`` / ``Backlog`` objects; JSON round trips.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/factory/backlog.py (under test), src/crb/factory/readiness.py (the DoR
              gate over items), src/crb/factory/loop.py (consumes the frozen backlog),
              tests/test_factory_loop.py
Tested by:    tests/test_factory_backlog.py
Touch when:   an item field is added (it is hashed — pin the round trip and that old frozen
              records still verify); an evolution kind is added.
"""

from __future__ import annotations

import json

import pytest

from crb.factory import backlog as bl


def _item(i: str, **kw: object) -> bl.BacklogItem:
    base: dict[str, object] = {
        "id": i,
        "title": f"item {i}",
        "kind": bl.KIND_CODE,
        "capability_class": "bug.fix",
        "registered": "2026-01-01T00:00:00+00:00",
    }
    base.update(kw)
    return bl.BacklogItem(**base)  # type: ignore[arg-type]


# --- items -----------------------------------------------------------------------


def test_item_validation() -> None:
    with pytest.raises(bl.BacklogError):
        _item("bad id!")
    with pytest.raises(bl.BacklogError):
        _item("a", kind="wizard")
    with pytest.raises(bl.BacklogError):
        _item("a", level="L9")
    with pytest.raises(bl.BacklogError):
        _item("a", size_estimate="XXL")
    with pytest.raises(bl.BacklogError):
        _item("a", depends_on=("a",))
    with pytest.raises(bl.BacklogError):
        _item("a", supersedes="a")
    with pytest.raises(bl.BacklogError):
        _item("a", title="   ")


def test_item_round_trip() -> None:
    it = _item(
        "I-1",
        acceptance_criteria=["ac1"],
        structural_facts=["method_path: GET /x"],
        depends_on=[],
        labels={"horizon": "mvp"},
    )
    back = bl.BacklogItem.from_dict(json.loads(json.dumps(it.to_dict())))
    assert back == it
    assert back.acceptance_criteria == ("ac1",)
    assert back.labels == {"horizon": "mvp"}


# --- freeze + hash ----------------------------------------------------------------


def test_freeze_computes_hash_and_verify_holds() -> None:
    b = bl.Backlog(items=(_item("a"), _item("b", depends_on=("a",))), repo="pyrepo")
    assert not b.frozen
    assert b.verify() is False  # unfrozen never verifies
    f = b.freeze(at="2026-01-02T00:00:00+00:00")
    assert f.frozen
    assert f.backlog_hash == bl.backlog_hash(f.items)
    assert f.verify()
    assert f.verify(f.backlog_hash)
    assert not f.verify("0" * 64)
    # idempotent
    assert f.freeze() is f


def test_hash_is_canonical_and_order_sensitive() -> None:
    a, b = _item("a"), _item("b")
    h1 = bl.backlog_hash((a, b))
    h2 = bl.backlog_hash((bl.BacklogItem.from_dict(a.to_dict()), b))
    assert h1 == h2
    assert bl.backlog_hash((b, a)) != h1


def test_tampered_frozen_record_fails_verify() -> None:
    f = bl.Backlog(items=(_item("a"),)).freeze()
    d = f.to_dict()
    d["items"][0]["title"] = "edited after freeze"
    tampered = bl.Backlog.from_dict(d)
    assert tampered.verify() is False
    with pytest.raises(bl.BacklogFrozen):
        tampered.freeze()


def test_cannot_freeze_empty_or_malformed() -> None:
    with pytest.raises(bl.BacklogError):
        bl.Backlog(items=()).freeze()
    with pytest.raises(bl.BacklogError, match="duplicate"):
        bl.Backlog(items=(_item("a"), _item("a")))
    with pytest.raises(bl.BacklogError, match="unknown item"):
        bl.Backlog(items=(_item("a", depends_on=("zz",)),))


# --- evolution -----------------------------------------------------------------------


def test_evolution_supersedes_without_mutating_frozen_record() -> None:
    f = bl.Backlog(items=(_item("a"), _item("b", depends_on=("a",)))).freeze()
    h = f.backlog_hash
    ev = _item("a2", supersedes="a", title="a, corrected")
    g = f.evolve(ev)
    assert g.backlog_hash == h  # frozen hash never changes
    assert g.items == f.items
    assert g.evolutions == (ev,)
    assert g.evolutions_hash and g.verify()
    assert [i.id for i in g.active_items()] == ["b", "a2"]
    assert g.superseded_ids() == frozenset({"a"})
    # the original still exists in the record (all-comers) …
    assert g.get("a") is not None
    # … and dependencies resolve to the latest evolution
    assert [i.id for i in g.ordered()] == ["a2", "b"]


def test_evolution_refusals() -> None:
    b = bl.Backlog(items=(_item("a"),))
    with pytest.raises(bl.BacklogError, match="freeze"):
        b.evolve(_item("x"))
    f = b.freeze()
    with pytest.raises(bl.BacklogFrozen):
        f.evolve(_item("a", title="in-place edit"))
    with pytest.raises(bl.BacklogError, match="unknown"):
        f.evolve(_item("x", supersedes="nope"))
    g = f.evolve(_item("a2", supersedes="a"))
    with pytest.raises(bl.BacklogFrozen, match="already superseded"):
        g.evolve(_item("a3", supersedes="a"))
    g2 = g.evolve(_item("a3", supersedes="a2"))
    assert [i.id for i in g2.active_items()] == ["a3"]


def test_evolutions_chain_detects_tamper_and_round_trips() -> None:
    f = bl.Backlog(items=(_item("a"),)).freeze()
    g = f.evolve(_item("amend", title="pure amendment"))
    d = g.to_dict()
    back = bl.Backlog.from_dict(json.loads(json.dumps(d)))
    assert back.verify()
    d["evolutions"][0]["title"] = "edited"
    assert bl.Backlog.from_dict(d).verify() is False
    with pytest.raises(bl.BacklogError):
        bl.Backlog(items=(_item("a"),), evolutions=(_item("z"),))  # unfrozen with evolutions


def test_ordered_is_topological_and_detects_cycles() -> None:
    f = bl.Backlog(
        items=(_item("c", depends_on=("b",)), _item("b", depends_on=("a",)), _item("a"))
    ).freeze()
    assert [i.id for i in f.ordered()] == ["a", "b", "c"]
    cyc = bl.Backlog(items=(_item("a", depends_on=("b",)), _item("b", depends_on=("a",))))
    with pytest.raises(bl.BacklogError, match="cycle"):
        cyc.ordered()
