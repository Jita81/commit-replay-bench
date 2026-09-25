"""crb.factory.author — the test author, and the invariant that it is never a build rung.

Navigation
----------
What it is:   The test-author rung's test suite — reply parsing, the re-ask on an unusable
              reply, the refusal when nothing usable arrives, the closed label space, and the
              invariant the loop enforces: the author rung and the build rung are never the
              same rung.
What it does: Pins that a reply without a ``FILE:`` line, with an empty block, with a path
              outside the repository or with a path the repository does not call a test is
              re-asked with the reason and never returned; that the author's identity is a
              rung label; that a rung whose builder is not registered is refused at
              construction; that ``FactorySpec`` refuses an author that is also on the
              ladder (the SAME refusal, ``SameIdentityError``, not a new one) — and, since
              C3 (2026-09-25), an author whose MODEL is on the ladder under another builder
              name, aliases normalised through the pricing table, the refusal naming the rung
              to change; and that the happy path returns an ``AuthoredTest`` the RED proof
              can then judge.
How:          A scripted ``chat_fn`` in place of the model (no network, no credential); the
              ``pyrepo`` fixture for the repository layout and its own tests as examples.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/factory/author.py (under test), src/crb/factory/testfirst.py
              (``assert_distinct_identity``, ``author_test``'s disposable worktree),
              src/crb/factory/loop.py (``FactorySpec`` — where the refusal fires),
              tests/test_worker_test_author.py (the served deployment's wiring)
Tested by:    tests/test_factory_author.py
Touch when:   the reply format changes; another authoring process is added; the identity rule
              changes (then docs/adr/0004-builder-registry-sighted-and-blind.md and the loop’s docstring move with it).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from crb.builders.base import Rung
from crb.core.execution import LocalExecutor
from crb.core.runners.pytest_runner import PytestRunner
from crb.factory import author as fa
from crb.factory.backlog import BacklogItem
from crb.factory.evidence import FactoryEvidence, JsonlFactoryStore
from crb.factory.loop import FactorySpec
from crb.factory.testfirst import SameIdentityError, author_label, author_test, worktree_at
from fixtures import pyrepo as pr

ITEM = BacklogItem(
    id="I-9",
    title="divide two numbers",
    kind="code",
    description="calc.divide(a, b) returns a / b and raises ZeroDivisionError for b == 0.",
    acceptance_criteria=("divide(6, 3) == 2",),
    capability_class="pure_function",
)

GOOD = """FILE: tests/test_divide.py
```python
from calc import divide


def test_divide() -> None:
    assert divide(6, 3) == 2
```
"""


def _chat(*replies: str) -> Any:
    """A scripted chat callable that records the messages it was handed."""
    sent: list[list[dict[str, Any]]] = []
    queue = list(replies)

    def chat(messages: list[dict[str, Any]]) -> str:
        sent.append(messages)
        return queue.pop(0) if queue else ""

    chat.sent = sent  # type: ignore[attr-defined]
    return chat


# --- parsing --------------------------------------------------------------------------


def test_parse_authored_reads_the_file_line_and_the_fenced_block() -> None:
    path, content = fa.parse_authored(GOOD)
    assert path == "tests/test_divide.py"
    assert content.startswith("from calc import divide") and content.endswith("== 2\n")
    # a markdown heading before the FILE line and a bare fence are both tolerated
    path, content = fa.parse_authored("### FILE: `tests/test_x.py`\n```\nx = 1\n```\n")
    assert (path, content) == ("tests/test_x.py", "x = 1\n")
    # prose with no file at all yields nothing — the caller re-asks, never guesses
    assert fa.parse_authored("I would write a test for divide.") == ("", "")


def test_layout_note_states_where_this_repository_keeps_its_tests(pyrepo: pr.PyRepo) -> None:
    note = fa.layout_note(pyrepo.config)
    assert "tests" in note and pyrepo.config.runner in note


def test_example_tests_are_the_repositorys_own_tests(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    ws = worktree_at(pyrepo.repo, "HEAD", tmp_path / "wt", config=pyrepo.config)
    try:
        examples = fa.example_tests(ws, pyrepo.config, item=ITEM, limit=2)
    finally:
        ws.remove()
    assert examples and all(pyrepo.config.is_test(f) for f in examples)


# --- the author -----------------------------------------------------------------------


def _author(pyrepo: pr.PyRepo, *replies: str, **kw: Any) -> fa.RungTestAuthor:
    return fa.RungTestAuthor(name="editblock", model="m1", chat_fn=_chat(*replies), **kw)


def test_the_happy_path_returns_an_authored_test_stamped_with_the_rung_label(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    author = _author(pyrepo, GOOD)
    res = author_test(
        pyrepo.repo,
        ITEM,
        author,
        facts={"signature": "divide(a, b)"},
        config=pyrepo.config,
        scratch=tmp_path / "scratch",
    )
    assert res.authored.path == "tests/test_divide.py"
    assert res.authored.author == "editblock:m1" == author_label(author)
    assert not res.authored.operator_authored
    # the item, its facts and the repository's own test conventions all reached the model
    text = author._chat_fn.sent[0][1]["content"]  # type: ignore[attr-defined,union-attr]
    assert "divide two numbers" in text and "signature: divide(a, b)" in text
    assert "for style only" in text
    # the authoring worktree is disposable and gone
    assert not any((tmp_path / "scratch").glob("author-*"))


def test_an_unusable_reply_is_re_asked_with_the_reason(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    author = _author(pyrepo, "I think a test would be nice.", GOOD)
    events: list[tuple[str, dict[str, Any]]] = []
    ws = worktree_at(pyrepo.repo, "HEAD", tmp_path / "wt", config=pyrepo.config)
    try:
        authored = author.author(
            ws,
            ITEM,
            facts={},
            config=pyrepo.config,
            on_event=lambda a, p: events.append((a, dict(p))),
        )
    finally:
        ws.remove()
    assert authored.path == "tests/test_divide.py"
    second = author._chat_fn.sent[1][1]["content"]  # type: ignore[attr-defined,union-attr]
    assert "COULD NOT BE USED" in second and "FILE:" in second
    assert [p["reason"] for _, p in events] == [
        "no `FILE: <path>` line — reply with the FILE line then one fenced block",
        "",
    ]


@pytest.mark.parametrize(
    ("reply", "why"),
    [
        ("FILE: tests/test_x.py\n```\n\n```\n", "was empty"),
        ("FILE: /etc/passwd\n```\nx = 1\n```\n", "repository-relative"),
        ("FILE: src/calc/__init__.py\n```\nx = 1\n```\n", "not a test path"),
    ],
)
def test_a_reply_that_is_not_a_test_of_this_repository_is_refused(
    pyrepo: pr.PyRepo, tmp_path: Path, reply: str, why: str
) -> None:
    author = _author(pyrepo, reply, reply, attempts=2)
    ws = worktree_at(pyrepo.repo, "HEAD", tmp_path / "wt", config=pyrepo.config)
    try:
        with pytest.raises(fa.AuthoringRefused, match=why):
            author.author(ws, ITEM, facts={}, config=pyrepo.config)
    finally:
        ws.remove()


def test_the_author_describes_its_apparatus_without_claiming_a_builder_process() -> None:
    d = fa.RungTestAuthor(name="editblock", model="m1", chat_fn=_chat()).describe()
    assert d["builder"] == "editblock" and d["model"] == "m1"
    assert "test-first authoring" in d["process"]


def test_a_test_author_needs_a_name_a_model_and_an_attempt() -> None:
    with pytest.raises(ValueError, match="builder name and a model id"):
        fa.RungTestAuthor(name=" ", model="m1")
    with pytest.raises(ValueError, match="at least one attempt"):
        fa.RungTestAuthor(name="editblock", model="m1", attempts=0)


# --- the label space and the invariant ------------------------------------------------


def test_the_author_label_space_is_the_registered_builder_names() -> None:
    a = fa.author_for_rung(Rung(builder="editblock", model="m1", provider="cerebras"))
    assert author_label(a) == "editblock:m1" and a.provider == "cerebras"
    with pytest.raises(ValueError, match="is not a builder name"):
        fa.author_for_rung(Rung(builder="not_a_builder", model="m1"))


def test_no_author_is_spelled_two_ways_and_decided_once() -> None:
    assert fa.author_from_label("") is None
    assert fa.author_from_label("  ") is None
    assert fa.author_from_label("NONE") is None
    a = fa.author_from_label("editblock:m1", default_provider="cerebras")
    assert a is not None and author_label(a) == "editblock:m1" and a.provider == "cerebras"


def _spec(pyrepo: pr.PyRepo, tmp_path: Path, *, author: Any, ladder: tuple[Rung, ...]) -> Any:
    """A ``FactorySpec`` with nothing but what the identity check reads."""
    return FactorySpec(
        config=pyrepo.config,
        runner=PytestRunner(pyrepo.config),
        executor=LocalExecutor(),
        scratch=tmp_path / "scratch",
        evidence_dir=tmp_path / "packs",
        evidence=FactoryEvidence(JsonlFactoryStore(tmp_path / "evidence.jsonl"), repo="pyrepo"),
        ladder=ladder,
        builder_for=lambda r: None,  # type: ignore[arg-type,return-value]
        test_author=author,
    )


def test_the_author_rung_and_the_build_rung_are_never_the_same_rung(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """The invariant, on the SAME refusal the loop already has (``SameIdentityError``).

    It fires at ``FactorySpec`` construction — before a readiness pass, before a model
    call, before a penny is spent.
    """
    author = fa.RungTestAuthor(name="editblock", model="m1", chat_fn=_chat(GOOD))
    with pytest.raises(SameIdentityError, match="authored the oracle"):
        _spec(pyrepo, tmp_path, author=author, ladder=(Rung("editblock", "m1"),))
    # the same identity anywhere on the ladder, not only its first rung
    with pytest.raises(SameIdentityError, match="authored the oracle"):
        _spec(
            pyrepo,
            tmp_path,
            author=author,
            ladder=(Rung("editblock", "m2"), Rung("editblock", "m1")),
        )
    # case and spacing cannot slip past it
    with pytest.raises(SameIdentityError, match="authored the oracle"):
        _spec(pyrepo, tmp_path, author=author, ladder=(Rung("EditBlock", "M1"),))
    # a different rung is accepted, and the author reaches the spec
    spec = _spec(pyrepo, tmp_path, author=author, ladder=(Rung("editblock", "m2"),))
    assert spec.test_author is author


# --- C3: the author and the builder are distinct MODELS, not distinct labels ---------


def _model_author(model: str, name: str = "editblock") -> Any:
    return fa.RungTestAuthor(name=name, model=model, chat_fn=_chat(GOOD))


def test_the_same_model_under_another_builder_name_is_refused(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """C3 (assessment 2026-09-25): the label check let ``editblock:claude-sonnet-5`` write the
    test that ``claude_code:claude-sonnet-5`` is graded against — one model's judgement on
    both sides, which is correlated judgement, not independent evidence. The refusal compares
    the MODEL half and names the rung to change."""
    with pytest.raises(SameIdentityError) as exc:
        _spec(
            pyrepo,
            tmp_path,
            author=_model_author("claude-sonnet-5"),
            ladder=(Rung("editblock", "gpt-oss-120b"), Rung("claude_code", "claude-sonnet-5")),
        )
    msg = str(exc.value)
    assert "rung 2" in msg and "claude_code:claude-sonnet-5" in msg
    assert "claude-sonnet-5" in msg and "model" in msg


@pytest.mark.parametrize(
    ("author_model", "rung_model"),
    [
        ("claude-sonnet-5", "claude-sonnet-5-20260901"),  # a dated id → the priced family
        ("claude-sonnet-5", "Claude-Sonnet-5"),  # case
        ("claude-opus-4-8", "claude-opus-4-8[1m]"),  # a context-window suffix
        ("gpt-oss-120b", "openai/gpt-oss-120b"),  # a vendor-prefixed id
        ("claude-sonnet-5", "sonnet"),  # Claude Code's family alias
    ],
)
def test_aliases_of_one_model_are_the_same_model(
    pyrepo: pr.PyRepo, tmp_path: Path, author_model: str, rung_model: str
) -> None:
    """Aliases are normalised through the pricing table (``crb.builders.budget``) — the
    one place the product already says which ids are one priced model — so a spelling cannot
    slip a model past the refusal; a bare family alias is read as the whole family (fail
    closed: ``sonnet`` could be any Sonnet)."""
    with pytest.raises(SameIdentityError, match="rung 1"):
        _spec(
            pyrepo,
            tmp_path,
            author=_model_author(author_model),
            ladder=(Rung("claude_code", rung_model),),
        )


def test_different_models_pass_whatever_the_builder_names(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    author = _model_author("gpt-oss-120b")
    spec = _spec(
        pyrepo,
        tmp_path,
        author=author,
        ladder=(Rung("claude_code", "claude-sonnet-5"), Rung("editblock", "zai-glm-4.7")),
    )
    assert spec.test_author is author
    # distinct versions of one family are distinct models
    spec = _spec(
        pyrepo,
        tmp_path,
        author=_model_author("claude-opus-5"),
        ladder=(Rung("claude_code", "claude-opus-4-8"),),
    )
    assert spec.test_author is not None
