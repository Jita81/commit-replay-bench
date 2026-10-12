"""P-792: an admitted attempt decides its commit, and nothing a run chooses after admission
can steer which commits leave a reading or what a row says.

docs/PREVENTION.md P-792 (and G-982) records the finding: a round-5 enumeration of the Wave 3
reading found nineteen channels (C1 to C19) through which an operator could choose which
commits leave a campaign reading, or what an admitted row says. The round-5 design spec for
closing them names one test per channel, each reproducing the enumeration's probe and failing
before its fix; this file holds them as the fixes land, one step at a time.

C3 (``builder_config``): a run's ``builder_config`` can carry ``extra_args``, which the Claude
Code builder appends to its argv after the rung's own ``--model`` and ``--max-turns``, and a
``claude_binary``, which replaces the CLI it runs. Part (c) is that the apparatus stamp names
both when they are set, so a row cannot describe the rung's model while the argv ran another.
Part (b) is the refusal at claim: a run inserted past submit with ``extra_args`` is failed
``reading_run_fields`` before anything is built (the round-5 probe
``test_builder_config_extra_args_validates_and_overrides_argv``); part (a) is the same
refusal at submit, 422 on ``POST /runs`` with nothing queued.

The reserved.v1 attempt rule (core): a reading registered under it reads each enrolled
commit by the one row its reservation wrote. C4 (a lint-off row is a miss, never a
hit or a leave), C6 (whatever the reserved attempt's exit — a cancel or kill included — later
rows never change its verdict), C15 (a settled reservation without a row is a miss), C19 (an
arm counts only its own reservation's row) and C7 (a non-loop run spends on the reading's
budget profile, refused otherwise) each have a test here, beside the goldens that pin every
legacy (``first_observed.v0``) reading as it read before and the property that the reserved
rule's hits are a subset of the legacy rule's.

The treatment pin's projections (worker helpers): a reservation pins a ``deployment_fp``
per campaign and repository and an ``arm_fp`` per arm, and a later mismatch halts the run.
C3 (``extra_args``), C4 (lint off), C5 (``timeout``), C7 (the budget profile) and C11 (a
``RepoConfig`` edit) each move a fingerprint; the ratchets list ``RepoConfig``'s and
``BuilderContainerSettings``' own fields, so a new field is pinned or named unpinned.

The worker (fail closed): a replay or blind run filed under a reserved.v1 reading reserves
each commit before its r1 build, so whatever the attempt does after — a kill (C1), a cancel
(C2), a gold control that timed out (C5), a clock rolled back (C9), a lost sandbox or a full
disk (C10), a demoted row (C12), an outage (C13) or no row at all (C15) — is that commit's one
attempt, and a later run skips it; a configuration edit after the first reservation halts the
next run before its build (C5, C11), and only a refusal before the reservation (a credential
gone at claim, C13; a field the reading does not register — ``builder_config``, a ``timeout``,
another budget profile or ladder — refused at claim, C3, C5, C7) leaves the commit pending.
Each of these failed on the code before the worker reserved (the claim refusals, before the
worker checked the run's fields); the legacy reading's run, which never reserves, is green on
both by design. ``GET /readings`` serves the rule each reading reads under, a reserved.v1
reading's treatment pins and its reserved commits per arm (C3, C5, C17), and a legacy reading
as open on its rule.

The submit gate (``POST /runs``): under a reserved.v1 reading the same whitelist refuses a
body 422 ``reading_run_fields`` before anything is queued (C3(a), C5(a), C7), every request
field is classified so a new one fails the ratchet until it is (C17), and a run filed under a
campaign holding a reserved.v1 reading on its repository without naming one is refused 409
``reading_required`` (C19); both refusals hold again under the events lock where the campaign
admits the run, and the real step-6 bodies are admitted.

The factory (C8, C16): a forward reading opts in to reserved.v1 on ``POST /readings/forward``
(``attempt_rule``; ``max_reruns`` 0 only), and a factory run filed under it by ``reading_id``
is admitted only on the reading's cell — an off-cell run is refused 422 ``reading_run_fields``
at submit and ``run.refused`` at claim, nothing reserved (C8) — and reserves each ticket's
first ``S2`` build, so only that attempt decides it, whatever later rows say; an exception
after the reservation is a miss (C16), and a reservation that cannot be written never blocks
the build (``build.not_reserved``, the ticket counted by no reading). The legacy forward
rule's ``_forward_attempt`` goldens stand beside them, unchanged.

Navigation
----------
What it is:   The P-792 channel tests — one per channel the round-5 enumeration found, each
              failing on the code before its fix.
What it does: C3(c): pins that ``ClaudeCodeBuilder.describe()`` names ``extra_args`` and
              ``claude_binary`` when they are set, that the named ``extra_args`` are exactly
              the argv's tail (the overriding ``--model``), and that a builder with neither
              set describes itself byte for byte as it did before. The legacy goldens: every
              registration variant's id and every scenario's outcome, looks and per-commit
              verdicts, printed from the code before reserved.v1 (the deciding row by its
              index, since a row hash covers its random ``row_id``), with the one deliberate
              move beside them (``P795_MOVED``: an unsealed replay row reads ``scope_fault``,
              its arm ``undecided``). reserved.v1: C4, C6 (every exit, against later rows of
              other runs, reservations and claims, with the legacy control), C15, C19, each
              check a named miss (replay and forward), the registration's ``max_reruns`` 0
              and budget profile, the ``reading_run_refusal`` whitelist table and the arm
              each admitted run maps to (C3, C5, C7 at the core), and the hypothesis property
              that a reserved hit is a legacy hit and a reserved ``deliver`` a legacy one at
              the same look or earlier. The projections: every pinned ``RepoConfig`` field and
              every container field and deployment input moves its fingerprint, A0 and A0+L
              share ``deployment_fp``, a calibrated profile moves only ``arm_fp``, and no
              secret reaches a projection (a credential-shaped input is refused). The worker:
              C1 (SQLite and PostgreSQL), C2, C5(b, c), C9-C13 and C15 end to end, S3 and A0
              reserving one commit apart, a reservation only at r1 and before every outcome
              event, two claims racing for one commit (one wins, on both backends), a settled
              claim's row refused up to ``execute``, a legacy reading's run never reserving,
              ``POST /readings`` registering reserved.v1 only when asked, the claim's
              ``reading_run_fields`` refusal (C3(b) ``extra_args``, C5 ``timeout``, C7 a budget
              profile, a two-rung ladder) and ``GET /readings`` serving ``attempt_rule``,
              ``pinned_treatment`` and ``reserved`` (null before the first reservation; a legacy
              reading ``first_observed.v0``, ``p792: "open on this rule"``). The submit gate:
              ``POST /runs`` refusing 422 ``reading_run_fields`` (C3(a) ``extra_args``, C5(a)
              ``timeout``, C7 the budget profile and learning switch, each with nothing queued
              or admitted), the request-field ratchet (C17: free, default, refused and factory
              fields; their stored ``params`` keys are ``RESERVED_RUN_PARAMS``), the pin that
              ``new_run``'s empty ladder is ``RESERVED_RUN_LADDER``, 409 ``reading_required``
              (C19), the step-6 re-measure bodies admitted, and both refusals re-checked under
              the events lock. Lint (P-796): a run of a reading of either rule on a repository
              whose lint is off refused 409 ``lint_disabled`` at submit and ``run.refused`` at
              claim (nothing reserved, the commit pending), and lint switched off after the
              first reservation refused, then switched on as another config halting the next
              ``reading_treatment_mismatch`` on the repository pin. The factory: C8 (the
              legacy ``_forward_attempt`` golden and its variants; an off-cell factory run
              refused at submit and at claim, nothing reserved), C16 (a grading exception
              after the reservation is a miss), the hook never blocking delivery (a store
              error, a ticket not enrolled), only the reserved attempt counting (SQLite and
              PostgreSQL), the ``RESERVED_FACTORY_PARAMS`` ratchet and ``POST
              /readings/forward`` opting in.
How:          Builds the builder directly with the worker's ``CRB_CLAUDE_CODE_*`` defaults
              cleared, and reads its argv for the fixture task from
              ``fixtures.builders_repo``; no model call, no store. The reading tests build
              readings, ``Reservation`` values and chained rows in memory (the reading
              fixture's ``sealed_row`` and the forward suite's ``S2`` row shape) and call the
              pure core, with no store. The projection tests call the worker's pure helpers on
              in-memory ``RepoConfig``, ladder and container values. The worker tests use a
              store and a worker: ``test_worker``'s ``Harness`` (SQLite, or the ``backend``
              fixture's database) over the pyrepo fixture with a second commit, the fake
              builder and a local sandbox on the run's cancel token (``_WExec``), every row
              relabelled as a sealed worker writes it, each run stored as ``POST /runs``
              stores one the whitelist admits; ``_w_peek`` acts the moment belt 2 reads red.
              The ``POST /readings`` test runs the app on a seeded SQLite store, and the
              ``GET /readings`` tests (``_w_served``) the app over the worker rig's store.
              The submit-gate tests (``_r_stack``) run the app on the ``backend`` fixture's
              store (SQLite and PostgreSQL) with the Wave 3 rehearsal's campaign and
              registrations opted in to reserved.v1, and settle each admitted run so the
              campaign's line is free for the next. The factory tests (``_f_rig``) run a
              factory run on the worker rig over ``test_worker``'s multiply backlog
              with a calibration grant and held-out tests, every cell a ceiling, under a
              forward reading appended as its event (``_FRig.register``).
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md,
              docs/adr/0026-the-context-standard.md
Works with:   src/crb/builders/claude_code.py (``describe`` and ``argv``, under test),
              tests/test_builders_claude_code.py (the builder's own suite),
              tests/fixtures/builders_repo.py (the task the argv is built for),
              src/crb/core/reading.py (the reserved.v1 rule, ``reading_run_refusal`` and the
              legacy loop, under test), tests/fixtures/readings.py (the registrations and
              rows the reading tests build on), src/crb/server/worker.py
              (``deployment_projection``, ``arm_projection``, ``repo_config_digest``, under
              test), docs/PREVENTION.md (P-792, the row these tests close; P-795, the golden's
              one deliberate move), tests/test_worker.py (``Harness``, ``FakeBuilder``,
              ``_multiply_backlog``),
              src/crb/server/reading_book.py and src/crb/server/campaigns.py
              (``load_readings`` filling ``reservations_of``; ``treatment_pins``),
              src/crb/store/jobs.py (``claim_guard``, ``reclaim_stale``),
              src/crb/server/routes/readings.py (the opt-in fields; ``served_reading``: the
              rule, the pins and the reserved counts), src/crb/server/routes/runs.py
              (``submit_refusals``: ``reading_run_fields_refusal``, ``reading_lint_refusal``
              and ``campaign_refusal``, under test), tests/test_wave3_registration_rehearsal.py
              (the campaign, the registrations and the step-6 bodies the submit-gate tests
              post), src/crb/factory/build.py and src/crb/factory/loop.py (the reserve hook,
              ``build.not_reserved``), tests/test_worker_held_out.py (``HELD_OUT`` and
              ``_every_cell_a_ceiling``), src/crb/server/acceptance.py (``write_held_out``)
Tested by:    tests/test_p792_reserved.py
Touch when:   never for a new repository; a P-792 channel's fix lands (its test goes here,
              failing first), or a builder gains a constructor option that shapes its argv
              (the stamp names it when set, and ``DEFAULT_STAMP`` stays unchanged); the
              reserved.v1 verdict or the run whitelist changes (its table row here first);
              a ``RepoConfig`` / ``BuilderContainerSettings`` field or a deployment input is
              added (its edit in the ratchet's table, which fails until then);
              never to regenerate ``GOLDEN`` — a legacy reading that moves is a regression,
              unless a PREVENTION row moves it on purpose (``P795_MOVED``, beside it).
"""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import inspect
import json
import os
import threading
import types
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import select

import crb.builders as builders_pkg
import crb.builders.adapter as adapter_mod
from crb.builders import base
from crb.builders import claude_code as cc
from crb.builders.adapter import Preflight
from crb.builders.budget import budget_for_rung
from crb.builders.container import BuilderContainerSettings
from crb.core.acceptance import (
    RESULT_ERROR,
    RESULT_FAIL,
    RESULT_PASS,
    HeldOutTests,
    held_out_labels,
)
from crb.core.campaign import CAMPAIGN_ADMITTED, tally
from crb.core.evidence import canonical_json
from crb.core.execution import Command, ExecResult, LocalExecutor, SandboxUnavailable
from crb.core.ledger import (
    FAILURE_OUTAGE,
    GENESIS_HASH,
    LABEL_BUILDER_EXECUTOR,
    LABEL_FAILURE_KIND,
    LABEL_POSTURE_CLASS,
    GradeRow,
    lint_could_change,
)
from crb.core.lint import LINT_DISABLED_BY_CONFIG
from crb.core.mine import change_identity
from crb.core.prevention import AUTO_CONTEXT, K_SECTION, LearningSnapshot, empty_snapshot
from crb.core.reading import (
    ATTEMPT_RULE_LEGACY,
    ATTEMPT_RULE_RESERVED,
    DEFAULT_MAX_RERUNS,
    HALT_TREATMENT_MISMATCH,
    LABEL_CLAIM,
    LABEL_RESERVATION,
    LABEL_TREATMENT,
    LEFT_LINT_DISABLED,
    OUTCOME_CEILING,
    POOL_RULE_ALL,
    READING_EVENT_ACTION,
    READING_RESERVED_ACTION,
    REASON_SCOPE_FAULT,
    REFUSAL_INVALID,
    REFUSAL_READING_REQUIRED,
    REFUSAL_RUN_FIELDS,
    RESERVED_RUN_LADDER,
    RESERVED_RUN_PARAMS,
    RULE_LOOK_V1,
    RULE_LOOK_V1_STRICT,
    RULES,
    SKIP_COMMIT_RESERVED,
    STATE_DELIVER,
    Reading,
    ReadingRefused,
    Reservation,
    arm_reading,
    enrolled,
    evaluate,
    reading_run_refusal,
    register,
    register_forward,
    with_admissions,
    with_enrolment,
    with_reservations,
)
from crb.core.spec import BELT_AFFECTED_DIRS, Language, RepoConfig
from crb.core.spend import (
    ESCALATION_ALWAYS,
    ESCALATION_MEASURED,
    PROFILE_CALIBRATED,
    PROFILE_DEFAULT,
)
from crb.core.taxonomy import GLOBAL_CLASS_SET
from crb.server import campaigns as campaigns_mod
from crb.server import worker
from crb.server.app import create_app
from crb.server.reading_book import load_readings
from crb.server.routes import runs as runs_routes
from crb.server.routes.learn import deployment_author_model
from crb.server.schemas import RunCreateRequest
from crb.store import qualifications as store_q
from crb.store.db import init_db
from crb.store.events import append_event
from crb.store.jobs import (
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    JobQueue,
    claim_guard,
)
from crb.store.ledger import AttemptSettled
from crb.store.models import Event, Repo, Run
from fixtures import pyrepo as pr
from fixtures.builders_repo import make_fixture
from fixtures.posture import posture_row
from fixtures.readings import (
    AUTHOR,
    BEFORE,
    CELL,
    HYPOTHESIS,
    REGISTERED_AT,
    REPO,
    S1,
    SEALED,
    SEALED_SETTINGS,
    SMALLEST_EFFECT,
    commits,
    register_reading,
    rows_for,
    sealed_row,
)
from fixtures.server_seed import Env, add_users, login, make_settings, seed
from test_wave3_registration_rehearsal import (
    TEST_AUTHOR,
    Wave3,
    _a0,
    _refused,
    _runs,
    _s3_body,
    a0l_body,
    add_repos_and_tasks,
    campaign_body,
    registration_bodies,
)
from test_worker import FakeBuilder, Harness

try:  # tests/ is a package only if the conftest owner made it one
    from tests.conftest_store import Backend, backend, pg_schema
except ImportError:  # pragma: no cover — rootdir-relative import (pytest default)
    from conftest_store import Backend, backend, pg_schema  # noqa: F401

#: What a default Claude Code builder's stamp held before the override keys existed, in its
#: key order: a stamp with neither override set must stay byte-identical to this.
DEFAULT_STAMP = (
    '{"builder": "claude_code", "model": "claude-sonnet-5", "provider": "anthropic", '
    '"process": "claude -p stream-json, tools=Read,Edit,Bash", "effort": "default", '
    '"bare": true, "auth": "api_key"}'
)


@pytest.fixture(autouse=True)
def _worker_defaults_cleared(monkeypatch: pytest.MonkeyPatch) -> None:
    """The builder reads its model and auth defaults from the worker's environment."""
    monkeypatch.delenv(cc.MODEL_ENV, raising=False)
    monkeypatch.delenv(cc.AUTH_ENV, raising=False)


def test_p792_c3_builder_config_refused_and_described(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C3, reproducing the enumeration's probe
    ``test_builder_config_extra_args_validates_and_overrides_argv``, which found the argv
    carrying a second ``--model`` while ``describe()`` named only the rung's. (a) ``POST
    /runs`` filed under a reserved.v1 reading with ``builder_config.extra_args`` is refused
    422 ``reading_run_fields`` naming ``builder_config``, with nothing queued and nothing
    admitted (201 before the route's check), on ``backend``'s store; the same body without
    it is admitted. (b) A run of a reserved.v1 reading inserted straight into the queue, past
    ``POST /runs``, with ``builder_config.extra_args`` is refused at claim — ``run.refused``
    ``reading_run_fields`` naming ``builder_config`` — before anything is built or reserved,
    and the commit stays pending. (c) ``describe()`` names ``extra_args`` and
    ``claude_binary`` when they are set."""
    (tmp_path / "submit").mkdir()
    with _r_stack(backend, tmp_path / "submit", monkeypatch) as w:
        a0 = _a0(w, ("cobra", "XS"))
        extra = {**a0, "builder_config": {"extra_args": ["--model", "x"]}}
        assert _r_fields(w, extra, ["builder_config"])["arm"] == "A0"
        _r_admit(w, a0)

    (tmp_path / "claim").mkdir()
    rig = _w_rig(tmp_path / "claim", monkeypatch)
    reading = rig.register()
    queued = rig.enqueue(reading, params={"builder_config": {"extra_args": ["--model", "x"]}})
    done = rig.h.run_one()
    assert done.status == STATUS_FAILED and done.error.startswith(REFUSAL_RUN_FIELDS)
    (why,) = rig.payloads(queued.id, "run.refused")
    assert (why["code"], why["reading_id"], why["fields"]) == (
        REFUSAL_RUN_FIELDS,
        reading.reading_id,
        ["builder_config"],
    )
    assert FakeBuilder.briefs == [] and "build.start" not in rig.actions(queued.id)
    assert rig.reservations(reading) == [] and rig.rows(queued.id) == []
    assert rig.verdicts(reading, "A0")[rig.first] == (None, "pending")

    extra = ["--model", "x"]
    b = cc.ClaudeCodeBuilder(extra_args=extra, claude_binary="/opt/claude")
    d = b.describe()
    assert d["extra_args"] == ["--model", "x"]
    assert d["claude_binary"] == "/opt/claude"
    # the stamp still names the rung's model; the override beside it is what the argv ran
    assert d["model"] == "claude-sonnet-5"
    fx = make_fixture(tmp_path)
    brief = base.BuildBrief.from_task(fx.task, config=fx.config, test_command="pytest")
    argv = b.argv(brief, base.Budget(max_turns=7, max_tool_calls=25), tmp_path / "wt")
    models = [argv[i + 1] for i, a in enumerate(argv) if a == "--model"]
    assert models == ["claude-sonnet-5", "x"]
    assert argv[-len(extra) :] == d["extra_args"]
    # the stamp is JSON: a list, not the tuple the builder keeps
    assert json.loads(json.dumps(d)) == d


def test_p792_describe_unchanged_when_unset() -> None:
    """With neither override set, no existing stamp changes: same keys, same order, same
    values; and an empty ``extra_args`` or ``claude_binary`` is the same as unset."""
    assert json.dumps(cc.ClaudeCodeBuilder().describe()) == DEFAULT_STAMP
    assert json.dumps(cc.ClaudeCodeBuilder(extra_args=[], claude_binary="").describe()) == (
        DEFAULT_STAMP
    )
    sealed = cc.ClaudeCodeBuilder(workdir_alias="/work/").describe()
    assert json.dumps(sealed) == DEFAULT_STAMP[:-1] + ', "container_workdir": "/work"}'


# --- the legacy goldens (first_observed.v0), generated from the code before reserved.v1 ---

_G_HARNESS = "harness: sandbox failed"
_G_OUTAGE = {LABEL_FAILURE_KIND: FAILURE_OUTAGE}


def _g_chain(rows: Sequence[GradeRow]) -> list[GradeRow]:
    """``rows`` chained from genesis, as the ledger writes them, so each has a row hash."""
    out: list[GradeRow] = []
    prev = GENESIS_HASH
    for r in rows:
        c = r.chained(prev)
        out.append(c)
        prev = c.row_hash
    return out


def _g_replay() -> tuple[Reading, list[GradeRow]]:
    """A legacy replay reading (S3 then S1, A0 descriptive of 4) over thirteen commits that
    walk every branch of the first-observed loop."""
    raw = commits(13, prefix="g")
    p = register_reading(raw, budget=0.05).pool  # the seeded order; changes do not move it
    reading = register_reading(
        raw, descriptive=(("A0", 4),), budget=0.05, changes={p[1]: "chg-x", p[10]: "chg-x"}
    )
    assert reading.pool == p
    rows = [
        sealed_row(p[0]),
        sealed_row(p[0], clean=False, arm=S1),
        sealed_row(p[1], clean=False),
        *(sealed_row(p[2], clean=False, error=_G_HARNESS) for _ in range(3)),
        sealed_row(p[3], clean=False, error=_G_HARNESS),
        sealed_row(p[3]),
        sealed_row(p[4], clean=False, labels=dict(_G_OUTAGE)),
        sealed_row(p[4], clean=False),
        sealed_row(p[5], builder_executor="local"),
        sealed_row(p[5], clean=False),
        sealed_row(p[6], change="chg-y", labels={"lint_reason": LINT_DISABLED_BY_CONFIG}),
        sealed_row(p[7], change="chg-y"),
        sealed_row(p[8], clean=False, created=BEFORE),
        sealed_row(p[8]),
        sealed_row(p[9], clean=False, trial="r2"),
        sealed_row(p[10]),
        *(sealed_row(p[11], clean=False, error=_G_HARNESS) for _ in range(2)),
        sealed_row(p[12], clean=False, disqualified=True),
        sealed_row(p[1], arm=S1),
        sealed_row(p[2], arm=S1),
        sealed_row(p[3], clean=False, arm=S1, error=_G_HARNESS),
        sealed_row(p[0], arm="A0"),
        sealed_row(p[1], clean=False, arm="A0"),
        sealed_row(p[2], clean=False, arm="A0", labels=dict(_G_OUTAGE)),
        sealed_row(p[3], arm="A0"),
        sealed_row(p[4], arm="A0"),
        sealed_row(p[5], clean=False, arm="A0"),
    ]
    return reading, _g_chain(rows)


def _g_campaign(*, read: bool) -> tuple[Reading, list[GradeRow]]:
    """A campaign-named reading whose admissions were read (``run-in``) or never read."""
    reading = register_reading(commits(4, prefix="k"), budget=0.05, campaign_id="camp-g")
    p = reading.pool
    rows = [
        sealed_row(p[0], run_id="run-out"),
        sealed_row(p[0], clean=False, run_id="run-in"),
        sealed_row(p[1], clean=False, error=_G_HARNESS, run_id="run-in"),
        sealed_row(p[1], run_id="run-in"),
        sealed_row(p[2], run_id="run-out"),
        sealed_row(p[3], run_id="run-in"),
    ]
    return (with_admissions(reading, ["run-in"]) if read else reading), _g_chain(rows)


def _g_forward() -> tuple[Reading, list[GradeRow]]:
    """A legacy forward reading over nine tickets, one per branch of its loop."""
    pool = commits(20, prefix="f")
    ceiling_reading = register_reading(pool, hierarchy=("S3", S1), budget=0.05)
    ceiling = evaluate(
        ceiling_reading,
        rows_for([True] * 20, pool, arm="S3") + rows_for([True] * 17 + [False] * 3, pool, arm=S1),
    )
    assert ceiling.state == OUTCOME_CEILING
    recs = [_g_record(i) for i in range(9)]
    fwd = register_forward(
        ceiling=ceiling,
        builder="claude_code",
        model="claude-sonnet-5",
        provider="anthropic",
        actor="op-1",
        existing=[ceiling_reading],
        now=_G_FWD_AT,
        budget=0.05,
    )
    reading = with_enrolment(fwd, recs)
    rows = [
        _g_s2(recs[0]),
        _g_s2(recs[0], result=RESULT_FAIL),
        _g_s2(recs[1], result=RESULT_FAIL),
        _g_s2(recs[2], clean=False, error=_G_HARNESS),
        _g_s2(recs[3], clean=False, extra=dict(_G_OUTAGE)),
        _g_s2(recs[4], result=RESULT_ERROR),
        _g_s2(recs[5], model="claude-haiku-5"),
        _g_s2(recs[6], stamp=held_out_labels(recs[7], RESULT_PASS)),
        _g_s2(recs[7], extra={"lint_reason": LINT_DISABLED_BY_CONFIG}),
    ]
    return reading, _g_chain(rows)


_G_FWD_AT = "2026-09-27T12:00:00+00:00"


def _g_record(i: int) -> HeldOutTests:
    return HeldOutTests(
        repo=REPO,
        item_id=f"T-{i}",
        grant=f"grant-{i}",
        files=(("tests/test_held_out.py", f"def test_it():\n    assert {i} == {i}\n"),),
        author="operator:bea",
        written_at="2026-09-27T13:00:00+00:00",
        capability_class="bug.fix",
        size="XS",
        language="go",
    )


def _g_s2(
    rec: HeldOutTests,
    *,
    result: str = RESULT_PASS,
    clean: bool = True,
    stamp: dict[str, str] | None = None,
    extra: dict[str, str] | None = None,
    **kw: Any,
) -> GradeRow:
    """A factory ``S2`` attempt of ``rec``'s ticket (the forward suite's ``_s2_row``)."""
    fields: dict[str, Any] = {
        "repo": REPO,
        "task_id": f"oracle-{rec.item_id}",
        "clean": clean,
        "tests_unmodified": True,
        "target_green": clean,
        "no_new_failures": True,
        "source_changed": True,
        "repo_lint_clean": None,
        "evidence_pack_hash": "h" * 64 if clean else "",
        "apparatus_version": "2.4",
        "created": "2026-09-27T14:00:00+00:00",
        "trial": "r1",
        "mode": "sighted",
        **CELL,
        "process_step": "factory",
        **kw,
    }
    return posture_row(
        **fields,
        labels={
            "posture_class": SEALED,
            "builder_executor": "docker",
            "context_arm": "S2",
            "taxonomy": GLOBAL_CLASS_SET,
            "item_id": rec.item_id,
            "calibration": "true",
            **(held_out_labels(rec, result) if stamp is None else stamp),
            **(extra or {}),
        },
    )


def _g_variant_ids() -> dict[str, str]:
    """The ids of registrations that hash the optional fields a legacy reading may carry."""
    common: dict[str, Any] = {
        "repo": REPO,
        "cell": CELL,
        "apparatus": "2.4",
        "taxonomy": GLOBAL_CLASS_SET,
        "posture_class": SEALED,
        "checks_arm": "off",
        "actor": "op-1",
        "now": REGISTERED_AT,
        "budget": 0.05,
    }
    pool = commits(3, prefix="v")
    return {
        "question": register(
            hierarchy=("S3",),
            pool=pool,
            hypothesis=HYPOTHESIS,
            smallest_effect=SMALLEST_EFFECT,
            **common,
        ).reading_id,
        "strict": register(
            hierarchy=("S3",), pool=pool, rule=RULE_LOOK_V1_STRICT, **common
        ).reading_id,
        "max_reruns_0": register(hierarchy=("S3",), pool=pool, max_reruns=0, **common).reading_id,
        "pool_rule": register(
            hierarchy=("S3",), pool=pool, pool_rule=POOL_RULE_ALL, org_class="acme.fix", **common
        ).reading_id,
    }


def _g_snapshot() -> dict[str, Any]:
    """Every scenario's reading id, outcome, and per arm its look and each commit's
    ``(outcome, left, the index of the row that decided it)`` in the reading's order — the
    row's index in the scenario's rows, since a row's hash covers its random ``row_id``."""
    snap: dict[str, Any] = {"ids": _g_variant_ids()}
    for name, (reading, rows) in {
        "replay": _g_replay(),
        "campaign_read": _g_campaign(read=True),
        "campaign_unread": _g_campaign(read=False),
        "forward": _g_forward(),
    }.items():
        out = evaluate(reading, rows)
        at = {r.row_hash: i for i, r in enumerate(rows)}
        snap[name] = {
            "reading_id": reading.reading_id,
            "state": out.state,
            "arms": {
                arm: (
                    (a.look.state, a.look.counted, a.look.clean, a.look.misses, a.look.needed),
                    [(c.outcome, c.left, at.get(c.row_hash)) for c in a.commits],
                )
                for arm, a in out.arms.items()
            },
        }
    return snap


#: The legacy goldens: ``_g_snapshot()`` printed from the code before reserved.v1 existed.
#: A legacy reading's id, its outcome and every commit's verdict must never move — but for
#: the one deliberate move named in :data:`P795_MOVED`, applied beside this record, never in it.
GOLDEN: dict[str, Any] = {
    "ids": {
        "question": "rdg_c5396a8975ea3ceca1dea904",
        "strict": "rdg_3e5ce7dcedfc2aa0e8dbb086",
        "max_reruns_0": "rdg_a503889415937047e0eecd8d",
        "pool_rule": "rdg_b9768a34baee70a0b1d8138e",
    },
    "replay": {
        "reading_id": "rdg_bee1449e806a36af95e0cf96",
        "state": "insufficient",
        "arms": {
            "S3": (
                ("insufficient", 5, 2, 3, 0),
                [
                    (True, "", 0),
                    (False, "", 2),
                    (None, "harness", None),
                    (True, "", 7),
                    (False, "", 9),
                    (False, "", 11),
                    (None, "lint_disabled", 12),
                    (None, "same_change", None),
                    (True, "", 15),
                    (None, "", None),
                    (None, "same_change", None),
                    (None, "", None),
                    (False, "", 20),
                ],
            ),
            "S1@claude-opus-5": (
                ("undecided", 3, 2, 1, 18),
                [
                    (False, "", 1),
                    (True, "", 21),
                    (True, "", 22),
                    (None, "", None),
                    (None, "", None),
                    (None, "", None),
                    (None, "", None),
                    (None, "", None),
                    (None, "", None),
                    (None, "", None),
                    (None, "same_change", None),
                    (None, "", None),
                    (None, "", None),
                ],
            ),
            "A0": (
                ("descriptive", 3, 2, 1, 1),
                [
                    (True, "", 24),
                    (False, "", 25),
                    (None, "", None),
                    (True, "", 27),
                    (True, "", 28),
                    (False, "", 29),
                    (None, "", None),
                    (None, "", None),
                    (None, "", None),
                    (None, "", None),
                    (None, "same_change", None),
                    (None, "", None),
                    (None, "", None),
                ],
            ),
        },
    },
    "campaign_read": {
        "reading_id": "rdg_463e1fb905e890ccd177f33c",
        "state": "undecided",
        "arms": {
            "S3": (
                ("undecided", 2, 1, 1, 26),
                [(False, "", 1), (True, "", 3), (None, "", None), (True, "", 5)],
            ),
            "S1@claude-opus-5": (
                ("undecided", 0, 0, 0, 16),
                [(None, "", None), (None, "", None), (None, "", None), (None, "", None)],
            ),
        },
    },
    "campaign_unread": {
        "reading_id": "rdg_463e1fb905e890ccd177f33c",
        "state": "undecided",
        "arms": {
            "S3": (
                ("undecided", 0, 0, 0, 16),
                [(None, "", None), (None, "", None), (None, "", None), (None, "", None)],
            ),
            "S1@claude-opus-5": (
                ("undecided", 0, 0, 0, 16),
                [(None, "", None), (None, "", None), (None, "", None), (None, "", None)],
            ),
        },
    },
    "forward": {
        "reading_id": "rdg_2e4128f424af4fa984e5dee6",
        "state": "look_pending",
        "arms": {
            "S2": (
                ("look_pending", 2, 1, 1, 28),
                [
                    (True, "", 0),
                    (False, "", 2),
                    (None, "harness", 3),
                    (None, "unobserved", 4),
                    (None, "held_out_error", 5),
                    (None, "other_cell", 6),
                    (None, "not_graded", 7),
                    (None, "lint_disabled", 8),
                    (None, "", None),
                ],
            )
        },
    },
}


#: The one legacy verdict moved on purpose since ``GOLDEN`` was printed (P-795), as
#: ``(recorded, now)``. The replay's ``p[5]`` row records ``builder_executor`` ``local`` in
#: the reading's sealed posture class: a row its writer failed to label sealed. It was
#: dropped in silence and the commit's next row (the miss at index 11) stood in for it — a
#: re-roll. Now the commit reads ``scope_fault`` on that row (index 10) with no verdict and
#: no stand-in, and ``S3``, so the reading, is ``undecided``: stricter, failing closed.
P795_MOVED: dict[str, tuple[Any, Any]] = {
    "state": ("insufficient", "undecided"),
    "S3_look": (("insufficient", 5, 2, 3, 0), ("undecided", 4, 2, 2, 31)),
    "S3_p5": ((False, "", 11), (None, "", 10)),
}


def _golden_after_p795() -> dict[str, Any]:
    """``GOLDEN`` with :data:`P795_MOVED` applied, each recorded value checked against
    ``GOLDEN`` first — so the move is exactly the one named and the record never changes."""
    golden = copy.deepcopy(GOLDEN)
    replay = golden["replay"]
    look, verdicts = replay["arms"]["S3"]
    recorded = {"state": replay["state"], "S3_look": look, "S3_p5": verdicts[5]}
    assert recorded == {k: was for k, (was, _) in P795_MOVED.items()}
    replay["state"] = P795_MOVED["state"][1]
    verdicts[5] = P795_MOVED["S3_p5"][1]
    replay["arms"]["S3"] = (P795_MOVED["S3_look"][1], verdicts)
    return golden


def test_p792_legacy_reading_ids_and_verdicts_unchanged() -> None:
    """Adding the reserved.v1 fields moved no legacy reading: every registration variant
    hashes to the id it hashed to before, and every scenario of the first-observed loop —
    replay, campaign admissions read and unread, forward — reads the same outcome, the
    same looks and the same per-commit verdicts and rows; the one exception is the P-795
    move (:data:`P795_MOVED`), whose commit is named a scope fault."""
    assert _g_snapshot() == _golden_after_p795()
    reading, rows = _g_replay()
    s3 = evaluate(reading, rows).arms["S3"]
    assert s3.scope_faults == (reading.pool[5],)
    assert s3.commits[5].reason == REASON_SCOPE_FAULT


# --- reserved.v1: the reserved attempt alone decides its commit (C4, C6, C7, C15, C19) ---

#: The ``Event.id`` of the registration the store loads beside a reserved.v1 reading: a
#: reservation written after it counts; one written before it never does.
REG_EVENT = 10
PROFILE = "default"
T1 = "treat-1"
#: A protocol refusal: the builder was stopped by a guard, and the belts judged an empty
#: patch — the builder's miss (``derive_failure_kind`` rule 3), never the instrument's.
PROTOCOL = "protocol violation: wrote the oracle"


def _reserved_reading(
    pool: Sequence[str],
    *,
    hierarchy: Sequence[str] = ("S3", S1),
    descriptive: Sequence[tuple[str, int]] = (),
    rule: str = RULE_LOOK_V1,
    changes: dict[str, str] | None = None,
    campaign_id: str = "",
    budget_profile: str = PROFILE,
    author_model: str | None = None,
) -> Reading:
    """A reserved.v1 reading of :data:`CELL` on :data:`REPO`, registered at
    :data:`REGISTERED_AT` — the legacy fixture's registration with the attempt rule set. Its
    test author is :data:`AUTHOR` when an ``S1`` arm is in the hierarchy, unless named."""
    if author_model is None:
        author_model = AUTHOR if any(a.startswith("S1@") for a in hierarchy) else ""
    return register(
        repo=REPO,
        cell=CELL,
        hierarchy=hierarchy,
        pool=list(pool),
        apparatus="2.4",
        taxonomy=GLOBAL_CLASS_SET,
        posture_class=SEALED,
        checks_arm="off",
        actor="op-1",
        rule=rule,
        descriptive=descriptive,
        author_model=author_model,
        changes=changes,
        budget=0.05,
        max_reruns=0,
        now=REGISTERED_AT,
        campaign_id=campaign_id,
        attempt_rule=ATTEMPT_RULE_RESERVED,
        budget_profile=budget_profile,
    )


def _res(
    arm: str,
    commit: str,
    *,
    run: str = "run-1",
    event: str = "",
    seq: int = REG_EVENT + 1,
    claim: int = 0,
    treatment: str = T1,
    settled: bool = False,
) -> Reservation:
    """The ``reading.reserved`` event of ``commit`` on ``arm``, as the store loads it."""
    return Reservation(
        arm=arm,
        task_id=commit,
        run_id=run,
        event_id=event or f"ev-{run}-{arm}-{commit[:8]}",
        event_seq_id=seq,
        claim=claim,
        treatment=treatment,
        hold_usd=0.5,
        settled=settled,
    )


def _stamp(res: Reservation, **over: str) -> dict[str, str]:
    """The labels the worker stamps on a reserved ``r1`` row."""
    return {
        "reservation": res.event_id,
        "treatment": res.treatment,
        "claim": str(res.claim),
        **over,
    }


def _reserved_row(res: Reservation, *, labels: dict[str, str] | None = None, **kw: Any) -> GradeRow:
    """The row the reserved attempt wrote: its run, its arm, its stamp."""
    return sealed_row(
        res.task_id, arm=res.arm, run_id=res.run_id, labels={**_stamp(res), **(labels or {})}, **kw
    )


def _read(reading: Reading, reservations: Sequence[Reservation]) -> Reading:
    """``reading`` with its reservations and registration event loaded."""
    return with_reservations(reading, reservations, REG_EVENT)


def _verdicts(
    reading: Reading, arm: str, rows: Sequence[GradeRow]
) -> list[tuple[bool | None, str]]:
    """Each enrolled commit's ``(outcome, reason)`` on ``arm``, in the reading's order."""
    return [(c.outcome, c.reason) for c in arm_reading(reading, arm, rows).commits]


def _reserved_forward(n: int, *, attempt_rule: str = ATTEMPT_RULE_RESERVED) -> Reading:
    """A forward reading of the golden section's ceiling, enrolled with ``n`` tickets."""
    pool = commits(20, prefix="rf")
    ceiling_reading = register_reading(pool, hierarchy=("S3", S1), budget=0.05)
    ceiling = evaluate(
        ceiling_reading,
        rows_for([True] * 20, pool, arm="S3") + rows_for([True] * 17 + [False] * 3, pool, arm=S1),
    )
    assert ceiling.state == OUTCOME_CEILING
    fwd = register_forward(
        ceiling=ceiling,
        builder="claude_code",
        model="claude-sonnet-5",
        provider="anthropic",
        actor="op-1",
        existing=[ceiling_reading],
        now=_G_FWD_AT,
        budget=0.05,
        attempt_rule=attempt_rule,
        budget_profile=PROFILE if attempt_rule == ATTEMPT_RULE_RESERVED else "",
    )
    return with_enrolment(fwd, [_g_record(i) for i in range(n)])


def test_p792_c4_forward_lint_disabled_is_not_a_hit() -> None:
    """C4, the reserved.v1 half (the legacy half, where the ticket leaves
    ``lint_disabled``, is ``test_p792_c4_forward_lint_disabled_is_not_a_hit_legacy`` in
    tests/test_forward_reading.py): a reserved row graded with belt 5 switched off by
    configuration is a MISS on a forward reading and on a replay arm — never a hit, and
    never a leave that hands the commit to a later attempt. Under lint-off a reserved.v1
    reading cannot deliver; that is the conservative direction."""
    lint_off = {"lint_reason": LINT_DISABLED_BY_CONFIG}
    # a replay arm
    reading = _reserved_reading(commits(3, prefix="l"), hierarchy=("S3",))
    c = reading.pool[0]
    res = _res("S3", c, settled=True)
    row = _reserved_row(res, labels=lint_off)
    assert lint_could_change(row)
    got = arm_reading(_read(reading, [res]), "S3", [row]).commits[0]
    assert (got.outcome, got.left, got.reason, got.row_hash) == (
        False,
        "",
        "lint_disabled",
        row.row_hash,
    )
    # a forward reading: the unit is the ticket, the reserved row is its factory S2 attempt
    fwd = _reserved_forward(2)
    assert fwd.attempt_rule == ATTEMPT_RULE_RESERVED and fwd.max_reruns == 0
    r0, r1 = (_res("S2", item, run=f"fac-{i}", settled=True) for i, item in enumerate(fwd.pool))
    rows = [
        _g_s2(_g_record(0), extra={**_stamp(r0), **lint_off}, run_id=r0.run_id),
        _g_s2(_g_record(1), extra=_stamp(r1), run_id=r1.run_id),
    ]
    assert lint_could_change(rows[0])
    assert _verdicts(_read(fwd, [r0, r1]), "S2", rows) == [(False, "lint_disabled"), (True, "")]
    # the same rows on the legacy forward reading: the ticket leaves, as the legacy test pins
    legacy = _reserved_forward(2, attempt_rule="")
    left = arm_reading(legacy, "S2", rows).commits[0]
    assert (left.outcome, left.left) == (None, LEFT_LINT_DISABLED)


#: Each way a reserved attempt can end, as ``(settled, the reserved rows, the reserved
#: verdict, the legacy outcome once a later clean row of another run exists)``. The
#: round-5 enumeration's probe ``test_side_channels_if_belt_values_were_withheld``
#: (round5/enum-replay/tree/tests/test_zz_enum_kill_probe.py) found the event stream before
#: ``ledger.append`` says whether the attempt missed (``grade.control`` is emitted only on a
#: miss), so an operator who peeks can cancel or kill the attempt — leaving a harness row or
#: no row — and let the legacy rule read the next run's clean row instead.
_C6_EXITS: dict[str, tuple[bool, tuple[dict[str, Any], ...], tuple[bool | None, str], bool]] = {
    "clean": (True, ({},), (True, ""), True),
    "miss": (True, ({"clean": False},), (False, "miss"), False),
    "harness": (True, ({"clean": False, "error": _G_HARNESS},), (False, "harness"), True),
    "outage": (True, ({"clean": False, "labels": dict(_G_OUTAGE)},), (False, "outage"), True),
    "error": (True, ({"clean": False, "error": PROTOCOL},), (False, "miss"), False),
    "no_row_terminal": (True, (), (False, "unobserved"), True),
    "no_row_reclaimed": (True, (), (False, "unobserved"), True),
    "no_row_running": (False, (), (None, "pending"), True),
    "cancel_harness": (
        True,
        ({"clean": False, "error": "harness: cancelled by the operator"},),
        (False, "harness"),
        True,
    ),
    "cancel_no_row": (True, (), (False, "unobserved"), True),
}


@pytest.mark.parametrize("exit_", sorted(_C6_EXITS))
def test_p792_c6_reserved_attempt_alone_decides(exit_: str) -> None:
    """C6: whatever the reserved attempt's exit — clean, miss, harness, outage, error, no
    row with its run terminal or reclaimed, a cancel that left a harness row or none — its
    verdict is the reserved row's alone, and later rows of other runs, of other
    reservations, or of a later claim of the same run never change it: a hit iff that row
    is clean. The legacy control reads the same rows and lets the later rows decide."""
    settled, reserved_rows, want, legacy_want = _C6_EXITS[exit_]
    pool = commits(2, prefix="x")
    reading = _reserved_reading(pool, hierarchy=("S3",))
    c = reading.pool[0]
    res = _res("S3", c, settled=settled)
    mine = [_reserved_row(res, **kw) for kw in reserved_rows]

    def later(clean: bool) -> list[GradeRow]:
        return [
            sealed_row(c, clean=clean, run_id="run-2"),  # another run, nothing reserved it
            sealed_row(
                c, clean=clean, run_id="run-3", labels=_stamp(res, reservation="ev-another")
            ),  # another reservation's attempt
            sealed_row(c, clean=clean, run_id=res.run_id, labels=_stamp(res, claim="1")),
            # the same run's later claim, stamped with the same reservation (reclaimed)
        ]

    loaded = _read(reading, [res])
    for tail in ([], later(True), later(False)):
        assert _verdicts(loaded, "S3", [*mine, *tail])[0] == want, tail
    # the legacy control: the same rows, the first observed attempt — later rows decide
    legacy = register_reading(pool, hierarchy=("S3",), budget=0.05)
    got = arm_reading(legacy, "S3", [*mine, *later(True)]).commits[0]
    assert (got.outcome, got.left) == (legacy_want, "")


def test_p792_c15_settled_without_a_row_is_a_miss() -> None:
    """C15: a reservation whose run is settled (terminal, or reclaimed past its claim) and
    wrote no reserved row is a miss — the attempt was admitted and ended without one, so
    the commit is spent. An unsettled one is pending; an unreserved commit is pending; and
    a reading whose reservations (or registration event) were never loaded reads every
    commit pending, never a hit."""
    reading = _reserved_reading(commits(3, prefix="u"), hierarchy=("S3",))
    p = reading.pool
    reservations = [_res("S3", p[0], settled=True), _res("S3", p[1], settled=False)]
    loaded = _read(reading, reservations)
    a = arm_reading(loaded, "S3", [])
    assert [(c.outcome, c.reason) for c in a.commits] == [
        (False, "unobserved"),
        (None, "pending"),
        (None, "pending"),
    ]
    assert (a.look.counted, a.look.misses, a.look.clean) == (1, 1, 0)
    assert a.left == ()
    # never loaded, or loaded without the registration event: every commit pending
    clean_row = _reserved_row(reservations[0])
    for unread in (reading, with_reservations(reading, reservations, 0)):
        assert unread.reservations_unread
        assert _verdicts(unread, "S3", [clean_row]) == [(None, "pending")] * 3
    # a campaign-named reading whose admissions were never read counts no row either
    camp = _read(_reserved_reading(commits(3, prefix="u"), hierarchy=("S3",), campaign_id="c"), [])
    assert camp.admissions_unread
    assert _verdicts(camp, "S3", []) == [(None, "pending")] * 3
    # the legacy control: no row is pending, whatever the run did
    legacy = register_reading(commits(3, prefix="u"), hierarchy=("S3",), budget=0.05)
    assert [c.outcome for c in arm_reading(legacy, "S3", []).commits] == [None] * 3


def test_p792_c19_counts_only_its_own_reservation() -> None:
    """C19: an arm counts only the row its own reservation wrote — the reservation's run,
    rung ``r1``, its event id and its claim. A row stamped with another reading's
    reservation, or an arm's row stamped with the other arm's, decides nothing."""
    reading = _reserved_reading(commits(2, prefix="o"))
    c = reading.pool[0]
    r3 = _res("S3", c, run="run-1", event="ev-s3")
    r1 = _res(S1, c, run="run-2", event="ev-s1")
    loaded = _read(reading, [r3, r1])
    stray = [
        _reserved_row(_res("S3", c, run="run-1", event="ev-other-reading")),
        sealed_row(c, arm=S1, run_id=r1.run_id, labels=_stamp(r3)),
        sealed_row(c, arm="S3", run_id=r3.run_id, labels=_stamp(r1)),
        sealed_row(c, arm="S3", run_id=r3.run_id, trial="r2", labels=_stamp(r3)),
    ]
    assert _verdicts(loaded, "S3", stray)[0] == (None, "pending")
    assert _verdicts(loaded, S1, stray)[0] == (None, "pending")
    own = [_reserved_row(r3, clean=False), _reserved_row(r1)]
    assert _verdicts(loaded, "S3", [*stray, *own])[0] == (False, "miss")
    assert _verdicts(loaded, S1, [*stray, *own])[0] == (True, "")
    # two rows of one reservation: neither is chosen
    dup = [*own, _reserved_row(r1, clean=False)]
    assert _verdicts(loaded, S1, dup)[0] == (False, "duplicate")


def test_p792_reserved_each_check_is_a_named_miss() -> None:
    """Every check the reserved row must pass is a miss named by its reason when it fails —
    never a leave, never a hit — on a replay arm and on a forward reading; each case's
    reserved row is otherwise the clean hit of the first case. A reservation that pins no
    treatment can never be a hit (fail closed)."""
    reading = _reserved_reading(commits(2, prefix="n"), hierarchy=("S3",))
    c = reading.pool[0]
    replay: dict[str, tuple[Reservation, dict[str, Any], tuple[bool | None, str]]] = {
        "hit": (_res("S3", c), {}, (True, "")),
        "treatment": (
            _res("S3", c),
            {"labels": {"treatment": "treat-2"}},
            (False, "treatment_mismatch"),
        ),
        "no_treatment": (
            _res("S3", c, treatment=""),
            {"labels": {"treatment": ""}},
            (False, "treatment_mismatch"),
        ),
        "before_registration": (_res("S3", c, seq=REG_EVENT), {}, (False, "before_registration")),
        "disqualified": (
            _res("S3", c),
            {"clean": False, "disqualified": True},
            (False, "disqualified"),
        ),
        "graded_before": (_res("S3", c), {"created": BEFORE}, (False, "out_of_scope")),
        # the arm's row but for its executor: the writer's fault, never another reading's (P-795)
        "local_executor": (_res("S3", c), {"builder_executor": "local"}, (False, "scope_fault")),
    }
    for name, (res, kw, expect) in replay.items():
        row = _reserved_row(res, **kw)
        got = arm_reading(_read(reading, [res]), "S3", [row]).commits[0]
        assert (got.outcome, got.reason) == expect, name
        assert got.left == "" and got.row_hash == row.row_hash, name
    # a campaign-named reading: a reserved row of a run its campaign never admitted
    camp = _reserved_reading(commits(2, prefix="n"), hierarchy=("S3",), campaign_id="camp-n")
    out = _res("S3", camp.pool[0], run="run-out")
    admitted = _read(with_admissions(camp, ["run-in"]), [out])
    assert _verdicts(admitted, "S3", [_reserved_row(out)])[0] == (False, "not_admitted")
    # a forward reading: the held-out result, the cell and the enrolling record decide too
    fwd = _reserved_forward(1)
    rec = _g_record(0)
    res = _res("S2", fwd.pool[0], run="fac-0", settled=True)
    forward: dict[str, tuple[dict[str, Any], tuple[bool | None, str]]] = {
        "hit": ({}, (True, "")),
        "held_out_fail": ({"result": RESULT_FAIL}, (False, "held_out")),
        "held_out_error": ({"result": RESULT_ERROR}, (False, "held_out")),
        "other_model": ({"model": "claude-haiku-5"}, (False, "other_cell")),
        "other_record": (
            {"stamp": held_out_labels(_g_record(1), RESULT_PASS)},
            (False, "not_graded"),
        ),
        "not_held_out": ({"stamp": {}}, (False, "not_graded")),
        "miss": ({"clean": False}, (False, "miss")),
    }
    for name, (kw, expect) in forward.items():
        row = _g_s2(rec, extra=_stamp(res), run_id=res.run_id, **kw)
        assert _verdicts(_read(fwd, [res]), "S2", [row]) == [expect], name


def test_p792_reserved_requires_max_reruns_zero_and_a_budget_profile() -> None:
    """A reserved.v1 registration has ``max_reruns`` 0 and names a budget profile, or is
    refused ``invalid_reading``; an unknown attempt rule is refused. The rule and the
    profile are hashed; the loaded reservations and registration event never are."""
    pool = commits(3, prefix="q")
    common: dict[str, Any] = {
        "repo": REPO,
        "cell": CELL,
        "hierarchy": ("S3",),
        "pool": pool,
        "apparatus": "2.4",
        "taxonomy": GLOBAL_CLASS_SET,
        "posture_class": SEALED,
        "checks_arm": "off",
        "actor": "op-1",
        "now": REGISTERED_AT,
        "budget": 0.05,
    }
    for bad in (
        {"attempt_rule": ATTEMPT_RULE_RESERVED, "budget_profile": PROFILE},  # max_reruns 2
        {"attempt_rule": ATTEMPT_RULE_RESERVED, "budget_profile": PROFILE, "max_reruns": 1},
        {"attempt_rule": ATTEMPT_RULE_RESERVED, "max_reruns": 0},  # no profile
        {"attempt_rule": ATTEMPT_RULE_RESERVED, "max_reruns": 0, "budget_profile": "  "},
        {"attempt_rule": "first_seen.v9", "max_reruns": 0, "budget_profile": PROFILE},
    ):
        with pytest.raises(ReadingRefused) as exc:
            register(**common, **bad)
        assert exc.value.code == REFUSAL_INVALID, bad
    ok = register(
        **common, attempt_rule=ATTEMPT_RULE_RESERVED, max_reruns=0, budget_profile=PROFILE
    )
    assert (ok.attempt_rule, ok.budget_profile, ok.max_reruns) == (
        ATTEMPT_RULE_RESERVED,
        PROFILE,
        0,
    )
    assert ok.reserved and ok.reservations_unread
    body = ok.body()
    assert (body["attempt_rule"], body["budget_profile"]) == (ATTEMPT_RULE_RESERVED, PROFILE)
    other = register(
        **common, attempt_rule=ATTEMPT_RULE_RESERVED, max_reruns=0, budget_profile="calibrated"
    )
    assert other.reading_id != ok.reading_id
    back = Reading.from_dict(ok.to_dict())
    assert back == ok and back.reading_id == ok.reading_id and back.verify()
    # loaded, never hashed or served: the id, the body and equality are unchanged
    loaded = _read(ok, [_res("S3", ok.pool[0])])
    assert not loaded.reservations_unread and loaded.registered_event_id == REG_EVENT
    assert loaded == ok and loaded.to_dict() == ok.to_dict() and loaded.verify()
    assert "reservations" not in loaded.to_dict() and "registered_event_id" not in loaded.body()
    # the first reservation per (arm, commit) by event id is the one that counts
    first = _res("S3", ok.pool[0], event="ev-first", seq=12)
    later = _res("S3", ok.pool[0], event="ev-later", seq=13)
    assert loaded.reservations is not None
    assert _read(ok, [later, first]).reservations == {("S3", ok.pool[0]): first}
    # a legacy registration: nothing new is hashed; the legacy rule's name is the same rule
    legacy = register(**common)
    named = register(**common, attempt_rule=ATTEMPT_RULE_LEGACY, budget_profile=PROFILE)
    assert named.reading_id == legacy.reading_id and named.attempt_rule == ""
    assert "attempt_rule" not in legacy.body() and "budget_profile" not in legacy.body()
    assert not legacy.reserved and with_reservations(legacy, [], REG_EVENT) == legacy
    # the forward registration under reserved.v1 has no re-run either
    fwd = _reserved_forward(1)
    assert fwd.max_reruns == 0 and fwd.budget_profile == PROFILE
    with pytest.raises(ReadingRefused) as exc:
        _reserved_forward(1, attempt_rule="first_seen.v9")
    assert exc.value.code == REFUSAL_INVALID


#: A blind run's arm is A0, a sighted replay's S3, and ``arm: S1`` on a blind run is the S1
#: arm of the reading's test author; with neither ``learning`` nor ``budget_profile`` the
#: loop is on (``+L``). Every other key a run can carry is refused.
_RUN_OK: dict[str, Any] = {
    "task_ids": ["t"],
    "limit": 0,
    "pool": "",
    "executor": "",
    "timeout": 0,
    "max_cost_usd": 4.0,
    "learning": "off",
    "budget_profile": PROFILE,
    "reading_id": "rdg_x",
    "campaign_id": "camp-w",
    "outage_stop": 3,
    "env_stop": 3,
    "qualify_first": False,
}
_NO_LOOP_KEYS = {k: v for k, v in _RUN_OK.items() if k not in ("learning", "budget_profile")}
_S3_RUN: dict[str, Any] = {"kind": "replay", "mode": "sighted"}
_A0_RUN: dict[str, Any] = {"kind": "blind", "mode": "blind"}
_CELL_RUN: dict[str, Any] = {
    "builder": "claude_code",
    "model": "claude-sonnet-5",
    "provider": "anthropic",
    "ladder": ["r1"],
}
#: ``(name, run fields over _S3_RUN, params, the arm when admitted, the refused fields)``.
_RUN_TABLE: list[tuple[str, dict[str, Any], dict[str, Any], str, list[str]]] = [
    ("s3", {}, _RUN_OK, "S3", []),
    ("a0", _A0_RUN, _RUN_OK, "A0", []),
    (
        "s1_named",
        _A0_RUN,
        {**_RUN_OK, "arm": "S1", "test_author": "claude_code:claude-opus-5"},
        S1,
        [],
    ),
    ("s1_reading_author", _A0_RUN, {**_RUN_OK, "arm": "S1"}, S1, []),
    ("a0_loop", _A0_RUN, _NO_LOOP_KEYS, "A0+L", []),
    ("s3_loop_not_read", {}, _NO_LOOP_KEYS, "", ["arm"]),
    *(
        (f"key_{k}", {}, {**_RUN_OK, k: v}, "", [k])
        for k, v in {
            "builder_config": {"extra_args": ["--model", "x"]},
            "ladder": ["r1"],
            "budget": {"max_turns": 3},
            "retain": {"worktrees": True},
            "preflight": True,
            "escalation": "rung",
            "checks": {"finish_gate": False},
            "taxonomy": "acme@1",
            "unknown": 1,
        }.items()
    ),
    ("timeout", {}, {**_RUN_OK, "timeout": 1}, "", ["timeout"]),
    ("pool", {}, {**_RUN_OK, "pool": "since:2026-09-01"}, "", ["pool"]),
    ("executor", {}, {**_RUN_OK, "executor": "local"}, "", ["executor"]),
    ("ladder_rung", {"ladder": ["claude_code:claude-opus-5"]}, _RUN_OK, "", ["ladder"]),
    ("ladder_two", {"ladder": ["r1", "r2"]}, _RUN_OK, "", ["ladder"]),
    ("ladder_empty", {"ladder": []}, _RUN_OK, "", ["ladder"]),
    ("cell_model", {"model": "claude-haiku-5"}, _RUN_OK, "", ["model"]),
    ("cell_builder", {"builder": "openai_agent"}, _RUN_OK, "", ["builder"]),
    ("cell_provider", {"provider": "bedrock"}, _RUN_OK, "", ["provider"]),
    ("arm_mode", {"mode": "blind"}, _RUN_OK, "", ["mode"]),
    ("arm_kind", {"kind": "factory"}, _RUN_OK, "", ["kind"]),
    ("arm_s1_sighted", {}, {**_RUN_OK, "arm": "S1"}, "", ["arm"]),
    ("arm_other", _A0_RUN, {**_RUN_OK, "arm": "S2"}, "", ["arm"]),
    (
        "arm_author",
        _A0_RUN,
        {**_RUN_OK, "arm": "S1", "test_author": "openai_agent:gpt-9"},
        "",
        ["test_author"],
    ),
    (
        "author_without_s1",
        _A0_RUN,
        {**_RUN_OK, "test_author": "claude_code:claude-opus-5"},
        "",
        ["test_author"],
    ),
    (
        "loop_with_learning",
        _A0_RUN,
        {**_NO_LOOP_KEYS, "learning": "on"},
        "",
        ["budget_profile", "learning"],
    ),
    ("c7_profile", {}, {**_RUN_OK, "budget_profile": "calibrated"}, "", ["budget_profile"]),
    (
        "c7_profile_only",
        {},
        {k: v for k, v in _RUN_OK.items() if k != "learning"},
        "",
        ["learning"],
    ),
    ("learning_on", {}, {**_RUN_OK, "learning": "on"}, "", ["learning"]),
]


@pytest.mark.parametrize(
    ("name", "run", "params", "arm", "refused"), _RUN_TABLE, ids=[t[0] for t in _RUN_TABLE]
)
def test_p792_reading_run_refusal_whitelist(
    name: str, run: dict[str, Any], params: dict[str, Any], arm: str, refused: list[str]
) -> None:
    """C3, C5 and C7 at the core: a run of a reserved.v1 reading may carry only the keys of
    :data:`RESERVED_RUN_PARAMS` — no ``builder_config``, budget, checks, preflight or
    escalation can steer its attempts; ``pool``, ``executor`` and ``timeout`` keep their
    defaults and the ladder is the default ``["r1"]``; it builds on the reading's own cell;
    its arm is one the reading reads; and a non-loop arm runs with the loop off on the
    reading's budget profile (C7) while the ``+L`` arm names neither."""
    reading = _reserved_reading(
        commits(3, prefix="w"), descriptive=(("A0", 2), ("A0+L", 2)), campaign_id="camp-w"
    )
    fields = {**_S3_RUN, **_CELL_RUN, **run}
    code, detail = reading_run_refusal(reading, params=params, **fields)
    if not refused:
        assert (code, detail) == ("", {}), name
        return
    assert code == REFUSAL_RUN_FIELDS, name
    assert detail["fields"] == refused, (name, detail)
    assert set(detail["reasons"]) == set(refused)
    assert all(detail["reasons"][f] for f in refused)
    # a legacy reading is never refused by it: the legacy rule is unchanged
    legacy = register_reading(commits(3, prefix="w"), descriptive=(("A0", 2),), budget=0.05)
    assert reading_run_refusal(legacy, params=params, **fields) == ("", {})
    assert arm == ""


def test_p792_reading_run_refusal_names_the_whitelist() -> None:
    """The whitelist and the one ladder are the core's constants, so the submit check and
    the claim check refuse the same runs; and each admitted run maps to the arm the table
    names — a reading without that arm refuses the run, naming the arm it would have run."""
    whitelist = frozenset(
        {
            "task_ids",
            "limit",
            "pool",
            "executor",
            "timeout",
            "max_cost_usd",
            "budget_profile",
            "learning",
            "arm",
            "test_author",
            "reading_id",
            "campaign_id",
            "outage_stop",
            "env_stop",
            "qualify_first",
        }
    )
    assert whitelist == RESERVED_RUN_PARAMS
    assert RESERVED_RUN_LADDER == ("r1",)
    reading = _reserved_reading(commits(3, prefix="w"), descriptive=(("A0", 2), ("A0+L", 2)))
    for name, run, params, arm, refused in _RUN_TABLE:
        if refused:
            continue
        fields = {**_S3_RUN, **_CELL_RUN, **run}
        assert arm in reading.arms, name
        assert reading_run_refusal(reading, params=params, **fields) == ("", {}), name
        without = _reserved_reading(
            commits(3, prefix="w"),
            hierarchy=[a for a in ("S3", S1) if a != arm],
            descriptive=[(a, 2) for a in ("A0", "A0+L") if a != arm],
            author_model=AUTHOR,
        )
        assert arm not in without.arms, name
        code, detail = reading_run_refusal(without, params=params, **fields)
        assert (code, detail["fields"], detail["arm"]) == (REFUSAL_RUN_FIELDS, ["arm"], arm), name


# --- the reserved rule is strictly more conservative than the legacy one ------------------

#: Each exit the reserved attempt of a commit can take in the property below.
_R_EXITS = (
    "clean",
    "miss",
    "harness",
    "outage",
    "error",
    "lint_clean",
    "disqualified",
    "no_row_settled",
    "no_row_open",
    "treatment",
    "before_registration",
    "unreserved",
)
_LATER = ("clean", "miss", "harness", "outage")
#: The drawn head of the pool: enough for every look of every rule.
_DRAWN = 42
#: The pool: the drawn head, then a clean tail long enough that the legacy pool still holds
#: every look after its leaves (each drawn commit can leave at most once), so the legacy
#: reading is never short of commits where the reserved one decides.
_H_POOL = commits(_DRAWN + 48, prefix="h")


def _r_rows(exit_: str, res: Reservation) -> list[GradeRow]:
    """The reserved attempt's rows for ``exit_`` (none when it wrote none)."""
    shapes: dict[str, dict[str, Any] | None] = {
        "clean": {},
        "miss": {"clean": False},
        "harness": {"clean": False, "error": _G_HARNESS},
        "outage": {"clean": False, "labels": dict(_G_OUTAGE)},
        "error": {"clean": False, "error": PROTOCOL},
        "lint_clean": {"labels": {"lint_reason": LINT_DISABLED_BY_CONFIG}},
        "disqualified": {"clean": False, "disqualified": True},
        "no_row_settled": None,
        "no_row_open": None,
        "treatment": {"labels": {"treatment": "treat-2"}},
        "before_registration": {},
    }
    if exit_ == "unreserved":
        return [sealed_row(res.task_id, run_id=res.run_id)]  # nothing reserved the attempt
    kw = shapes[exit_]
    return [] if kw is None else [_reserved_row(res, **kw)]


def _later_row(commit: str, kind: str, run: str) -> GradeRow:
    shapes: dict[str, dict[str, Any]] = {
        "clean": {},
        "miss": {"clean": False},
        "harness": {"clean": False, "error": _G_HARNESS},
        "outage": {"clean": False, "labels": dict(_G_OUTAGE)},
    }
    return sealed_row(commit, run_id=run, **shapes[kind])


@settings(max_examples=200, database=None, deadline=None)
@given(st.data())
def test_p792_new_hits_subset_of_old(data: st.DataObject) -> None:
    """The round-5 argument, over random worlds: the reserved attempt is one of the
    commit's attempts, so a reserved hit is a legacy hit (the legacy rule's first observed
    attempt is the reserved one when it is clean); the legacy rule only removes commits
    the reserved rule reads as non-hits, so for every prefix ``n`` the legacy hits among
    its first ``n`` kept commits are at least the reserved hits among the first ``n``
    enrolled; and so a reserved ``deliver`` is a legacy ``deliver`` at the same look or
    earlier. Every legacy commit has a final observed row, so the legacy world is complete
    (no re-run left to wait for)."""
    rule = data.draw(st.sampled_from(sorted(RULES)), label="rule")
    order = list(register_reading(_H_POOL, hierarchy=("S3",), budget=0.05).pool)
    changes: dict[str, str] = {}
    pairs = data.draw(
        st.lists(st.tuples(st.integers(0, _DRAWN - 1), st.integers(0, _DRAWN - 1)), max_size=4),
        label="same-change pairs",
    )
    for k, (i, j) in enumerate(pairs):
        if i != j:
            changes[order[i]] = changes[order[j]] = f"dup-{k}"
    if data.draw(st.booleans(), label="dense"):
        exits = data.draw(
            st.lists(st.sampled_from(_R_EXITS), min_size=_DRAWN, max_size=_DRAWN), label="exits"
        )
    else:
        exits = ["clean"] * _DRAWN
        for pos in data.draw(st.lists(st.integers(0, _DRAWN - 1), max_size=6), label="noise"):
            exits[pos] = data.draw(st.sampled_from(_R_EXITS))
    reservations: list[Reservation] = []
    rows: list[GradeRow] = []
    for i, commit in enumerate(order):
        exit_ = exits[i] if i < _DRAWN else "clean"
        res = _res(
            "S3",
            commit,
            run=f"run-{i}",
            seq=REG_EVENT - 5 if exit_ == "before_registration" else REG_EVENT + 1 + i,
            settled=exit_ != "no_row_open",
        )
        if exit_ != "unreserved":
            reservations.append(res)
        rows += _r_rows(exit_, res)
        if i >= _DRAWN:
            continue
        for k, kind in enumerate(data.draw(st.lists(st.sampled_from(_LATER), max_size=3))):
            rows.append(_later_row(commit, kind, f"later-{i}-{k}"))
        rows.append(sealed_row(commit, clean=data.draw(st.booleans()), run_id=f"final-{i}"))
    legacy = register_reading(_H_POOL, hierarchy=("S3",), rule=rule, budget=0.05, changes=changes)
    reserved = _read(
        _reserved_reading(_H_POOL, hierarchy=("S3",), rule=rule, changes=changes), reservations
    )
    old = arm_reading(legacy, "S3", rows)
    new = arm_reading(reserved, "S3", rows)
    assert [c.commit for c in new.commits] == list(enrolled(reserved, "S3"))
    assert [c.commit for c in new.commits] == [
        c.commit for c in old.commits if c.left != "same_change"
    ]
    assert all(not c.left for c in new.commits)
    old_by = {c.commit: c for c in old.commits}
    for c in new.commits:
        if c.outcome is True:
            assert (old_by[c.commit].outcome, old_by[c.commit].left) == (True, "")
    kept = [c for c in old.commits if not c.left]
    assert all(c.outcome is not None for c in kept)  # the legacy world is complete
    assert len(kept) >= max(n for looks in RULES.values() for n in looks)
    for n in range(len(new.commits) + 1):
        old_hits = sum(c.outcome is True for c in kept[:n])
        new_hits = sum(c.outcome is True for c in new.commits[:n])
        assert old_hits >= new_hits, n
    if new.look.state == STATE_DELIVER:
        assert old.look.state == STATE_DELIVER
        assert old.look.decided_at is not None and new.look.decided_at is not None
        assert old.look.decided_at <= new.look.decided_at


# ---------------------------------------------------------------------------
# The treatment pin's projections (C3, C4, C5, C7, C11): what deployment_fp and arm_fp hash
# ---------------------------------------------------------------------------

#: A fake provider key: the shape the redactor knows, so a leak of it is unmistakable.
_FAKE_KEY = "sk-ant-p792-fake-0123456789abcdef"

#: One edit per ``RepoConfig`` field, each valid on its own over ``_repo()``. A field added
#: to ``RepoConfig`` fails the ratchet until it has an edit here — and the edit then shows
#: whether it moves the digest, which it must unless it is in ``REPO_CONFIG_UNPINNED``.
_REPO_FIELD_EDITS: dict[str, Any] = {
    "name": "p792-other",
    "language": Language.GO,
    "runner": "vitest",
    "path": "/clones/elsewhere",
    "src_prefix": "src/",
    "test_prefix": "tests/",
    "ext": ".pyi",
    "test_mode": "suffix",
    "test_suffix": "_spec.py",
    "belt_scope": BELT_AFFECTED_DIRS,
    "probe": "tests/test_probe.py",
    "url": "https://example.invalid/p792.git",
    "layer": "api",
    "runner_opts": {"pythonpath_suffix": "src"},
    "sandbox_image": "crb-sandbox:other",
    "mining": {"log_n": 50},
    "lint": {"disabled": True},
    "sandbox_tree": "copy",
    "spend": {"budget_profile": PROFILE_CALIBRATED},
    "checks": {"format_step": True},
    "auto_stages": True,
}

#: One edit per ``BuilderContainerSettings`` field, valid over ``_container()``.
_CONTAINER_FIELD_EDITS: dict[str, Any] = {
    "image": "crb-builder:2",
    "proxy_image": "crb-proxy:2",
    "allow_hosts": ("api.anthropic.com", "example.invalid:8443"),
    "egress_network": "crb-egress",
    "memory": "8g",
    "cpus": "4",
    "pids_limit": 2048,
    "tmp_size": "2g",
    "user": "1001:1001",
    "docker_binary": "/usr/local/bin/docker",
    "extra_ro_mounts": {"/opt/cache": "/cache"},
}


def _repo(**edits: Any) -> RepoConfig:
    config = RepoConfig(
        name="p792", language=Language.PYTHON, path="/clones/p792", test_suffix="_tests.py"
    )
    return dataclasses.replace(config, **edits)


def _container(**edits: Any) -> BuilderContainerSettings:
    return dataclasses.replace(
        BuilderContainerSettings(image="crb-builder:1", user="1000:1000"), **edits
    )


def _ladder(model: str = "claude-sonnet-5", **config: Any) -> base.EscalationLadder:
    rung = base.Rung("claude_code", model, "anthropic", {"max_turns": 40, **config})
    second = base.Rung("claude_code", "claude-opus-5", "anthropic")
    return base.EscalationLadder((rung, second))


def _deployment_inputs(**edits: Any) -> dict[str, Any]:
    inputs: dict[str, Any] = {
        "ladder": _ladder(),
        "budget": base.Budget(max_turns=30, max_tool_calls=30),
        "builder_overrides": {"effort": "high"},
        "container": _container(),
        "executor": "docker",
        "timeout": 1800,
        "preflight": None,
        "escalation": ESCALATION_MEASURED,
        "posture_class": "docker/copy/offline",
        "config": _repo(),
        "s1_author": "",
    }
    return {**inputs, **edits}


def _deployment(**edits: Any) -> dict[str, Any]:
    return worker.deployment_projection(**_deployment_inputs(**edits))


def _deployment_fp(**edits: Any) -> str:
    return worker.fingerprint(_deployment(**edits))


def _r1_budget() -> base.Budget:
    inputs = _deployment_inputs()
    return budget_for_rung(inputs["ladder"].rungs[0], inputs["budget"])


def test_p792_repo_config_pin_ratchet() -> None:
    """C11: every ``RepoConfig`` field is in the pinned repository digest unless it is named
    in ``REPO_CONFIG_UNPINNED`` (where the clone lives, how far mining walks, and the free-stage
    chain change no attempt). The list is the dataclass's own fields, so a new field is pinned
    by default and this test fails until it has an edit."""
    names = {f.name for f in dataclasses.fields(RepoConfig)}
    assert set(_REPO_FIELD_EDITS) == names, "a RepoConfig field has no edit in this ratchet"
    assert frozenset({"path", "mining", "auto_stages"}) == worker.REPO_CONFIG_UNPINNED
    config = _repo()
    digest = worker.repo_config_digest(config)
    assert len(digest) == 64 and digest == worker.repo_config_digest(_repo())
    for name in sorted(names):
        edited = dataclasses.replace(config, **{name: _REPO_FIELD_EDITS[name]})
        assert getattr(edited, name) != getattr(config, name), name
        moved = worker.repo_config_digest(edited) != digest
        assert moved is (name not in worker.REPO_CONFIG_UNPINNED), name


def test_p792_container_projection_ratchet() -> None:
    """Every ``BuilderContainerSettings`` field is a named field of the deployment, and an
    edit to any one of them moves the deployment fingerprint; a builder on the host projects
    no container at all."""
    names = {f.name for f in dataclasses.fields(BuilderContainerSettings)}
    assert set(_CONTAINER_FIELD_EDITS) == names, "a container field has no edit in this ratchet"
    projected = _deployment()["container"]
    assert set(projected) == names
    assert projected["tmp_size"] == "1g" and projected["extra_ro_mounts"] == {}
    pinned = _deployment_fp()
    for name in sorted(names):
        edited = _container(**{name: _CONTAINER_FIELD_EDITS[name]})
        assert getattr(edited, name) != getattr(_container(), name), name
        assert _deployment_fp(container=edited) != pinned, name
    assert _deployment(container=None)["container"] is None
    assert _deployment_fp(container=None) != pinned


def test_p792_a0_and_a0l_share_the_deployment_fp() -> None:
    """A0 and A0+L are one deployment and two arms: the loop's overlay, the budget profile
    it may set and the budget that resolves to are the +L arm's treatment, so they live in a
    non-L arm's ``arm_fp`` and nowhere in the deployment. The +L arm pins only its arm id
    and learn level — what the loop learns between commits is what it measures."""
    params = inspect.signature(worker.deployment_projection).parameters
    assert not {"arm", "learning", "budget_profile", "budget_for_task"} & set(params)
    deployment_fp = _deployment_fp()
    r1 = _r1_budget()
    off = empty_snapshot("p792")
    on = LearningSnapshot(
        repo="p792", auto_apply=AUTO_CONTEXT, overlay={K_SECTION: {"escalation": "always"}}
    )
    a0 = worker.arm_projection("A0", off, PROFILE_DEFAULT, r1)
    a0l = worker.arm_projection(
        "A0+L", on, PROFILE_CALIBRATED, dataclasses.replace(r1, max_turns=9)
    )
    assert a0 == {
        "arm": "A0",
        "learn": "off",
        "overlay": "",
        "budget_profile": PROFILE_DEFAULT,
        "budget": r1.to_dict(),
    }
    assert a0l == {"arm": "A0+L", "learn": AUTO_CONTEXT}
    a0_fp, a0l_fp = worker.fingerprint(a0), worker.fingerprint(a0l)
    assert a0_fp != a0l_fp
    assert worker.treatment_digest(deployment_fp, a0_fp) != worker.treatment_digest(
        deployment_fp, a0l_fp
    )
    assert worker.treatment_digest(deployment_fp, a0_fp) == worker.treatment_digest(
        _deployment_fp(), worker.fingerprint(worker.arm_projection("A0", off, PROFILE_DEFAULT, r1))
    )
    # the loop learning a new overlay between commits is +L's treatment, not a drift of it
    learned = dataclasses.replace(on, overlay={K_SECTION: {"budget_profile": PROFILE_CALIBRATED}})
    assert worker.fingerprint(worker.arm_projection("A0+L", learned, PROFILE_DEFAULT, r1)) == a0l_fp
    # an overlay reaching a non-L arm is a drift of A0's treatment
    stray = dataclasses.replace(off, overlay={K_SECTION: {"escalation": "always"}})
    assert worker.fingerprint(worker.arm_projection("A0", stray, PROFILE_DEFAULT, r1)) != a0_fp
    # fail closed: an arm that disagrees with the loop switch it ran under is refused
    with pytest.raises(ValueError, match="loop"):
        worker.arm_projection("A0+L", off, PROFILE_DEFAULT, r1)
    with pytest.raises(ValueError, match="loop"):
        worker.arm_projection("A0", on, PROFILE_DEFAULT, r1)
    with pytest.raises(ValueError):
        worker.arm_projection("A9", off, PROFILE_DEFAULT, r1)


def test_p792_a_calibrated_profile_moves_only_arm_fp() -> None:
    """C7: a non-loop run on the calibrated profile is a different arm treatment from one on
    the default profile, and the same deployment. The deployment's r1 budget is the declared
    one (``budget_for_rung`` over the run's budget), never a per-task calibrated cap."""
    r1 = _r1_budget()
    calibrated = dataclasses.replace(r1, max_turns=12, max_tool_calls=14)
    off = empty_snapshot("p792")
    deployment = _deployment()
    assert deployment["budget"] == r1.to_dict()
    assert deployment["budget"]["max_turns"] == 40  # the rung's override, profile-independent
    declared = worker.arm_projection("A0", off, PROFILE_DEFAULT, r1)
    profiled = worker.arm_projection("A0", off, PROFILE_CALIBRATED, r1)
    capped = worker.arm_projection("A0", off, PROFILE_CALIBRATED, calibrated)
    fps = {worker.fingerprint(declared), worker.fingerprint(profiled), worker.fingerprint(capped)}
    assert len(fps) == 3
    assert capped["budget"] == calibrated.to_dict()
    assert _deployment_fp() == worker.fingerprint(deployment)
    sighted = worker.arm_projection("S3", off, PROFILE_CALIBRATED, calibrated)
    assert sighted["budget_profile"] == PROFILE_CALIBRATED


def test_p792_lint_and_runner_opts_move_the_repo_digest() -> None:
    """C4 and C11: switching the repository's lint belt off, or editing its runner options,
    after the first reservation moves the repository digest and so the deployment
    fingerprint (the next reservation halts ``reading_treatment_mismatch``); moving the
    clone or the mining depth moves neither."""
    pinned_repo = worker.repo_config_digest(_repo())
    pinned = _deployment_fp()
    assert _deployment()["repo_config"] == pinned_repo
    for edit in ({"lint": {"disabled": True}}, {"runner_opts": {"python": "python3.13"}}):
        assert worker.repo_config_digest(_repo(**edit)) != pinned_repo, edit
        assert _deployment_fp(config=_repo(**edit)) != pinned, edit
    for edit in ({"path": "/clones/moved"}, {"mining": {"max_candidates": 9}}):
        assert worker.repo_config_digest(_repo(**edit)) == pinned_repo, edit
        assert _deployment_fp(config=_repo(**edit)) == pinned, edit


def test_p792_timeout_and_extra_args_move_the_deployment_fp() -> None:
    """C5 and C3: the run's ``timeout`` (``RunSpec.timeout``) and a ``builder_config`` that
    carries ``extra_args`` or ``claude_binary`` each move the deployment fingerprint; so does
    every other input the deployment takes — each parameter has an edit here, so a new one
    fails until it is shown to be pinned. Only the r1 rung is pinned, and only its non-budget
    config is projected as config (its budget fields are in the r1 budget)."""
    pinned = _deployment_fp()
    assert _deployment()["timeout"] == 1800
    assert _deployment_fp(timeout=1) != pinned
    extra = {"effort": "high", "extra_args": ["--model", "claude-opus-5"]}
    assert _deployment(builder_overrides=extra)["builder_overrides"] == extra
    assert _deployment_fp(builder_overrides=extra) != pinned
    assert _deployment_fp(builder_overrides={"effort": "high", "claude_binary": "/opt/c"}) != pinned
    projected_rung = _deployment()["rung"]
    assert projected_rung == {
        "builder": "claude_code",
        "model": "claude-sonnet-5",
        "provider": "anthropic",
        "config": {},
    }
    assert _deployment_fp(ladder=_ladder(reasoning="max")) != pinned
    edits: dict[str, Any] = {
        "ladder": _ladder(model="claude-opus-5"),
        "budget": base.Budget(max_turns=30, max_tool_calls=60),
        "builder_overrides": {"effort": "low"},
        "container": _container(memory="16g"),
        "executor": "local",
        "timeout": 3600,
        "preflight": Preflight(),
        "escalation": ESCALATION_ALWAYS,
        "posture_class": "docker/readonly/offline",
        "config": _repo(probe="tests/test_other.py"),
        "s1_author": "claude_code:claude-opus-5",
    }
    params = set(inspect.signature(worker.deployment_projection).parameters)
    assert set(edits) == params, "a deployment input has no edit in this test"
    for name, value in sorted(edits.items()):
        assert _deployment_fp(**{name: value}) != pinned, name
    assert _deployment_fp(preflight=Preflight(repair_turns=0)) != _deployment_fp(
        preflight=Preflight()
    )
    # the r2 rung climbs after the reserved attempt; it is not the reserved treatment
    r2_moved = base.EscalationLadder(
        (_ladder().rungs[0], base.Rung("claude_code", "gpt-6", "openai"))
    )
    assert _deployment_fp(ladder=r2_moved) == pinned
    deployment = _deployment()
    assert deployment["apparatus_version"] == worker.APPARATUS_VERSION
    assert json.loads(canonical_json(deployment)) == deployment  # plain JSON, no objects


def test_p792_projection_holds_no_secret() -> None:
    """The treatment body is stored on a reservation event and served on GET /readings, so
    it must hold no secret. A provider key in the worker's environment never reaches it (the
    container is projected by named fields, not by the environment it was read from), and a
    credential-shaped override key or a secret-shaped value anywhere in the projection is
    refused before anything is hashed — fail closed, never projected or dropped, and the
    refusal never repeats the value."""
    env = {
        "CRB_BUILDER__EXECUTOR": "docker",
        "CRB_BUILDER__IMAGE": "crb-builder:1",
        "CRB_BUILDER__USER": "1000:1000",
        "CRB_BUILDER__ANTHROPIC_API_KEY": _FAKE_KEY,
        "CRB_BUILDER__TOKEN": _FAKE_KEY,
        "ANTHROPIC_API_KEY": _FAKE_KEY,
    }
    container = BuilderContainerSettings.from_env(env)
    assert container is not None
    deployment = _deployment(container=container)
    learning = LearningSnapshot(
        repo="p792", auto_apply=AUTO_CONTEXT, overlay={K_SECTION: {"note": _FAKE_KEY}}
    )
    arm = worker.arm_projection("A0+L", learning, PROFILE_DEFAULT, _r1_budget())
    a0 = worker.arm_projection("A0", empty_snapshot("p792"), PROFILE_DEFAULT, _r1_budget())
    body = canonical_json({"deployment": deployment, "arm": arm, "a0": a0})
    assert _FAKE_KEY not in body
    assert "fake" not in body.lower()
    refused = (
        {"api_key": _FAKE_KEY},
        {"env": {"ANTHROPIC_API_KEY": _FAKE_KEY}},
        {"extra_args": ["--header", f"x-api-key={_FAKE_KEY}"]},
        {"extra_args": ["--key", _FAKE_KEY]},
    )
    for overrides in refused:
        with pytest.raises(ValueError) as exc:
            _deployment(builder_overrides=overrides)
        assert _FAKE_KEY not in str(exc.value), overrides
    with pytest.raises(ValueError) as exc:
        _deployment(ladder=_ladder(auth_token=_FAKE_KEY))
    assert _FAKE_KEY not in str(exc.value)


# --- the worker: a reserved.v1 reading's run reserves each commit before its r1 build ------

#: The campaign every worker test's reading names; each run it files is admitted on its trace.
_W_CID = "cmp_" + "w" * 24
#: The cell the fake builder's rows are written in (rung ``fake:m@p``, the fixture's task).
_W_CELL = {
    "process_step": "replay",
    "capability_class": "bug.fix",
    "size": "XS",
    "language": "python",
    "builder": "fake",
    "model": "m",
    "provider": "p",
}


class _WKilled(BaseException):
    """The host killing the worker mid-grade (C1): not an ``Exception``, so neither the grader
    nor the worker records anything — the run is left ``running`` with its reservation."""


class _WExec(LocalExecutor):
    """The run's sandbox: a local executor on the run's cancel token, which the rig's ``exec``
    state switches to lose the sandbox (``lost``), time a command out (``timeout``) or fail
    one on a full disk (``disk``). A command started once the run is asked to cancel is
    killed at once (rc 130), as a sealed worker's gold container is: the fixture's commands
    finish inside the local executor's one-second cancel poll, the sealed witness does not."""

    def __init__(self, state: dict[str, Any], cancel: Callable[[], bool]) -> None:
        super().__init__(cancel=cancel)
        self._state = state
        self._cancel_token = cancel

    def run(self, cmd: Command) -> ExecResult:
        if self._cancel_token():
            return ExecResult(130, "", "", cancelled=True)
        how = self._state.get("exec")
        if how == "lost":
            raise SandboxUnavailable("the sandbox went away")
        if how == "timeout":
            return ExecResult(124, "", "", timed_out=True)
        if how == "disk":
            raise OSError(28, "No space left on device")
        return super().run(cmd)


@dataclasses.dataclass
class _WRig:
    """One worker over the fixture repository with two enrolled commits (``first``, the
    fixture's ``feat: add subtract``, and ``second``, ``feat: add multiply``), the fake
    builder switched by ``state`` (``b``, or ``by_model`` per rung model) and the run's
    sandbox by ``state["exec"]``; every row is written in the sealed posture the reading
    names, as a sealed worker writes it."""

    h: Harness
    first: str
    second: str
    state: dict[str, Any]
    posture: str

    def register(
        self,
        *,
        legacy: bool = False,
        hierarchy: tuple[str, ...] = ("S3",),
        descriptive: tuple[tuple[str, int], ...] = (("A0", 2),),
    ) -> Reading:
        """Register a reading of both commits on the campaign (reserved.v1 unless
        ``legacy``), five minutes ago, and store its ``reading.registered`` event. A reserved.v1
        pool is pinned to the records a ``qualify`` run wrote in the rig's live posture, as
        ``POST /readings`` pins it (P-797)."""
        pins = {} if legacy else self.qualify()
        reading = register(
            repo=pr.REPO_NAME,
            cell=_W_CELL,
            hierarchy=hierarchy,
            descriptive=descriptive,
            pool=[self.first, self.second],
            apparatus=worker.APPARATUS_VERSION,
            taxonomy=GLOBAL_CLASS_SET,
            posture_class=self.posture,
            checks_arm="off",
            actor="op-1",
            hypothesis=HYPOTHESIS,
            smallest_effect=SMALLEST_EFFECT,
            campaign_id=_W_CID,
            now=(datetime.now(UTC) - timedelta(minutes=5)).isoformat(timespec="seconds"),
            **(
                {}
                if legacy
                else {
                    "attempt_rule": ATTEMPT_RULE_RESERVED,
                    "max_reruns": 0,
                    "budget_profile": PROFILE_DEFAULT,
                    **pins,
                }
            ),
        )
        append_event(
            self.h.factory,
            trace_id=f"readings:{pr.REPO_NAME}",
            stage="system",
            action=READING_EVENT_ACTION,
            repo=pr.REPO_NAME,
            payload=reading.to_dict(),
        )
        return reading

    def qualify(self) -> dict[str, Any]:
        """Qualify both commits in the rig's live posture (a ``qualify`` run) and return the
        pins a reserved.v1 registration takes: ``pool_posture_id`` and
        ``pool_qualifications`` (commit → the record in force there)."""
        run = self.h.enqueue("qualify", params_json={"task_ids": [self.first, self.second]})
        self.h.run_one()
        done = self.h.queue.get(run.id)
        assert done is not None and done.status == STATUS_SUCCEEDED, done
        posture_id = str(dict(done.counts_json or {})["posture_id"])
        with self.h.factory() as s:
            records = store_q.latest_by_task(s, pr.REPO_NAME, posture_id)
        assert all(records[c].is_qualified for c in (self.first, self.second)), records
        return {
            "pool_posture_id": posture_id,
            "pool_qualifications": {
                c: records[c].qualification_id for c in (self.first, self.second)
            },
        }

    def enqueue(
        self,
        reading: Reading | None,
        *tasks: str,
        kind: str = "blind",
        admit: bool = True,
        params: dict[str, Any] | None = None,
        **fields: Any,
    ) -> Run:
        """Enqueue a run of ``tasks`` (``first`` by default) filed under ``reading`` (none
        when ``None``), admitted under the campaign unless ``admit`` is false — inserted as
        ``POST /runs`` stores a run the reserved.v1 whitelist admits (the cell's builder,
        model and provider on the ladder ``["r1"]``, the kind's mode, the loop off on the
        reading's budget profile), with ``params`` and ``fields`` laid over it."""
        stored: dict[str, Any] = {
            "task_ids": list(tasks or (self.first,)),
            "limit": None,
            "pool": "",
            "executor": "",
            "timeout": 0,
            "learning": "off",
            "budget_profile": PROFILE_DEFAULT,
        }
        if reading is not None:
            stored["reading_id"] = reading.reading_id
        cell = {k: _W_CELL[k] for k in ("builder", "model", "provider")}
        mode = "blind" if kind == "blind" else "sighted"
        base = {**cell, "mode": mode, "ladder_json": list(RESERVED_RUN_LADDER)}
        run = self.h.enqueue(kind, params_json={**stored, **(params or {})}, **{**base, **fields})
        if admit:
            append_event(
                self.h.factory,
                trace_id=_W_CID,
                stage="system",
                action=CAMPAIGN_ADMITTED,
                payload={"campaign_id": _W_CID, "run_id": run.id},
            )
        return run

    def reservations(self, reading: Reading) -> list[Event]:
        """The reading's ``reading.reserved`` events, in ``Event.id`` order."""
        with self.h.factory() as s:
            return list(
                s.execute(
                    select(Event)
                    .where(
                        Event.action == READING_RESERVED_ACTION,
                        Event.trace_id == reading.reading_id,
                    )
                    .order_by(Event.id)
                ).scalars()
            )

    def verdicts(self, reading: Reading, arm: str) -> dict[str, tuple[bool | None, str]]:
        """Each enrolled commit of ``arm`` as the server reads it: the reading as
        ``load_readings`` fills it, over every row in the ledger."""
        with self.h.factory() as s:
            loaded = next(
                r for r in load_readings(s, pr.REPO_NAME) if r.reading_id == reading.reading_id
            )
        rows = list(self.h.worker.ledger.rows())
        return {c.commit: (c.outcome, c.reason) for c in arm_reading(loaded, arm, rows).commits}

    def actions(self, run_id: str) -> list[str]:
        return [e.action for e in self.h.events(run_id)]

    def payloads(self, run_id: str, action: str) -> list[dict[str, Any]]:
        return [dict(e.payload or {}) for e in self.h.events(run_id) if e.action == action]

    def skips(self, run_id: str) -> list[tuple[str, str]]:
        """The run's ``run.task_skipped`` events as ``(task, reason)``."""
        return [
            (e.task_id, dict(e.payload or {}).get("reason", ""))
            for e in self.h.events(run_id)
            if e.action == "run.task_skipped"
        ]

    def rows(self, run_id: str) -> list[GradeRow]:
        return list(self.h.worker.ledger.rows(run_id=run_id))

    def status(self, run_id: str) -> str:
        run = self.h.queue.get(run_id)
        assert run is not None
        return run.status

    def edit_config(self, **changes: Any) -> None:
        """Edit the repository's stored ``RepoConfig`` (what the next claim loads)."""
        with self.h.factory() as s:
            repo = s.get(Repo, pr.REPO_NAME)
            assert repo is not None
            repo.config_json = {**dict(repo.config_json or {}), **changes}
            s.commit()


def _w_rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store: Backend | None = None) -> _WRig:
    """The worker rig on SQLite, or on ``store``'s database when one is given."""
    pyrepo = pr.build(tmp_path / "pyrepo")
    p = pyrepo.path
    (p / pr.SRC).write_text(
        pr.SRC_FEAT + "\n\ndef multiply(a: int, b: int) -> int:\n    return a * b\n",
        encoding="utf-8",
    )
    (p / pr.TEST_MULTIPLY).write_text(pr.TEST_MULTIPLY_SRC, encoding="utf-8")
    pr.git(p, "add", "-A")
    pr.git(p, "commit", "-q", "-m", "feat: add multiply")
    second = pr.git(p, "rev-parse", "HEAD")
    h = Harness(tmp_path, pyrepo)
    if store is not None:
        h.url = store.url
        h.settings = dataclasses.replace(h.settings, database_url=store.url)
        h.worker = worker.Worker(h.settings, engine=store.engine)
        h.factory = h.worker.factory
        h.queue = JobQueue(h.factory)
    h.add_repo()
    h.add_task(pyrepo.feat_task())
    h.add_task(
        pyrepo.feat_task(
            task_id=second,
            subject="feat: add multiply",
            authored=pyrepo.repo.author_date(second),
            test_files=(pr.TEST_MULTIPLY,),
            target_tests=(pr.TEST_MULTIPLY,),
            baseline_failing=(pr.TEST_MULTIPLY,),
            labels={"change_id": change_identity(pyrepo.repo, second)},
        )
    )
    state: dict[str, Any] = {"b": "gold", "by_model": {}, "exec": "", "created": ""}
    monkeypatch.setitem(
        builders_pkg._REGISTRY,
        "fake",
        lambda **cfg: FakeBuilder(
            **{**cfg, "behaviour": state["by_model"].get(cfg.get("model"), state["b"])}
        ),
    )
    monkeypatch.setattr(FakeBuilder, "briefs", [])
    monkeypatch.setattr(FakeBuilder, "hook", None)
    w = h.worker
    # a sealed worker: both executors docker (P-789), the sandbox a local one on the cancel token
    monkeypatch.setattr(
        w, "settings", dataclasses.replace(w.settings, executor="docker", builder_executor="docker")
    )
    monkeypatch.setattr(w, "_executor", lambda ctx: _WExec(state, cancel=lambda: w._cancelled(ctx)))
    monkeypatch.setenv("CRB_BUILDER__IMAGE", "crb-builder:test")
    monkeypatch.delenv("CRB_BUILDER__EXECUTOR", raising=False)
    posture = w._deployment_posture_class(pr.REPO_NAME, "docker")
    append = w.ledger.append

    def sealed_append(row: GradeRow, *, guard: Any = None) -> GradeRow:
        # the local sandbox and the host-run fake builder label a row unsealed: relabel it as
        # the sealed worker it stands in for writes it (and, for C9, at a chosen ``created``)
        labels = {**row.labels, LABEL_POSTURE_CLASS: posture, LABEL_BUILDER_EXECUTOR: "docker"}
        fields = {**row.fields(), "labels": labels}
        if state["created"]:
            fields["created"] = state["created"]
        return append(GradeRow(**fields), guard=guard)

    monkeypatch.setattr(w.ledger, "append", sealed_append)
    return _WRig(h, pyrepo.feat_sha, second, state, posture)


def _w_peek(rig: _WRig, monkeypatch: pytest.MonkeyPatch, at: Callable[[Run], None]) -> None:
    """Call ``at(run)`` once per build, as soon as grading has emitted belt 2 red — the
    moment the enumeration's operator peeked at the outcome before it was recorded."""
    real = rig.h.worker._emitter

    def emitter(run: Run) -> Any:
        e = real(run)
        on_event = e.on_event
        built = [False]

        def staged(stage: str, *a: Any, **kw: Any) -> Callable[[str, dict[str, Any]], Any]:
            cb = on_event(stage, *a, **kw)

            def call(action: str, payload: dict[str, Any]) -> Any:
                out = cb(action, payload)
                if action == "build.start":
                    built[0] = True
                elif (
                    built[0]
                    and action == "grade.belt"
                    and payload.get("belt") == "target_green"
                    and payload.get("value") is False
                ):
                    built[0] = False
                    at(run)
                return out

            return call

        e.on_event = staged
        return e

    monkeypatch.setattr(rig.h.worker, "_emitter", emitter)


def _w_event_ids(rig: _WRig, run_id: str) -> dict[str, list[int]]:
    """``Event.id`` of each of a run's events, by action."""
    out: dict[str, list[int]] = {}
    with rig.h.factory() as s:
        for ev in s.execute(select(Event).where(Event.trace_id == run_id)).scalars():
            out.setdefault(ev.action, []).append(int(ev.id))
    return out


def _w_row_count(rig: _WRig) -> int:
    return len(list(rig.h.worker.ledger.rows()))


def test_p792_c1_kill_after_peek_costs_the_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: Backend
) -> None:
    """C1, measured: reproduces the enumeration's kill probe (tests/test_zz_enum_kill_probe.py),
    which killed the worker as soon as belt 2 read red, before the row was written; the run was
    reclaimed and re-run with a clean builder, and the commit read a hit. Now the kill leaves
    the reservation: the reclaimed run skips the commit without building it, the commit reads
    a miss (``unobserved``) once its claim is settled, and a late append by the killed claim is
    refused under the grades lock."""
    rig = _w_rig(tmp_path, monkeypatch, backend)
    reading = rig.register()
    run = rig.enqueue(reading)
    rig.state["b"] = "noop"

    def kill(_: Run) -> None:
        raise _WKilled

    _w_peek(rig, monkeypatch, kill)
    with pytest.raises(_WKilled):
        rig.h.run_one()
    (res,) = rig.reservations(reading)
    assert (res.step_id, res.task_id) == ("A0", rig.first)
    assert rig.status(run.id) == STATUS_RUNNING
    assert rig.rows(run.id) == []
    # the killed claim is still running: the commit waits for it
    assert rig.verdicts(reading, "A0")[rig.first] == (None, "pending")

    assert [r.id for r in rig.h.queue.reclaim_stale(0.0)] == [run.id]
    rig.state["b"] = "gold"
    again = rig.h.run_one()
    assert again.id == run.id
    assert rig.skips(run.id) == [(rig.first, SKIP_COMMIT_RESERVED)]
    assert len(FakeBuilder.briefs) == 1  # the killed attempt's build; the re-run built nothing
    assert rig.rows(run.id) == []
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "unobserved")
    assert len(rig.reservations(reading)) == 1

    # the killed claim's row, had it reached the ledger late, is refused and never stored
    before = _w_row_count(rig)
    late = sealed_row(
        rig.first,
        clean=False,
        arm="A0",
        repo=pr.REPO_NAME,
        labels={LABEL_RESERVATION: res.event_id, LABEL_CLAIM: "0"},
    )
    with pytest.raises(AttemptSettled):
        rig.h.worker.ledger.append(late, guard=claim_guard(run.id, "w-test", 0))
    assert _w_row_count(rig) == before
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "unobserved")


def test_p792_c2_cancel_during_witness_is_a_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C2, measured in round 4: a cancel asked as soon as belt 2 read red reached the gold
    witness, which the run's cancel token stopped; the row was a harness failure, which the
    legacy rule passes over, so a second run re-rolled the commit and it read a hit. Now the
    harness row is the reserved attempt's and decides the commit: a miss (``harness``), and
    the second run skips the commit without building it."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    run = rig.enqueue(reading)
    rig.state["b"] = "noop"
    _w_peek(rig, monkeypatch, lambda r: rig.h.queue.request_cancel(r.id, actor="op-1"))
    rig.h.run_one()
    (res,) = rig.reservations(reading)
    (row,) = rig.rows(run.id)
    assert row.labels[LABEL_RESERVATION] == res.event_id
    assert row.failure_kind == "harness"
    assert row.labels["env_code"] == "GOLD_CONTROL_RED"
    (control,) = rig.payloads(run.id, "grade.control")
    assert (control["green"], control["rc"]) == (False, 130)
    assert rig.status(run.id) not in (STATUS_QUEUED, STATUS_RUNNING)
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "harness")

    rig.state["b"] = "gold"
    second = rig.enqueue(reading)
    rig.h.run_one()
    assert "build.start" not in rig.actions(second.id)
    assert rig.skips(second.id) == [(rig.first, SKIP_COMMIT_RESERVED)]
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "harness")


def test_p792_c5_timeout_refused_and_gold_red_is_a_miss(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C5, measured in round 4: a short timeout turned an honest attempt red, a gold control
    that timed out (blame ``GOLD_CONTROL_RED``) wrote a harness row the legacy rule passes
    over, and a later clean row of another run decided the commit; and a ``RepoConfig`` edit
    moved what later attempts ran under while the reading read on. (a) ``POST /runs`` filed
    under a reserved.v1 reading with its own ``timeout`` is refused 422 ``reading_run_fields``
    naming ``timeout``, nothing queued (201 before the route's check), on ``backend``'s
    store. (b) Now the timed-out control's row is the reserved attempt's: a miss, which a
    later clean row never changes. (c) A ``runner_opts`` edit after the first reservation
    halts the next run ``reading_treatment_mismatch`` before ``build.start``, naming the
    field that moved."""
    (tmp_path / "submit").mkdir()
    with _r_stack(backend, tmp_path / "submit", monkeypatch) as w:
        a0 = _a0(w, ("cobra", "XS"))
        _r_fields(w, {**a0, "timeout": 1}, ["timeout"])
        _r_admit(w, a0)

    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    # (b) the reserved attempt's gold control times out
    run = rig.enqueue(reading)
    rig.state["b"] = "noop"
    _w_peek(rig, monkeypatch, lambda _: rig.state.update(exec="timeout"))
    rig.h.run_one()
    (res,) = rig.reservations(reading)
    (row,) = rig.rows(run.id)
    assert row.labels[LABEL_RESERVATION] == res.event_id
    assert row.labels["env_code"] == "GOLD_CONTROL_RED"
    assert "gold control red" in row.error
    miss = rig.verdicts(reading, "A0")[rig.first]
    assert miss == (False, "harness")
    # a later clean row of another admitted run, under no reading, changes nothing
    rig.state.update(b="gold", exec="")
    other = rig.enqueue(None)
    rig.h.run_one()
    (clean,) = rig.rows(other.id)
    assert clean.clean and LABEL_RESERVATION not in clean.labels
    assert rig.verdicts(reading, "A0")[rig.first] == miss

    # (c) the repository's runner options move after the first reservation
    cfg = rig.h.pyrepo.config.to_dict()
    rig.edit_config(runner_opts={**dict(cfg.get("runner_opts") or {}), "p792_edit": "1"})
    rig.state["b"] = "multiply"
    moved = rig.enqueue(reading, rig.second)
    done = rig.h.run_one()
    assert done.status == STATUS_FAILED
    assert done.error == HALT_TREATMENT_MISMATCH
    (halted,) = rig.payloads(moved.id, "run.halted")
    assert halted["reason"] == HALT_TREATMENT_MISMATCH
    detail = halted["detail"]
    assert detail["half"] == "deployment"
    assert detail["pinned"] == dict(res.payload_json)["deployment_fp"]
    assert detail["ours"] != detail["pinned"]
    assert detail["pinned_by"] == res.event_id
    assert detail["fields"] == ["repo_config"]
    assert "build.start" not in rig.actions(moved.id)
    assert rig.rows(moved.id) == []
    assert len(rig.reservations(reading)) == 1
    assert rig.verdicts(reading, "A0")[rig.second] == (None, "pending")


def test_p792_claim_refuses_timeout_and_a_budget_profile_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C5 and C7 at claim (C17: the whitelist is the claim's too, not only the submit's): a
    run of a reserved.v1 reading inserted past ``POST /runs`` with its own ``timeout`` (C5:
    a short timeout turns an honest attempt red), or spending on a budget profile other than
    the reading's (C7), fails at claim with ``run.refused`` ``reading_run_fields`` naming the
    field — nothing built, nothing reserved, the commit pending. The same run as submit stores
    it is claimed, builds and reserves, so the refusals are the fields' and nothing else's."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    for params, field in (
        ({"timeout": 5}, "timeout"),
        ({"budget_profile": PROFILE_CALIBRATED}, "budget_profile"),
    ):
        queued = rig.enqueue(reading, params=params)
        done = rig.h.run_one()
        assert (done.id, done.status) == (queued.id, STATUS_FAILED), field
        (why,) = rig.payloads(queued.id, "run.refused")
        assert (why["code"], why["fields"], why["arm"]) == (REFUSAL_RUN_FIELDS, [field], "A0")
        assert field in why["reasons"] and done.error.startswith(REFUSAL_RUN_FIELDS)
        assert "build.start" not in rig.actions(queued.id) and rig.rows(queued.id) == []
    assert FakeBuilder.briefs == [] and rig.reservations(reading) == []
    assert rig.verdicts(reading, "A0")[rig.first] == (None, "pending")
    run = rig.enqueue(reading)
    rig.h.run_one()
    assert "run.refused" not in rig.actions(run.id)
    (res,) = rig.reservations(reading)
    assert (res.step_id, res.task_id) == ("A0", rig.first)
    assert rig.verdicts(reading, "A0")[rig.first] == (True, "")


def test_p792_c9_reservation_before_registration_is_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C9, from enumeration.md by code reading (no probe ran): a row whose ``created`` does
    not fall after the registration — a worker clock rolled back — was out of the reading's
    scope, so the legacy rule passed over it and a later attempt decided the commit. Now the
    reserved attempt's row decides it even so: a miss (``out_of_scope``), and a second run
    skips the commit."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    run = rig.enqueue(reading)
    rig.state["created"] = reading.registered_at  # the worker's clock reads the registration
    rig.h.run_one()
    (res,) = rig.reservations(reading)
    (row,) = rig.rows(run.id)
    assert row.clean and row.created == reading.registered_at
    assert row.labels[LABEL_RESERVATION] == res.event_id
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "out_of_scope")

    rig.state["created"] = ""
    second = rig.enqueue(reading)
    rig.h.run_one()
    assert "build.start" not in rig.actions(second.id)
    assert rig.skips(second.id) == [(rig.first, SKIP_COMMIT_RESERVED)]
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "out_of_scope")


def test_p792_c10_sandbox_loss_after_reserve_is_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C10, from enumeration.md by code reading (no probe ran): a sandbox lost after the
    build stopped the run with no row, and a host-side failure inside grading wrote a harness
    row; the legacy rule read the commit pending, or passed over the harness row, so a later
    attempt decided it. Now both are the reserved attempt's: the lost sandbox reads
    ``unobserved`` once the run has failed, and a second run skips the commit; a full disk
    under the grader is a ``harness`` miss."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    run = rig.enqueue(reading)
    monkeypatch.setattr(FakeBuilder, "hook", lambda ws, brief: rig.state.update(exec="lost"))
    done = rig.h.run_one()
    assert done.status == STATUS_FAILED
    assert done.error.startswith("sandbox unavailable")
    assert rig.rows(run.id) == []
    (res,) = rig.reservations(reading)
    assert res.task_id == rig.first
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "unobserved")

    monkeypatch.setattr(FakeBuilder, "hook", None)
    rig.state["exec"] = ""
    again = rig.enqueue(reading)
    rig.h.run_one()
    assert "build.start" not in rig.actions(again.id)
    assert rig.skips(again.id) == [(rig.first, SKIP_COMMIT_RESERVED)]
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "unobserved")

    # the second commit's grader fails on the host: a harness row, the reserved attempt's
    rig.state["b"] = "multiply"
    monkeypatch.setattr(FakeBuilder, "hook", lambda ws, brief: rig.state.update(exec="disk"))
    disk = rig.enqueue(reading, rig.second)
    rig.h.run_one()
    (row,) = rig.rows(disk.id)
    assert row.failure_kind == "harness"
    assert row.labels[LABEL_RESERVATION] == rig.reservations(reading)[1].event_id
    assert rig.verdicts(reading, "A0")[rig.second] == (False, "harness")


def test_p792_c11_inflight_attempt_uses_claim_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C11, measured: the reading side re-confirmed by tests/test_zz_enum_fwd_lint_probe.py — a
    ``RepoConfig`` edit changed what later attempts were graded under while the reading read
    on. Now an attempt in flight when the configuration is edited is graded on the claim's
    snapshot and decides its commit on the treatment it reserved (a hit), and the next run,
    which loads the edit, halts ``reading_treatment_mismatch`` before ``build.start``."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    run = rig.enqueue(reading)
    cfg = rig.h.pyrepo.config.to_dict()
    edit = {**dict(cfg.get("runner_opts") or {}), "p792_edit": "1"}
    monkeypatch.setattr(FakeBuilder, "hook", lambda ws, brief: rig.edit_config(runner_opts=edit))
    rig.h.run_one()
    (res,) = rig.reservations(reading)
    (row,) = rig.rows(run.id)
    assert row.clean
    assert row.labels[LABEL_TREATMENT] == dict(res.payload_json)["treatment"]
    assert rig.verdicts(reading, "A0")[rig.first] == (True, "")

    monkeypatch.setattr(FakeBuilder, "hook", None)
    rig.state["b"] = "multiply"
    later = rig.enqueue(reading, rig.second)
    done = rig.h.run_one()
    assert done.error == HALT_TREATMENT_MISMATCH
    (halted,) = rig.payloads(later.id, "run.halted")
    assert halted["detail"]["fields"] == ["repo_config"]
    assert "build.start" not in rig.actions(later.id)
    assert rig.verdicts(reading, "A0") == {rig.first: (True, ""), rig.second: (None, "pending")}


def test_p792_c12_demoted_row_is_miss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C12, from enumeration.md by code reading (no probe ran): a clean row whose evidence
    pack could not be kept is demoted to a harness failure, which the legacy rule passed
    over, so a later attempt decided the commit. Now the demoted row keeps its reservation
    and decides the commit: a miss (``harness``), and a second run skips it."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    run = rig.enqueue(reading)
    kept = worker._RunLedger._kept_pack
    monkeypatch.setattr(
        worker._RunLedger, "_kept_pack", lambda self, row: (None, "the pack store refused it")
    )
    rig.h.run_one()
    (res,) = rig.reservations(reading)
    (row,) = rig.rows(run.id)
    assert not row.clean and row.failure_kind == "harness"
    assert row.labels[LABEL_RESERVATION] == res.event_id
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "harness")

    monkeypatch.setattr(worker._RunLedger, "_kept_pack", kept)
    second = rig.enqueue(reading)
    rig.h.run_one()
    assert "build.start" not in rig.actions(second.id)
    assert rig.skips(second.id) == [(rig.first, SKIP_COMMIT_RESERVED)]
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "harness")


def test_p792_c13_credential_gone_before_reserve_stays_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C13, from enumeration.md by code reading (no probe ran): a provider outage row was an
    outage the legacy rule passed over, so a later attempt decided the commit. Now a refusal
    before the reservation — the claim's credential check — writes nothing and leaves the
    commit pending, while an outage after it is the reserved attempt's miss (``outage``),
    and the next run skips the commit."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    gone = "credential_missing: ANTHROPIC_API_KEY is unset"
    real = rig.h.worker._credential_gone
    monkeypatch.setattr(rig.h.worker, "_credential_gone", lambda run: gone)
    refused = rig.enqueue(reading)
    done = rig.h.run_one()
    assert (done.status, done.error) == (STATUS_FAILED, gone)
    assert "build.start" not in rig.actions(refused.id)
    assert rig.reservations(reading) == []
    assert rig.verdicts(reading, "A0")[rig.first] == (None, "pending")

    monkeypatch.setattr(rig.h.worker, "_credential_gone", real)
    rig.state["b"] = "outage"
    run = rig.enqueue(reading)
    rig.h.run_one()
    (res,) = rig.reservations(reading)
    (row,) = rig.rows(run.id)
    assert row.failure_kind == "outage" and row.labels[LABEL_RESERVATION] == res.event_id
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "outage")

    rig.state["b"] = "gold"
    third = rig.enqueue(reading)
    rig.h.run_one()
    assert "build.start" not in rig.actions(third.id)
    assert rig.skips(third.id) == [(rig.first, SKIP_COMMIT_RESERVED)]
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "outage")


def test_p792_c15_settled_reservation_without_a_row_is_a_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C15, from enumeration.md by code reading (no probe ran), and its mechanism measured
    here: on the replay path a discard that fails after the builder raised grades the edits
    as they are and writes a clean row naming the builder's error in its ``builder_error``
    label (the ledger refuses only a clean row with an ``error``), not no row as the
    enumeration read; that row is the reserved attempt's and decides the commit, and a later
    run skips the commit rather than re-rolling it. What C15's fix needs is that an attempt
    which ends with no row — here the ledger refusing the write — reads a miss
    (``unobserved``) once its run has failed, never pending for a later attempt to decide."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()

    def applied_then_raised(ws: Any, brief: Any) -> None:
        pr.apply_gold(ws)
        raise RuntimeError("the builder fell over after editing")

    def undiscardable(*_: Any, **__: Any) -> list[str]:
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(FakeBuilder, "hook", applied_then_raised)
    monkeypatch.setattr(adapter_mod, "discard_source_edits", undiscardable)
    raised = rig.enqueue(reading)
    rig.h.run_one()
    assert "builder.discard.error" in rig.actions(raised.id)
    (res,) = rig.reservations(reading)
    (row,) = rig.rows(raised.id)
    assert row.clean and not row.error
    assert row.labels["builder_error"].startswith("builder raised RuntimeError")
    assert row.labels[LABEL_RESERVATION] == res.event_id
    assert rig.verdicts(reading, "A0")[rig.first] == (True, "")

    monkeypatch.setattr(FakeBuilder, "hook", None)
    reroll = rig.enqueue(reading)
    rig.h.run_one()
    assert "build.start" not in rig.actions(reroll.id)
    assert rig.skips(reroll.id) == [(rig.first, SKIP_COMMIT_RESERVED)]

    # the second commit's row never reaches the ledger: a settled reservation with no row
    append = rig.h.worker.ledger.append

    def refused(row: GradeRow, *, guard: Any = None) -> GradeRow:
        if row.task_id == rig.second:
            raise OSError(28, "No space left on device")
        return append(row, guard=guard)

    monkeypatch.setattr(rig.h.worker.ledger, "append", refused)
    rig.state["b"] = "multiply"
    lost = rig.enqueue(reading, rig.second)
    done = rig.h.run_one()
    assert done.status == STATUS_FAILED
    assert rig.rows(lost.id) == []
    assert [e.task_id for e in rig.reservations(reading)] == [rig.first, rig.second]
    assert rig.verdicts(reading, "A0")[rig.second] == (False, "unobserved")

    monkeypatch.setattr(rig.h.worker.ledger, "append", append)
    again = rig.enqueue(reading, rig.second)
    rig.h.run_one()
    assert "build.start" not in rig.actions(again.id)
    assert rig.skips(again.id) == [(rig.second, SKIP_COMMIT_RESERVED)]
    assert rig.verdicts(reading, "A0") == {
        rig.first: (True, ""),
        rig.second: (False, "unobserved"),
    }


def test_p792_tally_charges_unrowed_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: Backend
) -> None:
    """C1's spend (F8, C19's tally half): a run killed after its reservation and before
    ``build.done`` leaves the reservation and no row. While its claim is live the attempt is
    in flight — held under the run's cap and headroom, never charged; once the run is
    reclaimed past that claim the attempt is settled, and the tally charges it at its
    reservation's hold and stops the campaign ``unplaced_spend`` (before, it charged nothing
    and admitted the next run). The reclaimed run skips the commit and ends, and the attempt
    is still charged once. A settled reservation whose hold is ``None`` (an r1 rung with no
    cost cap) is a cost the tally cannot know: ``campaign_cost_unknown``."""
    rig = _w_rig(tmp_path, monkeypatch, backend)
    reading = rig.register()
    hold: dict[str, float | None] = {"usd": 0.4}
    real = rig.h.worker._reserver
    monkeypatch.setattr(
        rig.h.worker,
        "_reserver",
        lambda *a, **kw: real(*a, **{**kw, "hold_usd": hold["usd"]}),
    )

    def killed(ws: Any, brief: Any) -> None:
        raise _WKilled

    def admitted(*tasks: str) -> Run:
        # filed as POST /runs admits it: a $1.00 cap and the $5.00 held before a priced attempt
        run = rig.enqueue(reading, *tasks, admit=False)
        append_event(
            rig.h.factory,
            trace_id=_W_CID,
            stage="system",
            action=CAMPAIGN_ADMITTED,
            payload={
                "campaign_id": _W_CID,
                "run_id": run.id,
                "cap_usd": 1.0,
                "s1": False,
                "commits": 1,
                "headroom_usd": 5.0,
            },
        )
        return run

    def tallied() -> tuple[list[Any], list[Any]]:
        with rig.h.factory() as s:
            ms = campaigns_mod.members(s, _W_CID)
            return campaigns_mod.unplaced_attempts(s, [m.run_id for m in ms]), ms

    monkeypatch.setattr(FakeBuilder, "hook", killed)
    run = admitted()
    with pytest.raises(_WKilled):
        rig.h.run_one()
    (res,) = rig.reservations(reading)
    assert rig.status(run.id) == STATUS_RUNNING
    assert "build.done" not in rig.actions(run.id) and rig.rows(run.id) == []
    # in flight: the live claim's run holds its cap and headroom, and nothing is charged
    unplaced, ms = tallied()
    assert unplaced == [] and ms[0].spent_usd == 0.0
    live = tally(54.0, ms)
    assert live.held_usd == pytest.approx(1.0 + 5.0)
    assert live.refusal(cap_usd=1.0, s1=False, commits=0) is None

    assert [r.id for r in rig.h.queue.reclaim_stale(0.0)] == [run.id]
    want = campaigns_mod.UnplacedAttempt(
        run_id=run.id,
        task_id=rig.first,
        trial="r1",
        rung="",
        cost_usd=0.4,
        reservation_event_id=res.event_id,
        reading_id=reading.reading_id,
    )
    unplaced, ms = tallied()
    assert unplaced == [want]
    assert ms[0].unrowed_usd == pytest.approx(0.4) and ms[0].spent_usd == pytest.approx(0.4)
    stop = tally(54.0, ms).refusal(cap_usd=1.0, s1=False, commits=0)
    assert stop is not None and stop.code == "unplaced_spend"
    assert stop.detail == {"run_ids": [run.id]}

    # the reclaimed run skips the reserved commit and ends: the attempt is charged once
    monkeypatch.setattr(FakeBuilder, "hook", None)
    assert rig.h.run_one().id == run.id
    assert rig.skips(run.id) == [(rig.first, SKIP_COMMIT_RESERVED)]
    assert rig.status(run.id) not in (STATUS_QUEUED, STATUS_RUNNING)
    unplaced, ms = tallied()
    assert unplaced == [want] and ms[0].spent_usd == pytest.approx(0.4)

    # a reservation held at None: settled, its cost unknown — the unknown cost stops first
    hold["usd"] = None
    monkeypatch.setattr(FakeBuilder, "hook", killed)
    second = admitted(rig.second)
    with pytest.raises(_WKilled):
        rig.h.run_one()
    assert [r.id for r in rig.h.queue.reclaim_stale(0.0)] == [second.id]
    unplaced, ms = tallied()
    assert [(u.run_id, u.task_id, u.cost_usd) for u in unplaced] == [
        (run.id, rig.first, 0.4),
        (second.id, rig.second, None),
    ]
    assert ms[1].unknown == 1 and ms[1].unrowed_usd == 0.0
    stop = tally(54.0, ms).refusal(cap_usd=1.0, s1=False, commits=0)
    assert stop is not None and stop.code == "campaign_cost_unknown"
    assert stop.detail == {"run_ids": [second.id]}


def test_p792_s3_and_a0_share_commits_without_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reservation is per (reading, arm, commit): a sighted replay (S3) and a blind run
    (A0) of the same commit each reserve it on their own arm, neither skips, and each arm's
    commit is decided by its own reservation's row."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    sighted = rig.enqueue(reading, kind="replay")
    rig.h.run_one()
    blind = rig.enqueue(reading, kind="blind")
    rig.h.run_one()
    s3, a0 = rig.reservations(reading)
    assert [(e.step_id, e.task_id) for e in (s3, a0)] == [("S3", rig.first), ("A0", rig.first)]
    assert rig.skips(sighted.id) == [] and rig.skips(blind.id) == []
    ((s3_row,), (a0_row,)) = rig.rows(sighted.id), rig.rows(blind.id)
    assert s3_row.labels[LABEL_RESERVATION] == s3.event_id
    assert a0_row.labels[LABEL_RESERVATION] == a0.event_id
    assert rig.verdicts(reading, "S3")[rig.first] == (True, "")
    assert rig.verdicts(reading, "A0")[rig.first] == (True, "")
    # the arms share the deployment half: the blind run's reservation is pinned by the S3 one
    assert dict(a0.payload_json)["pinned_by"] == s3.event_id
    assert dict(a0.payload_json)["deployment_fp"] == dict(s3.payload_json)["deployment_fp"]


def test_p792_reserve_only_at_r1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A reserved run reserves before its r1 build only. The claim's whitelist refuses a
    two-rung ladder before anything is built (``reading_run_fields``, the ladder named); past
    it — the claim check stubbed, as a run that reached the reserver by another path — a
    two-rung run whose r1 misses climbs to r2 without a second reservation and is not halted;
    the r2 row carries no reservation, so it never decides the commit — the r1 miss does."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    rig.state["by_model"] = {"m": "noop", "m2": "gold"}
    ladder = ["fake:m@p", "fake:m2@p"]
    refused = rig.enqueue(reading, ladder_json=ladder)
    assert rig.h.run_one().status == STATUS_FAILED
    (why,) = rig.payloads(refused.id, "run.refused")
    assert (why["code"], why["fields"]) == (REFUSAL_RUN_FIELDS, ["ladder"])
    assert "build.start" not in rig.actions(refused.id) and rig.reservations(reading) == []
    monkeypatch.setattr(rig.h.worker, "_reading_run_fields", lambda run, emitter: None)
    run = rig.enqueue(reading, ladder_json=ladder)
    rig.h.run_one()
    assert "run.halted" not in rig.actions(run.id)
    (res,) = rig.reservations(reading)
    r1, r2 = rig.rows(run.id)
    assert (r1.trial, r1.clean, r2.trial, r2.clean) == ("r1", False, "r2", True)
    assert r1.labels[LABEL_RESERVATION] == res.event_id
    assert LABEL_RESERVATION not in r2.labels
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "miss")


def test_p792_reservation_precedes_outcome_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C6's companion: the reservation is written before anything the attempt shows — its
    ``Event.id`` is below the task's ``build.start`` and every ``grade.*`` event of the run,
    so no outcome can be seen before the commit is spent."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    run = rig.enqueue(reading)
    rig.h.run_one()
    (res,) = rig.reservations(reading)
    ids = _w_event_ids(rig, run.id)
    outcome = [i for action, got in ids.items() if action.startswith("grade.") for i in got]
    assert ids["build.start"] and outcome
    assert int(res.id) < min([*ids["build.start"], *outcome])


def test_p792_concurrent_reserve_one_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: Backend
) -> None:
    """Two runs of the reading, claimed at once, race to reserve the same (reading, arm,
    commit) from two threads: one reservation is written and the other run skips the commit
    — the events lock decides, on SQLite and on PostgreSQL."""
    rig = _w_rig(tmp_path, monkeypatch, backend)
    reading = rig.register()
    for _ in range(2):
        rig.enqueue(reading)
    w = rig.h.worker
    task = rig.h.pyrepo.feat_task()
    reservers = []
    for _ in range(2):
        run = rig.h.queue.claim_next(w.worker_id)
        assert run is not None
        emitter = w._emitter(run)
        config, git = w._load_repo(run.repo, emitter, kind=run.kind)
        reservers.append(
            w._reserver(
                worker.RunContext(run=run, emitter=emitter, config=config, git=git),
                reading.reading_id,
                arm="A0",
                deployment={"d": 1},
                arm_body_for=lambda t: {"a": 1},
                hold_usd=None,
                ledger=types.SimpleNamespace(reserved={}),  # type: ignore[arg-type]
            )
        )
    gate = threading.Barrier(2)
    got: list[Any] = [None, None]

    def race(i: int) -> None:
        gate.wait()
        got[i] = reservers[i](task)

    threads = [threading.Thread(target=race, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted((r.status, r.reason) for r in got) == [
        ("ok", ""),
        ("skip", SKIP_COMMIT_RESERVED),
    ]
    assert len(rig.reservations(reading)) == 1


def test_p792_attempt_settled_reaches_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reserved attempt whose run is reclaimed mid-build reaches the ledger as a claim that
    is no longer its own: the append raises ``AttemptSettled``, the worker writes neither the
    row nor the run's finish (``run.finish_refused``; the reclaimed run stays queued for its
    new claim), and the new claim skips the commit, which reads ``unobserved``."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    run = rig.enqueue(reading)
    finished: list[tuple[Any, ...]] = []
    finish = rig.h.worker.queue.finish

    def spy(*a: Any, **kw: Any) -> Any:
        finished.append(a)
        return finish(*a, **kw)

    monkeypatch.setattr(rig.h.worker.queue, "finish", spy)
    monkeypatch.setattr(FakeBuilder, "hook", lambda ws, brief: rig.h.queue.reclaim_stale(0.0))
    rig.h.run_one()
    assert "run.finish_refused" in rig.actions(run.id)
    assert finished == []
    assert rig.rows(run.id) == []
    assert rig.status(run.id) == STATUS_QUEUED
    (res,) = rig.reservations(reading)

    monkeypatch.setattr(FakeBuilder, "hook", None)
    again = rig.h.run_one()
    assert again.id == run.id
    assert rig.skips(run.id) == [(rig.first, SKIP_COMMIT_RESERVED)]
    assert rig.rows(run.id) == []
    assert [e.event_id for e in rig.reservations(reading)] == [res.event_id]
    assert rig.verdicts(reading, "A0")[rig.first] == (False, "unobserved")


def test_p792_a_legacy_readings_run_never_reserves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run filed under a legacy (``first_observed.v0``) reading reserves nothing: no
    ``reading.reserved`` event, no reservation label on its row, and a second run builds the
    commit again, as it always did. Green before the change by design — it pins that the
    worker's reserver is wired only for a reserved.v1 reading."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register(legacy=True)
    first = rig.enqueue(reading)
    rig.h.run_one()
    second = rig.enqueue(reading)
    rig.h.run_one()
    assert rig.reservations(reading) == []
    rows = [*rig.rows(first.id), *rig.rows(second.id)]
    assert len(rows) == 2 and all(LABEL_RESERVATION not in r.labels for r in rows)
    assert "build.start" in rig.actions(second.id)
    assert rig.skips(first.id) == rig.skips(second.id) == []
    assert rig.verdicts(reading, "A0")[rig.first] == (True, "")


def test_p792_post_readings_opts_in_to_reserved(tmp_path: Path) -> None:
    """``POST /readings`` registers a reserved.v1 reading only when asked: a body naming no
    rule is registered under the legacy rule as before, ``attempt_rule: reserved.v1`` stores
    ``max_reruns`` 0 and the budget profile (``default`` unless named), and a reserved.v1
    body asking for reruns is refused 422 and writes nothing."""
    from fixtures.proven import add_tasks, register_via_api
    from fixtures.readings import SEALED_SETTINGS, qualify_pool
    from fixtures.server_seed import ALPHA, envelope, make_env

    with make_env(tmp_path, **SEALED_SETTINGS) as env:
        qualify_pool(env.factory, ALPHA, add_tasks(env.factory))
        legacy = register_via_api(env)
        assert legacy.status_code == 201, legacy.text
        got = legacy.json()
        assert got.get("attempt_rule", "") in ("", ATTEMPT_RULE_LEGACY)
        assert got["max_reruns"] == DEFAULT_MAX_RERUNS
        reserved = register_via_api(env, attempt_rule=ATTEMPT_RULE_RESERVED)
        assert reserved.status_code == 201, reserved.text
        body = reserved.json()
        assert body["attempt_rule"] == ATTEMPT_RULE_RESERVED
        assert (body["max_reruns"], body["budget_profile"]) == (0, PROFILE_DEFAULT)
        assert body["reading_id"] != got["reading_id"]
        with env.factory() as s:
            before = len(list(s.execute(select(Event).where(Event.action == READING_EVENT_ACTION))))
        refused = register_via_api(env, attempt_rule=ATTEMPT_RULE_RESERVED, max_reruns=1)
        assert refused.status_code == 422, refused.text
        err = envelope(refused)
        assert err["code"] == REFUSAL_INVALID
        assert err["detail"] == {"max_reruns": 1, "budget_profile": PROFILE_DEFAULT}
        with env.factory() as s:
            after = len(list(s.execute(select(Event).where(Event.action == READING_EVENT_ACTION))))
        assert after == before


def _w_served(rig: _WRig, home: Path) -> dict[str, dict[str, Any]]:
    """``GET /readings`` of the fixture repository over the rig's store, read by a viewer
    (the seed's users added on the first call), keyed by reading id."""
    from fastapi.testclient import TestClient

    from crb.server.app import API_PREFIX, create_app
    from crb.store.models import User
    from fixtures.server_seed import add_users, login, make_settings

    home.mkdir(exist_ok=True)
    with rig.h.factory() as s:
        seeded = s.execute(select(User.id).limit(1)).first() is not None
    if not seeded:
        add_users(rig.h.factory)
    with TestClient(create_app(make_settings(home), rig.h.factory)) as client:
        login(client, "viewer")
        got = client.get(f"{API_PREFIX}/readings?repo={pr.REPO_NAME}")
    assert got.status_code == 200, got.text
    return {o["reading_id"]: o for o in got.json()["readings"]}


def test_p792_get_readings_serves_the_attempt_rule_and_the_pins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``GET /readings`` serves a reserved.v1 reading's rule, its treatment pins and its
    reserved commits per arm (P-792): before any run, ``pinned_treatment`` is null and every
    arm has reserved none; after the first run the deployment half and its arm are pinned
    by that run's reservation — the body, the digest and the event, exactly as the
    reservation stored them — and a second arm's first run pins its own arm half while the
    deployment half stays the campaign's first."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    before = _w_served(rig, tmp_path / "api")[reading.reading_id]
    assert before["attempt_rule"] == ATTEMPT_RULE_RESERVED and "p792" not in before
    assert before["pinned_treatment"] is None
    assert before["reserved"] == {"S3": 0, "A0": 0}

    rig.enqueue(reading)
    rig.h.run_one()
    (a0,) = rig.reservations(reading)
    p = dict(a0.payload_json or {})

    def pin(half: str, ev: Event) -> dict[str, Any]:
        body = dict(ev.payload_json or {})
        return {
            "body": body["treatment_body"][half],
            "digest": body[f"{half}_fp"],
            "event_id": ev.event_id,
        }

    after = _w_served(rig, tmp_path / "api")[reading.reading_id]
    assert after["pinned_treatment"] == {
        "deployment": pin("deployment", a0),
        "arms": {"A0": pin("arm", a0)},
    }
    assert after["pinned_treatment"]["deployment"]["digest"] == p["deployment_fp"]
    assert after["reserved"] == {"S3": 0, "A0": 1}

    rig.enqueue(reading, kind="replay")
    rig.h.run_one()
    _, s3 = rig.reservations(reading)
    assert s3.step_id == "S3"
    later = _w_served(rig, tmp_path / "api")[reading.reading_id]
    assert later["pinned_treatment"] == {
        "deployment": pin("deployment", a0),
        "arms": {"A0": pin("arm", a0), "S3": pin("arm", s3)},
    }
    assert later["reserved"] == {"S3": 1, "A0": 1}


def test_p792_a_legacy_reading_is_served_open_on_this_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A legacy reading (registered under no attempt rule) is served under the rule's name,
    ``first_observed.v0``, with ``p792: "open on this rule"`` — the channels P-792 closes for
    a reserved.v1 reading stay open on it — and with no pins and no reserved counts, before
    and after a run (which reserves nothing). Its id never moves."""
    rig = _w_rig(tmp_path, monkeypatch)
    legacy = rig.register(legacy=True)
    reserved = rig.register()
    for when in ("before", "after"):
        served = _w_served(rig, tmp_path / "api")
        got = served[legacy.reading_id]
        assert (got["attempt_rule"], got["p792"]) == (ATTEMPT_RULE_LEGACY, "open on this rule")
        assert got["pinned_treatment"] is None and got["reserved"] is None, when
        assert served[reserved.reading_id]["attempt_rule"] == ATTEMPT_RULE_RESERVED
        assert "p792" not in served[reserved.reading_id]
        if when == "before":
            rig.enqueue(legacy)
            rig.h.run_one()
    assert rig.reservations(legacy) == []


def test_p792_settled_unrowed_is_served_per_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: Backend
) -> None:
    """``GET /readings`` serves ``settled_unrowed`` per arm of a reserved.v1 reading: its
    reservations among the campaign's unplaced attempts (F8) — the same count the tally
    charges, never a second one. The grade that raised after ``build.done`` (a lost sandbox)
    is the worker's own path: its run failed with no row, its reservation is settled, and the
    attempt is charged at the cost the worker's ``build.done`` wrote. A reservation with its
    row counts nothing; a legacy reading serves null."""
    rig = _w_rig(tmp_path, monkeypatch, backend)
    legacy = rig.register(legacy=True)
    reading = rig.register()
    served = _w_served(rig, tmp_path / "api")
    assert served[reading.reading_id]["settled_unrowed"] == {"S3": 0, "A0": 0}
    assert served[legacy.reading_id]["settled_unrowed"] is None

    monkeypatch.setattr(FakeBuilder, "hook", lambda ws, brief: rig.state.update(exec="lost"))
    lost = rig.enqueue(reading)
    assert rig.h.run_one().status == STATUS_FAILED
    assert "build.done" in rig.actions(lost.id) and rig.rows(lost.id) == []
    (a0,) = rig.reservations(reading)
    want = campaigns_mod.UnplacedAttempt(
        run_id=lost.id,
        task_id=rig.first,
        trial="r1",
        # the rung label the worker resolved trial r1 to, as its build.done names it
        rung=f"{_W_CELL['builder']}:{_W_CELL['model']}",
        cost_usd=0.01,
        reservation_event_id=a0.event_id,
        reading_id=reading.reading_id,
    )
    with rig.h.factory() as s:
        assert campaigns_mod.unplaced_attempts(s, [lost.id]) == [want]

    monkeypatch.setattr(FakeBuilder, "hook", None)
    rig.state["exec"] = ""
    rowed = rig.enqueue(reading, kind="replay")
    rig.h.run_one()
    assert len(rig.rows(rowed.id)) == 1
    with rig.h.factory() as s:
        assert campaigns_mod.unplaced_attempts(s, [lost.id, rowed.id]) == [want]
    served = _w_served(rig, tmp_path / "api")
    after = served[reading.reading_id]
    assert after["reserved"] == {"S3": 1, "A0": 1}
    assert after["settled_unrowed"] == {"S3": 0, "A0": 1}
    assert served[legacy.reading_id]["settled_unrowed"] is None


# --- the submit gate (POST /runs): 422 reading_run_fields and 409 reading_required --------


@contextlib.contextmanager
def _r_stack(
    backend: Backend,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    legacy: Sequence[tuple[str, str]] = (),
) -> Iterator[Wave3]:
    """The Wave 3 rehearsal's stack after step 4 on ``backend``'s store: sealed (sandbox and
    builder on docker), the record's test author, the builders' credential checks stubbed
    present (no key is set or read), the campaign registered, then its four readings — each
    opted in to reserved.v1 (``attempt_rule``) unless its ``(repo, size)`` is in ``legacy``."""
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)
    for name in ("claude_code", "editblock"):
        monkeypatch.setitem(runs_routes.CREDENTIAL_CHECKS, name, lambda *_a, **_k: "")
    init_db(backend.engine)
    info = seed(backend.factory)
    add_users(backend.factory)
    settings = make_settings(tmp_path, **SEALED_SETTINGS, factory={"test_author": TEST_AUTHOR})
    with TestClient(create_app(settings, backend.factory)) as client:
        env = Env(client=client, factory=backend.factory, info=info, settings=settings)
        add_repos_and_tasks(env)
        login(client, "operator")
        w = Wave3(env=env)
        r = w.send("POST", "/api/v1/campaigns", json=campaign_body())
        assert r.status_code == 201, r.text
        w.campaign = r.json()
        author = deployment_author_model(settings)
        for key, body in registration_bodies(w.cid, author).items():
            rule = {} if key in legacy else {"attempt_rule": ATTEMPT_RULE_RESERVED}
            r = w.send("POST", "/api/v1/readings", json={**body, **rule})
            assert r.status_code == 201, (key, r.text)
            w.readings[key] = r.json()
            assert w.readings[key].get("attempt_rule", "") == rule.get("attempt_rule", ""), key
        yield w


def _r_admitted(w: Wave3) -> int:
    """How many runs the campaign admitted (its ``campaign.admitted`` events)."""
    with w.env.factory() as s:
        return len(
            s.execute(
                select(Event.id).where(Event.action == CAMPAIGN_ADMITTED, Event.trace_id == w.cid)
            ).all()
        )


def _r_admit(w: Wave3, body: Mapping[str, Any]) -> Run:
    """``POST /runs`` ``body`` answers 201, the campaign admits it, and the run is then
    settled (``cancelled``, as an operator's cancel before its claim leaves it) so it holds
    none of the line; the stored run is returned."""
    before = _r_admitted(w)
    r = w.send("POST", "/api/v1/runs", json=dict(body))
    assert r.status_code == 201, r.text
    assert _r_admitted(w) == before + (1 if body.get("campaign_id") else 0)
    with w.env.factory() as s:
        run = s.get(Run, str(r.json()["id"]))
        assert run is not None
        run.status = STATUS_CANCELLED
        s.commit()
        s.refresh(run)
        s.expunge(run)
    return run


def _r_refused(w: Wave3, body: Mapping[str, Any], status: int, code: str) -> dict[str, Any]:
    """``POST /runs`` ``body`` is refused ``status`` ``code`` with nothing queued and
    nothing admitted; the error envelope is returned."""
    before, admitted = _runs(w.env), _r_admitted(w)
    err = _refused(w.send("POST", "/api/v1/runs", json=dict(body)), status, code)
    assert _runs(w.env) == before and _r_admitted(w) == admitted
    return err


def _r_fields(w: Wave3, body: Mapping[str, Any], fields: list[str]) -> dict[str, Any]:
    """``body`` is refused 422 ``reading_run_fields`` naming exactly ``fields`` (with a
    reason each), nothing queued; the error's ``detail`` is returned."""
    err = _r_refused(w, body, 422, REFUSAL_RUN_FIELDS)
    detail = dict(err["detail"])
    assert detail["fields"] == fields, detail
    assert detail["reading_id"] == body["reading_id"]
    assert set(detail["reasons"]) == set(fields) and all(detail["reasons"].values())
    assert "nothing was queued" in err["message"]
    return detail


def test_p792_c7_budget_profile_mismatch_refused(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C7 and C17 at submit, reproducing the probe ``test_in_scope_reads_no_run_parameter``
    (the reading's scope reads no run parameter, so a run's own profile was counted as the
    reading's): a non-loop arm spending on a budget profile other than the reading's
    (``calibrated`` against ``default``), a non-loop arm without ``learning: off``, and the
    ``+L`` arm naming a budget profile are each refused 422 ``reading_run_fields`` naming
    what moved, nothing queued (201 before the route's check). ``learning: on`` is the
    schema's 422 (green before: the loop is opted out, never in). The step-6 ``A0`` and
    ``A0+L`` bodies are admitted."""
    with _r_stack(backend, tmp_path, monkeypatch) as w:
        key = ("cobra", "XS")
        a0 = _a0(w, key)
        a0l = a0l_body(a0)
        s3 = _s3_body(w, key)
        assert a0["budget_profile"] == w.readings[key]["budget_profile"] == PROFILE_DEFAULT
        cases: list[tuple[dict[str, Any], list[str], str]] = [
            ({**a0, "budget_profile": PROFILE_CALIBRATED}, ["budget_profile"], "A0"),
            ({k: v for k, v in a0.items() if k != "learning"}, ["learning"], "A0"),
            ({**a0l, "budget_profile": PROFILE_CALIBRATED}, ["budget_profile", "learning"], "A0"),
            ({**s3, "budget_profile": PROFILE_CALIBRATED}, ["budget_profile"], "S3"),
        ]
        for body, fields, arm in cases:
            assert _r_fields(w, body, fields)["arm"] == arm, fields
        err = _r_refused(w, {**a0, "learning": "on"}, 422, "validation_error")
        assert "learning" in json.dumps(err)
        assert _r_admit(w, a0).params_json["learning"] == "off"
        assert "learning" not in _r_admit(w, a0l).params_json


#: Every ``RunCreateRequest`` field, as a run filed under a reserved.v1 reading may set it
#: (C17). ``free``: admitted with the value beside it (``{}``: the step-6 ``A0`` body sets
#: it already). ``default``: admitted at its default (the first body), refused naming it
#: otherwise (the second). ``refused``: refused naming it, whatever it is set to.
#: ``factory``: refused 422 ``validation_error`` before the gate (factory runs only). A new
#: field fails :func:`test_p792_run_fields_ratchet` until it is classified here.
_R_FREE: dict[str, dict[str, Any]] = {
    "repo": {},
    "kind": {},
    "builder": {},
    "model": {},
    "provider": {},
    "task_ids": {},
    "max_cost_usd": {},
    "budget_profile": {},
    "learning": {},
    "reading_id": {},
    "campaign_id": {},
    "mode": {"mode": "blind"},
    "limit": {"limit": 16},
    "arm": {"arm": "S1"},
    "test_author": {"arm": "S1", "test_author": TEST_AUTHOR},
    "outage_stop": {"outage_stop": 3},
    "env_stop": {"env_stop": 3},
    "qualify_first": {"qualify_first": True},
}
_R_DEFAULT: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "pool": ({"pool": ""}, {"pool": "hard"}),
    "executor": ({"executor": ""}, {"executor": "docker"}),
    "timeout": ({"timeout": None}, {"timeout": 1}),
    "ladder": ({"ladder": ["r1"]}, {"ladder": ["claude_code:claude-sonnet-5"]}),
}
_R_REFUSED: dict[str, Any] = {
    "budget": {"max_turns": 3},
    "builder_config": {"extra_args": ["--model", "x"]},
    "retain": {"worktrees": True},
    "preflight": True,
    "escalation": ESCALATION_ALWAYS,
    "checks": {"finish_gate": False},
    "taxonomy": GLOBAL_CLASS_SET,
}
_R_FACTORY: dict[str, Any] = {
    "backlog_hash": "0" * 64,
    "deliver": True,
    "deliver_override": True,
    "max_rework": 1,
}
#: The fields a run stores as columns, not under ``params``.
_R_COLUMNS = frozenset({"repo", "kind", "mode", "builder", "model", "provider", "ladder"})


def test_p792_run_fields_ratchet(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C17, the ratchet: every ``RunCreateRequest`` field is classified (``_R_FREE``,
    ``_R_DEFAULT``, ``_R_REFUSED``, ``_R_FACTORY``), so a field added to the request fails
    here until it is; the ``params`` keys the admitted classes store are exactly the core's
    :data:`RESERVED_RUN_PARAMS`, and no refused field's is one. Each class behaves as named
    on ``POST /runs`` filed under a reserved.v1 reading: a free field admitted, a default
    field admitted at its default and refused 422 ``reading_run_fields`` naming it
    otherwise, a refused field refused naming it, a factory field 422 ``validation_error`` —
    each refusal with nothing queued."""
    classes = [set(_R_FREE), set(_R_DEFAULT), set(_R_REFUSED), set(_R_FACTORY)]
    assert sum(len(c) for c in classes) == len(set().union(*classes))  # disjoint
    assert set(RunCreateRequest.model_fields) == set().union(*classes)
    assert (set(_R_FREE) | set(_R_DEFAULT)) - _R_COLUMNS == RESERVED_RUN_PARAMS
    assert RESERVED_RUN_PARAMS.isdisjoint(_R_REFUSED) and RESERVED_RUN_PARAMS.isdisjoint(_R_FACTORY)
    with _r_stack(backend, tmp_path, monkeypatch) as w:
        a0 = _a0(w, ("cobra", "XS"))
        for name, over in _R_FREE.items():
            assert over or name in a0, name
            run = _r_admit(w, {**a0, **over})
            stored = dict(run.params_json or {})
            assert name in _R_COLUMNS or name in stored, (name, stored)
        for name, (default, other) in _R_DEFAULT.items():
            run = _r_admit(w, {**a0, **default})
            assert run.ladder_json == list(RESERVED_RUN_LADDER), name
            _r_fields(w, {**a0, **other}, [name])
        for name, value in _R_REFUSED.items():
            _r_fields(w, {**a0, name: value}, [name])
        for name, value in _R_FACTORY.items():
            err = _r_refused(w, {**a0, name: value}, 422, "validation_error")
            assert name in err["message"], (name, err)


def test_p792_empty_ladder_default_is_what_new_run_stores() -> None:
    """The one ladder a reserved.v1 reading's run climbs (:data:`RESERVED_RUN_LADDER`) is
    what ``new_run`` stores for a body naming none, and ``pool``, ``executor`` and
    ``timeout`` are stored at the defaults the whitelist keeps — so a step-6 body, which
    names none of them, is the run the whitelist admits. A pin: green before the route's
    check, it fails if either side's default moves without the other."""
    for kind in ("replay", "blind"):
        body = RunCreateRequest(
            repo="cobra",
            kind=kind,
            builder="claude_code",
            model="claude-sonnet-5",
            provider="anthropic",
            task_ids=[],
        )
        run = runs_routes.new_run(body, actor="u")
        assert run.ladder_json == list(RESERVED_RUN_LADDER) == ["r1"], kind
        params = dict(run.params_json or {})
        assert {k: params[k] for k in ("pool", "executor", "timeout")} == {
            "pool": "",
            "executor": "",
            "timeout": 0,
        }
        assert set(params) <= RESERVED_RUN_PARAMS, params


def test_p792_reading_required_for_campaign_runs(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C19: a run filed under a campaign that holds a reserved.v1 reading on its repository
    names its reading — without ``reading_id`` it is refused 409 ``reading_required``
    (``detail: {campaign_id, reading_ids}``) with nothing queued and nothing admitted (201
    and admitted before the route's check), since it would spend the campaign's line while
    no reading's gate (``reading_run_fields``, sealed, posture) checked it. A repository
    whose readings in the campaign are all legacy is admitted as before; a run under no
    campaign, or under another campaign holding no reading, is unaffected."""
    legacy = (("click", "XS"), ("click", "S"))
    with _r_stack(backend, tmp_path, monkeypatch, legacy=legacy) as w:
        cobra = {k: v for k, v in _a0(w, ("cobra", "XS")).items() if k != "reading_id"}
        err = _r_refused(w, cobra, 409, REFUSAL_READING_REQUIRED)
        held = sorted(w.readings[("cobra", s)]["reading_id"] for s in ("XS", "S"))
        assert err["detail"] == {"campaign_id": w.cid, "reading_ids": held}
        assert "nothing was queued" in err["message"]
        click = {k: v for k, v in _a0(w, ("click", "XS")).items() if k != "reading_id"}
        _r_admit(w, click)
        outside = {k: v for k, v in cobra.items() if k != "campaign_id"}
        admitted = _r_admitted(w)
        _r_admit(w, outside)
        assert _r_admitted(w) == admitted
        r = w.send("POST", "/api/v1/campaigns", json={**campaign_body(), "name": "p792-other"})
        assert r.status_code == 201, r.text
        other = str(r.json()["campaign_id"])
        assert other != w.cid
        r = w.send("POST", "/api/v1/runs", json={**cobra, "campaign_id": other})
        assert r.status_code == 201, r.text


def test_p792_remeasure_bodies_are_admitted(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec risk 6, the whitelist against the real step-6 bodies on an opt-in reserved.v1
    reading: the ``GET /learn/remeasure`` plan's own request plus the three filing fields
    and the profile (``S3``), and the record's ``A0`` and ``A0+L`` bodies, are each
    admitted 201 and stored as the record words them; a body asking to ``retain`` its
    worktrees is refused 422 ``reading_run_fields`` (on purpose: allowing it would be a
    registration amendment)."""
    with _r_stack(backend, tmp_path, monkeypatch) as w:
        key = ("cobra", "XS")
        a0 = _a0(w, key)
        runs = [_r_admit(w, b) for b in (_s3_body(w, key), a0, a0l_body(a0))]
        assert [r.kind for r in runs] == ["replay", "blind", "blind"]
        assert [dict(r.params_json or {}).get("learning") for r in runs] == ["off", "off", None]
        assert all(r.ladder_json == list(RESERVED_RUN_LADDER) for r in runs)
        _r_fields(w, {**a0, "retain": {"worktrees": True}}, ["retain"])


def test_p792_admission_rechecks_both_refusals_under_the_lock(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``admit_under_campaign`` re-runs the submit gate under the events write lock, so both
    new refusals hold there too: when the readings read before the lock are still legacy
    and the ones read under it are reserved.v1 (an opt-in landing between the two reads),
    a run setting ``timeout`` is refused 422 ``reading_run_fields`` and a run without
    ``reading_id`` 409 ``reading_required`` — each with nothing queued and nothing admitted
    (both 201 before the route's checks)."""
    real = runs_routes.load_readings
    calls: list[str] = []

    def first_read_legacy(db: Any, repo: str) -> list[Reading]:
        got = list(real(db, repo))
        calls.append(repo)
        if len(calls) == 1:
            return [dataclasses.replace(r, attempt_rule="") for r in got]
        return got

    with _r_stack(backend, tmp_path, monkeypatch) as w:
        a0 = _a0(w, ("cobra", "XS"))
        monkeypatch.setattr(runs_routes, "load_readings", first_read_legacy)
        _r_fields(w, {**a0, "timeout": 1}, ["timeout"])
        assert len(calls) == 2
        calls.clear()
        no_reading = {k: v for k, v in a0.items() if k != "reading_id"}
        _r_refused(w, no_reading, 409, REFUSAL_READING_REQUIRED)
        assert len(calls) == 2


# --- an operator's lint switch never reshapes what a reading counts (P-796) ------------------


def _r_lint(w: Wave3, repo: str, lint: dict[str, Any]) -> None:
    """Store ``lint`` as ``repo``'s ``RepoConfig.lint`` (the operator's config edit)."""
    with w.env.factory() as s:
        row = s.get(Repo, repo)
        assert row is not None
        row.config_json = {**dict(row.config_json or {}), "lint": dict(lint)}
        s.commit()


def test_p792_a_run_of_a_reading_on_a_lint_disabled_repo_is_refused(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-796 (the Wave 3 red team's F7, by code reading): a row graded with belt 5 switched
    off lets its commit leave a legacy reading ``lint_disabled`` and is a reserved.v1
    reading's miss, and the switch is the operator's to throw after outcomes are seen. Now a
    run filed under a reading of either rule on a repository whose lint is disabled is
    refused 409 ``lint_disabled`` at submit, nothing queued or admitted (201 before), and a
    run that reached the queue past the gate is refused at claim — ``run.refused``
    ``lint_disabled``, failed before any build, nothing reserved, every commit still pending
    (built and reserved before)."""
    off = {"disabled": True}
    (tmp_path / "submit").mkdir()
    with _r_stack(backend, tmp_path / "submit", monkeypatch, legacy=[("click", "XS")]) as w:
        for key in (("cobra", "XS"), ("click", "XS")):
            body = _a0(w, key)
            _r_lint(w, key[0], off)
            err = _r_refused(w, body, 409, "lint_disabled")
            assert err["detail"] == {
                "reading_id": body["reading_id"],
                "repo": key[0],
                "reason": LINT_DISABLED_BY_CONFIG,
            }, key
            _r_lint(w, key[0], {})
            assert _r_admit(w, body).status == STATUS_CANCELLED

    (tmp_path / "claim").mkdir()
    rig = _w_rig(tmp_path / "claim", monkeypatch)
    for reading in (rig.register(), rig.register(legacy=True)):
        rig.edit_config(lint=off)
        run = rig.enqueue(reading)
        done = rig.h.run_one()
        assert done.status == STATUS_FAILED and done.error.startswith("lint_disabled"), done.error
        (refused,) = rig.payloads(run.id, "run.refused")
        assert (refused["code"], refused["reading_id"]) == ("lint_disabled", reading.reading_id)
        assert (refused["repo"], refused["reason"]) == (pr.REPO_NAME, LINT_DISABLED_BY_CONFIG)
        assert "build.start" not in rig.actions(run.id)
        assert rig.rows(run.id) == [] and rig.reservations(reading) == []
        assert rig.verdicts(reading, "A0")[rig.first][0] is None
        rig.edit_config(lint={})


def test_p792_toggling_lint_after_the_first_reservation_halts_the_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-796 against the treatment pin: once a reserved.v1 reading's first reservation has
    pinned the repository's configuration, switching belt 5 off refuses the next run at
    claim (``lint_disabled``, before any reservation — it halted on the pin before the claim
    check), and switching it back on under another lint block (``{"disabled": false}`` is
    not the ``{}`` pinned) halts the next ``reading_treatment_mismatch`` on the repository
    digest, before ``build.start``. The second commit stays pending throughout, and the
    first keeps the verdict its reservation gave it."""
    rig = _w_rig(tmp_path, monkeypatch)
    reading = rig.register()
    rig.enqueue(reading)
    rig.h.run_one()
    (res,) = rig.reservations(reading)
    assert rig.verdicts(reading, "A0")[rig.first] == (True, "")

    rig.state["b"] = "multiply"
    rig.edit_config(lint={"disabled": True})
    off = rig.enqueue(reading, rig.second)
    done = rig.h.run_one()
    assert done.status == STATUS_FAILED and done.error.startswith("lint_disabled"), done.error
    (refused,) = rig.payloads(off.id, "run.refused")
    assert refused["code"] == "lint_disabled"
    assert rig.payloads(off.id, "run.halted") == []
    assert "build.start" not in rig.actions(off.id)

    rig.edit_config(lint={"disabled": False})
    on = rig.enqueue(reading, rig.second)
    done = rig.h.run_one()
    assert done.error == HALT_TREATMENT_MISMATCH
    (halted,) = rig.payloads(on.id, "run.halted")
    assert halted["detail"]["fields"] == ["repo_config"]
    assert "build.start" not in rig.actions(on.id)
    assert [e.event_id for e in rig.reservations(reading)] == [res.event_id]
    assert rig.verdicts(reading, "A0") == {rig.first: (True, ""), rig.second: (None, "pending")}


# --- the factory: a reserved.v1 forward reading reserves each ticket's first build (C8, C16) --

#: The factory rung a forward reading's cell names: the fake builder's ``multiply`` build of
#: the one-item backlog (``test_worker._multiply_backlog``), on ``fake:m0@p``.
_F_RUNG = {"builder": "fake", "model": "m0", "provider": "p"}


@dataclasses.dataclass
class _FRig:
    """One worker over the fixture repository on a sealed deployment, with the one-item
    ``bug.fix × XS`` backlog (``I-1`` and its operator-authored oracle) frozen and every cell
    a ceiling, so a calibration grant builds the item and grades its first attempt on the
    held-out tests a second person wrote (``test_worker_held_out``)."""

    h: Harness
    home: Any
    backlog: Any
    posture: str
    feat: str

    def register(self, *, reserved: bool = True) -> Reading:
        """Register a ceiling (a legacy replay reading of the fixture commit, ten minutes
        ago) and its forward reading on :data:`_F_RUNG` (five minutes ago; reserved.v1
        unless ``reserved`` is false), and store both ``reading.registered`` events."""
        now = datetime.now(UTC)
        base = register(
            repo=pr.REPO_NAME,
            cell=_W_CELL,
            hierarchy=("S3",),
            pool=[self.feat],
            apparatus=worker.APPARATUS_VERSION,
            taxonomy=GLOBAL_CLASS_SET,
            posture_class=self.posture,
            checks_arm="off",
            actor="op-1",
            hypothesis=HYPOTHESIS,
            smallest_effect=SMALLEST_EFFECT,
            now=(now - timedelta(minutes=10)).isoformat(timespec="seconds"),
        )
        from crb.core.reading import ReadingOutcome

        ceiling = ReadingOutcome(
            reading=base, arms={}, chain=("S3",), stopped_at="", standard="", state=OUTCOME_CEILING
        )
        opt_in = {"attempt_rule": ATTEMPT_RULE_RESERVED, "budget_profile": PROFILE_DEFAULT}
        fwd = register_forward(
            ceiling=ceiling,
            **_F_RUNG,
            actor="op-1",
            existing=[base],
            hypothesis=HYPOTHESIS,
            smallest_effect=SMALLEST_EFFECT,
            now=(now - timedelta(minutes=5)).isoformat(timespec="seconds"),
            **(opt_in if reserved else {}),
        )
        for r in (base, fwd):
            append_event(
                self.h.factory,
                trace_id=f"readings:{pr.REPO_NAME}",
                stage="system",
                action=READING_EVENT_ACTION,
                repo=pr.REPO_NAME,
                payload=r.to_dict(),
            )
        return fwd

    def enrol(self, *, written_at: str = "") -> HeldOutTests:
        """Grant ``I-1`` a calibration build and store its held-out tests, written now (after
        the registration, so the ticket is enrolled) unless ``written_at`` says otherwise."""
        from crb.server.acceptance import write_held_out
        from test_worker_held_out import HELD_OUT

        grant = self.home.evidence(actor="approver:ada").record_calibration(
            "I-1", approver="approver:ada", reason="the forward reading"
        )
        record = HeldOutTests(
            repo=pr.REPO_NAME,
            item_id="I-1",
            grant=grant.event_id,
            files=(("tests/test_multiply_held_out.py", HELD_OUT),),
            author="operator:bea",
            written_at=written_at or datetime.now(UTC).isoformat(timespec="seconds"),
            capability_class="bug.fix",
            size="XS",
            language="python",
        )
        write_held_out(self.h.factory, record)
        return record

    def enqueue(
        self, reading: Reading | None, *, params: dict[str, Any] | None = None, **fields: Any
    ) -> Run:
        """Enqueue a factory run filed under ``reading`` (none when ``None``), stored as
        ``POST /runs`` stores one: the cell's rung on the ladder ``["r1"]``, sighted, the
        backlog's frozen hash and evolutions chain pinned; ``params`` and ``fields`` laid
        over it."""
        stored: dict[str, Any] = {
            "task_ids": [],
            "limit": None,
            "pool": "",
            "executor": "",
            "timeout": 0,
            "backlog_hash": self.backlog.backlog_hash,
            "evolutions_hash": self.backlog.evolutions_hash,
        }
        if reading is not None:
            stored["reading_id"] = reading.reading_id
        base = {**_F_RUNG, "mode": "sighted", "ladder_json": list(RESERVED_RUN_LADDER)}
        return self.h.enqueue(
            "factory", params_json={**stored, **(params or {})}, **{**base, **fields}
        )

    def reservations(self, reading: Reading) -> list[Event]:
        """The reading's ``reading.reserved`` events, in ``Event.id`` order."""
        with self.h.factory() as s:
            return list(
                s.execute(
                    select(Event)
                    .where(
                        Event.action == READING_RESERVED_ACTION,
                        Event.trace_id == reading.reading_id,
                    )
                    .order_by(Event.id)
                ).scalars()
            )

    def verdicts(self, reading: Reading) -> dict[str, tuple[bool | None, str]]:
        """Each enrolled ticket of the ``S2`` arm as the server reads it: the reading as
        ``load_readings`` fills it (its pool enrolled), over every row in the ledger."""
        with self.h.factory() as s:
            loaded = next(
                r for r in load_readings(s, pr.REPO_NAME) if r.reading_id == reading.reading_id
            )
        rows = list(self.h.worker.ledger.rows())
        return {c.commit: (c.outcome, c.reason) for c in arm_reading(loaded, "S2", rows).commits}

    def events(self, run_id: str, action: str) -> list[Any]:
        return [e for e in self.h.events(run_id) if e.action == action]

    def actions(self, run_id: str) -> list[str]:
        return [e.action for e in self.h.events(run_id)]

    def rows(self, run_id: str) -> list[GradeRow]:
        return list(self.h.worker.ledger.rows(run_id=run_id))

    def event_ids(self, run_id: str) -> dict[str, list[int]]:
        """``Event.id`` of each of a run's events, by action."""
        out: dict[str, list[int]] = {}
        with self.h.factory() as s:
            for ev in s.execute(select(Event).where(Event.trace_id == run_id)).scalars():
                out.setdefault(ev.action, []).append(int(ev.id))
        return out


def _f_rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store: Backend | None = None) -> _FRig:
    """The factory rig on SQLite, or on ``store``'s database when one is given."""
    from test_worker import _multiply_backlog
    from test_worker_held_out import _every_cell_a_ceiling

    pyrepo = pr.build(tmp_path / "pyrepo")
    h = Harness(tmp_path, pyrepo)
    if store is not None:
        h.url = store.url
        h.settings = dataclasses.replace(h.settings, database_url=store.url)
        h.worker = worker.Worker(h.settings, engine=store.engine)
        h.factory = h.worker.factory
        h.queue = JobQueue(h.factory)
    h.add_repo()
    h.add_task(pyrepo.feat_task())
    # _multiply_backlog sets the registry's fake builder; the monkeypatch restores it
    monkeypatch.setitem(builders_pkg._REGISTRY, "fake", FakeBuilder)
    w = h.worker
    # a sealed worker: both executors docker (P-789), the sandbox a local one on the cancel token
    monkeypatch.setattr(
        w, "settings", dataclasses.replace(w.settings, executor="docker", builder_executor="docker")
    )
    monkeypatch.setattr(
        w, "_executor", lambda ctx: _WExec({"exec": ""}, cancel=lambda: w._cancelled(ctx))
    )
    monkeypatch.setenv("CRB_BUILDER__IMAGE", "crb-builder:test")
    monkeypatch.delenv("CRB_BUILDER__EXECUTOR", raising=False)
    posture = w._deployment_posture_class(pr.REPO_NAME, "docker")
    _every_cell_a_ceiling(monkeypatch)
    home, _item, backlog = _multiply_backlog(h)
    return _FRig(h, home, backlog, posture, pyrepo.feat_sha)


def _f_forward(*, reserved: bool = True) -> Reading:
    """A forward reading in memory (the goldens' ceiling, :func:`_g_forward`), reserved.v1
    unless ``reserved`` is false."""
    pool = commits(20, prefix="f")
    ceiling_reading = register_reading(pool, hierarchy=("S3", S1), budget=0.05)
    ceiling = evaluate(
        ceiling_reading,
        rows_for([True] * 20, pool, arm="S3") + rows_for([True] * 17 + [False] * 3, pool, arm=S1),
    )
    opt_in = {"attempt_rule": ATTEMPT_RULE_RESERVED, "budget_profile": PROFILE_DEFAULT}
    return register_forward(
        ceiling=ceiling,
        builder="claude_code",
        model="claude-sonnet-5",
        provider="anthropic",
        actor="op-1",
        existing=[ceiling_reading],
        now=_G_FWD_AT,
        budget=0.05,
        **(opt_in if reserved else {}),
    )


def test_p792_c8_forward_offcell_run_cannot_reserve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C8: a factory run filed under a reserved.v1 forward reading reserves the ticket's
    first build, so the whitelist binds it as it binds a replay run's — a run built on
    another model than the reading's cell is refused 422 ``reading_run_fields`` naming
    ``model`` at ``POST /runs`` (nothing queued; 422 ``validation_error`` before, a factory
    run could name no reading), the on-cell run passes every reading gate (409
    ``no_frozen_backlog``, the next one), and a factory run naming a legacy reading is still
    a validation error. At claim the same off-cell run, inserted past the route, is refused
    ``reading_run_fields`` naming ``model`` alone — nothing built, nothing reserved (before,
    the claim named ``kind`` and the factory's own params too). The legacy forward rule is
    pinned unchanged: a ticket's first factory attempt is any rung-``r1`` factory row on
    the repository graded after registration and never imported."""
    from crb.core.ledger import LABEL_IMPORTED
    from crb.core.reading import _forward_attempt
    from fixtures.proven import add_oracle_and_controls, add_rows, add_tasks, register_via_api
    from fixtures.server_seed import ALPHA, BUILDER, MODEL, PROVIDER, envelope, make_env

    # the legacy forward rule, pinned: nine first attempts, and each way a row is not one
    legacy, rows = _g_forward()
    assert [_forward_attempt(legacy, r) for r in rows] == [True] * 9
    first = rows[0]
    for change in (
        {"trial": "r2"},
        {"labels": {**first.labels, LABEL_IMPORTED: "true"}},
        {"repo": "other/repo"},
        {"created": "2026-09-27T11:00:00+00:00"},
    ):
        assert not _forward_attempt(legacy, GradeRow(**{**first.fields(), **change})), change

    # the submit gate
    monkeypatch.setitem(runs_routes.CREDENTIAL_CHECKS, "editblock", lambda *_a, **_k: "")
    with make_env(tmp_path / "submit", **SEALED_SETTINGS) as env:
        add_tasks(env.factory)
        r = register_via_api(env)
        assert r.status_code == 201, r.text
        ceiling = r.json()
        pool = ceiling["pool"][:20]
        add_rows(env.factory, pool, arm="S3")
        add_rows(env.factory, pool[:3], arm=S1, clean=False)
        add_rows(env.factory, pool[3:], arm=S1)
        add_oracle_and_controls(env.factory, pool)
        fwd = env.post(
            "/readings/forward",
            json={
                "repo": ALPHA,
                "promotes": ceiling["reading_id"],
                "builder": BUILDER,
                "model": MODEL,
                "provider": PROVIDER,
                "hypothesis": HYPOTHESIS,
                "smallest_effect": SMALLEST_EFFECT,
                "attempt_rule": ATTEMPT_RULE_RESERVED,
            },
        )
        assert fwd.status_code == 201, fwd.text
        body = {
            "repo": ALPHA,
            "kind": "factory",
            "builder": BUILDER,
            "model": MODEL,
            "provider": PROVIDER,
            "reading_id": fwd.json()["reading_id"],
        }
        with env.factory() as s:
            queued = len(list(s.execute(select(Run.id)).scalars()))
        off = env.post("/runs", json={**body, "model": "gpt-oss-20b"})
        assert off.status_code == 422, off.text
        err = envelope(off)
        assert err["code"] == REFUSAL_RUN_FIELDS, err
        assert err["detail"]["fields"] == ["model"], err
        on = env.post("/runs", json=body)
        assert on.status_code == 409, on.text
        assert envelope(on)["code"] == "no_frozen_backlog"
        named = env.post("/runs", json={**body, "reading_id": ceiling["reading_id"]})
        assert named.status_code == 422, named.text
        err = envelope(named)
        assert err["code"] == "validation_error"
        assert "replay and blind runs only" in json.dumps(err), err
        with env.factory() as s:
            assert len(list(s.execute(select(Run.id)).scalars())) == queued

    # the claim
    rig = _f_rig(tmp_path / "claim", monkeypatch)
    reading = rig.register()
    rig.enrol()
    run = rig.enqueue(reading, model="m1")
    done = rig.h.run_one()
    assert done.status == STATUS_FAILED, (done.status, done.error)
    assert done.error.startswith(REFUSAL_RUN_FIELDS), done.error
    (refused,) = [dict(e.payload or {}) for e in rig.events(run.id, "run.refused")]
    assert (refused["code"], refused["fields"]) == (REFUSAL_RUN_FIELDS, ["model"]), refused
    assert "build.start" not in rig.actions(run.id)
    assert rig.reservations(reading) == [] and rig.rows(run.id) == []
    assert rig.verdicts(reading) == {"I-1": (None, "pending")}


def test_p792_c16_factory_exception_after_reserve_is_a_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C16: a factory build that raises after its reservation — here the grader itself —
    writes no row, the loop records the item as an error and the run settles, and the
    reserved ticket reads a miss (``unobserved``), as a replay attempt's does (C15): fail
    closed, an instrument failure after the reservation is the reading's cost. Before, the
    run was refused at claim and never reserved."""
    rig = _f_rig(tmp_path, monkeypatch)
    reading = rig.register()
    rig.enrol()

    def broken(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("the grader fell over")

    monkeypatch.setattr("crb.factory.build.grade", broken)
    run = rig.enqueue(reading)
    done = rig.h.run_one()
    assert done.status == STATUS_SUCCEEDED, (done.status, done.error)
    (outcome,) = dict(done.counts_json or {})["outcomes"]
    assert outcome["status"] == "error", outcome
    (res,) = rig.reservations(reading)
    assert (res.task_id, dict(res.payload_json or {})["run_id"]) == ("I-1", run.id)
    assert rig.rows(run.id) == []
    assert rig.verdicts(reading) == {"I-1": (False, "unobserved")}


@pytest.mark.parametrize("how", ["store_error", "not_enrolled"])
def test_p792_factory_reserve_never_blocks_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    """The factory's reservation hook never blocks a build: a reservation that cannot be
    written (the events store raising) or that the reading refuses (a ticket it does not
    enrol — its held-out tests written before the registration) is a ``build.not_reserved``
    event naming the item, the trial and why, and the item is built and graded as it was
    before, its row carrying no reservation. The ticket the store failed for stays pending;
    the one the reading never enrolled is not in its pool."""
    from crb.core.reading import SKIP_TASK_NOT_ENROLLED

    rig = _f_rig(tmp_path, monkeypatch)
    reading = rig.register()
    if how == "store_error":
        rig.enrol()
        real = worker.append_event_checked

        def flaky(*a: Any, **kw: Any) -> Any:
            if kw.get("action") == READING_RESERVED_ACTION:
                raise RuntimeError("the events store went away")
            return real(*a, **kw)

        monkeypatch.setattr(worker, "append_event_checked", flaky)
    else:
        rig.enrol(written_at=(datetime.now(UTC) - timedelta(minutes=20)).isoformat())
    run = rig.enqueue(reading)
    done = rig.h.run_one()
    assert done.status == STATUS_SUCCEEDED, (done.status, done.error)
    (event,) = rig.events(run.id, "build.not_reserved")
    assert {k: dict(event.payload or {}).get(k) for k in ("item", "trial")} == {
        "item": "I-1",
        "trial": "r1",
    }
    assert "build.start" in rig.actions(run.id)
    rows = [r for r in rig.rows(run.id) if r.trial == "r1"]
    assert len(rows) == 1 and LABEL_RESERVATION not in rows[0].labels, rows
    assert rig.reservations(reading) == []
    if how == "store_error":
        assert "the events store went away" in event.error_message
        assert rig.verdicts(reading) == {"I-1": (None, "pending")}
    else:
        assert SKIP_TASK_NOT_ENROLLED in event.error_message
        assert rig.verdicts(reading) == {}


def test_p792_forward_reserved_counts_only_the_reserved_attempt(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A factory run filed under a reserved.v1 forward reading reserves the ticket's ``r1``
    build before it starts (one ``reading.reserved`` event: the ticket, the ``S2`` arm, the
    run, no campaign), its row is stamped with that reservation, the claim and the
    treatment, and the ticket is read by that row alone — a later unreserved copy of the
    row, failing its held-out tests, does not move it. On SQLite and PostgreSQL. Before, the
    run was refused at claim and nothing was reserved."""
    rig = _f_rig(tmp_path, monkeypatch, store=backend)
    reading = rig.register()
    record = rig.enrol()
    run = rig.enqueue(reading)
    done = rig.h.run_one()
    assert done.status == STATUS_SUCCEEDED, (done.status, done.error)
    (res,) = rig.reservations(reading)
    p = dict(res.payload_json or {})
    assert (res.task_id, res.step_id) == ("I-1", "S2")
    assert (p["run_id"], p["arm"], p["trial"], p["campaign_id"]) == (run.id, "S2", "r1", "")
    (row,) = [r for r in rig.rows(run.id) if r.trial == "r1"]
    assert row.labels[LABEL_RESERVATION] == res.event_id
    assert row.labels[LABEL_CLAIM] == "0"
    assert row.labels[LABEL_TREATMENT] == p["treatment"]
    assert int(res.id) < min(rig.event_ids(run.id)["build.start"])
    assert rig.verdicts(reading) == {"I-1": (True, "")}
    unreserved = {
        k: v
        for k, v in row.labels.items()
        if k not in (LABEL_RESERVATION, LABEL_TREATMENT, LABEL_CLAIM)
    }
    rig.h.worker.ledger.append(
        GradeRow(
            **{
                **row.fields(),
                "row_id": "",
                "labels": {**unreserved, **held_out_labels(record, RESULT_FAIL)},
            }
        )
    )
    assert rig.verdicts(reading) == {"I-1": (True, "")}


def test_p792_reserved_factory_params_ratchet() -> None:
    """The factory whitelist (:data:`RESERVED_FACTORY_PARAMS`) is the replay one without the
    replay-only keys (``budget_profile``, ``learning``, ``arm``, ``campaign_id`` — a
    forward reading names no campaign and reads ``S2`` alone) plus the factory's own
    (``backlog_hash``, ``evolutions_hash``, ``deliver``, ``max_rework``), and the core
    table: a sighted factory run of a reserved.v1 forward reading on its cell and the one
    ladder is admitted with every whitelisted key; anything else is refused naming it; a
    replay or blind run of a forward reading, and a factory run of a replay reading, are
    refused ``kind``."""
    from crb.core.context_arm import BASE_S2
    from crb.core.reading import RESERVED_FACTORY_PARAMS

    replay_only = {"budget_profile", "learning", "arm", "campaign_id"}
    factory_own = {"backlog_hash", "evolutions_hash", "deliver", "max_rework"}
    expected = (RESERVED_RUN_PARAMS - replay_only) | factory_own
    assert expected == RESERVED_FACTORY_PARAMS
    fwd = _f_forward()
    assert fwd.reserved and fwd.prospective
    cell = {k: fwd.cell[k] for k in ("builder", "model", "provider")}
    params: dict[str, Any] = {
        "task_ids": [],
        "limit": None,
        "pool": "",
        "executor": "",
        "timeout": 0,
        "backlog_hash": "b" * 64,
        "evolutions_hash": "",
        "deliver": False,
        "max_rework": 1,
        "test_author": "fake:author",
        "reading_id": fwd.reading_id,
        "outage_stop": 3,
        "env_stop": 3,
        "qualify_first": True,
        "max_cost_usd": 1.0,
    }
    assert set(params) == RESERVED_FACTORY_PARAMS

    def refusal(
        reading: Reading = fwd, *, kind: str = "factory", mode: str = "sighted", **over: Any
    ) -> tuple[str, dict[str, Any]]:
        args: dict[str, Any] = {**cell, "ladder": list(RESERVED_RUN_LADDER), "params": params}
        return reading_run_refusal(reading, kind=kind, mode=mode, **{**args, **over})

    assert refusal() == ("", {})
    cases: list[tuple[dict[str, Any], list[str]]] = [
        ({"params": {**params, "builder_config": {"x": 1}}}, ["builder_config"]),
        ({"params": {**params, "budget_profile": PROFILE_DEFAULT}}, ["budget_profile"]),
        ({"params": {**params, "learning": "off"}}, ["learning"]),
        ({"params": {**params, "timeout": 1}}, ["timeout"]),
        ({"ladder": ["r1", "r2"]}, ["ladder"]),
        ({"model": "other"}, ["model"]),
        ({"mode": "blind"}, ["mode"]),
    ]
    for over, fields in cases:
        code, detail = refusal(**over)
        assert (code, detail["fields"]) == (REFUSAL_RUN_FIELDS, fields), over
        assert detail["arm"] == ("" if "mode" in fields else BASE_S2), (over, detail)
    for kind in ("replay", "blind"):
        code, detail = refusal(kind=kind, mode="blind" if kind == "blind" else "sighted")
        assert code == REFUSAL_RUN_FIELDS and "kind" in detail["fields"], (kind, detail)
    replay = _reserved_reading(commits(4, prefix="q"), hierarchy=("S3",))
    assert replay.reserved and not replay.prospective
    code, detail = refusal(replay, **{k: replay.cell[k] for k in ("builder", "model", "provider")})
    assert code == REFUSAL_RUN_FIELDS and "kind" in detail["fields"], detail
    assert reading_run_refusal(
        _f_forward(reserved=False),
        kind="factory",
        mode="sighted",
        ladder=["r9"],
        params={"x": 1},
        builder="",
        model="",
        provider="",
    ) == ("", {})


def test_p792_post_readings_forward_opts_in_to_reserved(tmp_path: Path) -> None:
    """``POST /readings/forward`` registers a reserved.v1 forward reading only when asked:
    ``attempt_rule: reserved.v1`` stores ``max_reruns`` 0 and the budget profile
    (``default`` unless named), and a reserved.v1 body asking for reruns is refused 422
    ``invalid_reading`` and writes nothing. Before, the route took no rule."""
    from fixtures.proven import add_oracle_and_controls, add_rows, add_tasks, register_via_api
    from fixtures.server_seed import ALPHA, BUILDER, MODEL, PROVIDER, envelope, make_env

    with make_env(tmp_path, **SEALED_SETTINGS) as env:
        add_tasks(env.factory)
        r = register_via_api(env)
        assert r.status_code == 201, r.text
        pool = r.json()["pool"][:20]
        add_rows(env.factory, pool, arm="S3")
        add_rows(env.factory, pool[:3], arm=S1, clean=False)
        add_rows(env.factory, pool[3:], arm=S1)
        add_oracle_and_controls(env.factory, pool)
        body = {
            "repo": ALPHA,
            "promotes": r.json()["reading_id"],
            "builder": BUILDER,
            "model": MODEL,
            "provider": PROVIDER,
            "hypothesis": HYPOTHESIS,
            "smallest_effect": SMALLEST_EFFECT,
            "attempt_rule": ATTEMPT_RULE_RESERVED,
        }

        def registered() -> int:
            with env.factory() as s:
                q = select(Event).where(Event.action == READING_EVENT_ACTION)
                return len(list(s.execute(q).scalars()))

        before = registered()
        refused = env.post("/readings/forward", json={**body, "max_reruns": 1})
        assert refused.status_code == 422, refused.text
        err = envelope(refused)
        assert err["code"] == REFUSAL_INVALID, err
        assert err["detail"] == {"max_reruns": 1, "budget_profile": PROFILE_DEFAULT}
        assert registered() == before
        fwd = env.post("/readings/forward", json=body)
        assert fwd.status_code == 201, fwd.text
        got = fwd.json()
        assert got["attempt_rule"] == ATTEMPT_RULE_RESERVED
        assert (got["max_reruns"], got["budget_profile"]) == (0, PROFILE_DEFAULT)
        assert registered() == before + 1
