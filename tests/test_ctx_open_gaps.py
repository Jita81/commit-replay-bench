"""Open requirement gaps on a stated set (ADR-0053): recorded, never rendered, pushed back.

A ``crb.ctxset.v2`` entry may record ``gaps``: questions the requester has not answered yet,
each naming the decision it leaves open. A digest reads them only when an entry has one, so
every set stored before them keeps its name. No renderer reads them. A run that would deliver
such a set is refused 409 ``ctx_open_gaps`` with the questions listed, before anything is
queued and again at claim, unless it opts in with ``measure_open_gaps: true`` — recorded in
the run's params and stamped ``ctx_open_gaps`` on each open-gap task's rows. A control run
delivers nothing and is never refused for them. ``crb ctxset lint`` lists the questions and
does not fail on them.

Navigation
----------
What it is:   The tests of the ``gaps`` field of a stated entry and the ``ctx_open_gaps`` gate.
What it does: Pins the schema's accept/refuse rules, digest stability for gap-free sets, that
              gaps never reach the rendered text or the composed brief, the submit refusal and
              its question list, the control role and the opt-in (params, plan stamps, ledger
              check), and the lint listing.
How:          Fixture documents (``fixtures.ctx_rows.req_doc``) parsed directly; the seeded
              server (``make_env``, sealed) with ``FakeJobs``; the worker's ``_ctx_plan`` over
              ``test_worker_ctx``'s rig; ``crb ctxset lint`` through ``crb.cli.main``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0053-open-requirement-gaps-gate.md, docs/adr/0052-stated-requirement-arms.md
Works with:   src/crb/core/ctxset.py (the field, digest and gate), src/crb/core/ledger.py (the
              stamp check), src/crb/server/routes/runs.py (the submit refusal),
              src/crb/server/worker.py (the claim refusal and stamps),
              src/crb/cli/commands/ctxset.py (the lint listing)
Tested by:    tests/test_ctx_open_gaps.py
Touch when:   never for a new repository; the gaps field, the gate or its opt-in changes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from crb.cli.main import main
from crb.core import context_arm as ca
from crb.core import ctxset
from crb.core import ledger as lg
from crb.core import stated as st
from crb.core.ctxset import CtxSetRefused
from crb.server.schemas import RunCreateRequest
from fixtures import pyrepo as pr
from fixtures.ctx_rows import TASKS, req_doc
from fixtures.server_seed import ALPHA, Env, task_id
from test_server_routes_runs import FakeJobs
from test_server_runs_ctx import SONNET, _code, _post, _store
from test_server_runs_ctx import _no_ambient_crb_env as _no_ambient_crb_env  # autouse
from test_server_runs_ctx import jobs as jobs  # fixture
from test_server_runs_ctx import sealed as sealed  # fixture
from test_worker_ctx import _Rig

#: The fixture set's digest as origin/main computed it before ``gaps`` existed.
FIXTURE_DIGEST = "d0039d368668b7363cbec36b0ad0069e64ec6bf996cd89bd01d0071cb822dd4b"
CHECKLIST_DIGEST = "630e257b642e8855a1ae9454ee87d95f0fd7e386e75db050219b293bca84fd5d"
Q1 = "What exact message should the command print when the flag is empty?"
Q2 = "Which value is the default timeout, in seconds?"
GAPS = [{"question": Q1, "decision": "error_text"}, {"question": Q2, "decision": "value"}]


def _with_gaps(doc: dict[str, Any], gaps: Any, *, at: int = 0) -> dict[str, Any]:
    doc["entries"][at]["gaps"] = gaps
    return doc


# --- the schema -----------------------------------------------------------------------------


def test_a_gap_free_set_keeps_its_digest() -> None:
    doc = req_doc()
    assert ctxset.parse(doc).digest == FIXTURE_DIGEST == ctxset.canonical_digest(doc)
    assert ctxset.parse(req_doc(structure="checklist")).digest == CHECKLIST_DIGEST


def test_an_empty_gaps_list_is_no_gap_and_keeps_the_digest() -> None:
    cset = ctxset.parse(_with_gaps(req_doc(), []))
    assert cset.digest == FIXTURE_DIGEST and cset.open_gaps == {}
    assert ctxset.canonical_digest(cset.to_doc()) == cset.digest


def test_open_gaps_parse_and_move_the_digest_not_the_items_digest() -> None:
    plain = ctxset.parse(req_doc())
    cset = ctxset.parse(_with_gaps(req_doc(), GAPS))
    assert cset.digest != plain.digest and cset.name != plain.name
    assert cset.items_digest == plain.items_digest
    assert cset.open_gaps == {TASKS[0]: [Q1, Q2]}
    entry = cset.entry_for(TASKS[0])
    assert [g.decision for g in entry.gaps] == ["error_text", "value"]
    assert ctxset.canonical_digest(cset.to_doc()) == cset.digest


@pytest.mark.parametrize(
    ("gaps", "reason", "match"),
    [
        ("Q?", ctxset.REASON_SCHEMA, "gaps is not a list"),
        (["Q?"], ctxset.REASON_SCHEMA, "is not an object"),
        ([{"question": Q1}], ctxset.REASON_SCHEMA, "lacks"),
        ([{**GAPS[0], "answer": "x"}], ctxset.REASON_SCHEMA, "unknown fields"),
        ([{"question": "", "decision": "rule"}], ctxset.REASON_SCHEMA, "non-empty"),
        ([{"question": "a\nb", "decision": "rule"}], ctxset.REASON_SCHEMA, "one trimmed line"),
        ([{"question": " q", "decision": "rule"}], ctxset.REASON_SCHEMA, "one trimmed line"),
        ([{"question": "```x```", "decision": "rule"}], ctxset.REASON_SCHEMA, "code block"),
        ([{"question": Q1, "decision": "colour"}], ctxset.REASON_SCHEMA, "decision"),
        ([GAPS[0], GAPS[0]], ctxset.REASON_SCHEMA, "repeats"),
        ([{"question": "q" * 241, "decision": "rule"}], ctxset.REASON_ITEMS_LENGTH, "241"),
        (
            [{"question": f"q{i}", "decision": "rule"} for i in range(st.MAX_GAPS + 1)],
            ctxset.REASON_ITEMS_LENGTH,
            "gaps",
        ),
    ],
)
def test_a_malformed_gap_is_refused(gaps: Any, reason: str, match: str) -> None:
    with pytest.raises(CtxSetRefused, match=f"^{reason}:.*{match}"):
        ctxset.parse(_with_gaps(req_doc(), gaps))


def test_a_question_of_exactly_the_limit_is_accepted() -> None:
    gap = {"question": "q" * st.MAX_GAP_QUESTION_CHARS, "decision": "rule"}
    assert ctxset.parse(_with_gaps(req_doc(), [gap])).open_gaps


def test_a_v1_entry_still_refuses_a_gaps_field() -> None:
    from fixtures.ctx_rows import ctx_doc

    with pytest.raises(CtxSetRefused, match="unknown fields"):
        ctxset.parse(_with_gaps(ctx_doc(), GAPS))


# --- never rendered -------------------------------------------------------------------------


@pytest.mark.parametrize("structure", st.STRUCTURES)
def test_gaps_are_never_rendered_into_the_entry_text(structure: str) -> None:
    plain = ctxset.parse(req_doc(structure=structure))
    cset = ctxset.parse(_with_gaps(req_doc(structure=structure), GAPS))
    text = cset.entry_for(TASKS[0]).text
    assert text == plain.entry_for(TASKS[0]).text
    assert Q1 not in text and Q2 not in text and "error_text" not in text


# --- the gate (core) ------------------------------------------------------------------------


def test_verify_open_gaps_refuses_entries_and_lists_the_questions() -> None:
    cset = ctxset.parse(_with_gaps(req_doc(), GAPS))
    with pytest.raises(CtxSetRefused, match=f"^{ctxset.REASON_OPEN_GAPS}:") as e:
        ctxset.verify_open_gaps(cset, ctxset.ROLE_ENTRIES)
    assert Q1 in e.value.detail and Q2 in e.value.detail and TASKS[0][:12] in e.value.detail
    ctxset.verify_open_gaps(cset, ctxset.ROLE_CONTROL)
    ctxset.verify_open_gaps(cset, ctxset.ROLE_ENTRIES, measure=True)
    ctxset.verify_open_gaps(ctxset.parse(req_doc()), ctxset.ROLE_ENTRIES)


def test_the_opt_in_stamps_only_open_gap_tasks_and_the_ledger_accepts_it() -> None:
    cset = ctxset.parse(_with_gaps(req_doc(), GAPS))
    gaps = dict.fromkeys(cset.task_ids, "1")
    measured = ctxset.run_stamps(cset, ctxset.ROLE_ENTRIES, gaps, measure_open_gaps=True)
    assert measured[TASKS[0]][ca.LABEL_CTX_OPEN_GAPS] == "2"
    assert ca.LABEL_CTX_OPEN_GAPS not in measured[TASKS[1]]
    assert lg.ctx_label_violation(cset.arm, measured[TASKS[0]]) == ""
    plain = ctxset.run_stamps(cset, ctxset.ROLE_ENTRIES, gaps)
    assert ca.LABEL_CTX_OPEN_GAPS not in plain[TASKS[0]]
    control = ctxset.run_stamps(cset, ctxset.ROLE_CONTROL, gaps, measure_open_gaps=True)
    assert ca.LABEL_CTX_OPEN_GAPS not in control[TASKS[0]]


@pytest.mark.parametrize("value", ["0", "-1", "two", "", "01", "\u0661", "+2", " 2"])
def test_the_ledger_refuses_a_malformed_open_gaps_stamp(value: str) -> None:
    cset = ctxset.parse(_with_gaps(req_doc(), GAPS))
    labels = ctxset.run_stamps(cset, ctxset.ROLE_ENTRIES, dict.fromkeys(cset.task_ids, "1"))
    bad = {**labels[TASKS[0]], ca.LABEL_CTX_OPEN_GAPS: value}
    assert "ctx_open_gaps" in lg.ctx_label_violation(cset.arm, bad)


def test_no_control_row_carries_the_open_gaps_stamp() -> None:
    cset = ctxset.parse(_with_gaps(req_doc(), GAPS))
    control = ctxset.run_stamps(cset, ctxset.ROLE_CONTROL, dict.fromkeys(cset.task_ids, "1"))
    labels = {**control[TASKS[0]], ca.LABEL_CTX_OPEN_GAPS: "2"}
    assert "arm's own stamps" in lg.ctx_label_violation(ca.BASE_A0, labels)


def test_a_placebo_records_no_gap() -> None:
    # A placebo's gaps would be refused or stamped apart from its treatment's, so the pair
    # would split unevenly; only the treatment carries the questions (ADR-0053).
    treatment = ctxset.parse(req_doc())
    doc = _with_gaps(req_doc(ctxset.SOURCE_REQ_PLACEBO, matched_to=treatment.digest), GAPS)
    with pytest.raises(CtxSetRefused) as e:
        ctxset.parse(doc)
    assert e.value.reason == ctxset.REASON_SCHEMA
    assert "placebo" in str(e.value)
    empty = _with_gaps(req_doc(ctxset.SOURCE_REQ_PLACEBO, matched_to=treatment.digest), [])
    assert ctxset.parse(empty).open_gaps == {}


# --- the run schema -------------------------------------------------------------------------

NAME = "ctx.req." + "0" * 12


def _req(**over: Any) -> RunCreateRequest:
    return RunCreateRequest(**{"repo": ALPHA, "kind": "blind", **SONNET, **over})


def test_measure_open_gaps_needs_a_context_set_and_the_entries_role() -> None:
    with pytest.raises(ValidationError, match="only with context_set"):
        _req(measure_open_gaps=True)
    with pytest.raises(ValidationError, match="context_role 'entries'"):
        _req(context_set=NAME, learning="off", context_role="control", measure_open_gaps=True)
    assert _req(context_set=NAME, learning="off", measure_open_gaps=True).measure_open_gaps


# --- POST /runs -----------------------------------------------------------------------------


def _alpha_doc(*, gaps: Any = None) -> dict[str, Any]:
    doc = req_doc(tasks=[task_id(1), task_id(2)], repo=ALPHA)
    return _with_gaps(doc, gaps) if gaps is not None else doc


def test_a_run_of_a_set_with_open_gaps_is_refused_with_its_questions(
    sealed: Env, jobs: FakeJobs
) -> None:
    ctx = _store(sealed.settings.home, _alpha_doc(gaps=GAPS))
    r = _post(sealed, context_set=ctx.name)
    assert r.status_code == 409 and _code(r) == ctxset.REASON_OPEN_GAPS, r.text
    detail = r.json()["error"]["detail"]
    assert detail["gaps"] == {min(task_id(1), task_id(2)): [Q1, Q2]}
    assert jobs.enqueued == []


def test_a_closed_set_runs_and_records_no_opt_in(sealed: Env, jobs: FakeJobs) -> None:
    ctx = _store(sealed.settings.home, _alpha_doc(gaps=[]))
    r = _post(sealed, context_set=ctx.name)
    assert r.status_code == 201, r.text
    assert "measure_open_gaps" not in jobs.enqueued[0].params_json


def test_the_control_role_is_not_refused_for_open_gaps(sealed: Env, jobs: FakeJobs) -> None:
    ctx = _store(sealed.settings.home, _alpha_doc(gaps=GAPS))
    r = _post(sealed, context_set=ctx.name, context_role="control")
    assert r.status_code == 201, r.text
    assert "measure_open_gaps" not in jobs.enqueued[0].params_json


def test_the_opt_in_runs_and_is_recorded(sealed: Env, jobs: FakeJobs) -> None:
    ctx = _store(sealed.settings.home, _alpha_doc(gaps=GAPS))
    r = _post(sealed, context_set=ctx.name, measure_open_gaps=True)
    assert r.status_code == 201, r.text
    assert jobs.enqueued[0].params_json["measure_open_gaps"] is True


def test_an_explicit_false_still_refuses(sealed: Env, jobs: FakeJobs) -> None:
    ctx = _store(sealed.settings.home, _alpha_doc(gaps=GAPS))
    r = _post(sealed, context_set=ctx.name, measure_open_gaps=False)
    assert r.status_code == 409 and _code(r) == ctxset.REASON_OPEN_GAPS, r.text
    assert jobs.enqueued == []


# --- the worker, at claim -------------------------------------------------------------------


@pytest.fixture
def rig(tmp_path: Path, pyrepo: pr.PyRepo) -> _Rig:
    return _Rig(tmp_path, pyrepo)


def _rig_set(rig: _Rig, gaps: Any) -> ctxset.CtxSet:
    from test_worker_ctx import _store as store

    doc = _with_gaps(req_doc(tasks=[rig.task.task_id], repo=pr.REPO_NAME), gaps)
    return store(rig.home, doc)


def test_the_worker_refuses_an_entries_run_with_open_gaps_at_claim(rig: _Rig) -> None:
    ctx = _rig_set(rig, GAPS)
    with pytest.raises(CtxSetRefused, match=f"^{ctxset.REASON_OPEN_GAPS}:"):
        rig.plan(context_set=ctx.name, context_role="entries")
    assert rig.plan(context_set=ctx.name, context_role="control").entries == {}


def test_the_worker_stamps_an_opted_in_run(rig: _Rig) -> None:
    ctx = _rig_set(rig, GAPS)
    plan = rig.plan(context_set=ctx.name, context_role="entries", measure_open_gaps=True)
    stamps = plan.stamps[rig.task.task_id]
    assert stamps[ca.LABEL_CTX_OPEN_GAPS] == "2"
    (entry,) = plan.entries.values()
    assert Q1 not in entry.text and Q2 not in entry.text


# --- crb ctxset lint ------------------------------------------------------------------------

SAFE = "The calculator keeps the existing add function working unchanged"


def test_lint_lists_open_gaps_as_questions_and_does_not_fail(
    pyrepo: pr.PyRepo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    task = pyrepo.feat_task()
    doc = _with_gaps(req_doc(tasks=[task.task_id], statement=SAFE), GAPS)
    path = tmp_path / "set.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    capsys.readouterr()
    assert main(["ctxset", "lint", str(path), "--clone", str(pyrepo.path)]) == 0
    out = capsys.readouterr().out
    assert f"{task.task_id[:12]}  ok" in out and "2 open gap(s)" in out
    assert f"? [error_text] {Q1}" in out and f"? [value] {Q2}" in out
    assert main(["ctxset", "lint", str(path), "--clone", str(pyrepo.path), "--json"]) == 0
    (entry,) = json.loads(capsys.readouterr().out)["entries"]
    assert entry["gaps"] == GAPS and entry["reasons"] == []
