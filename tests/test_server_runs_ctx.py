"""``POST /runs`` with a context set: the schema's rules and the submit refusals (ADR-0050).

A run naming ``context_set`` is a blind run over the set's own tasks, with no arm, no loop,
no ``task_ids`` and no ``limit``; ``context_role`` defaults to ``entries`` and is refused
without a set. At submit the deployment must be sealed (422 ``ctxset_posture``), the set
stored (404 ``ctxset_unknown``), its stored bytes the digest its file says (422
``ctxset_digest``) and its tasks gold-clean tasks of the run's repository (422
``ctxset_repo`` / ``ctxset_coverage``). Nothing is queued on any refusal; an admitted run
stores both fields in its params for the worker. Without ``context_set`` nothing changes.

Navigation
----------
What it is:   The tests of the context-set fields of ``RunCreateRequest`` and of
              ``crb.server.routes.runs``'s ``ctxset_refusal`` / ``stored_ctxset``.
What it does: Pins each schema refusal, each submit refusal with nothing queued, the stored
              params of an admitted run of either role, and ``stored_ctxset``'s digest checks
              and its re-verification of a placebo against its stored treatment.
How:          The seeded server (``make_env``), sealed and unsealed, with a ``crb.ctxset.v1``
              document over the seed's ``alpha`` tasks written where ``POST /ctxsets`` stores
              one; the queue replaced by ``FakeJobs``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0050-context-set-arms.md, docs/adr/0054-accepted-plan-context-arm.md
Works with:   src/crb/server/schemas.py (``RunCreateRequest``'s context-set fields),
              src/crb/server/routes/runs.py (under test),
              src/crb/core/ctxset.py (the set's parser and coverage rule),
              tests/fixtures/server_seed.py (the seeded app, its repositories and logins),
              tests/fixtures/readings.py (``SEALED_SETTINGS``)
              tests/fixtures/ctx_rows.py (the v3 accepted-plan document)
Tested by:    tests/test_server_runs_ctx.py
Touch when:   never for a new repository; a context-set field, a submit refusal or the stored layout
              of a set changes.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from crb.core import ctxset
from crb.core.ctxset import CtxSetRefused
from crb.server.routes.runs import CTXSET_DIR, stored_ctxset
from crb.server.schemas import RunCreateRequest
from crb.store.models import Run
from fixtures.ctx_rows import PLAN, plan_doc
from fixtures.readings import SEALED_SETTINGS
from fixtures.server_seed import ALPHA, BETA, Env, login, make_env, task_id
from test_server_routes_runs import FakeJobs
from test_server_routes_runs import _no_ambient_crb_env as _no_ambient_crb_env  # autouse

SONNET: dict[str, Any] = {"builder": "claude_code", "model": "claude-sonnet-5"}
WHEN = "2026-01-01T00:00:00+00:00"


def _doc(*ids: int, repo: str = ALPHA, source: str = "oracle") -> dict[str, Any]:
    tids = sorted(task_id(i) for i in ids)
    return {
        "schema": ctxset.SCHEMA,
        "source": source,
        "repo": repo,
        "method": "written from the merged change",
        "entries": [
            {
                "task_id": t,
                "entry_id": f"e-{t[:6]}",
                "version": "1",
                "text": f"Entry for {t[:6]}.",
                "produced_at": WHEN,
                "mechanical": False,
            }
            for t in tids
        ],
    }


def _store(home: Path, doc: dict[str, Any], *, as_digest: str = "") -> ctxset.CtxSet:
    parsed = ctxset.parse(doc)
    root = home / CTXSET_DIR
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{as_digest or parsed.digest}.json").write_text(json.dumps(doc), encoding="utf-8")
    return parsed


@pytest.fixture
def jobs(monkeypatch: pytest.MonkeyPatch) -> FakeJobs:
    return FakeJobs().install(monkeypatch)


@pytest.fixture
def sealed(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path, **SEALED_SETTINGS) as e:
        login(e.client, "operator")
        yield e


def _post(env: Env, **over: Any) -> Any:
    loop = {"learning": "off"} if "context_set" in over else {}
    return env.post("/runs", json={"repo": ALPHA, "kind": "blind", **SONNET, **loop, **over})


def _code(r: Any) -> str:
    body = r.json()
    return str(body.get("error", {}).get("code") or body.get("code") or "")


def _queued(env: Env) -> int:
    with env.factory() as s:
        return len([r for r in s.query(Run).all() if r.params_json.get("context_set")])


# --- the schema -----------------------------------------------------------------------------

NAME = "ctx.oracle." + "0" * 12


def _req(**over: Any) -> RunCreateRequest:
    loop = {"learning": "off"} if "context_set" in over else {}
    return RunCreateRequest(**{"repo": ALPHA, "kind": "blind", **SONNET, **loop, **over})


def test_without_a_context_set_nothing_changes() -> None:
    body = _req()
    assert body.context_set is None and body.context_role is None


def test_a_context_set_run_names_the_loop_off() -> None:
    with pytest.raises(ValidationError, match="learning 'off'"):
        RunCreateRequest(repo=ALPHA, kind="blind", context_set=NAME, **SONNET)


def test_a_context_set_defaults_to_the_entries_role() -> None:
    assert _req(context_set=NAME).context_role == "entries"
    assert _req(context_set=NAME, context_role="control").context_role == "control"


@pytest.mark.parametrize(
    "over",
    [
        {"context_role": "entries"},
        {"context_set": "library-v1"},
        {"context_set": "ctx.oracle.short"},
        {"context_set": NAME, "context_role": "treatment"},
        {"context_set": NAME, "kind": "replay"},
        {"context_set": NAME, "arm": "S1"},
        {"context_set": NAME, "learning": "on"},
        {"context_set": NAME, "learning": None},
        {"context_set": NAME, "learning": "auto"},
        {"context_set": NAME, "task_ids": [task_id(1)]},
        {"context_set": NAME, "limit": 2},
    ],
)
def test_the_schema_refuses_a_context_set_run_off_blind_a0(over: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _req(**over)


# --- submit ---------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["entries", "control"])
def test_an_admitted_run_stores_the_set_and_its_role(
    sealed: Env, jobs: FakeJobs, role: str
) -> None:
    ctx = _store(sealed.settings.home, _doc(1, 2))
    r = _post(sealed, context_set=ctx.name, context_role=role)
    assert r.status_code == 201, r.text
    (run,) = jobs.enqueued
    assert run.params_json["context_set"] == ctx.name
    assert run.params_json["context_role"] == role


def test_the_role_defaults_to_entries_in_the_stored_params(sealed: Env, jobs: FakeJobs) -> None:
    ctx = _store(sealed.settings.home, _doc(1, 2))
    assert _post(sealed, context_set=ctx.name).status_code == 201
    assert jobs.enqueued[0].params_json["context_role"] == "entries"


def test_a_run_without_a_set_stores_no_ctx_param(sealed: Env, jobs: FakeJobs) -> None:
    assert _post(sealed).status_code == 201
    params = jobs.enqueued[0].params_json
    assert "context_set" not in params and "context_role" not in params


def test_an_unsealed_deployment_is_refused(tmp_path: Path, jobs: FakeJobs) -> None:
    with make_env(tmp_path) as env:
        login(env.client, "operator")
        ctx = _store(env.settings.home, _doc(1, 2))
        r = _post(env, context_set=ctx.name)
        assert r.status_code == 422 and _code(r) == ctxset.REASON_POSTURE, r.text
        assert "nothing was queued" in r.text
        assert jobs.enqueued == [] and _queued(env) == 0


def test_an_unknown_set_is_404(sealed: Env, jobs: FakeJobs) -> None:
    r = _post(sealed, context_set=NAME)
    assert r.status_code == 404 and _code(r) == "ctxset_unknown", r.text
    assert jobs.enqueued == [] and _queued(sealed) == 0


@pytest.mark.parametrize(
    ("doc", "code"),
    [
        (_doc(1, 8), ctxset.REASON_COVERAGE),  # task 8 is not gold-clean
        (_doc(1, repo=BETA), ctxset.REASON_REPO),
    ],
)
def test_a_set_that_does_not_cover_the_runs_tasks_is_refused(
    sealed: Env, jobs: FakeJobs, doc: dict[str, Any], code: str
) -> None:
    ctx = _store(sealed.settings.home, doc)
    r = _post(sealed, context_set=ctx.name)
    assert r.status_code == 422 and _code(r) == code, r.text
    assert "nothing was queued" in r.text
    assert jobs.enqueued == [] and _queued(sealed) == 0


def test_a_set_of_unknown_tasks_is_refused(sealed: Env, jobs: FakeJobs) -> None:
    doc = _doc(1)
    doc["entries"][0]["task_id"] = "f" * 40
    ctx = _store(sealed.settings.home, doc)
    r = _post(sealed, context_set=ctx.name)
    assert r.status_code == 422 and _code(r) == ctxset.REASON_COVERAGE, r.text
    assert jobs.enqueued == []


def test_a_stored_file_whose_body_is_not_its_digest_is_refused(sealed: Env, jobs: FakeJobs) -> None:
    real = ctxset.parse(_doc(1, 2))
    other = _doc(1, 3)
    # the other body stored under the first set's file name: its prefix matches the name
    _store(sealed.settings.home, other, as_digest=real.digest)
    r = _post(sealed, context_set=real.name)
    assert r.status_code == 422 and _code(r) == ctxset.REASON_DIGEST, r.text
    assert jobs.enqueued == []


# --- stored_ctxset --------------------------------------------------------------------------


def test_stored_ctxset_reads_the_stored_set_by_name(tmp_path: Path) -> None:
    assert stored_ctxset(tmp_path, NAME) is None
    ctx = _store(tmp_path, _doc(1, 2))
    got = stored_ctxset(tmp_path, ctx.name)
    assert got is not None and got.digest == ctx.digest
    assert stored_ctxset(tmp_path, NAME) is None
    # a stray file that is not ``<64 hex>.json`` is never read
    (tmp_path / CTXSET_DIR / f"{ctx.digest[:12]}-notes.json").write_text("{", encoding="utf-8")
    assert stored_ctxset(tmp_path, ctx.name) is not None


def test_stored_ctxset_refuses_a_name_outside_the_grammar(tmp_path: Path) -> None:
    with pytest.raises(CtxSetRefused, match=f"^{ctxset.REASON_SCHEMA}:"):
        stored_ctxset(tmp_path, "ctx.oracle.*")


def test_stored_ctxset_refuses_a_body_that_is_not_its_file_digest(tmp_path: Path) -> None:
    real = ctxset.parse(_doc(1, 2))
    _store(tmp_path, _doc(1, 3), as_digest=real.digest)
    with pytest.raises(CtxSetRefused, match=f"^{ctxset.REASON_DIGEST}:"):
        stored_ctxset(tmp_path, real.name)


# --- a placebo, re-verified whenever a run loads it -----------------------------------------


def _placebo(treatment: ctxset.CtxSet, *, copy: bool = False) -> dict[str, Any]:
    """A placebo of ``treatment``: length-matched unrelated prose, or (``copy``) the
    treatment's own texts, which share its identifiers."""
    return {
        "schema": ctxset.SCHEMA,
        "source": treatment.source + ctxset.PLACEBO_SUFFIX,
        "repo": treatment.repo,
        "method": "length-matched unrelated prose",
        "matched_to": treatment.digest,
        "entries": [
            {
                "task_id": e.task_id,
                "entry_id": e.entry_id,
                "version": "1",
                "text": e.text if copy else ("Rivers and hills. " * 9)[: len(e.text)],
                "produced_at": WHEN,
                "mechanical": False,
            }
            for e in treatment.entries
        ],
    }


def _treatment(home: Path) -> ctxset.CtxSet:
    """A stored treatment whose entries name an identifier (``parse_config``)."""
    doc = _doc(1, 2)
    for e in doc["entries"]:
        e["text"] = f"Call `parse_config` first for {e['task_id'][:6]}."
    return _store(home, doc)


def test_a_matched_placebo_with_its_treatment_stored_is_read(tmp_path: Path) -> None:
    treatment = _treatment(tmp_path)
    placebo = _store(tmp_path, _placebo(treatment))
    got = stored_ctxset(tmp_path, placebo.name)
    assert got is not None and got.digest == placebo.digest


def test_a_placebo_whose_treatment_is_not_stored_is_refused(tmp_path: Path) -> None:
    treatment = _treatment(tmp_path)
    placebo = _store(tmp_path, _placebo(treatment))
    (tmp_path / CTXSET_DIR / f"{treatment.digest}.json").unlink()
    with pytest.raises(CtxSetRefused, match=f"^{ctxset.REASON_PLACEBO_UNMATCHED}:"):
        stored_ctxset(tmp_path, placebo.name)


def test_a_hand_written_placebo_copying_its_treatment_is_refused(tmp_path: Path) -> None:
    treatment = _treatment(tmp_path)
    placebo = _store(tmp_path, _placebo(treatment, copy=True))
    with pytest.raises(CtxSetRefused, match=f"^{ctxset.REASON_PLACEBO_OVERLAP}:"):
        stored_ctxset(tmp_path, placebo.name)


def test_a_hand_written_placebo_outside_the_length_tolerance_is_refused(tmp_path: Path) -> None:
    treatment = _treatment(tmp_path)
    doc = _placebo(treatment)
    doc["entries"][0]["text"] += " and more" * 10
    placebo = _store(tmp_path, doc)
    with pytest.raises(CtxSetRefused, match=f"^{ctxset.REASON_PLACEBO_UNMATCHED}:"):
        stored_ctxset(tmp_path, placebo.name)


@pytest.mark.parametrize("missing", [True, False])
def test_submit_refuses_an_unmatched_placebo_and_queues_nothing(
    sealed: Env, jobs: FakeJobs, missing: bool
) -> None:
    home = sealed.settings.home
    treatment = _treatment(home)
    placebo = _store(home, _placebo(treatment, copy=not missing))
    if missing:
        (home / CTXSET_DIR / f"{treatment.digest}.json").unlink()
    r = _post(sealed, context_set=placebo.name)
    want = ctxset.REASON_PLACEBO_UNMATCHED if missing else ctxset.REASON_PLACEBO_OVERLAP
    assert r.status_code == 422 and _code(r) == want, r.text
    assert "nothing was queued" in r.text
    assert jobs.enqueued == [] and _queued(sealed) == 0


def test_submit_admits_a_matched_placebo(sealed: Env, jobs: FakeJobs) -> None:
    treatment = _treatment(sealed.settings.home)
    placebo = _store(sealed.settings.home, _placebo(treatment))
    r = _post(sealed, context_set=placebo.name)
    assert r.status_code == 201, r.text
    assert jobs.enqueued[0].params_json["context_set"] == placebo.name


# --- an accepted-plan set (ADR-0054) --------------------------------------------------------


def _plan(*ids: int, **kw: Any) -> dict[str, Any]:
    return plan_doc(tasks=[task_id(i) for i in ids], repo=ALPHA, **kw)


def test_a_plan_set_run_is_admitted_like_any_other_set(sealed: Env, jobs: FakeJobs) -> None:
    ctx = _store(sealed.settings.home, _plan(1, 2))
    assert ctx.arm.startswith("A0+library@ctx.plan.")
    r = _post(sealed, context_set=ctx.name)
    assert r.status_code == 201, r.text
    (run,) = jobs.enqueued
    assert run.params_json["context_set"] == ctx.name
    assert run.params_json["context_role"] == "entries"


def test_a_stored_plan_over_the_limits_is_refused(sealed: Env, jobs: FakeJobs) -> None:
    real = ctxset.parse(_plan(1, 2))
    over = _plan(1, 2)
    over["entries"][0]["plan"] = {**PLAN, "steps": ["y" * 700]}
    root = sealed.settings.home / CTXSET_DIR
    root.mkdir(parents=True, exist_ok=True)
    # written past the store's own parser, under the name of a real set
    (root / f"{real.digest}.json").write_text(json.dumps(over), encoding="utf-8")
    r = _post(sealed, context_set=real.name)
    assert r.status_code == 422 and _code(r) == ctxset.REASON_PLAN_LENGTH, r.text
    assert jobs.enqueued == [] and _queued(sealed) == 0


def test_a_plan_set_with_open_gaps_is_refused_unless_measured(sealed: Env, jobs: FakeJobs) -> None:
    doc = _plan(1, 2)
    doc["entries"][0]["gaps"] = [{"question": "Which error text?", "decision": "error_text"}]
    ctx = _store(sealed.settings.home, doc)
    r = _post(sealed, context_set=ctx.name)
    assert r.status_code == 409 and _code(r) == ctxset.REASON_OPEN_GAPS, r.text
    assert jobs.enqueued == []
    r = _post(sealed, context_set=ctx.name, measure_open_gaps=True)
    assert r.status_code == 201, r.text
    assert jobs.enqueued[0].params_json["measure_open_gaps"] is True
