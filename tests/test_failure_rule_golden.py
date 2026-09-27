"""The failure rule is pinned to the apparatus, and the 2.3 rule is frozen (ADR-0025 item 6).

A row's failure kind decides its denominator: ``outage`` leaves ``n``, ``harness`` counts
against autonomy, ``builder_red`` / ``lint`` / ``api`` against the model. Before this, a row
pinned ``harness`` was re-read as ``outage`` against ``OUTAGE_ERROR_MARKERS`` — a tuple anyone
could edit — so an edit to it moved stored rows between denominators (external assessment
2026-09-25, A6; P-119). Now:

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
              shows the frozen reading of a row below 2.4 cannot move when the live markers do.
How:          Evaluates each rule over one grid of inputs that exercises every branch and every
              marker, hashes the canonical JSON of the outputs with the marker list, and compares
              with ``GOLDEN``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         ADR-0025 item 6 (stream G; the draft stream R commits);
              docs/adr/0020-a-bug-is-closed-by-prevention.md
Works with:   src/crb/core/ledger.py (``derive_failure_kind``, ``derive_failure_kind_v1``,
              ``OUTAGE_ERROR_MARKERS_V1``, ``GradeRow.failure_kind``), src/crb/core/version.py
              (``APPARATUS_VERSION``, the key of the golden table), docs/PREVENTION.md (P-119,
              the row this test closes)
Tested by:    tests/test_failure_rule_golden.py
Touch when:   the apparatus moves (add its line to ``GOLDEN``: the hash the test prints) — or the
              rule changes, which is an apparatus bump (src/crb/core/version.py) first.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections.abc import Callable, Sequence
from typing import Any

import pytest

from crb.core import ledger as lg
from crb.core.version import APPARATUS_VERSION
from fixtures.posture import with_posture_labels

#: apparatus version → the hash of its failure rule over the grid, with its outage markers.
#: A version's line is written once, when that version ships, and never edited.
GOLDEN: dict[str, str] = {
    "2.3": "5f7e319ccde777ac118b0bac6b5e182b4356c419e7e6989679b7d9ec55fa473a",
}
#: SHA-256 of the canonical JSON of ``OUTAGE_ERROR_MARKERS_V1`` (frozen at 2.3).
V1_MARKERS_SHA256 = "c4f586326e2950b861953ea2e49bb6e2d8c4e1acf7bd19ce9231cd544364713f"

RuleFn = Callable[..., str]


def _errors(markers: Sequence[str]) -> list[str]:
    return [
        "",
        "protocol violation: network",
        "model_error: some other trouble",
        "grader exception: 429 in a test log",
        "environment: gold control red",
        *(f"model_error: provider said {m.upper()}" for m in markers),
    ]


def _table(rule: RuleFn, markers: Sequence[str]) -> list[Any]:
    """The rule's output over the grid: every branch, every marker."""
    out: list[Any] = []
    grid = itertools.product(
        (True, False),  # clean
        (True, False),  # disqualified
        _errors(markers),
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


def _digest(rule: RuleFn, markers: Sequence[str]) -> str:
    body = {"markers": list(markers), "table": _table(rule, markers)}
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
    assert _digest(lg.derive_failure_kind_v1, lg.OUTAGE_ERROR_MARKERS_V1) == GOLDEN["2.3"]


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
