"""The edit-block builder: tolerant parser, fuzzy apply, compile feedback, guards,
budget, and an end-to-end build the core grader marks clean."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

from crb.builders import base
from crb.builders import editblock as eb
from crb.builders.openai_client import ChatReply
from crb.core.execution import LocalExecutor
from crb.core.grade import grade
from crb.core.runners import get_runner

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
if str(_FIXTURES) not in sys.path:
    sys.path.insert(0, str(_FIXTURES))
from builders_repo import make_fixture  # noqa: E402

_CLEAN = """<<<<<<< SEARCH
    return n or ""
=======
    return n if n is not None else ""
>>>>>>> REPLACE"""


# --- parser (ported cases: the variants the model actually emits) ---------------


def test_parser_handles_clean_block() -> None:
    assert eb.parse_edit_blocks(_CLEAN) == [
        ('    return n or ""', '    return n if n is not None else ""')
    ]


def test_parser_tolerates_marker_variations() -> None:
    assert len(eb.parse_edit_blocks(_CLEAN.replace("=======", "======= "))) == 1  # trailing space
    assert len(eb.parse_edit_blocks(_CLEAN.replace("=======", "========"))) == 1  # 8 equals
    assert len(eb.parse_edit_blocks(_CLEAN.replace("\n", "\r\n"))) == 1  # CRLF
    assert len(eb.parse_edit_blocks("  " + _CLEAN)) == 1  # leading space
    assert eb.parse_edit_blocks("no markers here") == []


def test_parser_malformed_blocks_do_not_crash() -> None:
    # missing REPLACE marker: the block runs to EOF and is still captured (upstream semantics)
    assert eb.parse_edit_blocks("<<<<<<< SEARCH\nx\n=======\ny\n") == [("x", "y\n")]
    # missing divider: search runs to EOF, replace empty
    assert eb.parse_edit_blocks("<<<<<<< SEARCH\nx\n") == [("x\n", "")]
    # stray markers
    assert eb.parse_edit_blocks("=======\n>>>>>>> REPLACE\n") == []


def test_parser_file_headers_route_blocks() -> None:
    text = f"FILE: a.py\n{_CLEAN}\n### FILE: `b/c.py`\n{_CLEAN}\n"
    blocks = eb.parse_file_edit_blocks(text, default_path="d.py")
    assert [b[0] for b in blocks] == ["a.py", "b/c.py"]
    assert eb.parse_file_edit_blocks(_CLEAN, default_path="d.py")[0][0] == "d.py"


# --- apply ------------------------------------------------------------------------


def test_apply_exact_and_fuzzy() -> None:
    src = "def f(n):\n    return n or ''\n"
    new, applied = eb.apply_edit_blocks(
        src, [("    return n or ''", "    return n if n is not None else ''")]
    )
    assert applied == 1 and "is not None" in new
    # fuzzy: model got the indentation wrong but the content right → still applies
    new2, applied2 = eb.apply_edit_blocks(src, [("return n or ''", "    return 42")])
    assert applied2 == 1 and "return 42" in new2
    # fuzzy + consistently mis-indented replacement → re-indented to the matched line
    new3, applied3 = eb.apply_edit_blocks(src, [("return n or ''", "return 42\n# c")])
    assert applied3 == 1 and new3 == "def f(n):\n    return 42\n    # c\n"
    # exact matches never re-indent
    new4, _ = eb.apply_edit_blocks(src, [("    return n or ''", "pass")])
    assert new4 == "def f(n):\npass\n"
    # genuinely absent search → does not apply
    _, applied5 = eb.apply_edit_blocks(src, [("nonexistent line", "x")])
    assert applied5 == 0
    # empty search is skipped, multi-line window applies once
    _, applied6 = eb.apply_edit_blocks(src, [("", "x"), ("def f(n):\n    return n or ''", "pass")])
    assert applied6 == 1


def test_compile_check() -> None:
    assert eb.compile_check("a.py", "def f(:\n") == (False, "invalid syntax at line 1")
    assert eb.compile_check("a.py", "x = 1\n") == (True, "")
    assert eb.compile_check("a.go", "not python at all") == (True, "")


# --- file selection never uses the task's src_files ------------------------------


def test_candidate_files_by_subject_and_test_imports(tmp_path: Path) -> None:
    fx = make_fixture(tmp_path)
    ws = fx.workspace(tmp_path / "wt")
    files = eb.candidate_source_files(
        ws, fx.config, subject=fx.task.subject, test_files=fx.task.test_files, max_files=2
    )
    assert files[0] == "pkg/calc.py"  # imported by the target test + named in the subject
    blind = eb.candidate_source_files(ws, fx.config, subject="touch util shout", max_files=1)
    assert blind == ["pkg/util.py"]
    ws.remove()


# --- the builder -----------------------------------------------------------------


class ScriptedChat:
    """Returns canned replies in order; records the prompts it was sent."""

    def __init__(self, replies: list[Any]) -> None:
        self.replies = list(replies)
        self.prompts: list[list[dict[str, Any]]] = []

    def __call__(self, messages: list[dict[str, Any]]) -> Any:
        self.prompts.append(messages)
        if not self.replies:
            raise RuntimeError("scripted chat exhausted")
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


FIX_BLOCK = "FILE: pkg/calc.py\n<<<<<<< SEARCH\n    return a - b\n=======\n    return a + b\n>>>>>>> REPLACE\n"


def _build(tmp_path: Path, replies: list[Any], *, mode: str = "sighted", **kw: Any):
    fx = make_fixture(tmp_path)
    ws = fx.workspace(tmp_path / "wt", mode=mode)
    brief = base.BuildBrief.from_task(fx.task, mode=mode, config=fx.config)
    chat = ScriptedChat(replies)
    builder = eb.EditBlockBuilder(model="gpt-oss-120b", provider="cerebras", chat_fn=chat, **kw)
    budget = base.Budget(max_turns=3, max_tool_calls=1, wall_clock_s=60)
    outcome = builder.build(ws, brief, budget)
    return fx, ws, brief, chat, outcome


def test_build_applies_edit_and_core_grader_marks_clean(tmp_path: Path) -> None:
    fx, ws, _brief, chat, out = _build(
        tmp_path, [ChatReply(FIX_BLOCK, tokens_in=1000, tokens_out=50, cost_usd=None)]
    )
    assert out.done and out.stop_reason == base.STOP_DONE and out.attempts == 1 and out.errors == ()
    assert out.tokens_in == 1000 and out.cost_usd == pytest.approx(1000 * 0.25e-6 + 50 * 0.69e-6)
    assert "pkg/calc.py" in out.summary
    # the prompt showed the target test but never the task's src_files list
    user = chat.prompts[0][1]["content"]
    assert "tests/test_calc.py" in user and "def test_add" in user
    assert "src_files" not in user
    result = grade(
        ws,
        fx.task,
        config=fx.config,
        runner=get_runner(fx.config),
        executor=LocalExecutor(),
        mode="sighted",
    )
    assert result.clean, result.to_dict()
    ref = out.builder_ref()
    assert ref.model == "gpt-oss-120b" and ref.provider == "cerebras" and ref.turns == 1
    ws.remove()


def test_build_feeds_back_apply_failure_then_succeeds(tmp_path: Path) -> None:
    bad = "FILE: pkg/calc.py\n<<<<<<< SEARCH\n    return nothing like this\n=======\n    return a + b\n>>>>>>> REPLACE\n"
    _fx, ws, _brief, chat, out = _build(tmp_path, ["no blocks at all", bad, FIX_BLOCK])
    assert out.done and out.attempts == 3 and out.turns == 3
    assert "No SEARCH/REPLACE blocks" in chat.prompts[1][1]["content"]
    assert "did not apply" in chat.prompts[2][1]["content"]
    ws.remove()


def test_build_rejects_syntax_breaking_edit_and_never_writes_it(tmp_path: Path) -> None:
    broken = "FILE: pkg/calc.py\n<<<<<<< SEARCH\n    return a - b\n=======\n    return a +\n>>>>>>> REPLACE\n"
    _fx, ws, _brief, chat, out = _build(tmp_path, [broken, broken, broken])
    assert not out.done and out.stop_reason == base.STOP_MAX_TURNS and out.attempts == 3
    assert "INVALID PYTHON" in chat.prompts[1][1]["content"]
    assert ws.read("pkg/calc.py").count("return a - b") == 1  # untouched
    ws.remove()


@pytest.mark.parametrize("mode", ["sighted", "blind"])
def test_build_refuses_test_edits_in_both_modes(tmp_path: Path, mode: str) -> None:
    cheat = "FILE: tests/test_calc.py\n<<<<<<< SEARCH\n    assert add(2, 3) == 5\n=======\n    assert True\n>>>>>>> REPLACE\n"
    new_test = "FILE: tests/test_zzz.py\n<<<<<<< SEARCH\n=======\ndef test_z():\n    pass\n>>>>>>> REPLACE\n"
    _fx, ws, _brief, chat, out = _build(tmp_path, [cheat, new_test, "../../evil.py"], mode=mode)
    assert not out.done and out.stop_reason == base.STOP_MAX_TURNS
    assert "REFUSED" in chat.prompts[1][1]["content"]
    assert "REFUSED" in chat.prompts[2][1]["content"]
    assert not (ws.root / "tests" / "test_zzz.py").exists()
    if mode == "sighted":
        assert "assert add(2, 3) == 5" in ws.read("tests/test_calc.py")
    else:
        assert not ws.exists("tests/test_calc.py")  # held out: never materialised
    assert out.errors == ()  # refused ⇒ prevented, not a violation
    ws.remove()


def test_build_traversal_refused(tmp_path: Path) -> None:
    esc = "FILE: ../escape.py\n<<<<<<< SEARCH\n=======\nx = 1\n>>>>>>> REPLACE\n"
    _fx, ws, _brief, chat, out = _build(tmp_path, [esc, esc, esc])
    assert not out.done
    assert "escapes" in chat.prompts[1][1]["content"]
    assert not (tmp_path / "escape.py").exists()
    ws.remove()


def test_build_model_error_is_recorded_not_raised(tmp_path: Path) -> None:
    _fx, ws, _brief, _chat, out = _build(tmp_path, [RuntimeError("boom 429")])
    assert not out.done and out.stop_reason == base.STOP_MODEL_ERROR
    assert out.errors and out.errors[0].startswith("model_error:")
    ws.remove()


def test_build_cost_cap_stops_before_next_attempt(tmp_path: Path) -> None:
    fx = make_fixture(tmp_path)
    ws = fx.workspace(tmp_path / "wt")
    brief = base.BuildBrief.from_task(fx.task, config=fx.config)
    chat = ScriptedChat(["nope"] * 5)
    builder = eb.EditBlockBuilder(model="gpt-oss-120b", chat_fn=chat)
    out = builder.build(ws, brief, base.Budget(max_turns=5, max_cost_usd=0.000001))
    # tokens are unknown for a str reply so cost stays 0 → turns cap; with a priced reply it stops
    assert out.stop_reason == base.STOP_MAX_TURNS
    chat2 = ScriptedChat([ChatReply("nope", tokens_in=100_000, tokens_out=100_000)] * 5)
    out2 = builder.__class__(model="gpt-oss-120b", chat_fn=chat2).build(
        ws, brief, base.Budget(max_turns=5, max_cost_usd=0.01)
    )
    assert out2.stop_reason == base.STOP_MAX_COST and out2.attempts == 1
    ws.remove()


def test_transcript_opt_in_and_redacted(tmp_path: Path) -> None:
    leak = FIX_BLOCK + "\n# token=ghp_abcdefghijklmnopqrstuvwxyz0123456789\n"
    _fx, ws, _brief, _chat, out = _build(tmp_path, [leak], keep_transcript=True)
    assert out.transcript and "reply" in out.transcript[0]
    assert "ghp_" not in out.transcript[0]["reply"]
    _fx2, ws2, _brief2, _chat2, out2 = _build(tmp_path / "b", [FIX_BLOCK])
    assert "reply" not in out2.transcript[0]
    ws.remove()
    ws2.remove()


@pytest.mark.live
def test_live_cerebras_editblock(tmp_path: Path) -> None:
    if not os.environ.get("CEREBRAS_API_KEY"):
        pytest.skip("CEREBRAS_API_KEY not set")
    pytest.importorskip("openai")
    fx = make_fixture(tmp_path)
    ws = fx.workspace(tmp_path / "wt")
    brief = base.BuildBrief.from_task(fx.task, config=fx.config)
    builder = eb.EditBlockBuilder(model="gpt-oss-120b", provider="cerebras")
    out = builder.build(ws, brief, base.Budget(max_turns=2, max_cost_usd=0.05, wall_clock_s=120))
    assert out.tokens_in > 0 and out.cost_known
    if out.done:
        result = grade(
            ws, fx.task, config=fx.config, runner=get_runner(fx.config), executor=LocalExecutor()
        )
        assert result.belts.tests_unmodified is True
    ws.remove()
