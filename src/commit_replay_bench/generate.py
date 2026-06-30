"""The model boundary.

``replay_commit`` calls a ``generate`` callable to get SEARCH/REPLACE edit
blocks. This module supplies the prompt + a pluggable **OpenAI-compatible**
adapter, so you can point the benchmark at any model that speaks
``/chat/completions``: OpenAI, Cerebras, Together, Fireworks, a local vLLM/TGI
server, or Ollama (``http://localhost:11434/v1``).

To use a model that is NOT OpenAI-compatible, write your own ``generate`` —
signature ``generate(*, subject, src_path, src, tests, prior_failure) ->
list[tuple[str, str]]`` (return value is parsed SEARCH/REPLACE blocks). See
:func:`commit_replay_bench.core.parse_edit_blocks`.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from .core import parse_edit_blocks

SYSTEM_PROMPT = (
    "You are an expert software engineer. Edit ONE file to make the failing tests "
    "pass, using SEARCH/REPLACE blocks in exactly this format:\n"
    "<<<<<<< SEARCH\n"
    "<exact lines copied verbatim from the file>\n"
    "=======\n"
    "<the replacement lines>\n"
    ">>>>>>> REPLACE\n"
    "Copy the SEARCH lines EXACTLY from the file shown (including indentation). "
    "Output ONLY SEARCH/REPLACE blocks — no prose, no fences."
)


def build_messages(
    *, subject: str, src_path: str, src: str, tests: str, prior_failure: str | None, src_cap: int = 48000
) -> list[dict]:
    """Build the chat messages for one regeneration attempt."""
    feedback = f"\n\nYour previous attempt failed:\n{prior_failure[:1800]}" if prior_failure else ""
    user = (
        f"TASK: {subject}\n\n"
        f"The following tests are currently FAILING and must pass:\n```\n{tests[:8000]}\n```\n\n"
        f"FILE TO EDIT — {src_path}:\n```\n{src[:src_cap]}\n```{feedback}\n\n"
        "Return SEARCH/REPLACE blocks:"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def openai_generate(
    *,
    model: str,
    base_url: str | None = None,
    api_key_env: str = "OPENAI_API_KEY",
    max_tokens: int = 8000,
    temperature: float = 0.0,
    fold_system_into_user: bool = False,
) -> Callable[..., list[tuple[str, str]]]:
    """Build a ``generate`` callable backed by any OpenAI-compatible endpoint.

    Args:
      model: the model id (e.g. ``gpt-4o-mini``, ``gpt-oss-120b``, ``llama3.1``).
      base_url: the API base, e.g. ``https://api.openai.com/v1`` (default),
        ``https://api.cerebras.ai/v1``, ``http://localhost:11434/v1`` (Ollama).
      api_key_env: env var holding the API key.
      fold_system_into_user: some providers reject a separate system role — set
        True to prepend the system prompt to the user message instead.

    Requires the ``openai`` package (``pip install commit-replay-bench[openai]``).
    """
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - import-time guard
        raise RuntimeError(
            "openai_generate needs the 'openai' package: pip install commit-replay-bench[openai]"
        ) from exc

    client = OpenAI(base_url=base_url, api_key=os.environ.get(api_key_env) or "missing-key")

    def _generate(*, subject: str, src_path: str, src: str, tests: str, prior_failure: str | None):
        messages = build_messages(
            subject=subject, src_path=src_path, src=src, tests=tests, prior_failure=prior_failure
        )
        if fold_system_into_user:
            sys_text = messages[0]["content"]
            messages = [{"role": "user", "content": sys_text + "\n\n" + messages[1]["content"]}]
        resp = client.chat.completions.create(
            model=model, messages=messages, max_tokens=max_tokens, temperature=temperature
        )
        return parse_edit_blocks(resp.choices[0].message.content or "")

    return _generate
