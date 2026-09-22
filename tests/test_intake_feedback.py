"""crb.intake.feedback — the one comment the ticket gets, and the label that goes with it.

Navigation
----------
What it is:   The renderer's test suite: which of the four labels each situation earns,
              that the comment carries the marker, the open questions, the cell's route
              with n and interval and the apparatus, and that it never leaves jargon
              unexplained.
What it does: Pins the label ladder (not deliverable beats needs-info beats ready), that
              an unclassified item SAYS it is unclassified rather than showing a class,
              that a cell nobody has measured is named as unmeasured rather than shown as
              zero, that the same inputs render byte-identical text (so a re-post writes
              nothing), and that every gap names what closes it.
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


def _render(ticket: c.Ticket, route: dict[str, Any] | None = None) -> fb.Feedback:
    draft = d.draft_from(ticket, tracker="ado")
    return fb.render_feedback(draft, rd.assess(draft.item), cell_route=route)


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


def test_a_cell_that_does_not_route_deliver_is_not_deliverable_even_when_ready() -> None:
    f = _render(_ready_ticket(), _deliver_route(route="calibrate", reason_code="n_below_min", n=3))
    assert f.label == c.LABEL_NOT_DELIVERABLE
    assert f.ready_to_register is True  # it is still built and withheld, never dropped


def test_not_deliverable_beats_needs_info_is_false_the_person_is_asked_first() -> None:
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
    assert f.label == c.LABEL_NOT_DELIVERABLE
    assert "do not ship" in f.text.lower() or "do_not_ship" in f.text


def test_the_comment_states_the_non_goals_so_nobody_fears_a_wider_edit() -> None:
    f = _render(_ready_ticket(), _deliver_route())
    low = f.text.lower()
    assert "never" in low
    assert "comment" in low and "label" in low


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
