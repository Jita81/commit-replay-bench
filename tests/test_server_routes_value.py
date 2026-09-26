"""``GET /value`` — the scorecard over the store: rows, the standing reviews and the register.

Navigation
----------
What it is:   The test suite for ``/value`` — the scorecard route the Home tile reads.
What it does: Pins that a viewer may read it and an anonymous caller may not; that an unknown
              repository is 404; that the served north star carries its n, interval, method and
              apparatus and is null (never zero) while no blind row exists; that blind rows
              appended through the write path move it; that a review written through
              ``POST /reviews`` reaches the precision joined to its row; that the scope defaults
              to the current apparatus and pools only on request; that the register behind the
              curve names itself; and that a false-Q1 row makes the route refuse (409).
How:          ``make_env`` over the seed; blind rows appended through ``DbLedger``; a real
              retained row and review from the reviews suite's ``Retained`` helper.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/server/routes/value.py (under test), src/crb/core/value.py (the report),
              tests/test_server_routes_reviews.py (``Retained``: a row a review can anchor to),
              tests/fixtures/server_seed.py (the seeded store), docs/API.md (the row it pins)
Tested by:    tests/test_server_routes_value.py
Touch when:   a scorecard field is added to the response (pin it here and in docs/API.md).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from crb.core.ledger import FAILURE_BUDGET, LABEL_FAILURE_KIND, GradeRow
from crb.core.version import APPARATUS_VERSION
from crb.store.ledger import DbLedger
from crb.store.models import Grade
from fixtures.server_seed import ALPHA, Env, assert_rbac, envelope, login, make_env
from test_server_routes_reviews import Retained


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path) as e:
        yield e


def _add_blind(env: Env, *, clean: bool, n: int = 1) -> None:
    """Append blind rows through the write path (chained, invariants checked)."""
    ledger = DbLedger(env.factory)
    template = next(r for r in ledger.rows(repo=ALPHA) if r.clean)
    for i in range(n):
        d = template.to_dict()
        d.update({"mode": "blind", "row_id": "", "prev_hash": "", "row_hash": "", "cost_usd": 0.5})
        d["task_id"] = f"{'b' if clean else 'c'}{i:039d}"
        if not clean:
            d.update(
                {
                    "clean": False,
                    "target_green": False,
                    "evidence_pack_hash": "",
                    "labels": {LABEL_FAILURE_KIND: FAILURE_BUDGET, "stop_reason": "max_turns"},
                }
            )
        d.pop("failure_kind", None)
        d.pop("cost_known", None)
        ledger.append(GradeRow.from_dict(d))


def test_rbac(env: Env) -> None:
    assert_rbac(env, "GET", f"/value?repo={ALPHA}", min_role="viewer")


def test_unknown_repo_404(env: Env) -> None:
    r = env.get("/value?repo=nope")
    assert r.status_code == 404 and envelope(r)["code"] == "not_found"


def test_the_seed_has_no_blind_rows_so_the_north_star_is_null(env: Env) -> None:
    r = env.get(f"/value?repo={ALPHA}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["schema"] == "crb.value.v1" and d["repo"] == ALPHA
    assert d["apparatus"] == APPARATUS_VERSION and d["pooled"] is False
    ns = d["north_star"]
    assert ns["n_valid"] == 0 and ns["per_pound"] is None and "Wilson" in ns["method"]
    assert d["learning_curve"]["register"]["source"] == "crb.prevention.register.v1"
    assert d["routing"]["controls"] == "not evaluated"


def test_blind_rows_move_the_north_star(env: Env) -> None:
    _add_blind(env, clean=True, n=3)
    _add_blind(env, clean=False, n=2)
    ns = env.get(f"/value?repo={ALPHA}").json()["north_star"]
    assert (ns["clean"], ns["n_valid"], ns["n_attempts"]) == (3, 5, 5)
    assert ns["clean_rate"]["ci_low"] is not None and ns["spend_usd"] == pytest.approx(2.5)
    assert ns["per_pound"] is not None and ns["precision_basis"] in ("proxy", "review")
    loss = env.get(f"/value?repo={ALPHA}").json()["process_loss"]
    assert loss["kinds"]["budget"]["rows"] == 2


def test_a_review_reaches_the_precision_joined_to_its_row(env: Env, tmp_path: Path) -> None:
    r = Retained(env, tmp_path)
    login(env.client, "operator")
    res = env.post("/reviews", json=r.review_body(mergeable=True))
    assert res.status_code == 201, res.text
    pr = env.get(f"/value?repo={ALPHA}").json()["precision"]
    assert pr["review"]["n"] == 1 and pr["review"]["k"] == 1 and pr["review"]["unjoined"] == 0
    assert pr["agreement"]["n"] == 1


def test_all_repositories_list_each_ones_north_star(env: Env) -> None:
    d = env.get("/value?apparatus=all").json()
    assert d["repo"] is None and d["apparatus"] == "all"
    assert ALPHA in {x["repo"] for x in d["repos"]}


def test_a_false_q1_row_refuses(env: Env) -> None:
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
    r = env.get(f"/value?repo={ALPHA}")
    assert r.status_code == 409 and envelope(r)["code"] == "false_q1_refused"


def test_the_curve_classes_a_belt_5_row_from_its_evidence_pack(env: Env) -> None:
    """The route hands the register the store's packs, as the Learn page's does: a gofmt
    rejection is ``format:gofmt`` on the scorecard too, never ``lint:*`` (P-022)."""
    from crb.store.models import EvidencePackRow

    pack_hash = "d" * 64
    with env.factory() as s:
        s.add(
            EvidencePackRow(
                pack_hash=pack_hash,
                repo=ALPHA,
                task_id="e" * 40,
                body_json={
                    "grade": {
                        "lint_run": {
                            "steps": [{"tool": "gofmt", "verdict": False, "tail": "a.go\n"}]
                        }
                    }
                },
            )
        )
        s.commit()
    ledger = DbLedger(env.factory)
    template = next(r for r in ledger.rows(repo=ALPHA) if r.clean)
    d = template.to_dict()
    d.update(
        {
            "row_id": "",
            "prev_hash": "",
            "row_hash": "",
            "task_id": "e" * 40,
            "clean": False,
            "repo_lint_clean": False,
            "evidence_pack_hash": pack_hash,
        }
    )
    d.pop("failure_kind", None)
    d.pop("cost_known", None)
    ledger.append(GradeRow.from_dict(d))
    r = env.get(f"/value?repo={ALPHA}")
    assert r.status_code == 200, r.text
    sigs = {c["signature"] for c in r.json()["learning_curve"]["classes"]}
    assert "format:gofmt" in sigs and "lint:*" not in sigs


def test_the_report_says_its_reviews_come_from_the_store(env: Env) -> None:
    """The route reads only the review store; the baseline page read an export plus the
    critical-friend page. The report names its source so the two are never read as one
    figure (P-035)."""
    d = env.get(f"/value?repo={ALPHA}").json()
    assert d["reviews_source"] == "store"
