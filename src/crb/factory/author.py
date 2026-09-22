"""The test author — the oracle for an item nobody wrote a test for.

Forward mode has no held-out test. Today an item without an operator-authored
oracle stops ``no_oracle`` and waits for a person. This module is the other half:
a *test author* that writes one failing test for the item, in the repository's own
test conventions, so the governed loop can go on to prove it RED and build against
it.

The invariant, stated once
--------------------------
**The author rung and the build rung are never the same rung.** A test author is
configured in the same spelling as a build rung — ``builder:model[:provider]`` —
because the refusal that keeps an author out of its own build compares *rung
labels* (``assert_distinct_identity`` in :mod:`crb.factory.testfirst`). That is
the refusal the loop already has: :class:`~crb.factory.loop.FactorySpec` applies
it to every rung on the ladder the moment a spec is constructed, so a deployment
that names the same rung on both sides fails before a penny is spent. Nothing new
is invented here; this module only makes the author side configurable so the
refusal has something to compare.

What the refusal deliberately does NOT catch: the *same model* under a different
registered builder name (``editblock:m`` authoring, ``openai_agent:m`` building).
That is a different process, and the label space is closed to the registered
builder names (:func:`crb.builders.builder_names`), so no label can be invented to
dodge the check — but an operator who wants model-level separation must choose
different models. The belts remain the authority either way: the authored test is
proven RED at the base before it is trusted, staged as a throwaway commit, and
belt 1 re-checks every test byte after the build.

The process
-----------
One shot, bounded re-asks, over any OpenAI-compatible chat endpoint (the same
transport the edit-block builder uses). The author is shown the item, the
readiness facts, the repository's test layout and one or two of the repository's
own tests as style examples; it replies with a single ``FILE:`` header and one
fenced block. A reply that cannot be parsed, or that names a path the repository
does not classify as a test, is re-asked with the reason — never silently
accepted. The author's own claim is never a verdict: :func:`crb.factory.testfirst.prove_red`
runs it and requires RED with attributable failing ids.

Navigation
----------
What it is:   The configurable test-author rung — a ``TestAuthor`` that writes one failing
              test for an item nobody authored an oracle for, named in the same
              ``builder:model[:provider]`` spelling as a build rung.
What it does: Turns a rung label into a test author whose identity the loop's existing
              refusal compares against every build rung (the author rung and the build rung
              are never the same rung); asks one OpenAI-compatible model for a single test
              file in the repository's own conventions, re-asking on a reply it cannot parse
              or a path the repository does not call a test, and refuses to return anything
              else.
How:          ``author_for_rung`` (validates the builder name against the registry) →
              ``RungTestAuthor.author`` = read the repo's test examples → ``build_messages``
              → one chat call → ``parse_authored`` → path check → ``AuthoredTest``; the
              caller (``crb.factory.testfirst.author_test``) runs this in a disposable
              worktree and ``prove_red`` is the only thing that trusts the result.
Layer:        factory — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md,
              docs/adr/0001-four-belts-and-false-q1-at-write.md
Works with:   src/crb/factory/testfirst.py (the ``TestAuthor`` protocol, ``author_test``'s
              disposable worktree and the ``assert_distinct_identity`` refusal this module
              relies on), src/crb/factory/loop.py (``FactorySpec.test_author`` — where the
              refusal fires, and ``_oracle``, which stops ``no_oracle`` without one),
              src/crb/builders/openai_client.py (the chat transport and its credential
              rule), src/crb/builders/adapter.py (``parse_rung_label`` — the same spelling a
              ladder rung uses), src/crb/builders/__init__.py (``builder_names`` — the closed
              label space), src/crb/server/worker.py (the served deployment's setting and
              per-run override)
Tested by:    tests/test_factory_author.py, tests/test_worker_test_author.py
Touch when:   another authoring process is added (a second ``TestAuthor`` and a way to name
              it); the reply format changes (``parse_authored`` and its test move together);
              never for a new repository — the test layout comes from the repo config.
Claims:       An authored test is never trusted on the author's say-so; it is proven RED at
              the base and re-checked by belt 1 (docs/EVIDENCE-AND-CLAIMS.md). [measured]
              claims about author quality belong to the ledger, not to this module.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from crb.builders import builder_names
from crb.builders.adapter import parse_rung_label
from crb.builders.base import Rung, emit
from crb.builders.openai_client import ChatFn, ChatReply, EndpointConfig, make_chat
from crb.core.spec import RepoConfig
from crb.core.workspace import Workspace
from crb.factory.backlog import BacklogItem
from crb.factory.testfirst import AuthoredTest, EventFn

#: The word that switches the author OFF where a label is expected (a deployment default an
#: operator wants no author for, a run that must not pay for one).
NO_AUTHOR = "none"

#: How many times the author may be re-asked after a reply that could not be used.
DEFAULT_ATTEMPTS = 2

#: How much of one example test the author is shown (characters).
DEFAULT_EXAMPLE_CHARS = 6000


class AuthoringRefused(ValueError):
    """The author produced nothing usable within its attempts — no oracle, fail closed."""


SYSTEM_PROMPT = """You write ONE failing test. You do not write source code.

Reply with exactly one file, in this shape and nothing else:

FILE: <repository-relative path of the test file>
```
<the whole file>
```

Rules:
- The test must FAIL on the repository as it stands today, because the behaviour it
  describes does not exist yet. A test that passes today is refused.
- Test the behaviour the item asks for, from the outside, through the names the item
  gives. Do not invent private helpers and do not import anything that does not exist
  except the thing the item asks to be built.
- Follow the conventions of the example tests you are shown: same framework, same
  import style, same naming.
- The file must be a test file of this repository (see the layout below). Never edit or
  reference another test file.
- No prose, no explanation, no second file."""

_FILE_RE = re.compile(r"^\s*(?:#{1,6}\s*)?FILE:\s*`?([^`\s]+)`?\s*$", re.M)
_FENCE_RE = re.compile(r"^\s*```[^\n]*\n(.*?)^\s*```", re.M | re.S)


def parse_authored(text: str) -> tuple[str, str]:
    """``(path, content)`` from the author's reply, or ``("", "")`` when it has neither.

    Tolerant in exactly the two ways models are sloppy: a markdown heading before the
    ``FILE:`` line, and a language tag on the fence. Everything else is the caller's
    problem — an unusable reply is re-asked, never guessed at.
    """
    body = text.replace("\r\n", "\n")
    m = _FILE_RE.search(body)
    path = m.group(1).strip() if m else ""
    after = body[m.end() :] if m else body
    fence = _FENCE_RE.search(after)
    if fence is not None:
        return path, fence.group(1)
    # an unfenced reply: everything after the FILE: line, when there is one
    return (path, after.strip("\n") + "\n") if m and after.strip() else (path, "")


def example_tests(
    ws: Workspace, config: RepoConfig, *, item: BacklogItem, limit: int = 2
) -> list[str]:
    """Up to ``limit`` of the repository's own test files, as style examples.

    Ranked by name overlap with the item's title so the example is near the change;
    deterministic, and never the item's own (nothing of the item exists yet).
    """
    try:
        tracked = ws.repo.run("ls-files", cwd=ws.root).lines
    except Exception:
        return []
    tests = [f for f in tracked if config.is_test(f)]
    want = {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", item.title)}
    scored = sorted(
        ((-len(want & set(re.findall(r"[a-z0-9]+", f.lower()))), f) for f in tests),
    )
    return [f for _, f in scored[:limit]]


def layout_note(config: RepoConfig) -> str:
    """One plain sentence telling the author where this repository keeps its tests."""
    where = config.test_prefix or "(the repository root)"
    if config.test_mode == "suffix":
        return (
            f"Tests of {config.name} are files ending {config.test_suffix!r} under "
            f"{where!r}; the test runner is {config.runner}."
        )
    return (
        f"Tests of {config.name} live under {where!r} and end {config.ext!r}; "
        f"the test runner is {config.runner}."
    )


def build_messages(
    item: BacklogItem,
    config: RepoConfig,
    *,
    facts: Mapping[str, str],
    examples: Mapping[str, str],
    retry_reason: str = "",
) -> list[dict[str, Any]]:
    """The chat messages: the item, its facts, the test layout, the style examples, and —
    on a re-ask — exactly why the previous reply could not be used."""
    parts = [
        f"Item {item.id} ({item.kind}, {item.capability_class}, size {item.size_estimate})",
        f"Title: {item.title}",
    ]
    if item.description:
        parts.append(f"What and why:\n{item.description}")
    if item.acceptance_criteria:
        crit = "\n".join(f"- {c}" for c in item.acceptance_criteria)
        parts.append(f"Acceptance criteria:\n{crit}")
    if facts:
        known = "\n".join(f"- {k}: {v}" for k, v in facts.items())
        parts.append(f"Facts the product owner has stated:\n{known}")
    parts.append(layout_note(config))
    for path, text in examples.items():
        parts.append(
            f"\nAn existing test of this repository, for style only:\n--- {path} ---\n{text}"
        )
    if retry_reason:
        parts.append(f"\nYOUR PREVIOUS REPLY COULD NOT BE USED: {retry_reason}\nReply again.")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


class RungTestAuthor:
    """A :class:`~crb.factory.testfirst.TestAuthor` on an OpenAI-compatible endpoint.

    Its ``name`` is the *builder* half of the rung it was configured as, so
    :func:`crb.factory.testfirst.author_label` produces exactly a rung label and the
    loop's existing refusal can compare it with every rung on the ladder.
    """

    def __init__(
        self,
        *,
        name: str,
        model: str,
        provider: str = "",
        chat_fn: ChatFn | None = None,
        endpoint: EndpointConfig | None = None,
        attempts: int = DEFAULT_ATTEMPTS,
        max_examples: int = 2,
        max_example_chars: int = DEFAULT_EXAMPLE_CHARS,
    ) -> None:
        if not name.strip() or not model.strip():
            raise ValueError("a test author needs a builder name and a model id")
        if attempts < 1:
            raise ValueError("a test author needs at least one attempt")
        self.name = name.strip()
        self.model = model.strip()
        self.endpoint = endpoint
        self.provider = provider or (endpoint.provider if endpoint else "cerebras")
        self._chat_fn = chat_fn
        self.attempts = attempts
        self.max_examples = max_examples
        self.max_example_chars = max_example_chars

    def describe(self) -> dict[str, Any]:
        """The apparatus stamp. ``process`` says what this actually runs — the one-shot
        test-first prompt — while ``builder`` names the identity the refusal compares."""
        return {
            "builder": self.name,
            "model": self.model,
            "provider": self.provider,
            "process": "one-shot test-first authoring, re-asked on an unusable reply",
            "attempts": self.attempts,
        }

    def _chat(self) -> ChatFn:
        """The chat callable, built lazily so construction needs no credential."""
        if self._chat_fn is not None:
            return self._chat_fn
        chat = make_chat(self.model, self.endpoint)  # needs the openai extra + credential
        self._chat_fn = chat.text
        return self._chat_fn

    def _examples(
        self, workspace: Workspace, item: BacklogItem, config: RepoConfig
    ) -> dict[str, str]:
        """The repository's own tests, read for style; unreadable ones are simply absent."""
        out: dict[str, str] = {}
        for path in example_tests(workspace, config, item=item, limit=self.max_examples):
            try:
                out[path] = workspace.read(path)[: self.max_example_chars]
            except OSError:
                continue
        return out

    def author(
        self,
        workspace: Workspace,
        item: BacklogItem,
        *,
        facts: Mapping[str, str],
        config: RepoConfig,
        on_event: EventFn | None = None,
    ) -> AuthoredTest:
        """One failing test for ``item``, or :class:`AuthoringRefused`.

        The reply is checked before it is returned: it must name a path this repository
        classifies as a test and carry a non-empty body. Anything else is re-asked with
        the reason, up to ``attempts`` times, and then refused — an author that cannot be
        used produces no oracle, and the loop stops the item rather than build blind.
        """
        chat = self._chat()
        examples = self._examples(workspace, item, config)
        reason = ""
        for attempt in range(1, self.attempts + 1):
            messages = build_messages(
                item, config, facts=facts, examples=examples, retry_reason=reason
            )
            reply = chat(messages)
            text = reply.text if isinstance(reply, ChatReply) else str(reply)
            path, content = parse_authored(text)
            reason = self._unusable(path, content, config)
            emit(
                on_event,
                "author.attempt",
                item=item.id,
                attempt=attempt,
                path=path,
                reason=reason,
            )
            if not reason:
                return AuthoredTest(path, content, f"{self.name}:{self.model}")
        raise AuthoringRefused(
            f"{self.name}:{self.model} produced no usable test for {item.id} in "
            f"{self.attempts} attempt(s): {reason}"
        )

    @staticmethod
    def _unusable(path: str, content: str, config: RepoConfig) -> str:
        """Why the reply cannot be used, or ``""`` when it can."""
        if not path:
            return "no `FILE: <path>` line — reply with the FILE line then one fenced block"
        if not content.strip():
            return f"the block for {path!r} was empty"
        if path.startswith(("/", "..")) or ".." in path.split("/"):
            return f"{path!r} is not a repository-relative path"
        if not config.is_test(path):
            return (
                f"{path!r} is not a test path of this repository — the oracle must live "
                "where the repository keeps its tests"
            )
        return ""


def author_for_rung(rung: Rung, **overrides: Any) -> RungTestAuthor:
    """A rung → a test author whose label is that rung's label.

    The builder half must be a **registered** builder name: the label space the refusal
    compares is closed, so an author rung cannot be spelled to dodge a ladder rung it is
    identical to.
    """
    names = builder_names()
    if rung.builder not in names:
        raise ValueError(
            f"unknown test-author rung {rung.label!r}: {rung.builder!r} is not a builder "
            f"name; expected one of {names}"
        )
    return RungTestAuthor(name=rung.builder, model=rung.model, provider=rung.provider, **overrides)


def author_from_label(
    label: str, *, default_provider: str = "", **overrides: Any
) -> RungTestAuthor | None:
    """``builder:model[:provider]`` → a test author; ``""`` or ``none`` → ``None``.

    This is the one place a deployment setting or a run parameter becomes an author, so
    the two spellings that mean "no author" are decided once.
    """
    raw = (label or "").strip()
    if not raw or raw.lower() == NO_AUTHOR:
        return None
    return author_for_rung(parse_rung_label(raw, default_provider=default_provider), **overrides)


__all__ = [
    "DEFAULT_ATTEMPTS",
    "DEFAULT_EXAMPLE_CHARS",
    "NO_AUTHOR",
    "SYSTEM_PROMPT",
    "AuthoringRefused",
    "RungTestAuthor",
    "author_for_rung",
    "author_from_label",
    "build_messages",
    "example_tests",
    "layout_note",
    "parse_authored",
]
