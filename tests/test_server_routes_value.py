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
Touch when:   never for a new repository; a scorecard field is added to the response (pin it here
              and in docs/API.md).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from crb.core.ledger import FAILURE_BUDGET, LABEL_FAILURE_KIND, GradeRow
from crb.core.version import APPARATUS_VERSION
from crb.store.ledger import DbLedger
from crb.store.models import Grade
from fixtures.posture import TEST_POSTURE_CLASS, dict_at_apparatus, with_posture_labels
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


def _add_blind(env: Env, *, clean: bool, n: int = 1, posture_class: str = "") -> None:
    """Append blind rows through the write path (chained, invariants checked), graded in the
    test posture (``local/inplace/host-env``) unless ``posture_class`` names another."""
    ledger = DbLedger(env.factory)
    template = next(r for r in ledger.rows(repo=ALPHA) if r.clean)
    for i in range(n):
        d = template.to_dict()
        d.update({"mode": "blind", "row_id": "", "prev_hash": "", "row_hash": "", "cost_usd": 0.5})
        prefix = ("b" if clean else "c") if not posture_class else ("d" if clean else "e")
        d["task_id"] = f"{prefix}{i:039d}"
        if not clean:
            d.update(
                {
                    "clean": False,
                    "target_green": False,
                    "evidence_pack_hash": "",
                    "labels": {LABEL_FAILURE_KIND: FAILURE_BUDGET, "stop_reason": "max_turns"},
                }
            )
        if posture_class:
            d["labels"] = {
                **d["labels"],
                "posture_class": posture_class,
                "posture_id": "pst_" + "6" * 24,
            }
        d.pop("failure_kind", None)
        d.pop("cost_known", None)
        ledger.append(GradeRow.from_dict(with_posture_labels(d)))


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


#: The test deployment runs ``sandbox.executor=local``: its own class is the host's.
HOST = TEST_POSTURE_CLASS
SEALED = "docker/copy/sealed"
_POSTURE_KEYS = ("posture_", "qualification_id")


def _mixed(env: Env) -> None:
    """Three clean blind rows graded on the host and two budget-stopped blind rows graded in
    a sealed container, $0.50 each: two instruments, never one rate per pound."""
    _add_blind(env, clean=True, n=3)
    _add_blind(env, clean=False, n=2, posture_class=SEALED)


def test_the_scorecard_reads_the_deployments_posture_class_by_default(env: Env) -> None:
    """ADR-0019 §8 (P-135): posture is a filter, never a blend. A sealed row and a host row
    in one repository: the default reading counts only the deployment's own class (its
    working changes per pound, its loss and its spend), for one repository and across every
    repository, and names the class it read."""
    _mixed(env)
    d = env.get(f"/value?repo={ALPHA}").json()
    assert (d["posture"], d["posture_class"]) == (HOST, HOST)
    ns = d["north_star"]
    assert (ns["clean"], ns["n_valid"], ns["n_attempts"]) == (3, 3, 3)
    assert ns["spend_usd"] == pytest.approx(1.5)
    assert d["process_loss"]["kinds"]["budget"]["rows"] == 0
    every = env.get("/value").json()
    assert (every["posture"], every["posture_class"]) == (HOST, HOST)
    (alpha,) = (x for x in every["repos"] if x["repo"] == ALPHA)
    assert alpha["north_star"]["n_attempts"] == 3
    assert alpha["north_star"]["spend_usd"] == pytest.approx(1.5)


def test_posture_names_another_class_and_reads_only_it(env: Env) -> None:
    _mixed(env)
    d = env.get(f"/value?repo={ALPHA}&posture={SEALED}").json()
    assert (d["posture"], d["posture_class"], d["rows"]) == (SEALED, SEALED, 2)
    ns = d["north_star"]
    assert (ns["clean"], ns["n_valid"], ns["n_attempts"]) == (0, 2, 2)
    assert ns["spend_usd"] == pytest.approx(1.0)
    assert d["process_loss"]["kinds"]["budget"]["rows"] == 2
    assert sum(c["attempts"] for c in d["cells"]) == 2


def test_posture_all_refuses_to_reduce_two_classes(env: Env) -> None:
    """``posture=all`` lifts the filter and is still never a blend: over rows of one class it
    reads that class (and names it); over rows of two it refuses with the classes present,
    for one repository and across every repository, as the economics fold withholds a cost
    that spans two (a pound spent in a sealed container buys a different measurement)."""
    _add_blind(env, clean=True, n=3)
    one = env.get(f"/value?repo={ALPHA}&posture=all")
    assert one.status_code == 200, one.text
    assert (one.json()["posture"], one.json()["posture_class"]) == ("all", HOST)
    _add_blind(env, clean=False, n=2, posture_class=SEALED)
    for query in (f"?repo={ALPHA}&posture=all", "?posture=all"):
        r = env.get(f"/value{query}")
        assert r.status_code == 422, r.text
        e = envelope(r)
        assert e["code"] == "posture_pooling_refused" and "ADR-0019" in e["message"]
        assert e["detail"]["present"] == [SEALED, HOST]


def test_a_row_from_before_2_3_is_placed_by_its_runs_executor(env: Env) -> None:
    """A pre-2.3 row carries no posture: its run's apparatus stamp places it, as on the map.
    The host graded ``legacy:local`` in its own environment, so it reads with the host's
    class; a ``legacy:docker`` row was graded against a baseline measured elsewhere, so it is
    left out of every figure and counted ``unqualified_posture``."""
    from crb.store.models import Run

    with env.factory() as s:
        for run_id, executor in (("7" * 32, "local"), ("8" * 32, "docker")):
            s.add(
                Run(
                    id=run_id,
                    repo=ALPHA,
                    kind="replay",
                    status="succeeded",
                    apparatus_json={"executor": {"executor": executor}},
                )
            )
        s.commit()
    ledger = DbLedger(env.factory)
    template = next(r for r in ledger.rows(repo=ALPHA) if r.clean)
    for i, run_id in enumerate(("7" * 32, "8" * 32, "8" * 32)):
        d = template.to_dict()
        d.update(
            {
                "mode": "blind",
                "row_id": "",
                "prev_hash": "",
                "row_hash": "",
                "cost_usd": 0.5,
                "task_id": f"f{i:039d}",
                "run_id": run_id,
            }
        )
        # a row of 2.2 carried no posture of its own: only its run's stamp places it
        d["labels"] = {k: v for k, v in d["labels"].items() if not k.startswith(_POSTURE_KEYS)}
        d.pop("failure_kind", None)
        d.pop("cost_known", None)
        ledger.append(GradeRow.from_dict(dict_at_apparatus(d, "2.2")))
    d = env.get(f"/value?repo={ALPHA}&apparatus=2.2").json()
    assert (d["posture_class"], d["unqualified_posture"]) == (HOST, 2)
    assert d["north_star"]["n_attempts"] == 1
    assert env.get(f"/value?repo={ALPHA}&apparatus=2.2&posture={SEALED}").json()["rows"] == 0


def _add_legacy_runs(env: Env, n: int) -> None:
    """``n`` pre-2.3 runs the host graded, one blind row each, at apparatus 2.2."""
    from crb.store.models import Run

    with env.factory() as s:
        for i in range(n):
            s.add(
                Run(
                    id=f"9{i:031d}",
                    repo=ALPHA,
                    kind="replay",
                    status="succeeded",
                    apparatus_json={"executor": {"executor": "local"}},
                )
            )
        s.commit()
    ledger = DbLedger(env.factory)
    template = next(r for r in ledger.rows(repo=ALPHA) if r.clean)
    for i in range(n):
        d = template.to_dict()
        d.update(
            {
                "mode": "blind",
                "row_id": "",
                "prev_hash": "",
                "row_hash": "",
                "cost_usd": 0.5,
                "task_id": f"g{i:039d}",
                "run_id": f"9{i:031d}",
            }
        )
        d["labels"] = {k: v for k, v in d["labels"].items() if not k.startswith(_POSTURE_KEYS)}
        d.pop("failure_kind", None)
        d.pop("cost_known", None)
        ledger.append(GradeRow.from_dict(dict_at_apparatus(d, "2.2")))


def _run_selects(env: Env, path: str) -> tuple[int, dict[str, Any]]:
    """The ``SELECT``s on ``runs`` one request issues, and its body."""
    from sqlalchemy import event as sa_event

    engine = env.factory.kw["bind"]
    seen: list[str] = []

    def count(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        del conn, cursor, args
        if statement.lstrip().upper().startswith("SELECT") and "FROM runs" in statement:
            seen.append(statement)

    sa_event.listen(engine, "before_cursor_execute", count)
    try:
        r = env.get(path)
    finally:
        sa_event.remove(engine, "before_cursor_execute", count)
    assert r.status_code == 200, r.text
    return len(seen), r.json()


@pytest.mark.parametrize("apparatus", ["2.2", "current"])
def test_legacy_runs_are_read_in_one_batch_not_one_query_each(
    env: Env, tmp_path: Path, apparatus: str
) -> None:
    """A pre-2.3 row is placed by its run's stamp: the stamps a request needs are read in
    one batch, so the queries one ``/value`` issues do not grow with the ledger — and a run
    outside the apparatus read is never looked up at all."""
    path = f"/value?repo={ALPHA}&apparatus={apparatus}"
    _add_legacy_runs(env, 2)
    few, _ = _run_selects(env, path)
    with make_env(tmp_path / "many") as many_env:
        _add_legacy_runs(many_env, 12)
        many, body = _run_selects(many_env, path)
    assert many == few, (few, many)
    if apparatus == "2.2":
        assert body["north_star"]["n_attempts"] == 12


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
    # a row of 2.4 pins its failure kind as a label: the clone derives its own (a red row)
    # and belt 5 ran on it (ADR-0025 item 5: the lint reason says so)
    d["labels"] = {k: v for k, v in d["labels"].items() if k != "failure_kind"}
    d["labels"]["lint_reason"] = "evaluated"
    ledger.append(GradeRow.from_dict(with_posture_labels(d)))
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
