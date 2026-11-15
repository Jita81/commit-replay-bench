"""``/ctxsets`` — store, read and compare context sets over HTTP (ADR-0050).

Navigation
----------
What it is:   The route suite for ``POST /ctxsets``, ``GET /ctxsets/compare`` and
              ``GET /ctxsets/{name}``.
What it does: Pins the store's RBAC (operator), its content-addressed write and its
              ``ctxset.stored`` event, idempotence on the same body and 409 on a different
              body at one digest, the coverage and placebo refusals, that ``compare`` is never
              read as a set name, that a read never returns an entry's text, and the paired
              comparison over two seeded runs (banner, counts, refusals).
How:          ``make_env`` over the seed; the set names seed tasks of ``alpha``; the runs'
              rows are appended through ``DbLedger`` as a run writes them.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0050-context-set-arms.md
Works with:   src/crb/server/routes/ctxsets.py (under test), tests/fixtures/ctx_rows.py
              (the set documents and the stamped rows), tests/fixtures/server_seed.py (the
              seeded app, its users and the RBAC check), src/crb/core/ctx_compare.py (the
              reader behind ``GET /ctxsets/compare``)
Tested by:    tests/test_server_ctxsets.py
Touch when:   never for a new repository; a ``/ctxsets`` route changes shape (mirror
              docs/API.md#context-sets).
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from crb.core import ctx_compare as cc
from crb.core import ctxset
from crb.core.ledger import GradeRow
from crb.server.routes import ctxsets as ctxsets_route
from crb.server.routes.ctxsets import (
    ACTION_STORED,
    REFUSAL_CONFLICT,
    REFUSAL_NOT_STORED,
    store_dir,
)
from crb.store.ledger import DbLedger
from crb.store.models import Event, Run
from fixtures.ctx_rows import ctx_doc, req_doc, side
from fixtures.server_seed import ALPHA, Env, assert_rbac, envelope, make_env

SECRET = "The handler reads the flag before parsing; the fix moves the read."


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path) as e:
        yield e


def _tasks(env: Env) -> list[str]:
    return [env.info.task(i).task_id for i in (1, 2, 3, 4)]


def _doc(env: Env, source: str = ctxset.SOURCE_ORACLE, **kw: Any) -> dict[str, Any]:
    kw.setdefault("text", SECRET)
    return ctx_doc(source, tasks=_tasks(env), repo=ALPHA, **kw)


def _put(env: Env, doc: dict[str, Any]) -> Any:
    return env.post("/ctxsets", json=doc)


class TestStore:
    def test_rbac_is_operator(self, env: Env) -> None:
        assert_rbac(env, "POST", "/ctxsets", min_role="operator", json=_doc(env))

    def test_content_addressed_write_and_event(self, env: Env) -> None:
        r = _put(env, _doc(env))
        assert r.status_code == 201, r.text
        body = r.json()
        parsed = ctxset.parse(_doc(env))
        assert body["stored"] is True and body["digest"] == parsed.digest
        assert body["name"] == parsed.name and body["arm"] == parsed.arm
        assert body["measurement_only"] is True and body["tasks"] == 4
        path = store_dir(env.settings) / f"{parsed.digest}.json"
        assert path.is_file()
        assert ctxset.parse(path.read_text(encoding="utf-8")).digest == parsed.digest
        with env.factory() as s:
            events = list(s.execute(select(Event).where(Event.action == "ctxset.stored")).scalars())
        assert len(events) == 1
        assert events[0].payload_json["digest"] == parsed.digest
        assert SECRET not in json.dumps(events[0].payload_json)

    def test_same_body_again_is_idempotent(self, env: Env) -> None:
        assert _put(env, _doc(env)).status_code == 201
        again = _put(env, _doc(env))
        assert again.status_code == 201 and again.json()["stored"] is False
        with env.factory() as s:
            n = len(list(s.execute(select(Event).where(Event.action == "ctxset.stored"))))
        assert n == 1

    def test_identical_retry_writes_a_missing_stored_event_once(self, env: Env) -> None:
        """An earlier store published the file but its event never committed: the identical
        retry records the event (the payload a new store writes), and a later retry adds no
        second one."""
        parsed = ctxset.parse(_doc(env))
        path = store_dir(env.settings) / f"{parsed.digest}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(ctxset.canonical_json(parsed.to_doc()), encoding="utf-8")
        for _ in range(2):
            again = _put(env, _doc(env))
            assert again.status_code == 201 and again.json()["stored"] is False
            with env.factory() as s:
                events = list(
                    s.execute(select(Event).where(Event.action == ACTION_STORED)).scalars()
                )
            assert len(events) == 1
            assert events[0].payload_json == {
                "digest": parsed.digest,
                "name": parsed.name,
                "source": parsed.source,
                "repo": ALPHA,
                "tasks": 4,
            }

    def test_a_concurrent_identical_store_answers_the_idempotent_result(
        self, env: Env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Another request publishes the same set between this request's check and its
        publish: this one answers ``stored: false`` (no 500, no overwrite) and leaves no
        temporary file behind."""
        parsed = ctxset.parse(_doc(env))
        text = ctxset.canonical_json(parsed.to_doc())
        path = store_dir(env.settings) / f"{parsed.digest}.json"
        real = ctxsets_route._publish

        def raced(dest: Path, body: str) -> bool:
            assert real(dest, body)  # the other request wins
            return real(dest, body)

        monkeypatch.setattr(ctxsets_route, "_publish", raced)
        r = _put(env, _doc(env))
        assert r.status_code == 201, r.text
        assert r.json()["stored"] is False
        assert path.read_text(encoding="utf-8") == text
        assert sorted(p.name for p in path.parent.iterdir()) == [path.name]

    def test_a_retry_racing_the_publisher_never_writes_a_second_event(
        self, env: Env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An identical retry sees the file this request just published and records the
        event before this request does: this request answers ``stored: true`` and the set
        still carries exactly one ``ctxset.stored`` event."""
        parsed = ctxset.parse(_doc(env))
        real = ctxsets_route._publish

        def retry_between(dest: Path, body: str) -> bool:
            won = real(dest, body)
            again = _put(env, _doc(env))  # the retry, between this publish and its event
            assert again.status_code == 201 and again.json()["stored"] is False
            return won

        monkeypatch.setattr(ctxsets_route, "_publish", retry_between)
        r = _put(env, _doc(env))
        assert r.status_code == 201, r.text
        assert r.json()["stored"] is True
        with env.factory() as s:
            events = list(s.execute(select(Event).where(Event.action == ACTION_STORED)).scalars())
        assert len(events) == 1
        assert events[0].payload_json["digest"] == parsed.digest

    def test_publish_never_replaces_an_existing_file(self, tmp_path: Path) -> None:
        dest = tmp_path / "set.json"
        assert ctxsets_route._publish(dest, "first") is True
        assert ctxsets_route._publish(dest, "second") is False
        assert dest.read_text(encoding="utf-8") == "first"
        assert [p.name for p in tmp_path.iterdir()] == ["set.json"]

    def test_different_body_at_one_digest_is_409(self, env: Env) -> None:
        digest = ctxset.parse(_doc(env)).digest
        path = store_dir(env.settings) / f"{digest}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"tampered": true}', encoding="utf-8")
        r = _put(env, _doc(env))
        assert r.status_code == 409 and envelope(r)["code"] == REFUSAL_CONFLICT
        assert path.read_text(encoding="utf-8") == '{"tampered": true}'  # never overwritten

    def test_unknown_task_is_coverage_422(self, env: Env) -> None:
        doc = ctx_doc(tasks=[*_tasks(env), "f" * 40], repo=ALPHA)
        r = _put(env, doc)
        assert r.status_code == 422 and envelope(r)["code"] == ctxset.REASON_COVERAGE

    def test_not_gold_clean_is_coverage_422(self, env: Env) -> None:
        doc = ctx_doc(tasks=[env.info.task(8).task_id], repo=ALPHA)
        r = _put(env, doc)
        assert r.status_code == 422 and envelope(r)["code"] == ctxset.REASON_COVERAGE

    def test_stored_set_is_owner_only_and_synced_before_the_event(
        self, env: Env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The body, its directory entry and the store directory's own entry are flushed
        to disk before the store is acknowledged (a retry flushes both directories again),
        and the file is never widened past the owner."""
        synced: list[bool] = []
        real_fsync = os.fsync

        def spy(fd: int) -> None:
            synced.append(stat.S_ISDIR(os.fstat(fd).st_mode))
            real_fsync(fd)

        monkeypatch.setattr(os, "fsync", spy)
        assert _put(env, _doc(env)).status_code == 201
        # the file first, then its directory, then the directory that holds the store
        assert synced == [False, True, True]
        path = store_dir(env.settings) / f"{ctxset.parse(_doc(env)).digest}.json"
        assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0
        synced.clear()
        assert _put(env, _doc(env)).json()["stored"] is False
        assert synced == [True, True]

    def test_placebo_needs_its_treatment_stored(self, env: Env) -> None:
        treatment = ctxset.parse(_doc(env))
        placebo = _doc(
            env,
            ctxset.SOURCE_ORACLE_PLACEBO,
            text="Some prose about weather patterns over the hills, near the same length.",
            matched_to=treatment.digest,
        )
        r = _put(env, placebo)
        assert r.status_code == 422
        assert envelope(r)["code"] == ctxset.REASON_PLACEBO_UNMATCHED
        assert _put(env, _doc(env)).status_code == 201
        r = _put(env, placebo)
        assert r.status_code == 201, r.text
        assert r.json()["matched_to"] == treatment.digest


class TestRead:
    def test_show_is_metadata_only(self, env: Env) -> None:
        name = _put(env, _doc(env)).json()["name"]
        r = env.get(f"/ctxsets/{name}")
        assert r.status_code == 200
        assert r.json()["name"] == name and r.json()["tasks"] == 4
        assert SECRET not in r.text and "entries" not in r.json()

    def test_a_stated_set_shows_its_v2_metadata_and_never_a_statement(self, env: Env) -> None:
        statement = "The command keeps the help output of every flag unchanged"
        doc = req_doc(tasks=_tasks(env), repo=ALPHA, statement=statement)
        cset = ctxset.parse(doc)
        r = _put(env, doc)
        assert r.status_code == 201, r.text
        d = env.get(f"/ctxsets/{cset.name}").json()
        assert d["schema"] == ctxset.SCHEMA_V2 and d["stated"] is True
        assert d["structure"] == "prose" and d["items_digest"] == cset.items_digest
        assert isinstance(d["saw"], list)
        assert statement not in env.get(f"/ctxsets/{cset.name}").text
        assert "entries" not in d and "items" not in d

    def test_unknown_name_is_404(self, env: Env) -> None:
        r = env.get(f"/ctxsets/ctx.oracle.{'0' * 12}")
        assert r.status_code == 404 and envelope(r)["code"] == "not_found"

    def test_compare_is_not_a_name(self, env: Env) -> None:
        r = env.get("/ctxsets/compare", params={"control": "9" * 32, "treatment": "8" * 32})
        assert r.status_code == 404
        assert "run" in envelope(r)["message"]
        # two seeded runs of no context set: the comparison refuses, it never lists their rows
        r = env.get("/ctxsets/compare", params={"control": "c" * 32, "treatment": "d" * 32})
        assert r.status_code == 422 and envelope(r)["code"] == cc.REASON_UNLINKED
        r = env.get("/ctxsets/compare")
        assert r.status_code == 422  # the query parameters are required: not a name lookup


def _seed_run(env: Env, run_id: str, rows: list[GradeRow]) -> None:
    with env.factory() as s:
        s.add(
            Run(
                id=run_id,
                kind="replay",
                mode="blind",
                status="succeeded",
                repo=ALPHA,
                created="2026-11-01T00:00:00+00:00",
            )
        )
        s.commit()
    DbLedger(env.factory).append_many(rows)


class TestCompare:
    CONTROL_RUN = "c" * 31 + "1"
    TREAT_RUN = "c" * 31 + "2"

    def _runs(self, env: Env, *, store: bool = True) -> ctxset.CtxSet:
        cset = ctxset.parse(_doc(env))
        if store:
            assert _put(env, _doc(env)).status_code == 201
        t = _tasks(env)
        control = dict.fromkeys(t, False) | {t[3]: True}
        treat = dict.fromkeys(t, True)
        _seed_run(
            env,
            self.CONTROL_RUN,
            side(cset, control, role=ctxset.ROLE_CONTROL, run_id=self.CONTROL_RUN),
        )
        _seed_run(env, self.TREAT_RUN, side(cset, treat, run_id=self.TREAT_RUN))
        return cset

    def _compare(self, env: Env) -> Any:
        return env.get(
            "/ctxsets/compare", params={"control": self.CONTROL_RUN, "treatment": self.TREAT_RUN}
        )

    def test_paired_counts_and_banner(self, env: Env) -> None:
        cset = self._runs(env)
        r = self._compare(env)
        assert r.status_code == 200, r.text
        d = r.json()
        assert next(iter(d)) == "control_run"
        assert d["banner"] == cc.CEILING_BANNER and d["ceiling"] is True
        assert d["treatment_arm"] == cset.arm and d["control_arm"] == "A0"
        assert (d["b"], d["c"]) == (3, 0) and d["complete"] is True
        assert (d["control"]["k"], d["treatment"]["k"]) == (1, 4)
        assert SECRET not in r.text

    def test_unstored_set_is_404(self, env: Env) -> None:
        self._runs(env, store=False)
        r = self._compare(env)
        assert r.status_code == 404 and envelope(r)["code"] == REFUSAL_NOT_STORED

    def test_refusal_is_422_with_its_reason(self, env: Env) -> None:
        self._runs(env)
        r = env.get(
            "/ctxsets/compare", params={"control": self.TREAT_RUN, "treatment": self.CONTROL_RUN}
        )
        assert r.status_code == 422
        assert envelope(r)["code"] in cc.REASONS
