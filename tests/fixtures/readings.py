"""Test helpers for registered readings (ADR-0026 items 2 to 6): sealed 2.4 rows, a reading.

Navigation
----------
What it is:   Builders for the rows and readings the routing.v2 tests read: a row of apparatus
              2.4 graded in the sealed posture on one full cell, and a reading registered over
              a pool of commits.
What it does: ``sealed_row`` stamps the posture class ``docker/copy/sealed``, the builder's
              sealed container, rung ``r1``, a context arm, the class-set version and a
              change id, with a ``created`` time after the registration; ``register_reading``
              registers a hierarchy over a pool at a fixed time, under a campaign when one is
              named, and under any other ``register`` option given (the reserved.v1 attempt
              rule); ``commits`` makes shas; ``qualify_pool`` writes one qualification record
              per task in a posture through the store's writer — what a reserved.v1 pool is
              read from and pinned to (P-797); ``reserve_for`` writes the ``reading.reserved``
              event the worker writes before a reserved attempt's r1 build (P-792), over the
              ``TEST_DEPLOYMENT`` half and ``arm_half_for``'s arm half, and returns the
              ``reservation``, ``treatment`` and ``claim`` labels the attempt's row carries;
              ``format_step_in_force`` puts the loop's ``format_step`` change in force on a
              repository's chain (the overlay a registration refuses, RT2B-2).
How:          Thin wrappers over ``tests.fixtures.posture.posture_row``,
              ``crb.core.reading.register``, ``crb.store.qualifications.append`` and
              ``crb.store.events.append_event_checked`` (the worker's ``fingerprint`` and
              ``treatment_digest`` over the two halves); ``EventsPreventionStore.append`` (the
              loop's chain).
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0026-the-context-standard.md, docs/adr/0025-routing-v2.md
Works with:   src/crb/core/reading.py (``register`` — the readings built here),
              src/crb/core/ledger.py (the sealed 2.4 rows the ledger admits),
              tests/fixtures/posture.py (``posture_row`` — the labels a 2.4 row carries),
              src/crb/store/qualifications.py (``append`` — the records ``qualify_pool`` writes),
              src/crb/server/worker.py (``fingerprint``, ``treatment_digest`` — the
              reservation's pins), src/crb/store/events.py (``append_event_checked``)
Tested by:    tests/test_reading.py, tests/test_routing_v2.py, tests/test_signoff_v5.py,
              tests/test_server_readings.py, tests/test_p792_pool.py,
              tests/test_wave3_registration_rehearsal.py, tests/test_class_set_hooks.py
Touch when:   never for a new repository; the sealed posture's labels or the reading's shape change.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from crb.core.capability import ReadingBook
from crb.core.context_arm import REPLAY_MODE, parse_arm
from crb.core.evidence import canonical_json, sha256_text
from crb.core.ledger import GradeRow
from crb.core.qualify import STATE_QUALIFIED, Qualification
from crb.core.reading import (
    LABEL_CLAIM,
    LABEL_RESERVATION,
    LABEL_TREATMENT,
    READING_RESERVED_ACTION,
    RULE_LOOK_V1,
    Reading,
    register,
)
from crb.core.routing import ControlsVerdict
from crb.core.taxonomy import GLOBAL_CLASS_SET
from crb.core.version import APPARATUS_VERSION
from crb.server.worker import fingerprint, treatment_digest
from crb.store import qualifications as store_q
from crb.store.events import append_event_checked
from crb.store.models import Event, Task
from fixtures.posture import posture_row

REPO = "cobra"
SEALED = "docker/copy/sealed"
REGISTERED_AT = "2026-09-27T10:00:00+00:00"
AFTER = "2026-09-27T11:00:00+00:00"
BEFORE = "2026-09-27T09:00:00+00:00"
CELL = {
    "process_step": "replay",
    "capability_class": "bug.fix",
    "size": "XS",
    "language": "go",
    "builder": "claude_code",
    "model": "claude-sonnet-5",
    "provider": "anthropic",
}
AUTHOR = "claude-opus-5"
S1 = f"S1@{AUTHOR}"
#: What a registration through the API states before its first attempt (P-787): the
#: hypothesis and the smallest effect that would matter — both required by ``POST /readings``.
HYPOTHESIS = "the leaner arm delivers what the richer arm does on this cell"
SMALLEST_EFFECT = 0.1
QUESTION: dict[str, Any] = {"hypothesis": HYPOTHESIS, "smallest_effect": SMALLEST_EFFECT}
#: A sealed deployment (P-789): the sandbox and the builder both run on docker — what
#: ``POST /readings`` needs for a replayed arm. ``make_env(tmp_path, **SEALED_SETTINGS)``.
SEALED_SETTINGS: dict[str, Any] = {
    "sandbox": {"executor": "docker"},
    "builder": {"executor": "docker", "image": "crb-builder:test"},
}


#: The posture ``qualify_pool`` records a pool in unless a test names another.
POSTURE_ID = "pst_" + "f" * 24


def qualify_pool(
    factory: sessionmaker[Session],
    repo: str,
    task_ids: Iterable[str],
    *,
    posture_class: str = SEALED,
    posture_id: str = POSTURE_ID,
    state: str = STATE_QUALIFIED,
    code: str = "",
    salt: str = "",
) -> dict[str, str]:
    """Write one qualification record per task of ``repo`` in ``posture_id`` (a
    ``posture_class`` posture) through the store's writer, and return task id → record id:
    what a reserved.v1 registration reads its pool from and pins it to (P-797). A record of
    another ``state`` names its refusal ``code``. Record ids are stable for the arguments (two
    stores qualified alike pin alike); ``salt`` tells a second record of the same task apart."""
    out: dict[str, str] = {}
    with factory() as s:
        for task_id in task_ids:
            key = "\0".join((repo, task_id, posture_id, state, code, salt))
            q = store_q.append(
                s,
                Qualification(
                    qualification_id=hashlib.sha256(key.encode()).hexdigest()[:32],
                    repo=repo,
                    task_id=task_id,
                    posture_id=posture_id,
                    posture={
                        "posture_class": posture_class,
                        "executor": "docker",
                        "image_ref": "crb-sandbox:fixture",
                    },
                    state=state,
                    code=code,
                    gold={"clean": True, "lint": None},
                ),
            )
            out[task_id] = q.qualification_id
    return out


#: The fixed deployment half ``reserve_for`` pins a reservation's treatment to: the shape
#: ``crb.server.worker.deployment_projection`` writes, for a sealed deployment (the builder
#: and the sandbox on docker) on one r1 rung — plain JSON, no secret.
TEST_DEPLOYMENT: dict[str, Any] = {
    "rung": {
        "builder": "claude_code",
        "model": "claude-sonnet-5",
        "provider": "anthropic",
        "config": {},
    },
    "builder_overrides": {},
    "container": {"image": "crb-builder:test", "network": "none", "tmp_size": "1g"},
    "executor": "docker",
    "timeout": 1800,
    "budget": {"max_turns": 30, "max_tool_calls": 30},
    "preflight": None,
    "escalation": "measured",
    "apparatus_version": APPARATUS_VERSION,
    "posture_class": SEALED,
    "repo_config": "r" * 64,
    "s1_author": "",
}


def arm_half_for(arm: str, *, budget_profile: str = "default") -> dict[str, Any]:
    """The arm half ``reserve_for`` pins: the shape ``crb.server.worker.arm_projection``
    writes — ``{arm, learn}``, for a loop arm a person's acts on the chain (none here), and
    for a non-loop arm the overlay, the budget profile and the r1 budget."""
    out: dict[str, Any] = {"arm": arm, "learn": "off"}
    if parse_arm(arm).loop:
        return {**out, "learn": "auto", "person": ""}
    return {
        **out,
        "overlay": "",
        "budget_profile": budget_profile,
        "budget": {"max_turns": 30, "max_tool_calls": 30},
    }


def reserve_for(
    factory: sessionmaker[Session],
    *,
    reading_id: str,
    arm: str,
    task_id: str,
    run_id: str,
    repo: str = REPO,
    campaign_id: str = "",
    claim: int = 0,
    hold_usd: float | None = 0.5,
    worker_id: str = "worker-test",
    deployment: Mapping[str, Any] | None = None,
    arm_body: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Reserve ``task_id`` on ``arm`` of the reserved.v1 reading ``reading_id`` for
    ``run_id`` at ``claim``, as the worker does before the attempt's r1 build (P-792): one
    ``reading.reserved`` event on the reading's trace (``step_id`` the arm, ``task_id`` the
    commit, stage ``system``) through ``append_event_checked``, its payload the worker's —
    ``v``, the reading, campaign, run, arm, trial ``r1``, worker, claim, the task spec's
    digest, ``hold_usd``, both treatment halves (``TEST_DEPLOYMENT`` and ``arm_half_for``
    unless given), their fingerprints, the treatment digest and ``pinned_by`` (the event
    that pinned the deployment half: the campaign's first reservation on the repository, or
    ``self``). Returns the labels the attempt's row carries: ``{reservation, treatment,
    claim}`` — merge them into ``sealed_row(..., labels=...)``."""
    deployment_body = dict(deployment if deployment is not None else TEST_DEPLOYMENT)
    arm_half = dict(arm_body if arm_body is not None else arm_half_for(arm))
    deployment_fp, arm_fp = fingerprint(deployment_body), fingerprint(arm_half)
    treatment = treatment_digest(deployment_fp, arm_fp)

    def build(s: Session) -> dict[str, Any]:
        task = s.get(Task, (repo, task_id))
        pinned_by = next(
            (
                ev.event_id
                for ev in s.execute(
                    select(Event)
                    .where(Event.action == READING_RESERVED_ACTION, Event.repo == repo)
                    .order_by(Event.id)
                ).scalars()
                if str((ev.payload_json or {}).get("campaign_id") or "") == campaign_id
                and (campaign_id or ev.trace_id == reading_id)
            ),
            "self",
        )
        return {
            "v": 1,
            "reading_id": reading_id,
            "campaign_id": campaign_id,
            "run_id": run_id,
            "arm": arm,
            "trial": "r1",
            "worker_id": worker_id,
            "claim": claim,
            "task_spec_sha256": sha256_text(
                canonical_json(dict(task.spec_json or {}) if task is not None else {})
            ),
            "hold_usd": hold_usd,
            "deployment_fp": deployment_fp,
            "arm_fp": arm_fp,
            "treatment": treatment,
            "treatment_body": {"deployment": deployment_body, "arm": arm_half},
            "pinned_by": pinned_by,
        }

    ev = append_event_checked(
        factory,
        trace_id=reading_id,
        stage="system",
        action=READING_RESERVED_ACTION,
        build=build,
        actor=worker_id,
        repo=repo,
        task_id=task_id,
        step_id=arm,
    )
    return {LABEL_RESERVATION: ev.event_id, LABEL_TREATMENT: treatment, LABEL_CLAIM: str(claim)}


def format_step_in_force(factory: sessionmaker[Session], repo: str) -> None:
    """Throw ``repo``'s learning switch to config and put the prevention loop's ``format_step``
    change (``checks.format_step = true``) in force — the ``switched`` and ``applied`` records
    the core tick's chain holds after one gofmt-only first attempt with the switch at config.
    With the repository's own ``checks`` block silent on the key, a run that learns resolves
    ``fmt`` while the block's own arm stays ``off`` (RT2B-2)."""
    from crb.core.prevention import AUTO_CONFIG, PreventionRecord
    from crb.server.prevention_state import EventsPreventionStore

    def rec(kind: str, payload: dict[str, Any], actor: str, i: int) -> PreventionRecord:
        return PreventionRecord(
            kind,
            repo,
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
    with factory() as s:
        store = EventsPreventionStore(s, repo)
        store.append(rec("switched", {"auto_apply": AUTO_CONFIG}, "op-1", 0))
        store.append(rec("applied", applied, "loop", 1))
        s.commit()


def commits(n: int, prefix: str = "c") -> list[str]:
    """``n`` distinct 40-hex shas, stable for a prefix."""
    return [hashlib.sha1(f"{prefix}{i}".encode()).hexdigest() for i in range(n)]


def sealed_row(
    commit: str,
    *,
    clean: bool = True,
    arm: str = "S3",
    created: str = AFTER,
    trial: str = "r1",
    change: str = "",
    posture_class: str = SEALED,
    builder_executor: str = "docker",
    error: str = "",
    labels: dict[str, str] | None = None,
    repo: str = REPO,
    cell: dict[str, str] | None = None,
    **kw: Any,
) -> GradeRow:
    """A row of apparatus 2.4 on :data:`CELL`, graded in the sealed posture by default."""
    fields: dict[str, Any] = {
        "repo": repo,
        "task_id": commit,
        "clean": clean,
        "tests_unmodified": True,
        "target_green": clean and not error,
        "no_new_failures": True,
        "source_changed": True,
        "repo_lint_clean": None,
        "evidence_pack_hash": "h" * 64 if clean else "",
        "apparatus_version": "2.4",
        "created": created,
        "trial": trial,
        "error": error,
        # the mode a replay writes the arm in — the writer's own table (P-338)
        "mode": REPLAY_MODE.get(parse_arm(arm).base, "sighted"),
        **(cell or CELL),
        **kw,
    }
    if error:
        fields["target_green"] = None
        fields["no_new_failures"] = None
        fields["source_changed"] = None
    return posture_row(
        **fields,
        labels={
            "posture_class": posture_class,
            "builder_executor": builder_executor,
            "context_arm": arm,
            "taxonomy": GLOBAL_CLASS_SET,
            "change_id": change or f"change-{commit}",
            **(labels or {}),
        },
    )


def rows_for(
    outcomes: Sequence[bool | None], pool: Sequence[str], *, arm: str = "S3", **kw: Any
) -> list[GradeRow]:
    """One first attempt per pool commit, in pool order: ``True`` clean, ``False`` a miss,
    ``None`` no row yet (pending)."""
    return [
        sealed_row(c, clean=o, arm=arm, **kw)
        for c, o in zip(pool, outcomes, strict=False)
        if o is not None
    ]


def register_reading(
    pool: Iterable[str],
    *,
    hierarchy: Sequence[str] = ("S3", S1),
    rule: str = RULE_LOOK_V1,
    existing: Iterable[Reading] = (),
    rows: Iterable[GradeRow] = (),
    descriptive: Sequence[tuple[str, int]] = (),
    now: str = REGISTERED_AT,
    budget: float | None = None,
    changes: dict[str, str] | None = None,
    repo: str = REPO,
    cell: dict[str, str] | None = None,
    campaign_id: str = "",
    **kw: Any,
) -> Reading:
    """A reading of :data:`CELL` on :data:`REPO`, registered at :data:`REGISTERED_AT` —
    under ``campaign_id`` when one is named (DL-382); ``kw`` goes to ``register`` as given
    (``attempt_rule``, ``budget_profile`` and ``max_reruns`` for a reserved.v1 reading)."""
    return register(
        repo=repo,
        cell=cell or CELL,
        hierarchy=hierarchy,
        pool=list(pool),
        apparatus="2.4",
        taxonomy=GLOBAL_CLASS_SET,
        posture_class=SEALED,
        checks_arm="off",
        actor="op-1",
        existing=existing,
        rows=rows,
        rule=rule,
        descriptive=descriptive,
        author_model=AUTHOR if any(a.startswith("S1@") for a in hierarchy) else "",
        now=now,
        budget=budget,
        changes=changes,
        campaign_id=campaign_id,
        **kw,
    )


# --- a proven world for any rows (routing.v2 for tests of what reads the map) ---------------

#: A complete, passing controls report at apparatus 2.4.
LIVE_PASSED = ControlsVerdict(
    passed=True, constructible=56, total=56, escapes=0, run_id="c" * 32, apparatus_version="2.4"
)


def live_labels(task_id: str, *, arm: str = S1) -> dict[str, Any]:
    """The ``GradeRow`` keyword arguments that make a measured row of 2.4 one a reading counts:
    sealed, rung ``r1``, graded after :data:`REGISTERED_AT`, on ``arm``, its own change."""
    return {
        "created": AFTER,
        "trial": "r1",
        "labels": {
            "posture_class": SEALED,
            "builder_executor": "docker",
            "context_arm": arm,
            "taxonomy": GLOBAL_CLASS_SET,
            "change_id": f"change-{task_id}",
        },
    }


def book_for(rows: Sequence[GradeRow], *, arm: str = S1) -> ReadingBook:
    """One reading per full cell of the stamped 2.4 rows, registered at :data:`REGISTERED_AT`
    over the cell's commits, with ``arm`` alone in its hierarchy."""
    groups: dict[tuple[str, Any], list[str]] = {}
    for r in rows:
        if r.context_arm == arm and r.apparatus_version == "2.4":
            groups.setdefault((r.repo, r.cell), []).append(r.task_id)
    readings = [
        register(
            repo=repo,
            cell=cell.to_dict(),
            hierarchy=(arm,),
            pool=list(dict.fromkeys(ids)),
            apparatus="2.4",
            taxonomy=GLOBAL_CLASS_SET,
            posture_class=SEALED,
            checks_arm="off",
            actor="op-1",
            author_model=parse_arm(arm).author,
            now=REGISTERED_AT,
        )
        for (repo, cell), ids in groups.items()
    ]
    return ReadingBook.evaluate(readings, rows)


def world_for(
    rows: Sequence[GradeRow], *, oracle: float | None = 0.9, controls: ControlsVerdict | None = None
) -> dict[str, Any]:
    """The readings, per-task oracle and controls a proven cell of ``rows`` is routed under."""
    return {
        "readings": book_for(rows),
        "oracle_by_task": {} if oracle is None else {r.task_id: oracle for r in rows},
        "controls": controls or LIVE_PASSED,
    }
