"""The failure rule is pinned to the apparatus, and the 2.3 rule is frozen (ADR-0025 item 6).

A row's failure kind decides its denominator: ``outage`` leaves ``n``, ``harness`` counts
against autonomy, ``builder_red`` / ``lint`` / ``api`` against the model. Before this, a row
pinned ``harness`` was re-read as ``outage`` against ``OUTAGE_ERROR_MARKERS`` — a tuple anyone
could edit — so an edit to it moved stored rows between denominators (external assessment
2026-09-25, A6; P-293). Now:

* the rule as it stood at 2.3 and its outage markers are FROZEN
  (``derive_failure_kind_v1``, ``OUTAGE_ERROR_MARKERS_V1``) and read every row below 2.4;
* the live rule (``derive_failure_kind``) and its live markers hash to the value this file
  pins for the current ``APPARATUS_VERSION``: changing either fails here until the apparatus
  moves and a new line is added below. The line of an earlier version is never edited.

Navigation
----------
What it is:   The golden table of the failure rule, one hash per apparatus version, and the
              pinned hash of the frozen 2.3 outage markers.
What it does: Fails when the live rule or its markers change under an unchanged
              ``APPARATUS_VERSION``; fails when the frozen v1 rule or markers change at all;
              shows the frozen reading of a row below 2.4 cannot move when the live markers do;
              and pins each rule's code as well as its answers, so an edit on a branch the grid
              never reaches fails too (P-298).
How:          Evaluates each rule over one grid of inputs that exercises every branch and every
              marker, hashes the canonical JSON of the outputs with the marker list, and compares
              with ``GOLDEN``; hashes each rule's tokens (docstring and comments dropped) with the
              constants it reads, and compares with ``GOLDEN_SOURCE`` / ``V1_SOURCE_SHA256``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         ADR-0025 item 6 (stream G; the draft stream R commits);
              docs/adr/0020-a-bug-is-closed-by-prevention.md
Works with:   src/crb/core/ledger.py (``derive_failure_kind``, ``derive_failure_kind_v1``,
              ``OUTAGE_ERROR_MARKERS_V1``, ``GradeRow.failure_kind``), src/crb/core/version.py
              (``APPARATUS_VERSION``, the key of the golden table), docs/PREVENTION.md (P-293,
              the row this test closes)
Tested by:    tests/test_failure_rule_golden.py
Touch when:   the apparatus moves (add its lines to ``GOLDEN`` and ``GOLDEN_SOURCE``: the hashes
              the tests print) — or the rule changes, which is an apparatus bump
              (src/crb/core/version.py) first.
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
    # Wave 2 integration wrote this line on the grid that reads them (AUTHORING_ERRORS)
    "2.4": "e5acb3be0430e2fc0ad050087aa89865fc89781a00b70cfa6adbfa74fa20b268",
}
#: SHA-256 of the canonical JSON of ``OUTAGE_ERROR_MARKERS_V1`` (frozen at 2.3).
V1_MARKERS_SHA256 = "c4f586326e2950b861953ea2e49bb6e2d8c4e1acf7bd19ce9231cd544364713f"
#: apparatus version → the hash of the live rule's SOURCE (``_source_digest``): the grid
#: above pins what the rule answers on its inputs, this pins the rule itself, so an edit on a
#: branch the grid never reaches still fails (P-298). Written once per version, never edited.
GOLDEN_SOURCE: dict[str, str] = {
    "2.3": "f4931817defdcb051a19397bee4a2b32bc1ea73e8b59eb2216edc3063df21e96",
    "2.4": "869ee80395a9d636283035a2ea0b50f036298ecac6b7cbd9965a55d21602f251",
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
)


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
#: The live rule and the frozen one, each with every function it calls.
LIVE_RULE = (lg.derive_failure_kind, lg.is_outage_error, lg._outage)
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


def _source_digest(sources: Iterable[str]) -> str:
    body = {
        "code": [_code_tokens(src) for src in sources],
        "constants": {name: getattr(lg, name) for name in _RULE_CONSTANTS},
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def _sources(fns: Sequence[Callable[..., Any]]) -> list[str]:
    return [inspect.getsource(fn) for fn in fns]


def test_the_live_failure_rule_source_is_pinned_to_the_apparatus() -> None:
    """The live rule's code, not only its answers on the grid: an edit on a branch the grid
    never reaches fails here until the apparatus moves (P-298)."""
    got = _source_digest(_sources(LIVE_RULE))
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
    """The class P-298 names: an edit that reads a new text as ``outage`` leaves every grid
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
    assert _source_digest([edited, *live[1:]]) != _source_digest(live)  # … the pin is not


def test_a_docstring_or_comment_edit_leaves_the_source_pin_alone() -> None:
    src = inspect.getsource(lg.derive_failure_kind)
    edited = src.replace("THE rule that names why a row is not clean.", "The rule.", 1)
    edited = edited.replace("    if clean:\n", "    # a comment\n    if clean:\n", 1)
    assert edited != src
    live = _sources(LIVE_RULE)
    assert _source_digest([edited, *live[1:]]) == _source_digest(live)
