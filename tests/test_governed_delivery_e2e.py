"""One governed delivery, end to end: from sealed rows to a pull request, every gate on the chain.

The product's claim is that code reaches a customer's repository only through a chain of
gates, each recorded: the rows a reading counts, the reading, the cell's standard and its
sign-off, a ticket that carries what the standard needs, a test another model wrote, the
build, a review whose strength probe is required, and a delivery inside the run's spend cap.
This file walks that chain once on a fixture repository with fake models (no model is called,
nothing costs money), then removes each gate's condition in turn and shows the chain stops
with the gate's own code before any spend or push.

Navigation
----------
What it is:   The end-to-end governed-delivery test (``product.truth.219``).
What it does: Seeds a store (the API's own) with qualified tasks and sealed rows at apparatus
              2.4 on two context arms, a ``mutation.v2`` oracle and a passed controls report;
              registers a reading (``S3`` then ``S1@t1``) through ``POST /readings`` on the
              item's cell and the next larger one (the size rule reads both); reads the
              standard ``S1@t1`` through the store-bound readers
              (``crb.server.factory_standard``) and signs each cell through ``POST /signoffs``
              as a second person; runs the factory loop on a fixture repository — the item's
              ticket carries S1's structural slots, the test author ``t1`` is another model
              than the builder, the default probes (the mutation strength probe required)
              review the build — under a spend cap checked before the item, and delivers to a
              fake forge. Every step lands on the hash-chained ``events`` table, which
              ``GET /ledger/verify`` then walks. Then each gate's condition is removed.
How:          ``fixtures.server_seed.make_env`` (the API and its store) → ``fixtures.proven``
              (tasks, sealed rows with stored packs, readings, oracle and controls) →
              ``FactoryLoop`` with ``test_factory_loop``'s fake builder, test author and
              forge, and a ``DbEventSink`` into the same store.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (items 1, 2, 6 and 8),
              docs/adr/0025-routing-v2.md, docs/adr/0021-factory-review-before-delivery.md,
              docs/adr/0029-the-audit-trail-is-hash-chained.md,
              docs/adr/0030-a-run-keeps-its-spend-cap.md
Works with:   src/crb/factory/loop.py (the chain under test), src/crb/server/factory_standard.py
              (the gate's store-bound readers), src/crb/server/spend_cap.py (the cap asked
              before the item), tests/fixtures/proven.py (tasks, rows, oracle, controls),
              tests/test_factory_loop.py (the fake builder, test author and credentials)
Tested by:    this file
Touch when:   never for a new repository; a gate is added to the delivery chain (add its step
              and its refusal here); the look rule's first look changes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from crb.builders.base import Rung
from crb.core.checks import ARM_OFF
from crb.core.execution import LocalExecutor
from crb.core.ledger import GradeRow, JsonlLedger
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.version import APPARATUS_VERSION
from crb.factory import evidence as fe
from crb.factory import loop as fl
from crb.factory import readiness as rd
from crb.factory import review as rv
from crb.factory.backlog import KIND_CODE, BacklogItem
from crb.factory.standard import CellRef, Readers
from crb.observability.events import Emitter
from crb.server import factory_standard
from crb.server.posture_view import deployment_posture_class
from crb.server.spend_cap import Spend, SpendCap, item_reserve
from crb.store.events import DbEventSink
from crb.store.models import Repo
from fixtures import pyrepo as pr
from fixtures.proven import CELL, LATER, add_oracle_and_controls, add_rows, add_tasks
from fixtures.readings import SEALED
from fixtures.server_seed import (
    ALPHA,
    BUILDER,
    MODEL,
    PROVIDER,
    RUN_IDS,
    Env,
    login,
    make_env,
)
from test_factory_loop import TEST_POWER, TEST_POWER_SRC, FakeTestAuthor, MultiBuilder, _creds

#: The test author (``t1``) is a different model from the builder (``gpt-oss-120b``).
AUTHOR_MODEL = "t1"
S1 = f"S1@{AUTHOR_MODEL}"
#: The size rule reads the estimate's cell and the next larger one until the points-to-churn
#: agreement passes (ADR-0026 item 8): both cells are proven and signed.
CELL_XS = dict(CELL)
CELL_S = {**CELL, "size": "S"}
#: The look rule's first look (ADR-0026 item 2): 20 of 20.
FIRST_LOOK = 20
#: When this test's commits were authored — after every commit the seed holds, so a pool rule
#: of "authored since" takes this test's commits only.
AUTHORED = "2026-09-20T12:00:00+00:00"
#: The run's spend cap (ADR-0030), in USD — the fake builder costs 0.001 an attempt.
CAP_USD = 0.25


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path) as e:
        # the deployment grades in the sealed posture: only sealed rows license (ADR-0025)
        e.settings.sandbox.executor = "docker"
        yield e


def _prove(
    env: Env, cell: dict[str, str], *, s3: list[bool], s1: list[bool], prefix: str
) -> list[GradeRow]:
    """Qualified tasks of ``cell``, a reading registered through the API over them (``S3`` then
    ``S1@t1``), then one sealed first attempt per commit on each arm in the reading's seeded
    order — the first five from a run the operator queued (the two-person rule's second
    person), the rest from a worker — and the oracle and controls at 2.4. Returns the rows."""
    ids = add_tasks(env.factory, 40, prefix=prefix, cell=cell, authored=AUTHORED)
    login(env.client, "operator")
    r = env.post(
        "/readings",
        json={
            "repo": ALPHA,
            "cell": cell,
            "hierarchy": ["S3", S1],
            "posture_class": SEALED,
            "author_model": AUTHOR_MODEL,
            # the pool rule: every qualified commit of the cell authored since this date —
            # this test's own, never the seed's (whose rows a reading may not count)
            "since": AUTHORED,
        },
    )
    assert r.status_code == 201, r.text
    pool = list(r.json()["pool"])
    assert sorted(pool) == sorted(ids)
    rows: list[GradeRow] = []
    for arm, outcomes in (("S3", s3), (S1, s1)):
        for k, (commit, clean) in enumerate(zip(pool, outcomes, strict=False)):
            rows += add_rows(
                env.factory,
                [commit],
                arm=arm,
                cell=cell,
                clean=clean,
                run_id=RUN_IDS["succeeded"] if k < 5 else f"{prefix}-{arm}-{k // 4}",
                actor="worker-1",
            )
    add_oracle_and_controls(env.factory, pool[:FIRST_LOOK])
    return rows


def _sign(env: Env, cell: dict[str, str], rows: list[GradeRow]) -> dict[str, Any]:
    """A second person (the approver) signs the cell on its standard arm, naming a clean row
    of that arm the operator's run produced; returns the stored record."""
    row = next(r for r in rows if r.clean and r.context_arm == S1)
    login(env.client, "approver")
    r = env.post(
        "/signoffs",
        json={
            "repo": ALPHA,
            "cell": cell,
            "note": "read the reading, the packs and one accepted diff",
            "attestation": {
                "reviewed_row_hash": row.row_hash,
                "statement": "I read this diff and the reading's first look; S1@t1 is the "
                "cell's standard.",
            },
        },
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


def _readers(env: Env) -> Readers:
    """The entry gate's readers exactly as the worker binds them: the store's readings on the
    repository's own checks arm and the deployment's posture class."""
    with env.factory() as s:
        posture = deployment_posture_class(env.settings, s.get(Repo, ALPHA))
    assert posture == SEALED
    return factory_standard.bind_readers(
        env.factory, ALPHA, checks_arm=ARM_OFF, posture_class=posture
    )


def _routes(env: Env) -> Callable[[BacklogItem], dict[str, Any] | None]:
    """The capability map's decision per (class × size) cell, read ONCE from the API as the
    worker reads it (the pre-run map, each cell on its standard arm)."""
    login(env.client, "viewer")
    r = env.get("/capability-map", params={"repo": ALPHA, "by": "class,size", "arm": "standard"})
    assert r.status_code == 200, r.text
    cells = {f"{c['capability_class']}|{c['size']}": c for c in r.json()["cells"]}

    def lookup(item: BacklogItem) -> dict[str, Any] | None:
        c = cells.get(f"{item.capability_class}|{item.size_estimate}")
        return (
            None
            if c is None
            else {
                k: c.get(k)
                for k in (
                    "route",
                    "reason",
                    "reason_code",
                    "n",
                    "point",
                    "ci_low",
                    "false_q1",
                    "policy_version",
                    "apparatus_versions",
                )
            }
        )

    return lookup


def power_item(**kw: Any) -> BacklogItem:
    """The ticket: bug.fix, estimated XS, carrying ``S1``'s structural slots (the facts the
    test author reads); its value slot is the test author's to fill (test-first)."""
    base: dict[str, Any] = {
        "id": "E-1",
        "title": "Add power to calc",
        "kind": KIND_CODE,
        "description": "calc needs power(a, b).",
        "acceptance_criteria": ("power(2, 3) == 8",),
        "capability_class": "bug.fix",
        "size_estimate": "XS",
        "structural_facts": (
            "reproduction: `from calc import power` raises ImportError",
            "expected_behaviour: calc exposes power(a: int, b: int) -> int",
        ),
    }
    base.update(kw)
    return BacklogItem(**base)


class Forge:
    """The fake forge: records every push and pull request, and when each happened."""

    def __init__(self) -> None:
        self.pushes: list[dict[str, Any]] = []
        self.prs: list[dict[str, Any]] = []

    def push(self, repo: Any, **kw: Any) -> None:
        self.pushes.append(kw)

    def open_pr(self, **kw: Any) -> tuple[str, int]:
        self.prs.append(kw)
        return f"https://github.invalid/acme/calc/pull/{len(self.prs)}", len(self.prs)


def _loop(
    env: Env,
    pyrepo: pr.PyRepo,
    tmp_path: Path,
    *,
    readers: Readers,
    forge: Forge,
    **overrides: Any,
) -> tuple[fl.FactoryLoop, fl.FactorySpec, MultiBuilder, FakeTestAuthor]:
    builder = MultiBuilder(name=BUILDER, model=MODEL, provider=PROVIDER)
    author = FakeTestAuthor(
        name="author",
        model=AUTHOR_MODEL,
        provider="fake-provider",
        tests={"E-1": (TEST_POWER, TEST_POWER_SRC)},
    )
    kw: dict[str, Any] = {
        "config": pyrepo.config,
        "runner": PytestRunner(pyrepo.config),
        "executor": LocalExecutor(),
        "scratch": tmp_path / "scratch",
        "evidence_dir": tmp_path / "packs",
        "evidence": fe.FactoryEvidence(
            fe.JsonlFactoryStore(tmp_path / "evidence.jsonl"), actor="op", repo=ALPHA
        ),
        "ledger": JsonlLedger(tmp_path / "grades.jsonl"),
        "ladder": (Rung(BUILDER, MODEL, PROVIDER),),
        "builder_for": lambda r: builder,
        "reviewer": rv.MechanicalReviewer(),
        "probes": rv.default_probes(),  # the mutation strength probe is REQUIRED
        "test_author": author,
        "gap_ledger": rd.JsonlGapSignoffLedger(tmp_path / "gaps.jsonl"),
        "deliver": True,
        "creds": _creds(),
        "push_fn": forge.push,
        "open_pr_fn": forge.open_pr,
        "comment_pr_fn": lambda **kw: None,
        "target_default_branch": "main",
        "run_id": "e2e-run",
        "actor": "operator-queued",
        "route_decision_for": _routes(env),
        "readers": readers,
        "require_signed_cell": True,
    }
    kw.update(overrides)
    spec = fl.FactorySpec(**kw)
    sink = DbEventSink(env.factory)
    loop = fl.FactoryLoop(spec, pyrepo.repo, emitter=Emitter(sink, actor="op", repo=ALPHA))
    return loop, spec, builder, author


def _capped_stop(spec: fl.FactorySpec) -> Callable[[], bool]:
    """The worker's stop hook (F5b): before the item, the run's spend so far plus the item's
    reserve must fit the cap."""
    cap = SpendCap(CAP_USD)

    def stop() -> bool:
        spent = Spend.of_rows(list(spec.ledger.rows()))
        reserve, attempts = item_reserve([0.0], spent, max_rework=spec.max_rework)
        return cap.check(spent, reserve=reserve, unit="item", attempts=attempts) is not None

    return stop


def _proven_and_signed(env: Env) -> list[dict[str, Any]]:
    signed = []
    for cell, prefix in ((CELL_XS, "xs"), (CELL_S, "s")):
        rows = _prove(env, cell, s3=[True] * FIRST_LOOK, s1=[True] * FIRST_LOOK, prefix=prefix)
        signed.append(_sign(env, cell, rows))
    return signed


def _actions(env: Env) -> list[str]:
    with env.factory() as s:
        from sqlalchemy import select

        from crb.store.models import Event

        return [str(a) for a in s.execute(select(Event.action).order_by(Event.id)).scalars()]


# --- the chain, walked once --------------------------------------------------------------


def test_a_governed_delivery_passes_every_gate_in_order_on_the_chain(
    env: Env, pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    _proven_and_signed(env)
    # (1) the rows a reading counts: qualified, sealed, 2.4, one arm label each, the global
    # class set, one posture class and one checks arm
    with env.factory() as s:
        from crb.store.ledger import rows_in

        mine = [r for r in rows_in(s, ALPHA) if r.created == LATER]
    assert len(mine) == 4 * FIRST_LOOK
    assert {r.apparatus_version for r in mine} == {APPARATUS_VERSION}
    assert {r.context_arm for r in mine} == {"S3", S1}
    assert {r.taxonomy for r in mine} == {"global/classes@v1"}
    assert {r.labels["posture_class"] for r in mine} == {SEALED}
    assert {r.checks_arm for r in mine} == {ARM_OFF}
    login(env.client, "viewer")
    cmap = env.get(
        "/capability-map", params={"repo": ALPHA, "by": "class,size", "arm": "standard"}
    ).json()
    assert cmap["controls"]["state"] == "passed"
    cell = next(c for c in cmap["cells"] if (c["capability_class"], c["size"]) == ("bug.fix", "XS"))
    assert cell["oracle_strength_mean"] >= 0.8 and cell["n_tasks"] == FIRST_LOOK
    # (2) the registered reading: S3 then S1@t1, both delivering at the first look
    assert cell["context_arm"] == S1 and cell["standard"]["standard"] == S1
    # the sign-off is bound to that arm, class-set version and reading
    with env.factory() as s:
        from crb.server.routes.signoffs import load_signoff_records

        records = [r for r in load_signoff_records(s, ALPHA) if r.size == "XS"]
    assert [(r.context_arm, r.taxonomy, r.reading_id) for r in records] == [
        (S1, "global/classes@v1", cell["reading_id"])
    ]
    readers = _readers(env)
    # (1)-(3): the cell's standard is S1@t1, proven by the reading, signed on that reading
    std = readers.standard_for(CellRef("bug.fix", "XS"))
    assert std is not None and std.arm == S1 and std.signed and not std.ceiling
    arms = {a.arm: a for a in readers.arm_readings(CellRef("bug.fix", "XS"))}
    assert (arms["S3"].n, arms["S3"].clean) == (FIRST_LOOK, FIRST_LOOK)
    assert (arms[S1].n, arms[S1].clean) == (FIRST_LOOK, FIRST_LOOK)
    route = _routes(env)(power_item())
    assert route is not None and route["route"] == "deliver", route
    forge = Forge()
    loop, spec, builder, author = _loop(env, pyrepo, tmp_path, readers=readers, forge=forge)
    # the run's spend cap is asked before the item, as the worker asks it (F5b)
    assert not _capped_stop(spec)()
    out = loop.run_item(power_item())
    assert out.status == fl.STATUS_ACCEPTED, out.error
    # (5) a test authored by another model, stamped with its provider
    assert author.calls == ["E-1"]
    assert out.proof is not None and out.proof.author == f"author:{AUTHOR_MODEL}"
    (row,) = list(spec.ledger.rows())
    assert row.labels["context_arm"] == S1 and row.labels["ctx_author"] == "fake-provider"
    assert row.labels["taxonomy"] == "global/classes@v1"
    assert (row.builder, row.model) == (BUILDER, MODEL) and AUTHOR_MODEL != MODEL
    # (6)-(7) the build, and a review whose REQUIRED strength probe accepted it
    assert builder.calls == 1
    verdict = out.final_verdict
    assert verdict is not None and verdict.accepted
    strength = next(p for p in verdict.probes if p.name == rv.MutationStrengthProbe.name)
    assert strength.required and strength.passed
    # (8) delivered to the fake forge only after the accepted review, within the cap
    assert out.delivery is not None and len(forge.pushes) == 1 and len(forge.prs) == 1
    assert Spend.of_rows(list(spec.ledger.rows())).spent <= CAP_USD
    kinds = [e.kind for e in spec.evidence.events_for("E-1")]
    assert kinds.index(fe.EV_VERDICT) < kinds.index(fe.EV_DELIVERY)
    # every step is on the hash-chained audit trail, and it verifies
    actions = _actions(env)
    for step in (
        "reading.registered",
        "oracle.score",
        "controls.report",
        "route.decided",
        "red.proved",
        "build.done",
        "review.verdict",
        "delivery.opened",
    ):
        assert step in actions, (step, sorted(set(actions)))
    assert actions.index("review.verdict") < actions.index("delivery.opened")
    login(env.client, "operator")
    verify = env.get("/ledger/verify", params={"full": "true"}).json()
    assert verify["ok"] and verify["events"]["chain_ok"] and verify["signoffs"]["chain_ok"]
    assert APPARATUS_VERSION == "2.4" and row.apparatus_version == APPARATUS_VERSION


# --- each gate's condition removed, in turn ------------------------------------------------


def _refused(
    env: Env,
    pyrepo: pr.PyRepo,
    tmp_path: Path,
    code: str,
    *,
    item: BacklogItem | None = None,
    **overrides: Any,
) -> tuple[fl.ItemOutcome, Forge, MultiBuilder]:
    forge = Forge()
    loop, _spec, builder, author = _loop(
        env, pyrepo, tmp_path, readers=_readers(env), forge=forge, **overrides
    )
    out = loop.run_item(item or power_item())
    assert out.status == code, (out.status, out.error)
    assert builder.calls == 0 and author.calls == [], "spent before the gate"
    assert not forge.pushes and not forge.prs, "pushed before the gate"
    return out, forge, builder


def test_no_registered_reading_stops_no_proven_standard(
    env: Env, pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    ids = add_tasks(env.factory, 40, prefix="bare", cell=CELL_XS)
    add_rows(env.factory, ids[:FIRST_LOOK], arm="S3", cell=CELL_XS, actor="worker-1")
    add_rows(env.factory, ids[:FIRST_LOOK], arm=S1, cell=CELL_XS, actor="worker-1")
    _refused(env, pyrepo, tmp_path, fl.STATUS_NO_PROVEN_STANDARD)


def test_s1_rows_with_no_s3_reading_prove_no_standard(
    env: Env, pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    for cell, prefix in ((CELL_XS, "xs"), (CELL_S, "s")):
        _prove(env, cell, s3=[], s1=[True] * FIRST_LOOK, prefix=prefix)
    _refused(env, pyrepo, tmp_path, fl.STATUS_NO_PROVEN_STANDARD)


def test_a_proven_but_unsigned_standard_stops_unsigned_cell(
    env: Env, pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    for cell, prefix in ((CELL_XS, "xs"), (CELL_S, "s")):
        _prove(env, cell, s3=[True] * FIRST_LOOK, s1=[True] * FIRST_LOOK, prefix=prefix)
    _refused(env, pyrepo, tmp_path, fl.STATUS_UNSIGNED_CELL)


def test_deliver_override_never_lifts_a_missing_standard(
    env: Env, pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """ADR-0026 item 8: the override lifts the sign-off clause and nothing else — a cell with
    no standard stops as it would without one, and nothing is recorded as lifted."""
    _refused(
        env, pyrepo, tmp_path, fl.STATUS_NO_PROVEN_STANDARD, deliver_override_by="approver:ada"
    )
    assert "delivery.override" not in _actions(env)


def test_an_s3_ceiling_alone_stops_no_proven_standard(
    env: Env, pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    misses = [True] * 17 + [False] * 3
    for cell, prefix in ((CELL_XS, "xs"), (CELL_S, "s")):
        _prove(env, cell, s3=[True] * FIRST_LOOK, s1=misses, prefix=prefix)
    std = _readers(env).standard_for(CellRef("bug.fix", "XS"))
    assert std is not None and std.ceiling and std.arm == "S3"
    _refused(env, pyrepo, tmp_path, fl.STATUS_NO_PROVEN_STANDARD)


def test_a_ticket_without_the_standards_slots_stops_needs_context(
    env: Env, pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    _proven_and_signed(env)
    bare = power_item(structural_facts=("expected_behaviour: calc exposes power(a, b)",))
    _refused(env, pyrepo, tmp_path, fl.STATUS_NEEDS_CONTEXT, item=bare)


def test_no_standard_with_delivery_off_still_stops_before_any_spend(
    env: Env, pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    _refused(env, pyrepo, tmp_path, fl.STATUS_NO_PROVEN_STANDARD, deliver=False)


def test_a_calibration_build_is_built_and_never_delivers(
    env: Env, pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    forge = Forge()
    loop, spec, builder, _author = _loop(env, pyrepo, tmp_path, readers=_readers(env), forge=forge)
    spec.evidence.record_calibration("E-1", approver="approver:ada", reason="first reading")
    out = loop.run_item(power_item())
    assert out.status == fl.STATUS_CALIBRATION_BUILD, out.error
    assert builder.calls >= 1 and out.delivery is None
    assert not forge.pushes and not forge.prs
    refused = spec.evidence.events_for("E-1", fe.EV_DELIVERY_REFUSED)
    assert refused and refused[-1].payload["reason_code"] == "calibration_build"
