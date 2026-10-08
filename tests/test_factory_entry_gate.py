"""The entry gate and the licence of the delivered change (ADR-0026 item 8, ADR-0025 item 12).

Navigation
----------
What it is:   The suite for G-933 (``product.truth.207``, intake ``recovery.23``,
              manufacture ``non-goals.12``) and G-975 (``manufacture-and-deliver.truth.16``,
              C4): a ticket is built only on its cell's proven context standard, and a pull
              request opens only when the delivered change's own cell licenses it.
What it does: Pins, on the real loop over the fixture repository, that an item in a cell
              with no proven standard stops before any spend whether or not delivery is on;
              that a ticket missing what its standard arm needs stops ``needs_context``
              naming it; that an ``S3`` ceiling admits only an approver's calibration build,
              which is evented, never opens a pull request and is claimed by one run on the
              chain before any spend (two interleaved runs build once — P-298); that the
              builder gets exactly
              the standard arm's context (a person's test on an ``S1`` cell is held out); the
              size rule (the more demanding of two cells until the points-to-churn agreement
              passes; ``L`` stops ``granularize``; no points is ``unsized`` and goes to a
              person); the sign-off clause and the override that lifts only it — for every
              other stop the pure gate makes, the override changes nothing; and the licence
              keyed on the building rung's builder and model, before the build
              (``not_licensed``, $0) and on the measured size after it
              (``size_exceeds_licence``), a line shaped like a diff header included (P-294).
How:          The loop rig of ``tests/test_factory_loop.py`` with the gate's readers replaced
              per test; ``decide_entry`` directly for the pure size-rule cases.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md
Works with:   src/crb/factory/standard.py (the gate), src/crb/factory/loop.py (where it runs),
              src/crb/intake/draft.py (``unsized``)
Tested by:    tests/test_factory_entry_gate.py
Touch when:   never for a new repository; a stop is added to the gate; the operator fixes ADR-0026
              item 8's size value.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from crb.builders.brief import (
    ACCEPTANCE_HELD_OUT,
    ACCEPTANCE_NONE,
    ARM_S2,
    LABEL_ACCEPTANCE,
    counts_as_s2_first_attempt,
)
from crb.factory import evidence as fe
from crb.factory import loop as fl
from crb.factory.standard import (
    OVERRIDABLE,
    STOP_GRANULARIZE,
    STOP_NEEDS_CONTEXT,
    STOP_NO_PROVEN_STANDARD,
    STOP_UNSIGNED_CELL,
    STOP_UNSIZED,
    Calibration,
    CellRef,
    Readers,
    Standard,
    decide_entry,
)
from crb.intake.draft import size_for
from fixtures import pyrepo as pr
from test_factory_build import (
    MULTIPLY_DEF,
    TEST_MULTIPLY,
    TEST_MULTIPLY_SRC,
    authored_multiply,
    multiply_item,
)
from test_factory_loop import FakeTestAuthor, MultiBuilder, _creds, _rig

StandardFn = Callable[[CellRef], "Standard | None"]
AUTHOR_TEST = "tests/test_multiply_by_author.py"


def _sub(tmp_path: Path, name: str) -> Path:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _readers(fn: StandardFn, *, agreement: bool = False) -> Readers:
    return Readers(standard_for=fn, agreement_passed=agreement)


def _none(cell: CellRef) -> Standard | None:
    return None


def _s1(cell: CellRef) -> Standard | None:
    return Standard("S1@t1", signed=True)


def _author() -> FakeTestAuthor:
    return FakeTestAuthor(tests={"I-1": (AUTHOR_TEST, TEST_MULTIPLY_SRC)})


def _not_built(rig: object) -> None:
    assert rig.builder.calls == 0  # type: ignore[attr-defined]
    assert rig.author.calls == []  # type: ignore[attr-defined]
    assert list(rig.ledger.rows()) == []  # type: ignore[attr-defined]


# --- no proven standard, missing context --------------------------------------------------


def test_a_ticket_in_a_cell_with_no_proven_standard_stops_before_any_spend_with_delivery_off(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    rig = _rig(pyrepo, tmp_path, readers=_readers(_none), deliver=False)
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_NO_PROVEN_STANDARD and not out.builds
    _not_built(rig)
    assert rig.kinds("I-1") == [
        fe.EV_READINESS,
        fe.EV_ENTRY_REFUSED,
        fe.EV_ROUTE,
        fe.EV_ITEM_OUTCOME,
    ]
    refused = rig.evidence.events_for("I-1", fe.EV_ENTRY_REFUSED)[0].payload
    assert refused["code"] == STOP_NO_PROVEN_STANDARD and refused["reason_code"] == "none"
    assert "not built" in refused["reason"] and "calibration build" in refused["reason"]
    # the size rule read two cells: the estimate and the next larger one
    assert [c["size"] for c in refused["entry"]["cells"]] == ["XS", "S"]


def test_a_ticket_missing_its_standards_slots_stops_needs_context(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """S1 needs the structural facts the test author reads; S2 needs a person's failing
    test. A ticket without them stops before any spend, naming what to attach."""
    rig = _rig(pyrepo, tmp_path, readers=_readers(_s1), author=_author())
    thin = multiply_item(structural_facts=("reproduction: `from calc import multiply` fails",))
    out = rig.loop().run_item(thin)
    assert out.status == fl.STATUS_NEEDS_CONTEXT
    _not_built(rig)
    refused = rig.evidence.events_for("I-1", fe.EV_ENTRY_REFUSED)[0].payload
    assert refused["code"] == STOP_NEEDS_CONTEXT and refused["needs"] == ["expected_behaviour"]

    rig2 = _rig(
        pyrepo, _sub(tmp_path, "s2"), readers=_readers(lambda c: Standard(ARM_S2, signed=True))
    )
    out2 = rig2.loop().run_item(multiply_item())  # no person's test attached
    assert out2.status == fl.STATUS_NEEDS_CONTEXT
    refused2 = rig2.evidence.events_for("I-1", fe.EV_ENTRY_REFUSED)[0].payload
    assert (
        refused2["needs"] == ["a failing test"]
        and "failing test a person wrote" in (refused2["reason"])
    )


# --- ceilings and calibration builds ----------------------------------------------------


def test_an_s3_ceiling_admits_only_a_calibration_build(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    rig = _rig(pyrepo, tmp_path, readers=_readers(lambda c: Standard("S3")))
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_NO_PROVEN_STANDARD
    refused = rig.evidence.events_for("I-1", fe.EV_ENTRY_REFUSED)[0].payload
    assert refused["reason_code"] == "ceiling" and "ceiling" in refused["reason"]
    _not_built(rig)

    rig.evidence.record_calibration("I-1", approver="approver:ada", reason="measure the arm")
    cal = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert cal.status == fl.STATUS_CALIBRATION_BUILD and cal.builds
    (row,) = list(rig.ledger.rows())
    # a person's test on the ticket: the calibration build is an S2 row, stamped as one
    assert row.labels["context_arm"] == ARM_S2 and row.labels["calibration"] == "true"


def test_a_calibration_build_never_opens_a_pull_request(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    """The fake forge sees no call; the event names the approver; the grant funds one run."""
    rig = _rig(pyrepo, tmp_path, readers=_readers(_none), deliver=True, creds=_creds())
    rig.evidence.record_calibration("I-1", approver="approver:ada", reason="first reading")
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_CALIBRATION_BUILD and out.final_verdict is not None
    assert out.final_verdict.accepted and out.delivery is None
    assert not rig.pushes and not rig.prs
    (funded,) = rig.evidence.events_for("I-1", fe.EV_CALIBRATION_FUNDED)
    assert funded.payload["approver"] == "approver:ada"
    refused = rig.evidence.events_for("I-1", fe.EV_DELIVERY_REFUSED)[-1].payload
    assert refused["reason_code"] == "calibration_build"
    assert refused["calibration_by"] == "approver:ada"
    outcome = rig.evidence.events_for("I-1", fe.EV_ITEM_OUTCOME)[-1].payload
    assert outcome["calibration_event"] == funded.event_id
    # spent: the next run meets the gate again
    again = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert again.status == fl.STATUS_NO_PROVEN_STANDARD and len(list(rig.ledger.rows())) == 1


def test_a_grant_is_claimed_once_on_either_store(tmp_path: Path) -> None:
    """The claim is a conditional append — the check and the write under the store's one
    lock — on the in-memory store and on the JSONL file both writers share (P-298)."""
    for store in (fe.MemoryFactoryStore(), fe.JsonlFactoryStore(tmp_path / "ev.jsonl")):
        ev = fe.FactoryEvidence(store, actor="tester", repo="pyrepo")
        grant = ev.record_calibration("I-1", approver="approver:ada", reason="measure")
        first = ev.claim_calibration("I-1", grant.event_id, run_id="run-a")
        assert first is not None and first.payload == {"grant": grant.event_id, "run_id": "run-a"}
        assert ev.claim_calibration("I-1", grant.event_id, run_id="run-b") is None
        assert fe.spent_grants(ev.events()) == {grant.event_id}
        assert ev.verify() == 2


def test_a_second_grant_while_one_waits_is_refused_under_the_stores_lock(tmp_path: Path) -> None:
    """P-730: two approvers' POSTs could both read "no grant waits" and both append one.
    The check is now the store's conditional append, read and write under one lock, on
    either store: a grant while the item's newest grant waits is refused (``None``); once a
    run claims it the item may be funded again; another item is not affected."""
    for store in (fe.MemoryFactoryStore(), fe.JsonlFactoryStore(tmp_path / "ev.jsonl")):
        ev = fe.FactoryEvidence(store, actor="tester", repo="pyrepo")
        first = ev.record_calibration("I-1", approver="approver:ada", reason="measure")
        assert first is not None
        assert ev.record_calibration("I-1", approver="approver:bo", reason="again") is None
        assert ev.record_calibration("I-2", approver="approver:bo", reason="other") is not None
        assert ev.claim_calibration("I-1", first.event_id, run_id="run-a") is not None
        assert ev.record_calibration("I-1", approver="approver:bo", reason="after") is not None
        assert len(ev.events_for("I-1", fe.EV_CALIBRATION_FUNDED)) == 2


class _StartsAnotherRun(MultiBuilder):
    """A builder that, during its first build, runs ``other`` — a second factory run on the
    same repository that starts while the first is still building (a second worker)."""

    other: Callable[[], object] | None = None
    seen: list[object]

    def build(self, workspace: Any, brief: Any, budget: Any, *, on_event: Any = None) -> Any:
        if self.other is not None:
            run, self.other = self.other, None
            self.seen.append(run())
        return super().build(workspace, brief, budget, on_event=on_event)


def test_one_grant_funds_one_build_when_two_runs_interleave(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """P-298: the grant counted as spent only when a run's outcome was written, so a second
    run that started while the first was building read the same grant as unspent and built
    too — one approver's grant, two paid builds. The grant is claimed on the chain, under
    the store's lock, before any spend: the second run finds it claimed and stops at the
    gate. A second grant recorded at once (two approvers' POSTs racing) is refused at the
    store (P-730), and one build is funded either way."""
    builder = _StartsAnotherRun()
    builder.seen = []
    a = _rig(pyrepo, _sub(tmp_path, "a"), readers=_readers(_none), builder=builder)
    b = _rig(pyrepo, _sub(tmp_path, "b"), readers=_readers(_none), evidence=a.evidence)
    a.evidence.record_calibration("I-1", approver="approver:ada", reason="measure the arm")
    a.evidence.record_calibration("I-1", approver="approver:bo", reason="measure it too")
    builder.other = lambda: b.loop().run_item(multiply_item(), authored=authored_multiply())
    first = a.loop().run_item(multiply_item(), authored=authored_multiply())
    (second,) = builder.seen
    assert first.status == fl.STATUS_CALIBRATION_BUILD
    assert second.status == fl.STATUS_NO_PROVEN_STANDARD  # type: ignore[attr-defined]
    assert b.builder.calls == 0 and len(list(a.ledger.rows()) + list(b.ledger.rows())) == 1
    (claim,) = a.evidence.events_for("I-1", fe.EV_CALIBRATION_CLAIMED)
    newest = a.evidence.events_for("I-1", fe.EV_CALIBRATION_FUNDED)[-1]
    assert claim.payload["grant"] == newest.event_id and claim.payload["run_id"] == "run-1"
    # the claim spent it: the next run meets the gate again
    assert a.loop().run_item(multiply_item()).status == fl.STATUS_NO_PROVEN_STANDARD


# --- the builder gets exactly the standard arm's context --------------------------------


def test_the_builder_gets_exactly_the_standard_arms_context(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """On an S1 cell the builder builds against the test author's test; the person's test
    attached to the ticket is held out, never in the brief. On an S2 cell the person's test
    is the oracle. The row names the arm."""
    builder = MultiBuilder()
    rig = _rig(pyrepo, tmp_path, readers=_readers(_s1), author=_author(), builder=builder)
    person = authored_multiply()
    out = rig.loop().run_item(multiply_item(), authored=person)
    assert out.status == fl.STATUS_ACCEPTED
    (brief,) = builder.briefs
    assert brief.test_files == (AUTHOR_TEST,) and person.path not in brief.test_files
    assert person.path not in brief.message
    held = [
        e.payload
        for e in rig.evidence.events_for("I-1", fe.EV_ROUTE)
        if e.payload.get("held_out_test")
    ]
    assert held and held[0]["held_out_sha256"] == person.sha256
    assert next(iter(rig.ledger.rows())).labels["context_arm"] == "S1@t1"

    builder2 = MultiBuilder()
    rig2 = _rig(
        pyrepo,
        _sub(tmp_path, "s2"),
        readers=_readers(lambda c: Standard(ARM_S2, signed=True)),
        builder=builder2,
    )
    out2 = rig2.loop().run_item(multiply_item(), authored=person)
    assert out2.status == fl.STATUS_ACCEPTED
    assert builder2.briefs[0].test_files == (person.path,)
    assert next(iter(rig2.ledger.rows())).labels["context_arm"] == ARM_S2


# --- the size rule ------------------------------------------------------------------------


def test_an_unchecked_point_estimate_applies_the_more_demanding_of_two_cells() -> None:
    def gate(fn: StandardFn, size: str = "XS", *, agreement: bool = False) -> object:
        return decide_entry(
            capability_class="bug.fix",
            size=size,
            standard_for=fn,
            agreement_passed=agreement,
            missing_slots=(),
            person_test=False,
        )

    by_size: dict[str, Standard | None] = {"XS": Standard("S1@t1"), "S": None}
    stopped = gate(lambda c: by_size[c.size])
    assert stopped.code == STOP_NO_PROVEN_STANDARD  # type: ignore[attr-defined]
    assert "bug.fix S cell" in stopped.reason  # type: ignore[attr-defined]
    by_size = {"XS": Standard("S1@t1"), "S": Standard(ARM_S2)}
    s2 = gate(lambda c: by_size[c.size])
    assert s2.code == STOP_NEEDS_CONTEXT and s2.needs == ("a failing test",)  # type: ignore[attr-defined]
    # once the agreement passes, the named cell alone
    assert gate(lambda c: {"XS": Standard("S1@t1"), "S": None}[c.size], agreement=True).enters  # type: ignore[attr-defined]


def test_an_item_without_points_is_unsized_and_routes_human(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    size, why = size_for(None)
    assert size == "unsized" and "no estimate" in why
    rig = _rig(pyrepo, tmp_path)
    out = rig.loop().run_item(multiply_item(size_estimate="unsized"), authored=authored_multiply())
    assert out.status == fl.STATUS_ROUTED_HUMAN
    _not_built(rig)
    refused = rig.evidence.events_for("I-1", fe.EV_ENTRY_REFUSED)[0].payload
    assert refused["code"] == "unsized" and "size" in refused["reason"]


def test_an_item_pointed_l_stops_granularize_until_the_agreement_passes(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    before = decide_entry(
        capability_class="bug.fix",
        size="L",
        standard_for=_s1,
        agreement_passed=False,
        missing_slots=(),
        person_test=False,
    )
    assert before.code == STOP_GRANULARIZE and "L and XL" in before.reason
    after = decide_entry(
        capability_class="bug.fix",
        size="L",
        standard_for=_s1,
        agreement_passed=True,
        missing_slots=(),
        person_test=False,
    )
    assert after.enters
    rig = _rig(pyrepo, tmp_path, readers=_readers(_s1))
    out = rig.loop().run_item(multiply_item(size_estimate="L"), authored=authored_multiply())
    assert out.status == fl.STATUS_GRANULARIZE
    _not_built(rig)


# --- the sign-off clause and the override ------------------------------------------------


def _unsigned(cell: CellRef) -> Standard | None:
    return Standard(ARM_S2, signed=False)


def test_an_unsigned_cell_stops_before_any_spend(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    rig = _rig(pyrepo, tmp_path, readers=_readers(_unsigned), require_signed_cell=True)
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_UNSIGNED_CELL
    _not_built(rig)
    reason = rig.evidence.events_for("I-1", fe.EV_ENTRY_REFUSED)[0].payload["reason"]
    assert "not built" in reason and "lifts only the sign-off" in reason


def test_deliver_override_lifts_only_a_missing_sign_off_never_a_missing_standard(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    # 1. the sign-off clause: lifted, by name, for this run
    rig = _rig(
        pyrepo,
        _sub(tmp_path, "a"),
        readers=_readers(_unsigned),
        require_signed_cell=True,
        deliver=True,
        creds=_creds(),
        deliver_override_by="approver:ada",
    )
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED and out.delivery is not None
    lifted = [
        e.payload
        for e in rig.evidence.events_for("I-1", fe.EV_ROUTE)
        if e.payload.get("override_by")
    ]
    assert lifted and lifted[0]["override_by"] == "approver:ada"
    # 2. a missing standard: never
    rig = _rig(
        pyrepo, _sub(tmp_path, "b"), readers=_readers(_none), deliver_override_by="approver:ada"
    )
    assert rig.loop().run_item(multiply_item(), authored=authored_multiply()).status == (
        fl.STATUS_NO_PROVEN_STANDARD
    )
    # 3. a calibration build: still no pull request
    rig = _rig(
        pyrepo,
        _sub(tmp_path, "c"),
        readers=_readers(_none),
        deliver=True,
        creds=_creds(),
        deliver_override_by="approver:ada",
    )
    rig.evidence.record_calibration("I-1", approver="approver:bo", reason="measure")
    cal = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert cal.status == fl.STATUS_CALIBRATION_BUILD and not rig.prs
    # 4. the delivered change's own unlicensed cell: still refused
    rig = _rig(
        pyrepo,
        _sub(tmp_path, "d"),
        readers=_readers(_xs_licence_only),
        builder=MultiBuilder(first_edit=BIG_MULTIPLY),
        deliver=True,
        creds=_creds(),
        deliver_override_by="approver:ada",
    )
    big = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert big.status == fl.STATUS_SIZE_EXCEEDS_LICENCE and not rig.prs


#: Every way the pure gate stops an item except the sign-off clause, keyed by a name the
#: failure message quotes: (size, standard_for, missing_slots, person_test, author).
_NOT_OVERRIDABLE: dict[str, tuple[str, StandardFn, tuple[str, ...], bool, str | None]] = {
    "unsized": ("unsized", _s1, (), False, None),
    "granularize": ("L", _s1, (), False, None),
    "no_proven_standard/none": ("XS", _none, (), False, None),
    "no_proven_standard/ceiling": ("XS", lambda c: Standard("S3", signed=True), (), True, None),
    "needs_context/S1 slot": ("XS", _s1, ("expected_behaviour",), False, None),
    "needs_context/S1 author": ("XS", _s1, (), False, "someone-else"),
    "needs_context/S2 test": ("XS", lambda c: Standard(ARM_S2, signed=True), (), False, None),
}


def test_an_override_never_admits_any_stop_but_the_sign_off_clause() -> None:
    """``deliver_override`` lifts ``unsigned_cell`` and nothing else (ADR-0026 item 8): for
    every other stop the pure gate makes — no size, a size split, no proven standard, an
    ``S3`` ceiling, and each way context is missing — an approver's override changes
    nothing, with or without a signed cell required. The cases cover every stop code the
    gate returns but ``unsigned_cell`` (a case removed fails the last assertion)."""
    seen: set[str] = set()
    for name, (size, fn, missing, person, author) in _NOT_OVERRIDABLE.items():
        for signed in (False, True):
            kw: dict[str, Any] = {
                "capability_class": "bug.fix",
                "size": size,
                "standard_for": fn,
                "agreement_passed": False,
                "missing_slots": missing,
                "person_test": person,
                "require_signed_cell": signed,
                "author": author,
            }
            plain = decide_entry(**kw)
            lifted = decide_entry(**kw, override_by="approver:ada")
            assert not plain.enters, name
            assert not lifted.enters, f"the override admitted {name}"
            assert (lifted.code, lifted.reason_code) == (plain.code, plain.reason_code), name
            assert lifted.override_by == "", name
            seen.add(plain.code)
    assert seen == {STOP_UNSIZED, STOP_GRANULARIZE, STOP_NO_PROVEN_STANDARD, STOP_NEEDS_CONTEXT}
    assert not seen & OVERRIDABLE


# --- the licence of the delivered change (C4) --------------------------------------------

#: A multiply with a dozen more lines: its churn is an S change, whatever the estimate said.
BIG_MULTIPLY = MULTIPLY_DEF + "".join(f"\n# a note the builder left, line {i}" for i in range(12))


def _xs_licence_only(cell: CellRef) -> Standard | None:
    """Every class × size cell has a proven standard; for the building rung only XS is
    licensed."""
    if cell.builder and cell.size != "XS":
        return None
    return Standard(ARM_S2, signed=True)


def test_a_change_larger_than_its_licence_stops_size_exceeds_licence(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    rig = _rig(
        pyrepo,
        tmp_path,
        readers=_readers(_xs_licence_only),
        builder=MultiBuilder(first_edit=BIG_MULTIPLY),
        deliver=True,
        creds=_creds(),
    )
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_SIZE_EXCEEDS_LICENCE
    assert out.final_verdict is not None and out.final_verdict.accepted
    assert not rig.pushes and not rig.prs
    refused = rig.evidence.events_for("I-1", fe.EV_DELIVERY_REFUSED)[-1].payload
    assert refused["reason_code"] == "size_exceeds_licence"
    assert (refused["estimate"], refused["measured"]) == ("XS", "S")
    assert refused["estimated_cell"] == "bug.fix|XS"
    assert refused["licence"]["cell"] == {
        "capability_class": "bug.fix",
        "size": "S",
        "builder": "fake",
        "model": "multi",
        "provider": "fake",  # the licence reads the provider too (P-340)
        "arm": ARM_S2,
    }


#: The same dozen-line change behind a line that reads, in the diff, as the oracle's own
#: file header (``+`` + ``++ b/<oracle>``): a prefix parse stopped counting there (P-294).
SMUGGLED_MULTIPLY = (
    MULTIPLY_DEF
    + f'\nNOTE = """\n++ b/{TEST_MULTIPLY}\n"""'
    + "".join(f"\n# a note the builder left, line {i}" for i in range(12))
)


def test_a_line_shaped_like_the_oracles_header_does_not_shrink_the_measured_size(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    rig = _rig(
        pyrepo,
        tmp_path,
        readers=_readers(_xs_licence_only),
        builder=MultiBuilder(first_edit=SMUGGLED_MULTIPLY),
        deliver=True,
        creds=_creds(),
    )
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_SIZE_EXCEEDS_LICENCE
    assert not rig.pushes and not rig.prs
    (row,) = list(rig.ledger.rows())
    assert row.size == "S"


def test_an_unlicensed_cell_is_refused_before_any_build_at_no_cost(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    def no_licence(cell: CellRef) -> Standard | None:
        return None if cell.builder else Standard(ARM_S2, signed=True)

    rig = _rig(pyrepo, tmp_path, readers=_readers(no_licence), deliver=True, creds=_creds())
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_NOT_LICENSED
    _not_built(rig)
    reason = rig.evidence.events_for("I-1", fe.EV_ENTRY_REFUSED)[0].payload["reason"]
    assert "fake:multi" in reason and "not built" in reason


def test_the_licence_is_keyed_on_the_building_rungs_builder_and_model(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """A licence held by another model is not this rung's licence: the projection is class ×
    size × builder × model, never one that pools models."""

    def for_model(model: str) -> StandardFn:
        def fn(cell: CellRef) -> Standard | None:
            if cell.builder and cell.model != model:
                return None
            return Standard(ARM_S2, signed=True)

        return fn

    rig = _rig(
        pyrepo,
        _sub(tmp_path, "a"),
        readers=_readers(for_model("another")),
        deliver=True,
        creds=_creds(),
    )
    assert rig.loop().run_item(multiply_item(), authored=authored_multiply()).status == (
        fl.STATUS_NOT_LICENSED
    )
    rig = _rig(
        pyrepo,
        _sub(tmp_path, "b"),
        readers=_readers(for_model("multi")),
        deliver=True,
        creds=_creds(),
    )
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_ACCEPTED and out.delivery is not None
    opened = rig.evidence.events_for("I-1", fe.EV_DELIVERY)[-1].payload
    assert opened["licence"]["cell"]["model"] == "multi" and opened["measured"] == "XS"


def test_calibration_is_one_grant_for_one_run() -> None:
    """The pure gate: a grant answers ``no_proven_standard`` and ``needs_context`` only."""
    grant = Calibration("approver:ada", "measure")
    entry = decide_entry(
        capability_class="bug.fix",
        size="L",
        standard_for=_none,
        agreement_passed=False,
        missing_slots=(),
        person_test=True,
        calibration=grant,
    )
    assert entry.code == STOP_GRANULARIZE  # a grant never lifts the size rule


# --- the arm the build carries is the standard's arm (verifier findings, 2026-09-27) -------


def _s1_alpha(cell: CellRef) -> Standard | None:
    return Standard("S1@alpha", signed=True)


def test_a_build_on_another_author_than_the_standards_stops_before_any_spend(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """The cell's standard is ``S1@alpha``; this run's test author is ``t1``. Building
    ``S1@t1`` would deliver an arm nobody measured on alpha's licence, so the item stops
    ``needs_context`` before the author or the builder is called — and so does a caller's
    own test by another author."""
    rig = _rig(
        pyrepo,
        tmp_path,
        readers=_readers(_s1_alpha),
        author=_author(),
        deliver=True,
        creds=_creds(),
    )
    out = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out.status == fl.STATUS_NEEDS_CONTEXT
    _not_built(rig)
    assert not rig.prs
    refused = rig.evidence.events_for("I-1", fe.EV_ENTRY_REFUSED)[0].payload
    assert refused["code"] == STOP_NEEDS_CONTEXT
    assert "S1@alpha" in refused["reason"] and "t1" in refused["reason"]
    assert refused["needs"] == ["a failing test written by alpha, the standard's test author"]

    rig2 = _rig(pyrepo, _sub(tmp_path, "caller"), readers=_readers(_s1_alpha))
    caller = authored_multiply(author="author:t2")
    out2 = rig2.loop().run_item(multiply_item(), authored=caller)
    assert out2.status == fl.STATUS_NEEDS_CONTEXT
    _not_built(rig2)


def _class_s1_rung_xs_s1_s_s2(cell: CellRef) -> Standard | None:
    """``S1@t1`` is every class × size cell's standard; for the building rung the XS cell's
    standard is ``S1@t1`` and the S cell's is ``S2``."""
    if cell.builder and cell.size != "XS":
        return Standard(ARM_S2, signed=True)
    return Standard("S1@t1", signed=True)


def test_the_licence_is_read_on_the_arm_the_build_carried(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """A change built on ``S1@t1`` that turns out S-sized is licensed only if ``S1@t1``
    is the standard of its own S cell — an ``S2`` standard there (a person's test, which
    this build never carried) licenses nothing. The licence names the arm."""
    rig = _rig(
        pyrepo,
        tmp_path,
        readers=_readers(_class_s1_rung_xs_s1_s_s2),
        author=_author(),
        builder=MultiBuilder(first_edit=BIG_MULTIPLY),
        deliver=True,
        creds=_creds(),
    )
    out = rig.loop().run_item(multiply_item())
    assert out.status == fl.STATUS_SIZE_EXCEEDS_LICENCE
    assert not rig.pushes and not rig.prs
    refused = rig.evidence.events_for("I-1", fe.EV_DELIVERY_REFUSED)[-1].payload
    assert refused["licence"]["cell"]["arm"] == "S1@t1"
    assert refused["licence"]["standard"]["arm"] == ARM_S2
    assert "S1@t1" in refused["reason"]

    # before the build: no rung holds a licence for the build's arm at the item's size
    def rung_s2_only(cell: CellRef) -> Standard | None:
        return Standard(ARM_S2, signed=True) if cell.builder else Standard("S1@t1", signed=True)

    rig2 = _rig(
        pyrepo,
        _sub(tmp_path, "pre"),
        readers=_readers(rung_s2_only),
        author=_author(),
        deliver=True,
        creds=_creds(),
    )
    assert rig2.loop().run_item(multiply_item()).status == fl.STATUS_NOT_LICENSED
    _not_built(rig2)


def test_a_factory_s2_row_is_not_a_routing_first_attempt_without_held_out_acceptance(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """ADR-0026 item 8: a calibration build yields an ``S2`` row that can promote a ceiling
    only when it is also graded on held-out acceptance tests a second person wrote
    (``product.truth.215``; tests/test_factory_held_out.py). Without them every factory
    ``S2`` row — the calibration build's and an ordinary one's — is stamped
    ``acceptance: none`` and the reading's predicate refuses it."""
    rig = _rig(pyrepo, tmp_path, readers=_readers(lambda c: Standard("S3")))
    rig.evidence.record_calibration("I-1", approver="approver:ada", reason="measure the arm")
    cal = rig.loop().run_item(multiply_item(), authored=authored_multiply())
    assert cal.status == fl.STATUS_CALIBRATION_BUILD
    (row,) = list(rig.ledger.rows())
    assert row.labels["context_arm"] == ARM_S2
    assert row.labels[LABEL_ACCEPTANCE] == ACCEPTANCE_NONE
    assert not counts_as_s2_first_attempt(row.labels)

    rig2 = _rig(
        pyrepo, _sub(tmp_path, "s2"), readers=_readers(lambda c: Standard(ARM_S2, signed=True))
    )
    out2 = rig2.loop().run_item(multiply_item(), authored=authored_multiply())
    assert out2.status == fl.STATUS_ACCEPTED
    (row2,) = list(rig2.ledger.rows())
    assert row2.labels[LABEL_ACCEPTANCE] == ACCEPTANCE_NONE
    assert not counts_as_s2_first_attempt(row2.labels)
    # only positive evidence of held-out acceptance grading counts — the stamp, the record's
    # digest and a result (P-690) — and only on S2
    held = {
        "context_arm": ARM_S2,
        LABEL_ACCEPTANCE: ACCEPTANCE_HELD_OUT,
        "acceptance_sha256": "a" * 64,
        "acceptance_result": "pass",
    }
    assert counts_as_s2_first_attempt(held)
    assert not counts_as_s2_first_attempt({**held, "context_arm": "S1@t1"})
    assert not counts_as_s2_first_attempt({"context_arm": ARM_S2})
    assert not counts_as_s2_first_attempt({"context_arm": ARM_S2, LABEL_ACCEPTANCE: "held_out"})


def test_an_unsigned_estimate_cell_is_not_hidden_by_a_signed_larger_cell() -> None:
    """Where a signed cell is required, every cell the size rule read must be signed: an
    XS estimate whose own XS cell is proven but unsigned stops ``unsigned_cell`` even when
    the S cell is signed."""
    by_size = {"XS": Standard("S1@t1", signed=False), "S": Standard("S1@t1", signed=True)}
    entry = decide_entry(
        capability_class="bug.fix",
        size="XS",
        standard_for=lambda c: by_size[c.size],
        agreement_passed=False,
        missing_slots=(),
        person_test=False,
        require_signed_cell=True,
    )
    assert entry.code == STOP_UNSIGNED_CELL
    assert "bug.fix XS" in entry.reason
    lifted = decide_entry(
        capability_class="bug.fix",
        size="XS",
        standard_for=lambda c: by_size[c.size],
        agreement_passed=False,
        missing_slots=(),
        person_test=False,
        require_signed_cell=True,
        override_by="approver:ada",
    )
    assert lifted.enters and lifted.override_by == "approver:ada"
