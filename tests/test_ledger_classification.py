"""A row of apparatus 2.4 carries its own classification from write (ADR-0025 items 5 and 6).

Below 2.4 a row's failure kind could be re-derived on read, a clean row and every factory row
carried none, and belt 5's ``None`` did not say whether a linter was absent or switched off.
From 2.4 every measured row is written with ``failure_kind`` (``""`` when clean) and
``lint_reason`` by ONE helper (``crb.core.ledger.row_labels_at_write``) that the replay and
the factory writers share; a replay row also names the change it observed (``change_id``)
and must have been gold-checked clean. The ledger refuses a 2.4 row that breaks any of that,
at write and on read alike. Rows below 2.4 are written and read exactly as before.

The apparatus does not move here: stream R owns the bump to 2.4. These tests stamp rows
``2.4`` explicitly (``apparatus_version=``), which is what ``crb.core.version`` will say.

Navigation
----------
What it is:   The tests of the 2.4 classification labels and their refusals in the ledger.
What it does: Pins each refusal of an unlabelled or self-contradicting 2.4 row; that the
              replay writer and the factory writer stamp the same kind through the one helper;
              that a clean 2.4 row pins ``""``; that a 2.3 row is written as before.
How:          Hand-built ``GradeResult``s (``posture_result``) reduced by
              ``grade_row_from_result`` and ``factory_row``; ``GradeRow`` built from their
              fields with one label removed or changed.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         ADR-0025 items 5 and 6 (stream G; the draft stream R commits),
              docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/core/ledger.py (under test), src/crb/factory/build.py (``factory_row``),
              src/crb/core/lint.py (``LINT_STATUSES``), tests/fixtures/posture.py (the posture
              labels and hand-built results the rows reduce)
Tested by:    tests/test_ledger_classification.py
Touch when:   a label joins what a 2.4 row must carry, or a refusal changes.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from crb.core import grade as g
from crb.core import ledger as lg
from crb.core import lint as lint_mod
from crb.core.evidence import BuilderRef
from crb.core.spec import TaskSpec
from crb.factory.build import factory_row
from fixtures.posture import posture_result

SHA = "a" * 40
CHANGE = "e" * 40
V2 = "2.4"
_CORE = g.Belts(True, True, True, True)


def _task(**labels: str) -> TaskSpec:
    return TaskSpec(
        task_id=SHA,
        repo="r",
        subject="fix",
        authored="2026-01-01T00:00:00+00:00",
        test_files=("tests/test_x.py",),
        src_files=("x.py",),
        target_tests=("tests/test_x.py",),
        belt_scope=("tests/",),
        capability_class="bug.fix",
        language="python",
        gold_clean=True,
        labels={lg.LABEL_CHANGE_ID: CHANGE, **labels},
    )


def _result(clean: bool = True, belts: g.Belts = _CORE, **kw: Any) -> g.GradeResult:
    return posture_result(SHA, "r", "sighted", clean, belts, **kw)


def _replay(result: g.GradeResult, task: TaskSpec | None = None, **kw: Any) -> lg.GradeRow:
    return lg.grade_row_from_result(
        result, task or _task(), pack_hash="c" * 64, apparatus_version=V2, **kw
    )


def _without(row: lg.GradeRow, key: str) -> dict[str, Any]:
    f = row.fields()
    f["labels"] = {k: v for k, v in row.labels.items() if k != key}
    return f


def _with(row: lg.GradeRow, **labels: str) -> dict[str, Any]:
    f = row.fields()
    f["labels"] = {**row.labels, **labels}
    return f


def test_a_clean_2_4_row_pins_the_empty_kind_its_lint_reason_and_its_change() -> None:
    row = _replay(_result(lint_status=lint_mod.LINT_NONE_DETECTED))
    assert row.apparatus_version == V2 and row.clean
    assert row.labels[lg.LABEL_FAILURE_KIND] == "" and row.failure_kind == ""
    assert row.labels[lg.LABEL_LINT_REASON] == lint_mod.LINT_NONE_DETECTED
    assert row.labels[lg.LABEL_CHANGE_ID] == CHANGE
    # what routing.v2 and the distinct count read (stream R)
    assert row.lint_reason == lint_mod.LINT_NONE_DETECTED and row.change_id == CHANGE


def test_a_2_3_row_is_written_as_before() -> None:
    """Below 2.4 nothing new is pinned: no empty kind on a clean row, no lint reason, and
    no change identity even when the task carries one (a mined task does) — so a 2.3 row
    written after stream G hashes as a 2.3 row did before it (DL-106 (2))."""
    task = _task()
    assert task.labels[lg.LABEL_CHANGE_ID] == CHANGE
    row = lg.grade_row_from_result(
        _result(lint_status=lint_mod.LINT_NONE_DETECTED),
        task,
        pack_hash="c" * 64,
        apparatus_version="2.3",
    )
    assert lg.LABEL_FAILURE_KIND not in row.labels
    assert lg.LABEL_LINT_REASON not in row.labels
    assert lg.LABEL_CHANGE_ID not in row.labels


@pytest.mark.parametrize("key", [lg.LABEL_FAILURE_KIND, lg.LABEL_LINT_REASON, lg.LABEL_CHANGE_ID])
def test_the_ledger_refuses_a_2_4_replay_row_without_a_label_it_must_carry(key: str) -> None:
    row = _replay(_result(lint_status=lint_mod.LINT_NONE_DETECTED))
    with pytest.raises(lg.LedgerIntegrityError, match=key):
        lg.GradeRow(**_without(row, key))


def test_the_ledger_refuses_a_2_4_replay_row_whose_gold_was_not_checked_clean() -> None:
    row = _replay(_result(lint_status=lint_mod.LINT_NONE_DETECTED))
    for gold in (None, False):
        with pytest.raises(lg.LedgerIntegrityError, match="gold-checked clean"):
            lg.GradeRow(**{**row.fields(), "gold_clean": gold})


@pytest.mark.parametrize(
    ("reason", "belt", "clean", "match"),
    [
        (lint_mod.LINT_NOT_REQUESTED, None, True, "not_requested"),
        (lint_mod.LINT_EVALUATED, None, True, "'evaluated' with belt 5 not evaluated"),
        (lint_mod.LINT_NONE_DETECTED, True, True, "with belt 5 evaluated"),
        (lint_mod.LINT_DISABLED_BY_CONFIG, False, False, "with belt 5 evaluated"),
        (lint_mod.LINT_ERROR, True, True, "'error' must fail belt 5 closed"),
        ("switched_off", None, True, "not one of"),
    ],
)
def test_the_ledger_refuses_a_lint_reason_that_contradicts_belt_5(
    reason: str, belt: bool | None, clean: bool, match: str
) -> None:
    row = _replay(_result(lint_status=lint_mod.LINT_NONE_DETECTED))
    fields = _with(row, **{lg.LABEL_LINT_REASON: reason})
    fields["repo_lint_clean"] = belt
    if not clean:
        fields["clean"] = False
        fields["labels"][lg.LABEL_FAILURE_KIND] = lg.FAILURE_LINT
        fields["labels"][lg.LABEL_BLAME_CONTROL] = g.BLAME_LINT_GOLD_OK
    with pytest.raises(lg.LedgerIntegrityError, match=match):
        lg.GradeRow(**fields)


def test_an_error_on_belt_5_is_never_a_clean_row() -> None:
    res = _result(
        clean=False,
        belts=g.Belts(True, True, True, True, False),
        error="lint: ruff: not runnable (rc=127)",
        lint_status=lint_mod.LINT_ERROR,
    )
    row = _replay(res)
    assert row.failure_kind == lg.FAILURE_HARNESS
    assert row.labels[lg.LABEL_LINT_REASON] == lint_mod.LINT_ERROR
    with pytest.raises((lg.LedgerIntegrityError, g.FalseQ1Violation)):
        lg.GradeRow(
            **{
                **_with(row, **{lg.LABEL_FAILURE_KIND: ""}),
                "clean": True,
                "error": "",
                "repo_lint_clean": False,
            }
        )


def _factory(result: g.GradeResult, apparatus: str, error: str = "") -> lg.GradeRow:
    pack: Any = SimpleNamespace(pack_hash="c" * 64)  # factory_row reads only the hash
    return factory_row(
        _task(),
        result,
        pack=pack,
        builder=BuilderRef(name="scripted", model="m", provider="p"),
        error=error,
        run_id="run",
        trial="r1",
        actor="t",
        labels={},
        apparatus_version=apparatus,
    )


@pytest.mark.parametrize(
    ("result", "builder_error"),
    [
        (
            _result(
                lint_status=lint_mod.LINT_EVALUATED, belts=g.Belts(True, True, True, True, True)
            ),
            "",
        ),
        (
            _result(
                clean=False,
                belts=g.Belts(True, True, True, True, False),
                lint_status=lint_mod.LINT_EVALUATED,
            ),
            "",
        ),
        (
            _result(clean=False, belts=g.Belts(True, False), lint_status=lint_mod.LINT_NOT_REACHED),
            "",
        ),
        (
            _result(clean=False, belts=g.Belts(True), lint_status=lint_mod.LINT_NOT_REACHED),
            "model_error: overloaded",
        ),
    ],
)
def test_the_factory_and_the_replay_writer_stamp_one_kind_through_one_helper(
    result: g.GradeResult, builder_error: str
) -> None:
    replay = _replay(result, builder_error=builder_error)
    made = _factory(result, V2, error=builder_error)
    assert made.labels[lg.LABEL_FAILURE_KIND] == replay.labels[lg.LABEL_FAILURE_KIND]
    assert made.labels[lg.LABEL_LINT_REASON] == replay.labels[lg.LABEL_LINT_REASON]
    assert made.failure_kind == replay.failure_kind
    # a factory row has no gold and observed no mined commit: neither is asked of it
    assert made.gold_clean is None and lg.LABEL_CHANGE_ID not in made.labels


def test_a_factory_row_below_2_4_is_written_as_before() -> None:
    made = _factory(
        _result(clean=False, belts=g.Belts(True, False), lint_status="not_reached"), "2.3"
    )
    assert lg.LABEL_FAILURE_KIND not in made.labels and lg.LABEL_LINT_REASON not in made.labels


def test_a_2_4_factory_row_without_its_kind_is_refused() -> None:
    made = _factory(_result(clean=False, belts=g.Belts(True, False), lint_status="not_reached"), V2)
    with pytest.raises(lg.LedgerIntegrityError, match=lg.LABEL_FAILURE_KIND):
        lg.GradeRow(**_without(made, lg.LABEL_FAILURE_KIND))


# --- the cause of an outage (pilot D1, P-205) -------------------------------------------

#: What the claude_code builder records when the login it presented is refused (the pilot's
#: canary 79cb7521: a keychain login answered HTTP 401 and the row read `outage`).
AUTH_401 = "model_error: authentication failed (HTTP 401) — run `claude login` as the worker's user"
USAGE_LIMIT = "model_error: you have hit your limit · resets 5pm"


def _outage(error: str, apparatus: str = V2) -> lg.GradeRow:
    red = g.Belts(True, None, None, None)
    return lg.grade_row_from_result(
        _result(clean=False, belts=red, error=error, lint_status=lint_mod.LINT_NOT_REACHED),
        _task(),
        pack_hash="c" * 64,
        apparatus_version=apparatus,
    )


def test_a_2_4_outage_row_names_a_refused_login_as_its_own_cause() -> None:
    """Pilot D1: a login this deployment presented was refused (HTTP 401) and the row was
    filed as a provider outage — the right denominator, the wrong reader's story. From 2.4 the
    row pins WHY the call never happened: ``auth`` (a local credential fault the operator
    fixes) or ``provider`` (a usage limit, a 429, an overload) — still ``outage``, still
    outside every ``n``."""
    auth = _outage(AUTH_401)
    assert auth.failure_kind == lg.FAILURE_OUTAGE and not auth.eligible
    assert auth.labels[lg.LABEL_OUTAGE_CAUSE] == lg.OUTAGE_CAUSE_AUTH
    assert auth.outage_cause == lg.OUTAGE_CAUSE_AUTH
    limit = _outage(USAGE_LIMIT)
    assert limit.failure_kind == lg.FAILURE_OUTAGE
    assert limit.outage_cause == lg.OUTAGE_CAUSE_PROVIDER
    split = lg.failure_split([auth, limit])
    assert split.n == 0 and split.outage == 2 and split.outage_auth == 1
    assert split.to_dict()["outage_auth"] == 1


def test_an_outage_row_below_2_4_carries_no_cause() -> None:
    """The cause is a 2.4 label (DL-106 (2), P-123): a 2.3 row is written as before and reads
    no cause — never one derived after the fact."""
    row = _outage(AUTH_401, apparatus="2.3")
    assert row.failure_kind == lg.FAILURE_OUTAGE
    assert lg.LABEL_OUTAGE_CAUSE not in row.labels and row.outage_cause == ""


def test_the_ledger_refuses_an_outage_cause_that_does_not_fit_its_row() -> None:
    auth = _outage(AUTH_401)
    with pytest.raises(lg.LedgerIntegrityError, match=lg.LABEL_OUTAGE_CAUSE):
        lg.GradeRow(**_without(auth, lg.LABEL_OUTAGE_CAUSE))  # a 2.4 outage row names it
    with pytest.raises(ValueError, match="outage_cause"):
        lg.GradeRow(**_with(auth, **{lg.LABEL_OUTAGE_CAUSE: "weather"}))
    clean = _replay(_result(lint_status=lint_mod.LINT_NONE_DETECTED))
    with pytest.raises(ValueError, match="outage_cause"):
        lg.GradeRow(**_with(clean, **{lg.LABEL_OUTAGE_CAUSE: lg.OUTAGE_CAUSE_AUTH}))
    old = _outage(AUTH_401, apparatus="2.3")
    with pytest.raises(ValueError, match="outage_cause"):
        lg.GradeRow(**_with(old, **{lg.LABEL_OUTAGE_CAUSE: lg.OUTAGE_CAUSE_AUTH}))


@pytest.mark.parametrize(
    ("error", "cause"),
    [
        (AUTH_401, "auth"),
        ("model_error: authentication failed (HTTP 403) — check ANTHROPIC_API_KEY", "auth"),
        ("model_error: OAuth access token is invalid", "auth"),
        (USAGE_LIMIT, "provider"),
        ("model_error: 529 overloaded", "provider"),
        ("model_error: 429 rate_limit", "provider"),
        ("model_error: some other trouble", ""),  # harness, not an outage
        ("", ""),
    ],
)
def test_the_outage_cause_rule(error: str, cause: str) -> None:
    kind = lg.derive_failure_kind(clean=False, disqualified=False, error=error)
    assert lg.derive_outage_cause(kind, error) == cause
