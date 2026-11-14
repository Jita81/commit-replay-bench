"""Tests for crb.core.ctxset — the context-set record, its digest and its checks (ADR-0050).

Navigation
----------
What it is:   Tests for ``crb.core.ctxset``: the set record, its canonical digest and name,
              the store-time and run-time checks, the ``anchor.v1`` gap rule and run stamps.
What it does: Pins a digest stable across key order and moved by any entry change; a name of
              ``ctx.<source>.<digest[:12]>``; each named refusal (``ctxset_schema``,
              ``ctxset_digest``, ``ctxset_coverage``, ``ctxset_repo``,
              ``ctxset_mechanical``, ``ctxset_placebo_unmatched``,
              ``ctxset_placebo_overlap``) on a minimal fixture; the gap label read through
              ``tree_has`` only; and the per-task stamps for the entries and control roles.
How:          Hand-built JSON sets over fake task ids; the parent tree is a callable over a
              fixed set of identifiers; no repository, no model, no docker.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0050-context-set-arms.md
Works with:   src/crb/core/ctxset.py (the module under test), src/crb/core/context_arm.py
              (the reserved ``ctx.`` names and labels), docs/adr/0050-context-set-arms.md
              (the decision whose refusals are pinned), src/crb/server/routes/ctxsets.py
              (the store-time caller of ``parse`` and the verifiers)
Tested by:    this file
Touch when:   never for a new repository; the set schema, a refusal, the placebo tolerance or
              the gap rule changes (an ADR amending ADR-0050 first).
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from crb.core import context_arm as arms
from crb.core import ctxset
from crb.core.ctxset import CtxSetRefused

T1 = "1" * 40
T2 = "2" * 40
P1 = "a" * 40
P2 = "b" * 40
DRAFTER = "some-model-v1@" + "c" * 64
WHEN = "2026-01-01T00:00:00+00:00"


def _entry(task_id: str, text: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "task_id": task_id,
        "entry_id": f"e-{task_id[:4]}",
        "version": "1",
        "text": text,
        "produced_at": WHEN,
        "mechanical": False,
    }
    out.update(extra)
    return out


def _oracle_doc() -> dict[str, Any]:
    return {
        "schema": ctxset.SCHEMA,
        "source": "oracle",
        "repo": "demo",
        "method": "written from the merged change",
        "entries": [
            _entry(T1, "Call `parse_config` before `load_plugins` in cmd/root.go."),
            _entry(T2, "The retry_count field moves into ClientOptions."),
        ],
    }


def _mech_doc() -> dict[str, Any]:
    return {
        "schema": ctxset.SCHEMA,
        "source": "mech",
        "repo": "demo",
        "method": "drafted at the parent commit",
        "drafter": DRAFTER,
        "entries": [
            _entry(T1, "The config loader lives in cmd/root.go.", mechanical=True, source_rev=P1),
            _entry(T2, "Options are built in ClientOptions.", mechanical=True, source_rev=P2),
        ],
    }


def _placebo_doc(treatment: ctxset.CtxSet, texts: dict[str, str]) -> dict[str, Any]:
    return {
        "schema": ctxset.SCHEMA,
        "source": "oracle-placebo",
        "repo": "demo",
        "method": "length-matched unrelated prose",
        "matched_to": treatment.digest,
        "entries": [_entry(tid, texts[tid]) for tid in treatment.task_ids],
    }


def _same_length(text: str, filler: str) -> str:
    return (filler * (len(text) // len(filler) + 1))[: len(text)]


@dataclass(frozen=True)
class _Task:
    task_id: str
    repo: str = "demo"
    gold_clean: bool | None = True
    labels: dict[str, str] = field(default_factory=dict)


def _refused(reason: str) -> Any:
    return pytest.raises(CtxSetRefused, match=f"^{reason}:")


# --- digest and name -----------------------------------------------------------------------


def test_the_digest_is_stable_across_key_order() -> None:
    doc = _oracle_doc()
    reordered = {k: doc[k] for k in reversed(list(doc))}
    reordered["entries"] = [{k: e[k] for k in reversed(list(e))} for e in doc["entries"]]
    assert ctxset.canonical_digest(doc) == ctxset.canonical_digest(reordered)
    assert ctxset.parse(doc).digest == ctxset.parse(json.dumps(reordered)).digest


def test_the_digest_moves_with_any_change_to_an_entry() -> None:
    doc = _oracle_doc()
    changed = copy.deepcopy(doc)
    changed["entries"][0]["text"] += " "
    assert ctxset.parse(doc).digest != ctxset.parse(changed).digest


def test_the_name_uses_the_first_twelve_hex_of_the_digest_and_is_a_ctx_arm() -> None:
    s = ctxset.parse(_oracle_doc())
    assert s.name == f"ctx.oracle.{s.digest[:12]}"
    assert arms.CTX_NAME_RE.match(s.name)
    assert s.arm == f"A0+library@{s.name}"
    assert arms.ctx_set_name(s.arm) == s.name
    assert arms.hindsight_arm(s.arm) and s.hindsight and not s.mechanical
    assert "name" not in s.to_doc()
    assert ctxset.canonical_digest(s.to_doc()) == s.digest


def test_a_matching_name_parses_and_a_stale_one_is_ctxset_digest() -> None:
    s = ctxset.parse(_oracle_doc())
    assert ctxset.parse(_oracle_doc(), name=s.name) == s
    with _refused("ctxset_digest"):
        ctxset.parse(_oracle_doc(), name="ctx.oracle.000000000000")


# --- ctxset_schema -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(schema="crb.ctxset.v2"),
        lambda d: d.update(source="ideas"),
        lambda d: d.pop("method"),
        lambda d: d.update(extra="x"),
        lambda d: d["entries"][0].update(extra="x"),
        lambda d: d["entries"][0].update(mechanical="no"),
        lambda d: d["entries"][0].update(produced_at="yesterday"),
        lambda d: d["entries"][0].update(produced_at="2026-01-01T00:00:00+02:00"),
        lambda d: d["entries"][0].update(text="  "),
        lambda d: d["entries"].reverse(),
        lambda d: d["entries"][0].update(source_rev=P1),
        lambda d: d.update(drafter=DRAFTER),
        lambda d: d.update(matched_to="f" * 64),
    ],
)
def test_a_malformed_set_is_ctxset_schema(mutate: Any) -> None:
    doc = _oracle_doc()
    mutate(doc)
    with _refused("ctxset_schema"):
        ctxset.parse(doc)


def test_not_json_is_ctxset_schema() -> None:
    with _refused("ctxset_schema"):
        ctxset.parse("{not json")
    with _refused("ctxset_schema"):
        ctxset.parse([1, 2])


# --- ctxset_coverage -----------------------------------------------------------------------


def test_an_empty_set_and_a_task_twice_are_ctxset_coverage() -> None:
    empty = _oracle_doc()
    empty["entries"] = []
    with _refused("ctxset_coverage"):
        ctxset.parse(empty)
    twice = _oracle_doc()
    twice["entries"][1]["task_id"] = T1
    with _refused("ctxset_coverage"):
        ctxset.parse(twice)


def test_coverage_holds_for_gold_clean_tasks_of_distinct_changes() -> None:
    s = ctxset.parse(_oracle_doc())
    ctxset.verify_coverage(s, [_Task(T1), _Task(T2), _Task("3" * 40)], repo="demo")


def test_two_tasks_of_one_change_are_ctxset_coverage() -> None:
    s = ctxset.parse(_oracle_doc())
    tasks = [_Task(T1, labels={"change_id": "c-1"}), _Task(T2, labels={"change_id": "c-1"})]
    with _refused("ctxset_coverage"):
        ctxset.verify_coverage(s, tasks)


def test_an_unknown_or_unproven_task_is_ctxset_coverage() -> None:
    s = ctxset.parse(_oracle_doc())
    with _refused("ctxset_coverage"):
        ctxset.verify_coverage(s, [_Task(T1)])
    with _refused("ctxset_coverage"):
        ctxset.verify_coverage(s, [_Task(T1), _Task(T2, gold_clean=None)])
    with _refused("ctxset_coverage"):
        ctxset.verify_coverage(s, [_Task(T1), _Task(T2, repo="other")])


def test_a_set_of_another_repository_is_ctxset_repo() -> None:
    s = ctxset.parse(_oracle_doc())
    with _refused("ctxset_repo"):
        ctxset.verify_coverage(s, [_Task(T1), _Task(T2)], repo="other")


# --- ctxset_mechanical ---------------------------------------------------------------------


def test_a_mechanical_set_parses_and_stamps_its_boundary() -> None:
    s = ctxset.parse(_mech_doc())
    assert s.mechanical and not s.hindsight and not s.placebo
    assert s.drafter == DRAFTER
    assert [e.source_rev for e in s.entries] == [P1, P2]
    assert not arms.hindsight_arm(s.arm)
    ctxset.verify_source_revs(s, {T1: P1, T2: P2})


def test_a_mechanical_set_without_its_drafter_is_ctxset_mechanical() -> None:
    doc = _mech_doc()
    doc.pop("drafter")
    with _refused("ctxset_mechanical"):
        ctxset.parse(doc)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e.update(mechanical=False),
        lambda e: e.pop("source_rev"),
        lambda e: e.update(source_rev=""),
    ],
)
def test_a_mechanical_entry_without_its_stamp_is_ctxset_mechanical(mutate: Any) -> None:
    doc = _mech_doc()
    mutate(doc["entries"][0])
    with _refused("ctxset_mechanical"):
        ctxset.parse(doc)


def test_a_wrong_source_rev_is_ctxset_mechanical() -> None:
    s = ctxset.parse(_mech_doc())
    with _refused("ctxset_mechanical"):
        ctxset.verify_source_revs(s, {T1: P2, T2: P2})
    with _refused("ctxset_mechanical"):
        ctxset.verify_source_revs(s, {T1: P1})


def test_a_hindsight_entry_stamped_mechanical_is_ctxset_mechanical() -> None:
    doc = _oracle_doc()
    doc["entries"][0]["mechanical"] = True
    with _refused("ctxset_mechanical"):
        ctxset.parse(doc)


def test_a_hindsight_set_has_no_source_rev_check() -> None:
    ctxset.verify_source_revs(ctxset.parse(_oracle_doc()), {})


# --- the placebo ---------------------------------------------------------------------------


def _treatment_and_placebo_texts() -> tuple[ctxset.CtxSet, dict[str, str]]:
    t = ctxset.parse(_oracle_doc())
    texts = {
        e.task_id: _same_length(e.text, "Weather notes about rivers and hills. ") for e in t.entries
    }
    return t, texts


def test_a_matched_placebo_verifies() -> None:
    t, texts = _treatment_and_placebo_texts()
    p = ctxset.parse(_placebo_doc(t, texts))
    assert p.placebo and p.hindsight and p.name.startswith("ctx.oracle-placebo.")
    ctxset.verify_placebo(t, p)


def test_a_placebo_naming_no_treatment_is_ctxset_placebo_unmatched() -> None:
    t, texts = _treatment_and_placebo_texts()
    doc = _placebo_doc(t, texts)
    doc.pop("matched_to")
    with _refused("ctxset_placebo_unmatched"):
        ctxset.parse(doc)
    doc["matched_to"] = "f" * 64
    with _refused("ctxset_placebo_unmatched"):
        ctxset.verify_placebo(t, ctxset.parse(doc))


def test_a_placebo_outside_the_length_tolerance_is_ctxset_placebo_unmatched() -> None:
    t, texts = _treatment_and_placebo_texts()
    texts[T1] = texts[T1] + "x" * (ctxset.placebo_tolerance(len(texts[T1])) + 1)
    with _refused("ctxset_placebo_unmatched"):
        ctxset.verify_placebo(t, ctxset.parse(_placebo_doc(t, texts)))


def test_the_tolerance_is_sixteen_characters_or_two_percent() -> None:
    assert ctxset.placebo_tolerance(100) == 16
    assert ctxset.placebo_tolerance(10_000) == 200


def test_a_placebo_over_other_tasks_is_ctxset_placebo_unmatched() -> None:
    t, texts = _treatment_and_placebo_texts()
    doc = _placebo_doc(t, texts)
    doc["entries"][1]["task_id"] = "3" * 40
    with _refused("ctxset_placebo_unmatched"):
        ctxset.verify_placebo(t, ctxset.parse(doc))


def test_a_placebo_sharing_an_identifier_is_ctxset_placebo_overlap() -> None:
    t, texts = _treatment_and_placebo_texts()
    leak = " see cmd/root.go"
    texts[T1] = texts[T1][: -len(leak)] + leak
    with _refused("ctxset_placebo_overlap"):
        ctxset.verify_placebo(t, ctxset.parse(_placebo_doc(t, texts)))


def test_a_shared_stopword_is_not_an_overlap() -> None:
    doc = _oracle_doc()
    doc["entries"][0]["text"] += " e.g"
    t = ctxset.parse(doc)
    texts = {
        e.task_id: _same_length(e.text, "Weather notes about rivers and hills. ") for e in t.entries
    }
    texts[T1] = texts[T1][:-4] + " e.g"
    ctxset.verify_placebo(t, ctxset.parse(_placebo_doc(t, texts)))


# --- the gap label (anchor.v1) -------------------------------------------------------------


def test_identifier_tokens_are_backticks_and_code_shaped_words() -> None:
    toks = ctxset.identifier_tokens("Fix `run()` in the parseArgs path; see pkg/cli and a_b. ok")
    assert {"run", "parseArgs", "pkg/cli", "a_b"} <= toks
    assert "Fix" not in toks and "ok" not in toks and "the" not in toks


def test_the_gap_is_one_when_no_identifier_resolves_in_the_tree() -> None:
    asked: list[str] = []

    def tree_has(tok: str) -> bool:
        asked.append(tok)
        return False

    assert ctxset.ctx_gap_anchor("Make `fooBar` honour the_limit.", tree_has) == "1"
    assert asked == sorted(asked) and set(asked) == {"fooBar", "the_limit"}


def test_the_gap_is_zero_when_an_identifier_resolves_in_the_tree() -> None:
    assert (
        ctxset.ctx_gap_anchor("Make `fooBar` honour the_limit.", {"the_limit"}.__contains__) == "0"
    )


def test_a_ticket_naming_nothing_is_a_gap_and_asks_the_tree_nothing() -> None:
    def tree_has(tok: str) -> bool:
        raise AssertionError("no identifier to ask about")

    assert ctxset.ctx_gap_anchor("It should be faster when busy.", tree_has) == "1"


def test_the_gap_rule_is_named() -> None:
    assert ctxset.GAP_RULE == "anchor.v1"


# --- the run stamps ------------------------------------------------------------------------


def test_entry_stamps_carry_the_digest_source_gap_and_zero_counts() -> None:
    s = ctxset.parse(_oracle_doc())
    stamps = ctxset.run_stamps(s, "entries", {T1: "1", T2: "0"})
    assert set(stamps) == {T1, T2}
    assert stamps[T1] == {
        "ctx_set": s.digest,
        "ctx_source": "oracle",
        "ctx_gap": "1",
        "ctx_gap_rule": "anchor.v1",
        "ctx_delivered": "0",
        "ctx_chars": "0",
        "ctx_ceiling": "1",
    }
    assert set(stamps[T1]) <= set(arms.PROVENANCE_LABELS)


def test_a_mechanical_set_stamps_its_drafter_and_no_ceiling() -> None:
    s = ctxset.parse(_mech_doc())
    stamps = ctxset.run_stamps(s, "entries", {T1: "0", T2: "0"})[T1]
    assert stamps["ctx_drafter"] == DRAFTER and "ctx_ceiling" not in stamps


def test_control_stamps_name_the_set_and_deliver_nothing() -> None:
    s = ctxset.parse(_oracle_doc())
    stamps = ctxset.run_stamps(s, "control", {T1: "1", T2: "0"})[T2]
    assert stamps == {
        "ctx_set": s.digest,
        "ctx_source": "control",
        "ctx_gap": "0",
        "ctx_gap_rule": "anchor.v1",
    }


def test_stamps_refuse_a_missing_gap_or_an_unknown_role() -> None:
    s = ctxset.parse(_oracle_doc())
    with pytest.raises(ValueError, match="ctx_gap"):
        ctxset.run_stamps(s, "entries", {T1: "1"})
    with pytest.raises(ValueError, match="role"):
        ctxset.run_stamps(s, "treatment", {T1: "1", T2: "1"})


def test_every_refusal_reason_is_named_and_an_unknown_one_is_refused() -> None:
    assert len(set(ctxset.REASONS)) == len(ctxset.REASONS) == 9
    assert all(r.startswith("ctxset_") for r in ctxset.REASONS)
    with pytest.raises(ValueError, match="unknown"):
        CtxSetRefused("ctxset_other", "x")
