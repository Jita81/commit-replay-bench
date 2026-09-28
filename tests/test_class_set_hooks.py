"""The class set where it is used: intake stamps a ticket, replay stamps a row, the gate refuses.

Navigation
----------
What it is:   Tests of the four hooks an organisation's class set reaches (ADR-0026 item 9):
              the intake's draft stamper, the replay's row stamp, the factory entry gate's
              readers and ``POST /runs``.
What it does: Pins that ONE rule classifies both sides — a ticket at intake and a commit at
              replay land in the same class for the same words; that the intake stamps a ticket
              the routing version classifies with ``taxonomy``, ``org_class`` and its global
              parent, counts a person's ``crb:class=`` override, and passes a ticket through
              untouched while no version routes; that the entry gate reads the organisation
              class's own cell, never the global one, and licenses nothing for a version that
              does not route; that a revoked version, and a signed one whose report fails, route
              nothing on the served readers (``readers_in``) and at the intake though a reading
              of the class and its rows exist; that a re-classified draft takes its new parent's
              kind; that a replay row is stamped with the run's class-set version inside its
              hash; and that a run is refused a version that does not route.
How:          The fixture organisation (``tests/fixtures/class_sets.py``) on the seeded app for
              the store-bound hooks; the intake's own poll over a fake tracker; readers built
              over a registered reading and sealed rows; no model, no docker.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (item 9)
Works with:   src/crb/server/class_set_state.py (the stamper and the verdict),
              src/crb/server/intake.py (the poll that calls the stamper),
              src/crb/server/factory_standard.py (the gate's readers), src/crb/core/run.py and
              src/crb/core/ledger.py (the replay row's stamp), src/crb/server/routes/runs.py
              (the run refused a version that does not route)
Tested by:    this file
Touch when:   never for a new repository; a place that reads a class set is added.
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select

from crb.core import class_sets as cs
from crb.core.grade import Belts
from crb.core.ledger import GradeRow
from crb.core.reading import register
from crb.core.run import RunSpec, row_from
from crb.core.spec import TaskSpec
from crb.factory.standard import CellRef, Readers, Standard, gate_for
from crb.intake import client as c
from crb.server import class_set_state
from crb.server import intake as sv
from crb.server.factory_standard import readers_over
from crb.server.factory_state import FactoryHome
from crb.server.routes.runs import new_run
from crb.server.schemas import RunCreateRequest
from crb.store.models import Event
from fixtures.class_sets import add_commits, routing_version, version
from fixtures.intake import FakeTracker
from fixtures.posture import posture_result
from fixtures.readings import CELL, REGISTERED_AT, SEALED, commits, sealed_row
from fixtures.server_seed import (
    ALPHA,
    BUILDER,
    MODEL,
    PROVIDER,
    Env,
    envelope,
    login,
    logout,
    make_env,
)

V1 = "acme/classes@v1"
READY_AC = (
    "reproduction: read a document whose last line is a comment",
    "expected_behaviour: the token before the comment is kept",
    "exact_value: tokens == ['a', 'b']",
)


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path, role="operator") as e:
        add_commits(e.factory)
        yield e


def _ticket(**kw: Any) -> c.Ticket:
    base: dict[str, Any] = {
        "key": "4711",
        "title": "The parser drops a token after a comment",
        "body": "Reading a document with a trailing comment loses its last token.",
        "acceptance_criteria": READY_AC,
        "revision": "1",
        "points": 2.0,
    }
    base.update(kw)
    return c.Ticket(**base)


def _signed_state() -> cs.VersionState:
    return cs.VersionState(
        version=version(), status="signed", sponsor="a" * 32,
        proposed_at="2026-09-28T09:00:00+00:00", approver="b" * 32,
        signed_at="2026-09-28T10:00:00+00:00",
    )  # fmt: skip


# --- one rule on both sides -------------------------------------------------------------


def test_one_rule_classifies_a_ticket_at_intake_and_a_commit_at_replay_alike() -> None:
    v = version()
    ticket = class_set_state.ticket_fields(_ticket(), as_of="2026-09-28")
    assert ticket.source == "ticket@2026-09-28" and not ticket.proxy
    commit = cs.from_message("fix: the parser drops a token after a comment")
    assert commit.proxy
    assert cs.classify(v, ticket).slug == cs.classify(v, commit).slug == "parser-fix"


def test_intake_stamps_a_ticket_with_the_routing_versions_class_and_its_global_parent(
    tmp_path: Path,
) -> None:
    home = FactoryHome(tmp_path, "alpha")
    tracker = FakeTracker({"4711": _ticket()})
    tracker.column = [c.TicketRef(key="4711", revision="1", title="t", changed="2026-09-22")]
    asked: list[CellRef] = []

    def standard_for(cell: CellRef) -> Standard | None:
        asked.append(cell)
        return Standard("S1@claude-sonnet-5", signed=True)

    state = _signed_state()
    report = sv.poll_repository(
        "alpha",
        tracker=tracker,
        listener=sv.ListenerState(enabled=True),
        column="Ready",
        home=home,
        route_for=lambda item: None,
        item_url=lambda item_id: f"https://crb.invalid/factory?item={item_id}",
        approval=sv.ApprovalPolicy(required=False),
        gate=Readers(standard_for=standard_for),
        classes=lambda draft: class_set_state.stamp(draft, state)[0],
    )
    assert report.ok and report.registered == 1, report.rows
    backlog = home.load_backlog()
    assert backlog is not None
    item = backlog.items[0]
    assert item.capability_class == "bug.fix"
    assert (item.labels["taxonomy"], item.labels["org_class"], item.labels["class_by"]) == (
        V1,
        "parser-fix",
        "rule",
    )
    # the entry gate read the organisation class's own cells, never the global one
    assert asked and {(x.taxonomy, x.org_class) for x in asked} == {(V1, "parser-fix")}


def test_a_ticket_no_class_names_and_an_override_are_each_said_as_they_are() -> None:
    from crb.intake.draft import draft_from

    state = _signed_state()
    none = draft_from(
        _ticket(title="Bump the version", body="housekeeping", acceptance_criteria=()),
        tracker="fake",
    )
    kept, payload = class_set_state.stamp(none, state)
    assert kept is none and payload["class"] == "(unclassified)"
    over = draft_from(_ticket(tags=("crb:class=cli-fix",)), tracker="fake")
    stamped, payload = class_set_state.stamp(over, state)
    assert stamped.item.labels["org_class"] == "cli-fix" and payload["by"] == "override"
    assert "crb:class=cli-fix" in stamped.classification.reason


def test_the_stamper_passes_a_ticket_through_until_a_version_routes_then_counts_it(
    env: Env,
) -> None:
    from crb.intake.draft import draft_from

    draft = draft_from(_ticket(), tracker="fake")
    assert class_set_state.draft_stamper(env.factory, ALPHA)(draft) is draft  # nothing routes
    r = env.post(
        "/classes/acme/versions",
        json={"repos": [ALPHA], "classes": [{"slug": "parser-fix", "title": "Parser", "definition": "The parser.",
                                             "parent": "bug.fix", "rule": {"words": ["parser"]}}]},
    )  # fmt: skip
    assert r.status_code == 201
    assert class_set_state.draft_stamper(env.factory, ALPHA)(draft) is draft  # unsigned
    with env.factory() as s:
        assert class_set_state.active_version(s, ALPHA) is None


def test_a_routing_version_stamps_intake_and_its_classifications_are_counted(env: Env) -> None:
    from crb.intake.draft import draft_from

    routing_version(env)  # v1 was never proposed in this test: the fixture's is v1
    hook = class_set_state.draft_stamper(env.factory, ALPHA)
    stamped = hook(draft_from(_ticket(tags=("crb:class=cli-fix",)), tracker="fake"))
    assert stamped.item.labels["taxonomy"] == V1 and stamped.item.labels["org_class"] == "cli-fix"
    with env.factory() as s:
        events = list(
            s.execute(
                select(Event).where(Event.action == class_set_state.EV_TICKET_CLASSIFIED)
            ).scalars()
        )
        assert [e.payload_json["by"] for e in events] == ["override"]
        assert class_set_state.intake_counts(s, V1) == (1, 1)
    # the override now shows in the version's report
    rate = next(
        m
        for m in env.get("/classes/acme/v/1").json()["report"]["measures"]
        if m["name"] == "override_rate"
    )
    assert "1 of" in rate["words"]


# --- the entry gate ------------------------------------------------------------------------


def _org_world(routes: bool) -> Readers:
    pool = commits(20, "org")
    reading = register(
        repo="cobra", cell=CELL, hierarchy=("S3",), pool=pool, apparatus="2.4", taxonomy=V1,
        posture_class=SEALED, checks_arm="off", actor="op-1", now=REGISTERED_AT,
        org_class="parser-fix",
    )  # fmt: skip
    rows = [sealed_row(x, arm="S3", labels={"taxonomy": V1}) for x in pool]
    return readers_over(
        [reading], rows, repo="cobra", checks_arm="off", posture_class=SEALED,
        routing={V1: routes},
    )  # fmt: skip


def test_the_gate_reads_the_organisation_class_cell_and_licenses_nothing_unless_it_routes() -> None:
    cell = CellRef(CELL["capability_class"], CELL["size"], taxonomy=V1, org_class="parser-fix")
    routing = _org_world(True)
    std = routing.standard_for(cell)
    assert std is not None and std.arm == "S3" and not std.licenses  # S3 alone: a ceiling
    # the global cell never reads the organisation's reading, nor another class's
    assert routing.standard_for(CellRef(CELL["capability_class"], CELL["size"])) is None
    assert routing.standard_for(dataclasses.replace(cell, org_class="cli-fix")) is None
    # an unsigned, revoked or failing version routes nothing: its cells have no standard
    assert _org_world(False).standard_for(cell) is None


def test_gate_for_asks_the_items_own_class_set_cell() -> None:
    from crb.factory.backlog import BacklogItem
    from crb.factory.readiness import assess

    asked: list[CellRef] = []
    item = BacklogItem(
        id="x-1", title="t", kind="code", capability_class="bug.fix", size_estimate="S",
        labels={"taxonomy": V1, "org_class": "parser-fix"},
    )  # fmt: skip
    gate_for(item, assess(item, []), Readers(standard_for=lambda cell: asked.append(cell)))
    assert asked and all((x.taxonomy, x.org_class) == (V1, "parser-fix") for x in asked)
    assert "acme/classes@v1#parser-fix" in asked[0].key()


# --- replay and runs ----------------------------------------------------------------------


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="a" * 40, repo="r", subject="fix", authored="2026-01-01T00:00:00+00:00",
        test_files=("tests/test_x.py",), src_files=("x.py",), target_tests=("tests/test_x.py",),
        belt_scope=("tests/",), capability_class="bug.fix", size="S", language="python",
        gold_clean=True, labels={"change_id": "c" * 40},
    )  # fmt: skip


def test_a_replay_row_is_stamped_with_the_runs_class_set_inside_its_hash() -> None:
    assert {f.name: f.default for f in dataclasses.fields(RunSpec)}["taxonomy"] == ""
    result = posture_result("a" * 40, "r", "sighted", True, Belts(True, True, True, True, None))
    attempt = SimpleNamespace(builder=None, error="", labels={})
    pack = SimpleNamespace(pack_hash="h" * 64)

    def spec(taxonomy: str) -> Any:
        return SimpleNamespace(
            run_id="run", actor="op", process_step="replay", taxonomy=taxonomy,
            config=SimpleNamespace(language=SimpleNamespace(value="python")),
        )  # fmt: skip

    row = row_from(spec(V1), _task(), result, pack=pack, attempt=attempt, trial="r1")  # type: ignore[arg-type]
    assert row.taxonomy == V1 and row.capability_class == "bug.fix"  # the parent stays the key
    global_row = row_from(spec(""), _task(), result, pack=pack, attempt=attempt, trial="r1")  # type: ignore[arg-type]
    assert global_row.taxonomy == "global/classes@v1"
    chained = row.chained("0" * 64)
    forged = GradeRow(
        **{**chained.fields(), "labels": {**chained.labels, "taxonomy": "global/classes@v1"}}
    )
    object.__setattr__(forged, "row_hash", chained.row_hash)
    assert chained.verify_hash() and not forged.verify_hash()


def test_a_run_is_refused_a_class_set_that_does_not_route(env: Env) -> None:
    body = {"repo": ALPHA, "kind": "replay", "builder": "editblock", "model": "m", "taxonomy": V1}
    r = env.post("/runs", json=body)
    assert r.status_code == 409 and envelope(r)["code"] == "class_set_not_routing"
    assert env.post("/runs", json={**body, "taxonomy": "not a version"}).status_code == 422
    assert env.post("/runs", json={**body, "kind": "mine"}).status_code == 422
    run = new_run(RunCreateRequest(**body), actor="op")
    assert run.params_json["taxonomy"] == V1
    assert (
        "taxonomy"
        not in new_run(RunCreateRequest(**{**body, "taxonomy": None}), actor="op").params_json
    )


def test_a_reading_of_an_organisation_class_is_a_cell_of_its_own_and_a_global_reading_is_unchanged() -> (
    None
):
    from crb.core.reading import Reading, budget_spent

    pool = commits(20, "own")
    kw: dict[str, Any] = {
        "repo": "cobra", "cell": CELL, "hierarchy": ("S3",), "pool": pool, "apparatus": "2.4",
        "posture_class": SEALED, "checks_arm": "off", "actor": "op-1", "now": REGISTERED_AT,
    }  # fmt: skip
    plain = register(taxonomy="global/classes@v1", **kw)
    assert "org_class" not in plain.to_dict()  # a global reading's body and id never moved
    parser = register(taxonomy=V1, org_class="parser-fix", **kw)
    cli = register(taxonomy=V1, org_class="cli-fix", existing=[parser], **kw)
    assert parser.to_dict()["org_class"] == "parser-fix"
    assert Reading.from_dict(parser.to_dict()).verify()
    assert parser.cell_key.endswith("|parser-fix") and parser.cell_key != cli.cell_key
    assert set(parser.pool) == set(cli.pool)  # the same commits, read as two cells
    assert budget_spent([parser, cli], parser.budget_key) == pytest.approx(parser.spend)


def test_a_reclassified_draft_takes_its_new_parents_kind() -> None:
    from crb.intake.draft import draft_from

    infra = cs.OrgClass(
        slug="parser-infra", title="Parser infrastructure", definition="The parser's deployment.",
        parent="infra.terraform.edit", rule=cs.ClassRule(words=("parser",)),
    )  # fmt: skip
    state = dataclasses.replace(
        _signed_state(), version=dataclasses.replace(version(), classes=(infra,))
    )
    draft = draft_from(_ticket(), tracker="fake")
    assert draft.item.kind == "code"  # the global classifier read a bug fix
    stamped, _payload = class_set_state.stamp(draft, state)
    assert stamped.item.capability_class == "infra.terraform.edit"
    assert stamped.item.kind == "infra"  # derived again for the parent (P-680)


# --- a version that stops routing routes nothing, on the served readers (P-689) ---------------

ORG_CELL = {
    "process_step": "replay", "capability_class": "bug.fix", "size": "S", "language": "python",
    "builder": BUILDER, "model": MODEL, "provider": PROVIDER,
}  # fmt: skip
ORG_REF = CellRef("bug.fix", "S", taxonomy=V1, org_class="parser-fix")


def _a_proven_org_cell(env: Env) -> dict[str, Any]:
    """``acme/classes@v1`` routing on ``alpha``, a reading of ``parser-fix`` registered on it
    and a clean ``S3`` first attempt on every pool commit: the served readers find its ceiling."""
    from datetime import UTC, datetime, timedelta

    from crb.core.version import APPARATUS_VERSION
    from crb.server.factory_standard import readers_in
    from crb.store.ledger import DbLedger

    routing_version(env)
    r = env.post(
        "/readings",
        json={"repo": ALPHA, "cell": ORG_CELL, "hierarchy": ["S3"], "posture_class": SEALED,
              "taxonomy": V1, "org_class": "parser-fix"},
    )  # fmt: skip
    assert r.status_code == 201, r.text
    reading = r.json()
    later = (datetime.now(UTC) + timedelta(minutes=5)).isoformat(timespec="seconds")
    DbLedger(env.factory).append_many(
        sealed_row(c, repo=ALPHA, cell=ORG_CELL, created=later, apparatus_version=APPARATUS_VERSION,
                   labels={"taxonomy": V1})
        for c in reading["pool"]
    )  # fmt: skip
    with env.factory() as s:
        readers = readers_in(s, ALPHA, checks_arm=reading["checks_arm"], posture_class=SEALED)
        std = readers.standard_for(ORG_REF)
    assert std is not None and std.arm == "S3", "the routing version's cell reads its ceiling"
    return dict(reading)


def _served(env: Env, reading: dict[str, Any]) -> Any:
    from crb.server.factory_standard import readers_in

    with env.factory() as s:
        return readers_in(s, ALPHA, checks_arm=reading["checks_arm"], posture_class=SEALED)


def test_a_revoked_version_routes_nothing_at_intake_or_the_served_gate(env: Env) -> None:
    from crb.intake.draft import draft_from

    reading = _a_proven_org_cell(env)
    draft = draft_from(_ticket(), tracker="fake")
    assert class_set_state.draft_stamper(env.factory, ALPHA)(draft) is not draft
    logout(env.client)
    login(env.client, "approver")
    assert env.post("/classes/acme/v/1/revoke", json={"reason": "retired"}).status_code == 200
    assert _served(env, reading).standard_for(ORG_REF) is None
    assert class_set_state.draft_stamper(env.factory, ALPHA)(draft) is draft
    # the global cell never read the organisation's reading, before or after
    assert _served(env, reading).standard_for(CellRef("bug.fix", "S")) is None


def test_a_signed_version_whose_report_fails_routes_nothing_at_intake_or_the_served_gate(
    env: Env,
) -> None:
    from crb.intake.draft import draft_from
    from crb.store.models import Task

    reading = _a_proven_org_cell(env)
    # sixty more commits no class names: coverage falls below 90% and the report fails
    with env.factory() as s:
        for i in range(60):
            base = s.get(Task, (ALPHA, reading["pool"][0]))
            assert base is not None
            s.add(Task(repo=ALPHA, task_id=f"{i:040x}", pool=base.pool, size="S",
                       capability_class="bug.fix", language="python", authored=base.authored,
                       subject=f"refactor: tidy module {i}", red_checked=True, gold_clean=True,
                       spec_json=dict(base.spec_json or {})))  # fmt: skip
        s.commit()
    detail = env.get("/classes/acme/v/1").json()
    assert (detail["status"], detail["route"]["code"]) == ("signed", "class_set_report_failed")
    assert _served(env, reading).standard_for(ORG_REF) is None
    draft = draft_from(_ticket(), tracker="fake")
    assert class_set_state.draft_stamper(env.factory, ALPHA)(draft) is draft
    with env.factory() as s:
        assert class_set_state.active_version(s, ALPHA) is None
