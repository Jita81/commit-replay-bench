"""``/learn/{refusals,strengthen,remeasure}`` — the three learning reports over the seed.

The seed (``fixtures/server_seed``) has no protocol rows, four ``oracle.score`` events
(strengths 0.9 / 0.5 / 0.33 / unscoreable) stamped apparatus ``2.0``, and a controls
report with one ESCAPE — so the 40-row deliver-on-numbers cell routes ``human``
(``controls_escapes``) and IS oracle-held. Rows are stamped with the live apparatus,
so nothing is stale until the query asks about a newer one.

Navigation
----------
What it is:   ``/learn/*``'s test suite — the three learning reports over the seed, and the
              three operator-gated writes they hand off to.
What it does: Pins RBAC and 404, refusals empty then one after a protocol row lands through the
              write path, that strengthen uses the controls verdict and the per-task
              ``oracle.score`` events from the store, that the CLI over the exports derives the
              same route items, that nothing is stale until the apparatus moves, and that a
              false-Q1 row inserted around the ledger refuses to load. For the writes (G-532):
              that all three need ``operator``; that an accepted refusal lands in the corpus
              under a provenance comment naming the DECIDER, is served back with the report, is
              on the chain with the account as actor and is idempotent; that the API refuses
              exactly what the CLI refuses; that registering freezes the first item, evolves the
              rest and supersedes a re-registered one; that an unknown id and an in-flight
              factory run are refused with nothing written; and that queueing enqueues the
              PLAN's own run bodies, never the caller's.
How:          ``make_env`` over the seed; a protocol row appended through ``DbLedger``; the CLI
              invoked over the API's own exports for the parity case; the writes driven through
              ``env.post`` and checked against ``GET /factory/{repo}/backlog``, ``GET /runs`` and
              the ``events`` table.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/server/routes/learn.py (under test), src/crb/core/learn.py (the
              derivations and ``apply_triage`` — the writer both halves share),
              tests/test_cli_learn.py (the CLI half of the parity),
              tests/fixtures/server_seed.py (``make_env``, ``assert_rbac``, ``user_id``),
              src/crb/server/factory_state.py (the backlog the register write moves),
              docs/LEARNING-LOOP.md (the contract these writes implement), docs/API.md
Tested by:    tests/test_server_routes_learn.py
Touch when:   a learn report gains a field (the CLI must read the export the same way — add the
              parity case); the event shapes the reports read change; a fourth write path lands
              (pin its role, its refusals and its event here).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from crb.core.ledger import FAILURE_PROTOCOL, LABEL_FAILURE_KIND
from crb.core.version import APPARATUS_VERSION
from crb.store.ledger import DbLedger
from crb.store.models import Event, Grade, Run
from fixtures.server_seed import (
    ALPHA,
    BETA,
    RUN_IDS,
    USERS,
    Env,
    assert_rbac,
    envelope,
    make_env,
    user_id,
)

ERR_NHS = (
    "protocol violation: archaeology: '.git' is off limits (.git) (attempted: find . -iname "
    '"*conftest*" -o -iname "*helpers*" | grep -v ".git"); network: \'curl\' is not allowed '
    "(no network access) (attempted: curl -sk https://localhost:8701/health)"
)


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    """The seeded environment, logged in as admin, torn down after the test."""
    with make_env(tmp_path) as e:
        yield e


def _add_protocol_row(env: Env) -> None:
    """Append one protocol row through the write path (chained, invariants checked)."""
    ledger = DbLedger(env.factory)
    template = next(r for r in ledger.rows(repo=ALPHA) if r.clean)
    d = template.to_dict()
    d.update(
        {
            "clean": False,
            "target_green": False,
            "no_new_failures": None,
            "source_changed": None,
            "evidence_pack_hash": "",
            "error": ERR_NHS,
            "labels": {"builder_error": ERR_NHS[:300], LABEL_FAILURE_KIND: FAILURE_PROTOCOL},
            "row_id": "",
            "prev_hash": "",
            "row_hash": "",
            "task_id": "f" * 40,
            "cost_usd": 0.21,
            "latency_s": 33.0,
        }
    )
    d.pop("failure_kind", None)
    d.pop("cost_known", None)
    from crb.core.ledger import GradeRow

    ledger.append(GradeRow.from_dict(d))


def test_rbac(env: Env) -> None:
    for path in ("/learn/refusals", "/learn/strengthen", "/learn/remeasure"):
        assert_rbac(env, "GET", f"{path}?repo={ALPHA}", min_role="viewer")


def test_unknown_repo_404(env: Env) -> None:
    r = env.get("/learn/refusals?repo=nope")
    assert r.status_code == 404 and envelope(r)["code"] == "not_found"


def test_refusals_empty_then_one(env: Env) -> None:
    r = env.get(f"/learn/refusals?repo={ALPHA}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["repo"] == ALPHA and d["rows_protocol"] == 0 and d["groups"] == []
    _add_protocol_row(env)
    d = env.get(f"/learn/refusals?repo={ALPHA}").json()
    assert d["rows_protocol"] == 1 and len(d["groups"]) == 2
    assert all(g["verdict"] == "unsure" for g in d["groups"])
    shapes = {g["shape"] for g in d["groups"]}
    assert shapes == {'find . -iname "<str>" -o -iname "<str>" | grep -v "<str>"', "curl -sk <url>"}
    curl = next(g for g in d["groups"] if g["prefix"] == "network")
    assert curl["candidate_refused"] == "curl -sk https://localhost:8701/health\tnetwork:"
    assert curl["cost_usd"] == pytest.approx(0.21)
    # beta has no rows: honest-empty, not an error
    assert env.get(f"/learn/refusals?repo={BETA}").json()["rows_total"] == 0


def test_strengthen_uses_the_controls_verdict_and_the_oracle_scores(env: Env) -> None:
    r = env.get(f"/learn/strengthen?repo={ALPHA}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["projection"] == "class_size" and "bug.fix|S" in d["cells_flagged"]
    items = [i for i in d["items"] if i["labels"]["cell"] == "bug.fix|S"]
    assert items, d
    assert all(i["capability_class"] == "test.add" for i in items)
    assert all(i["labels"]["reason_code"] == "controls_escapes" for i in items)
    weak = [
        i for i in items if i["labels"].get("oracle_strength") in ("0.50", "0.33", "unscoreable")
    ]
    assert weak, [i["labels"] for i in items]
    # the seed scores are stamped 2.0: asking since the live apparatus drops them
    d2 = env.get(f"/learn/strengthen?repo={ALPHA}&since={APPARATUS_VERSION}").json()
    assert "bug.fix|S" in d2["cells_without_scores"]
    r = env.get(f"/learn/strengthen?repo={ALPHA}&by=nope")
    assert r.status_code == 422


def test_strengthen_reads_per_task_scores_from_the_store_events(env: Env) -> None:
    """The per-task scores are the repo's ``oracle.score`` events (an oracle run's
    ``counts_json`` is only the cell roll-up): every item names a SEEDED scored task
    of the held cell, carries the repo, and the strengths are the seed's."""
    d = env.get(f"/learn/strengthen?repo={ALPHA}").json()
    items = [i for i in d["items"] if i["labels"]["cell"] == "bug.fix|S"]
    with env.factory() as session:
        scored = {
            ev.task_id: dict(ev.payload_json or {})
            for ev in session.execute(
                select(Event).where(Event.repo == ALPHA, Event.action == "oracle.score")
            ).scalars()
            if (ev.payload_json or {}).get("capability_class") == "bug.fix"
        }
    assert items and {i["labels"]["task_id"] for i in items} <= set(scored)
    assert all(i["labels"]["repo"] == ALPHA for i in items)
    assert all(i["labels"]["reason_code"] == "controls_escapes" for i in items)
    for i in items:
        payload = scored[i["labels"]["task_id"]]
        assert i["labels"]["mutants"] == str(payload["total"])
        assert i["labels"]["escaped"] == str(payload["total"] - payload["killed"])
    assert "bug.fix|S" not in d["cells_without_scores"]
    # the item id is sha(cell, repo, task): stable across reads
    assert [i["id"] for i in d["items"]] == [
        i["id"] for i in env.get(f"/learn/strengthen?repo={ALPHA}").json()["items"]
    ]


def test_cli_over_the_exports_derives_the_route_items(
    env: Env, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A ledger export is the rows alone: over it the CLI honestly flags nothing, even
    with the scores — the cell is held by the controls verdict. Given the two exports
    the route reads from the store (``GET /oracle/{repo}`` and
    ``GET /oracle/{repo}/controls``) the CLI derives the SAME items with the SAME ids;
    the oracle run's ``events/log`` page is an equivalent source of the scores."""
    from crb.cli.main import main

    route = env.get(f"/learn/strengthen?repo={ALPHA}").json()
    want = sorted(
        (i["id"], i["labels"]["task_id"], i["labels"]["oracle_strength"]) for i in route["items"]
    )
    assert want
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(env.get(f"/ledger/export?repo={ALPHA}&format=jsonl").text, encoding="utf-8")
    oracle = tmp_path / "oracle.json"
    oracle.write_text(env.get(f"/oracle/{ALPHA}").text, encoding="utf-8")
    controls = tmp_path / "controls.json"
    controls.write_text(env.get(f"/oracle/{ALPHA}/controls").text, encoding="utf-8")
    events = tmp_path / "events.json"
    events.write_text(
        env.get(f"/runs/{RUN_IDS['oracle']}/events/log?limit=200").text, encoding="utf-8"
    )

    def cli(*extra: str) -> dict[str, Any]:
        capsys.readouterr()
        argv = ["learn", "strengthen", "--path", str(ledger), "--json", "--workdir", str(tmp_path)]
        code = main([*argv, *extra])
        out = capsys.readouterr()
        assert code == 0, out.err
        return dict(json.loads(out.out))

    bare = cli("--oracle", str(oracle))
    with_controls = cli("--oracle", str(oracle), "--controls", str(controls))
    from_events = cli("--oracle", str(events), "--controls", str(controls))
    assert bare["cells_flagged"] == [] and bare["items"] == [] and bare["controls"] is None
    for d in (with_controls, from_events):
        got = sorted(
            (i["id"], i["labels"]["task_id"], i["labels"]["oracle_strength"]) for i in d["items"]
        )
        assert got == want
        assert d["cells_flagged"] == route["cells_flagged"]
        assert d["controls"]["escapes"] == 1 and d["controls"]["measured"] is True


def test_remeasure_nothing_stale_until_the_apparatus_moves(env: Env) -> None:
    d = env.get(f"/learn/remeasure?repo={ALPHA}").json()
    assert d["current_apparatus"] == APPARATUS_VERSION
    # only the legacy cell (apparatus 1.0-census) is older than the live instrument
    assert [c["stale_versions"] for c in d["cells"]] == [["1.0-census"]]
    d2 = env.get(f"/learn/remeasure?repo={ALPHA}&apparatus=9.9").json()
    assert d2["rows_stale"] == d2["rows_total"] and len(d2["cells"]) >= 3
    for c in d2["cells"]:
        for req in c["requests"]:
            assert req["repo"] == ALPHA and req["kind"] in ("replay", "blind")
    assert "nothing here was sent" in d2["note"]


def test_false_q1_row_refuses_to_load(env: Env) -> None:
    """A false-Q1 row inserted straight through the ORM (bypassing DbLedger — the table
    is append-only, so an UPDATE is impossible) makes every learn route answer 409."""
    with env.factory() as s:
        s.add(
            Grade(
                row_id="bad-row",
                schema="crb.grade.v2",
                repo=ALPHA,
                task_id="deadbeef" * 5,
                created="2026-09-01T00:00:00+00:00",
                clean=True,
                tests_unmodified=True,
                target_green=False,
                no_new_failures=True,
                source_changed=True,
                capability_class="docs.update",
                size="S",
                language="python",
                evidence_pack_hash="p" * 64,
                apparatus_version="2.0",
                belt_set="v4",
                prev_hash="x" * 64,
                row_hash="y" * 64,
            )
        )
        s.commit()
    for path in ("/learn/refusals", "/learn/strengthen", "/learn/remeasure"):
        r = env.get(f"{path}?repo={ALPHA}")
        assert r.status_code == 409, (path, r.text)
        assert envelope(r)["code"] == "false_q1_refused"


# ---------------------------------------------------------------------------
# The three writes (G-532): a named operator's decision, from the report that computed it
# ---------------------------------------------------------------------------


def _accept(env: Env, group_id: str, verdict: str, **extra: Any) -> Any:
    return env.post(
        f"/learn/refusals/accept?repo={ALPHA}",
        json={"group_id": group_id, "verdict": verdict, **extra},
    )


def _group(env: Env, prefix: str) -> dict[str, Any]:
    """One refusal class of ALPHA's current report, by guard family."""
    groups = env.get(f"/learn/refusals?repo={ALPHA}").json()["groups"]
    return next(g for g in groups if g["prefix"] == prefix)


def test_the_three_writes_are_operator_gated(env: Env) -> None:
    """Reading the reports is a viewer's; deciding is an operator's — at the API, not only
    in the UI. The bodies are the smallest valid ones: RBAC is checked before they are."""
    _add_protocol_row(env)
    gid = _group(env, "archaeology")["group_id"]
    assert_rbac(
        env,
        "POST",
        f"/learn/refusals/accept?repo={ALPHA}",
        min_role="operator",
        json={"group_id": gid, "verdict": "honest"},
    )
    item_id = env.get(f"/learn/strengthen?repo={ALPHA}").json()["items"][0]["id"]
    assert_rbac(
        env,
        "POST",
        f"/learn/strengthen/register?repo={ALPHA}",
        min_role="operator",
        json={"item_ids": [item_id]},
    )
    cell = env.get(f"/learn/remeasure?repo={ALPHA}&apparatus=9.9").json()["cells"][0]["label"]
    assert_rbac(
        env,
        "POST",
        f"/learn/remeasure/queue?repo={ALPHA}",
        min_role="operator",
        json={"cell": cell, "apparatus": "9.9"},
    )


def test_accepting_a_refusal_writes_the_line_under_the_operators_name(env: Env) -> None:
    """The verdict the report never makes, made once on the screen's behalf: the line lands
    in the corpus under a provenance comment that names WHO decided, the decision is served
    back with the report, and repeating it writes nothing."""
    _add_protocol_row(env)
    group = _group(env, "archaeology")
    r = _accept(env, group["group_id"], "honest", note=".git inside a quoted argument")
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["decided_by"] == USERS["admin"] and d["verdict"] == "honest"
    assert d["honest_added"] == [group["candidate_honest"]] and d["refused_added"] == []
    assert d["already_present"] is False
    corpus = Path(d["honest_path"])
    assert corpus.is_file()
    text = corpus.read_text(encoding="utf-8")
    assert group["candidate_honest"] in text
    assert f"(honest→{USERS['admin']})" in text and "quoted argument" in text
    # the decision is now part of what the report serves — nobody has to remember it
    served = env.get(f"/learn/refusals?repo={ALPHA}").json()["decisions"]
    assert [x["group_id"] for x in served] == [group["group_id"]]
    assert served[0]["decided_by"] == USERS["admin"] and served[0]["verdict"] == "honest"
    assert served[0]["lines"] == [group["candidate_honest"]]
    # and it is on the chain, once, with the actor
    with env.factory() as s:
        events = list(
            s.execute(
                select(Event).where(Event.action == "learn.refusal.accepted", Event.repo == ALPHA)
            ).scalars()
        )
    assert len(events) == 1 and events[0].actor == user_id(USERS["admin"])
    assert events[0].payload_json["guard"] == "archaeology"
    # idempotent: the same decision again adds nothing and says the line was already there
    again = _accept(env, group["group_id"], "honest")
    assert again.status_code == 201, again.text
    assert again.json()["honest_added"] == [] and again.json()["already_present"] is True
    assert corpus.read_text(encoding="utf-8") == text


def test_accepting_refuses_exactly_what_the_cli_refuses(env: Env) -> None:
    """The API and ``crb learn refusals --apply`` share ``apply_triage``, so they refuse the
    same things: an unknown class, a verdict the report may not carry, and a line that would
    contradict the other corpus (never weaken a refusal to make a line pass)."""
    _add_protocol_row(env)
    assert _accept(env, "no-such-group", "honest").status_code == 404
    curl = _group(env, "network")
    assert _accept(env, curl["group_id"], "unsure").status_code == 422  # the report's own word
    assert _accept(env, curl["group_id"], "refuse").status_code == 201
    contradiction = _accept(env, curl["group_id"], "honest")
    assert contradiction.status_code == 422
    assert envelope(contradiction)["code"] == "refusal_refused"
    assert "OTHER corpus" in envelope(contradiction)["message"]


def test_the_corpus_directory_defaults_under_home_and_is_overridable(tmp_path: Path) -> None:
    """Unset, the accepted lines are this deployment's own record under ``CRB_HOME``. A
    deployment running from a source checkout points ``CRB_LEARN_CORPUS_DIR`` at that
    checkout's fixtures, and an accepted line then binds the guard-corpus test directly."""
    from crb.server.routes.learn import corpus_dir

    class _S:
        home = tmp_path
        learn_corpus_dir = ""

    assert corpus_dir(_S()) == tmp_path / "learn" / "corpus"
    _S.learn_corpus_dir = str(tmp_path / "checkout" / "tests" / "fixtures")
    assert corpus_dir(_S()) == tmp_path / "checkout" / "tests" / "fixtures"


def test_registering_strengthening_items_freezes_then_evolves(env: Env) -> None:
    """The hand-off that used to be a paste into ``POST /factory/{repo}/backlog``: the first
    item freezes the backlog, the next is an evolution, and an item already on the record is
    registered as a NEW id superseding the latest of its lineage — a frozen record never
    mutates, so re-registering after a re-score chains rather than overwrites."""
    assert env.get(f"/factory/{ALPHA}/backlog").status_code == 404
    items = env.get(f"/learn/strengthen?repo={ALPHA}").json()["items"]
    assert len(items) >= 2, items
    first, second = items[0]["id"], items[1]["id"]
    r = env.post(f"/learn/strengthen/register?repo={ALPHA}", json={"item_ids": [first, second]})
    assert r.status_code == 201, r.text
    d = r.json()
    assert [x["how"] for x in d["registered"]] == ["frozen", "evolved"]
    assert [x["item_id"] for x in d["registered"]] == [first, second]
    assert all(x["supersedes"] == "" for x in d["registered"])
    backlog = env.get(f"/factory/{ALPHA}/backlog").json()
    assert backlog["hash"] == d["backlog_hash"]
    ids = [i["id"] for i in backlog["items"]]
    assert first in ids and second in ids
    # the same item again: a new id that supersedes the one on the record
    again = env.post(f"/learn/strengthen/register?repo={ALPHA}", json={"item_ids": [first]})
    assert again.status_code == 201, again.text
    row = again.json()["registered"][0]
    assert (
        row["item_id"] == f"{first}-v2" and row["supersedes"] == first and row["how"] == "evolved"
    )
    # a third registration chains onto the SECOND, never onto the superseded first
    third = env.post(f"/learn/strengthen/register?repo={ALPHA}", json={"item_ids": [first]}).json()
    assert third["registered"][0]["supersedes"] == f"{first}-v2"
    with env.factory() as s:
        events = list(
            s.execute(
                select(Event).where(
                    Event.action == "learn.strengthen.registered", Event.repo == ALPHA
                )
            ).scalars()
        )
    assert len(events) == 3 and all(e.actor == user_id(USERS["admin"]) for e in events)
    assert events[0].payload_json["items"][0]["item_id"] == first


def test_registering_refuses_an_unknown_id_and_a_factory_run_in_flight(env: Env) -> None:
    """The body names ids and nothing else, so an id the report does not hold is refused
    before anything is written; and the backlog a queued run verifies against cannot change
    under it."""
    bad = env.post(f"/learn/strengthen/register?repo={ALPHA}", json={"item_ids": ["strengthen-x"]})
    assert bad.status_code == 422 and envelope(bad)["code"] == "validation_error"
    assert envelope(bad)["detail"]["unknown"] == ["strengthen-x"]
    item_id = env.get(f"/learn/strengthen?repo={ALPHA}").json()["items"][0]["id"]
    with env.factory() as s:
        s.add(Run(id="ab" * 16, repo=ALPHA, kind="factory", status="queued", mode="sighted"))
        s.commit()
    blocked = env.post(f"/learn/strengthen/register?repo={ALPHA}", json={"item_ids": [item_id]})
    assert blocked.status_code == 409 and envelope(blocked)["code"] == "factory_run_active"
    assert env.get(f"/factory/{ALPHA}/backlog").status_code == 404  # nothing was written


def test_queueing_a_remeasurement_enqueues_the_plans_own_bodies(env: Env) -> None:
    """Money is spent only on an operator's instruction, and only on the bodies the plan
    computed: the caller names a cell, the product composes the runs."""
    plan = env.get(f"/learn/remeasure?repo={ALPHA}&apparatus=9.9").json()
    cell = plan["cells"][0]
    before = env.get("/runs").json()["total"]
    r = env.post(
        f"/learn/remeasure/queue?repo={ALPHA}", json={"cell": cell["label"], "apparatus": "9.9"}
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert len(d["run_ids"]) == len(cell["requests"])
    assert d["n_needed"] == cell["n_needed"] and d["cost_known"] == cell["cost_known"]
    assert env.get("/runs").json()["total"] == before + len(d["run_ids"])
    queued = [env.get(f"/runs/{rid}").json() for rid in d["run_ids"]]
    for run, request in zip(queued, cell["requests"], strict=True):
        assert run["status"] == "queued" and run["repo"] == ALPHA
        assert run["kind"] == request["kind"] and run["mode"] == request["mode"]
        assert run["builder"] == request["builder"] and run["model"] == request["model"]
        assert run["task_ids"] == request["task_ids"]
    with env.factory() as s:
        event = s.execute(
            select(Event).where(Event.action == "learn.remeasure.queued", Event.repo == ALPHA)
        ).scalar_one()
    assert event.actor == user_id(USERS["admin"])
    assert event.payload_json["run_ids"] == d["run_ids"]
    assert event.payload_json["cell"] == cell["label"]


def test_queueing_refuses_a_cell_the_plan_does_not_hold(env: Env) -> None:
    """A cell that is not in the plan — or is not planned in the mode asked for, since
    sighted and blind are never pooled — is refused with the plan's own cells named."""
    plan = env.get(f"/learn/remeasure?repo={ALPHA}&apparatus=9.9").json()
    cell = plan["cells"][0]
    before = env.get("/runs").json()["total"]
    missing = env.post(
        f"/learn/remeasure/queue?repo={ALPHA}", json={"cell": "replay|nope|S", "apparatus": "9.9"}
    )
    assert missing.status_code == 422 and envelope(missing)["code"] == "validation_error"
    assert envelope(missing)["detail"]["available"]
    wrong_mode = env.post(
        f"/learn/remeasure/queue?repo={ALPHA}",
        json={"cell": cell["label"], "mode": "blind", "apparatus": "9.9"},
    )
    assert wrong_mode.status_code == 422
    assert env.get("/runs").json()["total"] == before  # nothing was queued
