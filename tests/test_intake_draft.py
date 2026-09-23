"""crb.intake.draft — one ticket becomes one draft backlog item, and says how.

Navigation
----------
What it is:   The mapping layer's test suite: HTML and ADF to text, acceptance criteria
              to structural facts, story points to a size tier, work-item type to a kind,
              the classifier's class WITH its confidence, and the evolution id.
What it does: Pins the id shape (``ado-4711``, ``jira-abc-123``) against the backlog's own
              id regex, that every mapping states the rule it used (``size_reason``,
              ``kind_reason``, ``Classification.reason``), that a low-confidence
              classification is ``unclassified`` and never a silent guess, and that a
              re-read whose CONTENT changed produces a NEW id that supersedes the old one —
              while a new revision the product's own writes moved does not.
How:          Plain ``Ticket`` objects from ``fixtures.intake``'s helper; the
              produced ``BacklogItem`` is fed to the real ``crb.factory.readiness.assess``
              so the facts this module writes are the facts the gate reads.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md
Works with:   src/crb/intake/draft.py (under test), src/crb/factory/backlog.py (the id
              regex and the item shape), src/crb/factory/readiness.py (the slot catalogue
              the facts must satisfy), tests/fixtures/intake.py (the ticket helper)
Tested by:    tests/test_intake_draft.py
Touch when:   a capability class is added to the readiness catalogue (give it cues here
              first); the points → size mapping changes (it is published in the guide).
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from crb.factory import readiness as rd
from crb.factory.backlog import ID_MAX_LEN, KIND_CODE, KIND_INFRA, KIND_OPERATOR, BacklogItem
from crb.intake import client as c
from crb.intake import draft as d
from fixtures.intake import a_ticket

# --- the id ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tracker", "key", "expected"),
    [
        ("ado", "4711", "ado-4711"),
        ("jira", "ABC-123", "jira-abc-123"),
        ("ado", "WI 42", "ado-wi-42"),
        ("jira", "a/b:c", "jira-a-b-c"),
    ],
)
def test_the_item_id_is_tracker_and_key_lowercased_and_legal(
    tracker: str, key: str, expected: str
) -> None:
    item = d.draft_from(a_ticket(key=key), tracker=tracker).item
    assert item.id == expected
    # the real constructor is the check: a bad id raises in BacklogItem.__post_init__
    assert BacklogItem(id=item.id, title="t", kind=KIND_CODE).id == expected


def test_a_key_that_sanitises_to_nothing_is_refused_rather_than_guessed() -> None:
    with pytest.raises(ValueError, match="key"):
        d.draft_from(a_ticket(key="///"), tracker="ado")


def test_two_long_keys_sharing_a_prefix_never_become_one_item() -> None:
    """A plain ``slug[:64]`` mapped two keys sharing a 64-character prefix onto one id: the
    second ticket was labelled queued, told it had been recorded as the FIRST one's item and
    linked to it, while nothing at all was registered for it — a silent drop with an
    affirmative false statement on somebody's board."""
    long_a = "a" * 80 + "1"
    long_b = "a" * 80 + "2"
    id_a = d.item_id_for("ado", long_a)
    id_b = d.item_id_for("ado", long_b)
    assert id_a != id_b
    assert len(id_a) <= ID_MAX_LEN and len(id_b) <= ID_MAX_LEN
    # still a legal id, and still derived from the whole key (the same key gives the same id)
    assert BacklogItem(id=id_a, title="t", kind=KIND_CODE).id == id_a
    assert d.item_id_for("ado", long_a) == id_a


# --- rich text to plain text -----------------------------------------------------


def test_html_becomes_plain_lines_with_the_list_items_kept() -> None:
    html = "<div>Given a user<br/>when they call <b>/health</b></div><ul><li>200</li></ul>"
    assert d.html_to_text(html) == "Given a user\nwhen they call /health\n- 200"


def test_html_entities_and_scripts_do_not_survive_the_conversion() -> None:
    assert d.html_to_text("<p>a &amp; b</p><script>alert(1)</script>") == "a & b"


def test_adf_becomes_plain_lines_with_bullets() -> None:
    adf = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Given a user"}]},
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "200"}]}
                        ],
                    }
                ],
            },
        ],
    }
    assert d.adf_to_text(adf) == "Given a user\n- 200"


def test_adf_that_is_already_plain_text_is_returned_unchanged() -> None:
    assert d.adf_to_text("just text") == "just text"


# --- acceptance criteria → structural facts ---------------------------------------


def _route_ticket(**kw: object) -> c.Ticket:
    base: dict[str, object] = {
        "key": "4711",
        "title": "Add a new POST /health route to the API",
        "body": "A new HTTP endpoint is needed so the load balancer can probe the service.",
        "type": "User Story",
        "acceptance_criteria": (
            "method_path: POST /health",
            "request_shape: no body",
            "response_shape: 200 with {status: string}",
            "error_contract: 503 with {status: string} when a dependency is down",
            "Given the service is up, when I POST /health, then I get 200.",
        ),
        "revision": "1",
    }
    base.update(kw)
    return c.Ticket(**base)  # type: ignore[arg-type]


def test_acceptance_criteria_that_name_a_slot_become_structural_facts() -> None:
    draft = d.draft_from(_route_ticket(), tracker="ado")
    assert draft.item.capability_class == "backend.route.add"
    facts = rd.parse_facts(draft.item.structural_facts)
    assert facts["method_path"] == "POST /health"
    assert facts["response_shape"] == "200 with {status: string}"
    # and the gate agrees: no blocking gap is left
    assert rd.assess(draft.item).ready is True


def test_prose_acceptance_criteria_are_kept_but_never_invented_as_facts() -> None:
    draft = d.draft_from(_route_ticket(), tracker="ado")
    assert "Given the service is up, when I POST /health, then I get 200." in (
        draft.item.acceptance_criteria
    )
    assert all(":" in f for f in draft.item.structural_facts)


def test_a_line_naming_a_slot_of_another_class_is_not_used_as_a_fact() -> None:
    t = _route_ticket(acceptance_criteria=("reproduction: click the button", "method_path: GET /x"))
    draft = d.draft_from(t, tracker="ado")
    facts = rd.parse_facts(draft.item.structural_facts)
    assert "reproduction" not in facts  # a bug.fix slot on a backend.route.add item
    assert facts["method_path"] == "GET /x"


def test_a_missing_slot_leaves_a_blocking_gap_the_comment_can_ask_about() -> None:
    t = _route_ticket(acceptance_criteria=("method_path: POST /health",))
    r = rd.assess(d.draft_from(t, tracker="ado").item)
    assert r.ready is False
    assert {g.slot for g in r.blocking_gaps} == {
        "request_shape",
        "response_shape",
        "error_contract",
    }


# --- the classifier ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "body", "expected"),
    [
        ("Add a POST /orders route", "a new HTTP endpoint on the API", "backend.route.add"),
        ("Fix the crash when the cart is empty", "steps to reproduce: …", "bug.fix"),
        (
            "Add a column to the orders table",
            "a database migration adds the column",
            "backend.migration.add",
        ),
        ("Add a Basket React component", "a new UI component with props", "frontend.component.add"),
        ("Update the README install section", "the documentation is wrong", "docs.update"),
    ],
)
def test_the_classifier_finds_the_class_a_reader_would(
    title: str, body: str, expected: str
) -> None:
    got = d.classify(title, body)
    assert got.capability_class == expected
    assert got.confidence >= d.MIN_CONFIDENCE
    assert got.reason


def test_a_ticket_with_no_cues_is_unclassified_and_says_so() -> None:
    got = d.classify("Do the thing", "Please do the thing by Friday.")
    assert got.capability_class == d.UNCLASSIFIED
    assert got.confidence < d.MIN_CONFIDENCE
    assert "not classify" in got.reason


def test_the_classifier_serves_its_confidence_and_what_it_considered() -> None:
    got = d.classify("Add a POST /orders route", "a new HTTP endpoint on the API")
    assert 0.0 <= got.confidence <= 1.0
    assert got.considered and got.considered[0][0] == got.capability_class


def test_an_unclassified_draft_carries_the_unclassified_class_not_a_guess() -> None:
    draft = d.draft_from(a_ticket(title="Do the thing", body="by Friday"), tracker="ado")
    assert draft.item.capability_class == d.UNCLASSIFIED
    assert draft.classification.confidence < d.MIN_CONFIDENCE
    # and the gate routes it to a human rather than building it
    assert rd.assess(draft.item).route_hint == rd.ROUTE_HUMAN


def test_an_explicit_class_tag_wins_over_the_classifier_and_is_full_confidence() -> None:
    t = a_ticket(title="Do the thing", tags=("crb:class=bug.fix",))
    draft = d.draft_from(t, tracker="ado")
    assert draft.item.capability_class == "bug.fix"
    assert draft.classification.confidence == 1.0
    assert "tag" in draft.classification.reason


def test_an_unknown_class_tag_is_refused_rather_than_trusted() -> None:
    t = a_ticket(tags=("crb:class=not.a.class",))
    draft = d.draft_from(t, tracker="ado")
    assert draft.item.capability_class == d.UNCLASSIFIED
    assert "not in the catalogue" in draft.classification.reason


# --- points → size ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("points", "size"),
    [
        (None, "S"),
        (0.5, "XS"),
        (1.0, "XS"),
        (2.0, "S"),
        (3.0, "S"),
        (5.0, "M"),
        (8.0, "M"),
        (13.0, "L"),
        (20.0, "L"),
        (40.0, "XL"),
    ],
)
def test_story_points_map_to_a_size_tier_and_the_rule_is_stated(
    points: float | None, size: str
) -> None:
    draft = d.draft_from(a_ticket(points=points), tracker="ado")
    assert draft.item.size_estimate == size
    assert draft.size_reason
    if points is None:
        assert "no estimate" in draft.size_reason


def test_a_negative_estimate_is_treated_as_no_estimate_rather_than_crashing() -> None:
    draft = d.draft_from(a_ticket(points=-3.0), tracker="ado")
    assert draft.item.size_estimate == "S"
    assert "no estimate" in draft.size_reason


# --- type/tags → kind and level ----------------------------------------------------


@pytest.mark.parametrize(
    ("wi_type", "kind"),
    [("Bug", KIND_CODE), ("User Story", KIND_CODE), ("Task", KIND_CODE), ("", KIND_CODE)],
)
def test_a_work_item_type_maps_to_a_kind_and_states_the_rule(wi_type: str, kind: str) -> None:
    draft = d.draft_from(a_ticket(type=wi_type), tracker="ado")
    assert draft.item.kind == kind
    assert draft.kind_reason


def test_an_infrastructure_class_makes_the_item_infra_kind() -> None:
    t = a_ticket(
        title="Change the terraform resource for the bucket",
        body="a terraform resource attribute changes",
    )
    draft = d.draft_from(t, tracker="ado")
    assert draft.item.capability_class == "infra.terraform.edit"
    assert draft.item.kind == KIND_INFRA


def test_an_explicit_kind_tag_wins() -> None:
    draft = d.draft_from(a_ticket(tags=("crb:kind=operator",)), tracker="ado")
    assert draft.item.kind == KIND_OPERATOR
    assert "tag" in draft.kind_reason


def test_an_explicit_level_tag_wins_and_an_unknown_one_falls_back_to_l1() -> None:
    assert d.draft_from(a_ticket(tags=("crb:level=L2",)), tracker="ado").item.level == "L2"
    assert d.draft_from(a_ticket(tags=("crb:level=L9",)), tracker="ado").item.level == "L1"


def test_tracker_tags_are_carried_as_item_labels_with_their_provenance() -> None:
    draft = d.draft_from(a_ticket(tags=("area:api", "iteration:sprint-3")), tracker="ado")
    assert draft.item.labels["tracker"] == "ado"
    assert draft.item.labels["ticket"] == "4711"
    assert draft.item.labels["tags"] == "area:api, iteration:sprint-3"
    assert draft.item.labels["revision"] == "1"


# --- evolution ---------------------------------------------------------------------


def test_a_re_read_at_a_new_revision_is_a_new_item_that_supersedes_the_old_one() -> None:
    first = d.draft_from(a_ticket(revision="1"), tracker="ado").item
    second = d.draft_from(
        a_ticket(revision="3", title="Add a health route, revised"), tracker="ado", previous=first
    )
    assert second.item.id == "ado-4711.r3"
    assert second.item.supersedes == first.id
    assert second.is_evolution is True
    assert first.title != second.item.title  # the frozen record is never rewritten


def test_a_re_read_at_the_same_revision_is_not_an_evolution() -> None:
    first = d.draft_from(a_ticket(revision="1"), tracker="ado").item
    again = d.draft_from(a_ticket(revision="1"), tracker="ado", previous=first)
    assert again.is_evolution is False
    assert again.item.id == first.id
    assert again.item.supersedes == ""


def test_a_third_read_supersedes_the_second_not_the_first() -> None:
    first = d.draft_from(a_ticket(revision="1"), tracker="ado").item
    edited = a_ticket(revision="3", title="Add a health route, revised")
    second = d.draft_from(edited, tracker="ado", previous=first).item
    again = a_ticket(revision="4", title="Add a health route, revised twice")
    third = d.draft_from(again, tracker="ado", previous=second)
    assert third.item.supersedes == second.id == "ado-4711.r3"
    assert third.item.id == "ado-4711.r4"


def test_a_re_read_at_a_new_revision_the_product_itself_moved_is_not_an_evolution() -> None:
    """The product's own writes move the ticket's revision: an Azure DevOps tag PATCH
    increments ``System.Rev`` and every Jira write moves ``fields.updated``. Compared on the
    revision alone, a ticket NOBODY had edited became a new evolution on the next poll — one
    needless item per pass, each superseding the last, and the backlog's evolutions hash
    moving with them. The comparison is on the draft's own content."""
    first = d.draft_from(a_ticket(revision="1"), tracker="ado").item
    assert first.labels["content_revision"]  # recorded on the item, so a later poll can ask
    # same ticket, next revision, and the product's own label now on it
    same = d.draft_from(a_ticket(revision="2", tags=("crb:queued",)), tracker="ado", previous=first)
    assert same.is_evolution is False
    assert same.item.id == first.id
    assert same.item.supersedes == ""
    assert same.item.labels["revision"] == "2"  # the revision is still recorded, honestly
    # and a real edit at that same revision IS one
    edited = d.draft_from(
        a_ticket(revision="2", title="Add a health route, revised"), tracker="ado", previous=first
    )
    assert edited.is_evolution is True and edited.item.id == "ado-4711.r2"


def test_an_item_registered_before_the_digest_existed_still_evolves_on_a_new_revision() -> None:
    """An item on a frozen record from before this rule carries no digest. The revision is
    then the only thing there is to compare, once — and a re-read at a new revision is still
    an evolution rather than a silent overwrite."""
    old = d.draft_from(a_ticket(revision="1"), tracker="ado").item
    without = replace(old, labels={k: v for k, v in old.labels.items() if k != "content_revision"})
    again = d.draft_from(a_ticket(revision="2"), tracker="ado", previous=without)
    assert again.is_evolution is True and again.item.id == "ado-4711.r2"


def test_the_draft_round_trips_through_its_dict_for_the_intake_row() -> None:
    draft = d.draft_from(_route_ticket(), tracker="ado")
    body = draft.to_dict()
    assert body["item"]["id"] == "ado-4711"
    assert body["classification"]["capability_class"] == "backend.route.add"
    assert body["size_reason"] and body["kind_reason"]
