"""The agentic Claude Code builder — the census's measured path.

Runs ``claude -p`` (headless) in the worktree with ``--output-format stream-json``
and parses the event stream for turns, tool uses, usage and cost. The tool set
is restricted (``--tools`` + ``--allowedTools``) and pre-approved under
``--permission-mode dontAsk`` so nothing can prompt, with deny rules for git
archaeology and network fetches (``--disallowedTools``). ``--bare`` (default)
makes authentication strictly ``ANTHROPIC_API_KEY`` (never the operator's
keychain or OAuth profile), skips the target repo's ``CLAUDE.md`` (a
prompt-injection vector) and hooks, and — as the CLI's simple mode — exposes
exactly ``Read/Edit/Bash`` (:data:`BARE_TOOLS`); ``bare=False`` restores the
full ``Read/Edit/Write/Glob/Grep/Bash`` set at the cost of that isolation.
``--no-session-persistence`` keeps transcripts off disk.

Authentication modes (``auth=``)
--------------------------------
``api_key`` (default, production)
    ``--bare``; ``ANTHROPIC_API_KEY`` is required and is the only credential; the
    isolation above holds in full.
``cli`` (developer / evaluation only — never production)
    No ``--bare``; the key is NOT required and NOT forwarded: the CLI authenticates
    with the **operator's own login** (``claude login``: OAuth profile in the macOS
    keychain / ``~/.claude/.credentials.json``), so spend and identity are the
    operator's subscription, not a service account's. Selected per run with
    ``builder_config: {"auth": "cli"}`` or per worker with ``CRB_CLAUDE_CODE_AUTH=cli``.

    Still isolated (checked against claude 2.1.132 ``--help``): the tool set
    (``--tools``/``--allowedTools``), ``--permission-mode dontAsk``, the deny rules
    (``--disallowedTools``), slash commands (``--disable-slash-commands``), the
    target repository's ``.claude/settings.json`` / ``settings.local.json`` — its
    hooks and permission rules — via ``--setting-sources user`` (the CLI's own
    switch: only the operator's *user* settings load), the minimal child
    environment (``PATH HOME LANG LC_ALL TMPDIR TERM TZ`` plus ``USER``/``LOGNAME``
    and ``CLAUDE_CONFIG_DIR``, nothing else), ``--no-session-persistence``, and
    every post-hoc guard (test tamper, git archaeology, network) — the grader
    decides regardless.

    NOT isolated: the target repository's ``CLAUDE.md`` files ARE auto-discovered
    (``--bare`` is the only switch that skips them; ``--setting-sources`` governs
    settings files, not memory files — a prompt-injection surface, mitigated only
    by the rules above and the grader); the operator's ``~/.claude/CLAUDE.md`` and
    user settings (user-level hooks included) load; the keychain is read; plugins
    and LSP that user settings enable are not disabled. The mode is recorded in
    ``describe()``, on ``build.start`` and in the run's apparatus.

The system prompt is the census ``wf_wave.js`` contract: no test edits, no git
archaeology, no network, ~25 tool-call budget, ``{done, summary}`` structured
output. The same :class:`TestFileGuard` is applied **post hoc** (diff the
worktree: a protected test changed → ``errors += tamper:``; the grader DQs
anyway) and every Bash command seen in the transcript is checked by
:class:`GitArchaeologyGuard` (a violation is recorded fail-closed even if the
CLI's deny rule refused it).

Model ids come from the ``claude-api`` skill (never guessed): ``claude-sonnet-5``
(default — the census's measured path), ``claude-opus-5``, ``claude-haiku-4-5``,
``claude-opus-4-8``; ``CRB_CLAUDE_CODE_MODEL`` moves the default.
Transport is injected (``spawn``) so tests replay canned stream-json lines.

Note: the skill's Claude *API* surface (Messages/Tool Runner) is deliberately
not used here — the Claude *Agent SDK* / Claude Code CLI is a separate product
with its own harness, and the CLI is what the census measured.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import warnings
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any, Protocol

from crb.builders.base import (
    STOP_DONE,
    STOP_MAX_COST,
    STOP_MAX_TURNS,
    STOP_MODEL_ERROR,
    STOP_WALL_CLOCK,
    Budget,
    BuildBrief,
    BuildOutcome,
    EventFn,
    GitArchaeologyGuard,
    TestFileGuard,
    emit,
)
from crb.builders.budget import CostMeter, price_for
from crb.core.redact import redact_and_cap
from crb.core.workspace import Workspace

#: The census's measured path (quality-floor essay): Sonnet 5 through the agentic CLI.
#: ``claude-opus-5`` is selectable per rung; ``CRB_CLAUDE_CODE_MODEL`` changes the default.
DEFAULT_MODEL = "claude-sonnet-5"
#: From the claude-api skill's model table (cached 2026-06-24). Aliases like
#: ``sonnet``/``opus`` are accepted by the CLI but warned about: an alias moves.
KNOWN_MODELS: frozenset[str] = frozenset(
    {
        "claude-opus-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-sonnet-5",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    }
)
API_KEY_ENV = "ANTHROPIC_API_KEY"

#: ``auth`` modes. ``api_key`` is production (``--bare``, key required); ``cli`` relies on
#: the operator's own CLI login (developer / evaluation only — see the module docstring).
AUTH_API_KEY = "api_key"
AUTH_CLI = "cli"
AUTH_MODES: tuple[str, ...] = (AUTH_API_KEY, AUTH_CLI)
#: Worker-environment defaults, used only when the rung / ``builder_config`` leaves the
#: field unset: ``CRB_CLAUDE_CODE_AUTH`` (``api_key`` | ``cli``) and ``CRB_CLAUDE_CODE_MODEL``.
#: A run's ladder always names its model (a rung cannot be model-less), so the model
#: default applies to direct instantiation (``get_builder("claude_code")``) and to the UI's
#: suggested value; the auth default applies to every run that does not say otherwise.
AUTH_ENV = "CRB_CLAUDE_CODE_AUTH"
MODEL_ENV = "CRB_CLAUDE_CODE_MODEL"
#: Where the CLI keeps its login/config when the operator relocated it; forwarded in
#: ``cli`` mode only (``HOME`` is always forwarded).
CLI_CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
#: What the CLI needs on top of the base passthrough to FIND its login in ``cli`` mode.
#: Measured on claude 2.1.132 / macOS: the keychain entry is keyed by ``$USER`` — with
#: ``HOME`` + ``PATH`` alone the CLI reports "Not logged in"; adding ``USER`` finds it.
#: A long-lived subscription token minted by ``claude setup-token`` — the headless way to
#: use a claude.ai login on a machine (or in a worker process) where the interactive
#: keychain token cannot be refreshed. Forwarded in ``cli`` mode only, never logged.
CLI_OAUTH_TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"  # noqa: S105 — an env var NAME, not a secret
_CLI_ENV_PASSTHROUGH: tuple[str, ...] = ("USER", "LOGNAME", CLI_CONFIG_DIR_ENV, CLI_OAUTH_TOKEN_ENV)
#: ``cli`` mode: load the operator's user settings only — never the target repository's
#: ``.claude/settings.json`` (hooks, permission rules) nor its ``.claude/settings.local.json``.
CLI_SETTING_SOURCES = "user"

#: Built-in tools requested. Under ``--bare`` (simple mode) the CLI exposes exactly
#: ``Bash, Edit, Read`` whatever is requested — verified against claude 2.1.132 —
#: so the bare set names those three and nothing that silently would not exist.
#: The init event's ``tools`` list is recorded in ``BuildOutcome.extra["session"]``
#: so the apparatus stamp says what the agent actually had.
BARE_TOOLS: tuple[str, ...] = ("Read", "Edit", "Bash")
FULL_TOOLS: tuple[str, ...] = ("Read", "Edit", "Write", "Glob", "Grep", "Bash")
TOOLS = FULL_TOOLS

#: Permission deny rules — defence in depth; the transcript scan is the belt.
DENY_RULES: tuple[str, ...] = (
    "WebFetch",
    "WebSearch",
    "Agent",
    "Bash(git log:*)",
    "Bash(git show:*)",
    "Bash(git reflog:*)",
    "Bash(git stash:*)",
    "Bash(git bisect:*)",
    "Bash(git checkout:*)",
    "Bash(git switch:*)",
    "Bash(git restore:*)",
    "Bash(git cat-file:*)",
    "Bash(git rev-list:*)",
    "Bash(git fetch:*)",
    "Bash(git pull:*)",
    "Bash(git push:*)",
    "Bash(git clone:*)",
    "Bash(git worktree:*)",
    "Bash(git reset:*)",
    "Bash(git branch:*)",
    "Bash(git tag:*)",
    "Bash(curl:*)",
    "Bash(wget:*)",
    "Bash(pip install:*)",
    "Bash(pip3 install:*)",
    "Bash(npm install:*)",
    "Bash(npm i:*)",
    "Bash(npm ci:*)",
    "Bash(go get:*)",
    "Bash(cargo add:*)",
    "Bash(gh:*)",
)

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "done": {"type": "boolean", "description": "true if the target tests pass"},
        "summary": {"type": "string", "description": "one-paragraph summary of the change made"},
    },
    "required": ["done", "summary"],
}

#: Environment passed to the CLI. Nothing else from the operator's shell leaks in.
_ENV_PASSTHROUGH: tuple[str, ...] = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TERM", "TZ")


def default_model() -> str:
    """The model a ``claude_code`` rung gets when none is named: ``CRB_CLAUDE_CODE_MODEL``,
    else :data:`DEFAULT_MODEL`. Read at run creation (API) and at instantiation (adapter)."""
    return os.environ.get(MODEL_ENV, "").strip() or DEFAULT_MODEL


def default_auth() -> str:
    """``CRB_CLAUDE_CODE_AUTH`` else ``api_key`` (validated by the constructor)."""
    return os.environ.get(AUTH_ENV, "").strip() or AUTH_API_KEY


def system_rules(budget: Budget) -> str:
    """The census ``wf_wave.js`` rules, appended to Claude Code's default prompt."""
    return (
        "You are completing a real code change in the git worktree you were started in.\n"
        "RULES (violations disqualify the run):\n"
        "- NEVER modify, delete, or add any test files. Source files only.\n"
        "- Work only inside this worktree.\n"
        "- Do not use git to peek at other commits (no git log/show/reflog/stash/bisect, no diff "
        "or checkout of another revision).\n"
        "- NEVER consult external sources for this change: no fetching the upstream repository, no "
        "package-registry downloads, no web lookups of the project's history or PRs. Solving by "
        "finding the real commit's diff anywhere is a DISQUALIFYING protocol violation. Solve from "
        "the local code and the failing tests only.\n"
        "- The test environment is ALREADY PROVISIONED: NEVER install or upgrade packages (no "
        "pip/uv/npm/yarn/pnpm install, go get, cargo add, mvn dependency:*). If the tests cannot "
        "import the package, run them EXACTLY with the test command in the task — it sets the "
        "interpreter and PYTHONPATH/NODE_PATH for this worktree.\n"
        f"Budget: roughly {budget.max_tool_calls} tool calls. If green early, stop early.\n"
        "Finish by reporting done=true only if the target test command exits 0."
    )


def task_prompt(brief: BuildBrief, worktree: Path) -> str:
    """The user prompt: the wf_wave.js task statement plus the method steps."""
    text = brief.task_text(worktree=str(worktree))
    if brief.sighted:
        cmd = brief.test_command or "(run the target test files with the project's test runner)"
        text += (
            "\n\nMETHOD (agentic loop):\n"
            f"1. Run the target tests to see the failures:\n   {cmd}\n"
            "2. Read the failing test(s) carefully — they are the executable spec.\n"
            "3. Explore the relevant source files, implement the change.\n"
            "4. Re-run the tests. Iterate until they pass (green).\n"
            "5. Be careful not to break neighbouring behaviour — keep the change minimal and "
            "idiomatic to the codebase."
        )
    else:
        text += (
            "\n\nMETHOD (agentic loop):\n"
            "1. Find the code the commit message describes (Grep/Glob/Read).\n"
            "2. Implement the change completely and idiomatically, including any new public "
            "behaviour the message implies.\n"
            "3. Run the project's own cheap checks (compile, lint, existing tests near the change).\n"
            "4. Keep the change minimal; do not break neighbouring behaviour."
        )
    return text


# ---------------------------------------------------------------------------
# Transport seam
# ---------------------------------------------------------------------------


class SpawnHandle(Protocol):
    """What ``spawn`` returns: a line iterator plus exit status once exhausted.
    ``kill()`` lets the reader stop the process early (e.g. on an auth failure)."""

    def lines(self) -> Iterator[str]: ...

    def kill(self) -> None: ...

    @property
    def returncode(self) -> int | None: ...

    @property
    def timed_out(self) -> bool: ...

    @property
    def stderr_tail(self) -> str: ...


SpawnFn = Callable[[list[str], Mapping[str, str], Path, int], SpawnHandle]


class SubprocessHandle:
    """Real transport: ``claude`` as a child process, killed as a group on timeout.

    A watchdog timer kills the process group at the deadline even if it is
    silent (a blocked ``readline`` would otherwise wait forever). stderr goes to
    a temporary file so it can never fill a pipe and deadlock the stdout reader.
    """

    def __init__(self, argv: list[str], env: Mapping[str, str], cwd: Path, timeout_s: int) -> None:
        self._stderr_file = tempfile.TemporaryFile(  # noqa: SIM115 — closed in lines()
            mode="w+", encoding="utf-8", errors="replace"
        )
        self._proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=self._stderr_file,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
        )
        self._timed_out = False
        self._stderr = ""
        self._watchdog = threading.Timer(timeout_s, self._on_deadline)
        self._watchdog.daemon = True
        self._watchdog.start()

    def lines(self) -> Iterator[str]:
        assert self._proc.stdout is not None
        try:
            for line in self._proc.stdout:
                yield line.rstrip("\n")
        finally:
            self._watchdog.cancel()
            try:  # reap the child whether it exited, was killed, or the reader stopped early
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.kill()
                self._proc.wait()
            try:
                self._stderr_file.seek(0)
                self._stderr = self._stderr_file.read()[-4000:]
            except (OSError, ValueError):
                self._stderr = ""
            finally:
                self._stderr_file.close()

    def _on_deadline(self) -> None:
        self._timed_out = True
        self.kill()

    def kill(self) -> None:
        try:
            os.killpg(self._proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            self._proc.kill()

    @property
    def returncode(self) -> int | None:
        return self._proc.returncode

    @property
    def timed_out(self) -> bool:
        return self._timed_out

    @property
    def stderr_tail(self) -> str:
        return self._stderr


def subprocess_spawn(
    argv: list[str], env: Mapping[str, str], cwd: Path, timeout_s: int
) -> SpawnHandle:
    return SubprocessHandle(argv, env, cwd, timeout_s)


# ---------------------------------------------------------------------------
# Stream parsing
# ---------------------------------------------------------------------------


class StreamStats:
    """Accumulates what the stream-json events say. Tolerant of unknown shapes:
    anything it cannot read is skipped, never inferred."""

    def __init__(self, git_guard: GitArchaeologyGuard, guard: TestFileGuard | None = None) -> None:
        self.git_guard = git_guard
        self.guard = guard
        self.assistant_messages = 0
        self.tool_uses = 0
        self.tool_names: list[str] = []
        self.tokens_in = 0
        self.tokens_out = 0
        self.cached_in = 0
        self.result: dict[str, Any] | None = None
        self.init: dict[str, Any] = {}
        self.last_text = ""
        self.violations: list[str] = []
        self.refused: list[str] = []
        self.bash_commands: list[str] = []
        self.write_paths: list[str] = []
        self.events: list[dict[str, Any]] = []
        self.parse_errors = 0
        self.api_retries: list[int] = []
        self.auth_failed = False

    def feed(self, line: str, *, keep: bool) -> dict[str, Any] | None:
        line = line.strip()
        if not line:
            return None
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            self.parse_errors += 1
            return None
        if not isinstance(ev, dict):
            return None
        kind = str(ev.get("type", ""))
        summary: dict[str, Any] = {"kind": kind}
        if kind == "system" and ev.get("subtype") == "init":
            self.init = {
                k: ev.get(k)
                for k in ("model", "session_id", "tools", "permissionMode", "cwd", "apiKeySource")
                if k in ev
            }
            summary["model"] = self.init.get("model")
        elif kind == "system" and ev.get("subtype") == "api_retry":
            status = ev.get("error_status")
            code = int(status) if isinstance(status, int) and not isinstance(status, bool) else 0
            self.api_retries.append(code)
            summary.update({"subtype": "api_retry", "error_status": code})
            if code in {401, 403}:
                self.auth_failed = True
        elif kind == "assistant":
            self.assistant_messages += 1
            msg = ev.get("message") or {}
            self._usage(msg.get("usage"))
            names: list[str] = []
            for block in msg.get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    self.last_text = str(block.get("text", "") or "")
                    if keep:
                        summary["text"] = redact_and_cap(self.last_text, max_chars=2000)
                elif block.get("type") == "tool_use":
                    self.tool_uses += 1
                    name = str(block.get("name", ""))
                    names.append(name)
                    self.tool_names.append(name)
                    self._inspect_tool_use(
                        name, block.get("input") or {}, summary if keep else None
                    )
            summary["tool_uses"] = names
        elif kind == "user":
            msg = ev.get("message") or {}
            n = sum(
                1
                for b in (msg.get("content") or [])
                if isinstance(b, dict) and b.get("type") == "tool_result"
            )
            summary["tool_results"] = n
        elif kind == "result":
            self.result = ev
            summary.update(
                {
                    "subtype": ev.get("subtype"),
                    "is_error": ev.get("is_error"),
                    "num_turns": ev.get("num_turns"),
                    "total_cost_usd": ev.get("total_cost_usd"),
                }
            )
            for d in ev.get("permission_denials") or []:
                if isinstance(d, dict):
                    self.refused.append(
                        redact_and_cap(
                            f"{d.get('tool_name', '?')}: {json.dumps(d.get('tool_input', {}))}",
                            max_chars=300,
                        )
                    )
        self.events.append(summary)
        return summary

    def _usage(self, usage: Any) -> None:
        if not isinstance(usage, dict):
            return
        # cache CREATION is real input (billed at a premium); cache READS are recorded
        # separately so "tokens in" is never a misleading 50 for a 60k-token session.
        self.tokens_in += int(usage.get("input_tokens", 0) or 0) + int(
            usage.get("cache_creation_input_tokens", 0) or 0
        )
        self.tokens_out += int(usage.get("output_tokens", 0) or 0)
        self.cached_in += int(usage.get("cache_read_input_tokens", 0) or 0)

    def _inspect_tool_use(self, name: str, inp: Any, summary: dict[str, Any] | None) -> None:
        if not isinstance(inp, dict):
            return
        if name == "Bash":
            cmd = str(inp.get("command", "") or "")
            self.bash_commands.append(cmd)
            if summary is not None:
                summary.setdefault("commands", []).append(redact_and_cap(cmd, max_chars=300))
            reason = self.git_guard.check_shell(cmd)
            if reason:
                self.violations.append(f"{reason} (attempted: {cmd[:120]})")
        elif name in {"Edit", "Write", "MultiEdit", "NotebookEdit"}:
            path = str(inp.get("file_path", "") or inp.get("path", "") or "")
            self.write_paths.append(path)
            if summary is not None:
                summary.setdefault("paths", []).append(path)
            if self.guard is not None and path:
                rel = path
                try:
                    p = Path(path)
                    if p.is_absolute():
                        rel = str(p.resolve().relative_to(self.guard.root))
                except (ValueError, OSError):
                    self.refused.append(f"{name} outside worktree: {path}")
                    return
                if self.guard.check_write(rel):
                    self.refused.append(f"{name} {rel}: {self.guard.check_write(rel)}")

    # --- totals ---------------------------------------------------------------
    def totals(self) -> tuple[int, int, int]:
        r = self.result or {}
        usage = r.get("usage")
        if isinstance(usage, dict) and (usage.get("input_tokens") or usage.get("output_tokens")):
            return (
                int(usage.get("input_tokens", 0) or 0)
                + int(usage.get("cache_creation_input_tokens", 0) or 0),
                int(usage.get("output_tokens", 0) or 0),
                int(usage.get("cache_read_input_tokens", 0) or 0),
            )
        return self.tokens_in, self.tokens_out, self.cached_in

    def reported_cost(self) -> float | None:
        r = self.result or {}
        v = r.get("total_cost_usd")
        if isinstance(v, int | float) and not isinstance(v, bool):
            return float(v)
        return None

    def turns(self) -> int:
        r = self.result or {}
        v = r.get("num_turns")
        if isinstance(v, int) and not isinstance(v, bool) and v > 0:
            return v
        return self.assistant_messages

    def claim(self) -> tuple[bool, str]:
        """``(done, summary)`` from structured output, else the result text, else the
        last assistant text. Untrusted either way."""
        r = self.result or {}
        so = r.get("structured_output")
        if isinstance(so, dict) and "done" in so:
            return bool(so.get("done")), str(so.get("summary", "") or "")
        text = str(r.get("result", "") or "") or self.last_text
        stripped = text.strip()
        if stripped.startswith("{"):
            try:
                obj = json.loads(stripped)
                if isinstance(obj, dict) and "done" in obj:
                    return bool(obj.get("done")), str(obj.get("summary", "") or "")
            except json.JSONDecodeError:
                pass
        return False, text


def _stop_reason(stats: StreamStats, *, timed_out: bool) -> str:
    if timed_out:
        return STOP_WALL_CLOCK
    r = stats.result or {}
    sub = str(r.get("subtype", "") or "")
    if sub == "error_max_turns":
        return STOP_MAX_TURNS
    if "budget" in sub:
        return STOP_MAX_COST
    if r.get("is_error") or sub.startswith("error") or not r:
        return STOP_MODEL_ERROR
    return STOP_DONE


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class ClaudeCodeBuilder:
    """Agentic Claude Code (``claude -p``) builder."""

    name = "claude_code"
    provider = "anthropic"

    def __init__(
        self,
        *,
        model: str = "",
        claude_binary: str = "",
        spawn: SpawnFn | None = None,
        effort: str = "",
        bare: bool | None = None,
        auth: str = "",
        keep_transcript: bool = False,
        extra_args: tuple[str, ...] | list[str] = (),
    ) -> None:
        """``model`` / ``auth`` resolve explicit value → worker environment
        (:data:`MODEL_ENV` / :data:`AUTH_ENV`) → :data:`DEFAULT_MODEL` / ``api_key``.
        ``bare`` defaults to ``True`` under ``auth="api_key"`` and to ``False`` under
        ``auth="cli"`` (``--bare`` forces API-key auth, so the two cannot combine)."""
        model = model.strip() or default_model()
        auth_source = "explicit" if auth else AUTH_ENV
        auth = auth.strip() or default_auth()
        self.model = model
        if model not in KNOWN_MODELS:
            warnings.warn(
                f"claude_code: model {model!r} is not in the known id table {sorted(KNOWN_MODELS)}; "
                "aliases move over time — prefer an exact id",
                stacklevel=2,
            )
        if auth not in AUTH_MODES:
            raise ValueError(
                f"claude_code: auth must be one of {AUTH_MODES}, not {auth!r} (from {auth_source})"
            )
        if bare is None:
            bare = auth == AUTH_API_KEY
        if bare and auth == AUTH_CLI:
            raise ValueError(
                "claude_code: auth='cli' cannot combine with bare=True (--bare makes "
                "authentication strictly ANTHROPIC_API_KEY)"
            )
        self.claude_binary = claude_binary
        self._spawn = spawn
        self.effort = effort
        self.auth = auth
        self.bare = bare
        self.tools: tuple[str, ...] = BARE_TOOLS if bare else FULL_TOOLS
        self.keep_transcript = keep_transcript
        self.extra_args = tuple(str(a) for a in extra_args)

    def describe(self) -> dict[str, Any]:
        return {
            "builder": self.name,
            "model": self.model,
            "provider": self.provider,
            "process": "claude -p stream-json, tools=" + ",".join(self.tools),
            "effort": self.effort or "default",
            "bare": self.bare,
            "auth": self.auth,
        }

    def _binary(self) -> str:
        if self.claude_binary:
            return self.claude_binary
        found = shutil.which("claude")
        if not found:
            raise FileNotFoundError("the 'claude' CLI was not found on PATH")
        return found

    def argv(
        self, brief: BuildBrief, budget: Budget, worktree: Path, *, binary: str = "claude"
    ) -> list[str]:
        """The full headless invocation (tests assert on this directly)."""
        args = [
            binary,
            "-p",
            task_prompt(brief, worktree),
            "--output-format",
            "stream-json",
            "--verbose",
            "--model",
            self.model,
            "--max-turns",
            str(budget.max_turns),
            "--permission-mode",
            "dontAsk",
            "--tools",
            ",".join(self.tools),
            "--allowedTools",
            ",".join(self.tools),
            "--disallowedTools",
            ",".join(DENY_RULES),
            "--append-system-prompt",
            system_rules(budget),
            "--json-schema",
            json.dumps(OUTPUT_SCHEMA, separators=(",", ":")),
            "--no-session-persistence",
            "--disable-slash-commands",
        ]
        if budget.max_cost_usd > 0:
            args += ["--max-budget-usd", f"{budget.max_cost_usd:.4f}"]
        if self.effort:
            args += ["--effort", self.effort]
        if self.bare:
            args.append("--bare")
        if self.auth == AUTH_CLI:
            args += ["--setting-sources", CLI_SETTING_SOURCES]
        args += list(self.extra_args)
        return args

    @staticmethod
    def env(auth: str = AUTH_API_KEY) -> dict[str, str]:
        """The child's environment: the passthrough set plus the CLI's hygiene flags.

        ``api_key``: ``ANTHROPIC_API_KEY`` is required (``PermissionError`` otherwise)
        and forwarded. ``cli``: the key is neither required nor forwarded — the
        CLI's own login is the only credential, so a run can never silently bill
        a key the operator meant for production; ``USER``/``LOGNAME`` (the keychain
        account the login is stored under), ``CLAUDE_CONFIG_DIR`` (a relocated
        login) and ``CLAUDE_CODE_OAUTH_TOKEN`` (a ``claude setup-token`` token for
        headless use) are forwarded when set. Nothing else from the shell leaks in.
        """
        env = {k: v for k, v in os.environ.items() if k in _ENV_PASSTHROUGH}
        if auth == AUTH_CLI:
            for k in _CLI_ENV_PASSTHROUGH:
                v = os.environ.get(k, "").strip()
                if v:
                    env[k] = v
        else:
            key = os.environ.get(API_KEY_ENV, "").strip()
            if not key:
                raise PermissionError(
                    f"{API_KEY_ENV} is not set — the claude_code builder needs it (auth={auth!r})"
                )
            env[API_KEY_ENV] = key
        env.setdefault("LANG", "C.UTF-8")
        env["NO_COLOR"] = "1"
        env["CI"] = "1"
        env["DISABLE_AUTOUPDATER"] = "1"
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        return env

    def build(
        self,
        workspace: Workspace,
        brief: BuildBrief,
        budget: Budget,
        *,
        on_event: EventFn | None = None,
    ) -> BuildOutcome:
        started = time.monotonic()
        config = brief.repo_config()
        guard = TestFileGuard(workspace.root, config, brief.test_files, mode=brief.mode)
        stats = StreamStats(GitArchaeologyGuard(), guard)
        meter = CostMeter(price_for(self.model), model=self.model)
        errors: list[str] = []

        def finish(
            *, done: bool, summary: str, stop: str, extra: Mapping[str, Any]
        ) -> BuildOutcome:
            tampered = guard.tampered(workspace)
            if tampered:
                errors.append("tamper: test files modified: " + ", ".join(tampered[:10]))
            errors.extend(stats.violations)
            tin, tout, cached = stats.totals()
            # tokens_in is TOTAL input (cache reads included, as CostMeter expects); cached is the subset
            meter.add(tin + cached, tout, cached_in=cached, cost_usd=stats.reported_cost())
            return BuildOutcome(
                builder=self.name,
                model=self.model,
                provider=self.provider,
                mode=brief.mode,
                done=done and not tampered,
                summary=summary,
                turns=stats.turns(),
                tool_calls=stats.tool_uses,
                tokens_in=meter.tokens_in,
                tokens_out=meter.tokens_out,
                tokens_cached=meter.cached_in,
                cost_usd=meter.cost_usd,
                cost_known=meter.cost_known,
                latency_s=time.monotonic() - started,
                stop_reason=stop,
                errors=tuple(errors),
                transcript=tuple(stats.events) if self.keep_transcript else (),
                budget=budget,
                extra=dict(extra),
            )

        try:
            binary = self._binary()
            env = self.env(self.auth)
        except (FileNotFoundError, PermissionError) as exc:
            errors.append(f"model_error: {exc}")
            return finish(done=False, summary="", stop=STOP_MODEL_ERROR, extra={})

        argv = self.argv(brief, budget, workspace.root, binary=binary)
        spawn = self._spawn or subprocess_spawn
        emit(
            on_event,
            "build.start",
            builder=self.name,
            model=self.model,
            mode=brief.mode,
            auth=self.auth,
        )
        over_cap = False
        try:
            handle = spawn(argv, env, workspace.root, budget.wall_clock_s)
            for line in handle.lines():
                ev = stats.feed(line, keep=self.keep_transcript)
                if ev is not None:
                    emit(on_event, "build.event", **{k: v for k, v in ev.items() if k != "text"})
                if stats.auth_failed:
                    # the CLI retries 401/403 ten times with backoff; auth is not transient
                    hint = (
                        "run `claude login` as the worker's user"
                        if self.auth == AUTH_CLI
                        else f"check {API_KEY_ENV}"
                    )
                    errors.append(
                        f"model_error: authentication failed (HTTP {stats.api_retries[-1]}) — {hint}"
                    )
                    handle.kill()
                    break
                if stats.tool_uses > budget.max_tool_calls * 2 and not over_cap:
                    # the CLI has no tool-call cap; --max-turns bounds it, this is the belt
                    over_cap = True
                    errors.append(f"budget: tool uses exceeded 2x cap ({stats.tool_uses})")
        except Exception as exc:
            errors.append(
                f"model_error: {type(exc).__name__}: {redact_and_cap(str(exc), max_chars=500)}"
            )
            return finish(done=False, summary="", stop=STOP_MODEL_ERROR, extra={})

        timed_out = bool(handle.timed_out)
        rc = handle.returncode
        if timed_out:
            errors.append(f"wall_clock: killed after {budget.wall_clock_s}s")
        elif rc not in (0, None) and stats.result is None and not stats.auth_failed:
            errors.append(
                f"model_error: claude exited rc={rc}: {redact_and_cap(handle.stderr_tail, max_chars=500)}"
            )
        if stats.result is None and not timed_out and not stats.auth_failed:
            errors.append("model_error: no result event in stream")
        elif stats.result is not None and stats.result.get("is_error"):
            errors.append(
                "model_error: "
                + redact_and_cap(
                    f"{stats.result.get('subtype', '')}: {stats.result.get('result', '')}",
                    max_chars=500,
                )
            )
        if stats.parse_errors:
            errors.append(f"stream: {stats.parse_errors} unparseable line(s)")
        done, summary = stats.claim()
        stop = _stop_reason(stats, timed_out=timed_out)
        extra = {
            "session": stats.init,
            "tool_names": stats.tool_names[:200],
            "refused": stats.refused[:20],
            "bash_commands": [redact_and_cap(c, max_chars=200) for c in stats.bash_commands[:50]],
            "result_subtype": (stats.result or {}).get("subtype"),
            "returncode": rc,
            "api_retries": stats.api_retries[:20],
        }
        return finish(done=done and stop == STOP_DONE, summary=summary, stop=stop, extra=extra)


__all__ = [
    "API_KEY_ENV",
    "AUTH_API_KEY",
    "AUTH_CLI",
    "AUTH_ENV",
    "AUTH_MODES",
    "BARE_TOOLS",
    "CLI_CONFIG_DIR_ENV",
    "CLI_SETTING_SOURCES",
    "DEFAULT_MODEL",
    "DENY_RULES",
    "FULL_TOOLS",
    "KNOWN_MODELS",
    "MODEL_ENV",
    "OUTPUT_SCHEMA",
    "TOOLS",
    "ClaudeCodeBuilder",
    "SpawnFn",
    "SpawnHandle",
    "StreamStats",
    "SubprocessHandle",
    "default_auth",
    "default_model",
    "subprocess_spawn",
    "system_rules",
    "task_prompt",
]
