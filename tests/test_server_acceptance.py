"""``/factory/{repo}/acceptance`` — a second person's held-out acceptance tests (ADR-0026 item 8).

Navigation
----------
What it is:   The route suite for G-679's write path: the assignment list a person answers
              and the write that stores held-out acceptance tests for a calibration build.
What it does: Pins that the assignment shows the ticket (title, description, criteria, class,
              size, who funded it) and never its failing test; that a second person — not the
              ticket's author, not the funding approver, operator role or above — writes the
              tests once per grant, stored with their author, time and digest and served back
              without their content; and every refusal: no person's test, no grant, a build
              started or done before, a second record, a path outside the repository or not
              a test file or the ticket's own test, and text shaped like a credential.
How:          The API's own store (``fixtures.server_seed.make_env``): the backlog through
              ``POST /factory/{repo}/backlog``, the grant through the calibration route, the
              chain through ``FactoryHome``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (item 8)
Works with:   src/crb/server/routes/acceptance.py (under test), src/crb/server/acceptance.py
              (the store), src/crb/core/acceptance.py (the record), tests/fixtures/server_seed.py
              (the API and its store)
Tested by:    this file
Touch when:   never for a new repository; a refusal or a field of the assignment changes.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from crb.core.acceptance import EVENT_ACTION, HeldOutTests, trace_for
from crb.server.factory_state import FactoryHome
from crb.store.models import Event
from fixtures.server_seed import ALPHA, Env, envelope, login, make_env, user_id

TEST_SRC = "from calc import multiply\n\n\ndef test_multiply():\n    assert multiply(3, 4) == 12\n"
HELD_OUT = (
    "from calc import multiply\n\n\n"
    "def test_multiply_held_out_by_a_second_person():\n"
    "    assert multiply(7, 6) == 42\n"
)
ITEM: dict[str, Any] = {
    "id": "I-1",
    "title": "Add multiply to calc",
    "kind": "code",
    "description": "calc needs a multiply(a, b) function.",
    "acceptance_criteria": ["multiply(3, 4) == 12"],
    "capability_class": "bug.fix",
    "size_estimate": "XS",
    "structural_facts": [
        "reproduction: `from calc import multiply` raises ImportError",
        "expected_behaviour: calc exposes multiply(a: int, b: int) -> int",
    ],
}
URL = f"/factory/{ALPHA}/items/I-1/acceptance"
LIST = f"/factory/{ALPHA}/acceptance"
BODY = {"files": [{"path": "tests/test_multiply_held_out.py", "content": HELD_OUT}]}


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path) as e:
        yield e


def _register(env: Env, *, authored: bool = True) -> None:
    login(env.client, "operator")
    extra = (
        {"authored": {"I-1": {"path": "tests/test_multiply.py", "content": TEST_SRC}}}
        if authored
        else {}
    )
    r = env.post(f"/factory/{ALPHA}/backlog", json={"items": [ITEM], **extra})
    assert r.status_code == 201, r.text


def _fund(env: Env) -> str:
    login(env.client, "approver")
    r = env.post(f"/factory/{ALPHA}/items/I-1/calibration", json={"reason": "forward reading"})
    assert r.status_code == 201, r.text
    return str(r.json()["event"])


def _stored(env: Env) -> list[dict[str, Any]]:
    with env.factory() as s:
        return [
            dict(e.payload_json or {})
            for e in s.execute(
                select(Event).where(
                    Event.trace_id == trace_for(ALPHA), Event.action == EVENT_ACTION
                )
            ).scalars()
        ]


def test_a_second_person_writes_held_out_tests_from_the_ticket_alone(env: Env) -> None:
    _register(env)
    grant = _fund(env)
    login(env.client, "admin")  # neither the ticket's author nor the approver who funded it
    r = env.get(LIST)
    assert r.status_code == 200, r.text
    (a,) = r.json()["assignments"]
    assert a["item_id"] == "I-1" and a["status"] == "open" and a["can_write"] is True
    assert a["title"] == ITEM["title"] and a["acceptance_criteria"] == ITEM["acceptance_criteria"]
    assert a["grant"] == grant and a["funded_by"] == user_id("appr1") and a["record"] is None
    # the ticket's own failing test is never shown to the person who writes the held-out ones
    assert "assert multiply(3, 4) == 12" not in r.text and "tests/test_multiply.py" not in r.text

    r = env.post(URL, json=BODY)
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["author"] == f"operator:{user_id('root')}" and rec["grant"] == grant
    assert rec["paths"] == ["tests/test_multiply_held_out.py"] and len(rec["sha256"]) == 64
    assert "content" not in rec and HELD_OUT not in r.text
    # stored whole, with its author, time and digest — and it verifies
    (stored,) = _stored(env)
    held = HeldOutTests.from_dict(stored)
    assert held.verify() and held.files == (("tests/test_multiply_held_out.py", HELD_OUT),)
    assert held.written_at and held.sha256 == rec["sha256"]
    (a,) = env.get(LIST).json()["assignments"]
    assert a["status"] == "written" and a["can_write"] is False and a["record"]["sha256"]
    assert HELD_OUT not in env.get(LIST).text
    # one record per calibration build
    r = env.post(URL, json=BODY)
    assert r.status_code == 409 and envelope(r)["code"] == "acceptance_written"


def test_the_tickets_author_and_the_funding_approver_may_not_write_them(env: Env) -> None:
    _register(env)
    _fund(env)
    for role, why in (("operator", "author"), ("approver", "funded")):
        login(env.client, role)
        (a,) = env.get(LIST).json()["assignments"]
        assert a["can_write"] is False and why in a["why_not"], (role, a["why_not"])
        r = env.post(URL, json=BODY)
        assert r.status_code == 403 and envelope(r)["code"] == "acceptance_same_person", role
    login(env.client, "viewer")
    (a,) = env.get(LIST).json()["assignments"]
    assert a["can_write"] is False and "operator role" in a["why_not"]
    assert env.post(URL, json=BODY).status_code == 403
    assert _stored(env) == []


def test_there_is_nothing_to_write_without_a_persons_test_or_a_grant(env: Env) -> None:
    _register(env, authored=False)
    login(env.client, "admin")
    assert env.get(LIST).json()["assignments"] == []
    r = env.post(URL, json=BODY)
    assert r.status_code == 409 and envelope(r)["code"] == "acceptance_not_needed"

    _register(env)
    login(env.client, "admin")
    r = env.post(URL, json=BODY)
    assert r.status_code == 409 and envelope(r)["code"] == "no_calibration_build"
    assert env.get(LIST).json()["assignments"] == []


def test_tests_are_refused_once_the_build_has_started_or_the_ticket_was_built(env: Env) -> None:
    _register(env)
    grant = _fund(env)
    home = FactoryHome(env.settings.home, ALPHA)
    assert home.evidence(actor="worker").claim_calibration("I-1", grant, run_id="run-1")
    login(env.client, "admin")
    (a,) = env.get(LIST).json()["assignments"]
    assert a["status"] == "building" and a["can_write"] is False
    r = env.post(URL, json=BODY)
    assert r.status_code == 409 and envelope(r)["code"] == "build_started"

    ev = home.evidence(actor="worker")
    ev.record_build(
        "I-1",
        pack_hash="p",
        row_id="r",
        row_hash="h",
        clean=False,
        belts={},
        rung="fake:multi",
        trial="r1",
        oracle_commit="c",
        test_sha256="t",
    )
    _fund(env)  # a second grant, on a ticket already built
    login(env.client, "admin")
    (a,) = env.get(LIST).json()["assignments"]
    # the ticket cannot be graded again: its tag says so, not "tests needed" (verify_fwd_user)
    assert a["status"] == "cannot_grade" and a["can_write"] is False
    assert "attempted before" in a["why_not"]
    r = env.post(URL, json=BODY)
    assert r.status_code == 409 and envelope(r)["code"] == "already_built"


@pytest.mark.parametrize(
    ("path", "content", "why"),
    [
        ("../outside/test_x.py", HELD_OUT, "plain relative path"),
        ("/etc/test_x.py", HELD_OUT, "relative path"),
        ("tests/test_multiply.py", HELD_OUT, "already carries"),
        ("src/calc_extra.py", HELD_OUT, "not a test file"),
        ("tests/test_key.py", 'KEY = "sk-ant-api03-' + "a" * 40 + '"\n', "credential"),
    ],
)
def test_a_file_that_cannot_hold_a_held_out_test_is_refused(
    env: Env, path: str, content: str, why: str
) -> None:
    _register(env)
    _fund(env)
    login(env.client, "admin")
    r = env.post(URL, json={"files": [{"path": path, "content": content}]})
    assert r.status_code == 422, r.text
    assert why in envelope(r)["message"]
    assert _stored(env) == []


def test_a_claimed_grant_makes_the_ticket_attempted_even_with_no_build(env: Env) -> None:
    """verify_fwd_attack: a run that claimed its grant and died before recording a build left
    the chain with no ``build.graded``, and a second grant's tests were accepted (201) — its
    build's first attempt, the ticket's second, would have been stamped S2. The write route,
    the list and the loop now share one predicate (``attempted_before``, P-692)."""
    _register(env)
    first = _fund(env)
    login(env.client, "admin")
    assert env.post(URL, json=BODY).status_code == 201
    home = FactoryHome(env.settings.home, ALPHA)
    assert home.evidence(actor="worker").claim_calibration("I-1", first, run_id="died")
    _fund(env)  # a second grant: the first is spent
    login(env.client, "admin")
    (a,) = env.get(LIST).json()["assignments"]
    assert a["status"] == "cannot_grade" and a["can_write"] is False
    r = env.post(URL, json=BODY)
    assert r.status_code == 409 and envelope(r)["code"] == "already_built"
    assert len(_stored(env)) == 1


@pytest.mark.parametrize("record", ["freeze", "evolve"])
def test_whoever_froze_or_evolved_the_backlog_may_not_write_them(env: Env, record: str) -> None:
    """verify_fwd_evidence F7b: the ticket's author is also whoever froze a backlog naming it
    or registered it as an evolution — here the admin, not the operator whose test it carries."""
    _register(env)
    _fund(env)
    home = FactoryHome(env.settings.home, ALPHA)
    by_root = home.evidence(actor=f"operator:{user_id('root')}")
    if record == "freeze":
        by_root.record_freeze(backlog_hash="b" * 64, item_ids=["I-1"], frozen_at="2026-01-01")
    else:
        by_root.record_evolution(
            item_id="I-1", supersedes="I-0", backlog_hash="b" * 64, evolutions_hash="e"
        )
    login(env.client, "admin")
    (a,) = env.get(LIST).json()["assignments"]
    assert a["can_write"] is False and "author" in a["why_not"]
    r = env.post(URL, json=BODY)
    assert r.status_code == 403 and envelope(r)["code"] == "acceptance_same_person"
    assert _stored(env) == []


def test_a_record_that_does_not_re_hash_is_left_out(env: Env) -> None:
    """factory-acceptance.operations.11: a stored record whose content no longer matches its
    digest grades nothing and enrols nothing — ``load_held_out`` leaves it out, so the list
    still reads ``tests needed`` and the loop's reader finds no tests."""
    from crb.server.acceptance import held_out_reader, load_held_out
    from crb.store.events import append_event_checked

    _register(env)
    grant = _fund(env)
    rec = HeldOutTests(
        repo=ALPHA,
        item_id="I-1",
        grant=grant,
        files=(("tests/test_multiply_held_out.py", HELD_OUT),),
        author="operator:someone",
        written_at="2026-01-01T00:00:00+00:00",
    )
    forged = {**rec.to_dict(), "files": [["tests/test_multiply_held_out.py", "assert True\n"]]}
    append_event_checked(
        env.factory,
        trace_id=trace_for(ALPHA),
        stage="system",
        action=EVENT_ACTION,
        build=lambda _s: forged,
        actor="someone",
        repo=ALPHA,
    )
    assert len(_stored(env)) == 1
    with env.factory() as s:
        assert load_held_out(s, ALPHA) == []
    assert held_out_reader(env.factory, ALPHA)("I-1", grant) is None
    login(env.client, "admin")
    (a,) = env.get(LIST).json()["assignments"]
    assert a["status"] == "open" and a["record"] is None and a["can_write"] is True


def test_an_assignment_ends_when_its_build_ran_without_the_tests(env: Env) -> None:
    """verify_fwd_user: the tag read "being built" for ever after a run built without the tests.
    ``acceptance.not_graded`` (recorded before the build) ends it with why."""
    _register(env)
    grant = _fund(env)
    home = FactoryHome(env.settings.home, ALPHA)
    ev = home.evidence(actor="worker")
    assert ev.claim_calibration("I-1", grant, run_id="run-1")
    ev.record_acceptance_not_graded("I-1", grant=grant, why="no_held_out_tests")
    login(env.client, "admin")
    (a,) = env.get(LIST).json()["assignments"]
    assert a["status"] == "not_graded" and a["can_write"] is False
    assert "before any held-out tests were written" in a["why_not"]


def test_the_list_names_people_suggests_a_path_and_says_no_reading_counts_it(env: Env) -> None:
    """verify_fwd_user: the page cut every identity to 8 characters, pre-filled a Python path
    on every repository and promised a miss for a reading that did not exist."""
    _register(env)
    _fund(env)
    login(env.client, "admin")
    (a,) = env.get(LIST).json()["assignments"]
    assert a["funded_by_name"] == "appr1" and a["author_name"] == ""
    assert a["suggested_path"] == "tests/test_i_1_held_out.py"
    assert a["forward_reading"] == "" and a["counted_by"] == ""
    assert env.post(URL, json=BODY).status_code == 201
    (a,) = env.get(LIST).json()["assignments"]
    assert a["author_name"] == "root"


def test_a_path_that_is_not_a_test_is_answered_with_one_that_is(env: Env) -> None:
    _register(env)
    _fund(env)
    login(env.client, "admin")
    r = env.post(URL, json={"files": [{"path": "src/calc_extra.py", "content": HELD_OUT}]})
    assert r.status_code == 422
    assert "for example, 'tests/test_i_1_held_out.py'" in envelope(r)["message"]
