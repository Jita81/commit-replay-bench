"""What a class is — ``crb.prevention.sig.v1`` pinned, family by family.

Navigation
----------
What it is:   The signature rule's test suite (ADR-0020 §2).
What it does: Pins that a protocol class is the guard and the command head and that no path,
              string, number or flag reaches the head; the budget stop reason (or
              ``unrecorded``); the ordered harness table against a pinned corpus of errors; a
              refusal before spend; belt 5's format and lint classes read from the pack's step
              tails (never a message's words); belt 6's kind only; the builder-red order; the
              standing review's classes; that an outage is never a class; and a golden fixture
              that fails when a family rule changes without bumping ``SIGNATURE_RULES``.
How:          Fixture rows from tests/prevention_fixtures.py; the corpus
              tests/fixtures/prevention/harness_errors.txt; the golden
              tests/fixtures/prevention/signatures_golden.json.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0020-a-bug-is-closed-by-prevention.md
Works with:   src/crb/core/prevention.py (under test), tests/prevention_fixtures.py (the rows),
              src/crb/core/lint.py (the tools the plan runs — the formatter list must be a
              subset), src/crb/core/review.py (the standing review)
Tested by:    tests/test_prevention_signatures.py
Touch when:   a family rule changes: bump ``SIGNATURE_RULES`` and regenerate the golden
              (``CRB_REGEN_GOLDEN=1``) in the same change.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from crb.core import lint as lint_mod
from crb.core.ledger import GradeRow
from crb.core.lint import LINT_TAIL_CHARS
from crb.core.prevention import (
    FORMATTER_TOOLS,
    SIGNATURE_RULES,
    api_signatures,
    blocked,
    command_head,
    harness_cause,
    lint_signatures,
    make_signature,
    primary_signature,
    review_signatures,
    rule_ids,
    signatures,
)
from crb.core.review import Finding, ReviewRecord
from prevention_fixtures import attempt, lint_pack, task

FIXTURES = Path(__file__).parent / "fixtures" / "prevention"
GOLDEN = FIXTURES / "signatures_golden.json"
CORPUS = FIXTURES / "harness_errors.txt"


def _proto(cmd: str, guard: str = "network") -> GradeRow:
    err = f"protocol violation: {guard}: '{cmd.split()[0]}' is not allowed (attempted: {cmd})"
    return attempt(i=0, task_id=task(1), kind="protocol", error=err)


def test_protocol_signature_is_guard_and_command_head() -> None:
    assert signatures(_proto("go mod tidy")) == ("protocol:network:go mod",)
    assert signatures(_proto("pip install -e .")) == ("protocol:network:pip install",)
    assert signatures(_proto("git log --oneline -5", "archaeology")) == (
        "protocol:archaeology:git log",
    )
    two = attempt(
        i=0,
        task_id=task(1),
        kind="protocol",
        error=(
            "protocol violation: network: 'curl' is not allowed (attempted: curl -sk "
            "https://x.test/a); archaeology: history is off limits (attempted: git show HEAD~1)"
        ),
    )
    assert signatures(two) == ("protocol:network:curl", "protocol:archaeology:git show")
    assert primary_signature(two) == "protocol:network:curl"


def test_command_head_carries_no_path_string_number_or_flag() -> None:
    cases = {
        "cd /work/repo && FOO=1 sudo timeout 30 go mod tidy": "go mod",
        "npx jest --runInBand src/thing.test.js": "npx jest",
        "python -m pytest tests/test_a.py::test_b -x": "python -m pytest",
        "curl -sk https://example.test/secret-path": "curl",
        'grep -rn "CANARY_STRING" src/ | head -30': "grep",
        "pip install ./local/pkg-1.2.3.tar.gz": "pip install",
        "timeout 60 npm install lodash@4.17.21": "npm install",
        "git log 1a2b3c4d5e6f7": "git log",
        "cd /tmp": "-",
        "./run.sh --all": "-",
        "": "-",
    }
    for cmd, want in cases.items():
        assert command_head(cmd) == want, cmd
    # nothing after the head: every head is at most three word tokens of the closed grammar
    for cmd in cases:
        head = command_head(cmd)
        assert head == "-" or all(re.fullmatch(r"-m|[a-z][a-z0-9._+-]*", t) for t in head.split())
        for bad in ("/", '"', "'", "<", "http", "CANARY", "1.2.3", "30", "60"):
            assert bad not in head, (cmd, head)


def test_budget_signature_is_the_stop_reason_or_unrecorded() -> None:
    wall = attempt(i=0, task_id=task(1), kind="budget", labels={"stop_reason": "wall_clock"})
    assert signatures(wall) == ("budget:wall_clock",)
    old = attempt(
        i=0,
        task_id=task(1),
        kind="budget",
        labels={"stop_reason": "", "failure_kind": "budget"},
    )
    assert signatures(old) == ("budget:unrecorded",)


def _corpus() -> list[tuple[str, str]]:
    out = []
    for line in CORPUS.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            want, _, err = line.partition("\t")
            out.append((want, err))
    return out


def test_harness_table_matches_the_pinned_error_corpus() -> None:
    corpus = _corpus()
    assert len(corpus) >= 15
    seen_causes = set()
    for want, err in corpus:
        cause, tool = harness_cause(err)
        got = f"{cause}:{tool}" if tool else cause
        assert got == want, (err, got)
        seen_causes.add(cause)
        row = attempt(i=0, task_id=task(1), kind="harness", error=err)
        assert signatures(row) == (make_signature("harness", cause, tool or None),)
    # every cause of the ADR's table is exercised by the corpus
    assert seen_causes == {
        "runner-tool-missing",
        "linter-unrunnable",
        "no-credential",
        "env-network",
        "sandbox",
        "timeout",
        "other",
    }


def test_runner_tool_missing_is_a_blocked_occurrence() -> None:
    row = attempt(i=0, task_id=task(1), kind="blocked")
    assert blocked(row) and row.cost_usd == 0.0
    assert signatures(row) == ("harness:runner-tool-missing:jest",)
    spent = attempt(i=0, task_id=task(1), kind="harness", error="sh: jest: not found")
    assert signatures(spent) == ("harness:runner-tool-missing:jest",) and not blocked(spent)


def test_format_and_lint_signatures_read_rule_ids_from_the_pack() -> None:
    fmt = lint_pack([{"tool": "gofmt", "verdict": False, "tail": "cmd/root.go\n"}])
    assert lint_signatures(fmt) == ("format:gofmt",)
    ruff = lint_pack(
        [
            {
                "tool": "ruff",
                "verdict": False,
                "tail": "src/a.py:1:1: E501 Line too long (CANARYVALUE is 120 > 88)\n"
                "src/a.py:3:5: F401 `os` imported but unused\n",
            },
            {"tool": "ruff-format", "verdict": False, "tail": "Would reformat: src/a.py"},
        ]
    )
    assert lint_signatures(ruff) == ("lint:ruff:e501", "lint:ruff:f401")
    eslint = lint_pack(
        [
            {
                "tool": "eslint",
                "verdict": False,
                "tail": "/w/lib/x.js\n  3:7  error  'CANARYVAR' is assigned a value but never used"
                "  no-unused-vars\n",
            }
        ]
    )
    assert lint_signatures(eslint) == ("lint:eslint:no-unused-vars",)
    unparsed = lint_pack([{"tool": "checkstyle", "verdict": False, "tail": "something odd"}])
    assert lint_signatures(unparsed) == ("lint:checkstyle:*",)
    assert lint_signatures(None) == ("lint:*",)
    row = attempt(i=0, task_id=task(1), kind="lint")
    assert signatures(row, pack=ruff) == ("lint:ruff:e501", "lint:ruff:f401")
    # the message's words never become a class
    assert all("canary" not in s for s in signatures(row, pack=ruff) + lint_signatures(eslint))


def test_each_parser_reads_a_rule_only_where_its_tool_prints_one() -> None:
    """A rule-shaped word in the builder's code (quoted in a snippet or a message) is never
    a rule: each parser is anchored to its tool's own output position (P-018)."""
    cases = {
        "ruff": (
            "F401 [*] `x.CNRY1234` imported but unused\n --> a.py:1:1\n  |\n"
            "1 | from x import CNRY1234\n  |\nCNRY9 note\n"
            "a.py:2:1: E501 Line too long (CNRY4321)\n",
            ["F401", "E501"],
        ),
        "tsc": (
            "src/a.ts(3,7): error TS2304: Cannot find name 'TS9999'.\n"
            "src/b.ts:4:2 - error TS2322: Type 'TS1111' is wrong.\n"
            "  const TS8888 = 1\n",
            ["TS2304", "TS2322"],
        ),
        "clippy": (
            "warning: unneeded `return`\n --> src/a.rs:3:5\n  |\n"
            "3 |     #[allow(clippy::canary_rule)] return x;\n  |\n"
            "  = note: `#[warn(clippy::needless_return)]` on by default\n",
            ["clippy::needless_return"],
        ),
        "checkstyle": (
            "[ERROR] /w/A.java:3:5: Name 'x' must match pattern [CanaryRule]. [MemberName]\n"
            "  code line ending in [CanaryTwo]\n",
            ["MemberName"],
        ),
        "standard": (
            "  /w/a.js:3:7: 'x' is assigned a value but never used. (no-unused-vars)\n"
            "  const y = f(canary-thing)\n",
            ["no-unused-vars"],
        ),
    }
    for tool, (tail, want) in cases.items():
        assert rule_ids(tool, tail) == want, tool
    # a tail capped tail-first may begin mid-line, inside a snippet: its first line is dropped
    capped = ("CNRY1234 rest of a cut line\n" + "a.py:1:1: E501 x\n") + "x" * LINT_TAIL_CHARS
    assert rule_ids("ruff", capped) == ["E501"]


def test_formatter_tools_are_tools_the_lint_plan_runs() -> None:
    source = Path(lint_mod.__file__).read_text(encoding="utf-8")
    for tool in FORMATTER_TOOLS:
        assert f'"{tool}"' in source, f"{tool} is not a tool crb.core.lint's plan names"


def test_api_signature_keeps_the_kind_only() -> None:
    labels = {
        "api_stable": "false",
        "api_findings": "changed:cmd:Command.CANARYSYMBOL;removed:pkg/x:OldFunc;changed:y:Z",
    }
    assert api_signatures(labels) == ("api:removed", "api:changed")
    assert api_signatures({"api_stable": "false"}) == ("api:*",)
    assert api_signatures({"api_stable": "true"}) == ()
    red = attempt(i=0, task_id=task(1), kind="target_red", labels=labels)
    assert signatures(red) == ("builder_red:target_red", "api:removed", "api:changed")
    assert all("canary" not in s and "cmd" not in s for s in signatures(red))


def test_builder_red_sub_follows_the_fixed_order() -> None:
    assert signatures(attempt(i=0, task_id=task(1), kind="target_red")) == (
        "builder_red:target_red",
    )
    assert signatures(attempt(i=0, task_id=task(1), kind="no_source_change")) == (
        "builder_red:no_source_change",
    )
    assert signatures(attempt(i=0, task_id=task(1), kind="regression")) == (
        "builder_red:regression",
    )
    assert signatures(attempt(i=0, task_id=task(1), kind="disqualified")) == (
        "disqualified:target_test_modified",
    )


def test_review_signatures_read_the_standing_review() -> None:
    rec = ReviewRecord(
        grade_row_hash="a" * 64,
        repo="fx",
        task_id=task(1),
        reviewer="rev-1",
        statement="CANARY statement words never reach a class",
        verdict="api_change",
        findings=(
            Finding("style", "gofmt would reformat CANARY"),
            Finding("api_change", "renamed CANARY"),
        ),
        mergeable=False,
        patch_sha256_reviewed="b" * 64,
    )
    assert review_signatures(rec) == ("review:api_change", "review:style")
    bare = ReviewRecord(
        grade_row_hash="a" * 64,
        repo="fx",
        task_id=task(1),
        reviewer="rev-1",
        statement="not mergeable",
        mergeable=False,
        patch_sha256_reviewed="b" * 64,
    )
    assert review_signatures(bare) == ("review:not_mergeable",)


def test_outage_is_never_a_class() -> None:
    assert signatures(attempt(i=0, task_id=task(1), kind="outage")) == ()
    assert signatures(attempt(i=0, task_id=task(1), kind="clean")) == ()
    assert primary_signature(attempt(i=0, task_id=task(1), kind="outage")) is None


def _golden_cases() -> dict[str, list[str]]:
    pack = lint_pack([{"tool": "ruff", "verdict": False, "tail": "a.py:1:1: E501 x\n"}])
    rows = {
        "protocol": attempt(i=0, task_id=task(1), kind="protocol"),
        "archaeology": attempt(i=0, task_id=task(1), kind="archaeology"),
        "budget": attempt(i=0, task_id=task(1), kind="budget"),
        "blocked": attempt(i=0, task_id=task(1), kind="blocked"),
        "harness": attempt(i=0, task_id=task(1), kind="harness"),
        "target_red": attempt(i=0, task_id=task(1), kind="target_red"),
        "no_source_change": attempt(i=0, task_id=task(1), kind="no_source_change"),
        "regression": attempt(i=0, task_id=task(1), kind="regression"),
        "disqualified": attempt(i=0, task_id=task(1), kind="disqualified"),
        "outage": attempt(i=0, task_id=task(1), kind="outage"),
        "clean": attempt(i=0, task_id=task(1), kind="clean"),
    }
    out = {name: list(signatures(r)) for name, r in rows.items()}
    out["lint_ruff"] = list(signatures(attempt(i=0, task_id=task(1), kind="lint"), pack=pack))
    for cmd in ("cd /x && go mod tidy", "python -m pytest -q", "npx jest", "git stash list"):
        out[f"head:{cmd}"] = [command_head(cmd)]
    for want, err in _corpus():
        out[f"harness:{err[:40]}"] = [want]
    return out


def test_signature_rules_golden_fixture() -> None:
    cases = _golden_cases()
    if os.environ.get("CRB_REGEN_GOLDEN") == "1":  # pragma: no cover - the regeneration path
        GOLDEN.write_text(
            json.dumps({"rules": SIGNATURE_RULES, "cases": cases}, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    changed = sorted(
        k for k in set(cases) | set(golden["cases"]) if cases.get(k) != golden["cases"].get(k)
    )
    if golden["rules"] == SIGNATURE_RULES:
        assert not changed, (
            f"the class rule changed ({changed[:5]}…) without bumping SIGNATURE_RULES "
            f"({SIGNATURE_RULES}): bump it, then regenerate with CRB_REGEN_GOLDEN=1"
        )
    else:
        pytest.fail(
            f"SIGNATURE_RULES is {SIGNATURE_RULES} but the golden was written under "
            f"{golden['rules']}: regenerate it with CRB_REGEN_GOLDEN=1 in the same change"
        )
