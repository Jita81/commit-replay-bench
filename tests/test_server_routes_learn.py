"""``/learn/{refusals,strengthen,remeasure}`` — the three learning reports over the seed.

The seed (``fixtures/server_seed``) has no protocol rows, four ``oracle.score`` events
(strengths 0.9 / 0.5 / 0.33 / unscoreable) stamped apparatus ``2.0``, and a controls
report with one ESCAPE — so the 40-row deliver-on-numbers cell routes ``human``
(``controls_escapes``) and IS oracle-held. Rows are stamped with the live apparatus,
so nothing is stale until the query asks about a newer one.

Navigation
----------
What it is:   ``/learn/{refusals, strengthen, remeasure}``'s test suite — the three learning
              reports over the seed.
What it does: Pins RBAC and 404, refusals empty then one after a protocol row lands through the
              write path, that strengthen uses the controls verdict and the per-task
              ``oracle.score`` events from the store, that the CLI over the exports derives the
              same route items, that nothing is stale until the apparatus moves, and that a
              false-Q1 row inserted around the ledger refuses to load.
How:          ``make_env`` over the seed; a protocol row appended through ``DbLedger``; the CLI
              invoked over the API's own exports for the parity case.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/server/routes/learn.py (under test), src/crb/core/learn.py (the
              derivations), tests/test_cli_learn.py (the CLI half of the parity),
              tests/fixtures/server_seed.py, docs/LEARNING-LOOP.md, docs/API.md
Tested by:    tests/test_server_routes_learn.py
Touch when:   a learn report gains a field (the CLI must read the export the same way — add the
              parity case); the event shapes the reports read change.
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
from crb.store.models import Event, Grade
from fixtures.server_seed import (
    ALPHA,
    BETA,
    RUN_IDS,
    Env,
    assert_rbac,
    envelope,
    make_env,
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
            # the template's posture labels stay (ADR-0019: a 2.3 row names its posture)
            "labels": {
                **template.labels,
                "builder_error": ERR_NHS[:300],
                LABEL_FAILURE_KIND: FAILURE_PROTOCOL,
            },
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
