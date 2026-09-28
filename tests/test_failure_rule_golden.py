"""The failure rule is pinned to the apparatus, and the 2.3 rule is frozen (ADR-0025 item 6).

A row's failure kind decides its denominator: ``outage`` leaves ``n``, ``harness`` counts
against autonomy, ``builder_red`` / ``lint`` / ``api`` against the model. Before this, a row
pinned ``harness`` was re-read as ``outage`` against ``OUTAGE_ERROR_MARKERS`` — a tuple anyone
could edit — so an edit to it moved stored rows between denominators (external assessment
2026-09-25, A6; P-301). Now:

* the rule as it stood at 2.3 and its outage markers are FROZEN
  (``derive_failure_kind_v1``, ``OUTAGE_ERROR_MARKERS_V1``) and read every row below 2.4;
* the live rule (``derive_failure_kind``) and its live markers hash to the value this file
  pins for the current ``APPARATUS_VERSION``: changing either fails here until the apparatus
  moves and a new line is added below. The line of an earlier version is never edited.

Navigation
----------
What it is:   The golden table of the failure rule, one hash per apparatus version, the
              pinned hash of the frozen 2.3 outage markers, and the pin of the outage-cause
              rule the 2.4 rows' ``outage_cause`` label is stamped by (pilot D1).
What it does: Fails when the live rule or its markers change under an unchanged
              ``APPARATUS_VERSION``; fails when the frozen v1 rule or markers change at all;
              shows the frozen reading of a row below 2.4 cannot move when the live markers do;
              and pins each rule's code as well as its answers, so an edit on a branch the grid
              never reaches fails too (P-306).
How:          Evaluates each rule over one grid of inputs that exercises every branch and every
              marker, hashes the canonical JSON of the outputs with the marker list, and compares
              with ``GOLDEN``; hashes each rule's tokens (docstring and comments dropped) with the
              constants it reads, and compares with ``GOLDEN_SOURCE`` / ``V1_SOURCE_SHA256``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         ADR-0025 item 6 (stream G; the draft stream R commits);
              docs/adr/0020-a-bug-is-closed-by-prevention.md
Works with:   src/crb/core/ledger.py (``derive_failure_kind``, ``derive_failure_kind_v1``,
              ``OUTAGE_ERROR_MARKERS_V1``, ``GradeRow.failure_kind``), src/crb/core/version.py
              (``APPARATUS_VERSION``, the key of the golden table), docs/PREVENTION.md (P-301,
              the row this test closes)
Tested by:    tests/test_failure_rule_golden.py
Touch when:   never for a new repository; the apparatus moves (add its lines to ``GOLDEN`` and
              ``GOLDEN_SOURCE``: the hashes the tests print) — or the rule changes, which is an
              apparatus bump (src/crb/core/version.py) first.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import io
import itertools
import json
import textwrap
import tokenize
from collections.abc import Callable, Iterable, Sequence
from typing import Any

import pytest

from crb.core import ledger as lg
from crb.core.version import APPARATUS_VERSION
from fixtures.posture import with_posture_labels

#: apparatus version → the hash of its failure rule over the grid, with its outage markers.
#: A version's line is written once, when that version ships, and never edited.
GOLDEN: dict[str, str] = {
    "2.3": "5f7e319ccde777ac118b0bac6b5e182b4356c419e7e6989679b7d9ec55fa473a",
    # 2.4 (ADR-0025): from here a row pins its own kind; the rule gained 3b, the S1 arm's
    # ``authoring`` kind and its author-outage exception (stream F), before 2.4 shipped — the
    # Wave 2 integration wrote this line on the grid that reads them (AUTHORING_ERRORS);
    # rewritten once, before 2.4 shipped and with no 2.4 row measured, when rule 3b took
    # rule 4b for the author's instrument failures (DL-360), and once more, still before 2.4
    # shipped, when rule 3b read the author's ``model_error`` only at the adapter's head
    # (P-735, DL-360 amended) — never edited after release
    "2.4": "08d22b5d006f77b4b60954876f6ebba145072e155379cffc83ae8548a326f661",
}
#: SHA-256 of the canonical JSON of ``OUTAGE_ERROR_MARKERS_V1`` (frozen at 2.3).
V1_MARKERS_SHA256 = "c4f586326e2950b861953ea2e49bb6e2d8c4e1acf7bd19ce9231cd544364713f"
#: apparatus version → the hash of the live rule's SOURCE (``_source_digest``): the grid
#: above pins what the rule answers on its inputs, this pins the rule itself, so an edit on a
#: branch the grid never reaches still fails (P-306). Written once per version, never edited.
GOLDEN_SOURCE: dict[str, str] = {
    "2.3": "f4931817defdcb051a19397bee4a2b32bc1ea73e8b59eb2216edc3063df21e96",
    # 2.4: rewritten with the line above (DL-360), which also pinned rule 3b's helpers, and
    # again with it for P-735 (``authoring_model_error``, ``AUTHORING_AUTHOR_FAILED``)
    "2.4": "4bc0aa97759143cb4159822ace028ba567a992d00f73cef58f728b7fed45ce60",
}
#: The hash of the frozen 2.3 rule's source (``derive_failure_kind_v1`` and what it calls).
V1_SOURCE_SHA256 = "1768a6844c74c9e2c789635b33388b72960c656e0f91d9f916d60efdae54d842"

RuleFn = Callable[..., str]


#: The ``S1`` arm's test-author errors (ADR-0026 item 1, stream F): rule 3b's two answers —
#: ``authoring`` against the arm, or ``outage`` when the author's own provider refused the
#: call. They joined the grid with 2.4, the rule that reads them; the 2.3 line keeps the grid
#: it was written on, so it is never edited.
AUTHORING_ERRORS: tuple[str, ...] = (
    "authoring: the author returned no test that fails on the parent",
    "authoring: model_error: provider said USAGE LIMIT REACHED",
    # rule 4b for the author (DL-360): a failed call that is no refusal, and the runner
    # raising while proving RED, are ``harness`` — the instrument failed, not the arm
    "authoring: the test author failed: model_error: InternalServerError: 500",
    "authoring: harness error proving RED: OSError: the sandbox went away",
    # the model's own words are never the instrument's (P-735): a miss whose test path — the
    # model chose it — says ``model_error``, even beside an outage marker, is ``authoring``
    "authoring: the authored test 'tests/test_model_error.py' is not RED at the parent: "
    "it passes at the parent",
    "authoring: the authored test 'tests/test_model_error_rate_limit.py' is not RED at the "
    "parent: it passes at the parent",
)


def test_rule_3b_reads_the_instrument_only_off_the_head_the_adapter_writes() -> None:
    """P-735: the answers the ``AUTHORING_ERRORS`` lines must give, spelt out, so the grid's
    hash is not the only thing that knows them."""
    want = {
        AUTHORING_ERRORS[0]: lg.FAILURE_AUTHORING,
        AUTHORING_ERRORS[1]: lg.FAILURE_OUTAGE,
        AUTHORING_ERRORS[2]: lg.FAILURE_HARNESS,
        AUTHORING_ERRORS[3]: lg.FAILURE_HARNESS,
        AUTHORING_ERRORS[4]: lg.FAILURE_AUTHORING,
        AUTHORING_ERRORS[5]: lg.FAILURE_AUTHORING,
        "authoring: the test author failed: model_error: RateLimitError: 429": lg.FAILURE_OUTAGE,
        "authoring: the test author failed: ImportError: no name 'Model_Error'": (
            lg.FAILURE_AUTHORING
        ),
        "authoring: the test author failed: ValueError: model_error: rate limit": (
            lg.FAILURE_AUTHORING
        ),
    }
    got = {e: lg.derive_failure_kind(clean=False, disqualified=False, error=e) for e in want}
    assert got == want


def _errors(markers: Sequence[str], *, authoring: bool = True) -> list[str]:
    return [
        "",
        "protocol violation: network",
        "model_error: some other trouble",
        "grader exception: 429 in a test log",
        "environment: gold control red",
        *(f"model_error: provider said {m.upper()}" for m in markers),
        *(AUTHORING_ERRORS if authoring else ()),
    ]


def _table(rule: RuleFn, markers: Sequence[str], *, authoring: bool = True) -> list[Any]:
    """The rule's output over the grid: every branch, every marker."""
    out: list[Any] = []
    grid = itertools.product(
        (True, False),  # clean
        (True, False),  # disqualified
        _errors(markers, authoring=authoring),
        ("", "protocol violation: archaeology"),  # builder_error
        ("", "max_turns", "wall_clock", "done"),  # stop_reason
        (True, False),  # lint_only
        (True, False),  # api_only
    )
    for clean, dq, error, berr, stop, lint, api in grid:
        kind = rule(
            clean=clean,
            disqualified=dq,
            error=error,
            builder_error=berr,
            stop_reason=stop,
            lint_only=lint,
            api_only=api,
        )
        out.append([clean, dq, error, berr, stop, lint, api, kind])
    return out


def _digest(rule: RuleFn, markers: Sequence[str], *, authoring: bool = True) -> str:
    body = {"markers": list(markers), "table": _table(rule, markers, authoring=authoring)}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def test_the_live_failure_rule_is_pinned_to_the_apparatus() -> None:
    """Changing ``derive_failure_kind`` or ``OUTAGE_ERROR_MARKERS`` fails here until the
    apparatus moves and its line is added to ``GOLDEN``."""
    got = _digest(lg.derive_failure_kind, lg.OUTAGE_ERROR_MARKERS)
    assert APPARATUS_VERSION in GOLDEN, (
        f"apparatus {APPARATUS_VERSION} has no line in GOLDEN: add {got!r} "
        "(and freeze the rule it replaces beside the v1 copy if it changed)"
    )
    assert got == GOLDEN[APPARATUS_VERSION], (
        f"the failure rule changed under apparatus {APPARATUS_VERSION} (now {got}); "
        "a change to the rule or its outage markers is an apparatus bump"
    )


def test_the_frozen_v1_rule_is_the_rule_as_it_stood_at_2_3() -> None:
    assert (
        _digest(lg.derive_failure_kind_v1, lg.OUTAGE_ERROR_MARKERS_V1, authoring=False)
        == GOLDEN["2.3"]
    )


def test_the_v1_outage_markers_are_frozen_by_their_hash() -> None:
    got = hashlib.sha256(json.dumps(list(lg.OUTAGE_ERROR_MARKERS_V1)).encode()).hexdigest()
    assert got == V1_MARKERS_SHA256


def _harness_row(apparatus: str, error: str) -> lg.GradeRow:
    base: dict[str, Any] = {
        "repo": "r",
        "task_id": "a" * 40,
        "clean": False,
        "tests_unmodified": True,
        "target_green": None,
        "no_new_failures": None,
        "source_changed": None,
        "error": error,
        "gold_clean": True,
        "evidence_pack_hash": "c" * 64,
        "apparatus_version": apparatus,
        "labels": {lg.LABEL_FAILURE_KIND: lg.FAILURE_HARNESS},
    }
    return lg.GradeRow(**with_posture_labels(base))


def test_a_row_below_2_4_is_read_by_the_frozen_markers_whatever_the_live_list_says(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An edit to the live marker list can no longer move a stored 2.3 row: it is re-read
    as ``outage`` against the frozen v1 list only."""
    row = _harness_row("2.3", "model_error: you have hit your limit")
    assert row.failure_kind == lg.FAILURE_OUTAGE
    monkeypatch.setattr(lg, "OUTAGE_ERROR_MARKERS", ())
    assert row.failure_kind == lg.FAILURE_OUTAGE  # the live list is not consulted
    plain = _harness_row("2.3", "model_error: a new provider refusal")
    monkeypatch.setattr(lg, "OUTAGE_ERROR_MARKERS", ("a new provider refusal",))
    assert plain.failure_kind == lg.FAILURE_HARNESS


def test_a_2_4_row_reads_its_pinned_kind_verbatim() -> None:
    """From 2.4 the label IS the kind: a pinned ``harness`` stays ``harness`` even when its
    error text names an outage marker — nothing is re-derived after write."""
    labels = {
        lg.LABEL_FAILURE_KIND: lg.FAILURE_HARNESS,
        lg.LABEL_LINT_REASON: "not_reached",
        lg.LABEL_CHANGE_ID: "d" * 40,
    }
    base: dict[str, Any] = {
        "repo": "r",
        "task_id": "a" * 40,
        "clean": False,
        "tests_unmodified": True,
        "target_green": None,
        "no_new_failures": None,
        "source_changed": None,
        "error": "model_error: you have hit your limit",
        "gold_clean": True,
        "evidence_pack_hash": "c" * 64,
        "apparatus_version": "2.4",
        "labels": labels,
    }
    row = lg.GradeRow(**with_posture_labels(base))
    assert row.failure_kind == lg.FAILURE_HARNESS


#: Every value the rule reads besides its arguments: the kinds it returns, the protocol
#: prefix and the budget stop reasons (the markers are pinned by their own hash).
_RULE_CONSTANTS = (
    "FAILURE_CLEAN",
    "FAILURE_DISQUALIFIED",
    "FAILURE_PROTOCOL",
    "FAILURE_OUTAGE",
    "FAILURE_HARNESS",
    "FAILURE_BUDGET",
    "FAILURE_API",
    "FAILURE_LINT",
    "FAILURE_BUILDER_RED",
    "PROTOCOL_VIOLATION_PREFIX",
    "BUDGET_STOP_REASONS",
)
#: What only the live rule reads (rule 3b, 2.4): pinned beside the shared constants, never
#: added to them, so the frozen v1 pin (``V1_SOURCE_SHA256``) cannot move.
_LIVE_ONLY_CONSTANTS = (
    "FAILURE_AUTHORING",
    "AUTHORING_ERROR_PREFIX",
    "AUTHORING_HARNESS_ERROR",
    "AUTHORING_AUTHOR_FAILED",
)
#: The live rule and the frozen one, each with every function it calls — held by
#: ``test_every_function_and_constant_the_live_rule_reads_is_pinned`` (P-720).
LIVE_RULE = (
    lg.derive_failure_kind,
    lg.is_outage_error,
    lg._outage,
    lg.authoring_model_error,
    lg.authoring_outage,
    lg.authoring_instrument_failure,
)
V1_RULE = (lg.derive_failure_kind_v1, lg.is_outage_error_v1, lg._outage)
_SKIP_TOKENS = {
    tokenize.COMMENT,
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.ENCODING,
    tokenize.ENDMARKER,
}


def _code_tokens(source: str) -> list[str]:
    """A function's code as tokens — its docstring, comments and blank lines dropped, so
    only an edit to what it DOES moves the hash; indentation kept as structure."""
    src = textwrap.dedent(source)
    body = ast.parse(src).body[0]
    assert isinstance(body, ast.FunctionDef)
    doc = body.body[0] if body.body else None
    doc_lines: set[int] = set()
    if (
        isinstance(doc, ast.Expr)
        and isinstance(doc.value, ast.Constant)
        and isinstance(doc.value.value, str)
    ):
        doc_lines = set(range(doc.lineno, (doc.end_lineno or doc.lineno) + 1))
    out: list[str] = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in _SKIP_TOKENS or tok.start[0] in doc_lines:
            continue
        name = tokenize.tok_name[tok.type]
        out.append(name if tok.type in (tokenize.INDENT, tokenize.DEDENT) else tok.string)
    return out


def _source_digest(sources: Iterable[str], constants: Sequence[str] = _RULE_CONSTANTS) -> str:
    body = {
        "code": [_code_tokens(src) for src in sources],
        "constants": {name: getattr(lg, name) for name in constants},
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def _live_digest(sources: Iterable[str]) -> str:
    return _source_digest(sources, (*_RULE_CONSTANTS, *_LIVE_ONLY_CONSTANTS))


def _reads(fn: Callable[..., Any]) -> tuple[set[str], set[str]]:
    """The ledger functions ``fn`` calls and the ledger constants it reads, by name."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    calls: set[str] = set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            calls.add(node.func.id)
        elif isinstance(node, ast.Name) and node.id.isupper():
            names.add(node.id)
    return (
        {c for c in calls if inspect.isfunction(getattr(lg, c, None))},
        {n for n in names if hasattr(lg, n)},
    )


def test_every_function_and_constant_the_live_rule_reads_is_pinned() -> None:
    """P-720: ``authoring_outage`` decided rule 3b's answers yet sat outside ``LIVE_RULE``,
    so an edit to it moved no source pin (P-306's class). Every ledger function the live
    rule reaches, and every ledger constant any of them reads, is pinned — by construction,
    not by a list someone remembers to extend."""
    pinned = {fn.__name__ for fn in LIVE_RULE}
    constants = set(_RULE_CONSTANTS) | set(_LIVE_ONLY_CONSTANTS)
    for fn in LIVE_RULE:
        calls, names = _reads(fn)
        assert calls <= pinned, (fn.__name__, calls - pinned)
        assert names <= constants | {"OUTAGE_ERROR_MARKERS"}, (fn.__name__, names - constants)


def _sources(fns: Sequence[Callable[..., Any]]) -> list[str]:
    return [inspect.getsource(fn) for fn in fns]


def test_the_live_failure_rule_source_is_pinned_to_the_apparatus() -> None:
    """The live rule's code, not only its answers on the grid: an edit on a branch the grid
    never reaches fails here until the apparatus moves (P-306)."""
    got = _live_digest(_sources(LIVE_RULE))
    assert APPARATUS_VERSION in GOLDEN_SOURCE, (
        f"apparatus {APPARATUS_VERSION} has no line in GOLDEN_SOURCE: add {got!r}"
    )
    assert got == GOLDEN_SOURCE[APPARATUS_VERSION], (
        f"the failure rule's code changed under apparatus {APPARATUS_VERSION} (now {got}); "
        "a change to the rule is an apparatus bump"
    )


def test_the_frozen_v1_rule_source_never_changes() -> None:
    assert _source_digest(_sources(V1_RULE)) == V1_SOURCE_SHA256


def test_an_edit_the_grid_never_reaches_still_moves_the_source_pin() -> None:
    """The class P-306 names: an edit that reads a new text as ``outage`` leaves every grid
    answer as it was — and the source pin fails on it."""
    src = inspect.getsource(lg.derive_failure_kind)
    edited = src.replace(
        "is_outage_error(error) else",
        '(is_outage_error(error) or "context length" in error) else',
    )
    assert edited != src
    namespace: dict[str, Any] = dict(vars(lg))
    exec(compile(textwrap.dedent(edited), "<edited rule>", "exec"), namespace)
    rule = namespace["derive_failure_kind"]
    assert rule(clean=False, disqualified=False, error="model_error: context length") == (
        lg.FAILURE_OUTAGE
    )
    assert _digest(rule, lg.OUTAGE_ERROR_MARKERS) == _digest(
        lg.derive_failure_kind, lg.OUTAGE_ERROR_MARKERS
    )  # the grid is blind to it …
    live = _sources(LIVE_RULE)
    assert _live_digest([edited, *live[1:]]) != _live_digest(live)  # … the pin is not


def test_a_docstring_or_comment_edit_leaves_the_source_pin_alone() -> None:
    src = inspect.getsource(lg.derive_failure_kind)
    edited = src.replace("THE rule that names why a row is not clean.", "The rule.", 1)
    edited = edited.replace("    if clean:\n", "    # a comment\n    if clean:\n", 1)
    assert edited != src
    live = _sources(LIVE_RULE)
    assert _live_digest([edited, *live[1:]]) == _live_digest(live)


#: The outage-cause rule (pilot D1, P-435): its code and the constants it reads, for the 2.4
#: rows that carry its label. Set once more before any row carried the label (Q1's review
#: pruned the auth markers the failure rule could never reach — DL-234 (4)); from the first
#: 2.4 row on it is never edited. A change to the rule or its markers moves an
#: ``outage_cause`` already pinned in the chain, so it is then an apparatus bump with the old
#: rule frozen beside the new one, like the failure rule's.
OUTAGE_CAUSE_SOURCE_SHA256 = "9db880f1bc7a56459307e5cbc578229f62efb399d71e2ba0fac37175a621d66b"


def _outage_cause_digest(source: str) -> str:
    body = {
        "code": _code_tokens(source),
        "constants": {
            "AUTH_ERROR_MARKERS": list(lg.AUTH_ERROR_MARKERS),
            "OUTAGE_CAUSES": list(lg.OUTAGE_CAUSES),
            "FAILURE_OUTAGE": lg.FAILURE_OUTAGE,
        },
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def test_the_outage_cause_rule_is_pinned_by_its_code_and_markers() -> None:
    got = _outage_cause_digest(inspect.getsource(lg.derive_outage_cause))
    assert got == OUTAGE_CAUSE_SOURCE_SHA256, (
        f"the outage-cause rule changed (now {got}); it decides a hashed 2.4 label, so a "
        "change is an apparatus bump"
    )
