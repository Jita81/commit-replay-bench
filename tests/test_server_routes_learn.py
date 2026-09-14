"""``/learn/{refusals,strengthen,remeasure}`` — the three learning reports over the seed.

The seed (``fixtures/server_seed``) has no protocol rows, four ``oracle.score`` events
(strengths 0.9 / 0.5 / 0.33 / unscoreable) stamped apparatus ``2.0``, and a controls
report with one ESCAPE — so the 40-row deliver-on-numbers cell routes ``human``
(``controls_escapes``) and IS oracle-held. Rows are stamped with the live apparatus,
so nothing is stale until the query asks about a newer one.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from crb.core.ledger import FAILURE_PROTOCOL, LABEL_FAILURE_KIND
from crb.core.version import APPARATUS_VERSION
from crb.store.ledger import DbLedger
from crb.store.models import Grade
from fixtures.server_seed import ALPHA, BETA, Env, assert_rbac, envelope, make_env

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
