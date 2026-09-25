"""The served worker's test-author rung — the deployment setting, the per-run override, the refusal.

Navigation
----------
What it is:   The test suite for the one thing the served worker adds to the factory loop's
              test author: resolving which rung authors the oracle, and refusing one that is
              also a build rung.
What it does: Pins that a deployment with no ``CRB_FACTORY__TEST_AUTHOR`` has no author (the
              state in which an item without an operator-authored test stops ``no_oracle``);
              that the setting produces an author whose identity is that rung label; that a
              run's ``params.test_author`` wins over the setting and that ``none`` in either
              place declines one; that an unregistered builder name is refused with the run's
              ladder named; and that the environment reaches ``WorkerSettings`` the way every
              other shared key does.
How:          ``Worker.__new__`` with only ``settings`` set (the resolution reads nothing
              else) and a ``RunContext`` over the ``pyrepo`` fixture; ``settings_from_args``
              for the environment path. No model call, no credential, no network.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/server/worker.py (``Worker._test_author``, ``_run_factory``),
              src/crb/server/worker_main.py (``settings_from_args`` — the environment),
              src/crb/server/settings.py (``FactorySettings``),
              src/crb/factory/author.py (the author this builds),
              tests/test_factory_author.py (the invariant at the ``FactorySpec`` boundary)
Tested by:    tests/test_worker_test_author.py
Touch when:   another factory deployment setting is added; the label spelling changes.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest

from crb.builders.base import EscalationLadder, Rung
from crb.factory.testfirst import author_label
from crb.observability.events import Emitter, MemorySink
from crb.server import worker as w
from crb.server import worker_main as wm
from crb.server.settings import FactorySettings, Settings
from crb.store.models import Run
from fixtures import pyrepo as pr

LADDER = EscalationLadder((Rung("editblock", "gpt-oss-120b"),))


def _worker(test_author: str = "") -> w.Worker:
    """A worker with nothing but its settings — all ``_test_author`` reads."""
    worker = w.Worker.__new__(w.Worker)
    worker.settings = w.WorkerSettings(
        home=Path(".crb"), factory=FactorySettings(test_author=test_author)
    )
    return worker


def _ctx(pyrepo: pr.PyRepo, sink: MemorySink, **params: Any) -> w.RunContext:
    run = Run(
        id="r" * 32, repo="pyrepo", kind="factory", actor="operator:1", params_json=dict(params)
    )
    return w.RunContext(
        run=run,
        emitter=Emitter(sink, trace_id=run.id, actor=run.actor, repo="pyrepo"),
        config=pyrepo.config,
        git=pyrepo.repo,
    )


def test_a_deployment_with_no_setting_has_no_test_author(pyrepo: pr.PyRepo) -> None:
    """The state this product shipped in: no author, so an item with no operator-authored
    oracle stops ``no_oracle`` (tests/test_factory_loop.py::test_no_oracle_when_no_test_and_no_author)."""
    sink = MemorySink()
    assert _worker()._test_author(_ctx(pyrepo, sink), LADDER) is None
    assert [e.action for e in sink.events] == []


def test_the_deployment_setting_names_the_author_rung(pyrepo: pr.PyRepo) -> None:
    sink = MemorySink()
    author = _worker("openai_agent:qwen-3-coder")._test_author(_ctx(pyrepo, sink), LADDER)
    assert author is not None and author_label(author) == "openai_agent:qwen-3-coder"
    assert author.provider == "cerebras"
    # the run's trace says which identity will write the oracle, before it writes one
    (configured,) = [e for e in sink.events if e.action == "author.configured"]
    assert configured.payload == {"author": "openai_agent:qwen-3-coder"}


def test_a_run_overrides_the_deployments_author_and_can_decline_one(pyrepo: pr.PyRepo) -> None:
    worker = _worker("openai_agent:qwen-3-coder")
    sink = MemorySink()
    author = worker._test_author(_ctx(pyrepo, sink, test_author="editblock:m2"), LADDER)
    assert author is not None and author_label(author) == "editblock:m2"
    # `none` on the run declines the deployment's author — this run pays for no authoring
    assert worker._test_author(_ctx(pyrepo, sink, test_author="none"), LADDER) is None


def test_a_rung_that_is_not_a_registered_builder_is_refused_with_the_ladder_named(
    pyrepo: pr.PyRepo,
) -> None:
    sink = MemorySink()
    with pytest.raises(ValueError, match="is not a builder name") as exc:
        _worker("wishful:m1")._test_author(_ctx(pyrepo, sink), LADDER)
    assert "editblock:gpt-oss-120b" in str(exc.value)


def test_the_run_provider_is_the_authors_default_provider(pyrepo: pr.PyRepo) -> None:
    sink = MemorySink()
    ctx = _ctx(pyrepo, sink)
    ctx.run.provider = "azure"
    author = _worker("editblock:m1")._test_author(ctx, LADDER)
    assert author is not None and author.provider == "azure"


# --- the environment ------------------------------------------------------------------


def test_the_environment_reaches_worker_settings_like_every_other_shared_key() -> None:
    args = argparse.Namespace(
        home="",
        executor="",
        image="",
        kinds="factory",
        database_url="",
        worker_id="",
        poll=2.0,
        heartbeat=10.0,
        stale_after=120.0,
        keep_worktrees=False,
        metrics_port=None,
        metrics_host="",
    )
    settings = wm.settings_from_args(args, env={"CRB_FACTORY__TEST_AUTHOR": "editblock:m1"})
    assert settings.factory.test_author == "editblock:m1"
    # a label that is not a rung at all fails at start-up, not half-way through a paid run
    with pytest.raises(Exception, match="builder:model"):
        wm.settings_from_args(args, env={"CRB_FACTORY__TEST_AUTHOR": "gpt-oss-120b"})


def test_the_settings_view_shows_an_absent_author_as_none() -> None:
    # the view also carries the delivery-licence posture (ADR-0018), default on
    assert FactorySettings().redacted() == {"test_author": "none", "require_signed_cell": True}
    assert FactorySettings(test_author=" editblock:m1 ").redacted() == {
        "test_author": "editblock:m1",
        "require_signed_cell": True,
    }
    # and it reaches what `GET /settings` serves as `raw` — an operator can read which rung
    # will write the test without opening the worker's environment
    view = Settings(env="dev", factory=FactorySettings(test_author="editblock:m1")).redacted_dict()
    assert view["factory"] == {"test_author": "editblock:m1", "require_signed_cell": True}
