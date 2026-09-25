"""W3-B route contracts: ``POST /runs`` ``builder_config`` (stored under
``params.builder_config``, served on the run, identity/credential keys refused) and
``POST /repos`` URL policy for URL-only registrations (cloned by the worker later, so an
uncloneable source is refused at registration).

Navigation
----------
What it is:   The W3-B route contracts' test suite — ``POST /runs`` ``builder_config`` and
              ``POST /repos`` URL policy for URL-only registrations, plus the Claude Code model
              default and per-run retention.
What it does: Pins that ``builder_config`` is stored under ``params.builder_config`` and served
              (absent or empty means no key; identity and credential keys refused with 422;
              non-object 422), that URL-only registration accepts HTTPS and SSH and refuses
              uncloneable sources without echoing credentials while a URL beside a clone path is
              informational, that ``claude_code`` without a model gets the default, and that
              retention defaults to none and is stored under ``params.retain`` when asked
              (unknown keys 422).
How:          ``make_env`` over the seed with a recording jobs stand-in.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md
Works with:   src/crb/server/routes/runs.py and src/crb/server/routes/repos.py (under test),
              src/crb/core/git.py (the URL policy), tests/test_worker_clone.py (the worker's
              half: the clone and ``builder_config`` reaching the builder),
              tests/test_cli_repo_url.py (the CLI's half), docs/API.md
Tested by:    tests/test_server_routes_w3b.py
Touch when:   a builder gains a config key (decide here whether it is identity — refused — or
              config — stored); a retention key is added (ADR-0006).
"""

from __future__ import annotations

import os
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from crb.store.models import Run
from fixtures.server_seed import ALPHA, Env, envelope, login, make_env


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    """The seeded environment, logged in as OPERATOR, torn down after the test."""
    with make_env(tmp_path) as e:
        login(e.client, "operator")
        yield e


@pytest.fixture
def jobs(monkeypatch: pytest.MonkeyPatch) -> list[Run]:
    """A recording ``enqueue`` installed as ``crb.store.jobs``; returns the
    list of enqueued runs.
    """
    calls: list[Run] = []

    def enqueue(factory: Any, run: Run) -> Run:
        calls.append(run)
        with factory() as s:
            s.add(run)
            s.commit()
        return run

    mod = types.ModuleType("crb.store.jobs")
    mod.enqueue = enqueue  # type: ignore[attr-defined]
    mod.request_cancel = lambda factory, run_id, actor="": True  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "crb.store.jobs", mod)
    return calls


# --- POST /runs builder_config ---------------------------------------------------------------


class TestBuilderConfig:
    def test_stored_under_params_and_served(self, env: Env, jobs: list[Run]) -> None:
        cfg = {"auth": "cli", "effort": "high", "extra_args": ["--x"], "keep_transcript": True}
        r = env.post(
            "/runs",
            json={"repo": ALPHA, "kind": "replay", "builder": "claude_code", "builder_config": cfg},
        )
        assert r.status_code == 201, r.text
        assert r.json()["builder_config"] == cfg
        (run,) = jobs
        assert run.params_json["builder_config"] == cfg
        assert env.get(f"/runs/{run.id}").json()["builder_config"] == cfg

    def test_absent_or_empty_means_no_params_key(self, env: Env, jobs: list[Run]) -> None:
        r = env.post("/runs", json={"repo": ALPHA, "kind": "replay", "builder": "b"})
        assert r.status_code == 201 and r.json()["builder_config"] == {}
        r = env.post(
            "/runs", json={"repo": ALPHA, "kind": "replay", "builder": "b", "builder_config": {}}
        )
        assert r.status_code == 201 and r.json()["builder_config"] == {}
        assert all("builder_config" not in run.params_json for run in jobs)
        # seeded runs (written before the field existed) serve an empty object, never null
        seeded = env.get("/runs").json()["items"]
        assert seeded and all(isinstance(item["builder_config"], dict) for item in seeded)

    @pytest.mark.parametrize(
        ("cfg", "why"),
        [
            ({"model": "other"}, "recorded identity"),
            ({"provider": "other"}, "recorded identity"),
            ({"api_key": "sk-x"}, "credentials"),
            ({"anthropic_api_key": "x"}, "credentials"),
            ({"access_token": "x"}, "credentials"),
            ({"password": "x"}, "credentials"),
            ({"Effort": "high"}, "not a builder keyword"),
            ({"bad-key": 1}, "not a builder keyword"),
            ({"": 1}, "not a builder keyword"),
            ({f"k{i}": i for i in range(33)}, "more than 32 keys"),
            ({"big": "x" * 9000}, "exceeds 8192 bytes"),
        ],
    )
    def test_refused_keys_422(
        self, env: Env, jobs: list[Run], cfg: dict[str, Any], why: str
    ) -> None:
        r = env.post(
            "/runs", json={"repo": ALPHA, "kind": "replay", "builder": "b", "builder_config": cfg}
        )
        assert r.status_code == 422, r.text
        e = envelope(r)
        assert e["code"] == "validation_error"
        assert why in str(e["detail"]) or why in e["message"]
        assert jobs == []

    def test_non_object_422(self, env: Env, jobs: list[Run]) -> None:
        r = env.post(
            "/runs",
            json={"repo": ALPHA, "kind": "replay", "builder": "b", "builder_config": ["auth"]},
        )
        assert r.status_code == 422 and jobs == []


# --- POST /repos url policy ------------------------------------------------------------------


class TestRepoUrlPolicy:
    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/encode/httpx.git",
            "https://github.com/encode/httpx",
            "ssh://git@github.com/encode/httpx.git",
            "git@github.com:encode/httpx.git",
        ],
    )
    def test_url_only_accepts_https_and_ssh(self, env: Env, url: str) -> None:
        r = env.post("/repos", json={"name": "httpx", "language": "python", "url": f" {url} "})
        assert r.status_code == 201, r.text
        assert r.json()["url"] == url and r.json()["clone_path"] == ""

    @pytest.mark.parametrize(
        ("url", "why"),
        [
            ("file:///srv/repos/httpx", "scheme 'file'"),
            ("http://github.com/encode/httpx.git", "scheme 'http'"),
            ("git://github.com/encode/httpx.git", "scheme 'git'"),
            ("/srv/repos/httpx", "not a git URL"),
            ("https://github.com/", "no repository path"),
        ],
    )
    def test_url_only_refuses_uncloneable_sources(self, env: Env, url: str, why: str) -> None:
        r = env.post("/repos", json={"name": "httpx", "language": "python", "url": url})
        assert r.status_code == 422, r.text
        e = envelope(r)
        assert e["code"] == "validation_error" and why in str(e["detail"])
        assert env.get("/repos/httpx").status_code == 404

    def test_url_is_informational_with_a_clone_path(self, env: Env) -> None:
        """An existing clone plus a browse URL (no .git, http, whatever): nothing to clone,
        so nothing to police."""
        r = env.post(
            "/repos",
            json={
                "name": "local",
                "language": "python",
                "clone_path": "/srv/repos/local",
                "url": "http://intranet/projects/local",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["url"] == "http://intranet/projects/local"

    def test_refusal_never_echoes_credentials(self, env: Env) -> None:
        r = env.post(
            "/repos",
            json={"name": "x", "language": "python", "url": "http://alice:s3cretT0ken@host/x"},
        )
        assert r.status_code == 422 and "s3cretT0ken" not in r.text


# --- POST /runs model default for claude_code ---------------------------------------------


class TestClaudeCodeModelDefault:
    def test_claude_code_without_a_model_gets_the_default(
        self, env: Env, jobs: list[Run], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CRB_CLAUDE_CODE_MODEL", raising=False)
        # the default auth is api_key, and POST /runs refuses one with no key (P-003): this
        # case is about the model default, so the key is present — a placeholder, never real
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-placeholder-not-a-key")
        r = env.post("/runs", json={"repo": ALPHA, "kind": "replay", "builder": "claude_code"})
        assert r.status_code == 201, r.text
        assert r.json()["model"] == "claude-sonnet-5" and jobs[-1].model == "claude-sonnet-5"
        monkeypatch.setenv("CRB_CLAUDE_CODE_MODEL", "claude-opus-5")
        r = env.post("/runs", json={"repo": ALPHA, "kind": "blind", "builder": "claude_code"})
        assert r.status_code == 201 and r.json()["model"] == "claude-opus-5"
        # an explicit model always wins; other builders get no default
        r = env.post(
            "/runs",
            json={
                "repo": ALPHA,
                "kind": "replay",
                "builder": "claude_code",
                "model": "claude-opus-5",
            },
        )
        assert r.json()["model"] == "claude-opus-5"
        r = env.post("/runs", json={"repo": ALPHA, "kind": "replay", "builder": "editblock"})
        assert r.status_code == 201 and r.json()["model"] == ""
        r = env.post("/runs", json={"repo": ALPHA, "kind": "mine"})
        assert r.status_code == 201 and r.json()["model"] == ""


# --- POST /runs retain -----------------------------------------------------------------------


class TestRetain:
    """Per-run raw retention is the operator's call at queue time (ADR-0006 default: none)."""

    def test_default_is_no_retention_and_no_params_key(self, env: Env, jobs: list[Run]) -> None:
        r = env.post("/runs", json={"repo": ALPHA, "kind": "replay", "builder": "b"})
        assert r.status_code == 201, r.text
        assert r.json()["retain"] == {"worktrees": False, "transcripts": False}
        (run,) = jobs
        assert "retain" not in run.params_json

    def test_retain_stored_under_params_and_served(self, env: Env, jobs: list[Run]) -> None:
        r = env.post(
            "/runs",
            json={
                "repo": ALPHA,
                "kind": "replay",
                "builder": "b",
                "retain": {"worktrees": True, "transcripts": True},
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["retain"] == {"worktrees": True, "transcripts": True}
        (run,) = jobs
        assert run.params_json["retain"] == {"worktrees": True, "transcripts": True}
        assert env.get(f"/runs/{run.id}").json()["retain"]["worktrees"] is True

    def test_unknown_retain_key_422(self, env: Env, jobs: list[Run]) -> None:
        r = env.post(
            "/runs",
            json={"repo": ALPHA, "kind": "replay", "builder": "b", "retain": {"diffs": True}},
        )
        assert r.status_code == 422 and jobs == []
