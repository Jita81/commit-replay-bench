"""crb.builders.labeller — the LLM intent labellers over fake transports: what the
model is shown (never the diff body), parsing, malformed / errored replies (never an
exception), auth + env handling mirrored from claude_code, and the factory.

The real-LLM check at the bottom labels the three cobra commits the critical-friend
review discusses and is skipped unless a credential (``ANTHROPIC_API_KEY``,
``CRB_CLAUDE_CODE_AUTH=cli`` or ``CEREBRAS_API_KEY``) is present.

Navigation
----------
What it is:   The LLM intent labellers' test suite over fake transports — what the model is
              shown, parsing, failures that are never exceptions, auth mirrored from
              ``claude_code``, and the factory.
What it does: Pins that the OpenAI-compatible labeller parses a reply and meters usage, shows
              evidence and the vocabulary but never the diff body, turns malformed output into
              ``unclassified`` and transport errors into a recorded label, and fails closed
              without a credential at the first call; that the Claude labeller's argv and
              environment mirror the builder in both auth modes, a missing key is a model-error
              label, and every failure is ``unclassified`` never raised; and that
              ``make_labeller`` routes by builder name and filters config. The real-LLM case
              labels the three cobra commits the critical-friend review discusses, skipped
              without a credential.
How:          ``_Chat`` and ``FakeSpawn`` replay canned replies; a fake API key for the hermetic
              cases only.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md
Works with:   src/crb/builders/labeller.py (under test), src/crb/core/classify.py (the label,
              evidence and parser it wraps), src/crb/builders/claude_code.py (the spawn and
              auth it mirrors), src/crb/builders/openai_client.py (the chat transport),
              tests/test_worker_label.py and tests/test_cli_tasks.py (the callers)
Tested by:    tests/test_builders_labeller.py
Touch when:   a labeller for a new transport is added (a no-diff case, a malformed-reply case
              and a no-credential case); the prompt changes what the model sees.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from crb.builders import claude_code as cc
from crb.builders import labeller as lb
from crb.builders.openai_client import ChatReply, MissingCredential
from crb.core import classify as c
from crb.core.git import GitRepo
from crb.core.spec import CLASS_VOCABULARY, UNCLASSIFIED

# ---------------------------------------------------------------------------
# shared evidence: cobra #1559 as the review describes it (stats only, no code)
# ---------------------------------------------------------------------------

_EV: dict[str, Any] = {
    "subject": 'Remove the default "completion" cmd if it is alone (#1559)',
    "message": (
        "When a program has no sub-commands, its root command can accept arguments. "
        "If we add the default completion command to such programs they will now have a "
        "sub-command and will no longer accept arguments."
    ),
    "changed_paths": ("command.go", "completions.go", "completions_test.go"),
    "diff_stats": (
        c.PathStat("command.go", 8, 7),
        c.PathStat("completions.go", 28, 2),
        c.PathStat("completions_test.go", 141, 3),
    ),
    "path_class": "bug.fix",
}
_DIGEST = c.LabelEvidence(**_EV).digest()

#: A line that would only appear if the diff body leaked into the prompt.
_DIFF_MARKERS = ("diff --git", "+++ b/", "@@ ", "func (c *Command)")


def _label(labeller: c.Labeller) -> c.IntentLabel:
    return labeller.label(**_EV)


# ---------------------------------------------------------------------------
# OpenAI-compatible labeller (fake chat_fn)
# ---------------------------------------------------------------------------


class _Chat:
    """A chat transport that returns one canned reply and records the messages it was sent."""

    def __init__(self, reply: str | ChatReply | Exception) -> None:
        self.reply = reply
        self.messages: list[list[dict[str, Any]]] = []

    def __call__(self, messages: list[dict[str, Any]]) -> str | ChatReply:
        self.messages.append(messages)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_openai_labeller_parses_reply_and_meters_usage() -> None:
    chat = _Chat(
        ChatReply(
            text='{"class": "behavior.change", "confidence": 0.86, "rationale": "changes when the completion cmd exists"}',
            tokens_in=900,
            tokens_out=40,
            cost_usd=0.0012,
        )
    )
    lab = lb.OpenAILabeller(model="gpt-oss-120b", provider="cerebras", chat_fn=chat)
    assert isinstance(lab, c.Labeller) and lab.name == "openai_agent:gpt-oss-120b@cerebras"
    out = _label(lab)
    assert out.intent_class == "behavior.change" and out.confidence == 0.86
    assert out.labeller == lab.name and out.evidence_hash == _DIGEST and not out.is_human
    assert lab.usage.to_dict() == {
        "calls": 1,
        "errors": 0,
        "tokens_in": 900,
        "tokens_out": 40,
        "cost_usd": 0.0012,
        "cost_known": True,
    }
    assert lab.describe()["process"] == "one-shot chat, no tools, no diff body"


def test_openai_labeller_prompt_shows_evidence_and_vocabulary_but_no_diff() -> None:
    chat = _Chat('{"class": "bug.fix", "confidence": 0.5}')
    lb.OpenAILabeller(model="m", chat_fn=chat).label(**_EV)
    (messages,) = chat.messages
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[0]["content"] == lb.SYSTEM_PROMPT
    user = messages[1]["content"]
    assert user == c.render_label_prompt(c.LabelEvidence(**_EV))
    assert _EV["subject"] in user and _EV["message"] in user
    assert "- completions_test.go  (+141 / -3)" in user
    for cls in CLASS_VOCABULARY:
        assert f"- {cls}:" in user
    for marker in _DIFF_MARKERS:
        assert marker not in user
    # nothing else is in the transcript either
    assert all(m not in json.dumps(messages) for m in _DIFF_MARKERS)


@pytest.mark.parametrize(
    ("reply", "why"),
    [
        ("I'd say it's a behaviour change.", "malformed reply"),
        ('{"class": "security.fix", "confidence": 0.9}', "unknown class"),
        ("", "malformed reply"),
    ],
)
def test_openai_labeller_malformed_output_is_unclassified_not_an_exception(
    reply: str, why: str
) -> None:
    lab = lb.OpenAILabeller(model="m", chat_fn=_Chat(reply))
    out = _label(lab)
    assert out.unclassified and out.confidence == 0.0 and why in out.rationale
    assert out.evidence_hash == _DIGEST
    assert c.resolve_class("bug.fix", out) == "bug.fix"  # the path class stands


def test_openai_labeller_transport_errors_are_recorded_never_raised() -> None:
    boom = lb.OpenAILabeller(
        model="m", chat_fn=_Chat(RuntimeError("502 upstream sk-live-abcdefghijklmnopqrstuvwx"))
    )
    out = _label(boom)
    assert out.unclassified and out.rationale.startswith("model_error: RuntimeError")
    assert "sk-live-abcdefghijklmnopqrstuvwx" not in out.rationale  # redacted
    assert boom.usage.errors == 1 and boom.usage.calls == 1
    nokey = lb.OpenAILabeller(
        model="m", chat_fn=_Chat(MissingCredential("CEREBRAS_API_KEY is not set"))
    )
    out = _label(nokey)
    assert out.unclassified and "CEREBRAS_API_KEY is not set" in out.rationale
    assert nokey.usage.last["error"] == "no credential"


def test_openai_labeller_without_credential_fails_closed_at_first_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    monkeypatch.delenv("CRB_OPENAI_KEY_ENV", raising=False)
    monkeypatch.delenv("CRB_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("CRB_AZURE_ENDPOINT", raising=False)
    lab = lb.OpenAILabeller(model="gpt-oss-120b")  # constructing needs nothing
    out = _label(lab)
    assert out.unclassified and "not set" in out.rationale
    with pytest.raises(ValueError, match="needs a model"):
        lb.OpenAILabeller(model="  ")


# ---------------------------------------------------------------------------
# Claude Code labeller (fake spawn)
# ---------------------------------------------------------------------------


def ev_result(
    *,
    structured: Mapping[str, Any] | None = None,
    text: str = "",
    cost: float | None = 0.004,
    is_error: bool = False,
    subtype: str = "success",
) -> str:
    """The CLI's terminal ``result`` line for a label call."""
    ev: dict[str, Any] = {
        "type": "result",
        "subtype": subtype,
        "is_error": is_error,
        "num_turns": 1,
        "result": text,
        "usage": {"input_tokens": 1200, "output_tokens": 35, "cache_read_input_tokens": 100},
    }
    if cost is not None:
        ev["total_cost_usd"] = cost
    if structured is not None:
        ev["structured_output"] = dict(structured)
    return json.dumps(ev)


def ev_init() -> str:
    """The CLI's ``system/init`` line."""
    return json.dumps(
        {"type": "system", "subtype": "init", "model": "claude-sonnet-5", "tools": []}
    )


def ev_retry(status: int) -> str:
    """A ``system/api_retry`` line with the given HTTP status (an auth failure surfaces this way)."""
    return json.dumps({"type": "system", "subtype": "api_retry", "error_status": status})


class FakeHandle:
    """The spawned process as the labeller sees it: an iterator of stdout lines and a ``kill``."""

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
    """Records the argv, env and cwd of the spawn and answers with canned lines."""

    def __init__(self, lines: list[str], **handle_kw: Any) -> None:
        self.lines = lines
        self.handle_kw = handle_kw
        self.calls: list[tuple[list[str], dict[str, str], Path, int]] = []
        self.handle: FakeHandle | None = None

    def __call__(
        self, argv: list[str], env: Mapping[str, str], cwd: Path, timeout_s: int
    ) -> FakeHandle:
        self.calls.append((list(argv), dict(env), Path(cwd), timeout_s))
        assert cwd.is_dir() and not any(cwd.iterdir())  # an empty temp dir, never a repo
        self.handle = FakeHandle(self.lines, **self.handle_kw)
        return self.handle


@pytest.fixture
def api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fake API key in the environment, ``cli`` and model overrides cleared, and an unrelated
    secret that must never reach the child.
    """
    monkeypatch.setenv(cc.API_KEY_ENV, "sk-ant-test-key-0123456789abcdef")
    monkeypatch.delenv(cc.AUTH_ENV, raising=False)
    monkeypatch.delenv(cc.MODEL_ENV, raising=False)
    monkeypatch.setenv("UNRELATED_SECRET", "leak-me")


def test_claude_labeller_argv_and_env_api_key_mode(api_key: None) -> None:
    spawn = FakeSpawn(
        [
            ev_init(),
            ev_result(
                structured={"class": "feature.add", "confidence": 0.8, "rationale": "new option"}
            ),
        ]
    )
    lab = lb.ClaudeCodeLabeller(
        model="claude-sonnet-5", spawn=spawn, effort="low", claude_binary="claude"
    )
    assert lab.name == "claude_code:claude-sonnet-5" and lab.auth == "api_key" and lab.bare
    out = _label(lab)
    assert out.intent_class == "feature.add" and out.confidence == 0.8
    assert out.labeller == lab.name and out.evidence_hash == _DIGEST
    ((argv, env, _cwd, timeout),) = spawn.calls
    assert argv[0] == "claude" and argv[1] == "-p"
    prompt = argv[2]
    assert prompt == c.render_label_prompt(c.LabelEvidence(**_EV))
    for marker in _DIFF_MARKERS:
        assert marker not in prompt and marker not in " ".join(argv)
    a = " ".join(argv)
    assert "--output-format stream-json" in a and "--max-turns 3" in a
    assert argv[argv.index("--tools") + 1] == ""  # every tool disabled
    assert (
        "--json-schema" in argv
        and json.loads(argv[argv.index("--json-schema") + 1]) == lb.LABEL_OUTPUT_SCHEMA
    )
    assert argv[argv.index("--system-prompt") + 1] == lb.SYSTEM_PROMPT
    assert "--no-session-persistence" in argv and "--disable-slash-commands" in argv
    assert "--bare" in argv and "--setting-sources" not in argv and "--effort low" in a
    assert "--allowedTools" not in argv and "--disallowedTools" not in argv
    # env: the key is forwarded, the operator's shell is not; hygiene flags set
    assert env[cc.API_KEY_ENV] == "sk-ant-test-key-0123456789abcdef"
    assert "UNRELATED_SECRET" not in env and env["CI"] == "1" and env["NO_COLOR"] == "1"
    assert env == cc.ClaudeCodeBuilder.env("api_key")
    assert timeout == lb.DEFAULT_TIMEOUT_S
    assert lab.usage.to_dict()["tokens_in"] == 1200 and lab.usage.to_dict()["cost_usd"] == 0.004


def test_claude_labeller_cli_mode_mirrors_claude_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(cc.API_KEY_ENV, raising=False)
    monkeypatch.setenv(cc.AUTH_ENV, "cli")
    monkeypatch.setenv("USER", "operator")
    monkeypatch.setenv(cc.CLI_OAUTH_TOKEN_ENV, "sk-ant-oat01-token-value-0123456789")
    spawn = FakeSpawn(
        [
            ev_init(),
            ev_result(text='{"class":"refactor","confidence":0.7,"rationale":"x"}', cost=None),
        ]
    )
    lab = lb.ClaudeCodeLabeller(spawn=spawn, claude_binary="claude")  # auth/model from env
    assert lab.auth == "cli" and not lab.bare and lab.model == cc.DEFAULT_MODEL
    out = _label(lab)
    assert out.intent_class == "refactor" and out.confidence == 0.7  # text fallback parsed
    ((argv, env, _, _),) = spawn.calls
    assert (
        "--bare" not in argv and argv[argv.index("--setting-sources") + 1] == cc.CLI_SETTING_SOURCES
    )
    assert cc.API_KEY_ENV not in env and env["USER"] == "operator"
    assert env[cc.CLI_OAUTH_TOKEN_ENV] == "sk-ant-oat01-token-value-0123456789"
    assert env == cc.ClaudeCodeBuilder.env("cli")
    # no total_cost_usd reported → priced from the tokens (sonnet-5 has a pricing row)
    usage = lab.usage.to_dict()
    assert usage["cost_known"] is True and usage["cost_usd"] > 0 and usage["tokens_in"] == 1200
    with pytest.raises(ValueError, match="cannot combine"):
        lb.ClaudeCodeLabeller(auth="cli", bare=True, spawn=spawn)
    with pytest.raises(ValueError, match="auth must be one of"):
        lb.ClaudeCodeLabeller(auth="keychain", spawn=spawn)


def test_claude_labeller_missing_key_is_a_model_error_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(cc.API_KEY_ENV, raising=False)
    monkeypatch.delenv(cc.AUTH_ENV, raising=False)
    spawn = FakeSpawn([ev_result(structured={"class": "perf", "confidence": 0.9, "rationale": ""})])
    # claude_binary pinned: a faked spawn must not depend on a real CLI on PATH (CI has none)
    out = _label(lb.ClaudeCodeLabeller(spawn=spawn, claude_binary="claude"))
    assert out.unclassified and "ANTHROPIC_API_KEY is not set" in out.rationale
    assert spawn.calls == []  # never spawned


@pytest.mark.parametrize(
    ("lines", "handle_kw", "why"),
    [
        (
            [ev_init(), ev_retry(401), ev_result(structured={"class": "perf", "confidence": 1})],
            {},
            "authentication failed (HTTP 401)",
        ),
        (  # measured on claude 2.1.132 with an invalid OAuth token: no api_retry, one result
            [
                ev_init(),
                json.dumps(
                    {
                        "type": "result",
                        "subtype": "success",
                        "is_error": True,
                        "api_error_status": 401,
                        "result": "Failed to authenticate. API Error: 401 OAuth access token is invalid.",
                        "total_cost_usd": 0,
                        "usage": {},
                    }
                ),
            ],
            {},
            "authentication failed (HTTP 401) — check ANTHROPIC_API_KEY",
        ),
        ([ev_init()], {"timed_out": True}, "wall_clock"),
        ([ev_init()], {"returncode": 1, "stderr": "boom"}, "no result event (rc=1): boom"),
        (
            [
                ev_init(),
                ev_result(is_error=True, subtype="error_during_execution", text="overloaded"),
            ],
            {},
            "model_error: error_during_execution: overloaded",
        ),
        ([ev_init(), ev_result(text="not json at all")], {}, "malformed reply"),
        (
            [ev_init(), ev_result(structured={"class": "nonsense", "confidence": 0.9})],
            {},
            "unknown class 'nonsense'",
        ),
        (
            [
                "{not json",
                ev_result(
                    structured={"class": "other", "confidence": 0.3, "rationale": "none fit"}
                ),
            ],
            {},
            "labeller answered 'other'",
        ),
    ],
)
def test_claude_labeller_failures_are_unclassified_never_raised(
    api_key: None, lines: list[str], handle_kw: dict[str, Any], why: str
) -> None:
    spawn = FakeSpawn(lines, **handle_kw)
    lab = lb.ClaudeCodeLabeller(spawn=spawn, claude_binary="claude")  # no real CLI needed
    out = _label(lab)
    assert out.unclassified and out.confidence == 0.0 and why in out.rationale
    assert out.evidence_hash == _DIGEST and out.labeller == lab.name
    if "401" in why and any('"api_retry"' in ln for ln in lines):
        assert spawn.handle is not None and spawn.handle.killed  # not retried ten times


def test_claude_labeller_missing_binary_and_unknown_model_warning(
    api_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    out = _label(lb.ClaudeCodeLabeller())
    assert out.unclassified and "not found on PATH" in out.rationale
    with pytest.warns(UserWarning, match="not in the known id table"):
        lb.ClaudeCodeLabeller(model="sonnet", spawn=FakeSpawn([]))


# ---------------------------------------------------------------------------
# factory
# ---------------------------------------------------------------------------


def test_make_labeller_routes_by_builder_and_filters_config(api_key: None) -> None:
    spawn = FakeSpawn([])
    claude = lb.make_labeller(
        "claude_code",
        model="claude-opus-5",
        builder_config={
            "auth": "api_key",
            "effort": "low",
            "spawn": spawn,
            "keep_transcript": True,
        },
    )
    assert isinstance(claude, lb.ClaudeCodeLabeller) and claude.effort == "low"
    chat = _Chat("{}")
    for builder in ("openai_agent", "editblock"):
        oa = lb.make_labeller(
            builder,
            model="gpt-oss-120b",
            provider="cerebras",
            builder_config={"chat_fn": chat, "executor": "x"},
        )
        assert isinstance(oa, lb.OpenAILabeller) and oa.name == "openai_agent:gpt-oss-120b@cerebras"
    with pytest.raises(ValueError, match="no labeller for builder"):
        lb.make_labeller("fixture_gold", model="m")
    assert set(lb.OPENAI_BUILDERS | lb.CLAUDE_BUILDERS) == {
        "openai_agent",
        "editblock",
        "claude_code",
    }


# ---------------------------------------------------------------------------
# real LLM (skipped without a credential): the review's three cobra commits
# ---------------------------------------------------------------------------

_COBRA = "https://github.com/spf13/cobra"
_COBRA_CLONE_ENV = "CRB_TEST_COBRA_CLONE"
#: sha → (review's own reading, the class the review implies)
_REVIEW_COMMITS: dict[str, tuple[str, str]] = {
    "1995054b003053cc1e404bccfbf6d168e8731509": (
        "#2241 Flow context to command in SetHelpFunc",
        "bug.fix",
    ),
    "24ada7fe71e3a3a8741dd52e0a7fc3b97450535a": (
        "#1559 Remove the default completion cmd if alone",
        "behavior.change",
    ),
    "6dec1ae26659a130bdb4c985768d1853b0e1bc06": (
        "#2238 default ShellCompDirective customisable",
        "feature.add",
    ),
}


def _live_labeller() -> c.Labeller | None:
    """Prefer Claude Code (the census's measured path): an API key, or the operator's
    own login when ``CRB_CLAUDE_CODE_AUTH=cli``. Else an OpenAI-compatible key."""
    cli = os.environ.get(cc.AUTH_ENV, "").strip() == cc.AUTH_CLI
    if (os.environ.get(cc.API_KEY_ENV) or cli) and shutil.which("claude"):
        return lb.ClaudeCodeLabeller(effort=os.environ.get("CRB_TEST_LABEL_EFFORT", "low"))
    if os.environ.get("CEREBRAS_API_KEY"):
        return lb.OpenAILabeller(model=os.environ.get("CRB_TEST_LABEL_MODEL", "gpt-oss-120b"))
    return None


@pytest.mark.timeout(600)
def test_real_llm_labels_the_review_cobra_commits(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    labeller = _live_labeller()
    if labeller is None:
        pytest.skip(
            "no ANTHROPIC_API_KEY / CRB_CLAUDE_CODE_AUTH=cli / CEREBRAS_API_KEY: real-LLM check skipped"
        )
    clone = os.environ.get(_COBRA_CLONE_ENV, "")
    if clone and Path(clone, ".git").exists():
        repo = GitRepo(clone)
    else:
        from crb.core.git import clone_repo

        dest = tmp_path / "cobra"
        clone_repo(_COBRA, dest, timeout=300)
        repo = GitRepo(dest)
    report: list[dict[str, Any]] = []
    for sha, (what, implied) in _REVIEW_COMMITS.items():
        ev = c.commit_evidence(
            repo, sha, path_class="bug.fix"
        )  # cobra's path class is always bug.fix
        lab = labeller.label(
            subject=ev.subject,
            message=ev.message,
            diff_stats=ev.diff_stats,
            changed_paths=ev.changed_paths,
            path_class=ev.path_class,
        )
        assert lab.evidence_hash == ev.digest() and lab.labeller == labeller.name
        report.append(
            {
                "sha": sha[:10],
                "what": what,
                "review_implies": implied,
                "model": lab.intent_class,
                "confidence": lab.confidence,
                "resolved": c.resolve_class("bug.fix", lab),
                "rationale": lab.rationale,
            }
        )
    usage = getattr(labeller, "usage", None)
    with capsys.disabled():
        print("\nREAL-LLM LABELS (" + labeller.name + "):")
        for r in report:
            print(json.dumps(r, ensure_ascii=False))
        if usage is not None:
            print("usage: " + json.dumps(usage.to_dict()))
    # the contract, not the opinion: closed vocabulary, honest confidence, hash stamped
    for r in report:
        assert r["model"] in CLASS_VOCABULARY or r["model"] == UNCLASSIFIED
        assert 0.0 <= r["confidence"] <= 1.0
    # the whole point of the run: at least one of the three must leave `bug.fix`
    assert any(r["resolved"] != "bug.fix" for r in report), report
