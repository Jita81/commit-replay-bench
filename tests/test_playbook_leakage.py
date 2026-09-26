"""No leakage, by construction — the playbook can carry operating facts and nothing else.

The loop's lines are the only text it adds to a brief. These tests try to get a task's words
into one: canaries planted in a gold diff, in target tests, in review statements, in row
errors and in linter messages; a line taught only by the task it is replayed into; a slot
value outside its vocabulary; a command the builder's own guard refuses. None may reach a
line or a brief (ADR-0020 §7).

Navigation
----------
What it is:   The playbook's leakage suite (ADR-0020 §7).
What it does: Pins that no canary reaches a line or a rendered brief; that a line reaches
              task T only when two OTHER tasks taught it; that the leak gate drops a line whose
              slot names a target-test stem; that a slot outside its vocabulary never appears;
              the caps (seven lines, 160 characters each, 1,000 in all); that every command a
              line recommends is in the honest guard corpus and passes the guard, and a refused
              one drops the line at injection; that ``playbook.py`` imports nothing that holds
              task text; and that no template serves budget, capability, review or factory
              classes.
How:          The fixture ledger, the loop's tick and snapshot, ``BuildBrief.task_text``, the
              guard ``GitArchaeologyGuard.check_shell``, and ``ast`` over playbook.py.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0020-a-bug-is-closed-by-prevention.md
Works with:   src/crb/core/playbook.py (under test), src/crb/core/prevention.py (the tick and
              the snapshot that carry the lines), src/crb/builders/base.py (the brief the lines
              are rendered in), tests/fixtures/shell_corpus.txt (the honest corpus)
Tested by:    tests/test_playbook_leakage.py
Touch when:   a template or a slot is added (plant a canary in its source here first).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from crb.builders.base import BuildBrief, GitArchaeologyGuard
from crb.core import playbook as playbook_mod
from crb.core.playbook import (
    MAX_CHARS,
    MAX_LINE_CHARS,
    MAX_LINES,
    NO_TEMPLATE,
    TEMPLATES,
    PlaybookLine,
    PlaybookSignal,
    RepoFacts,
    compile_playbook,
    held_out,
    leak_gate,
    render_line,
)
from crb.core.prevention import (
    AUTO_CONTEXT,
    LEVERS,
    MemoryPreventionStore,
    build_register,
    choose_lever,
    snapshot,
    tick,
)
from crb.core.review import Finding, ReviewRecord
from prevention_fixtures import REPO, at, attempt, ledger, lint_pack, switched, task

CANARY = re.compile(r"canary", re.I)
CORPUS = Path(__file__).parent / "fixtures" / "shell_corpus.txt"


def _canary_world() -> tuple[list, list, dict]:
    """Rows, reviews and packs carrying canaries everywhere a task's words live."""
    rows = []
    for i in range(30):
        kind = "clean"
        err = ""
        if i % 3 == 0:
            kind = "protocol"
            err = (
                "protocol violation: network: 'pip' is not allowed (attempted: pip install "
                f"canarypkg{i} ./CANARY_dir 'CANARY string')"
            )
        elif i % 3 == 1:
            kind = "lint"
        rows.append(attempt(i=i, task_id=task(i % 10), kind=kind, error=err))
    pack = lint_pack(
        [
            {
                "tool": "eslint",
                "verdict": False,
                "tail": "/w/lib/canary_module.js\n  3:7  error  'canaryVariable' is assigned a "
                "value but never used  no-unused-vars\n",
            }
        ]
    )
    # the evidence pack also holds the task and the graded diff: never read
    pack["task"] = {"subject": "CANARY subject", "test_files": ["canary_test.go"]}
    pack["grade"]["diff"] = "+++ b/canary.go\n+func CanaryGold() {}\n"
    rows = ledger(rows)
    reviews = [
        ReviewRecord(
            grade_row_hash=rows[2].row_hash,
            repo=REPO,
            task_id=rows[2].task_id,
            reviewer="rev",
            statement="CANARY review statement: the reviewer's own words",
            verdict="style",
            findings=(Finding("style", "CANARY finding note"),),
            mergeable=False,
            patch_sha256_reviewed="b" * 64,
        )
    ]
    return rows, reviews, {"c" * 64: pack}


def test_canaries_never_reach_a_line_or_a_brief() -> None:
    rows, reviews, packs = _canary_world()
    store = MemoryPreventionStore()
    store.append(switched(AUTO_CONTEXT, i=40))
    reg = build_register(rows, reviews, records=store.records(), repo=REPO, packs=packs.get)
    for e in reg.entries:
        assert not CANARY.search(e.signature), e.signature
    for r in tick(reg, store.records(), now=at(50)):
        store.append(r)
    applied = [r for r in store.records() if r.kind == "applied"]
    assert applied, "the scenario must apply at least one line"
    for r in applied:
        assert not CANARY.search(r.payload["what"]["text"])
    snap = snapshot(store.records(), repo=REPO)
    assert snap.lines
    texts, ids, _ = snap.lines_for(
        task(99),
        target_tests=["TestCanaryZeta"],
        test_files=["pkg/canary_zeta_test.go"],
        src_files=["pkg/canary.go"],
    )
    assert texts and ids
    brief = BuildBrief(
        subject="Fix the thing",
        message="Fix the thing",
        repo=REPO,
        language="go",
        mode="blind",
        playbook=tuple(texts),
    )
    rendered = brief.task_text()
    assert "Operating notes for this repository" in rendered
    assert not CANARY.search(rendered)
    assert not CANARY.search(str(brief.to_dict()))


def test_a_line_reaches_task_t_only_when_two_other_tasks_taught_it() -> None:
    line = PlaybookLine("l1", "T-API", "api:changed", "Keep exported names.", ("a" * 8, "b" * 8))
    kept, dropped = held_out([line], "a" * 8)
    assert kept == [] and dropped == ["l1"]  # only one OTHER task taught it
    kept, dropped = held_out([line], "c" * 8)
    assert kept == [line] and dropped == []
    solo = PlaybookLine("l2", "T-API", "api:changed", "Keep exported names.", ("a" * 8,))
    assert held_out([solo], "a" * 8) == ([], ["l2"])


def test_the_leak_gate_drops_a_line_naming_a_target_test_stem() -> None:
    line = render_line(
        PlaybookSignal(
            "T-LINT",
            "lint:eslint:no-foobar-quux",
            {"tool": "eslint", "rule": "no-foobar-quux"},
            ("x", "y", "z"),
        )
    )
    assert line is not None and "no-foobar-quux" in line.text
    kept, dropped = leak_gate([line], target_tests=["TestFoobarWidget"])
    assert kept == [] and dropped == [line.line_id]
    kept, dropped = leak_gate([line], src_files=["lib/quux.js"])
    assert kept == [] and dropped == [line.line_id]
    # a template's fixed words cannot come from a task and are not gated
    kept, _ = leak_gate([line], target_tests=["TestFilesChangeFinish"])
    assert kept == [line]


def test_a_slot_outside_the_vocabulary_renders_no_line() -> None:
    cases = [
        PlaybookSignal("T-NET", "protocol:network:go canaryx", {"head": "go canaryx"}),
        PlaybookSignal("T-ARCH", "protocol:archaeology:canary", {"head": "canary"}),
        PlaybookSignal("T-FMT", "format:canaryfmt", {"tool": "canaryfmt"}),
        PlaybookSignal("T-LINT", "lint:eslint:$(canary)", {"tool": "eslint", "rule": "$(canary)"}),
        PlaybookSignal("T-LINT", "lint:canarylint:x", {"tool": "canarylint", "rule": "x"}),
    ]
    for sg in cases:
        line = render_line(
            sg, RepoFacts(lint_cmd="eslint . ; curl canary.test", format_cmd="canary`x`")
        )
        assert line is not None and not CANARY.search(line.text), line
        assert line.commands == ()
    # an unknown template, or a class no template may serve, renders nothing at all
    assert render_line(PlaybookSignal("T-CANARY", "api:changed")) is None
    assert render_line(PlaybookSignal("T-NET", "budget:max_turns", {"head": "curl"})) is None


def test_caps_hold_seven_lines_160_characters_1000_in_all() -> None:
    signals = [
        PlaybookSignal(
            "T-LINT",
            f"lint:eslint:rule-{i}",
            {"tool": "eslint", "rule": f"rule-{i}"},
            spend=float(i),
        )
        for i in range(12)
    ]
    signals.append(PlaybookSignal("T-LINT", "lint:eslint:rule-3", {"tool": "eslint", "rule": "x"}))
    pb = compile_playbook(signals, RepoFacts(lint_cmd="npx eslint lib/request.js"))
    assert len(pb.lines) == MAX_LINES == 7
    assert all(len(ln.text) <= MAX_LINE_CHARS == 160 for ln in pb.lines)
    assert pb.chars == sum(len(ln.text) for ln in pb.lines) <= MAX_CHARS == 1000
    assert len({ln.signature for ln in pb.lines}) == len(pb.lines)  # one per class
    assert pb.lines[0].signature == "lint:eslint:rule-11"  # the costliest first
    for tpl in TEMPLATES.values():
        for text in tpl.values():
            assert len(re.sub(r"\{[a-z_]+\}", "", text)) <= MAX_LINE_CHARS


def _corpus() -> set[str]:
    return {
        ln.strip()
        for ln in CORPUS.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")
    }


def test_every_recommended_command_is_in_the_honest_corpus() -> None:
    corpus = _corpus()
    guard = GitArchaeologyGuard()
    facts = RepoFacts(lint_cmd="ruff check src tests", format_cmd="gofmt -l .")
    lines = [
        render_line(
            PlaybookSignal("T-LINT", "lint:ruff:e501", {"tool": "ruff", "rule": "e501"}), facts
        ),
        render_line(PlaybookSignal("T-FMT", "format:gofmt", {"tool": "gofmt"}), facts),
    ]
    recommended = [c for ln in lines if ln for c in ln.commands]
    assert recommended == ["ruff check src tests", "gofmt -l ."]
    for cmd in recommended:
        assert cmd in corpus, f"{cmd!r} is not in the honest corpus"
        assert guard.check_shell(cmd) == "", cmd
    # a command the builder's own guard refuses drops the line at injection
    from crb.core.prevention import LearningSnapshot

    refused = render_line(
        PlaybookSignal(
            "T-LINT", "lint:ruff:e501", {"tool": "ruff", "rule": "e501"}, ("a", "b", "c")
        ),
        RepoFacts(lint_cmd="git log -p"),
    )
    assert refused is not None and refused.commands == ("git log -p",)
    snap = LearningSnapshot(repo=REPO, auto_apply=AUTO_CONTEXT, lines=(refused,))
    texts, ids, dropped = snap.lines_for(task(1), refuses=lambda c: guard.check_shell(c))
    assert texts == [] and ids == [] and dropped == [refused.line_id]


def test_playbook_imports_nothing_that_holds_task_text() -> None:
    tree = ast.parse(Path(playbook_mod.__file__).read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            found.add(node.module or "")
    assert found == {"__future__", "dataclasses", "hashlib", "re", "collections.abc", "typing"}


def test_no_template_exists_for_budget_capability_review_or_factory() -> None:
    assert set(NO_TEMPLATE) == {
        "budget:*",
        "builder_red:target_red",
        "review:defect",
        "review:regression",
        "factory:*",
    }
    for sig in (
        "budget:max_turns",
        "builder_red:target_red",
        "review:defect",
        "review:regression",
        "factory:pr_closed",
    ):
        for tid in TEMPLATES:
            assert (
                render_line(
                    PlaybookSignal(tid, sig, {"head": "curl", "tool": "ruff", "rule": "E1"})
                )
                is None
            )
        assert not any(lv.family == "context" and lv.admits_sig(sig) for lv in LEVERS)
        assert choose_lever(sig, switch=AUTO_CONTEXT).family != "context"


#: ruff 0.15 ``check --no-fix`` output, full and concise, around a builder's code that holds
#: a rule-shaped identifier (``CNRY1234``) in the message, the source snippet and the fix
#: diff. Only ``F401`` and ``E501`` are rules (docs/PREVENTION.md P-018).
RUFF_TAIL_WITH_CODE = (
    "F401 [*] `.fmt.CNRY1234` imported but unused\n"
    " --> pkg/m.py:1:19\n"
    "  |\n"
    "1 | from .fmt import CNRY1234\n"
    "  |                  ^^^^^^^^\n"
    "2 | CNRY5678 = 1\n"
    "  |\n"
    "help: Remove unused import: `.fmt.CNRY1234`\n"
    "  |\n"
    "  - from .fmt import CNRY1234\n"
    "\n"
    "pkg/m.py:2:89: E501 Line too long (CNRY4321 is 129 > 88)\n"
    "Found 2 errors.\n"
    "[*] 1 fixable with the `--fix` option.\n"
)
CNRY = re.compile(r"cnry", re.I)


def test_a_rule_shaped_word_in_a_builders_code_never_becomes_a_rule_or_a_line() -> None:
    rows = [
        attempt(i=i, task_id=task(i % 10), kind="lint" if i % 3 == 1 else "clean")
        for i in range(30)
    ]
    rows = ledger(rows)
    pack = lint_pack([{"tool": "ruff", "verdict": False, "tail": RUFF_TAIL_WITH_CODE}])
    store = MemoryPreventionStore()
    store.append(switched(AUTO_CONTEXT, i=40))
    reg = build_register(rows, [], records=store.records(), repo=REPO, packs={"c" * 64: pack}.get)
    sigs = [e.signature for e in reg.entries]
    assert "lint:ruff:f401" in sigs and "lint:ruff:e501" in sigs
    assert not any(CNRY.search(s) for s in sigs), sigs
    for r in tick(reg, store.records(), now=at(50)):
        store.append(r)
    applied = [r for r in store.records() if r.kind == "applied"]
    assert applied, "the scenario must apply at least one line"
    assert not any(CNRY.search(str(r.payload)) for r in applied)
    texts, _ids, _ = snapshot(store.records(), repo=REPO).lines_for(task(99))
    brief = BuildBrief(
        subject="Fix it",
        message="Fix it",
        repo=REPO,
        language="python",
        mode="blind",
        playbook=tuple(texts),
    )
    assert not CNRY.search(brief.task_text())
