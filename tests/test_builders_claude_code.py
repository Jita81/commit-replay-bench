"""The Claude Code adapter: headless argv, stream-json parsing (turns / tool uses / usage /
cost / structured claim), post-hoc tamper + archaeology detection, and an end-to-end
build (fake transport performs the edit) the core grader marks clean."""

from __future__ import annotations

import json
import os
import shutil
import sys
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from crb.builders import base
from crb.builders import claude_code as cc
from crb.core.execution import LocalExecutor
from crb.core.grade import grade
from crb.core.runners import get_runner

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
if str(_FIXTURES) not in sys.path:
    sys.path.insert(0, str(_FIXTURES))
from builders_repo import FIXED_CALC, make_fixture  # noqa: E402

# ---------------------------------------------------------------------------
# Canned stream-json (shapes as emitted by `claude -p --output-format stream-json`)
# ---------------------------------------------------------------------------


def ev_init(model: str = "claude-opus-5") -> str:
    return json.dumps(
        {
            "type": "system",
            "subtype": "init",
            "session_id": "s1",
            "model": model,
            "tools": list(cc.TOOLS),
            "cwd": "/wt",
        }
    )


def ev_assistant(*blocks: dict[str, Any], tin: int = 100, tout: int = 30, cached: int = 0) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": list(blocks),
                "usage": {
                    "input_tokens": tin,
                    "output_tokens": tout,
                    "cache_read_input_tokens": cached,
                },
            },
            "session_id": "s1",
        }
    )


def text(t: str) -> dict[str, Any]:
    return {"type": "text", "text": t}


def tool_use(name: str, **inp: Any) -> dict[str, Any]:
    return {"type": "tool_use", "id": f"tu_{name}", "name": name, "input": inp}


def ev_user(n: int = 1) -> str:
    return json.dumps(
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}] * n,
            },
        }
    )


def ev_result(
    *,
    subtype: str = "success",
    is_error: bool = False,
    num_turns: int = 3,
    cost: float | None = 0.0123,
    tin: int = 500,
    tout: int = 120,
    structured: Mapping[str, Any] | None = None,
    result: str = "",
    denials: list[dict[str, Any]] | None = None,
) -> str:
    ev: dict[str, Any] = {
        "type": "result",
        "subtype": subtype,
        "is_error": is_error,
        "duration_ms": 1234,
        "num_turns": num_turns,
        "result": result,
        "session_id": "s1",
        "usage": {"input_tokens": tin, "output_tokens": tout, "cache_read_input_tokens": 0},
        "permission_denials": denials or [],
    }
    if cost is not None:
        ev["total_cost_usd"] = cost
    if structured is not None:
        ev["structured_output"] = dict(structured)
    return json.dumps(ev)


GOOD_RUN = [
    ev_init(),
    ev_assistant(
        text("Let me run the tests"),
        tool_use("Bash", command="python -m pytest tests/test_calc.py -q"),
    ),
    ev_user(),
    ev_assistant(tool_use("Read", file_path="/wt/pkg/calc.py"), tin=200, tout=40),
    ev_user(),
    ev_assistant(
        tool_use("Edit", file_path="/wt/pkg/calc.py", old_string="a - b", new_string="a + b")
    ),
    ev_user(),
    ev_assistant(tool_use("Bash", command="python -m pytest tests/test_calc.py -q")),
    ev_user(),
    ev_result(num_turns=4, structured={"done": True, "summary": "Fixed add()."}),
]


class FakeHandle:
    def __init__(
        self, lines: list[str], *, returncode: int = 0, timed_out: bool = False, stderr: str = ""
    ) -> None:
        self._lines = list(lines)
        self.returncode: int | None = returncode
        self.timed_out = timed_out
        self.stderr_tail = stderr
        self.killed = False

    def lines(self) -> Iterator[str]:
        for ln in self._lines:
            if self.killed:
                return
            yield ln

    def kill(self) -> None:
        self.killed = True


class FakeSpawn:
    """Records the invocation; optionally mutates the worktree like the real CLI would."""

    def __init__(
        self,
        lines: list[str],
        *,
        side_effect: Callable[[Path], None] | None = None,
        returncode: int = 0,
        timed_out: bool = False,
        stderr: str = "",
        raise_exc: Exception | None = None,
    ) -> None:
        self.lines = lines
        self.side_effect = side_effect
        self.returncode = returncode
        self.timed_out = timed_out
        self.stderr = stderr
        self.raise_exc = raise_exc
        self.argv: list[str] = []
        self.env: dict[str, str] = {}
        self.cwd: Path | None = None
        self.timeout_s = 0

    def __call__(
        self, argv: list[str], env: Mapping[str, str], cwd: Path, timeout_s: int
    ) -> FakeHandle:
        self.argv, self.env, self.cwd, self.timeout_s = list(argv), dict(env), cwd, timeout_s
        if self.raise_exc:
            raise self.raise_exc
        if self.side_effect:
            self.side_effect(cwd)
        return FakeHandle(
            self.lines, returncode=self.returncode, timed_out=self.timed_out, stderr=self.stderr
        )


def _fix_calc(cwd: Path) -> None:
    (cwd / "pkg" / "calc.py").write_text(FIXED_CALC, encoding="utf-8")


def _tamper(cwd: Path) -> None:
    _fix_calc(cwd)
    (cwd / "tests" / "test_calc.py").write_text("def test_add():\n    pass\n", encoding="utf-8")


def _setup(
    tmp_path: Path,
    spawn: FakeSpawn,
    *,
    mode: str = "sighted",
    budget: base.Budget | None = None,
    **kw: Any,
):
    fx = make_fixture(tmp_path)
    ws = fx.workspace(tmp_path / "wt", mode=mode)
    brief = base.BuildBrief.from_task(
        fx.task,
        mode=mode,
        config=fx.config,
        test_command="python -m pytest tests/test_calc.py -q" if mode == "sighted" else "",
    )
    builder = cc.ClaudeCodeBuilder(spawn=spawn, claude_binary="/fake/claude", **kw)
    out = builder.build(
        ws,
        brief,
        budget or base.Budget(max_turns=10, max_tool_calls=25, max_cost_usd=1.0, wall_clock_s=300),
    )
    return fx, ws, out


@pytest.fixture(autouse=True)
def _api_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fake key for the hermetic tests only — the live test must see the real environment."""
    if request.node.get_closest_marker("live"):
        return
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key-not-real-0000000000000000")
    monkeypatch.setenv("SOME_OTHER_SECRET", "must-not-leak")


# ---------------------------------------------------------------------------
# argv + env
# ---------------------------------------------------------------------------


def test_argv_is_headless_restricted_and_uses_skill_model_ids(tmp_path: Path) -> None:
    fx = make_fixture(tmp_path)
    brief = base.BuildBrief.from_task(
        fx.task, config=fx.config, test_command="pytest tests/test_calc.py"
    )
    b = cc.ClaudeCodeBuilder(model="claude-sonnet-5")
    budget = base.Budget(max_turns=7, max_tool_calls=25, max_cost_usd=0.5)
    argv = b.argv(brief, budget, tmp_path / "wt", binary="claude")
    s = " ".join(argv)
    assert argv[:2] == ["claude", "-p"]
    assert "--output-format stream-json" in s and "--verbose" in s
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5"
    assert argv[argv.index("--max-turns") + 1] == "7"
    assert argv[argv.index("--max-budget-usd") + 1] == "0.5000"
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[argv.index("--tools") + 1] == "Read,Edit,Bash"  # bare = the CLI's simple mode
    assert argv[argv.index("--allowedTools") + 1] == "Read,Edit,Bash"
    full = cc.ClaudeCodeBuilder(bare=False).argv(brief, budget, tmp_path / "wt")
    assert (
        full[full.index("--tools") + 1] == "Read,Edit,Write,Glob,Grep,Bash" and "--bare" not in full
    )
    deny = argv[argv.index("--disallowedTools") + 1]
    assert "Bash(git log:*)" in deny and "WebFetch" in deny and "Bash(curl:*)" in deny
    sysprompt = argv[argv.index("--append-system-prompt") + 1]
    assert (
        "NEVER modify" in sysprompt
        and "DISQUALIFYING" in sysprompt
        and "25 tool calls" in sysprompt
    )
    schema = json.loads(argv[argv.index("--json-schema") + 1])
    assert schema["required"] == ["done", "summary"]
    assert (
        "--bare" in argv
        and "--no-session-persistence" in argv
        and "--disable-slash-commands" in argv
    )
    prompt = argv[2]
    assert "tests/test_calc.py" in prompt and "pytest tests/test_calc.py" in prompt
    assert "pkg/calc.py" not in prompt  # never the src_files
    assert cc.DEFAULT_MODEL == "claude-sonnet-5"  # the census's measured path
    assert cc.ClaudeCodeBuilder().model == "claude-sonnet-5"
    assert cc.ClaudeCodeBuilder(model="claude-opus-5").model == "claude-opus-5"
    with pytest.warns(UserWarning, match="not in the known id table"):
        cc.ClaudeCodeBuilder(model="sonnet")


def test_blind_prompt_has_no_test_paths(tmp_path: Path) -> None:
    fx = make_fixture(tmp_path)
    brief = base.BuildBrief.from_task(fx.task, mode="blind", config=fx.config)
    prompt = cc.task_prompt(brief, tmp_path)
    assert "test_calc" not in prompt and "held out" in prompt and "Grep/Glob/Read" in prompt


def test_env_is_minimal_and_key_only_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    env = cc.ClaudeCodeBuilder.env()
    assert env["ANTHROPIC_API_KEY"].startswith("sk-ant-test")
    assert "SOME_OTHER_SECRET" not in env and env["CI"] == "1" and "PATH" in env
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(PermissionError, match="ANTHROPIC_API_KEY"):
        cc.ClaudeCodeBuilder.env()


# ---------------------------------------------------------------------------
# auth modes: api_key (production, --bare) vs cli (operator login, no --bare)
# ---------------------------------------------------------------------------


def test_auth_api_key_mode_is_the_default_and_bare(tmp_path: Path) -> None:
    fx = make_fixture(tmp_path)
    brief = base.BuildBrief.from_task(fx.task, config=fx.config, test_command="pytest")
    b = cc.ClaudeCodeBuilder()
    assert b.auth == cc.AUTH_API_KEY and b.bare is True and b.tools == cc.BARE_TOOLS
    argv = b.argv(brief, base.Budget(), tmp_path / "wt")
    assert "--bare" in argv and "--setting-sources" not in argv
    assert b.describe()["auth"] == "api_key" and b.describe()["bare"] is True
    # an explicit bare=False under api_key is still allowed (full tools, key auth)
    full = cc.ClaudeCodeBuilder(bare=False)
    assert full.auth == cc.AUTH_API_KEY and full.bare is False and full.tools == cc.FULL_TOOLS


def test_auth_cli_mode_argv_drops_bare_and_restricts_setting_sources(tmp_path: Path) -> None:
    fx = make_fixture(tmp_path)
    brief = base.BuildBrief.from_task(fx.task, config=fx.config, test_command="pytest")
    b = cc.ClaudeCodeBuilder(auth="cli", model="claude-sonnet-5")
    assert b.auth == cc.AUTH_CLI and b.bare is False and b.tools == cc.FULL_TOOLS
    budget = base.Budget(max_turns=7, max_tool_calls=25, max_cost_usd=0.5)
    argv = b.argv(brief, budget, tmp_path / "wt", binary="claude")
    assert "--bare" not in argv
    assert argv[argv.index("--setting-sources") + 1] == "user"
    # everything else that isolates the run is unchanged
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[argv.index("--tools") + 1] == "Read,Edit,Write,Glob,Grep,Bash"
    assert argv[argv.index("--allowedTools") + 1] == "Read,Edit,Write,Glob,Grep,Bash"
    deny = argv[argv.index("--disallowedTools") + 1]
    assert "Bash(git log:*)" in deny and "WebFetch" in deny and "Bash(curl:*)" in deny
    assert "--no-session-persistence" in argv and "--disable-slash-commands" in argv
    assert argv[argv.index("--max-budget-usd") + 1] == "0.5000"
    assert b.describe() == {
        "builder": "claude_code",
        "model": "claude-sonnet-5",
        "provider": "anthropic",
        "process": "claude -p stream-json, tools=Read,Edit,Write,Glob,Grep,Bash",
        "effort": "default",
        "bare": False,
        "auth": "cli",
    }


def test_auth_cli_mode_env_needs_no_key_and_never_forwards_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/Users/op/.claude-eval")
    monkeypatch.setenv("USER", "op")
    monkeypatch.setenv("LOGNAME", "op")
    env = cc.ClaudeCodeBuilder.env("cli")
    assert "ANTHROPIC_API_KEY" not in env  # set in the shell by the autouse fixture: not forwarded
    assert env["CLAUDE_CONFIG_DIR"] == "/Users/op/.claude-eval" and "HOME" in env
    # the keychain entry is keyed by the user: without USER the CLI says "Not logged in"
    assert env["USER"] == "op" and env["LOGNAME"] == "op"
    assert "SOME_OTHER_SECRET" not in env and env["CI"] == "1"
    # api_key mode never forwards the login-locating variables (the key is the credential)
    assert "USER" not in cc.ClaudeCodeBuilder.env("api_key")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    env = cc.ClaudeCodeBuilder.env("cli")  # no key: not an error in cli mode
    assert "ANTHROPIC_API_KEY" not in env and "CLAUDE_CONFIG_DIR" not in env
    with pytest.raises(PermissionError, match="auth='api_key'"):
        cc.ClaudeCodeBuilder.env("api_key")


def test_auth_cli_build_without_a_key_runs_and_grades(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    spawn = FakeSpawn(GOOD_RUN, side_effect=_fix_calc)
    fx, ws, out = _setup(tmp_path, spawn, auth="cli")
    assert out.stop_reason == base.STOP_DONE and out.done and not out.errors, out.errors
    assert "--bare" not in spawn.argv and "ANTHROPIC_API_KEY" not in spawn.env
    res = grade(
        ws, fx.task, config=fx.config, runner=get_runner(fx.config), executor=LocalExecutor()
    )
    assert res.clean
    ws.remove()


def test_auth_cli_auth_failure_hint_names_the_login(tmp_path: Path) -> None:
    lines = [
        ev_init(),
        json.dumps({"type": "system", "subtype": "api_retry", "error_status": 401}),
    ]
    _fx, ws, out = _setup(tmp_path, FakeSpawn(lines), auth="cli")
    assert out.stop_reason == base.STOP_MODEL_ERROR
    assert any("claude login" in e for e in out.errors) and not any(
        "ANTHROPIC_API_KEY" in e for e in out.errors
    )
    ws.remove()


def test_auth_mode_validation() -> None:
    with pytest.raises(ValueError, match="auth must be one of"):
        cc.ClaudeCodeBuilder(auth="oauth")
    with pytest.raises(ValueError, match="cannot combine"):
        cc.ClaudeCodeBuilder(auth="cli", bare=True)
    # builder_config from the API arrives as JSON: a list for extra_args must work
    b = cc.ClaudeCodeBuilder(auth="cli", extra_args=["--x", "1"])
    assert b.extra_args == ("--x", "1")


def test_worker_environment_defaults_for_auth_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """``CRB_CLAUDE_CODE_AUTH`` / ``CRB_CLAUDE_CODE_MODEL`` fill what the rung and the
    builder_config leave unset; an explicit value always wins; a bad env value is an error
    that names its source."""
    monkeypatch.delenv(cc.AUTH_ENV, raising=False)
    monkeypatch.delenv(cc.MODEL_ENV, raising=False)
    b = cc.ClaudeCodeBuilder()
    assert (b.auth, b.model, b.bare) == ("api_key", "claude-sonnet-5", True)
    monkeypatch.setenv(cc.AUTH_ENV, "cli")
    monkeypatch.setenv(cc.MODEL_ENV, "claude-opus-5")
    b = cc.ClaudeCodeBuilder()
    assert (b.auth, b.model, b.bare) == ("cli", "claude-opus-5", False)
    # explicit (rung model / builder_config auth) beats the environment
    b = cc.ClaudeCodeBuilder(model="claude-sonnet-5", auth="api_key")
    assert (b.auth, b.model, b.bare) == ("api_key", "claude-sonnet-5", True)
    monkeypatch.setenv(cc.AUTH_ENV, "keychain")
    with pytest.raises(ValueError, match=f"'keychain' \\(from {cc.AUTH_ENV}\\)"):
        cc.ClaudeCodeBuilder()
    monkeypatch.setenv(cc.AUTH_ENV, "  ")  # blank = unset
    assert cc.ClaudeCodeBuilder().auth == "api_key"


# ---------------------------------------------------------------------------
# Stream parsing + end-to-end
# ---------------------------------------------------------------------------


def test_good_run_parses_stream_and_grades_clean(tmp_path: Path) -> None:
    spawn = FakeSpawn(GOOD_RUN, side_effect=_fix_calc)
    fx, ws, out = _setup(tmp_path, spawn, keep_transcript=True, model="claude-opus-5")
    assert spawn.cwd == ws.root and spawn.timeout_s == 300
    assert (
        spawn.env["ANTHROPIC_API_KEY"].startswith("sk-ant") and "SOME_OTHER_SECRET" not in spawn.env
    )
    assert out.done and out.stop_reason == base.STOP_DONE and out.errors == ()
    assert out.summary == "Fixed add()." and out.turns == 4 and out.tool_calls == 4
    assert out.tokens_in == 500 and out.tokens_out == 120  # result totals win over per-message sums
    assert out.cost_usd == pytest.approx(0.0123) and out.cost_known  # provider-reported cost
    assert out.extra["tool_names"] == ["Bash", "Read", "Edit", "Bash"]
    assert out.extra["session"]["model"] == "claude-opus-5"
    assert out.transcript and out.transcript[0]["kind"] == "system"
    assert [e["kind"] for e in out.transcript].count("assistant") == 4
    ref = out.builder_ref()
    assert (
        ref.provider == "anthropic"
        and ref.model == "claude-opus-5"
        and ref.cost_usd == pytest.approx(0.0123)
    )
    res = grade(
        ws, fx.task, config=fx.config, runner=get_runner(fx.config), executor=LocalExecutor()
    )
    assert res.clean, res.to_dict()
    ws.remove()


def test_usage_falls_back_to_summed_messages_and_priced_cost(tmp_path: Path) -> None:
    lines = [
        ev_init(),
        ev_assistant(text("hi"), tin=1000, tout=100),
        ev_assistant(tool_use("Read", file_path="/wt/pkg/calc.py"), tin=2000, tout=200, cached=500),
        ev_result(
            num_turns=0, cost=None, tin=0, tout=0, result='{"done": false, "summary": "no change"}'
        ),
    ]
    _fx, ws, out = _setup(tmp_path, FakeSpawn(lines), model="claude-opus-5")
    # The API's `input_tokens` EXCLUDES cache reads (measured live: 50 input vs a 60k
    # session), so tokens_in is the TOTAL prompt (input + cache reads) and
    # tokens_cached the cached subset: 1000 + 2000 + 500 cached = 3500.
    assert out.tokens_in == 3500 and out.tokens_cached == 500
    assert out.tokens_out == 300 and out.turns == 2
    expected = (3500 - 500) * 5e-6 + 300 * 25e-6 + 500 * 0.5e-6  # opus 5 list prices
    assert out.cost_usd == pytest.approx(expected) and out.cost_known
    assert not out.done and out.summary == "no change" and out.stop_reason == base.STOP_DONE
    ws.remove()


def test_tamper_is_detected_post_hoc_and_grader_disqualifies(tmp_path: Path) -> None:
    lines = [
        ev_init(),
        ev_assistant(
            tool_use("Edit", file_path="/wt/tests/test_calc.py", old_string="5", new_string="0")
        ),
        ev_user(),
        ev_result(structured={"done": True, "summary": "made tests pass"}),
    ]
    fx, ws, out = _setup(tmp_path, FakeSpawn(lines, side_effect=_tamper))
    assert not out.done  # the claim says done; the tamper overrides it
    assert any(e.startswith("tamper:") and "tests/test_calc.py" in e for e in out.errors)
    assert out.violated
    res = grade(
        ws, fx.task, config=fx.config, runner=get_runner(fx.config), executor=LocalExecutor()
    )
    assert res.disqualified and not res.clean and "tests/test_calc.py" in res.tamper_files
    ws.remove()


def test_blind_tamper_new_test_file(tmp_path: Path) -> None:
    def add_test(cwd: Path) -> None:
        _fix_calc(cwd)
        (cwd / "tests" / "test_sneaky.py").write_text("def test_s():\n    pass\n", encoding="utf-8")

    _fx, ws, out = _setup(
        tmp_path,
        FakeSpawn(
            [ev_init(), ev_result(structured={"done": True, "summary": "x"})], side_effect=add_test
        ),
        mode="blind",
    )
    assert not out.done and any("tests/test_sneaky.py" in e for e in out.errors)
    ws.remove()


def test_archaeology_and_network_in_transcript_are_violations(tmp_path: Path) -> None:
    lines = [
        ev_init(),
        ev_assistant(tool_use("Bash", command="git log --oneline -3")),
        ev_user(),
        ev_assistant(tool_use("Bash", command="cd pkg && git show HEAD~1:pkg/calc.py")),
        ev_user(),
        ev_assistant(tool_use("Bash", command="curl -s https://github.com/x/y/commit/abc")),
        ev_user(),
        ev_assistant(tool_use("Bash", command="python -m pytest -q")),
        ev_user(),
        ev_result(
            structured={"done": True, "summary": "ok"},
            denials=[{"tool_name": "Bash", "tool_input": {"command": "git log --oneline -3"}}],
        ),
    ]
    _fx, ws, out = _setup(tmp_path, FakeSpawn(lines, side_effect=_fix_calc))
    arch = [e for e in out.errors if e.startswith("archaeology:")]
    net = [e for e in out.errors if e.startswith("network:")]
    assert len(arch) == 2 and len(net) == 1 and out.violated
    assert out.extra["refused"] and "git log" in out.extra["refused"][0]
    assert out.done  # the claim stands as a claim; the orchestrator DQs on `violated`
    ws.remove()


def test_wall_clock_timeout_and_missing_result(tmp_path: Path) -> None:
    lines = [ev_init(), ev_assistant(tool_use("Read", file_path="/wt/pkg/calc.py"))]
    _fx, ws, out = _setup(tmp_path, FakeSpawn(lines, timed_out=True, returncode=-9))
    assert out.stop_reason == base.STOP_WALL_CLOCK and not out.done
    assert any(e.startswith("wall_clock:") for e in out.errors)
    ws.remove()


def test_error_result_and_max_turns(tmp_path: Path) -> None:
    _fx, ws, out = _setup(
        tmp_path,
        FakeSpawn([ev_init(), ev_result(subtype="error_max_turns", is_error=True, result="")]),
    )
    assert out.stop_reason == base.STOP_MAX_TURNS and not out.done
    _fx2, ws2, out2 = _setup(
        tmp_path / "b",
        FakeSpawn(
            [
                json.dumps(
                    {
                        "type": "result",
                        "subtype": "success",
                        "is_error": True,
                        "api_error_status": 401,
                        "result": "Invalid API key",
                        "num_turns": 1,
                        "total_cost_usd": 0,
                        "usage": {},
                    }
                )
            ]
        ),
    )
    assert (
        out2.stop_reason == base.STOP_MODEL_ERROR
        and not out2.done
        and out2.summary == "Invalid API key"
    )
    assert any("Invalid API key" in e for e in out2.errors)
    _fx3, ws3, out3 = _setup(
        tmp_path / "c",
        FakeSpawn(
            ["not json", ""], returncode=2, stderr="boom sk-ant-api03-secretsecretsecretsecret"
        ),
    )
    assert out3.stop_reason == base.STOP_MODEL_ERROR
    joined = " ".join(out3.errors)
    assert "rc=2" in joined and "no result event" in joined and "unparseable" in joined
    assert "secretsecret" not in joined
    ws.remove()
    ws2.remove()
    ws3.remove()


def test_auth_failure_kills_early(tmp_path: Path) -> None:
    retry = json.dumps(
        {
            "type": "system",
            "subtype": "api_retry",
            "attempt": 1,
            "max_retries": 10,
            "error_status": 401,
            "error": "authentication_failed",
        }
    )
    spawn = FakeSpawn([ev_init(), retry, retry, retry, ev_result()])
    _fx, ws, out = _setup(tmp_path, spawn)
    assert out.stop_reason == base.STOP_MODEL_ERROR and not out.done
    assert any("authentication failed (HTTP 401)" in e for e in out.errors)
    assert out.extra["api_retries"] == [401] and out.turns == 0  # killed after the first retry
    ws.remove()


def test_spawn_failure_missing_key_and_missing_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fx, ws, out = _setup(tmp_path, FakeSpawn([], raise_exc=OSError("cannot exec")))
    assert out.stop_reason == base.STOP_MODEL_ERROR and "cannot exec" in out.errors[0]
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    _fx2, ws2, out2 = _setup(tmp_path / "b", FakeSpawn(GOOD_RUN))
    assert out2.stop_reason == base.STOP_MODEL_ERROR and "ANTHROPIC_API_KEY" in out2.errors[0]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    fx3 = make_fixture(tmp_path / "c")
    ws3 = fx3.workspace(tmp_path / "c" / "wt")
    out3 = cc.ClaudeCodeBuilder(spawn=FakeSpawn(GOOD_RUN)).build(
        ws3, base.BuildBrief.from_task(fx3.task, config=fx3.config), base.Budget()
    )
    assert out3.stop_reason == base.STOP_MODEL_ERROR and "not found" in out3.errors[0]
    ws.remove()
    ws2.remove()
    ws3.remove()


def test_stream_stats_claim_and_write_path_inspection(tmp_path: Path) -> None:
    fx = make_fixture(tmp_path)
    ws = fx.workspace(tmp_path / "wt")
    guard = base.TestFileGuard(ws.root, fx.config, fx.task.test_files)
    st = cc.StreamStats(base.GitArchaeologyGuard(), guard)
    st.feed(
        ev_assistant(
            tool_use("Write", file_path=str(ws.root / "tests" / "test_calc.py"), content="x")
        ),
        keep=False,
    )
    st.feed(ev_assistant(tool_use("Write", file_path="/etc/passwd", content="x")), keep=False)
    st.feed(ev_assistant(text("prose only")), keep=True)
    assert len(st.refused) == 2 and "immutable" in st.refused[0] and "outside" in st.refused[1]
    assert st.claim() == (False, "prose only")
    st.feed(ev_result(result='{"done": true, "summary": "parsed from text"}'), keep=False)
    assert st.claim() == (True, "parsed from text")
    assert st.events[2].get("text") == "prose only"
    ws.remove()


@pytest.mark.live
def test_live_claude_code(tmp_path: Path) -> None:
    if not os.environ.get("ANTHROPIC_API_KEY") or not shutil.which("claude"):
        pytest.skip("ANTHROPIC_API_KEY not set or claude CLI not on PATH")
    fx = make_fixture(tmp_path)
    ws = fx.workspace(tmp_path / "wt")
    brief = base.BuildBrief.from_task(
        fx.task, config=fx.config, test_command=f"{sys.executable} -m pytest tests/test_calc.py -q"
    )
    out = cc.ClaudeCodeBuilder().build(
        ws, brief, base.Budget(max_turns=12, max_tool_calls=25, max_cost_usd=0.50, wall_clock_s=300)
    )
    assert out.stop_reason != base.STOP_MODEL_ERROR, out.errors
    assert out.tokens_in > 0 and out.cost_known and not out.violated
    res = grade(
        ws, fx.task, config=fx.config, runner=get_runner(fx.config), executor=LocalExecutor()
    )
    assert res.belts.tests_unmodified is True
    ws.remove()


def _cli_logged_in() -> bool:
    """``claude auth status`` under the adapter's own cli-mode environment."""
    import subprocess

    if not shutil.which("claude"):
        return False
    try:
        p = subprocess.run(
            ["claude", "auth", "status"],
            env=cc.ClaudeCodeBuilder.env("cli"),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return bool(json.loads(p.stdout).get("loggedIn"))
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


@pytest.mark.live
def test_live_claude_code_cli_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The operator's own ``claude login`` drives a real build (no API key in the child).

    Opt-in (``CRB_LIVE_CLAUDE_CLI=1``): it spends the operator's subscription and a
    stale login fails it honestly (``401`` → ``model_error``), which must not break
    the default suite on a developer machine."""
    if os.environ.get("CRB_LIVE_CLAUDE_CLI") != "1":
        pytest.skip("set CRB_LIVE_CLAUDE_CLI=1 to run the cli-auth live test")
    if not _cli_logged_in():
        pytest.skip("claude CLI not on PATH or not logged in (run `claude login`)")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    fx = make_fixture(tmp_path)
    ws = fx.workspace(tmp_path / "wt")
    brief = base.BuildBrief.from_task(
        fx.task, config=fx.config, test_command=f"{sys.executable} -m pytest tests/test_calc.py -q"
    )
    out = cc.ClaudeCodeBuilder(auth="cli").build(
        ws, brief, base.Budget(max_turns=12, max_tool_calls=25, max_cost_usd=0.50, wall_clock_s=300)
    )
    assert out.stop_reason != base.STOP_MODEL_ERROR, out.errors
    session = out.extra["session"]
    assert session.get("apiKeySource") in (None, "none")  # the login, not a key
    assert session.get("model") == cc.DEFAULT_MODEL
    assert not out.violated
    ws.remove()
