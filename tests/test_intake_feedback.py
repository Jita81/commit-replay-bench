"""crb.intake.feedback — the one comment the ticket gets, and the label that goes with it.

Navigation
----------
What it is:   The renderer's test suite: which of the four labels each situation earns,
              that the comment carries the marker, the open questions, the cell's route
              with n and interval and the apparatus, and that it never leaves jargon
              unexplained.
What it does: Pins the label ladder (needs-info beats not deliverable beats ready — asking
              the person comes first, because answering is the only step they can take), that
              an unclassified item SAYS it is unclassified rather than showing a class,
              that a cell nobody has measured is named as unmeasured rather than shown as
              zero, that the same inputs render byte-identical text (so a re-post writes
              nothing), that every gap names what closes it, and that only an entry stop
              says "not built": a ticket the entry gate admits is ready whatever its cell
              routes, told whether a pull request opens (P-129).
How:          Real ``Readiness`` objects from ``crb.factory.readiness.assess`` over drafts
              built by ``crb.intake.draft`` — no hand-written gap fixtures, so a change to
              the catalogue shows up here.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md
Works with:   src/crb/intake/feedback.py (under test), src/crb/factory/readiness.py (the
              open questions it renders), src/crb/core/routing.py (the route words),
              tests/test_intake_draft.py (the drafts it renders)
Tested by:    tests/test_intake_feedback.py
Touch when:   the comment gains a section — say what closes the gap in the same sentence,
              and keep the renderer deterministic or the idempotent re-post breaks.
"""

from __future__ import annotations

from typing import Any

from crb.factory import readiness as rd
from crb.factory.standard import ArmReading, CellRef, Readers, Standard, gate_for
from crb.intake import client as c
from crb.intake import draft as d
from crb.intake import feedback as fb
from fixtures.intake import a_ticket


def _ready_ticket() -> c.Ticket:
    return c.Ticket(
        key="4711",
        title="Add a POST /health route",
        body="a new HTTP endpoint on the api",
        acceptance_criteria=(
            "method_path: POST /health",
            "request_shape: no body",
            "response_shape: 200 with {status: string}",
            "error_contract: 503 when a dependency is down",
        ),
        revision="1",
        points=2.0,
    )


def _deliver_route(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "route": "deliver",
        "reason": "every bar cleared",
        "reason_code": "deliver",
        "n": 42,
        "point": 0.81,
        "ci_low": 0.67,
        "ci_high": 0.90,
        "apparatus_versions": ["2.2"],
    }
    base.update(kw)
    return base


def _proven(cell: CellRef) -> Standard | None:
    return Standard("S1@claude-sonnet-5", signed=True)


PROVEN = Readers(standard_for=_proven)


def _render(
    ticket: c.Ticket,
    route: dict[str, Any] | None = None,
    *,
    readers: Readers = PROVEN,
    arms: tuple[ArmReading, ...] = (),
    require_signed_cell: bool = False,
) -> fb.Feedback:
    draft = d.draft_from(ticket, tracker="ado")
    readiness = rd.assess(draft.item)
    entry = gate_for(draft.item, readiness, readers, require_signed_cell=require_signed_cell)
    return fb.render_feedback(draft, readiness, entry=entry, cell_route=route, arms=arms)


# --- the label ladder ---------------------------------------------------------------


def test_a_ready_item_on_a_deliverable_cell_is_labelled_ready() -> None:
    f = _render(_ready_ticket(), _deliver_route())
    assert f.label == c.LABEL_READY
    assert f.ready_to_register is True


def test_a_missing_structural_slot_is_needs_info() -> None:
    t = _ready_ticket()
    f = _render(c.Ticket(**{**t.to_dict(), "acceptance_criteria": ("method_path: POST /health",)}))
    assert f.label == c.LABEL_NEEDS_INFO
    assert f.ready_to_register is False


#: Words that say a ticket is not built — true only of an entry-gate stop (P-121, P-129).
NOT_BUILT_WORDS: tuple[str, ...] = (
    "not be built",
    "not built",
    "nothing is built",
    "will not build",
    "not build it",
    "not build anything",
    "not build this",
)


def test_a_ticket_the_gate_admits_is_built_whatever_its_cells_route() -> None:
    """The route gate is not the entry gate (P-121's class, in the ticket comment): a ticket
    the entry gate admits is built, graded and reviewed whatever its cell routes, and only
    ``deliver`` opens a pull request. For every other route — and an unmeasured cell — the
    comment says it is built with no pull request, never "not built"; the label is
    ``crb:ready`` and, once registered, ``crb:queued``: both stay true."""
    routes: list[dict[str, Any] | None] = [
        _deliver_route(route=word, reason_code=word, n=3)
        for word in ("calibrate", "human", "do_not_ship", "granularize")
    ]
    for route in [*routes, None]:
        f = _render(_ready_ticket(), route)
        word = route["route"] if route else "unmeasured"
        assert f.entry is not None and f.entry["code"] == "", word
        assert f.label == c.LABEL_READY and f.ready_to_register is True, word
        lowered = f.text.lower()
        assert not [w for w in NOT_BUILT_WORDS if w in lowered], (word, f.text)
        assert "no pull request opens" in lowered, word
        assert fb.label_once_registered(f.entry["code"]) == c.LABEL_QUEUED, word
    ready = _render(_ready_ticket(), _deliver_route())
    assert "no pull request opens" not in ready.text.lower()


def test_only_an_entry_stop_says_not_built() -> None:
    """The other side: every entry stop the comment renders says the ticket is not built."""
    none = Readers(standard_for=lambda cell: None)
    ceiling = Readers(standard_for=lambda cell: Standard("S3", signed=True))
    unsigned = Readers(standard_for=lambda cell: Standard("S1@claude-sonnet-5", signed=False))
    for f in (
        _render(_ready_ticket(), _deliver_route(), readers=none),
        _render(_ready_ticket(), _deliver_route(), readers=ceiling),
        _render(_ready_ticket(), _deliver_route(), readers=unsigned, require_signed_cell=True),
    ):
        assert f.label == c.LABEL_NOT_DELIVERABLE
        assert "will not be built" in f.text


def test_a_cell_with_no_proven_standard_is_not_deliverable_naming_each_arm_and_the_way_forward() -> (
    None
):
    """Recovery 23 (ADR-0026 item 8): no proven context standard → `crb:not-deliverable`,
    NOT BUILT, with each measured arm's state, n and interval and the way forward (measure
    the cell, or an approver's calibration build that never opens a pull request)."""
    arms = (
        ArmReading("S3", "deliver", n=20, clean=20, ci_low=0.84, ci_high=1.0),
        ArmReading("S1@claude-sonnet-5", "look_pending", n=12, clean=11, ci_low=0.65, ci_high=0.99),
    )
    none = Readers(standard_for=lambda cell: None)
    f = _render(_ready_ticket(), _deliver_route(), readers=none, arms=arms)
    assert f.label == c.LABEL_NOT_DELIVERABLE and f.ready_to_register is True
    assert "will not be built" in f.text and "held back" not in f.text
    assert "`S3`: deliver — 20 of 20 commit(s) clean, 95 % Wilson interval 84 % to 100 %" in f.text
    assert "`S1@claude-sonnet-5`: look_pending — 11 of 12" in f.text
    assert "an approver funds one calibration build" in f.text
    assert fb.GLOSSED["calibration build"] in f.text and fb.GLOSSED["context standard"] in f.text
    assert f.entry is not None and f.entry["code"] == "no_proven_standard"
    # with nothing registered yet, it says so — never a zero
    bare = _render(_ready_ticket(), None, readers=none)
    assert "No arm of this cell has a registered reading yet" in bare.text


def test_a_ticket_lacking_what_its_standard_needs_is_needs_info_naming_it() -> None:
    s2 = Readers(standard_for=lambda cell: Standard("S2", signed=True))
    f = _render(_ready_ticket(), _deliver_route(), readers=s2)
    assert f.label == c.LABEL_NEEDS_INFO and f.ready_to_register is False
    assert "`a failing test`" in f.text and "Attach it to the ticket" in f.text


def test_an_unsigned_cell_names_the_sign_off_and_the_override_that_lifts_only_it() -> None:
    unsigned = Readers(standard_for=lambda cell: Standard("S1@claude-sonnet-5", signed=False))
    f = _render(_ready_ticket(), _deliver_route(), readers=unsigned, require_signed_cell=True)
    assert f.label == c.LABEL_NOT_DELIVERABLE
    assert "a second person's sign-off" in f.text and "lifts only the sign-off" in f.text


def test_a_ticket_without_points_asks_for_them() -> None:
    t = _ready_ticket()
    f = _render(c.Ticket(**{**t.to_dict(), "points": None}), _deliver_route())
    assert f.label == c.LABEL_NEEDS_INFO and f.ready_to_register is False
    assert "Story points" in f.text and "unsized" in f.text


def test_needs_info_beats_not_deliverable_so_the_person_is_asked_first() -> None:
    # a ticket that is BOTH missing a slot and on an unmeasured cell asks for the
    # information first: answering it is the only step the person can take.
    t = _ready_ticket()
    f = _render(
        c.Ticket(**{**t.to_dict(), "acceptance_criteria": ()}),
        None,
    )
    assert f.label == c.LABEL_NEEDS_INFO


def test_the_queued_label_is_rendered_by_its_own_helper_not_by_readiness() -> None:
    body = fb.render_queued("ado-4711", "https://crb.invalid/factory?item=ado-4711")
    assert "ado-4711" in body
    assert "https://crb.invalid/factory?item=ado-4711" in body


# --- what the comment says ----------------------------------------------------------


def test_the_comment_carries_the_marker_so_a_re_post_edits_rather_than_adds() -> None:
    f = _render(_ready_ticket(), _deliver_route())
    assert f.marker == c.marker_for("ado", "4711")
    assert f.marker in f.text


def test_the_same_inputs_render_identical_text() -> None:
    a = _render(_ready_ticket(), _deliver_route())
    b = _render(_ready_ticket(), _deliver_route())
    assert a.text == b.text


def test_every_open_question_names_the_slot_and_what_closes_it() -> None:
    t = _ready_ticket()
    f = _render(c.Ticket(**{**t.to_dict(), "acceptance_criteria": ("method_path: POST /health",)}))
    assert "response_shape" in f.text
    assert "What is the response shape" in f.text
    assert "response_shape: " in f.text  # the exact line to add to the acceptance criteria


def test_an_unclassified_item_says_so_and_never_shows_an_invented_class() -> None:
    f = _render(a_ticket(title="Do the thing", body="by Friday"))
    assert "could not classify" in f.text.lower()
    assert f.label == c.LABEL_NEEDS_INFO


def test_a_classified_item_shows_the_class_with_its_confidence() -> None:
    f = _render(_ready_ticket(), _deliver_route())
    assert "backend.route.add" in f.text
    assert "confidence" in f.text.lower()


def test_the_route_is_quoted_with_n_interval_and_apparatus() -> None:
    f = _render(_ready_ticket(), _deliver_route())
    assert "42" in f.text  # n
    assert "67" in f.text and "90" in f.text  # the Wilson interval, as percentages
    assert "2.2" in f.text  # the apparatus version
    assert "deliver" in f.text


def test_an_unmeasured_cell_is_named_as_unmeasured_not_shown_as_zero() -> None:
    f = _render(_ready_ticket(), None)
    assert "not been measured" in f.text
    assert "0 %" not in f.text


def test_a_false_q1_cell_is_reported_as_the_honesty_floor_breach_it_is() -> None:
    f = _render(
        _ready_ticket(),
        _deliver_route(route="do_not_ship", reason_code="false_q1", reason="a row credited clean"),
    )
    assert f.label == c.LABEL_READY  # admitted by the entry gate: built, never delivered
    assert "do not ship" in f.text.lower() or "do_not_ship" in f.text
    assert "no pull request opens" in f.text.lower()


def test_the_comment_counts_what_it_writes_rather_than_promising_it_writes_little() -> None:
    """The sentence used to say the product "only ever adds this one comment … and never
    edits any other field". One poll of a ready ticket leaves TWO comments and attaches a
    link, and over its life a ticket can get four. The old test looked for the words
    "never", "comment" and "label", so it could not catch the miscount. This one counts
    against the renderers that exist and the verbs the adapter has."""
    import inspect

    f = _render(_ready_ticket(), _deliver_route())
    low = f.text.lower()
    # the four notes, the label, both links and the one configured state change
    assert "up to four comments" in low
    for phrase in ("what is missing", "queued", "pull request opens", "if the work stopped"):
        assert phrase in low
    assert "one crb: label" in low
    assert "a link to the backlog item and to the pull request" in low
    assert "one state change when the pull request is merged" in low
    assert "edits no other field" in low
    # and the count is the truth: one renderer per note the sentence claims
    renderers = [n for n in dir(fb) if n.startswith("render_")]
    assert sorted(renderers) == [
        "render_delivered",
        "render_feedback",
        "render_queued",
        "render_refusal",
    ]
    # nothing in the sentence promises a bound the protocol does not have
    verbs = [
        n
        for n, _ in inspect.getmembers(c.TrackerClient, inspect.isfunction)
        if not n.startswith("_")
    ]
    assert sorted(verbs) == ["comment", "entered", "label", "link", "read", "transition"]


def test_the_comment_has_no_unexplained_jargon() -> None:
    f = _render(_ready_ticket(), _deliver_route())
    for term in ("Wilson", "apparatus", "cell"):
        assert term.lower() in f.text.lower()
        # each jargon word is followed somewhere by its gloss in brackets or a clause
        assert fb.GLOSSED[term.lower()] in f.text


def test_feedback_round_trips_through_its_dict_for_the_intake_row() -> None:
    f = _render(_ready_ticket(), _deliver_route())
    body = f.to_dict()
    assert body["label"] == c.LABEL_READY
    assert body["text"] == f.text
    assert body["marker"] == f.marker
    # the one open question left on a ready item is a VALUE slot: it routes, it never blocks
    assert [q["severity"] for q in body["open_questions"]] == ["routed"]


def test_the_open_questions_on_the_row_are_the_readiness_shape() -> None:
    t = _ready_ticket()
    f = _render(c.Ticket(**{**t.to_dict(), "acceptance_criteria": ("method_path: POST /health",)}))
    refs = {q["ref"] for q in f.open_questions}
    assert any("response_shape" in r for r in refs)
    assert all(set(q) == {"ref", "severity", "reason"} for q in f.open_questions)


# --- the refusal comment ------------------------------------------------------------


def test_a_refusal_comment_carries_the_served_way_forward_verbatim() -> None:
    body = fb.render_refusal(
        "ado-4711",
        status="no_oracle",
        reason="no operator-authored test and no test-author rung",
        way_forward="Register an evolution that carries the acceptance test.",
        url="https://crb.invalid/factory?item=ado-4711",
    )
    assert "Register an evolution that carries the acceptance test." in body
    assert "no_oracle" in body


def test_a_delivery_comment_carries_the_pull_request_link() -> None:
    body = fb.render_delivered("ado-4711", "https://github.invalid/o/r/pull/7")
    assert "https://github.invalid/o/r/pull/7" in body


def test_a_decision_rendered_straight_from_the_router_quotes_the_whole_interval() -> None:
    """The worker's own timed poll — the product's DEFAULT front door — handed the renderer a
    ``RouteDecision.to_dict()`` while the on-demand poll handed it the capability map's row.
    Only the row carried ``ci_high``, so the same cell produced two different comments and
    the worker's one said the interval ran "to unknown". One shape, pinned from the router's
    own output, is what stops that coming back.
    """
    from crb.core.capability import CellKey, CellStats
    from crb.core.ledger import wilson_interval
    from crb.core.routing import route

    cell = CellKey("replay", "bug.fix", "S", "python", "agentic", "m", "p")
    stats = CellStats(
        cell=cell,
        n=42,
        clean=34,
        disqualified=0,
        errors=0,
        false_q1=0,
        point=34 / 42,
        ci=wilson_interval(34, 42),
        cost_usd_mean=0.01,
        latency_s_mean=5.0,
        oracle_strength_mean=None,
        apparatus_versions=("2.2",),
    )
    decision = dict(route(stats).to_dict())
    decision["apparatus_versions"] = ["2.2"]
    text = _render(_ready_ticket(), decision).text
    assert "to unknown" not in text
    assert f"{stats.ci.low * 100:.0f} % to {stats.ci.high * 100:.0f} %" in text
