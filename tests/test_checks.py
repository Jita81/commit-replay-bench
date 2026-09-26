"""crb.core.checks — the one per-repository switchboard, and the API that writes it.

Navigation
----------
What it is:   The suite for ``RepoConfig.checks`` / ``RepoChecks`` / ``resolve`` and the two API
              surfaces that write them (``PUT /repos/{name}`` and ``POST /runs``).
What it does: Pins that every switch is OFF by default; that the run beats the repository and
              the repository beats the default, with the source named; that an unknown key or
              a wrong type is refused at config time (never a silent default); that the row
              label and the configuration version are stable; that a repository write lands
              in the config and on the audit trail, and a run's override lands in
              ``params.checks`` with only the fields set.
How:          The dataclasses directly; the seeded server (``fixtures.server_seed``) for the
              routes, with the queue faked.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0024-working-by-construction.md
Works with:   src/crb/core/checks.py (under test), src/crb/core/spec.py (``RepoConfig.checks``),
              src/crb/server/schemas.py (the request shapes), src/crb/server/routes/repos.py and
              src/crb/server/routes/runs.py (the writers)
Tested by:    tests/test_checks.py
Touch when:   a switch is added to the surface or its resolution rule changes.
"""

from __future__ import annotations

import os
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from crb.core.checks import (
    SOURCE_DEFAULT,
    SOURCE_REPO,
    SOURCE_RUN,
    CheckCommand,
    RepoChecks,
    resolve,
)
from crb.core.spec import Language, RepoConfig
from crb.server.routes.runs import system_trace_id
from crb.store.models import Event, Run
from fixtures.server_seed import ALPHA, Env, envelope, login, make_env


def test_every_switch_is_off_by_default_and_the_default_has_a_named_version() -> None:
    r = resolve(RepoChecks.from_config(None), None)
    assert (r.format_step, r.finish_gate, r.api_stable) == (False, False, False)
    assert not r.any_on and r.repo.is_default and r.repo.version == "default"
    assert r.label() == "fmt=0:default;gate=0:default;api=0:default;cfg=default"
    assert RepoConfig(name="x", language=Language.GO).checks == {}


def test_run_beats_repository_beats_default_and_names_the_source() -> None:
    repo = RepoChecks.from_config({"format_step": True, "finish_gate": True})
    r = resolve(repo, {"finish_gate": False, "api_stable": True})
    assert (r.format_step, r.finish_gate, r.api_stable) == (True, False, True)
    assert r.sources == {
        "format_step": SOURCE_REPO,
        "finish_gate": SOURCE_RUN,
        "api_stable": SOURCE_RUN,
    }
    assert r.label().startswith("fmt=1:repo;gate=0:run;api=1:run;cfg=")
    assert r.to_dict()["config_version"] == repo.version and len(repo.version) == 12
    assert resolve(repo, {"format_step": None}).sources["format_step"] == SOURCE_REPO
    assert resolve(RepoChecks(), {}).sources["api_stable"] == SOURCE_DEFAULT


@pytest.mark.parametrize(
    "raw",
    [
        {"bogus": True},
        {"format_step": "yes"},
        {"commands": [{"name": "vet", "argv": "go vet ./..."}]},
        {"commands": [{"name": "Vet!", "argv": ["go", "vet"]}]},
        {"commands": [{"name": "vet", "argv": ["go"], "extra": 1}]},
        {"commands": [{"name": "a", "argv": ["x"]}, {"name": "a", "argv": ["y"]}]},
        {"finish_repair_turns": 9},
        {"finish_repair_turns": True},
        {"formatter": {"command": "black"}},
        {"formatter": {"command": ["black"], "flags": 1}},
    ],
)
def test_a_malformed_block_is_refused_at_config_time(raw: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        RepoChecks.from_config(raw)
    with pytest.raises(ValueError):
        RepoConfig(name="x", language=Language.PYTHON, checks=raw)


def test_run_params_refuse_an_unknown_switch() -> None:
    with pytest.raises(ValueError, match="unknown"):
        resolve(RepoChecks(), {"lint_step": True})


def test_the_block_round_trips_through_repo_config_and_its_version_is_content_addressed() -> None:
    raw = {
        "finish_gate": True,
        "commands": [{"name": "vet", "argv": ["go", "vet", "./..."]}],
        "formatter": {"disabled": True},
    }
    cfg = RepoConfig.from_dict("cobra", {"language": "go", "checks": raw})
    again = RepoConfig.from_dict("cobra", cfg.to_dict())
    a, b = RepoChecks.from_config(cfg.checks), RepoChecks.from_config(again.checks)
    assert a == b and a.version == b.version
    assert a.commands == (CheckCommand("vet", ("go", "vet", "./...")),)
    assert RepoChecks.from_config({**raw, "api_stable": True}).version != a.version


# --- the API that writes it ------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)
    # POST /runs refuses a builder whose key variable is unset (P-003): the OpenAI-compatible
    # builders' key is PRESENT here — a placeholder, never a real key
    monkeypatch.setenv("CEREBRAS_API_KEY", "csk-test-placeholder-not-a-key")


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path) as e:
        yield e


def test_put_repo_checks_is_stored_validated_and_on_the_audit_trail(env: Env) -> None:
    block = {"format_step": True, "commands": [{"name": "vet", "argv": ["go", "vet", "./..."]}]}
    r = env.put(f"/repos/{ALPHA}", json={"checks": block})
    assert r.status_code == 200, r.text
    stored = r.json()["config"]["checks"]
    assert stored["format_step"] is True and stored["commands"][0]["argv"] == ["go", "vet", "./..."]
    with env.factory() as s:
        ev = list(
            s.execute(
                select(Event)
                .where(Event.trace_id == system_trace_id("repo", ALPHA))
                .order_by(Event.seq)
            ).scalars()
        )[-1]
    assert ev.action == "repo.updated" and ev.payload_json["fields"] == ["checks"]
    bad = env.put(f"/repos/{ALPHA}", json={"checks": {"format_step": "yes"}})
    assert bad.status_code == 422 and envelope(bad)["code"] == "validation_error"


def test_post_run_stores_only_the_switches_it_sets(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    enqueued: list[Run] = []
    mod = types.ModuleType("crb.store.jobs")

    def enqueue(factory: Any, run: Run) -> Run:
        enqueued.append(run)
        with factory() as s:
            s.add(run)
            s.commit()
        return run

    mod.enqueue = enqueue  # type: ignore[attr-defined]
    mod.request_cancel = lambda *a, **k: True  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "crb.store.jobs", mod)
    login(env.client, "operator")
    body = {"repo": ALPHA, "kind": "blind", "builder": "editblock", "model": "m"}
    r = env.post("/runs", json={**body, "checks": {"finish_gate": True, "api_stable": None}})
    assert r.status_code == 201, r.text
    assert enqueued[-1].params_json["checks"] == {"finish_gate": True}
    r = env.post("/runs", json=body)
    assert r.status_code == 201 and "checks" not in enqueued[-1].params_json
    r = env.post("/runs", json={**body, "checks": {"lint_step": True}})
    assert r.status_code == 422
