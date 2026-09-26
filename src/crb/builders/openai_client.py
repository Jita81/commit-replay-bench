"""Thin client for any OpenAI-compatible chat endpoint (Cerebras, Azure OpenAI, …).

This module is the *only* place the ``openai`` package is imported, and it is
imported lazily inside :func:`make_client` so ``crb.builders`` stays importable
without it. Everything the builders consume is expressed in the small,
provider-neutral types below (:class:`ChatReply`, :class:`ToolCall`,
:class:`ModelTurn`) so the loops are hermetic under test.

Credentials come from the environment variable named by ``api_key_env`` and are
never logged, never placed in an outcome, never passed through a prompt. A
missing key raises :class:`MissingCredential` up front — we do not let a build
start and fail half-way with a 401.

Retries: 429 and 5xx (and connection/timeout errors) back off exponentially with
jitter up to ``max_retries``; 4xx other than 429 are not retried.

Navigation
----------
What it is:   The one OpenAI-compatible transport — ``OpenAIChat`` over a lazily imported
              ``openai`` client — and the provider-neutral wire types (``ToolCall``,
              ``ModelTurn``, ``ChatReply``) the tool loop, the edit-block builder and the
              labeller consume.
What it does: Builds a client for Cerebras / Azure OpenAI / any base URL from an
              ``EndpointConfig``, refuses to start without the named credential, retries
              transient failures with jittered backoff, decodes tool calls tolerantly (bad
              JSON → ``parse_error``, not a crash) and meters every attempt.
How:          ``make_chat`` → ``make_client`` (imports ``openai`` here only) → ``OpenAIChat``:
              ``_create`` (kwargs + ``with_retries``) → ``__call__`` parses usage, content and
              tool calls into a ``ModelTurn``; ``text`` narrows it to a ``ChatReply``.
Layer:        builders — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/builders/openai_agent.py and src/crb/builders/editblock.py (the
              builders on this client), src/crb/builders/labeller.py (the labeller on it),
              src/crb/builders/budget.py (``CostMeter``/``price_for`` — the meter here is
              per client), src/crb/server/settings.py (the ``CRB_OPENAI_*``/``CRB_AZURE_*``
              variables ``EndpointConfig.from_env`` reads)
Tested by:    tests/test_builders_openai_agent.py, tests/test_builders_editblock.py,
              tests/test_builders_labeller.py
Touch when:   pointing the factory at another OpenAI-compatible provider — set
              ``CRB_OPENAI_BASE_URL`` / ``CRB_OPENAI_KEY_ENV`` (docs/OPERATOR.md), not the
              defaults here; a new retryable status joins ``RETRY_STATUSES``; a provider
              whose usage block differs changes ``_usage_of`` with a fake-response test.
"""

from __future__ import annotations

import json
import os
import random
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from crb.builders.budget import CostMeter, Pricing, price_for

CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"
CEREBRAS_KEY_ENV = "CEREBRAS_API_KEY"
AZURE_KEY_ENV = "AZURE_OPENAI_API_KEY"

RETRY_STATUSES: frozenset[int] = frozenset({408, 409, 429, 500, 502, 503, 504})


class MissingCredential(RuntimeError):
    """The named environment variable is not set. Fail closed before any call."""


class ModelCallError(RuntimeError):
    """The model endpoint failed after retries (status preserved, no secrets)."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# Provider-neutral wire types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolCall:
    """One function call the model asked for. ``arguments`` is already decoded;
    a malformed JSON payload decodes to ``{}`` with ``parse_error`` set so the loop
    can tell the model instead of crashing."""

    id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    parse_error: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "arguments", dict(self.arguments))

    def to_openai(self) -> dict[str, Any]:
        """The wire shape, re-encoded — needed to echo the call back in the history."""
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": json.dumps(dict(self.arguments))},
        }


@dataclass(frozen=True)
class ModelTurn:
    """One assistant turn: text and/or tool calls, plus what it cost."""

    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tokens_in: int = 0
    tokens_out: int = 0
    cached_in: int = 0
    cost_usd: float | None = None
    finish_reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))

    def as_message(self) -> dict[str, Any]:
        """The assistant message to append to an OpenAI-style history."""
        msg: dict[str, Any] = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            msg["tool_calls"] = [tc.to_openai() for tc in self.tool_calls]
        return msg


@dataclass(frozen=True)
class ChatReply:
    """A plain-text completion with usage (the edit-block builder's seam)."""

    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    cached_in: int = 0
    cost_usd: float | None = None


ChatFn = Callable[[list[dict[str, Any]]], "str | ChatReply"]
ModelFn = Callable[[list[dict[str, Any]], Sequence[Mapping[str, Any]] | None], ModelTurn]


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AzureConfig:
    """Azure OpenAI: the model is addressed by *deployment name*, not model id."""

    endpoint: str
    api_version: str
    deployment: str
    api_key_env: str = AZURE_KEY_ENV

    def __post_init__(self) -> None:
        if not self.endpoint.startswith("https://"):
            raise ValueError("azure endpoint must be an https:// URL")
        if not self.api_version or not self.deployment:
            raise ValueError("azure config needs api_version and deployment")

    def to_dict(self) -> dict[str, Any]:
        """The apparatus-stamp shape (the key's NAME, never its value)."""
        return {
            "endpoint": self.endpoint,
            "api_version": self.api_version,
            "deployment": self.deployment,
            "api_key_env": self.api_key_env,
        }


def _require_key(env_name: str) -> str:
    """The credential from the environment, or ``MissingCredential`` before any call."""
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise MissingCredential(
            f"{env_name} is not set — refusing to start a build that would fail with 401"
        )
    return key


def make_client(
    base_url: str = CEREBRAS_BASE_URL,
    api_key_env: str = CEREBRAS_KEY_ENV,
    azure: AzureConfig | None = None,
    *,
    timeout_s: float = 120.0,
) -> Any:
    """Return an ``openai.OpenAI`` (or ``openai.AzureOpenAI``) client.

    ``openai`` is imported here, lazily; install with ``pip install 'commit-replay-bench[openai]'``.
    SDK-level retries are disabled (``max_retries=0``) because :class:`OpenAIChat`
    owns the backoff and needs to meter every attempt.
    """
    key = _require_key(azure.api_key_env if azure is not None else api_key_env)
    try:
        import openai  # noqa: PLC0415 — lazy by design: the package must import without the extra
    except ImportError as e:  # pragma: no cover — exercised only without the extra
        raise RuntimeError(
            "the 'openai' package is required for OpenAI-compatible builders: "
            "pip install 'commit-replay-bench[openai]'"
        ) from e
    if azure is not None:
        return openai.AzureOpenAI(
            azure_endpoint=azure.endpoint,
            api_version=azure.api_version,
            api_key=key,
            timeout=timeout_s,
            max_retries=0,
        )
    return openai.OpenAI(base_url=base_url, api_key=key, timeout=timeout_s, max_retries=0)


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


def _status_of(exc: BaseException) -> int | None:
    """The HTTP status an SDK exception carries, wherever this SDK version puts it."""
    for attr in ("status_code", "status"):
        v = getattr(exc, attr, None)
        if isinstance(v, int):
            return v
    resp = getattr(exc, "response", None)
    v = getattr(resp, "status_code", None)
    return v if isinstance(v, int) else None


def _is_retryable(exc: BaseException) -> bool:
    """Rate limits, server errors and transport failures retry; other 4xx do not."""
    status = _status_of(exc)
    if status is not None:
        return status in RETRY_STATUSES
    name = type(exc).__name__
    return name in {"APITimeoutError", "APIConnectionError", "TimeoutError", "ConnectionError"}


def with_retries(
    fn: Callable[[], Any],
    *,
    max_retries: int = 4,
    base_delay_s: float = 1.0,
    max_delay_s: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
    on_retry: Callable[[int, BaseException], None] | None = None,
) -> Any:
    """Call ``fn`` with exponential backoff on retryable failures."""
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:
            if not _is_retryable(exc) or attempt >= max_retries:
                raise ModelCallError(
                    f"model call failed after {attempt + 1} attempt(s): {type(exc).__name__}: "
                    f"{str(exc)[:300]}",
                    status=_status_of(exc),
                ) from exc
            delay = min(max_delay_s, base_delay_s * (2**attempt)) * (0.5 + random.random())  # noqa: S311 — jitter, not crypto
            if on_retry is not None:
                on_retry(attempt + 1, exc)
            sleep(delay)
            attempt += 1


# ---------------------------------------------------------------------------
# Chat adapter
# ---------------------------------------------------------------------------


def _usage_of(resp: Any) -> tuple[int, int, int]:
    """``(prompt, completion, cached prompt)`` tokens from a response, zeros when absent."""
    u = getattr(resp, "usage", None)
    if u is None:
        return 0, 0, 0
    tin = int(getattr(u, "prompt_tokens", 0) or 0)
    tout = int(getattr(u, "completion_tokens", 0) or 0)
    cached = 0
    details = getattr(u, "prompt_tokens_details", None)
    if details is not None:
        cached = int(getattr(details, "cached_tokens", 0) or 0)
    return tin, tout, cached


def parse_tool_calls(raw_calls: Any) -> tuple[ToolCall, ...]:
    """Decode SDK tool-call objects (or dicts) into :class:`ToolCall` tuples."""
    out: list[ToolCall] = []
    for tc in raw_calls or ():
        if isinstance(tc, Mapping):
            fn = tc.get("function") or {}
            cid = str(tc.get("id", ""))
            name = str(fn.get("name", ""))
            raw_args = fn.get("arguments", "")
        else:
            fn = getattr(tc, "function", None)
            cid = str(getattr(tc, "id", ""))
            name = str(getattr(fn, "name", "") or "")
            raw_args = getattr(fn, "arguments", "") or ""
        args: dict[str, Any] = {}
        err = ""
        if isinstance(raw_args, Mapping):
            args = dict(raw_args)
        elif raw_args:
            try:
                decoded = json.loads(raw_args)
                if isinstance(decoded, dict):
                    args = decoded
                else:
                    err = "arguments must be a JSON object"
            except json.JSONDecodeError as e:
                err = f"arguments are not valid JSON: {e.msg}"
        out.append(
            ToolCall(id=cid or f"call_{len(out)}", name=name, arguments=args, parse_error=err)
        )
    return tuple(out)


class OpenAIChat:
    """A bound ``chat.completions`` caller that meters every attempt.

    Call it as ``chat(messages, tools=None)`` → :class:`ModelTurn`, or via
    :meth:`text` → :class:`ChatReply`. Works with any OpenAI-compatible client
    object exposing ``chat.completions.create``; tests pass a fake.
    """

    def __init__(
        self,
        client: Any,
        model: str,
        *,
        deployment: str = "",
        temperature: float | None = 0.2,
        max_tokens: int = 4000,
        timeout_s: float = 120.0,
        max_retries: int = 4,
        sleep: Callable[[float], None] = time.sleep,
        pricing: Pricing | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.deployment = deployment
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._sleep = sleep
        self.pricing = pricing if pricing is not None else price_for(model)
        self.extra = dict(extra or {})
        self.meter = CostMeter(self.pricing, model=model)

    def _create(
        self, messages: list[dict[str, Any]], tools: Sequence[Mapping[str, Any]] | None
    ) -> Any:
        """One ``chat.completions.create`` under the retry policy (``temperature`` is
        omitted when ``None`` — newer models reject the parameter)."""
        kwargs: dict[str, Any] = {
            "model": self.deployment or self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout_s,
        }
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if tools:
            kwargs["tools"] = list(tools)
            kwargs["tool_choice"] = "auto"
        kwargs.update(self.extra)
        return with_retries(
            lambda: self.client.chat.completions.create(**kwargs),
            max_retries=self.max_retries,
            sleep=self._sleep,
        )

    def __call__(
        self,
        messages: list[dict[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> ModelTurn:
        """The ``ModelFn``: one assistant turn with its tool calls and metered cost."""
        resp = self._create(messages, tools)
        tin, tout, cached = _usage_of(resp)
        choice = resp.choices[0] if getattr(resp, "choices", None) else None
        msg = getattr(choice, "message", None)
        content = str(getattr(msg, "content", "") or "")
        calls = parse_tool_calls(getattr(msg, "tool_calls", None))
        finish = str(getattr(choice, "finish_reason", "") or "")
        cost = self.pricing.cost(tin, tout, cached_in=cached) if self.pricing.known else None
        self.meter.add(tin, tout, cached_in=cached, cost_usd=cost)
        return ModelTurn(
            content=content,
            tool_calls=calls,
            tokens_in=tin,
            tokens_out=tout,
            cached_in=cached,
            cost_usd=cost,
            finish_reason=finish,
        )

    def text(self, messages: list[dict[str, Any]]) -> ChatReply:
        """The ``ChatFn``: a tool-less completion as text plus usage."""
        turn = self(messages, None)
        return ChatReply(
            text=turn.content,
            tokens_in=turn.tokens_in,
            tokens_out=turn.tokens_out,
            cached_in=turn.cached_in,
            cost_usd=turn.cost_usd,
        )

    def describe(self) -> dict[str, Any]:
        """The apparatus-stamp shape (no client, no key)."""
        return {
            "model": self.model,
            "deployment": self.deployment,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "pricing": self.pricing.to_dict(),
        }


@dataclass(frozen=True)
class EndpointConfig:
    """Where an OpenAI-compatible builder talks to. Defaults to Cerebras."""

    base_url: str = CEREBRAS_BASE_URL
    api_key_env: str = CEREBRAS_KEY_ENV
    azure: AzureConfig | None = None
    timeout_s: float = 120.0
    max_retries: int = 4
    temperature: float | None = 0.2
    max_tokens: int = 4000

    @property
    def provider(self) -> str:
        """``azure`` | ``cerebras`` | the base URL's host — the ledger's provider column."""
        if self.azure is not None:
            return "azure"
        host = self.base_url.split("//", 1)[-1].split("/", 1)[0]
        return "cerebras" if "cerebras" in host else host

    def to_dict(self) -> dict[str, Any]:
        """The apparatus-stamp shape (the key's NAME, never its value)."""
        return {
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "azure": self.azure.to_dict() if self.azure else None,
            "timeout_s": self.timeout_s,
            "max_retries": self.max_retries,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

    @classmethod
    def from_env(cls) -> EndpointConfig:
        """``CRB_OPENAI_BASE_URL`` / ``CRB_OPENAI_KEY_ENV`` (and the Azure trio) if set."""
        az = None
        ep = os.environ.get("CRB_AZURE_ENDPOINT", "")
        if ep:
            az = AzureConfig(
                endpoint=ep,
                api_version=os.environ.get("CRB_AZURE_API_VERSION", "2024-10-21"),
                deployment=os.environ.get("CRB_AZURE_DEPLOYMENT", ""),
                api_key_env=os.environ.get("CRB_AZURE_KEY_ENV", AZURE_KEY_ENV),
            )
        return cls(
            base_url=os.environ.get("CRB_OPENAI_BASE_URL", CEREBRAS_BASE_URL),
            api_key_env=os.environ.get("CRB_OPENAI_KEY_ENV", CEREBRAS_KEY_ENV),
            azure=az,
        )


def resolved_endpoint(endpoint: EndpointConfig | None = None) -> EndpointConfig:
    """The endpoint a builder with ``endpoint`` talks to — the one place it is decided, so
    the submit-time credential check, the build and the provider column agree. No explicit
    endpoint means the deployment's (:meth:`EndpointConfig.from_env` — Cerebras when
    nothing is set), never the Cerebras default regardless of the environment."""
    return endpoint or EndpointConfig.from_env()


def key_env(endpoint: EndpointConfig | None = None) -> str:
    """The NAME of the environment variable a build against ``endpoint`` needs."""
    ep = resolved_endpoint(endpoint)
    return ep.azure.api_key_env if ep.azure is not None else ep.api_key_env


def credential_missing(
    auth: str = "", *, secrets_dir: Any = None, endpoint: EndpointConfig | None = None
) -> str:
    """Why an OpenAI-compatible build (``openai_agent``, ``editblock``) would have no
    credential — ``""`` when its key variable is set. PRESENCE ONLY: the variable's name is
    returned, never its value. ``auth`` and ``secrets_dir`` are accepted for the shape
    ``POST /runs`` calls every check with (docs/PREVENTION.md P-003)."""
    del auth, secrets_dir
    try:
        name = key_env(endpoint)
    except ValueError as exc:  # the deployment's endpoint variables do not make an endpoint
        return (
            f"the OpenAI-compatible endpoint the worker would call is misconfigured: {exc} — "
            "fix CRB_OPENAI_BASE_URL / CRB_AZURE_ENDPOINT, CRB_AZURE_API_VERSION and "
            "CRB_AZURE_DEPLOYMENT before queuing the run"
        )
    if os.environ.get(name, "").strip():
        return ""
    return (
        f"an OpenAI-compatible builder needs {name} in the worker's environment and it is not "
        "set — set it (the provider's API key) before queuing the run"
    )


def make_chat(model: str, endpoint: EndpointConfig | None = None, **kw: Any) -> OpenAIChat:
    """Build a live :class:`OpenAIChat` for ``model`` against ``endpoint``."""
    ep = resolved_endpoint(endpoint)
    client = make_client(ep.base_url, ep.api_key_env, ep.azure, timeout_s=ep.timeout_s)
    pricing = price_for(f"azure:{model}" if ep.azure else model)
    # a caller's keyword (the labeller's max_tokens / temperature) overrides the endpoint's
    # default of the same name — passing both raised TypeError and every live
    # OpenAI-compatible label read `unclassified` (found by the header pass, 2026-09-15)
    settings: dict[str, Any] = {
        "deployment": ep.azure.deployment if ep.azure else "",
        "temperature": ep.temperature,
        "max_tokens": ep.max_tokens,
        "timeout_s": ep.timeout_s,
        "max_retries": ep.max_retries,
        "pricing": pricing,
        **kw,
    }
    return OpenAIChat(client, model, **settings)


__all__ = [
    "AZURE_KEY_ENV",
    "CEREBRAS_BASE_URL",
    "CEREBRAS_KEY_ENV",
    "RETRY_STATUSES",
    "AzureConfig",
    "ChatFn",
    "ChatReply",
    "EndpointConfig",
    "MissingCredential",
    "ModelCallError",
    "ModelFn",
    "ModelTurn",
    "OpenAIChat",
    "ToolCall",
    "credential_missing",
    "key_env",
    "make_chat",
    "make_client",
    "parse_tool_calls",
    "resolved_endpoint",
    "with_retries",
]
