"""crb.intake.ado / crb.intake.jira — the two adapters, against a mock transport.

**No test in this file, and no job in CI, ever contacts a real Azure DevOps or Jira.**
Every request is answered by an ``httpx.MockTransport`` recorded in the test, so what is
pinned here is exactly what the product would send: the WIQL and JQL it builds, the
fields it asks for, and the writes it makes — one comment, one label, one transition,
one link, and nothing else.

Navigation
----------
What it is:   The adapter suite: protocol conformance, the queries, the idempotent
              comment, the label replacement, the transition and the link, and the
              mapping from an HTTP status to a stop reason.
What it does: Pins that a repeated comment writes nothing, that an edited comment is
              PATCHed rather than added, that setting a ``crb:`` label removes the other
              ``crb:`` labels and leaves everybody else's alone, that Jira moves an issue
              by a real transition and refuses when there is none, that a 401 is
              ``unauthorised`` while a 404 is ``column_gone``, and (C6) that the credential
              is never sent to another origin, that a 429 waits for ``Retry-After`` within a
              cap before it is ``unreachable``, and that both adapters read the ticket's
              creator.
How:          ``httpx.MockTransport`` handlers that assert on the request and return
              recorded bodies; every call is asserted, so an extra request the adapter
              made would fail the test rather than pass silently.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0017-the-ticket-is-the-backlog-item.md
Works with:   src/crb/intake/ado.py and src/crb/intake/jira.py (under test),
              src/crb/intake/http.py (the status → reason table),
              src/crb/intake/client.py (the protocol both must satisfy)
Tested by:    tests/test_intake_adapters.py
Touch when:   a tracker changes an api-version or a route — change it here first and watch
              this suite fail, never the other way round.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from crb.intake import ado, jira
from crb.intake import client as c

ORG = "https://dev.azure.invalid/contoso"
SITE = "https://contoso.atlassian.invalid"

#: A REAL marker, not a one-letter fixture: what makes a comment this product's is the
#: token ``crb:intake:<tracker>:<key>``, and a test that used ``<!-- m -->`` would pass on
#: an adapter that matched the letter "m" anywhere in somebody else's comment.
MARKER = c.marker_for("ado", "4711")
JIRA_MARKER = c.marker_for("jira", "WID-12")


def _a_real_feedback_comment() -> str:
    """The comment the product actually posts, rendered by the product's own code.

    A hand-written two-line fixture cannot catch a lossy comparison: the real comment has
    blank lines between its sections, and dropping them is exactly what broke Jira's
    idempotency.
    """
    from crb.factory.readiness import assess
    from crb.intake.draft import draft_from
    from crb.intake.feedback import render_feedback

    ticket = c.Ticket(
        key="WID-12",
        title="Fix the 500 on the export endpoint",
        body="The export endpoint returns 500 when the range is empty.",
        acceptance_criteria="Given an empty range, when exporting, then a 200 with no rows.",
        type="Bug",
        state="Ready for manufacture",
        revision="7",
        url=f"{SITE}/browse/WID-12",
    )
    draft = draft_from(ticket, tracker="jira")
    return render_feedback(draft, assess(draft.item, []), cell_route=None).text


def _client(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _ado(handler: Any, **cfg: Any) -> ado.AdoTracker:
    base = {"organisation_url": ORG, "project": "Widgets", "column": "Ready for manufacture"}
    base.update(cfg)
    return ado.AdoTracker(ado.AdoConfig(**base), "pat-token", client=_client(handler))


def _jira(handler: Any, **cfg: Any) -> jira.JiraTracker:
    base = {
        "site_url": SITE,
        "project": "WID",
        "column": "Ready for manufacture",
        "email": "bot@example.invalid",
    }
    base.update(cfg)
    return jira.JiraTracker(jira.JiraConfig(**base), "api-token", client=_client(handler))


def _json(body: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body)


# --- both adapters satisfy the protocol ---------------------------------------------


def test_both_adapters_satisfy_the_tracker_protocol() -> None:
    assert isinstance(_ado(lambda r: _json({})), c.TrackerClient)
    assert isinstance(_jira(lambda r: _json({})), c.TrackerClient)


def test_a_connection_without_a_project_or_column_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="project"):
        ado.AdoConfig(organisation_url=ORG, project="", column="Ready")
    with pytest.raises(ValueError, match="column"):
        jira.JiraConfig(site_url=SITE, project="WID", column=" ")


# --- Azure DevOps -------------------------------------------------------------------


def test_ado_asks_wiql_for_the_state_inside_the_area_path_and_returns_refs() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/wiql"):
            seen["query"] = json.loads(request.content)["query"]
            seen["auth"] = request.headers["Authorization"]
            return _json({"workItems": [{"id": 4711}]})
        assert request.url.path.endswith("/_apis/wit/workitems")
        seen["ids"] = request.url.params["ids"]
        return _json(
            {
                "value": [
                    {
                        "id": 4711,
                        "fields": {
                            ado.FIELD_TITLE: "Add a route",
                            "System.Rev": 3,
                            "System.ChangedDate": "2026-09-22T09:00:00Z",
                        },
                    }
                ]
            }
        )

    refs = _ado(handler, area_path="Widgets\\Payments").entered(
        "Ready for manufacture", "2026-09-01"
    )
    assert [r.key for r in refs] == ["4711"]
    assert refs[0].revision == "3"
    assert refs[0].url.endswith("/_workitems/edit/4711")
    assert "[System.State] = 'Ready for manufacture'" in seen["query"]
    assert "[System.AreaPath] UNDER 'Widgets\\Payments'" in seen["query"]
    assert "[System.ChangedDate] >= '2026-09-01'" in seen["query"]
    assert seen["ids"] == "4711"
    assert seen["auth"].startswith("Basic ")


def test_ado_bounds_the_wiql_query_and_the_ids_it_asks_for() -> None:
    """Azure DevOps answers a WIQL query with up to 20,000 ids, and one pass costs about
    eleven calls per ticket, so the QUERY carries the bound — and the adapter truncates to it
    even if the service ignored ``$top``."""
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/wiql"):
            seen["top"] = request.url.params["$top"]
            return _json({"workItems": [{"id": i} for i in range(1, 10)]})
        seen["ids"] = request.url.params["ids"]
        return _json({"value": [{"id": 1, "fields": {ado.FIELD_TITLE: "x"}}]})

    _ado(handler, max_refs=4).entered("Ready", "")
    assert seen["top"] == "4"
    assert seen["ids"] == "1,2,3,4"


def test_ado_refuses_a_connection_whose_bound_is_not_a_bound() -> None:
    with pytest.raises(ValueError, match="max_refs"):
        ado.AdoConfig(organisation_url=ORG, project="Widgets", column="Ready", max_refs=0)


def test_ado_escapes_a_quote_in_a_column_name_rather_than_building_broken_wiql() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["query"] = json.loads(request.content)["query"]
        return _json({"workItems": []})

    _ado(handler).entered("Dev's queue", "")
    assert "'Dev''s queue'" in seen["query"]


def test_ado_read_maps_html_acceptance_criteria_and_points_to_a_ticket() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(
            {
                "id": 4711,
                "rev": 3,
                "fields": {
                    ado.FIELD_TITLE: "Add a route",
                    ado.FIELD_DESCRIPTION: "<p>A new <b>endpoint</b></p>",
                    ado.FIELD_AC: "<ul><li>method_path: POST /health</li></ul>",
                    ado.FIELD_TAGS: "area:api; crb:needs-info",
                    ado.FIELD_TYPE: "User Story",
                    ado.FIELD_POINTS: 5,
                    ado.FIELD_STATE: "Ready for manufacture",
                    "System.Rev": 3,
                },
                "relations": [{"rel": "Hyperlink", "url": "https://github.invalid/pr/1"}],
            }
        )

    t = _ado(handler).read("4711")
    assert t.body == "A new endpoint"
    assert t.acceptance_criteria == ("- method_path: POST /health",)
    assert t.tags == ("area:api", "crb:needs-info")
    assert t.points == 5.0
    assert t.revision == "3"
    assert t.links == ("https://github.invalid/pr/1",)


def test_ado_posts_a_comment_when_the_marker_is_absent() -> None:
    posted: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _json({"comments": [{"id": 1, "text": "somebody else's comment"}]})
        assert request.method == "POST"
        posted.append(json.loads(request.content)["text"])
        return _json({"id": 2}, 201)

    _ado(handler).comment("4711", f"{MARKER}\nhello", MARKER)
    assert posted == [f"{MARKER}\nhello"]


def test_ado_writes_nothing_when_the_same_comment_is_already_there() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return _json({"comments": [{"id": 1, "text": f"{MARKER}\nhello"}]})

    _ado(handler).comment("4711", f"{MARKER}\nhello", MARKER)
    assert calls == ["GET"]


def test_ado_patches_the_existing_comment_when_the_text_changed() -> None:
    patched: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _json({"comments": [{"id": 9, "text": f"{MARKER}\nold"}]})
        assert request.method == "PATCH"
        patched.append((request.url.path, json.loads(request.content)["text"]))
        return _json({"id": 9})

    _ado(handler).comment("4711", f"{MARKER}\nnew", MARKER)
    assert patched and patched[0][0].endswith("/comments/9")
    assert patched[0][1] == f"{MARKER}\nnew"


def test_ado_names_the_comment_format_on_both_the_add_and_the_edit() -> None:
    """The renderer writes Markdown and the marker is an HTML comment. Left to the service's
    own default the comment is stored as rich text and comes back rewritten — the marker a
    re-read looks for is gone, and the same note is added again. The update route documents
    ``format`` as required, so both requests name it."""
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fmt = request.url.params.get("format", "")
        if request.method == "GET":
            return _json({"comments": [{"id": 9, "text": f"{MARKER}\nold"}]})
        seen.append((request.method, fmt))
        return _json({"id": 9})

    _ado(handler).comment("4711", f"{MARKER}\nnew", MARKER)
    assert seen == [("PATCH", "markdown")]

    posted: list[tuple[str, str]] = []

    def empty(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _json({"comments": []})
        posted.append((request.method, request.url.params.get("format", "")))
        return _json({"id": 1}, 201)

    _ado(empty).comment("4711", f"{MARKER}\nhello", MARKER)
    assert posted == [("POST", "markdown")]


def test_ado_marks_a_note_that_does_not_carry_the_marker_itself() -> None:
    """The queued, pull-request and refusal notes are rendered without a marker. Without
    this, each of them would carry no identity on the ticket and every re-read would add
    another copy — so the adapter puts the marker on, and finds it again next time."""
    posted: list[str] = []
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _json({"comments": [{"id": 1, "text": t} for t in seen]})
        posted.append(json.loads(request.content)["text"])
        seen.append(posted[-1])
        return _json({"id": len(posted)}, 201)

    note = "This ticket is now item `ado-4711` in the factory's frozen backlog."
    queued = c.marker_for("ado", "4711:queued")
    _ado(handler).comment("4711", note, queued)
    assert posted == [f"{queued}\n{note}"]
    _ado(handler).comment("4711", note, queued)
    assert len(posted) == 1  # the second call found its own marker and wrote nothing


def test_ado_label_replaces_only_the_products_own_tags() -> None:
    written: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _json({"id": 4711, "fields": {ado.FIELD_TAGS: "area:api; crb:needs-info"}})
        ops = json.loads(request.content)
        written.append(ops[0]["value"])
        return _json({"id": 4711})

    _ado(handler).label("4711", c.LABEL_QUEUED)
    assert written == ["area:api; crb:queued"]


def test_ado_label_keeps_the_classifier_tags_a_person_put_on_the_work_item() -> None:
    """``crb:class=`` / ``crb:kind=`` / ``crb:level=`` are an INPUT to the draft, not a state
    this product owns. Removed by prefix, the operator's classification left the work item —
    and because the tag write moves ``System.Rev``, the next poll drafted the same ticket
    again without it (a different class, a different size, a needless evolution)."""
    written: list[str] = []
    tags = "area:api; crb:class=backend.route.add; crb:level=L2; crb:needs-info"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _json({"id": 4711, "fields": {ado.FIELD_TAGS: tags}})
        written.append(json.loads(request.content)[0]["value"])
        return _json({"id": 4711})

    _ado(handler).label("4711", c.LABEL_QUEUED)
    assert written == ["area:api; crb:class=backend.route.add; crb:level=L2; crb:queued"]


def test_ado_label_writes_nothing_when_the_tag_is_already_the_only_crb_tag() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return _json({"id": 4711, "fields": {ado.FIELD_TAGS: "area:api; crb:queued"}})

    _ado(handler).label("4711", c.LABEL_QUEUED)
    assert methods == ["GET"]


def test_ado_transition_sets_the_state_field() -> None:
    ops: list[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        ops.append(json.loads(request.content))
        assert request.headers["Content-Type"] == "application/json-patch+json"
        return _json({"id": 4711})

    _ado(handler).transition("4711", "Done")
    assert ops == [[{"op": "add", "path": "/fields/System.State", "value": "Done"}]]


def test_ado_reports_a_state_the_board_does_not_have_as_a_refusal_not_a_missing_column() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"message": "no"}, 404)

    with pytest.raises(c.TrackerError) as err:
        _ado(handler).transition("4711", "Nowhere")
    assert err.value.reason == c.REASON_REFUSED
    assert "Nowhere" in err.value.detail


def test_ado_names_the_link_so_a_reader_knows_what_it_opens() -> None:
    """The same verb attaches the backlog item when a ticket is queued and the pull request
    when one opens, so the name travels with the URL."""
    ops: list[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _json({"id": 4711, "fields": {}, "relations": []})
        ops.append(json.loads(request.content))
        return _json({"id": 4711})

    _ado(handler).link("4711", "https://crb.invalid/factory?item=ado-4711", c.LINK_ITEM)
    value = ops[0][0]["value"]
    assert value["rel"] == "Hyperlink"
    assert value["attributes"]["comment"] == "Backlog item"


def test_ado_link_is_skipped_when_the_url_is_already_attached() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return _json(
            {"id": 4711, "fields": {}, "relations": [{"rel": "Hyperlink", "url": "https://pr"}]}
        )

    _ado(handler).link("4711", "https://pr")
    assert methods == ["GET"]


# --- Jira ----------------------------------------------------------------------------


def test_jira_asks_jql_for_the_status_in_the_project() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["jql"] = json.loads(request.content)["jql"]
        return _json(
            {
                "issues": [
                    {
                        "key": "WID-12",
                        "fields": {
                            "summary": "Add a route",
                            "updated": "2026-09-22T09:00:00.000+0000",
                        },
                    }
                ]
            }
        )

    refs = _jira(handler, jql="component = payments").entered("Ready for manufacture", "2026-09-01")
    assert [r.key for r in refs] == ["WID-12"]
    assert refs[0].revision == "2026-09-22T09:00:00.000+0000"
    assert refs[0].url == f"{SITE}/browse/WID-12"
    assert 'project = "WID"' in seen["jql"]
    assert 'status = "Ready for manufacture"' in seen["jql"]
    assert "(component = payments)" in seen["jql"]


def test_jira_pages_until_the_bound_and_never_drops_the_rest_in_silence() -> None:
    """The first version asked for one page of 200 and ignored whatever came after it. A
    column longer than the bound now comes back AT the bound, and the service — which asked
    for one more than a pass may read — stops the pass rather than reading a truncated
    column and saying nothing."""
    page_size = jira.PAGE_SIZE
    pages: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        pages.append(body)
        start = len(pages) - 1
        issues = [
            {
                "key": f"WID-{start * page_size + i}",
                "fields": {"summary": "x", "updated": "2026-09-22"},
            }
            for i in range(min(page_size, body["maxResults"]))
        ]
        return _json({"issues": issues, "nextPageToken": f"tok{len(pages)}"})

    refs = _jira(handler, max_refs=page_size + 5).entered("Ready for manufacture", "")
    assert len(refs) == page_size + 5
    assert [p["maxResults"] for p in pages] == [page_size, 5]
    assert pages[1]["nextPageToken"] == "tok1"


def test_jira_refuses_a_connection_whose_bound_is_not_a_bound() -> None:
    with pytest.raises(ValueError, match="max_refs"):
        jira.JiraConfig(site_url=SITE, project="WID", column="Ready", max_refs=0)


def test_jira_read_flattens_adf_and_reads_the_configured_points_field() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(
            {
                "key": "WID-12",
                "fields": {
                    "summary": "Add a route",
                    "description": {
                        "type": "doc",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "A new endpoint"}],
                            }
                        ],
                    },
                    "issuetype": {"name": "Story"},
                    "labels": ["area-api"],
                    "status": {"name": "Ready for manufacture"},
                    "updated": "2026-09-22T09:00:00.000+0000",
                    "customfield_10016": 8,
                },
            }
        )

    t = _jira(handler, points_field="customfield_10016").read("WID-12")
    assert t.body == "A new endpoint"
    assert t.points == 8.0
    assert t.tags == ("area-api",)
    assert t.state == "Ready for manufacture"


def _jira_posted(text: str, marker: str) -> dict[str, Any]:
    """The ADF document the adapter would post for ``text`` — the only honest fixture for
    "the comment is already there", since the adapter compares against its own shape."""
    posted: list[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _json({"comments": []})
        posted.append(json.loads(request.content)["body"])
        return _json({"id": "1"}, 201)

    _jira(handler).comment("WID-12", text, marker)
    return dict(posted[0])


def test_jira_keeps_the_marker_out_of_the_body_and_names_itself_instead() -> None:
    """ADF has no hidden node, so a marker written as an HTML comment is READ OUT on a Jira
    issue: the first paragraph of every comment literally said ``<!-- crb:intake:jira:… -->``.
    The identity is shown instead of smuggled — one attribution line a person understands —
    and the token is in it, so the same lookup still finds the comment."""
    doc = _jira_posted(f"{JIRA_MARKER}\nhello", JIRA_MARKER)
    text = jira.adf_to_text(doc)
    assert doc["type"] == "doc"
    assert "<!--" not in text
    assert text.startswith("hello")
    assert c.marker_token(JIRA_MARKER) in text
    assert "only ever edits this one comment" in text


def test_jira_renders_the_renderers_markdown_as_adf_marks_not_as_characters() -> None:
    doc = _jira_posted(f"{JIRA_MARKER}\n**What is missing** the `acceptance` slot", JIRA_MARKER)
    nodes = [n for p in doc["content"] for n in (p.get("content") or [])]
    strong = [n["text"] for n in nodes if {"type": "strong"} in (n.get("marks") or [])]
    code = [n["text"] for n in nodes if {"type": "code"} in (n.get("marks") or [])]
    assert strong == ["What is missing"]
    assert code == ["acceptance"]
    assert not any("**" in n["text"] or "`" in n["text"] for n in nodes)


def test_jira_writes_nothing_when_the_same_comment_is_already_there() -> None:
    methods: list[str] = []
    already = _jira_posted(f"{JIRA_MARKER}\nhello", JIRA_MARKER)

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return _json({"comments": [{"id": "1", "body": already}]})

    _jira(handler).comment("WID-12", f"{JIRA_MARKER}\nhello", JIRA_MARKER)
    assert methods == ["GET"]


def test_jira_writes_nothing_when_the_products_own_comment_is_already_there() -> None:
    """The regression the two-line fixture above cannot catch. ``adf_to_text`` drops blank
    lines, and every comment the renderer produces has them, so comparing the text the
    product holds against the flattened text Jira returns was never equal for a REAL
    comment: the same unchanged comment was rewritten on every poll, for ever."""
    text = _a_real_feedback_comment()
    assert "\n\n" in text, "the fixture must be the real comment, blank lines and all"
    already = _jira_posted(text, JIRA_MARKER)
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return _json({"comments": [{"id": "1", "body": already}]})

    _jira(handler).comment("WID-12", text, JIRA_MARKER)
    assert methods == ["GET"], "the same comment was rewritten"


def test_jira_names_the_remote_link_by_what_it_points_at() -> None:
    """A Jira remote link SHOWS its title. Hard-coding "Pull request" labelled the queued
    link — attached long before any pull request exists — as something that did not exist."""
    posted: list[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        posted.append(json.loads(request.content))
        return _json({"id": 1}, 201)

    t = _jira(handler)
    t.link("WID-12", "https://crb.invalid/factory?item=jira-wid-12", c.LINK_ITEM)
    t.link("WID-12", "https://github.invalid/o/r/pull/7", c.LINK_PULL_REQUEST)
    assert [p["object"]["title"] for p in posted] == ["Backlog item", "Pull request"]
    assert posted[0]["globalId"] == posted[0]["object"]["url"]


def test_jira_label_removes_the_other_crb_labels_and_adds_the_wanted_one() -> None:
    updates: list[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _json({"key": "WID-12", "fields": {"labels": ["area-api", "crb:needs-info"]}})
        updates.append(json.loads(request.content)["update"]["labels"])
        return httpx.Response(204)

    _jira(handler).label("WID-12", c.LABEL_QUEUED)
    assert updates == [[{"remove": "crb:needs-info"}, {"add": "crb:queued"}]]


def test_jira_label_keeps_the_classifier_labels_somebody_put_on_the_issue() -> None:
    """The state label replaces the other three and nothing else. Jira's ticket revision is
    ``fields.updated``, so a label write that deleted ``crb:level=L2`` also made the next
    draft read the issue as L1."""
    updates: list[Any] = []
    labels = ["area-api", "crb:class=backend.route.add", "crb:level=L2", "crb:ready"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _json({"key": "WID-12", "fields": {"labels": labels}})
        updates.append(json.loads(request.content)["update"]["labels"])
        return httpx.Response(204)

    _jira(handler).label("WID-12", c.LABEL_QUEUED)
    assert updates == [[{"remove": "crb:ready"}, {"add": "crb:queued"}]]


def test_jira_moves_the_issue_by_the_transition_that_lands_on_the_status() -> None:
    posted: list[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _json(
                {
                    "transitions": [
                        {"id": "11", "to": {"name": "In progress"}},
                        {"id": "31", "to": {"name": "Done"}},
                    ]
                }
            )
        posted.append(json.loads(request.content))
        return httpx.Response(204)

    _jira(handler).transition("WID-12", "done")
    assert posted == [{"transition": {"id": "31"}}]


def test_jira_refuses_rather_than_forces_a_status_the_workflow_does_not_offer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"transitions": [{"id": "11", "to": {"name": "In progress"}}]})

    with pytest.raises(c.TrackerError) as err:
        _jira(handler).transition("WID-12", "Done")
    assert err.value.reason == c.REASON_REFUSED
    assert "no transition" in err.value.detail


# --- the error vocabulary -------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (401, c.REASON_UNAUTHORISED),
        (403, c.REASON_UNAUTHORISED),
        (404, c.REASON_COLUMN_GONE),
        (400, c.REASON_REFUSED),
        (503, c.REASON_UNREACHABLE),
    ],
)
def test_a_status_maps_to_the_published_stop_reason(status: int, reason: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"message": "…"}, status)

    with pytest.raises(c.TrackerError) as err:
        _ado(handler).entered("Ready", "")
    assert err.value.reason == reason
    assert err.value.advice


def test_a_transport_failure_is_unreachable_and_never_shows_the_credential() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    with pytest.raises(c.TrackerError) as err:
        _ado(handler).entered("Ready", "")
    assert err.value.reason == c.REASON_UNREACHABLE
    assert "pat-token" not in str(err.value)


def test_an_error_message_never_repeats_the_trackers_body_or_the_query_string() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"message": "customer name leaked here"}, 400)

    with pytest.raises(c.TrackerError) as err:
        _ado(handler).read("4711")
    assert "customer name" not in str(err.value)
    assert "?" not in err.value.detail


# --- C6 (assessment 2026-09-25): the credential's origin, rate limits, the author -----


def test_an_absolute_url_on_another_origin_is_refused_and_never_sent_the_credential() -> None:
    """C6(e): ``request`` used an absolute URL as-is, so a caller handing it one on another
    host would have sent the tracker credential there. The request URL's origin (scheme,
    host, port) must equal ``base_url``'s; anything else is refused before the transport
    is touched."""
    from crb.intake.http import TrackerHttp

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return _json({"ok": True})

    http = TrackerHttp(f"{ORG}/Widgets", "Basic secret", client=_client(handler))
    for url in (
        "https://evil.invalid/steal",
        "http://dev.azure.invalid/contoso/Widgets/_apis/x",  # same host, another scheme
        "https://dev.azure.invalid:8443/contoso/_apis/x",  # same host, another port
        "https://dev.azure.invalid.evil.invalid/_apis/x",  # a lookalike host
    ):
        with pytest.raises(c.TrackerError) as err:
            http.get(url)
        assert err.value.reason == c.REASON_REFUSED
        assert "secret" not in str(err.value)
    assert seen == []
    # the same origin, absolute or relative, is served
    assert http.get(f"{ORG}/Widgets/_apis/wit/workitems/1") == {"ok": True}
    assert http.get("_apis/wit/workitems/1") == {"ok": True}
    # a relative path that merely STARTS with "http" is a path, not an absolute URL
    assert http.get("httpbin/x") == {"ok": True}
    assert seen[-1] == f"{ORG}/Widgets/httpbin/x"


def test_a_429_honours_retry_after_with_a_capped_backoff() -> None:
    """C6(d): HTTP 429 was ``unreachable`` at once, so a busy tracker stopped the pass. A
    429 now waits for ``Retry-After`` (seconds or an HTTP date) — never longer than the cap
    — and retries a bounded number of times; with no header the wait doubles from one
    second. Only after the last retry is it ``unreachable``, and the detail says so."""
    from crb.intake import http as th

    answers = [
        httpx.Response(429, headers={"Retry-After": "2"}),
        httpx.Response(429, headers={"Retry-After": "3600"}),  # far beyond the cap
        httpx.Response(200, json={"ok": True}),
    ]
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return answers.pop(0)

    http = th.TrackerHttp(ORG, "Basic x", client=_client(handler), sleep=slept.append)
    assert http.get("_apis/x") == {"ok": True}
    assert slept == [2.0, th.MAX_RETRY_WAIT_S]

    # no header: 1 s, then 2 s — and after the last retry, unreachable with the reason
    slept.clear()

    def always_429(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    http = th.TrackerHttp(ORG, "Basic x", client=_client(always_429), sleep=slept.append)
    with pytest.raises(c.TrackerError) as err:
        http.get("_apis/x")
    assert err.value.reason == c.REASON_UNREACHABLE
    assert "rate" in err.value.detail and "429" in err.value.detail
    assert slept == [1.0, 2.0][: th.MAX_RETRIES]
    assert len(slept) == th.MAX_RETRIES
    assert all(s <= th.MAX_RETRY_WAIT_S for s in slept)


def test_a_retry_after_http_date_is_read_and_capped() -> None:
    from datetime import UTC, datetime, timedelta
    from email.utils import format_datetime

    from crb.intake import http as th

    when = format_datetime(datetime.now(UTC) + timedelta(seconds=4), usegmt=True)
    assert 0.0 <= th.retry_after_seconds(when) <= 4.0
    assert th.retry_after_seconds("7") == 7.0
    assert th.retry_after_seconds("") is None
    assert th.retry_after_seconds("soon") is None
    assert th.retry_after_seconds("-5") == 0.0


def test_the_adapters_read_who_created_the_ticket() -> None:
    """C6(a): the allowlist that may bypass operator approval is a list of tracker AUTHORS,
    so each adapter reads who created the ticket — Azure DevOps' ``System.CreatedBy``
    unique name, Jira's ``creator`` email address (its account id when the email is
    hidden)."""

    def ado_handler(request: httpx.Request) -> httpx.Response:
        return _json(
            {
                "id": 4711,
                "fields": {
                    ado.FIELD_TITLE: "Add a route",
                    "System.CreatedBy": {"displayName": "Ada", "uniqueName": "Ada@Contoso.com"},
                },
            }
        )

    assert _ado(ado_handler).read("4711").author == "ada@contoso.com"

    def jira_handler(request: httpx.Request) -> httpx.Response:
        assert "creator" in request.url.params["fields"].split(",")
        return _json(
            {
                "key": "WID-12",
                "fields": {"summary": "x", "creator": {"accountId": "5b10ac8d82e05b22cc7d4ef5"}},
            }
        )

    assert _jira(jira_handler).read("WID-12").author == "5b10ac8d82e05b22cc7d4ef5"
