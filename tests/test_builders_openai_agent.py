"""The in-process tool loop: guards through tools, budget caps, the loop producing an
edit the core grader marks clean, and the OpenAI-compatible client's retry/metering.

Navigation
----------
What it is:   The in-process tool-loop builder's test suite — guards through tools, budget caps,
              the loop producing an edit the grader marks clean, and the OpenAI-compatible
              client's retry and metering.
What it does: Pins that edit-then-green is graded clean, that blind mode offers no test tool and
              holds out the oracle, that test writes are refused via tools in both modes, the
              ``run_command`` allowlist (archaeology and network refused; a tamper through an
              allowed command is caught post hoc), every cap (turns, tool calls mid-turn, cost,
              tokens, wall clock), model errors and nudges, malformed tool arguments and unknown
              tools, file paging and search, the opt-in redacted transcript, the tool schema; and
              the client's retry-then-meter, non-retryable and exhausted paths, tolerant tool-call
              parsing, Azure deployments and the missing-credential model error. The ``live``
              case spends real tokens.
How:          ``ScriptedModel`` returns scripted turns and records the history; ``FakeClient``
              mimics ``chat.completions.create``; ``fixtures.builders_repo`` for the build.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/builders/openai_agent.py (under test), src/crb/builders/openai_client.py
              (the transport), src/crb/builders/base.py (guards and budget),
              src/crb/builders/budget.py (the caps), tests/fixtures/builders_repo.py
Tested by:    tests/test_builders_openai_agent.py
Touch when:   a tool is added to the loop (a schema case, a guard case if it can write or run,
              and a cap case if it counts); a provider's error shape changes the retry rule.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from crb.builders import base
from crb.builders import budget as bud
from crb.builders import openai_client as oc
from crb.builders.openai_agent import RUN_COMMAND_ALLOWLIST, OpenAIAgentBuilder, tool_schema
from crb.core.execution import LocalExecutor
from crb.core.grade import grade
from crb.core.runners import get_runner

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
if str(_FIXTURES) not in sys.path:
    sys.path.insert(0, str(_FIXTURES))
from builders_repo import make_fixture  # noqa: E402

# ---------------------------------------------------------------------------
# Scripted model
# ---------------------------------------------------------------------------


def call(name: str, **args: Any) -> oc.ToolCall:
    """A ``ToolCall`` with a deterministic id derived from its name and arguments — a
    stable digest, not ``hash()`` (which varies with ``PYTHONHASHSEED``), and wide enough
    that five calls in one turn cannot collide."""
    digest = hashlib.sha256(f"{name}:{json.dumps(args, sort_keys=True)}".encode()).hexdigest()
    return oc.ToolCall(
        id=f"c{digest[:12]}",
        name=name,
        arguments=args,
    )


def turn(
    *calls: oc.ToolCall, content: str = "", tokens: tuple[int, int] = (100, 20)
) -> oc.ModelTurn:
    """A scripted ``ModelTurn``: tool calls, optional content, and the token
    counts the meter sums.
    """
    return oc.ModelTurn(
        content=content, tool_calls=calls, tokens_in=tokens[0], tokens_out=tokens[1]
    )


class ScriptedModel:
    """Returns scripted turns; records the message history and the tools offered."""

    def __init__(self, turns: list[Any]) -> None:
        self.turns = list(turns)
        self.histories: list[list[dict[str, Any]]] = []
        self.live: list[dict[str, Any]] = []  # the loop's own message list (appended in place)
        self.tools_seen: list[list[str]] = []

    def __call__(self, messages: list[dict[str, Any]], tools: Any) -> oc.ModelTurn:
        self.live = messages
        self.histories.append([dict(m) for m in messages])
        self.tools_seen.append([t["function"]["name"] for t in tools or ()])
        if not self.turns:
            raise RuntimeError("scripted model exhausted")
        t = self.turns.pop(0)
        if isinstance(t, Exception):
            raise t
        return t  # type: ignore[no-any-return]

    def tool_results(self) -> list[str]:
        return [str(m["content"]) for m in self.live if m.get("role") == "tool"]


def _setup(
    tmp_path: Path,
    turns: list[Any],
    *,
    mode: str = "sighted",
    budget: base.Budget | None = None,
    **kw: Any,
):
    fx = make_fixture(tmp_path)
    ws = fx.workspace(tmp_path / "wt", mode=mode)
    brief = base.BuildBrief.from_task(fx.task, mode=mode, config=fx.config)
    model = ScriptedModel(turns)
    builder = OpenAIAgentBuilder(model="gpt-oss-120b", provider="cerebras", model_fn=model, **kw)
    out = builder.build(
        ws, brief, budget or base.Budget(max_turns=8, max_tool_calls=10, wall_clock_s=120)
    )
    return fx, ws, model, out


# ---------------------------------------------------------------------------
# Happy path: explore → edit → tests green → grader clean
# ---------------------------------------------------------------------------


def test_loop_edit_then_green_is_graded_clean(tmp_path: Path) -> None:
    fx, ws, model, out = _setup(
        tmp_path,
        [
            turn(call("run_target_tests")),
            turn(call("search_repo", pattern="def add"), call("read_file", path="pkg/calc.py")),
            turn(
                call(
                    "apply_edit",
                    path="pkg/calc.py",
                    search="    return a - b",
                    replace="    return a + b",
                )
            ),
            turn(call("run_target_tests")),
            turn(content="should not be reached"),
        ],
    )
    assert out.done and out.stop_reason == base.STOP_DONE and out.errors == ()
    assert out.turns == 4 and out.tool_calls == 5
    assert out.tokens_in == 400 and out.tokens_out == 80
    assert out.cost_usd == pytest.approx(400 * 0.25e-6 + 80 * 0.69e-6)
    assert out.extra["target_green_claim"] is True
    results = model.tool_results()
    assert results[0].startswith("TESTS STILL FAILING")
    assert "pkg/calc.py:1:def add" in results[1]
    assert "return a - b" in results[2]
    assert results[3].startswith("OK: edited")
    assert results[4].startswith("ALL TESTS PASS")
    assert "run_target_tests" in model.tools_seen[0]
    res = grade(
        ws, fx.task, config=fx.config, runner=get_runner(fx.config), executor=LocalExecutor()
    )
    assert res.clean, res.to_dict()
    ws.remove()


def test_blind_mode_has_no_test_tool_and_holds_out_oracle(tmp_path: Path) -> None:
    fx, ws, model, out = _setup(
        tmp_path,
        [
            turn(call("list_files", glob="tests/*.py")),
            turn(call("run_target_tests")),
            turn(
                call(
                    "apply_edit", path="pkg/calc.py", search="return a - b", replace="return a + b"
                )
            ),
            turn(content="Fixed add() to add."),
        ],
        mode="blind",
    )
    assert "run_target_tests" not in model.tools_seen[0]
    results = model.tool_results()
    assert "test_calc" not in results[0] and "test_util.py" in results[0]
    assert "held out" in results[1]
    assert out.done and out.stop_reason == base.STOP_DONE and out.summary == "Fixed add() to add."
    res = grade(
        ws,
        fx.task,
        config=fx.config,
        runner=get_runner(fx.config),
        executor=LocalExecutor(),
        mode="blind",
    )
    assert res.clean, res.to_dict()
    ws.remove()


# ---------------------------------------------------------------------------
# Guards through the tools
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["sighted", "blind"])
def test_test_writes_refused_via_tools(tmp_path: Path, mode: str) -> None:
    _fx, ws, model, out = _setup(
        tmp_path,
        [
            turn(
                call("apply_edit", path="tests/test_calc.py", search="== 5", replace="== -1"),
                call("write_file", path="tests/test_new.py", content="def test_x(): pass\n"),
                call("write_file", path="tests/conftest.py", content="x=1\n"),
                call("write_file", path="../escape.py", content="x=1\n"),
                call("write_file", path="/tmp/abs.py", content="x=1\n"),
                call("write_file", path=".git/hooks/pre-commit", content="#!/bin/sh\n"),
                call("read_file", path=".git/HEAD"),
            ),
            turn(content="giving up"),
            turn(content="really"),
            turn(content="really giving up"),
        ],
        mode=mode,
    )
    results = model.tool_results()
    assert all(r.startswith("ERROR") for r in results), results
    assert ("immutable" in results[0]) if mode == "sighted" else ("test file" in results[0])
    assert "test file" in results[1] and "test file" in results[2]
    assert (
        "escapes" in results[3]
        and "absolute" in results[4]
        and ".git" in results[5]
        and ".git" in results[6]
    )
    assert not (ws.root / "tests" / "test_new.py").exists()
    assert not (tmp_path / "escape.py").exists()
    assert not out.done and out.stop_reason == base.STOP_NO_TOOL_CALL
    assert out.errors == ()  # prevented, so no violation is recorded
    assert len(out.extra["refused"]) == 6
    ws.remove()


def test_run_command_allowlist_archaeology_and_network(tmp_path: Path) -> None:
    _fx, ws, model, out = _setup(
        tmp_path,
        [
            turn(
                call("run_command", argv=["git", "log", "--oneline"]),
                call("run_command", argv=["curl", "https://example.com"]),
                call("run_command", argv=["sed", "-i", "s/a/b/", "pkg/calc.py"]),
                call("run_command", argv=["git", "status", "--short"]),
                call("run_command", argv=["cat", ".git/HEAD"]),
                call("run_command", argv="git diff"),
            ),
            turn(content="done"),
        ],
    )
    results = model.tool_results()
    assert results[0].startswith("REFUSED: archaeology")
    assert results[1].startswith("REFUSED: network")
    assert results[2].startswith("REFUSED") and "sed" in results[2]
    assert results[3].startswith("[rc=0]")
    assert results[4].startswith("REFUSED") and ".git" in results[4]
    assert results[5].startswith("[rc=0]")
    # attempted archaeology/network is a recorded protocol violation (fail closed)
    assert any(e.startswith("archaeology:") for e in out.errors)
    assert any(e.startswith("network:") for e in out.errors)
    assert out.violated
    assert "sed" not in RUN_COMMAND_ALLOWLIST
    ws.remove()


def test_tamper_via_allowed_command_is_caught_post_hoc(tmp_path: Path) -> None:
    prog = "open('tests/test_calc.py','w').write('def test_add():\\n    pass\\n')"
    fx, ws, _model, out = _setup(
        tmp_path,
        [
            turn(call("run_command", argv=[sys.executable, "-c", prog])),
            turn(
                call(
                    "apply_edit", path="pkg/calc.py", search="return a - b", replace="return a + b"
                )
            ),
            turn(content="done"),
        ],
    )
    assert not out.done
    assert any(e.startswith("tamper:") and "tests/test_calc.py" in e for e in out.errors)
    res = grade(
        ws, fx.task, config=fx.config, runner=get_runner(fx.config), executor=LocalExecutor()
    )
    assert res.disqualified and not res.clean
    ws.remove()


# ---------------------------------------------------------------------------
# Budgets stop the loop with the recorded reason
# ---------------------------------------------------------------------------


def test_turn_cap(tmp_path: Path) -> None:
    _fx, ws, _model, out = _setup(
        tmp_path,
        [turn(call("read_file", path="pkg/calc.py")) for _ in range(10)],
        budget=base.Budget(max_turns=3, max_tool_calls=50),
    )
    assert out.stop_reason == base.STOP_MAX_TURNS and out.turns == 3 and not out.done
    ws.remove()


def test_tool_call_cap_mid_turn(tmp_path: Path) -> None:
    _fx, ws, model, out = _setup(
        tmp_path,
        [turn(*[call("read_file", path="pkg/calc.py", start_line=i + 1) for i in range(5)])],
        budget=base.Budget(max_turns=5, max_tool_calls=3),
    )
    assert out.stop_reason == base.STOP_MAX_TOOL_CALLS and out.tool_calls == 3
    results = model.histories  # every tool call still got a tool message (protocol-valid history)
    assert results
    ws.remove()


def test_cost_cap_and_token_cap(tmp_path: Path) -> None:
    big = [turn(call("read_file", path="pkg/calc.py"), tokens=(200_000, 1_000)) for _ in range(5)]
    _fx, ws, _model, out = _setup(tmp_path, big, budget=base.Budget(max_cost_usd=0.02))
    assert out.stop_reason == base.STOP_MAX_COST and out.turns == 1
    _fx2, ws2, _model2, out2 = _setup(
        tmp_path / "b", list(big), budget=base.Budget(max_tokens=150_000)
    )
    assert out2.stop_reason == base.STOP_MAX_TOKENS
    ws.remove()
    ws2.remove()


def test_wall_clock_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [0.0]

    def tick() -> float:
        clock[0] += 100.0
        return clock[0]

    monkeypatch.setattr(bud.time, "monotonic", tick)
    _fx, ws, _model, out = _setup(
        tmp_path,
        [turn(call("read_file", path="pkg/calc.py")) for _ in range(5)],
        budget=base.Budget(wall_clock_s=250),
    )
    assert out.stop_reason == base.STOP_WALL_CLOCK
    ws.remove()


def test_model_error_and_nudges(tmp_path: Path) -> None:
    _fx, ws, model, out = _setup(
        tmp_path, [turn(content="thinking..."), turn(content="still"), RuntimeError("502")]
    )
    assert out.stop_reason == base.STOP_MODEL_ERROR and out.errors[0].startswith("model_error")
    assert sum(1 for m in model.histories[-1] if m["role"] == "user") == 3  # task + 2 nudges
    ws.remove()


def test_malformed_tool_args_and_unknown_tool(tmp_path: Path) -> None:
    bad = oc.ToolCall(
        id="x", name="read_file", arguments={}, parse_error="arguments are not valid JSON: x"
    )
    _fx, ws, model, _out = _setup(tmp_path, [turn(bad, call("frobnicate")), turn(content="ok")])
    r = model.tool_results()
    assert r[0].startswith("ERROR: arguments") and r[1].startswith("ERROR: unknown tool")
    ws.remove()


def test_read_file_paging_and_search(tmp_path: Path) -> None:
    _fx, ws, model, _out = _setup(
        tmp_path,
        [
            turn(
                call("read_file", path="pkg/calc.py", start_line=2, end_line=2),
                call("read_file", path="pkg/calc.py", start_line=99),
                call("read_file", path="nope.py"),
                call("search_repo", pattern="zzz-none"),
                call("search_repo", pattern=""),
                call("list_files", glob="pkg/*.py"),
            ),
            turn(content="ok"),
        ],
    )
    r = model.tool_results()
    assert r[0].startswith(
        "# lines 2-2 of 6\n    return a - b\n... (call read_file with start_line=3"
    )
    assert r[1].startswith("# lines 6-6 of 6")
    assert r[2].startswith("ERROR: file not found")
    assert r[3].startswith("no matches")
    assert r[4].startswith("ERROR")
    assert r[5].split("\n") == ["pkg/__init__.py", "pkg/calc.py", "pkg/util.py"]
    ws.remove()


def test_transcript_opt_in_is_redacted(tmp_path: Path) -> None:
    leak = "AWS key AKIAABCDEFGHIJKLMNOP in the tree"
    _fx, ws, _model, out = _setup(
        tmp_path,
        [turn(call("write_file", path="pkg/new.py", content=f"# {leak}\n")), turn(content=leak)],
        keep_transcript=True,
    )
    joined = json.dumps(out.to_dict(include_transcript=True))
    assert "AKIAABCDEFGHIJKLMNOP" not in joined and "[REDACTED-AWS]" in joined
    assert "AKIA" not in out.summary
    ws.remove()


def test_tool_schema_shape() -> None:
    names = [t["function"]["name"] for t in tool_schema(sighted=True)]
    assert names[-1] == "run_target_tests" and "run_target_tests" not in [
        t["function"]["name"] for t in tool_schema(sighted=False)
    ]


# ---------------------------------------------------------------------------
# openai_client: parsing, retries, metering, credentials
# ---------------------------------------------------------------------------


_UNPRICED = bud.Pricing(0.0, 0.0, known=False)


class _FakeStatusError(Exception):
    """An exception carrying ``status_code`` the way the OpenAI SDK's API errors do."""

    def __init__(self, status: int) -> None:
        super().__init__(f"status {status}")
        self.status_code = status


class FakeClient:
    """Mimics ``openai.OpenAI().chat.completions.create``."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw: Any) -> Any:
        self.calls.append(kw)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _resp(content: str = "", tool_calls: Any = None, tin: int = 10, tout: int = 5) -> Any:
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg, finish_reason="stop")],
        usage=SimpleNamespace(
            prompt_tokens=tin, completion_tokens=tout, prompt_tokens_details=None
        ),
    )


def test_openai_chat_retries_then_meters() -> None:
    sleeps: list[float] = []
    client = FakeClient(
        [_FakeStatusError(429), _FakeStatusError(503), _resp("hi", tin=100, tout=10)]
    )
    chat = oc.OpenAIChat(client, "gpt-oss-120b", sleep=sleeps.append, max_retries=3)
    t = chat([{"role": "user", "content": "x"}])
    assert t.content == "hi" and t.tokens_in == 100 and len(sleeps) == 2
    assert chat.meter.calls == 1 and chat.meter.cost_usd == pytest.approx(
        100 * 0.25e-6 + 10 * 0.69e-6
    )
    assert client.calls[-1]["model"] == "gpt-oss-120b" and "tools" not in client.calls[-1]


def test_openai_chat_non_retryable_and_exhausted() -> None:
    client = FakeClient([_FakeStatusError(400)])
    chat = oc.OpenAIChat(client, "m", sleep=lambda s: None, pricing=_UNPRICED)
    with pytest.raises(oc.ModelCallError) as ei:
        chat([{"role": "user", "content": "x"}])
    assert ei.value.status == 400
    client2 = FakeClient([_FakeStatusError(500)] * 3)
    chat2 = oc.OpenAIChat(client2, "m", sleep=lambda s: None, max_retries=2, pricing=_UNPRICED)
    with pytest.raises(oc.ModelCallError):
        chat2([{"role": "user", "content": "x"}])
    assert len(client2.calls) == 3


def test_parse_tool_calls_tolerates_bad_json() -> None:
    raw = [
        SimpleNamespace(
            id="a", function=SimpleNamespace(name="read_file", arguments='{"path": "x"}')
        ),
        SimpleNamespace(id="b", function=SimpleNamespace(name="read_file", arguments="{not json")),
        {"id": "c", "function": {"name": "list_files", "arguments": "[1]"}},
    ]
    calls = oc.parse_tool_calls(raw)
    assert calls[0].arguments == {"path": "x"} and not calls[0].parse_error
    assert calls[1].arguments == {} and "not valid JSON" in calls[1].parse_error
    assert "JSON object" in calls[2].parse_error
    turn_ = oc.ModelTurn(content="", tool_calls=calls)
    assert turn_.as_message()["tool_calls"][0]["function"]["name"] == "read_file"


def test_azure_deployment_and_missing_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    az = oc.AzureConfig(
        endpoint="https://x.openai.azure.com", api_version="2024-10-21", deployment="dep"
    )
    client = FakeClient([_resp("ok")])
    chat = oc.OpenAIChat(
        client, "gpt-4o", deployment=az.deployment, sleep=lambda s: None, pricing=_UNPRICED
    )
    chat([{"role": "user", "content": "x"}])
    assert client.calls[0]["model"] == "dep"
    with pytest.raises(ValueError):
        oc.AzureConfig(endpoint="http://insecure", api_version="v", deployment="d")
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    with pytest.raises(oc.MissingCredential):  # checked before the SDK is even imported
        oc.make_client()
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    with pytest.raises(oc.MissingCredential):
        oc.make_client(azure=az)
    ep = oc.EndpointConfig(azure=az)
    assert ep.provider == "azure" and oc.EndpointConfig().provider == "cerebras"


def test_builder_without_credential_records_model_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    # the builder calls the CONFIGURED endpoint: no shell setting may point it elsewhere
    for name in ("CRB_OPENAI_BASE_URL", "CRB_OPENAI_KEY_ENV", "CRB_AZURE_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    fx = make_fixture(tmp_path)
    ws = fx.workspace(tmp_path / "wt")
    brief = base.BuildBrief.from_task(fx.task, config=fx.config)
    out = OpenAIAgentBuilder(model="gpt-oss-120b").build(ws, brief, base.Budget())
    assert out.stop_reason == base.STOP_MODEL_ERROR and out.errors[0].startswith("model_error")
    ws.remove()


@pytest.mark.live
def test_live_cerebras_agent(tmp_path: Path) -> None:
    if not os.environ.get("CEREBRAS_API_KEY"):
        pytest.skip("CEREBRAS_API_KEY not set")
    pytest.importorskip("openai")
    fx = make_fixture(tmp_path)
    ws = fx.workspace(tmp_path / "wt")
    brief = base.BuildBrief.from_task(fx.task, config=fx.config)
    out = OpenAIAgentBuilder(model="gpt-oss-120b", provider="cerebras").build(
        ws, brief, base.Budget(max_turns=8, max_tool_calls=12, max_cost_usd=0.10, wall_clock_s=240)
    )
    assert out.tokens_in > 0 and out.cost_known and not out.violated
    if out.done:
        res = grade(
            ws, fx.task, config=fx.config, runner=get_runner(fx.config), executor=LocalExecutor()
        )
        assert res.belts.tests_unmodified is True
    ws.remove()


def test_make_chat_lets_a_caller_keyword_override_the_endpoint_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The labeller passes max_tokens/temperature; the endpoint has defaults of the same
    name. Passing both to OpenAIChat raised TypeError and every live OpenAI-compatible
    label read `unclassified` (found by the header pass, 2026-09-15)."""
    monkeypatch.setattr(oc, "make_client", lambda *a, **k: object())
    chat = oc.make_chat(
        "m", oc.EndpointConfig(max_tokens=4000, temperature=0.2), max_tokens=64, temperature=0.0
    )
    assert chat.max_tokens == 64 and chat.temperature == 0.0
    plain = oc.make_chat("m", oc.EndpointConfig(max_tokens=4000))
    assert plain.max_tokens == 4000
