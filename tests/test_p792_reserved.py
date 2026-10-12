"""P-792: an admitted attempt decides its commit, and nothing a run chooses after admission
can steer which commits leave a reading or what a row says.

docs/PREVENTION.md P-792 (and G-982) records the finding: a round-5 enumeration of the Wave 3
reading found nineteen channels (C1 to C19) through which an operator could choose which
commits leave a campaign reading, or what an admitted row says. The round-5 design spec for
closing them names one test per channel, each reproducing the enumeration's probe and failing
before its fix; this file holds them as the fixes land, one step at a time.

C3 (``builder_config``): a run's ``builder_config`` can carry ``extra_args``, which the Claude
Code builder appends to its argv after the rung's own ``--model`` and ``--max-turns``, and a
``claude_binary``, which replaces the CLI it runs. Part (c) is that the apparatus stamp names
both when they are set, so a row cannot describe the rung's model while the argv ran another.
Parts (a) and (b), the refusals at submit and at claim, are added to the same test later.

Navigation
----------
What it is:   The P-792 channel tests — one per channel the round-5 enumeration found, each
              failing on the code before its fix.
What it does: C3(c): pins that ``ClaudeCodeBuilder.describe()`` names ``extra_args`` and
              ``claude_binary`` when they are set, that the named ``extra_args`` are exactly
              the argv's tail (the overriding ``--model``), and that a builder with neither
              set describes itself byte for byte as it did before.
How:          Builds the builder directly with the worker's ``CRB_CLAUDE_CODE_*`` defaults
              cleared, and reads its argv for the fixture task from
              ``fixtures.builders_repo``; no model call, no store.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/builders/claude_code.py (``describe`` and ``argv``, under test),
              tests/test_builders_claude_code.py (the builder's own suite),
              tests/fixtures/builders_repo.py (the task the argv is built for),
              docs/PREVENTION.md (P-792, the row these tests close)
Tested by:    tests/test_p792_reserved.py
Touch when:   never for a new repository; a P-792 channel's fix lands (its test goes here,
              failing first), or a builder gains a constructor option that shapes its argv
              (the stamp names it when set, and ``DEFAULT_STAMP`` stays unchanged).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crb.builders import base
from crb.builders import claude_code as cc
from fixtures.builders_repo import make_fixture

#: What a default Claude Code builder's stamp held before the override keys existed, in its
#: key order: a stamp with neither override set must stay byte-identical to this.
DEFAULT_STAMP = (
    '{"builder": "claude_code", "model": "claude-sonnet-5", "provider": "anthropic", '
    '"process": "claude -p stream-json, tools=Read,Edit,Bash", "effort": "default", '
    '"bare": true, "auth": "api_key"}'
)


@pytest.fixture(autouse=True)
def _worker_defaults_cleared(monkeypatch: pytest.MonkeyPatch) -> None:
    """The builder reads its model and auth defaults from the worker's environment."""
    monkeypatch.delenv(cc.MODEL_ENV, raising=False)
    monkeypatch.delenv(cc.AUTH_ENV, raising=False)


def test_p792_c3_builder_config_refused_and_described(tmp_path: Path) -> None:
    """C3(c): reproduces the describe half of the enumeration's probe
    ``test_builder_config_extra_args_validates_and_overrides_argv``, which found the argv
    carrying a second ``--model`` while ``describe()`` named only the rung's."""
    extra = ["--model", "x"]
    b = cc.ClaudeCodeBuilder(extra_args=extra, claude_binary="/opt/claude")
    d = b.describe()
    assert d["extra_args"] == ["--model", "x"]
    assert d["claude_binary"] == "/opt/claude"
    # the stamp still names the rung's model; the override beside it is what the argv ran
    assert d["model"] == "claude-sonnet-5"
    fx = make_fixture(tmp_path)
    brief = base.BuildBrief.from_task(fx.task, config=fx.config, test_command="pytest")
    argv = b.argv(brief, base.Budget(max_turns=7, max_tool_calls=25), tmp_path / "wt")
    models = [argv[i + 1] for i, a in enumerate(argv) if a == "--model"]
    assert models == ["claude-sonnet-5", "x"]
    assert argv[-len(extra) :] == d["extra_args"]
    # the stamp is JSON: a list, not the tuple the builder keeps
    assert json.loads(json.dumps(d)) == d


def test_p792_describe_unchanged_when_unset() -> None:
    """With neither override set, no existing stamp changes: same keys, same order, same
    values; and an empty ``extra_args`` or ``claude_binary`` is the same as unset."""
    assert json.dumps(cc.ClaudeCodeBuilder().describe()) == DEFAULT_STAMP
    assert json.dumps(cc.ClaudeCodeBuilder(extra_args=[], claude_binary="").describe()) == (
        DEFAULT_STAMP
    )
    sealed = cc.ClaudeCodeBuilder(workdir_alias="/work/").describe()
    assert json.dumps(sealed) == DEFAULT_STAMP[:-1] + ', "container_workdir": "/work"}'
