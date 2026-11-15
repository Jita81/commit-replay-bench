"""Tests for crb.core.stated and the ``crb.ctxset.v2`` stated-requirement set (ADR-0052).

Navigation
----------
What it is:   Tests for ``crb.core.stated`` (kinds, provenance, the two fixed renderers, the
              item and items digests, the limits, the ``ctx_prov`` stamp) and for the v2 path
              of ``crb.core.ctxset`` (parse, the source-to-schema rule, the item refusals,
              the stated run stamps, the placebo structure rule) and the kind table of
              ``crb.core.context_arm``.
What it does: Pins that an entry's text is rendered by code from its items, never stored; that
              a prose and a checklist set over the same items share an items digest and differ
              in digest; that v1 digests are unchanged; that ``req*`` is v2-only and v2 is
              ``req*``-only; and each new refusal on a minimal fixture.
How:          Hand-built JSON sets over fake task ids; no repository, no model, no docker.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0052-stated-requirement-arms.md, docs/adr/0050-context-set-arms.md
Works with:   src/crb/core/stated.py, src/crb/core/ctxset.py, src/crb/core/context_arm.py
              (the modules under test), tests/test_ctxset.py (the v1 fixtures pinned here)
Tested by:    this file
Touch when:   a kind, provenance value, structure, renderer, limit or the v2 schema changes
              (an ADR amending ADR-0052 first).
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from crb.core import context_arm as arms
from crb.core import ctxset, stated
from crb.core.ctxset import CtxSetRefused
from crb.core.stated import StatedItem
from test_ctxset import _mech_doc, _oracle_doc

T1 = "1" * 40
T2 = "2" * 40
WHEN = "2026-01-01T00:00:00+00:00"
MODEL = "model:some-model-v1@" + "d" * 64


def _item(item_id: str, statement: str, **kw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "item_id": item_id,
        "kind": "rule",
        "statement": statement,
        "provenance": "nowhere",
        "discloses": [],
    }
    out.update(kw)
    return out


def req_doc(structure: str = "prose", **top: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema": ctxset.SCHEMA_V2,
        "source": "req",
        "repo": "demo",
        "method": "items written by a reviewer with sight of the change",
        "structure": structure,
        "drafter": "human:reviewer-01",
        "saw": ["diff", "tests"],
        "entries": [
            {
                "task_id": T1,
                "entry_id": "r-1111",
                "version": "1",
                "produced_at": WHEN,
                "items": [
                    _item(
                        "i01",
                        "An empty name is refused with the error text `name required`",
                        kind="error_text",
                        provenance="tests_only",
                        discloses=["name required"],
                    ),
                    _item("i02", "Existing callers keep working unchanged"),
                ],
            },
            {
                "task_id": T2,
                "entry_id": "r-2222",
                "version": "1",
                "produced_at": WHEN,
                "items": [_item("i01", "The limit stays inclusive", kind="value")],
            },
        ],
    }
    doc.update(top)
    return doc


# -- the kind table ---------------------------------------------------------------------------


def test_every_source_has_one_kind_and_req_is_stated() -> None:
    assert set(arms.CTX_SOURCE_KIND) == set(arms.CTX_SOURCES)
    assert set(arms.CTX_SOURCE_KIND.values()) == set(arms.CTX_KINDS)
    assert arms.ctx_kind("req") == arms.ctx_kind("req-placebo") == arms.CTX_KIND_STATED
    with pytest.raises(ValueError, match="not one of"):
        arms.ctx_kind("ticket")


def test_req_arms_are_hindsight_stated_and_measurement_only() -> None:
    arm = "A0+library@ctx.req.0123456789ab"
    assert arms.is_arm(arm)
    assert arms.ctx_source_of(arm) == "req"
    assert arms.hindsight_arm(arm) and arms.stated_arm(arm) and arms.measurement_only(arm)
    placebo = "A0+library@ctx.req-placebo.0123456789ab"
    assert arms.stated_arm(placebo) and arms.measurement_only(placebo)
    for other in ("A0+library@ctx.oracle.0123456789ab", "A0+library@ctx.mech.0123456789ab"):
        assert not arms.stated_arm(other)
    assert not arms.stated_arm("A0") and not arms.hindsight_arm("A0+library@plain-lib")


def test_ctx_turns_is_not_a_provenance_stamp() -> None:
    assert arms.LABEL_CTX_TURNS not in arms.PROVENANCE_LABELS
    for label in (arms.LABEL_CTX_STATED, arms.LABEL_CTX_ITEMS, arms.LABEL_CTX_REQ_REFUSED):
        assert label in arms.PROVENANCE_LABELS


# -- the renderers ----------------------------------------------------------------------------


ITEMS = (
    StatedItem("b2", "rule", "Second, in id order", "nowhere"),
    StatedItem("a1", "name", "First names `do_it`", "change_detail", ("do_it",)),
)


def test_prose_renders_one_paragraph_in_item_id_order() -> None:
    assert stated.render("prose", ITEMS) == (
        "Stated requirements for this change: First names `do_it`. Second, in id order."
    )


def test_checklist_renders_one_line_per_item_in_item_id_order() -> None:
    assert stated.render("checklist", ITEMS) == (
        "Stated requirements for this change:\n- First names `do_it`\n- Second, in id order"
    )


def test_both_renderers_carry_every_statement_and_no_tag() -> None:
    for structure in stated.STRUCTURES:
        text = stated.render(structure, ITEMS)
        assert text.startswith(stated.HEADER)
        for item in ITEMS:
            assert item.statement in text
            assert item.provenance not in text and f"{item.kind}:" not in text


def test_render_refuses_an_unknown_structure_or_no_items() -> None:
    with pytest.raises(ValueError, match="structure"):
        stated.render("table", ITEMS)
    with pytest.raises(ValueError, match="at least one"):
        stated.render("prose", ())


def test_item_refuses_an_unknown_kind_or_provenance() -> None:
    with pytest.raises(ValueError, match="kind"):
        StatedItem("a", "essay", "x", "nowhere")
    with pytest.raises(ValueError, match="provenance"):
        StatedItem("a", "rule", "x", "somewhere")


def test_item_hash_moves_with_every_field_and_the_task() -> None:
    base = StatedItem("a1", "rule", "Keep it", "nowhere")
    h = stated.item_hash(T1, base)
    assert stated.item_hash(T2, base) != h
    for changed in (
        StatedItem("a2", "rule", "Keep it", "nowhere"),
        StatedItem("a1", "value", "Keep it", "nowhere"),
        StatedItem("a1", "rule", "Keep it!", "nowhere"),
        StatedItem("a1", "rule", "Keep it", "product"),
        StatedItem("a1", "rule", "Keep it", "nowhere", ("it",)),
    ):
        assert stated.item_hash(T1, changed) != h


def test_prov_label_counts_declared_provenance_and_attested_items() -> None:
    assert stated.prov_label(ITEMS) == (
        "product:0,change_detail:1,tests_only:0,nowhere:1;attested:1"
    )
    assert stated.any_tests_only([StatedItem("a", "rule", "x", "tests_only", ("x",))])
    assert not stated.any_tests_only(ITEMS)
    assert stated.PROV_RANK["tests_only"] > stated.PROV_RANK["change_detail"]
    assert stated.PROV_RANK["change_detail"] > stated.PROV_RANK["product"] > 0


def test_length_violation_names_each_limit() -> None:
    many = [StatedItem(f"i{n:02}", "rule", "x", "nowhere") for n in range(stated.MAX_ITEMS + 1)]
    assert "items" in stated.length_violation(many, "x")
    long_item = [StatedItem("a", "rule", "x" * (stated.MAX_STATEMENT_CHARS + 1), "nowhere")]
    assert "characters" in stated.length_violation(long_item, "x")
    assert "entry" in stated.length_violation(ITEMS, "x" * (stated.MAX_ENTRY_CHARS + 1))
    assert stated.length_violation(ITEMS, "short") == ""


# -- the v2 set -------------------------------------------------------------------------------


def test_v1_digests_are_unchanged() -> None:
    """The kind table and the v2 path move no v1 digest (and so no v1 arm name)."""
    assert ctxset.parse(_oracle_doc()).digest == (
        "19618dc98fd925d3d97ff9282aed6e9b41cd5e685bff3bb1a28c857d5e738ece"
    )
    assert ctxset.parse(_mech_doc()).digest == (
        "5fbb92545516613adcdb1d3aec86b99ee16a78a2ee26252c2ea6ab1cd3d45df8"
    )


def test_a_req_set_parses_with_rendered_text_and_round_trips() -> None:
    s = ctxset.parse(req_doc())
    assert s.schema == ctxset.SCHEMA_V2 and s.stated and s.hindsight and not s.mechanical
    assert s.name.startswith("ctx.req.") and s.arm == f"A0+library@{s.name}"
    e = s.entry_for(T1)
    assert e.text == stated.render("prose", e.items) and not e.mechanical
    assert ctxset.canonical_digest(s.to_doc()) == s.digest
    assert "text" not in s.to_doc()["entries"][0]
    assert ctxset.parse(s.to_doc(), name=s.name).digest == s.digest


def test_prose_and_checklist_share_the_items_digest_not_the_set_digest() -> None:
    prose = ctxset.parse(req_doc("prose"))
    checklist = ctxset.parse(req_doc("checklist"))
    assert prose.items_digest == checklist.items_digest != ""
    assert prose.digest != checklist.digest
    assert prose.entry_for(T1).text != checklist.entry_for(T1).text
    assert ctxset.parse(_oracle_doc()).items_digest == ""


def test_items_digest_moves_when_a_statement_moves() -> None:
    doc = req_doc()
    doc["entries"][1]["items"][0]["statement"] = "The limit becomes exclusive"
    assert ctxset.parse(doc).items_digest != ctxset.parse(req_doc()).items_digest


def test_a_req_source_is_refused_as_v1_and_another_source_as_v2() -> None:
    v1_req = _oracle_doc()
    v1_req["source"] = "req"
    with pytest.raises(CtxSetRefused, match="ctxset_schema") as err:
        ctxset.parse(v1_req)
    assert "v2" in err.value.detail
    v2_oracle = req_doc()
    v2_oracle["source"] = "oracle"
    with pytest.raises(CtxSetRefused, match="ctxset_schema"):
        ctxset.parse(v2_oracle)


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda d: d["entries"][0].update(text="free text"), "ctxset_schema"),
        (lambda d: d.update(structure="table"), "ctxset_schema"),
        (lambda d: d.update(drafter="Some Person"), "ctxset_schema"),
        (lambda d: d.update(drafter="some-model-v1@" + "c" * 64), "ctxset_schema"),
        (lambda d: d.update(saw=["tests", "diff"]), "ctxset_schema"),
        (lambda d: d.update(saw=["gold"]), "ctxset_schema"),
        (lambda d: d["entries"][0]["items"].reverse(), "ctxset_schema"),
        (lambda d: d["entries"][0]["items"][0].update(kind="essay"), "ctxset_schema"),
        (lambda d: d["entries"][0]["items"][0].update(provenance="maybe"), "ctxset_schema"),
        (lambda d: d["entries"][0]["items"][0].update(statement="a\nb"), "ctxset_schema"),
        (lambda d: d["entries"][0]["items"][0].update(extra=1), "ctxset_schema"),
        (lambda d: d["entries"][0].update(items=[]), "ctxset_schema"),
        (lambda d: d.update(matched_to="e" * 64), "ctxset_schema"),
        (
            lambda d: d["entries"][0]["items"][0].update(discloses=["not said"]),
            "ctxset_items_undelivered",
        ),
        (
            lambda d: d["entries"][0]["items"][1].update(statement="x" * 241),
            "ctxset_items_length",
        ),
        (lambda d: d["entries"].reverse(), "ctxset_schema"),
    ],
)
def test_v2_refusals(mutate: Any, reason: str) -> None:
    doc = copy.deepcopy(req_doc())
    mutate(doc)
    with pytest.raises(CtxSetRefused) as err:
        ctxset.parse(doc)
    assert err.value.reason == reason


def test_too_many_items_is_a_length_refusal() -> None:
    doc = req_doc()
    doc["entries"][1]["items"] = [_item(f"i{n:02}", "Keep it") for n in range(13)]
    with pytest.raises(CtxSetRefused) as err:
        ctxset.parse(doc)
    assert err.value.reason == "ctxset_items_length"


def test_a_model_drafter_is_accepted() -> None:
    assert ctxset.parse(req_doc(drafter=MODEL)).drafter == MODEL


def test_stated_run_stamps() -> None:
    s = ctxset.parse(req_doc("checklist"))
    stamps = ctxset.run_stamps(s, "entries", {T1: "1", T2: "0"})
    one = stamps[T1]
    assert one["ctx_source"] == "req" and one["ctx_ceiling"] == "1"
    assert one["ctx_stated"] == "1" and one["ctx_items"] == s.items_digest
    assert one["ctx_structure"] == "checklist" and one["ctx_author_saw"] == "diff,tests"
    assert one["ctx_prov"] == "product:0,change_detail:0,tests_only:1,nowhere:1;attested:1"
    assert one["ctx_req_drafter"] == "human:reviewer-01"
    assert "ctx_drafter" not in one
    control = ctxset.run_stamps(s, "control", {T1: "1", T2: "0"})[T1]
    assert not set(control) & {"ctx_stated", "ctx_items", "ctx_prov", "ctx_ceiling"}


def _placebo_doc(treatment: ctxset.CtxSet, structure: str = "prose") -> dict[str, Any]:
    doc = req_doc(structure, source="req-placebo", matched_to=treatment.digest)
    doc["entries"][0]["items"] = [
        _item("i01", "Neighbouring words of no bearing here, roughly matched in size"),
        _item("i02", "Some more unrelated prose"),
    ]
    doc["entries"][1]["items"] = [_item("i01", "Nothing to do with it")]
    return doc


def test_a_req_placebo_must_share_its_treatment_structure() -> None:
    treatment = ctxset.parse(req_doc())
    ctxset.verify_placebo(treatment, ctxset.parse(_placebo_doc(treatment)))
    with pytest.raises(CtxSetRefused) as err:
        ctxset.verify_placebo(treatment, ctxset.parse(_placebo_doc(treatment, "checklist")))
    assert err.value.reason == "ctxset_placebo_unmatched"
