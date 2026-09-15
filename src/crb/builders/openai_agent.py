"""In-process tool-loop builder over any OpenAI-compatible function-calling model.

The loop design is the census ``agentic_generate`` driver; the tool surface is
the ``gptoss_agent`` bench: ``list_files``, ``read_file``, ``search_repo``,
``apply_edit``, ``write_file``, ``run_target_tests`` (sighted only) and a
narrow ``run_command``. Every write goes through :class:`TestFileGuard`; every
command through :class:`GitArchaeologyGuard` *and* an executable allowlist,
and is executed by the injected :class:`~crb.core.execution.Executor` — so a
docker executor sandboxes the builder's commands exactly as it sandboxes the
grader's test runs.

``run_target_tests`` runs the *sighted, spec-visible* target scope through the
injected runner. It is never the regression belt, and in blind mode the tool
does not exist: the held-out oracle is never shown to the builder.

The model is reached through a ``model_fn(messages, tools) -> ModelTurn`` seam;
tests inject a scripted fake, production uses :class:`OpenAIChat`.

Navigation
----------
What it is:   The in-process agentic builder — ``OpenAIAgentBuilder`` — with its tool surface
              (``_Tools``) and the function-calling schema the model is offered.
What it does: Runs a read / search / edit / run loop against any OpenAI-compatible
              function-calling model under the budget tracker; every write passes the
              ``TestFileGuard``, every command the ``GitArchaeologyGuard`` plus an executable
              allowlist, and runs through the injected executor (a docker executor sandboxes
              the model's commands like the grader's). ``run_target_tests`` exists only in
              sighted mode; a tool crash or refusal is a tool result, never a loop crash.
How:          task text + method → ``model_fn(messages, schema)`` → ``ModelTurn`` → for each
              tool call: ``tracker.can_call_tool`` → ``_Tools.dispatch`` → result message →
              repeat; a turn with no tool call is the summary (or a nudge, up to
              ``MAX_NUDGES``) → ``finish``: tamper scan → outcome.
Layer:        builders — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md,
              docs/adr/0012-builder-in-a-sealed-container.md
Works with:   src/crb/builders/base.py (brief, budget, outcome, both guards),
              src/crb/builders/openai_client.py (``ModelFn``/``ModelTurn``/``ToolCall``),
              src/crb/builders/editblock.py (shares ``apply_edit_blocks``/``compile_check``),
              src/crb/builders/budget.py (``BudgetTracker``), src/crb/core/execution.py (the
              executor the commands run through), src/crb/core/runners/base.py (the sighted
              test tool), src/crb/builders/container.py (supplies a sealed executor)
Tested by:    tests/test_builders_openai_agent.py
Touch when:   never for a new repository; a build/test tool a repository needs that is not
              in ``RUN_COMMAND_ALLOWLIST`` is added there with a test; a new tool means a
              schema entry, a ``_Tools`` method and a ``dispatch`` branch together.
"""

from __future__ import annotations

import fnmatch
import json
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from crb.builders.base import (
    STOP_DONE,
    STOP_MODEL_ERROR,
    STOP_NO_TOOL_CALL,
    Budget,
    BuildBrief,
    BuildOutcome,
    EventFn,
    GitArchaeologyGuard,
    GuardRefused,
    TestFileGuard,
    emit,
)
from crb.builders.budget import BudgetTracker, CostMeter, price_for
from crb.builders.editblock import apply_edit_blocks, compile_check
from crb.builders.openai_client import EndpointConfig, ModelFn, ModelTurn, ToolCall, make_chat
from crb.core.execution import Command, Executor, LocalExecutor
from crb.core.redact import redact_and_cap
from crb.core.runners import get_runner
from crb.core.runners.base import BaseRunner
from crb.core.spec import RepoConfig
from crb.core.workspace import Workspace

READ_CHAR_CAP = 20_000
READ_LINE_WINDOW = 150
LIST_MAX = 2_000
SEARCH_MAX_LINES = 50
SEARCH_LINE_CAP = 200
TOOL_RESULT_CAP = 12_000
COMMAND_TIMEOUT_S = 300
MAX_NUDGES = 2

#: Executables ``run_command`` may launch (build/test tools only). ``git`` is
#: additionally filtered by :class:`GitArchaeologyGuard`.
RUN_COMMAND_ALLOWLIST: frozenset[str] = frozenset(
    {
        "python",
        "python3",
        "pytest",
        "go",
        "node",
        "npm",
        "npx",
        "yarn",
        "pnpm",
        "mvn",
        "gradle",
        "cargo",
        "make",
        "ruff",
        "mypy",
        "black",
        "tsc",
        "eslint",
        "vitest",
        "jest",
        "mocha",
        "git",
        "ls",
        "cat",
        "head",
        "tail",
        "wc",
        "grep",
        "rg",
        "find",
    }
)

SYSTEM_PROMPT = """You are a senior engineer reproducing a code change in an isolated checkout. You have TOOLS.
Work like an engineer: find and read the relevant code, make an edit, verify, and ITERATE.

Rules (strict): edit only NON-TEST source. Never modify, weaken, add or skip any test file or conftest.
Do not guess blindly — read the actual code before editing. Use apply_edit with EXACT text copied from
the file for `search`. Do not use git history or the network. When you are done, reply with a short
plain-text summary of the change (no tool call)."""

SIGHTED_METHOD = """METHOD: 1) run_target_tests to see the failures; 2) read the failing test(s) — they
are the executable spec; 3) explore the source with search_repo/read_file and implement the change;
4) run_target_tests again; iterate until ALL PASS, then stop with a summary."""

BLIND_METHOD = """METHOD: the tests for this change are held out. 1) search_repo/read_file to find the
code the commit message describes; 2) implement the change completely and idiomatically, including
any new public behaviour the message implies; 3) run_command with the project's own checks (compile,
lint, existing tests) where cheap; then stop with a summary."""


def tool_schema(*, sighted: bool) -> list[dict[str, Any]]:
    """The OpenAI function-calling tool list; ``run_target_tests`` only when sighted."""

    def fn(
        name: str, desc: str, props: Mapping[str, Any], required: Sequence[str]
    ) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": {
                    "type": "object",
                    "properties": dict(props),
                    "required": list(required),
                },
            },
        }

    tools = [
        fn(
            "list_files",
            "List tracked files (repo-relative). Optional glob filters, e.g. 'src/**/*.py'.",
            {"glob": {"type": "string"}},
            [],
        ),
        fn(
            "read_file",
            "Read a file (repo-relative). Optional 1-based start_line/end_line window; "
            "the body is raw text you can copy as an apply_edit search anchor.",
            {
                "path": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
            },
            ["path"],
        ),
        fn(
            "search_repo",
            "grep -n an extended regex across the repo; returns path:line: text hits.",
            {"pattern": {"type": "string"}},
            ["pattern"],
        ),
        fn(
            "apply_edit",
            "Replace an EXACT block of text in a source file. `search` must be copied verbatim "
            "from the current file (indentation included).",
            {
                "path": {"type": "string"},
                "search": {"type": "string"},
                "replace": {"type": "string"},
            },
            ["path", "search", "replace"],
        ),
        fn(
            "write_file",
            "Write `content` as the full body of a NEW or existing source file.",
            {"path": {"type": "string"}, "content": {"type": "string"}},
            ["path", "content"],
        ),
        fn(
            "run_command",
            "Run a build/test tool in the repo (argv list, no shell). Allowed: the language's "
            "test/build/lint tools and read-only git (status, diff, ls-files, grep).",
            {"argv": {"type": "array", "items": {"type": "string"}}},
            ["argv"],
        ),
    ]
    if sighted:
        tools.append(
            fn(
                "run_target_tests",
                "Run the target failing tests. Returns pass/fail and the output tail.",
                {},
                [],
            )
        )
    return tools


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class _Tools:
    """Sandbox-scoped tool implementations. Pure functions of the worktree + args."""

    def __init__(
        self,
        ws: Workspace,
        brief: BuildBrief,
        guard: TestFileGuard,
        *,
        runner: BaseRunner | None,
        executor: Executor,
        remaining_s: Callable[[], float],
    ) -> None:
        self.ws = ws
        self.brief = brief
        self.guard = guard
        self.git_guard = GitArchaeologyGuard(cwd=ws.root)
        self.runner = runner
        self.executor = executor
        self.remaining_s = remaining_s
        self.refused: list[str] = []
        self.violations: list[str] = []
        self.target_green = False

    # --- read side ---------------------------------------------------------------
    def list_files(self, glob: str = "") -> str:
        """Tracked files (git's view), optionally filtered by a glob; capped at ``LIST_MAX``."""
        entries = [
            e
            for e in self.ws.repo.run("ls-files", cwd=self.ws.root).lines
            if not e.startswith(".git/")
        ]
        if glob:
            g = str(glob)
            entries = [e for e in entries if fnmatch.fnmatch(e, g) or Path(e).match(g)]
        entries = entries[:LIST_MAX]
        return "\n".join(entries) if entries else "(no files match)"

    def read_file(self, path: str, start_line: Any = None, end_line: Any = None) -> str:
        """A numbered window of a file (tests may be read; ``.git`` and traversal may not)."""
        reason = self.guard.check_read(path)
        if reason:
            return f"ERROR: {reason}"
        full = self.ws.root / path
        if not full.is_file():
            return f"ERROR: file not found: {path}"
        try:
            text = full.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"ERROR: could not read {path}: {type(exc).__name__}"
        if start_line is None:
            if len(text) > READ_CHAR_CAP:
                return (
                    text[:READ_CHAR_CAP]
                    + f"\n... (truncated at {READ_CHAR_CAP} chars; use start_line/end_line to page)"
                )
            return text
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines = lines[:-1]
        total = len(lines)
        if total == 0:
            return "# lines 0-0 of 0\n"
        start = _clamp_int(start_line, 1, 1, total)
        end = _clamp_int(end_line, start - 1 + READ_LINE_WINDOW, start, total)
        body = "\n".join(lines[start - 1 : end])[:READ_CHAR_CAP]
        out = f"# lines {start}-{end} of {total}\n{body}"
        if end < total:
            out += f"\n... (call read_file with start_line={end + 1} to continue)"
        return out

    def search_repo(self, pattern: str) -> str:
        if not pattern or not str(pattern).strip():
            return "ERROR: empty search pattern"
        argv = [
            "grep",
            "-rnIE",
            "--exclude-dir=.git",
            "--exclude-dir=node_modules",
            "--exclude-dir=.venv",
            "--",
            str(pattern),
            ".",
        ]
        try:
            proc = subprocess.run(
                argv,
                cwd=str(self.ws.root),
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return f"ERROR: search failed: {type(exc).__name__}"
        raw = [ln[2:] if ln.startswith("./") else ln for ln in proc.stdout.splitlines() if ln]
        if not raw:
            return f"no matches for {pattern!r}"
        out = [
            ln[:SEARCH_LINE_CAP] + (" ...(truncated)" if len(ln) > SEARCH_LINE_CAP else "")
            for ln in raw[:SEARCH_MAX_LINES]
        ]
        if len(raw) > SEARCH_MAX_LINES:
            out.append(f"... ({len(raw) - SEARCH_MAX_LINES} more matches; refine the pattern)")
        return "\n".join(out)

    # --- write side ----------------------------------------------------------------
    def apply_edit(self, path: str, search: str, replace: str) -> str:
        """One SEARCH/REPLACE on an existing file through the guard; a non-compiling
        result is written AND warned about (the model must fix it before testing)."""
        reason = self.guard.check_write(path)
        if reason:
            self.refused.append(f"apply_edit {path}: {reason}")
            return f"ERROR: {reason}"
        full = self.ws.root / path
        if not full.is_file():
            return f"ERROR: file not found: {path} (use write_file to create a new file)"
        src = full.read_text(encoding="utf-8", errors="replace")
        new, applied = apply_edit_blocks(src, [(str(search), str(replace))])
        if not applied:
            return (
                "ERROR: search text NOT FOUND — copy it EXACTLY (with indentation) from the current "
                "file via read_file."
            )
        full.write_text(new, encoding="utf-8")
        ok, err = compile_check(path, new)
        note = (
            ""
            if ok
            else f"\nWARNING: {path} no longer compiles ({err}) — fix it before running tests."
        )
        return f"OK: edited {path}.{note}"

    def write_file(self, path: str, content: str) -> str:
        """Create or overwrite a non-test file through the guard."""
        reason = self.guard.check_write(path)
        if reason:
            self.refused.append(f"write_file {path}: {reason}")
            return f"ERROR: {reason}"
        try:
            full = self.guard.resolve_write(path)
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(str(content), encoding="utf-8")
        except (GuardRefused, OSError) as exc:
            return f"ERROR: could not write {path}: {exc}"
        ok, err = compile_check(path, str(content))
        note = "" if ok else f"\nWARNING: {path} does not compile ({err})."
        return f"OK: wrote {path}.{note}"

    # --- execution -----------------------------------------------------------------
    def run_target_tests(self) -> str:
        """The sighted target scope through the injected runner — the builder's feedback,
        never the belt; records a green so the outcome's ``done`` can be claimed."""
        if not self.brief.sighted or self.runner is None:
            return "ERROR: the target tests are held out in blind mode"
        timeout = max(1, min(int(self.remaining_s()), self.runner.default_timeout))
        run = self.runner.run(self.executor, self.ws.root, self.brief.target_tests, timeout=timeout)
        tail = redact_and_cap(run.tail, max_chars=6000)
        if run.timed_out:
            return f"TESTS TIMED OUT after {timeout}s:\n{tail}"
        if run.green:
            self.target_green = True
            return f"ALL TESTS PASS (rc=0):\n{tail}"
        failing = ", ".join(sorted(run.failing)[:20])
        return f"TESTS STILL FAILING (rc={run.returncode}) failing={failing or 'unattributed'}:\n{tail}"

    def run_command(self, argv: Any) -> str:
        """An allowlisted build/test tool, checked by the shell guard first (a hit is a
        recorded violation), then run through the executor with a scratch-only write path."""
        if isinstance(argv, str):
            argv = argv.split()
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            return "ERROR: argv must be a non-empty list of strings"
        reason = self.git_guard.check(argv)
        if reason:
            self.violations.append(f"{reason} (attempted: {' '.join(argv)[:120]})")
            return f"REFUSED: {reason}"
        exe = Path(argv[0]).name
        if exe not in RUN_COMMAND_ALLOWLIST:
            self.refused.append(f"run_command {exe}: not on the allowlist")
            return f"REFUSED: '{exe}' is not an allowed build/test tool"
        if any("/.git" in a or a.startswith(".git") for a in argv[1:]):
            self.violations.append(f"archaeology: touched .git via {exe}")
            return "REFUSED: .git is off limits"
        timeout = max(1, min(int(self.remaining_s()), COMMAND_TIMEOUT_S))
        try:
            cmd = Command(
                tuple(argv), self.ws.root, timeout=timeout, writable_paths=(".crb_scratch",)
            )
            res = self.executor.run(cmd)
        except Exception as exc:
            return f"ERROR: command failed to launch: {type(exc).__name__}: {exc}"
        out = redact_and_cap(res.combined, max_chars=TOOL_RESULT_CAP)
        status = "TIMED OUT" if res.timed_out else f"rc={res.returncode}"
        return f"[{status}]\n{out}"

    # --- dispatch --------------------------------------------------------------------
    def dispatch(self, call: ToolCall) -> str:
        """Route one tool call by name; arguments are coerced, never trusted."""
        if call.parse_error:
            return f"ERROR: {call.parse_error}"
        a = call.arguments
        try:
            if call.name == "list_files":
                return self.list_files(str(a.get("glob", "") or ""))
            if call.name == "read_file":
                return self.read_file(
                    str(a.get("path", "")), a.get("start_line"), a.get("end_line")
                )
            if call.name == "search_repo":
                return self.search_repo(str(a.get("pattern", "")))
            if call.name == "apply_edit":
                return self.apply_edit(
                    str(a.get("path", "")), str(a.get("search", "")), str(a.get("replace", ""))
                )
            if call.name == "write_file":
                return self.write_file(str(a.get("path", "")), str(a.get("content", "")))
            if call.name == "run_target_tests":
                return self.run_target_tests()
            if call.name == "run_command":
                return self.run_command(a.get("argv"))
        except Exception as exc:  # a tool crash is an observation, never a loop crash
            return f"ERROR: tool crashed: {type(exc).__name__}: {exc}"
        return f"ERROR: unknown tool {call.name!r}"


def _clamp_int(value: Any, default: int, lo: int, hi: int) -> int:
    """An int from model-supplied JSON, defaulted and clamped (models send strings, floats)."""
    try:
        v = int(value) if value is not None else default
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class OpenAIAgentBuilder:
    """Tool loop over an OpenAI-compatible function-calling model."""

    name = "openai_agent"

    def __init__(
        self,
        *,
        model: str,
        provider: str = "",
        model_fn: ModelFn | None = None,
        endpoint: EndpointConfig | None = None,
        executor: Executor | None = None,
        runner_factory: Callable[[RepoConfig], BaseRunner] = get_runner,
        keep_transcript: bool = False,
    ) -> None:
        self.model = model
        self.endpoint = endpoint
        self.provider = provider or (endpoint.provider if endpoint else "cerebras")
        self._model_fn = model_fn
        self.executor: Executor = executor or LocalExecutor()
        self.runner_factory = runner_factory
        self.keep_transcript = keep_transcript

    def describe(self) -> dict[str, Any]:
        """The apparatus stamp (the executor's posture included)."""
        return {
            "builder": self.name,
            "model": self.model,
            "provider": self.provider,
            "process": "in-process tool loop (read/search/edit/run)",
            "executor": self.executor.describe(),
        }

    def _model(self) -> ModelFn:
        """The model callable, built lazily so construction needs no credential."""
        if self._model_fn is not None:
            return self._model_fn
        chat = make_chat(self.model, self.endpoint)  # needs the openai extra + credential
        self._model_fn = chat
        return chat

    def build(
        self,
        workspace: Workspace,
        brief: BuildBrief,
        budget: Budget,
        *,
        on_event: EventFn | None = None,
    ) -> BuildOutcome:
        """The tool loop (module docstring). ``done`` is the model's green claim from
        ``run_target_tests`` and is untrusted; never raises for a model failure."""
        started = time.monotonic()
        config = brief.repo_config()
        guard = TestFileGuard(workspace.root, config, brief.test_files, mode=brief.mode)
        meter = CostMeter(price_for(self.model), model=self.model)
        tracker = BudgetTracker(budget, meter)
        # No runner in blind mode: the tool must not exist, not merely refuse.
        runner = self.runner_factory(config) if brief.sighted else None
        tools = _Tools(
            workspace,
            brief,
            guard,
            runner=runner,
            executor=self.executor,
            remaining_s=lambda: tracker.remaining_s,
        )
        schema = tool_schema(sighted=brief.sighted)
        transcript: list[dict[str, Any]] = []
        errors: list[str] = []
        last_text = ""

        def finish(*, done: bool, stop: str) -> BuildOutcome:
            tampered = guard.tampered(workspace)
            if tampered:
                errors.append("tamper: test files modified: " + ", ".join(tampered[:10]))
            errors.extend(tools.violations)
            summary = last_text.strip() or (
                "target tests reported green" if tools.target_green else ""
            )
            return BuildOutcome(
                builder=self.name,
                model=self.model,
                provider=self.provider,
                mode=brief.mode,
                done=done and not tampered,
                summary=summary,
                turns=tracker.turns,
                tool_calls=tracker.tool_calls,
                tokens_in=meter.tokens_in,
                tokens_out=meter.tokens_out,
                cost_usd=meter.cost_usd,
                cost_known=meter.cost_known,
                latency_s=time.monotonic() - started,
                stop_reason=stop,
                errors=tuple(errors),
                transcript=tuple(transcript),
                budget=budget,
                extra={
                    "refused": list(tools.refused)[:20],
                    "target_green_claim": tools.target_green,
                },
            )

        try:
            model_fn = self._model()
        except Exception as exc:
            errors.append(f"model_error: {type(exc).__name__}: {exc}")
            return finish(done=False, stop=STOP_MODEL_ERROR)

        method = SIGHTED_METHOD if brief.sighted else BLIND_METHOD
        task = (
            brief.task_text()
            + "\n\n"
            + method
            + f"\nBudget: at most {budget.max_tool_calls} tool calls."
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ]
        emit(on_event, "build.start", builder=self.name, model=self.model, mode=brief.mode)
        nudges = 0

        while True:
            reason = tracker.exceeded()
            if reason:
                return finish(done=tools.target_green, stop=reason)
            tracker.note_turn()
            try:
                turn: ModelTurn = model_fn(messages, schema)
            except Exception as exc:
                errors.append(f"model_error: {type(exc).__name__}: {exc}")
                return finish(done=tools.target_green, stop=STOP_MODEL_ERROR)
            meter.add(
                turn.tokens_in, turn.tokens_out, cached_in=turn.cached_in, cost_usd=turn.cost_usd
            )
            msg = turn.as_message()
            if not msg["content"] and not turn.tool_calls:
                msg["content"] = "(no tool call emitted)"
            messages.append(msg)
            if turn.content.strip():
                last_text = turn.content
            ev: dict[str, Any] = {
                "kind": "assistant",
                "turn": tracker.turns,
                "tool_calls": [tc.name for tc in turn.tool_calls],
                "tokens_in": turn.tokens_in,
                "tokens_out": turn.tokens_out,
            }
            if self.keep_transcript:
                ev["content"] = redact_and_cap(turn.content, max_chars=4000)
                ev["arguments"] = [
                    redact_and_cap(json.dumps(dict(tc.arguments)), max_chars=2000)
                    for tc in turn.tool_calls
                ]
            transcript.append(ev)
            emit(on_event, "build.turn", turn=tracker.turns, tool_calls=ev["tool_calls"])

            if not turn.tool_calls:
                has_changes = bool(guard.source_changes(workspace))
                if not has_changes and nudges < MAX_NUDGES:
                    nudges += 1
                    messages.append(
                        {
                            "role": "user",
                            "content": "Use a tool: search_repo, read_file, apply_edit or write_file. "
                            "Keep going until the change is implemented.",
                        }
                    )
                    continue
                return finish(
                    done=has_changes, stop=STOP_DONE if has_changes else STOP_NO_TOOL_CALL
                )

            stop_after = ""
            for tc in turn.tool_calls:
                cap = tracker.can_call_tool()
                if cap:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": "BUDGET: tool-call cap reached — stop and summarise.",
                        }
                    )
                    stop_after = cap
                    continue
                tracker.note_tool_call()
                result = tools.dispatch(tc)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": redact_and_cap(result, max_chars=TOOL_RESULT_CAP),
                    }
                )
                rev: dict[str, Any] = {
                    "kind": "tool",
                    "name": tc.name,
                    "ok": not result.startswith(("ERROR", "REFUSED")),
                }
                if self.keep_transcript:
                    rev["result"] = redact_and_cap(result, max_chars=2000)
                transcript.append(rev)
                emit(on_event, "build.tool", name=tc.name, ok=rev["ok"])
                if tc.name == "run_target_tests" and tools.target_green:
                    stop_after = STOP_DONE
            if stop_after == STOP_DONE:
                return finish(done=True, stop=STOP_DONE)
            if stop_after:
                return finish(done=tools.target_green, stop=stop_after)


__all__ = [
    "RUN_COMMAND_ALLOWLIST",
    "SYSTEM_PROMPT",
    "OpenAIAgentBuilder",
    "tool_schema",
]
