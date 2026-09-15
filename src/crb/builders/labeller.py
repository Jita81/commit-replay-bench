"""LLM intent labellers — :class:`~crb.core.classify.Labeller` over the builder clients.

A labeller is shown a commit's **subject, message, changed paths and per-path line
counts** together with the closed class vocabulary (with one-line definitions)
and asked for one ``{class, confidence, rationale}`` JSON object. It is **never**
shown the diff body: the label must not leak the implementation into a task the
same model family may later be asked to reproduce. The prompt is rendered by the
core (:func:`~crb.core.classify.render_label_prompt`) from a
:class:`~crb.core.classify.LabelEvidence` whose digest is stamped on the label,
so "what the labeller saw" is auditable byte for byte.

Two transports, no new SDK code:

* :class:`OpenAILabeller` — any OpenAI-compatible chat endpoint through
  :class:`~crb.builders.openai_client.OpenAIChat` (Cerebras, Azure OpenAI …); the
  same client, credentials-from-environment and retry policy as ``openai_agent``.
* :class:`ClaudeCodeLabeller` — ``claude -p`` with **all tools disabled**
  (``--tools ""``), up to three turns, structured output, run from an empty temporary
  directory (never the repository). Auth mirrors :mod:`crb.builders.claude_code`
  exactly — ``api_key`` (``--bare``, ``ANTHROPIC_API_KEY`` required) or ``cli``
  (the operator's own login; developer / evaluation only) — by reusing its
  :meth:`~crb.builders.claude_code.ClaudeCodeBuilder.env` and constants.

Both are total: a transport error, an auth failure, a timeout or a malformed reply
yields an ``unclassified`` label with confidence 0 and the reason in its rationale
(so the path class stands and the run continues), never an exception.

Navigation
----------
What it is:   The two LLM intent labellers (``OpenAILabeller``, ``ClaudeCodeLabeller``) that
              implement the core's ``Labeller`` protocol, and ``make_labeller``, which picks
              one from a run's builder/model/provider triple.
What it does: Asks a model for one ``{class, confidence, rationale}`` over the commit's
              subject, message, paths and line counts — never the diff — and stamps the
              evidence digest on the label; meters tokens and cost per run; turns every
              failure into an ``unclassified`` label with the reason, never an exception.
How:          ``LabelEvidence`` → ``render_label_prompt`` (core) → one chat call / one
              tool-less ``claude -p`` with a JSON schema → ``parse_label_reply`` (core) →
              ``IntentLabel``; ``_Usage`` accumulates through ``CostMeter``.
Layer:        builders — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/core/classify.py (the protocol, the prompt, the parser and
              ``resolve()`` — human > intent > path), src/crb/core/taxonomy.py (the closed
              vocabulary the prompt carries), src/crb/builders/openai_client.py (the chat
              transport), src/crb/builders/claude_code.py (the CLI's auth/env, reused
              verbatim), src/crb/builders/budget.py (metering), src/crb/server/worker.py
              (the ``label`` run kind)
Tested by:    tests/test_builders_labeller.py, tests/test_worker_label.py
Touch when:   never for a new repository (a label run is started per repo from the UI or
              ``crb tasks label`` — docs/OPERATOR.md); a new class in the vocabulary is a
              change to src/crb/core/taxonomy.py, not here; a new transport implements
              ``label()`` with the same total-failure contract and joins ``make_labeller``.
Claims:       An intent label is a model's reading of metadata; the class a row carries is
              the resolved one, and a human label always wins (docs/EVIDENCE-AND-CLAIMS.md).
"""

from __future__ import annotations

import json
import tempfile
import time
import warnings
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from crb.builders.budget import CostMeter, price_for
from crb.builders.claude_code import (
    API_KEY_ENV,
    AUTH_API_KEY,
    AUTH_CLI,
    AUTH_MODES,
    CLI_SETTING_SOURCES,
    KNOWN_MODELS,
    ClaudeCodeBuilder,
    SpawnFn,
    default_auth,
    default_model,
    subprocess_spawn,
)
from crb.builders.openai_client import (
    ChatFn,
    ChatReply,
    EndpointConfig,
    MissingCredential,
    make_chat,
)
from crb.core.classify import (
    IntentLabel,
    LabelEvidence,
    PathStat,
    parse_label_reply,
    render_label_prompt,
    unclassified_label,
)
from crb.core.redact import redact_and_cap

#: What the model is told it is. Deliberately short: the instrument is the prompt
#: the core renders, and it already carries the vocabulary and the answer contract.
SYSTEM_PROMPT = (
    "You classify git commits by the KIND of change they make. You are given only the "
    "commit's subject, message, changed paths and line counts — never the code. Answer "
    "with exactly one JSON object as instructed; no prose, no markdown fences."
)

#: Structured-output schema for ``claude -p --json-schema``.
LABEL_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "class": {"type": "string", "description": "a vocabulary member or 'unclassified'"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": {"type": "string"},
    },
    "required": ["class", "confidence", "rationale"],
}

DEFAULT_MAX_TOKENS = 400
DEFAULT_TIMEOUT_S = 120

#: Builders whose model client the labeller can reuse; ``editblock`` shares the
#: OpenAI-compatible client with ``openai_agent``.
OPENAI_BUILDERS: frozenset[str] = frozenset({"openai_agent", "editblock"})
CLAUDE_BUILDERS: frozenset[str] = frozenset({"claude_code"})


def _evidence(
    subject: str,
    message: str,
    diff_stats: Sequence[PathStat],
    changed_paths: Sequence[str],
    path_class: str,
) -> LabelEvidence:
    """The auditable "what the labeller saw" record (its digest goes on the label)."""
    return LabelEvidence(
        subject=subject,
        message=message,
        changed_paths=tuple(changed_paths),
        diff_stats=tuple(diff_stats),
        path_class=path_class,
    )


class _Usage:
    """Per-labeller running totals so a labelling run reports its cost with its n."""

    def __init__(self, model: str) -> None:
        self.meter = CostMeter(price_for(model), model=model)
        self.calls = 0
        self.errors = 0
        self.last: dict[str, Any] = {}

    def add(
        self,
        *,
        tokens_in: int,
        tokens_out: int,
        cached_in: int = 0,
        cost_usd: float | None,
        latency_s: float,
        error: str = "",
    ) -> None:
        """Record one labelling call (a failed one counts, with zero tokens)."""
        self.calls += 1
        if error:
            self.errors += 1
        self.meter.add(tokens_in, tokens_out, cached_in=cached_in, cost_usd=cost_usd)
        self.last = {
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
            "latency_s": round(latency_s, 3),
            "error": error,
        }

    def to_dict(self) -> dict[str, Any]:
        """The run's ``counts_json`` usage block: calls, errors, tokens, cost with its flag."""
        return {
            "calls": self.calls,
            "errors": self.errors,
            "tokens_in": self.meter.tokens_in,
            "tokens_out": self.meter.tokens_out,
            "cost_usd": self.meter.cost_usd,
            "cost_known": self.meter.cost_known,
        }


# ---------------------------------------------------------------------------
# OpenAI-compatible
# ---------------------------------------------------------------------------


class OpenAILabeller:
    """Label through an OpenAI-compatible chat endpoint (Cerebras by default).

    ``chat_fn`` is the test seam (``messages -> str | ChatReply``); without it the
    live client is built lazily on first use from ``endpoint`` (default:
    :meth:`EndpointConfig.from_env`), so constructing a labeller never needs a
    credential — the first ``label()`` does, and a missing key is recorded on the
    label as ``model_error``, never raised.
    """

    builder = "openai_agent"

    def __init__(
        self,
        *,
        model: str,
        provider: str = "",
        endpoint: EndpointConfig | None = None,
        chat_fn: ChatFn | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float | None = 0.0,
    ) -> None:
        if not model.strip():
            raise ValueError("an OpenAI-compatible labeller needs a model")
        self.model = model.strip()
        self.endpoint = endpoint
        self.provider = provider or (endpoint.provider if endpoint else "cerebras")
        self._chat_fn = chat_fn
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.usage = _Usage(self.model)

    @property
    def name(self) -> str:
        """``builder:model@provider`` — the labeller id stamped on every label."""
        return f"{self.builder}:{self.model}@{self.provider}"

    def describe(self) -> dict[str, Any]:
        """The apparatus stamp for a label run."""
        return {
            "labeller": self.name,
            "builder": self.builder,
            "model": self.model,
            "provider": self.provider,
            "process": "one-shot chat, no tools, no diff body",
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

    def _chat(self) -> ChatFn:
        """The chat callable, built lazily so construction needs no credential."""
        if self._chat_fn is None:
            ep = self.endpoint or EndpointConfig.from_env()
            self._chat_fn = make_chat(
                self.model, ep, max_tokens=self.max_tokens, temperature=self.temperature
            ).text
        return self._chat_fn

    def label(
        self,
        *,
        subject: str,
        message: str,
        diff_stats: Sequence[PathStat],
        changed_paths: Sequence[str],
        path_class: str,
    ) -> IntentLabel:
        """One chat call → an ``IntentLabel``; any failure → ``unclassified`` with the reason."""
        ev = _evidence(subject, message, diff_stats, changed_paths, path_class)
        digest = ev.digest()
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": render_label_prompt(ev)},
        ]
        started = time.monotonic()
        try:
            reply = self._chat()(messages)
        except MissingCredential as exc:
            self.usage.add(
                tokens_in=0,
                tokens_out=0,
                cost_usd=None,
                latency_s=time.monotonic() - started,
                error="no credential",
            )
            return unclassified_label(self.name, reason=f"model_error: {exc}", evidence_hash=digest)
        except Exception as exc:
            err = f"model_error: {type(exc).__name__}: {redact_and_cap(str(exc), max_chars=300)}"
            self.usage.add(
                tokens_in=0,
                tokens_out=0,
                cost_usd=None,
                latency_s=time.monotonic() - started,
                error=err,
            )
            return unclassified_label(self.name, reason=err, evidence_hash=digest)
        if isinstance(reply, ChatReply):
            text = reply.text
            self.usage.add(
                tokens_in=reply.tokens_in,
                tokens_out=reply.tokens_out,
                cached_in=reply.cached_in,
                cost_usd=reply.cost_usd,
                latency_s=time.monotonic() - started,
            )
        else:
            text = str(reply)
            self.usage.add(
                tokens_in=0, tokens_out=0, cost_usd=None, latency_s=time.monotonic() - started
            )
        return parse_label_reply(text, labeller=self.name, evidence_hash=digest)


# ---------------------------------------------------------------------------
# Claude Code (claude -p, tools off)
# ---------------------------------------------------------------------------


class ClaudeCodeLabeller:
    """Label through ``claude -p`` with every tool disabled and one turn.

    ``model`` / ``auth`` resolve explicit value → worker environment
    (``CRB_CLAUDE_CODE_MODEL`` / ``CRB_CLAUDE_CODE_AUTH``) → defaults, exactly as
    :class:`~crb.builders.claude_code.ClaudeCodeBuilder` does; the child's
    environment is :meth:`ClaudeCodeBuilder.env` (nothing else leaks in). The CLI
    runs in an empty temporary directory so no repository ``CLAUDE.md`` can be
    discovered even outside ``--bare``. ``spawn`` is the transport seam.
    """

    builder = "claude_code"
    provider = "anthropic"

    def __init__(
        self,
        *,
        model: str = "",
        auth: str = "",
        claude_binary: str = "",
        spawn: SpawnFn | None = None,
        effort: str = "",
        bare: bool | None = None,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        extra_args: tuple[str, ...] | list[str] = (),
    ) -> None:
        model = model.strip() or default_model()
        auth = auth.strip() or default_auth()
        if model not in KNOWN_MODELS:
            warnings.warn(
                f"claude_code labeller: model {model!r} is not in the known id table; "
                "aliases move over time — prefer an exact id",
                stacklevel=2,
            )
        if auth not in AUTH_MODES:
            raise ValueError(
                f"claude_code labeller: auth must be one of {AUTH_MODES}, not {auth!r}"
            )
        if bare is None:
            bare = auth == AUTH_API_KEY
        if bare and auth == AUTH_CLI:
            raise ValueError("claude_code labeller: auth='cli' cannot combine with bare=True")
        self.model = model
        self.auth = auth
        self.bare = bare
        self.claude_binary = claude_binary
        self._spawn = spawn
        self.effort = effort
        self.timeout_s = int(timeout_s)
        self.extra_args = tuple(str(a) for a in extra_args)
        self.usage = _Usage(self.model)

    @property
    def name(self) -> str:
        """``claude_code:<model>`` — the labeller id stamped on every label."""
        return f"{self.builder}:{self.model}"

    def describe(self) -> dict[str, Any]:
        """The apparatus stamp for a label run (auth posture included)."""
        return {
            "labeller": self.name,
            "builder": self.builder,
            "model": self.model,
            "provider": self.provider,
            "process": "claude -p, tools disabled, 3 turns, json-schema output, no diff body",
            "auth": self.auth,
            "bare": self.bare,
            "effort": self.effort or "default",
        }

    def argv(self, prompt: str, *, binary: str = "claude") -> list[str]:
        """The full headless invocation (tests assert on this directly)."""
        args = [
            binary,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            "--model",
            self.model,
            "--max-turns",
            "3",  # structured output is delivered through an internal tool turn: at 1 the
            # CLI answers `error_max_turns` before the JSON lands (live label runs, 2026-09-14)
            "--tools",
            "",
            "--permission-mode",
            "dontAsk",
            "--system-prompt",
            SYSTEM_PROMPT,
            "--json-schema",
            json.dumps(LABEL_OUTPUT_SCHEMA, separators=(",", ":")),
            "--no-session-persistence",
            "--disable-slash-commands",
        ]
        if self.effort:
            args += ["--effort", self.effort]
        if self.bare:
            args.append("--bare")
        if self.auth == AUTH_CLI:
            args += ["--setting-sources", CLI_SETTING_SOURCES]
        args += list(self.extra_args)
        return args

    def _binary(self) -> str:
        """The configured binary, else ``claude`` on PATH; missing → a failed label."""
        if self.claude_binary:
            return self.claude_binary
        import shutil  # noqa: PLC0415 — keep the module import-light

        found = shutil.which("claude")
        if not found:
            raise FileNotFoundError("the 'claude' CLI was not found on PATH")
        return found

    def label(
        self,
        *,
        subject: str,
        message: str,
        diff_stats: Sequence[PathStat],
        changed_paths: Sequence[str],
        path_class: str,
    ) -> IntentLabel:
        """One tool-less ``claude -p`` in an empty temp dir → an ``IntentLabel``; any
        failure (no CLI, no credential, timeout, bad JSON) → ``unclassified``."""
        ev = _evidence(subject, message, diff_stats, changed_paths, path_class)
        digest = ev.digest()
        started = time.monotonic()

        def fail(reason: str) -> IntentLabel:
            self.usage.add(
                tokens_in=0,
                tokens_out=0,
                cost_usd=None,
                latency_s=time.monotonic() - started,
                error=reason,
            )
            return unclassified_label(self.name, reason=reason, evidence_hash=digest)

        try:
            binary = self._binary()
            env = ClaudeCodeBuilder.env(self.auth)
        except (FileNotFoundError, PermissionError) as exc:
            return fail(f"model_error: {exc}")
        argv = self.argv(render_label_prompt(ev), binary=binary)
        spawn = self._spawn or subprocess_spawn
        result: dict[str, Any] | None = None
        auth_status = 0
        try:
            with tempfile.TemporaryDirectory(prefix="crb-label-") as tmp:
                handle = spawn(argv, env, Path(tmp), self.timeout_s)
                for line in handle.lines():
                    ev_obj = _parse_line(line)
                    if ev_obj is None:
                        continue
                    kind = str(ev_obj.get("type", ""))
                    if kind == "system" and ev_obj.get("subtype") == "api_retry":
                        status = ev_obj.get("error_status")
                        if isinstance(status, int) and status in {401, 403}:
                            auth_status = status
                            handle.kill()
                            break
                    elif kind == "result":
                        result = ev_obj
                        # measured on claude 2.1.132: an invalid OAuth token yields ONE
                        # result event (is_error, api_error_status=401) and no api_retry
                        status = ev_obj.get("api_error_status")
                        if isinstance(status, int) and status in {401, 403}:
                            auth_status = status
                timed_out = bool(handle.timed_out)
                rc = handle.returncode
                stderr = handle.stderr_tail
        except Exception as exc:
            return fail(
                f"model_error: {type(exc).__name__}: {redact_and_cap(str(exc), max_chars=300)}"
            )
        if auth_status:
            hint = (
                "run `claude login` as the worker's user"
                if self.auth == AUTH_CLI
                else f"check {API_KEY_ENV}"
            )
            return fail(f"model_error: authentication failed (HTTP {auth_status}) — {hint}")
        if timed_out:
            return fail(f"wall_clock: killed after {self.timeout_s}s")
        if result is None:
            tail = redact_and_cap(stderr, max_chars=300)
            return fail(f"model_error: no result event (rc={rc}){': ' + tail if tail else ''}")
        tin, tout, cached = _usage_of(result)
        cost = result.get("total_cost_usd")
        self.usage.add(
            tokens_in=tin,
            tokens_out=tout,
            cached_in=cached,
            cost_usd=float(cost) if isinstance(cost, int | float) else None,
            latency_s=time.monotonic() - started,
        )
        if result.get("is_error"):
            return unclassified_label(
                self.name,
                reason="model_error: "
                + redact_and_cap(
                    f"{result.get('subtype', '')}: {result.get('result', '')}", max_chars=300
                ),
                evidence_hash=digest,
            )
        so = result.get("structured_output")
        text = json.dumps(so) if isinstance(so, dict) else str(result.get("result", "") or "")
        return parse_label_reply(text, labeller=self.name, evidence_hash=digest)


def _parse_line(line: str) -> dict[str, Any] | None:
    """One stream-json line as a dict, or ``None`` when blank or not an object."""
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _usage_of(result: Mapping[str, Any]) -> tuple[int, int, int]:
    """``(tokens_in, tokens_out, cached_in)`` from a result event, cache creation counted
    as input (the same reading as ``claude_code.StreamStats``)."""
    usage = result.get("usage")
    if not isinstance(usage, dict):
        return 0, 0, 0
    tin = int(usage.get("input_tokens", 0) or 0) + int(
        usage.get("cache_creation_input_tokens", 0) or 0
    )
    tout = int(usage.get("output_tokens", 0) or 0)
    cached = int(usage.get("cache_read_input_tokens", 0) or 0)
    return tin, tout, cached


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

#: What :func:`make_labeller` returns: a core :class:`Labeller` that also carries
#: ``usage`` (tokens / cost / errors with their n) and ``describe()``.
LLMLabeller = OpenAILabeller | ClaudeCodeLabeller
LabellerFactory = Callable[..., LLMLabeller]

_OPENAI_KWARGS: frozenset[str] = frozenset({"endpoint", "chat_fn", "max_tokens", "temperature"})
_CLAUDE_KWARGS: frozenset[str] = frozenset(
    {"auth", "claude_binary", "spawn", "effort", "bare", "timeout_s", "extra_args"}
)


def make_labeller(
    builder: str,
    *,
    model: str = "",
    provider: str = "",
    builder_config: Mapping[str, Any] | None = None,
) -> LLMLabeller:
    """A labeller for a run's ``builder`` / ``model`` / ``provider`` (the same triple
    a replay run names) plus the run's ``builder_config`` — of which only the keys
    a labeller understands are applied; builder-only keys (``executor``,
    ``keep_transcript`` …) are ignored rather than refused so one config serves
    both run kinds."""
    cfg = dict(builder_config or {})
    if builder in CLAUDE_BUILDERS:
        kw = {k: v for k, v in cfg.items() if k in _CLAUDE_KWARGS}
        return ClaudeCodeLabeller(model=model, **kw)
    if builder in OPENAI_BUILDERS:
        kw = {k: v for k, v in cfg.items() if k in _OPENAI_KWARGS}
        return OpenAILabeller(model=model, provider=provider, **kw)
    raise ValueError(
        f"no labeller for builder {builder!r}; expected one of "
        f"{sorted(CLAUDE_BUILDERS | OPENAI_BUILDERS)}"
    )


__all__ = [
    "CLAUDE_BUILDERS",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_TIMEOUT_S",
    "LABEL_OUTPUT_SCHEMA",
    "OPENAI_BUILDERS",
    "SYSTEM_PROMPT",
    "ClaudeCodeLabeller",
    "LLMLabeller",
    "OpenAILabeller",
    "make_labeller",
]
