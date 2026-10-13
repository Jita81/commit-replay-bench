"""P-792: an admitted attempt decides its commit, and nothing a run chooses after admission
can steer which commits leave a reading or what a row says.

docs/PREVENTION.md P-792 records the finding: a round-5 enumeration of the Wave 3 reading
found nineteen channels (C1 to C19) through which an operator could choose which commits leave
a campaign reading, or what an admitted row says. The round-5 design spec for closing them
names one test per channel, each reproducing the enumeration's probe and failing before its
fix, and P-792 is closed on them now that ``POST /readings`` registers every reading under
reserved.v1 (DL-385). The channel tests live in five files, split by theme so that each stays
under CI's per-file time ceiling. This one holds the rigs and helpers the other parts import,
and the tests of C3, the rule itself, the treatment pin's projections and the factory; the
worker's tests are in tests/test_p792_reserved_losses.py (an attempt lost before or after its
reservation), tests/test_p792_reserved_rows.py (the reserved attempt's row decides, whatever
its kind), tests/test_p792_reserved_refusals.py (a run refused or halted before it reserves)
and tests/test_p792_reserved_reservation.py (where and how often the worker reserves, and how
``/readings`` registers and serves it).

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
rows never change its verdict), C15 (a settled reservation without a row is a miss) and C19
(an arm counts only its own reservation's row) each have a test here, and C7 (a non-loop run
spends on the reading's budget profile) one in the refusals part. Beside them are the goldens
that pin every legacy (``first_observed.v0``) reading as it read before and the property that
the reserved rule's hits are a subset of the legacy rule's.

The treatment pin's projections (worker helpers): a reservation pins a ``deployment_fp``
per campaign and repository and an ``arm_fp`` per arm, and a later mismatch halts the run.
C3 (``extra_args``), C4 (lint off), C5 (``timeout``), C7 (the budget profile) and C11 (a
``RepoConfig`` edit) each move a fingerprint; the ratchets list ``RepoConfig``'s and
``BuilderContainerSettings``' own fields, so a new field is pinned or named unpinned.

The factory (C8, C16): a forward reading opts in to reserved.v1 on ``POST /readings/forward``
(``attempt_rule``; ``max_reruns`` 0 only), and a factory run filed under it by ``reading_id``
is admitted only on the reading's cell — an off-cell run is refused 422 ``reading_run_fields``
at submit and ``run.refused`` at claim, nothing reserved (C8) — and reserves each ticket's
first ``S2`` build, so only that attempt decides it, whatever later rows say; an exception
after the reservation is a miss (C16), and a reservation that cannot be written never blocks
the build (``build.not_reserved``, the ticket counted by no reading).

Navigation
----------
What it is:   The P-792 channel tests that need no worker run but C3's and the factory's, and
              the rigs and helpers the other parts import (``_WRig`` and ``_w_*``, the worker
              rig; ``_r_stack`` and ``_r_*``, the submit-gate stack; ``_FRig``, the factory's).
What it does: C3: ``POST /runs`` refusing ``builder_config.extra_args`` 422 (a), the claim
              refusing it ``run.refused`` (b), and ``ClaudeCodeBuilder.describe()`` naming
              ``extra_args`` and ``claude_binary`` when set, a builder with neither describing
              itself byte for byte as before (c). The legacy goldens: every registration
              variant's id and every scenario's outcome, looks and per-commit verdicts, printed
              from the code before reserved.v1, with the one deliberate move beside them
              (``P795_MOVED``). reserved.v1: C4, C6 (every exit, against later rows of other
              runs, with the legacy control), C15, C19, an imported copy of a reserved row
              deciding nothing (R5V3-IMPORT-1, P-321), each check a named miss, a reserved row
              off the reading's checks arm a ``scope_fault`` and never a miss (RT2B-1, VS1-2),
              a forward reserved row off the frozen arm a ``scope_fault`` and another attempt
              of a reserved ticket a duplicate, the registration's ``max_reruns`` 0 and budget
              profile, the ``reading_run_refusal`` whitelist table and the arm each admitted
              run maps to, and a loop arm filing its enrolled commits in the seeded order
              (NEW-1); the hypothesis property that a reserved hit is a legacy hit and a
              reserved ``deliver`` a legacy one at the same look or earlier, and its
              condition's counterexample. The projections: every pinned field and deployment
              input moves its fingerprint, A0 and A0+L share ``deployment_fp``, a calibrated
              profile moves only ``arm_fp``, a person on the loop's chain moves the ``A0+L``
              ``arm_fp``, and no secret reaches a projection. The factory: C8 (the legacy
              ``_forward_attempt`` golden; an off-cell run refused at submit and at claim),
              C16, the hook never blocking delivery, a run off the reading's checks arm halting
              before it reserves (V1-CA-3), only the reserved attempt counting, a reserved
              ticket placed by its ``item_id`` in F8's tally, the ``RESERVED_FACTORY_PARAMS``
              ratchet and ``POST /readings/forward`` opting in.
How:          The reading tests build readings, ``Reservation`` values and chained rows in
              memory and call the pure core; the projection tests call the worker's pure
              helpers on in-memory values; C3 reads the builder's argv for
              ``fixtures.builders_repo``'s task with the worker's ``CRB_CLAUDE_CODE_*``
              defaults cleared (``_worker_defaults_cleared``, autouse, which each part
              imports). ``_w_rig`` runs ``test_worker``'s ``Harness`` (SQLite, or the
              ``backend`` fixture's database) over the pyrepo fixture with a second commit, the
              fake builder and a local sandbox on the run's cancel token, each row relabelled
              as a sealed worker writes it; ``_r_stack`` runs the app on the ``backend``
              store with the Wave 3 rehearsal's campaign; ``_f_rig`` runs a factory run on the
              worker rig under a forward reading appended as its event (``_FRig.register``).
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md,
              docs/adr/0026-the-context-standard.md
Works with:   src/crb/core/reading.py (the reserved.v1 rule, ``reading_run_refusal`` and the
              legacy loop, under test), src/crb/server/worker.py (the projections, under
              test; the reserver the rigs drive), src/crb/builders/claude_code.py
              (``describe`` and ``argv``, under test), src/crb/factory/build.py and
              src/crb/factory/loop.py (the reserve hook, ``build.not_reserved``),
              tests/fixtures/readings.py (the registrations and rows the tests build on),
              tests/test_worker.py and tests/test_wave3_registration_rehearsal.py
              (``Harness`` and ``FakeBuilder``; the campaign the submit-gate stack posts to),
              docs/PREVENTION.md (P-792, the row these tests close; P-795, the golden's move),
              tests/test_p792_reserved_losses.py and tests/test_p792_reserved_rows.py and
              tests/test_p792_reserved_refusals.py and tests/test_p792_reserved_reservation.py
              and tests/test_p792_pool.py (the parts that import the rigs and helpers here)
Tested by:    tests/test_p792_reserved.py
Touch when:   never for a new repository; a P-792 channel's fix lands (its test goes in the part
              its theme names, failing first), a rig or helper the parts share changes, or a
              builder gains a constructor option that shapes its argv (the stamp names it when
              set, and ``DEFAULT_STAMP`` stays unchanged); the reserved.v1 verdict or the run
              whitelist changes (its table row here first); a ``RepoConfig`` /
              ``BuilderContainerSettings`` field or a deployment input is added (its edit in
              the ratchet's table, which fails until then); never to regenerate ``GOLDEN`` — a
              legacy reading that moves is a regression, unless a PREVENTION row moves it on
              purpose (``P795_MOVED``, beside it).
"""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import inspect
import json
import os
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
from crb.core.learn import remeasure_plan
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
from crb.core.prevention import (
    AUTO_CONFIG,
    AUTO_CONTEXT,
    K_SECTION,
    LearningSnapshot,
    empty_snapshot,
)
from crb.core.reading import (
    ATTEMPT_RULE_LEGACY,
    ATTEMPT_RULE_RESERVED,
    HALT_CHECKS_ARM_MISMATCH,
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
    REFUSAL_RUN_FIELDS,
    RESERVED_RUN_LADDER,
    RESERVED_RUN_PARAMS,
    RULE_LOOK_V1,
    RULE_LOOK_V1_STRICT,
    RULES,
    SCOPE_CHECKS_ARM,
    SCOPE_UNSEALED,
    STATE_DELIVER,
    STATE_INSUFFICIENT,
    STATE_LOOK_PENDING,
    STATE_UNDECIDED,
    Reading,
    ReadingRefused,
    Reservation,
    arm_reading,
    enrolled,
    evaluate,
    loop_pair,
    reading_run_refusal,
    register,
    register_forward,
    verdict_for,
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
from crb.core.version import APPARATUS_VERSION
from crb.server import campaigns as campaigns_mod
from crb.server import worker
from crb.server.app import create_app
from crb.server.posture_view import deployment_posture_class
from crb.server.reading_book import load_readings
from crb.server.routes import runs as runs_routes
from crb.server.routes.learn import deployment_author_model
from crb.store import qualifications as store_q
from crb.store.db import init_db
from crb.store.events import append_event
from crb.store.jobs import (
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    JobQueue,
)
from crb.store.ledger import DbLedger, import_stamp
from crb.store.models import Event, Repo, Run, Task
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
    format_step_in_force,
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
    move (:data:`P795_MOVED`), whose commit is named a scope fault. Beside those verdicts each
    arm counts the rows after the one that decided a commit (``duplicate_commits``, F87-2):
    the forward ticket whose passing first attempt decided it has a failing second one."""
    assert _g_snapshot() == _golden_after_p795()
    reading, rows = _g_replay()
    s3 = evaluate(reading, rows).arms["S3"]
    assert s3.scope_faults == (reading.pool[5],)
    assert s3.commits[5].reason == REASON_SCOPE_FAULT
    dups = {
        name: {arm: a.duplicate_commits for arm, a in evaluate(*scenario).arms.items()}
        for name, scenario in {"replay": (reading, rows), "forward": _g_forward()}.items()
    }
    assert dups == {"replay": {"S3": 0, S1: 0, "A0": 0}, "forward": {"S2": 1}}


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


def test_two_admitted_attempts_of_one_commit_the_first_admitted_decides() -> None:
    """F87-2 (round 6): two runs a campaign admitted attempt one commit on one arm. ``A``,
    admitted first, holds the commit's ``reading.reserved`` event; ``B``, admitted second,
    carries none (a second run on a reserved commit skips it, ``commit_reserved`` — the
    worker's half is ``test_p792_c2_cancel_during_witness_is_a_miss`` and
    ``test_p792_concurrent_reserve_one_wins``), yet its row is written BEFORE ``A``'s. The
    commit is read by ``A``'s row, hit or miss, wherever it falls in the ledger — a pin:
    reserved.v1 never read row order — and the arm serves ``duplicate_commits`` 1, the row
    of a decided commit it did not read; it read no such count before. A row of a run the
    campaign never admitted, and a row on a commit still pending, are not counted, and the
    count moves no verdict. The legacy control reads the same rows in LEDGER order: ``B``'s
    row decides, ``A``'s is the one it did not read — the legacy rule is not reordered (a
    known gap: POST /readings registers reserved.v1 only)."""
    pool = commits(3, prefix="fa")
    reading = _reserved_reading(pool, hierarchy=("S3",), campaign_id="camp-fa")
    c, other = reading.pool[0], reading.pool[1]
    res = _res("S3", c, run="run-A")
    loaded = _read(with_admissions(reading, ["run-A", "run-B"]), [res])
    legacy = with_admissions(
        register_reading(pool, hierarchy=("S3",), budget=0.05, campaign_id="camp-fa"),
        ["run-A", "run-B"],
    )
    for a_clean in (True, False):
        row_b = sealed_row(c, clean=not a_clean, run_id="run-B")  # admitted second, unreserved
        row_a = _reserved_row(res, clean=a_clean)  # admitted first, the reservation's row
        rows = _g_chain(
            [
                row_b,
                row_a,
                sealed_row(c, clean=not a_clean, run_id="run-C"),  # never admitted
                sealed_row(other, run_id="run-B"),  # a commit nothing reserved: pending
            ]
        )
        arm = arm_reading(loaded, "S3", rows)
        got = arm.commits[0]
        assert (got.commit, got.outcome, got.reason) == (c, a_clean, "" if a_clean else "miss")
        assert got.row_hash == rows[1].row_hash  # A's row, though B's was written first
        assert arm.commits[1].outcome is None
        assert arm.duplicate_commits == 1
        assert arm.to_dict()["duplicate_commits"] == 1
        # the reservation's row alone: the same verdicts, nothing it did not read
        alone = arm_reading(loaded, "S3", [rows[1]])
        assert [(x.outcome, x.reason) for x in alone.commits] == [
            (x.outcome, x.reason) for x in arm.commits
        ]
        assert (alone.duplicate_commits, alone.look, alone.state) == (0, arm.look, arm.state)
        # the legacy control: ledger order, so B's row decides and A's is not read
        old = arm_reading(legacy, "S3", rows)
        (lc,) = [x for x in old.commits if x.commit == c]
        assert (lc.outcome, lc.row_hash) == (not a_clean, rows[0].row_hash)
        assert old.duplicate_commits == 1
        without_a = arm_reading(legacy, "S3", [r for r in rows if r is not rows[1]])
        assert [(x.outcome, x.left) for x in without_a.commits] == [
            (x.outcome, x.left) for x in old.commits
        ]
        assert (without_a.duplicate_commits, without_a.look) == (0, old.look)


def _imported_copy(row: GradeRow) -> GradeRow:
    """What an admin can post to ``POST /ledger/import`` after reading ``row`` off ``GET
    /ledger/export``: the same run, commit, rung and reservation, claim and treatment labels,
    with a fresh ``row_id`` and no evidence pack, so the route's dedupe (on ``row_id`` and
    pack hash) lets it through."""
    d = {**row.to_dict(), "row_id": "", "evidence_pack_hash": "", "prev_hash": "", "row_hash": ""}
    return GradeRow.from_dict(d)


def test_p792_reserved_an_imported_copy_decides_nothing(backend: Backend) -> None:
    """R5V3-IMPORT-1 (P-792, P-321): an imported row never counts toward a reserved.v1
    reading, whatever labels it carries. An admin who, after the outcomes, imports a red copy
    of a reserved row — its run, commit, rung, reservation, claim and treatment — leaves a
    hit a hit (it read ``duplicate`` before), an attempt in flight pending (``out_of_scope``
    before) and a settled attempt with no row of its own ``unobserved``; the hit is served by
    the reserved row's own hash. In memory, and end to end through ``DbLedger.append`` and
    ``DbLedger.import_rows`` on the backend's store (SQLite, and PostgreSQL when set), as
    ``POST /ledger/import`` writes it and ``GET /readings`` reads it."""
    reading = _reserved_reading(commits(2, prefix="imp"), hierarchy=("S3",))
    c = reading.pool[0]
    res = _res("S3", c)
    loaded = _read(reading, [res])
    own = _reserved_row(res)
    copy = _imported_copy(_reserved_row(res, clean=False))
    imported = GradeRow(
        **{**import_stamp(copy, imported_by="admin-1", imported_at="2026-10-12"), "prev_hash": ""}
    )
    assert imported.imported and imported.labels[LABEL_RESERVATION] == res.event_id
    assert _verdicts(loaded, "S3", [own])[0] == (True, "")
    assert _verdicts(loaded, "S3", [own, imported])[0] == (True, "")
    assert _verdicts(loaded, "S3", [imported])[0] == (None, "pending")
    settled = _read(reading, [dataclasses.replace(res, settled=True)])
    assert _verdicts(settled, "S3", [imported])[0] == (False, "unobserved")
    assert arm_reading(loaded, "S3", [imported, own]).commits[0].row_hash == own.row_hash

    init_db(backend.engine)
    ledger = DbLedger(backend.factory)
    ledger.import_rows([copy], imported_by="admin-1", imported_at="2026-10-12T00:00:00+00:00")
    in_flight = list(ledger.rows(repo=REPO))
    assert [(r.imported, r.labels[LABEL_RESERVATION]) for r in in_flight] == [(True, res.event_id)]
    assert _verdicts(loaded, "S3", in_flight)[0] == (None, "pending")
    landed = ledger.append(own)
    stored = list(ledger.rows(repo=REPO))
    assert sorted(r.imported for r in stored) == [False, True]
    got = arm_reading(loaded, "S3", stored).commits[0]
    assert (got.outcome, got.reason, got.row_hash) == (True, "", landed.row_hash)


def test_p792_reserved_each_check_is_a_named_miss() -> None:
    """Every check the reserved row must pass is a miss named by its reason when it fails —
    never a leave, never a hit — on a replay arm and on a forward reading; each case's
    reserved row is otherwise the clean hit of the first case, and a scope fault (unsealed,
    or off the checks arm) is no hit and no miss: outcome ``None`` (VS1-2). A reservation
    that pins no treatment can never be a hit (fail closed)."""
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
        # the arm's row but for its executor: the writer's fault, never another reading's
        # (P-795) — no hit and no miss, outcome None as on the legacy rule (VS1-2)
        "local_executor": (_res("S3", c), {"builder_executor": "local"}, (None, "scope_fault")),
        # the arm's reserved row but for its checks arm: this reading's reservation, so never
        # another reading's row — a scope fault, never a miss (RT2B-1)
        "checks_arm": (_res("S3", c), {"labels": {"checks": "fmt=1"}}, (None, "scope_fault")),
        # off the checks arm AND failing an earlier check: the earlier check's answer stands
        "checks_arm_graded_before": (
            _res("S3", c),
            {"labels": {"checks": "fmt=1"}, "created": BEFORE},
            (False, "out_of_scope"),
        ),
        "checks_arm_host_posture": (
            _res("S3", c),
            {"labels": {"checks": "fmt=1"}, "posture_class": "local/inplace/host-env"},
            (False, "out_of_scope"),
        ),
    }
    scopes = {"local_executor": SCOPE_UNSEALED, "checks_arm": SCOPE_CHECKS_ARM}
    for name, (res, kw, expect) in replay.items():
        row = _reserved_row(res, **kw)
        got = arm_reading(_read(reading, [res]), "S3", [row]).commits[0]
        assert (got.outcome, got.reason) == expect, name
        assert got.left == "" and got.row_hash == row.row_hash, name
        assert got.scope == scopes.get(name, "") == got.to_dict()["scope"], name
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


def test_a_reserved_row_off_the_readings_checks_arm_is_scope_fault_not_a_miss() -> None:
    """RT2B-1 part 2 (round 6): a reserved.v1 reading freezes its checks arm (``off``), and
    a reserved row graded on another (``fmt``) carries this reading's reservation, so it is
    no other reading's row. It read ``out_of_scope`` — a miss — so three such rows among the
    20 reserved rows of an ``S3`` look read the arm ``insufficient``: an apparatus fault
    charged to the builder, and the cell barred. Each now reads ``scope_fault`` with
    ``scope`` ``checks_arm``: the arm is ``undecided`` and names the three commits in
    ``scope_faults`` (no hit among them, none counted unsealed), the reading has no standard
    and needs nothing, and the remeasure plan asks for no attempt — it names the checks arm
    the reading froze against the rows' — so nothing is re-run."""
    reading = _reserved_reading(commits(20, prefix="ck"), hierarchy=("S3",))
    assert reading.checks_arm == "off"
    off = {reading.pool[i] for i in (2, 9, 15)}
    reservations = [
        _res("S3", c, run=f"run-{i}", event=f"ev-ck-{i}") for i, c in enumerate(reading.pool)
    ]
    rows = [
        _reserved_row(res, labels={"checks": "fmt=1"} if res.task_id in off else None)
        for res in reservations
    ]
    assert sorted(r.checks_arm for r in rows) == ["fmt"] * 3 + ["off"] * 17
    out = evaluate(_read(reading, reservations), rows)
    s3 = out.arms["S3"]
    got = {c.commit: (c.outcome, c.reason, c.scope) for c in s3.commits}
    assert {c: got[c] for c in off} == dict.fromkeys(
        off, (None, REASON_SCOPE_FAULT, SCOPE_CHECKS_ARM)
    )
    assert all(got[c] == (True, "", "") for c in reading.pool if c not in off)
    assert s3.scope_faults == tuple(c for c in reading.pool if c in off)
    assert s3.unsealed_dropped == 0
    assert s3.state == STATE_UNDECIDED and out.state == STATE_UNDECIDED
    assert out.standard == "" and out.chain == () and out.needed == 0
    assert verdict_for(out, "S3").state == STATE_UNDECIDED
    served = {a["arm"]: a for a in out.to_dict()["arms"]}["S3"]
    assert sorted(served["scope_faults"]) == sorted(off)
    assert {c["commit"]: c["scope"] for c in served["commits"] if c["scope"]} == dict.fromkeys(
        off, SCOPE_CHECKS_ARM
    )
    plan = remeasure_plan(rows, readings=(out,), current_apparatus="2.4")
    assert not plan.pending and not plan.up_to_date
    (blocked,) = plan.cannot_clear
    assert (blocked.arm, blocked.state, blocked.next_act) == ("S3", STATE_UNDECIDED, "audit")
    assert "built on checks arm fmt where the reading froze checks arm off" in blocked.reason
    assert all(c in blocked.reason for c in off) and "sealed container" not in blocked.reason
    # the same rows on the reading's arm: the arm reads by its look and delivers
    on_arm = [_reserved_row(res) for res in reservations]
    assert evaluate(_read(reading, reservations), on_arm).arms["S3"].state == STATE_DELIVER


def test_p792_a_reserved_scope_fault_is_no_miss_in_a_look_a_tally_or_the_loop_pair() -> None:
    """VS1-2, F1, V1-CA-1 (round 6): a reserved.v1 ``scope_fault`` read outcome ``False``, so
    the served look counted it a miss — three among an ``S3`` look's 20 read the look
    ``insufficient`` with three misses in its Wilson bounds — a descriptive arm's tally
    counted it, and the loop pair read an ``A0`` fault as an ``A0`` miss: a discordant pair
    FOR the loop (``b`` 1). The docs said never a miss. It now reads outcome ``None``, as the
    legacy rule reads an unsealed row: the look stops at it with no miss, the tally leaves it
    out, and the loop pair names it pending (NEW-1, read against the loop), ``b`` 0. Its
    reserved row is still named, and another admitted attempt of the commit is still counted
    in ``duplicate_commits``."""
    reading = _reserved_reading(
        commits(20, prefix="sf"), hierarchy=("S3",), descriptive=(("A0", 16), ("A0+L", 16))
    )
    off = [reading.pool[i] for i in (2, 9, 15)]
    first_a0 = enrolled(reading, "A0")[0]
    reservations = [
        _res("S3", c, run=f"s3-{i}", event=f"ev-s3-{i}") for i, c in enumerate(reading.pool)
    ]
    for arm in ("A0", "A0+L"):
        reservations += [
            _res(arm, c, run=f"{arm}-{i}", event=f"ev-{arm}-{i}")
            for i, c in enumerate(enrolled(reading, arm))
        ]
    faulted = {("S3", c) for c in off} | {("A0", first_a0)}
    # chained as the ledger writes them, so each row has a hash; the last is a second
    # admitted attempt of a faulted commit, on the arm: a duplicate, never read
    rows = _g_chain(
        [
            *(
                _reserved_row(
                    res, labels={"checks": "fmt=1"} if (res.arm, res.task_id) in faulted else None
                )
                for res in reservations
            ),
            sealed_row(off[0], arm="S3", run_id="s3-again"),
        ]
    )
    reserved = {(r.context_arm, r.task_id): r for r in rows[: len(reservations)]}
    assert all(r.row_hash for r in rows)
    out = evaluate(_read(reading, reservations), rows)
    served = {a["arm"]: a for a in out.to_dict()["arms"]}
    s3 = served["S3"]
    assert (s3["state"], s3["look_state"], s3["counted"], s3["misses"]) == (
        STATE_UNDECIDED,
        STATE_LOOK_PENDING,
        2,
        0,
    )
    assert s3["look_state"] != STATE_INSUFFICIENT
    assert sorted(s3["scope_faults"]) == sorted(off) and s3["duplicate_commits"] == 1
    commits_of = {c["commit"]: c for c in s3["commits"]}
    for c in off:
        got = commits_of[c]
        assert (got["outcome"], got["reason"], got["scope"], got["row_hash"]) == (
            None,
            REASON_SCOPE_FAULT,
            SCOPE_CHECKS_ARM,
            reserved[("S3", c)].row_hash,
        )
    a0 = out.arms["A0"]
    head = a0.commits[0]
    assert (head.commit, head.outcome, head.reason, head.scope) == (
        first_a0,
        None,
        REASON_SCOPE_FAULT,
        SCOPE_CHECKS_ARM,
    )
    assert a0.state == STATE_UNDECIDED and a0.scope_faults == (first_a0,)
    assert (served["A0"]["counted"], served["A0"]["misses"]) == (15, 0)
    assert first_a0 not in a0.counted_commits
    pair = loop_pair(a0, out.arms["A0+L"])
    assert first_a0 in pair.pairs
    assert (pair.b, pair.c, pair.pending, pair.complete) == (0, 0, (first_a0,), False)


def test_p792_a_forward_reserved_row_off_the_checks_arm_is_a_scope_fault() -> None:
    """V1-CA-2 (round 6): a forward reserved.v1 reading's reserved ``S2`` row graded on
    another checks arm than the reading froze failed ``_counts_forward`` and read
    ``(False, "not_graded")`` — a counted miss — where the replay rule reads the same row a
    scope fault (RT2B-1). It now reads ``scope_fault`` (``scope`` ``checks_arm``, outcome
    ``None``): the ticket is named in ``scope_faults``, the arm is ``undecided`` and its look
    counts no miss. A row off the arm that fails an earlier check too keeps that answer."""
    fwd = _reserved_forward(2)
    assert fwd.checks_arm == "off"
    r0, r1 = (_res("S2", item, run=f"fac-{i}", settled=True) for i, item in enumerate(fwd.pool))
    loaded = _read(fwd, [r0, r1])
    off_arm, on_arm = _g_chain(
        [
            _g_s2(_g_record(0), extra={**_stamp(r0), "checks": "fmt=1"}, run_id=r0.run_id),
            _g_s2(_g_record(1), extra=_stamp(r1), run_id=r1.run_id),
        ]
    )
    assert (off_arm.checks_arm, on_arm.checks_arm) == ("fmt", "off")
    assert off_arm.row_hash and on_arm.row_hash
    s2 = arm_reading(loaded, "S2", [off_arm, on_arm])
    assert [(c.outcome, c.reason, c.scope, c.row_hash) for c in s2.commits] == [
        (None, REASON_SCOPE_FAULT, SCOPE_CHECKS_ARM, off_arm.row_hash),
        (True, "", "", on_arm.row_hash),
    ]
    assert s2.scope_faults == (fwd.pool[0],) and s2.unsealed_dropped == 0
    assert s2.state == STATE_UNDECIDED and s2.look.misses == 0
    earlier: dict[str, dict[str, Any]] = {
        "other_record": {"stamp": held_out_labels(_g_record(1), RESULT_PASS)},
        "not_held_out": {"stamp": {}},
    }
    for name, kw in earlier.items():
        row = _g_s2(_g_record(0), extra={**_stamp(r0), "checks": "fmt=1"}, run_id=r0.run_id, **kw)
        assert _verdicts(loaded, "S2", [row, on_arm])[0] == (False, "not_graded"), name


def test_p792_forward_reserved_counts_another_attempt_of_a_ticket_a_duplicate() -> None:
    """F5 (round 6): a forward reserved.v1 reading's ticket built twice by admitted runs — an
    unreserved attempt written first, failing its held-out tests, then the reserved one — is
    read by the reserved row alone (a hit), and the other attempt is counted in
    ``duplicate_commits`` (the forward branch of ``_arm_attempt``: a ticket's factory
    attempt, ``_forward_attempt``), never read toward the verdict. A ticket whose reserved
    row is its only attempt counts none. The other attempt is graded off the reading's
    checks arm (``fmt=1``): the forward branch counts it whatever it was graded on, while the
    replay scope it would otherwise fall to (``_in_scope``) drops it as a checks-arm miss, so
    the count pins the branch (R6V2-1)."""
    fwd = _reserved_forward(2)
    r0, r1 = (_res("S2", item, run=f"fac-{i}", settled=True) for i, item in enumerate(fwd.pool))
    other, reserved, lone = _g_chain(
        [
            _g_s2(_g_record(0), result=RESULT_FAIL, extra={"checks": "fmt=1"}, run_id="fac-x"),
            _g_s2(_g_record(0), extra=_stamp(r0), run_id=r0.run_id),
            _g_s2(_g_record(1), extra=_stamp(r1), run_id=r1.run_id),
        ]
    )
    assert len({other.row_hash, reserved.row_hash, lone.row_hash}) == 3
    s2 = arm_reading(_read(fwd, [r0, r1]), "S2", [other, reserved, lone])
    assert [(c.outcome, c.reason, c.row_hash) for c in s2.commits] == [
        (True, "", reserved.row_hash),
        (True, "", lone.row_hash),
    ]
    assert s2.duplicate_commits == 1


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
    "outage_stop": 1,
    "env_stop": 1,
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
    # PW-7: a reading run halts at its first outage or environment row — a stop knob is 1
    # or unset; True, 0 (off), null, 2 and 3 would each let it reserve past an outage
    ("stops_unset", {}, {k: v for k, v in _RUN_OK.items() if not k.endswith("_stop")}, "S3", []),
    *(
        (f"{k}_{v!r}", {}, {**_RUN_OK, k: v}, "", [k])
        for k in ("outage_stop", "env_stop")
        for v in (True, 0, None, 2, 3, "1", 1.0)
    ),
    (
        "both_stops",
        {},
        {**_RUN_OK, "outage_stop": 3, "env_stop": 2},
        "",
        ["env_stop", "outage_stop"],
    ),
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
    params = {**params, "task_ids": [reading.pool[0]]}  # A0+L files in the seeded order
    fields = {**_S3_RUN, **_CELL_RUN, **run}
    code, detail = reading_run_refusal(reading, params=params, **fields)
    if refused:
        assert code == REFUSAL_RUN_FIELDS, name
        assert detail["fields"] == refused, (name, detail)
        assert set(detail["reasons"]) == set(refused)
        assert all(detail["reasons"][f] for f in refused)
        assert arm == ""  # a refused run maps to no arm
    else:
        assert (code, detail) == ("", {}), name
    # a legacy reading is never refused by it, admitted run or refused: the legacy rule is
    # unchanged
    legacy = register_reading(commits(3, prefix="w"), descriptive=(("A0", 2),), budget=0.05)
    assert reading_run_refusal(legacy, params=params, **fields) == ("", {})


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
    from crb.core.reading import RESERVED_RUN_STOP

    assert RESERVED_RUN_STOP == 1  # PW-7: the first outage or environment row halts it
    reading = _reserved_reading(commits(3, prefix="w"), descriptive=(("A0", 2), ("A0+L", 2)))
    for name, run, params, arm, refused in _RUN_TABLE:
        if refused:
            continue
        params = {**params, "task_ids": [reading.pool[0]]}  # A0+L files in the seeded order
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


def test_p792_a_loop_arm_files_its_enrolled_commits_in_the_seeded_order() -> None:
    """NEW-1 (round 5): nothing compared a run's ``task_ids`` with the arm's enrolled commits,
    so with ``A0``'s outcomes in hand ``A0+L`` could be filed on ``A0``'s misses alone, or in an
    order of the operator's choosing, and the loop learns from each attempt it makes. A run of
    a loop arm (``A0+L``) now names its commits, each one the arm enrols, and those it has not
    reserved are, in order, the first of its enrolled commits it has not reserved — the whole
    list, any prefix of it, or a re-file of it after some are reserved (those are skipped).
    Anything else is refused ``task_ids``, at submit and at claim alike. ``A0``, which runs with
    the loop off, and a hierarchy arm are not held to it: a commit pending on ``A0`` is read
    against the loop by the pair (``loop_pair``), and a look waits at its first pending one."""
    pool = commits(20, prefix="w")
    reading = _reserved_reading(pool, descriptive=(("A0", 16), ("A0+L", 16)))
    order = list(enrolled(reading, "A0+L"))
    assert len(order) == 16 and order == list(reading.pool[:16])
    loop = {**_A0_RUN, **_CELL_RUN}
    base = {k: v for k, v in _NO_LOOP_KEYS.items() if k != "task_ids"}

    def refusal(r: Reading, tasks: list[str], **over: Any) -> tuple[str, dict[str, Any]]:
        return reading_run_refusal(r, params={**base, "task_ids": tasks, **over}, **loop)

    for ok in (order, order[:3], order[:1]):
        assert refusal(reading, ok) == ("", {}), ok
    assert refusal(reading, order, limit=4) == ("", {})  # a limit keeps a prefix
    refused = {
        "a0_misses_only": [order[1], order[4], order[9]],
        "reversed": order[::-1],
        "a skipped head": order[1:],
        "swapped": [order[1], order[0], *order[2:]],
        "past_n": [*order, reading.pool[16]],
        "a stranger": [*order[:2], "f" * 40],
        "twice": [order[0], order[0]],
        "none, by limit": [],
    }
    for name, tasks in refused.items():
        code, detail = refusal(reading, tasks, limit=16)
        assert (code, detail["fields"], detail["arm"]) == (
            REFUSAL_RUN_FIELDS,
            ["task_ids"],
            "A0+L",
        ), name
        assert "seeded order" in detail["reasons"]["task_ids"], name
    # after the first five are reserved: re-filing the whole list, or the rest of it, is the
    # seeded order still; starting past the sixth is not
    held = _read(
        reading,
        [_res("A0+L", c, seq=REG_EVENT + 1 + i) for i, c in enumerate(order[:5])],
    )
    for ok in (order, order[5:], order[5:7], order[:5], [*order[:5][::-1], *order[5:]]):
        assert refusal(held, ok) == ("", {}), ok
    assert refusal(held, order[6:])[0] == REFUSAL_RUN_FIELDS
    # A0's reservations do not move A0+L's order
    a0_held = _read(
        reading, [_res("A0", c, seq=REG_EVENT + 1 + i) for i, c in enumerate(order[:5])]
    )
    assert refusal(a0_held, order[5:])[0] == REFUSAL_RUN_FIELDS
    # A0 and a hierarchy arm are not held to the order
    a0 = {**_RUN_OK, "task_ids": [order[9], order[4], order[1]]}
    assert reading_run_refusal(reading, params=a0, **{**_A0_RUN, **_CELL_RUN}) == ("", {})
    assert reading_run_refusal(reading, params=a0, **{**_S3_RUN, **_CELL_RUN}) == ("", {})


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
    (no re-run left to wait for). The argument holds when no other reading whose rows the
    legacy rule reads enrols the commit on the same arm (``test_p792_conservative_needs_one_
    reading_per_commit_and_arm``), so the worlds draw, before each reserved attempt, an
    earlier row of another reading that keeps to it: on another arm, or — when both
    readings name a campaign — on the same arm in a run another campaign admitted."""
    rule = data.draw(st.sampled_from(sorted(RULES)), label="rule")
    campaign = data.draw(st.sampled_from(("", "camp-h")), label="campaign")
    others = ("none", "other_arm", "other_campaign") if campaign else ("none", "other_arm")
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
    outside: set[str] = set()
    for i, commit in enumerate(order):
        exit_ = exits[i] if i < _DRAWN else "clean"
        other = data.draw(st.sampled_from(others), label="other") if i < _DRAWN else "none"
        if other == "other_arm":
            rows.append(
                sealed_row(commit, arm="A0", run_id=f"other-{i}", clean=data.draw(st.booleans()))
            )
        elif other == "other_campaign":
            outside.add(f"outside-{i}")
            rows.append(sealed_row(commit, run_id=f"outside-{i}", clean=data.draw(st.booleans())))
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
    admitted = sorted({r.run_id for r in rows} - outside)
    legacy = with_admissions(
        register_reading(
            _H_POOL,
            hierarchy=("S3",),
            rule=rule,
            budget=0.05,
            changes=changes,
            campaign_id=campaign,
        ),
        admitted,
    )
    reserved = with_admissions(
        _read(
            _reserved_reading(
                _H_POOL, hierarchy=("S3",), rule=rule, changes=changes, campaign_id=campaign
            ),
            reservations,
        ),
        admitted,
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


def test_p792_conservative_needs_one_reading_per_commit_and_arm() -> None:
    """The bound of the round-5 argument: its steps 1 and 2 hold only when no other reading
    whose rows the legacy rule reads enrols the commit on the same arm. Two reserved.v1
    readings of one campaign on one cell and arm can each reserve the same commit; the legacy
    rule reads the other reading's earlier miss as the commit's first observed attempt, and
    this reading's own reserved hit is a new hit with no old one. Wave 3 keeps to the bound —
    one reading per cell, and a commit in one cell's pool — so the registration scopes the
    argument to it rather than refusing the overlap."""
    pool = commits(25, prefix="o")
    camp = "camp-1"
    legacy = with_admissions(
        register_reading(pool, hierarchy=("S3",), budget=0.05, campaign_id=camp),
        ["run-B", "run-A"],
    )
    first = legacy.pool[0]
    res_b = _res("S3", first, run="run-B", event="ev-B")
    res_a = _res("S3", first, run="run-A", event="ev-A", seq=REG_EVENT + 20)
    rows = [_reserved_row(res_b, clean=False), _reserved_row(res_a)]
    reserved = with_admissions(
        _read(_reserved_reading(pool, hierarchy=("S3",), campaign_id=camp), [res_a]),
        ["run-B", "run-A"],
    )
    old = arm_reading(legacy, "S3", rows).commits[0]
    new = arm_reading(reserved, "S3", rows).commits[0]
    assert (old.commit, new.commit) == (first, first)
    assert (old.outcome, old.left) == (False, "")
    assert (new.outcome, new.reason) == (True, "")
    # without the other reading's row, the old hit is the new one
    alone = arm_reading(legacy, "S3", rows[1:]).commits[0]
    assert (alone.outcome, alone.left) == (True, "")


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
    non-L arm's ``arm_fp`` and nowhere in the deployment. The +L arm pins its arm id, learn
    level and a person's acts on the loop's chain (none here) — what the loop learns between
    commits is what it measures."""
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
    assert a0l == {"arm": "A0+L", "learn": AUTO_CONTEXT, "person": ""}
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


def test_p792_a_person_on_the_loop_moves_the_l_arm_fp() -> None:
    """C7 on ``+L``: the arm half pins what a person did to the loop's chain, not only its
    level. The loop applying a switch and retiring it (its own acts) is the ``+L`` treatment
    and keeps ``arm_fp``; a person's veto revert (``POST /learn/changes/{id}/revert``: the
    change leaves force and the loop never re-applies it) or link (``POST /learn/links``)
    moves it, as a level edit does, so the reading's next ``A0+L`` reservation halts
    ``reading_treatment_mismatch``. Before, ``{arm, learn}`` alone was pinned and a veto
    reshaped the ``+L`` treatment mid-reading with ``arm_fp`` unmoved."""
    from crb.core.prevention import AUTO_CONFIG, PreventionRecord, snapshot

    r1 = _r1_budget()
    repo = "p792"

    def rec(kind: str, payload: dict[str, Any], *, actor: str, at: int) -> PreventionRecord:
        return PreventionRecord(
            kind, repo, payload, actor=actor, created=f"2026-10-12T0{at}:00:00+00:00"
        )

    def arm_fp(*records: PreventionRecord) -> str:
        learning = snapshot(records, repo=repo, params={})
        return worker.fingerprint(worker.arm_projection("A0+L", learning, PROFILE_DEFAULT, r1))

    switched = rec("switched", {"auto_apply": AUTO_CONFIG}, actor="op-1", at=0)
    applied = rec(
        "applied",
        {
            "change_id": "chg-1",
            "lever_id": "budget_calibrated",
            "family": "config",
            "level": "config",
            "targets": ["E-BUDGET"],
            "key": "k",
            "what": {"section": K_SECTION, "key": "budget_profile", "value": PROFILE_CALIBRATED},
        },
        actor="loop",
        at=1,
    )
    pinned = arm_fp(switched, applied)
    assert snapshot([switched, applied], repo=repo, params={}).overlay
    # the loop's own acts — applying, then retiring by measurement — are the treatment
    assert arm_fp(switched) == pinned
    retired = rec(
        "reverted", {"change_id": "chg-1", "by": "loop", "veto": False}, actor="loop", at=2
    )
    assert arm_fp(switched, applied, retired) == pinned
    # a person's veto revert, exactly as the route writes it, moves the +L arm
    veto = rec("reverted", {"change_id": "chg-1", "by": "person", "veto": True}, actor="op-1", at=2)
    assert not snapshot([switched, applied, veto], repo=repo, params={}).overlay
    assert arm_fp(switched, applied, veto) != pinned
    # so does a person's link of classes to a fix made outside the loop
    linked = rec("linked", {"targets": ["E-BUDGET"], "ref": "PR #9"}, actor="op-1", at=3)
    assert arm_fp(switched, applied, linked) != pinned
    assert arm_fp(switched, applied, veto, linked) not in {pinned, arm_fp(switched, applied, veto)}
    # and a level edit, as before
    level = rec("switched", {"auto_apply": AUTO_CONTEXT}, actor="op-1", at=4)
    assert arm_fp(switched, applied, level) != pinned


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

    def look(self, reading: Reading, arm: str) -> tuple[int, int]:
        """``arm``'s look as the server reads it, as ``(counted, misses)``."""
        with self.h.factory() as s:
            loaded = next(
                r for r in load_readings(s, pr.REPO_NAME) if r.reading_id == reading.reading_id
            )
        look = arm_reading(loaded, arm, list(self.h.worker.ledger.rows())).look
        return look.counted, look.misses

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
    # the container's user named, never the host's uid (a root CI container refuses it)
    monkeypatch.setenv("CRB_BUILDER__USER", "1000:1000")
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


def _w_before_reserve(
    rig: _WRig, monkeypatch: pytest.MonkeyPatch, act: Callable[[Run], None]
) -> None:
    """Run ``act`` on the run once, after the run's own stop check and just before the first
    commit's reserve transaction (the ``_reserver`` the worker built for it, wrapped)."""
    w = rig.h.worker
    real = w._reserver
    done: list[bool] = []

    def reserver(ctx: Any, *a: Any, **kw: Any) -> Any:
        inner = real(ctx, *a, **kw)

        def call(task: Any) -> Any:
            if not done:
                done.append(True)
                act(ctx.run)
            return inner(task)

        return call

    monkeypatch.setattr(w, "_reserver", reserver)


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
    present (no key is set or read), the campaign registered, then its four readings —
    each registered through ``POST /readings`` (reserved.v1, the record's body) unless its
    ``(repo, size)`` is in ``legacy``, which is written as a legacy reading a store
    registered before step 13 holds (:func:`_r_legacy`)."""
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
            if key in legacy:
                w.readings[key] = _r_legacy(w, body)
                assert w.readings[key].get("attempt_rule", "") == "", key
                continue
            r = w.send("POST", "/api/v1/readings", json=body)
            assert r.status_code == 201, (key, r.text)
            w.readings[key] = r.json()
            assert w.readings[key]["attempt_rule"] == ATTEMPT_RULE_RESERVED, key
        yield w


def _r_legacy(w: Wave3, body: Mapping[str, Any]) -> dict[str, Any]:
    """``body``'s reading under the legacy rule (``first_observed.v0``), as a store holds one
    registered before step 13 — ``POST /readings`` registers reserved.v1 only (DL-385): the
    core's ``register`` over every qualified commit of the cell, each its own change, in the
    deployment's posture class, and the ``reading.registered`` event the route writes on the
    repository's trace."""
    repo, cell = str(body["repo"]), dict(body["cell"])
    with w.env.factory() as s:
        tasks = list(
            s.execute(
                select(Task).where(
                    Task.repo == repo,
                    Task.size == cell["size"],
                    Task.capability_class == cell["capability_class"],
                    Task.language == cell["language"],
                )
            ).scalars()
        )
        existing = load_readings(s, repo)
        posture = str(body.get("posture_class") or "") or deployment_posture_class(
            w.env.settings, s.get(Repo, repo)
        )
    labels = {t.task_id: dict(dict(t.spec_json or {}).get("labels") or {}) for t in tasks}
    reading = register(
        repo=repo,
        cell=cell,
        hierarchy=list(body["hierarchy"]),
        pool=sorted(labels),
        apparatus=APPARATUS_VERSION,
        taxonomy=GLOBAL_CLASS_SET,
        posture_class=posture,
        checks_arm="off",
        actor="op-legacy",
        existing=existing,
        rule=str(body["rule"]),
        descriptive=[(str(a), int(n)) for a, n in body["descriptive"]],
        author_model=str(body["author_model"]),
        changes={c: str(lab.get("change_id") or c) for c, lab in labels.items()},
        hypothesis=str(body["hypothesis"]),
        smallest_effect=float(body["smallest_effect"]),
        campaign_id=str(body["campaign_id"]),
    )
    append_event(
        w.env.factory,
        trace_id=f"readings:{repo}",
        stage="system",
        action=READING_EVENT_ACTION,
        actor="op-legacy",
        repo=repo,
        payload=reading.to_dict(),
    )
    return reading.to_dict()


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
    "qualify_first": {"qualify_first": True},
}
_R_DEFAULT: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "pool": ({"pool": ""}, {"pool": "hard"}),
    "executor": ({"executor": ""}, {"executor": "docker"}),
    "timeout": ({"timeout": None}, {"timeout": 1}),
    "ladder": ({"ladder": ["r1"]}, {"ladder": ["claude_code:claude-sonnet-5"]}),
    # PW-7: a reading run halts at its first outage or environment row
    "outage_stop": ({"outage_stop": 1}, {"outage_stop": 3}),
    "env_stop": ({"env_stop": 1}, {"env_stop": 2}),
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


# --- an operator's lint switch never reshapes what a reading counts (P-796) ------------------


def _r_lint(w: Wave3, repo: str, lint: dict[str, Any]) -> None:
    """Store ``lint`` as ``repo``'s ``RepoConfig.lint`` (the operator's config edit)."""
    with w.env.factory() as s:
        row = s.get(Repo, repo)
        assert row is not None
        row.config_json = {**dict(row.config_json or {}), "lint": dict(lint)}
        s.commit()


def _w_loop_on(rig: _WRig) -> None:
    """Throw the repository's learning switch to context, as ``PUT /learn/switch`` does."""
    from crb.core.prevention import PreventionRecord
    from crb.server.prevention_state import EventsPreventionStore

    with rig.h.factory() as s:
        EventsPreventionStore(s, pr.REPO_NAME).append(
            PreventionRecord(
                "switched",
                pr.REPO_NAME,
                {"auto_apply": AUTO_CONTEXT},
                actor="op-1",
                on_behalf_of="op-1",
                reason="the loop on for A0+L",
                created="2026-10-12T00:00:00+00:00",
            )
        )
        s.commit()


def _w_a0l(rig: _WRig, reading: Reading, *tasks: str) -> Run:
    """``A0+L`` of ``tasks`` as the record files it — the ``A0`` body with no ``learning`` and
    no ``budget_profile`` — admitted under the campaign."""
    run = rig.enqueue(reading, *tasks, admit=False)
    with rig.h.factory() as s:
        stored = s.get(Run, run.id)
        assert stored is not None
        stored.params_json = {
            k: v
            for k, v in dict(stored.params_json or {}).items()
            if k not in ("learning", "budget_profile")
        }
        s.commit()
    append_event(
        rig.h.factory,
        trace_id=_W_CID,
        stage="system",
        action=CAMPAIGN_ADMITTED,
        payload={"campaign_id": _W_CID, "run_id": run.id},
    )
    return run


def _w_loop_pair(rig: _WRig, reading: Reading) -> Any:
    """``A0`` and ``A0+L`` of ``reading`` as the server reads them, paired."""
    with rig.h.factory() as s:
        loaded = next(
            r for r in load_readings(s, pr.REPO_NAME) if r.reading_id == reading.reading_id
        )
    rows = list(rig.h.worker.ledger.rows())
    return loop_pair(arm_reading(loaded, "A0", rows), arm_reading(loaded, "A0+L", rows))


def _w_format_step_in_force(rig: _WRig) -> None:
    """Throw the repository's learning switch to config and put the loop's ``format_step``
    switch (``checks.format_step = true``) in force — the ``applied`` record the core tick
    writes for one gofmt-only first attempt with the switch at config."""
    from crb.core.prevention import PreventionRecord
    from crb.server.prevention_state import EventsPreventionStore

    def rec(kind: str, payload: dict[str, Any], actor: str, i: int) -> PreventionRecord:
        return PreventionRecord(
            kind,
            pr.REPO_NAME,
            payload,
            actor=actor,
            on_behalf_of="op-1",
            reason="the loop's formatter switch",
            created=f"2026-10-12T00:00:{i:02d}+00:00",
        )

    applied = {
        "change_id": "fmt-1",
        "lever_id": "format_step",
        "family": "config",
        "level": "construction",
        "targets": ["format:gofmt"],
        "stratum": {"mode": "blind"},
        "key": "2.2|fake|m0|crb.prevention.sig.v1",
        "what": {"section": "checks", "key": "format_step", "value": True},
        "before": {"format:gofmt": {"k0": 1, "n0": 1, "decisive_n": 3}},
    }
    with rig.h.factory() as s:
        store = EventsPreventionStore(s, pr.REPO_NAME)
        store.append(rec("switched", {"auto_apply": AUTO_CONFIG}, "op-1", 0))
        store.append(rec("applied", applied, "loop", 1))
        s.commit()


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

    def settled_unrowed(self, reading: Reading) -> dict[str, int]:
        """The reading's ``settled_unrowed`` as ``GET /readings`` serves it
        (``served_reading``): the reading as ``load_readings`` fills it, over every row of
        the repository."""
        from crb.server.routes.readings import served_reading

        with self.h.factory() as s:
            loaded = next(
                r for r in load_readings(s, pr.REPO_NAME) if r.reading_id == reading.reading_id
            )
            rows = list(self.h.worker.ledger.rows(repo=pr.REPO_NAME))
            return dict(served_reading(s, evaluate(loaded, rows))["settled_unrowed"])


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
    # the container's user named, never the host's uid (a root CI container refuses it)
    monkeypatch.setenv("CRB_BUILDER__USER", "1000:1000")
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
    ``no_frozen_backlog``, the next one), and a factory run naming the replayed ceiling
    reading is still a validation error. At claim the same off-cell run, inserted past the
    route, is refused ``reading_run_fields`` naming ``model`` alone — nothing built, nothing
    reserved (before, the claim named ``kind`` and the factory's own params too). The
    legacy forward rule is pinned unchanged: a ticket's first factory attempt is any
    rung-``r1`` factory row on the repository graded after registration and never
    imported."""
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
        add_tasks(env.factory, qualify=True)
        r = register_via_api(env)
        assert r.status_code == 201, r.text
        ceiling = r.json()
        pool = ceiling["pool"][:20]
        add_rows(env.factory, pool, arm="S3", reading=ceiling)
        add_rows(env.factory, pool[:3], arm=S1, clean=False, reading=ceiling)
        add_rows(env.factory, pool[3:], arm=S1, reading=ceiling)
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


def test_p792_factory_reserve_halts_off_the_readings_checks_arm(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """V1-CA-3 (round 6), the factory beside the replay's halt above: a factory run filed
    under a reserved.v1 forward reading hands the reservation hook the arm its own checks
    resolved (``checks.arm``), and the hook halts ``reading_checks_arm_mismatch`` when that
    is not the arm the reading froze. No test held it: handing the hook the reading's own arm
    instead reserved a ticket whose row, on another arm, the reading could never count. With
    the loop's ``format_step`` change in force (the team's block silent) the run resolves
    ``fmt`` against the reading's ``off``: nothing is reserved, the build is a
    ``build.not_reserved`` naming the item, the trial and the halt, and builds on (the hook
    never blocks delivery), its ``r1`` row on ``fmt`` with no reservation, and the ticket
    stays pending. On SQLite and PostgreSQL (R6V2-6)."""
    rig = _f_rig(tmp_path, monkeypatch, store=backend)
    reading = rig.register()
    assert reading.checks_arm == "off"
    rig.enrol()
    format_step_in_force(rig.h.factory, pr.REPO_NAME)
    run = rig.enqueue(reading)
    done = rig.h.run_one()
    assert done.status == STATUS_SUCCEEDED, (done.status, done.error)
    assert rig.reservations(reading) == []
    (event,) = rig.events(run.id, "build.not_reserved")
    assert {k: dict(event.payload or {}).get(k) for k in ("item", "trial")} == {
        "item": "I-1",
        "trial": "r1",
    }
    assert HALT_CHECKS_ARM_MISMATCH in event.error_message
    assert "build.start" in rig.actions(run.id)
    assert [
        (r.trial, r.checks_arm, r.labels.get(LABEL_RESERVATION, "")) for r in rig.rows(run.id)
    ] == [("r1", "fmt", "")]
    assert rig.verdicts(reading) == {"I-1": (None, "pending")}


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


@pytest.mark.parametrize("graded", [True, False], ids=["rowed", "unrowed"])
def test_p792_forward_reserved_ticket_is_placed_by_its_item(
    backend: Backend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, graded: bool
) -> None:
    """F8 on a forward reading: the reservation names the ticket (``I-1``) while its row's
    ``task_id`` is the build's own id, so ``unplaced_attempts`` places a factory row against
    its reservation by the row's ``item_id`` label (``reservation_unit``, the key the worker
    stamps the row by). A reserved ticket built and rowed is no unplaced attempt: the reading
    serves ``settled_unrowed`` 0 and the campaign the run is admitted under is charged its
    row alone and admits on. One whose grade raised after the reservation (no row) is one, at
    its hold: served as 1, and the campaign stops ``unplaced_spend``. On SQLite and
    PostgreSQL. Before, every rowed reserved ticket was counted settled with no row — the
    reading served 1 and its campaign stopped, charged the hold on top of the row."""
    cid = "cmp_" + "f" * 24
    rig = _f_rig(tmp_path, monkeypatch, store=backend)
    real = rig.h.worker._unit_reserver
    monkeypatch.setattr(
        rig.h.worker, "_unit_reserver", lambda *a, **kw: real(*a, **{**kw, "hold_usd": 0.4})
    )
    if not graded:

        def broken(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError("the grader fell over")

        monkeypatch.setattr("crb.factory.build.grade", broken)
    reading = rig.register()
    rig.enrol()
    run = rig.enqueue(reading)
    append_event(
        rig.h.factory,
        trace_id=cid,
        stage="system",
        action=CAMPAIGN_ADMITTED,
        payload={
            "campaign_id": cid,
            "run_id": run.id,
            "cap_usd": 10.0,
            "s1": False,
            "commits": 1,
            "headroom_usd": 5.0,
        },
    )
    done = rig.h.run_one()
    assert done.status == STATUS_SUCCEEDED, (done.status, done.error)
    (res,) = rig.reservations(reading)
    rows = [r for r in rig.rows(run.id) if r.trial == "r1"]
    with rig.h.factory() as s:
        unplaced = campaigns_mod.unplaced_attempts(s, [run.id])
        (member,) = campaigns_mod.members(s, cid)
    t = tally(54.0, [member])
    if graded:
        (row,) = rows
        assert (row.labels["item_id"], res.task_id) == ("I-1", "I-1") and row.task_id != "I-1"
        assert rig.verdicts(reading) == {"I-1": (True, "")}
        assert unplaced == [], unplaced
        assert rig.settled_unrowed(reading) == {"S2": 0}
        assert (member.unrowed, member.unrowed_usd) == (0, 0.0), member
        assert not t.stopped, t
    else:
        assert rows == []
        assert rig.verdicts(reading) == {"I-1": (False, "unobserved")}
        assert [(u.task_id, u.trial, u.cost_usd, u.reservation_event_id) for u in unplaced] == [
            ("I-1", "r1", 0.4, res.event_id)
        ]
        assert rig.settled_unrowed(reading) == {"S2": 1}
        assert (member.unrowed, member.unrowed_usd) == (1, 0.4), member
        assert t.unplaced_runs == (run.id,), t


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
        "outage_stop": 1,
        "env_stop": 1,
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
        # PW-7, the one rule for every reserved.v1 run (a factory run reads neither knob)
        ({"params": {**params, "outage_stop": 3}}, ["outage_stop"]),
        ({"params": {**params, "env_stop": 2}}, ["env_stop"]),
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
        add_tasks(env.factory, qualify=True)
        r = register_via_api(env)
        assert r.status_code == 201, r.text
        pool = r.json()["pool"][:20]
        add_rows(env.factory, pool, arm="S3", reading=r.json())
        add_rows(env.factory, pool[:3], arm=S1, clean=False, reading=r.json())
        add_rows(env.factory, pool[3:], arm=S1, reading=r.json())
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
