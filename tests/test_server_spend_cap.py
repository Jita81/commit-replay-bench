"""``POST /runs`` with a spend cap (F5b): stored, served, and refused when it could not be kept.

A run declares ``max_cost_usd``, the most its attempts may cost together; the worker keeps it
(tests/test_worker_spend_cap.py). The API's half: a build kind stores it as
``params.max_cost_usd`` and serves it as ``max_cost_usd`` on the run; a cap on a kind that
makes no attempt, or a cap that is not a positive amount, is a 422; a capped run with a rung
whose model has no known price is refused 422 ``spend_cap_unpriced`` with nothing queued,
because the cap could not see what that rung spends; and a run the cap stopped serves
``counts.stopped_code: spend_cap`` with its reason.

Navigation
----------
What it is:   The route suite for the per-run spend cap.
What it does: Pins the stored parameter and the served field, the 422 bounds, the unpriced
              refusal (and that the same run without a cap, or with the model priced through
              ``CRB_PRICING_JSON``, is queued), and the served stop code for a replay and a
              factory run.
How:          ``make_env`` over the seed and ``FakeJobs`` from the runs route suite.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/server/routes/runs.py (under test), src/crb/server/schemas.py
              (``RunCreateRequest.max_cost_usd``, ``RunOut.max_cost_usd``,
              ``RunCounts.stopped_code``), src/crb/server/spend_cap.py (``unpriced_rungs``),
              docs/API.md (the field and the error)
Tested by:    tests/test_server_spend_cap.py
Touch when:   never for a new repository; the cap's request field, its bounds or its refusal change.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from crb.store.models import Run
from fixtures.server_seed import ALPHA, Env, envelope, login, make_env
from test_server_routes_runs import FakeJobs, _no_ambient_crb_env

__all__ = ["_no_ambient_crb_env"]  # the runs suite's autouse fixture, applied here too

PRICED = {"repo": ALPHA, "kind": "replay", "builder": "editblock", "model": "gpt-oss-120b"}


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path) as e:
        yield e


@pytest.fixture
def jobs(monkeypatch: pytest.MonkeyPatch) -> FakeJobs:
    return FakeJobs().install(monkeypatch)


def test_a_capped_build_run_stores_and_serves_its_cap(env: Env, jobs: FakeJobs) -> None:
    login(env.client, "operator")
    r = env.post("/runs", json={**PRICED, "max_cost_usd": 12.5})
    assert r.status_code == 201, r.text
    assert jobs.enqueued[0].params_json["max_cost_usd"] == 12.5
    assert r.json()["max_cost_usd"] == 12.5
    plain = env.post("/runs", json=PRICED)
    assert plain.status_code == 201 and plain.json()["max_cost_usd"] is None
    assert "max_cost_usd" not in jobs.enqueued[1].params_json


@pytest.mark.parametrize("bad", [0, -1, "x"])
def test_a_cap_that_is_not_a_positive_amount_is_refused(
    env: Env, jobs: FakeJobs, bad: object
) -> None:
    login(env.client, "operator")
    r = env.post("/runs", json={**PRICED, "max_cost_usd": bad})
    assert r.status_code == 422 and jobs.enqueued == []


def test_a_cap_on_a_kind_that_makes_no_attempt_is_refused(env: Env, jobs: FakeJobs) -> None:
    login(env.client, "operator")
    r = env.post("/runs", json={"repo": ALPHA, "kind": "mine", "max_cost_usd": 5})
    assert r.status_code == 422, r.text
    assert "max_cost_usd applies to build runs only" in r.text and jobs.enqueued == []


def test_a_capped_run_with_an_unpriced_rung_is_refused_with_nothing_queued(
    env: Env, jobs: FakeJobs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cap sums what the attempts cost; a model with no known price reports no cost, so
    a cap over it could never stop the run. Uncapped, the same run is queued (its rows say
    their cost is unknown); priced through CRB_PRICING_JSON, it is queued capped."""
    login(env.client, "operator")
    body = {**PRICED, "ladder": ["r1", "openai_agent:mystery-model"], "max_cost_usd": 5}
    r = env.post("/runs", json=body)
    assert r.status_code == 422, r.text
    err = envelope(r)
    assert err["code"] == "spend_cap_unpriced" and "mystery-model" in err["message"]
    assert err["detail"]["rungs"] == [{"builder": "openai_agent", "model": "mystery-model"}]
    assert jobs.enqueued == []
    body.pop("max_cost_usd")
    assert env.post("/runs", json=body).status_code == 201
    table = tmp_path / "pricing.json"
    table.write_text(json.dumps({"mystery-model": {"input_per_m": 1, "output_per_m": 2}}))
    monkeypatch.setenv("CRB_PRICING_JSON", str(table))
    assert env.post("/runs", json={**body, "max_cost_usd": 5}).status_code == 201


def test_a_run_the_cap_stopped_serves_the_stop_code(env: Env) -> None:
    reason = "spend cap: $0.80 of $1.00 spent; the next attempt could cost up to …"
    with env.factory() as s:
        for rid, kind, counts in (
            ("5a" * 16, "replay", {"tasks": 1, "rows": 2, "stopped_reason": reason}),
            ("5b" * 16, "factory", {"items": 1, "done": 0, "stopped_reason": reason}),
        ):
            s.add(
                Run(
                    id=rid,
                    repo=ALPHA,
                    kind=kind,
                    status="failed",
                    error=reason,
                    params_json={"max_cost_usd": 1.0},
                    counts_json={**counts, "stopped_code": "spend_cap"},
                )
            )
        s.commit()
    for rid in ("5a" * 16, "5b" * 16):
        out = env.get(f"/runs/{rid}").json()
        assert out["max_cost_usd"] == 1.0
        assert out["counts"]["stopped_code"] == "spend_cap"
        assert out["counts"]["stopped_reason"] == reason


def test_a_capped_factory_run_whose_test_author_is_unpriced_is_refused(
    env: Env, jobs: FakeJobs
) -> None:
    """The test author calls a model too, and its calls are the run's spend: a capped
    factory run whose author — named on the run, or the deployment's — has no known price
    is refused like an unpriced rung, with nothing queued. A priced author passes this
    gate (and meets the next one: no frozen backlog is registered here)."""
    from crb.server.settings import FactorySettings

    login(env.client, "operator")
    body = {"repo": ALPHA, "kind": "factory", "builder": "editblock", "model": "gpt-oss-120b"}
    r = env.post("/runs", json={**body, "max_cost_usd": 5, "test_author": "editblock:mystery"})
    assert r.status_code == 422, r.text
    err = envelope(r)
    assert err["code"] == "spend_cap_unpriced" and "editblock:mystery" in err["message"]
    assert jobs.enqueued == []
    bare = env.post("/runs", json={**body, "max_cost_usd": 5, "test_author": "editblock:m"})
    assert bare.status_code == 422 and "editblock:m " in envelope(bare)["message"]
    ok = env.post(
        "/runs", json={**body, "max_cost_usd": 5, "test_author": "openai_agent:gpt-oss-120b-x"}
    )
    assert envelope(ok)["code"] == "no_frozen_backlog", ok.text
    env.settings.factory = FactorySettings(test_author="openai_agent:mystery")
    r = env.post("/runs", json={**body, "max_cost_usd": 5})
    assert r.status_code == 422 and "openai_agent:mystery" in envelope(r)["message"]
    declined = env.post("/runs", json={**body, "max_cost_usd": 5, "test_author": "none"})
    assert envelope(declined)["code"] == "no_frozen_backlog", declined.text
    uncapped = env.post("/runs", json=body)
    assert envelope(uncapped)["code"] == "no_frozen_backlog", uncapped.text
