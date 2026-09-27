"""``POST /repos/{name}/baseline-read`` — the server's record that a person read the baseline.

Home task 6 is called "Read the baseline", and until this record it could complete only on an
active sign-off, so a baseline read and not signed never completed and the tag contradicted the
task's own name (G-165). The decision (DL-074): the Baseline screen tells the server when a
person has the map of a repository with rows in front of them; the server appends one
``repo.baseline_read`` event per person per repository on the repository's audit trace; and
``GET /repos/{name}`` serves the first such read as ``baseline_read: {at, by}``, which is what
Home reads. A GET never writes: the record is its own POST, CSRF-protected like every write.

Navigation
----------
What it is:   The suite for the baseline-read record and the field Home reads.
What it does: Pins that a viewer may record a read (the least role that can open the map) and
              an anonymous caller may not; that the record is refused with 409
              ``baseline_empty`` for a repository with no graded row — there is nothing to
              read — and 404 for an unknown one; that the first read appends one
              ``repo.baseline_read`` event naming the actor and the rows read, and a second read
              by the same person writes nothing and answers the first; that a second person's
              read is recorded too but ``baseline_read`` keeps the first; and that
              ``GET /repos/{name}`` serves ``baseline_read: null`` until a read.
How:          ``make_env`` over the seed (``alpha`` has graded rows, ``beta`` has none);
              ``login`` switches the person.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none (DL-074)
Works with:   src/crb/server/routes/repos.py (the route and ``repo_detail``),
              src/crb/server/schemas.py (``BaselineRead``), tests/fixtures/server_seed.py
              (``alpha`` has graded rows, ``beta`` none), docs/API.md (the route row and
              the event vocabulary), ui/src/screens/Home/HomePage.tsx (task 6 reads the
              field)
Tested by:    tests/test_server_baseline_read.py
Touch when:   what counts as "read the baseline" changes — change DL-074 first.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import select

from crb.server.routes.runs import system_trace_id
from crb.store.models import Event
from fixtures.server_seed import (
    ALPHA,
    BETA,
    USERS,
    Env,
    assert_rbac,
    envelope,
    login,
    make_env,
    user_id,
)


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path, role="viewer") as e:
        yield e


def _reads(env: Env, repo: str) -> list[Event]:
    with env.factory() as s:
        return list(
            s.execute(
                select(Event)
                .where(Event.trace_id == system_trace_id("repo", repo))
                .where(Event.action == "repo.baseline_read")
                .order_by(Event.seq)
            ).scalars()
        )


def test_a_viewer_may_record_a_read_and_an_anonymous_caller_may_not(env: Env) -> None:
    assert_rbac(env, "POST", f"/repos/{ALPHA}/baseline-read", min_role="viewer")


def test_before_any_read_the_repository_serves_no_baseline_read(env: Env) -> None:
    body = env.get(f"/repos/{ALPHA}").json()
    assert "baseline_read" in body
    assert body["baseline_read"] is None


def test_the_first_read_is_recorded_once_per_person_with_who_and_how_many_rows(env: Env) -> None:
    r = env.post(f"/repos/{ALPHA}/baseline-read")
    assert r.status_code == 201, r.text
    first = r.json()
    assert (
        first["repo"] == ALPHA
        and first["by"] == user_id(USERS["viewer"])
        and first["recorded"] is True
    )
    assert first["rows"] > 0 and first["at"]
    events = _reads(env, ALPHA)
    assert len(events) == 1
    assert events[0].actor == user_id(USERS["viewer"]) and events[0].stage == "system"
    # the same person again: nothing new is written, the first read is answered
    again = env.post(f"/repos/{ALPHA}/baseline-read")
    assert again.status_code == 200, again.text
    assert again.json()["recorded"] is False and again.json()["at"] == first["at"]
    assert len(_reads(env, ALPHA)) == 1
    # Home reads the first read from the repository itself
    detail = env.get(f"/repos/{ALPHA}").json()
    assert detail["baseline_read"] == {"at": first["at"], "by": user_id(USERS["viewer"])}


def test_a_second_person_is_recorded_too_and_the_repository_keeps_the_first_read(env: Env) -> None:
    first = env.post(f"/repos/{ALPHA}/baseline-read").json()
    login(env.client, "operator")
    second = env.post(f"/repos/{ALPHA}/baseline-read")
    assert second.status_code == 201 and second.json()["by"] == user_id(USERS["operator"])
    assert [e.actor for e in _reads(env, ALPHA)] == [
        user_id(USERS["viewer"]),
        user_id(USERS["operator"]),
    ]
    assert env.get(f"/repos/{ALPHA}").json()["baseline_read"]["by"] == first["by"]


def test_a_repository_with_no_graded_row_has_no_baseline_to_read(env: Env) -> None:
    r = env.post(f"/repos/{BETA}/baseline-read")
    assert r.status_code == 409
    assert envelope(r)["code"] == "baseline_empty"
    assert _reads(env, BETA) == []
    assert env.get(f"/repos/{BETA}").json()["baseline_read"] is None


def test_an_unknown_repository_is_404(env: Env) -> None:
    r = env.post("/repos/nope/baseline-read")
    assert r.status_code == 404
    assert envelope(r)["code"] == "not_found"
