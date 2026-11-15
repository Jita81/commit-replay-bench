"""crb.core.ctx_compare — the fail-closed paired reader of a context set's runs (ADR-0050).

Navigation
----------
What it is:   The unit suite for ``ctx_pair``: two runs of one context set read task by task.
What it does: Pins ``b``/``c`` and the exact McNemar p against hand-computed values, the
              Wilson interval per side, that a pending task fails closed (read clean on the
              control and a miss on the treatment), that a harness-only task is not clean,
              ``dose_imbalance`` on characters and on the delivered fraction, every refusal
              (mixed arm, unlinked, one blend test per field, unsealed, gap mismatch), the
              ceiling banner iff the treatment is hindsight, and placebo linkage via
              ``matched_to``.
How:          Rows from tests/fixtures/ctx_rows.py, stamped as a run stamps them.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0050-context-set-arms.md
Works with:   src/crb/core/ctx_compare.py (under test), tests/fixtures/ctx_rows.py (the
              sets and the stamped rows paired here), src/crb/core/reading.py (``mcnemar_p``,
              the expected p), src/crb/core/stats.py (``wilson_interval``, the expected
              intervals)
Tested by:    tests/test_ctx_compare.py
Touch when:   never for a new repository; the paired reader's counts, refusals or dose rule change.
"""

from __future__ import annotations

from typing import Any

import pytest

from crb.core import ctx_compare as cc
from crb.core import ctxset
from crb.core.checks import LABEL_CHECKS
from crb.core.ledger import GradeRow
from crb.core.reading import mcnemar_p
from crb.core.stats import wilson_interval
from crb.core.taxonomy import LABEL_TAXONOMY
from fixtures.ctx_rows import TASKS, ctx_row, ctx_set, side

ORACLE = ctx_set(ctxset.SOURCE_ORACLE)
#: The placebo matched to ORACLE: same tasks, same length, no shared identifier.
PLACEBO = ctx_set(
    ctxset.SOURCE_ORACLE_PLACEBO,
    text="Some prose about weather patterns over the hills, quite long enough now.",
    matched_to=ORACLE.digest,
)
SETS = {ORACLE.digest: ORACLE, PLACEBO.digest: PLACEBO}

T = TASKS
CONTROL = {T[0]: False, T[1]: False, T[2]: False, T[3]: False, T[4]: True, T[5]: False}
TREAT = {T[0]: True, T[1]: True, T[2]: True, T[3]: True, T[4]: True, T[5]: False}


def _pair(control: list[GradeRow], treatment: list[GradeRow]) -> cc.CtxPair:
    return cc.ctx_pair(control, treatment, task_ids=ORACLE.task_ids, sets=SETS)


def _ctl(outcomes: dict[str, bool] = CONTROL, **kw: Any) -> list[GradeRow]:
    return side(ORACLE, outcomes, role=ctxset.ROLE_CONTROL, **kw)


def _trt(outcomes: dict[str, bool] = TREAT, **kw: Any) -> list[GradeRow]:
    return side(ORACLE, outcomes, **kw)


def _refused(reason: str, control: list[GradeRow], treatment: list[GradeRow]) -> None:
    with pytest.raises(cc.CtxPairRefused) as exc:
        _pair(control, treatment)
    assert exc.value.reason == reason, exc.value


class TestCounts:
    def test_b_c_and_p_by_hand(self) -> None:
        pair = _pair(_ctl(), _trt())
        # b: treatment clean, control not = T0..T3; c: control clean, treatment not = none
        assert (pair.b, pair.c) == (4, 0)
        assert pair.p == pytest.approx(0.125)  # 2 * (1/2)^4
        assert pair.p == mcnemar_p(4, 0)
        assert (pair.control.k, pair.control.n) == (1, 6)
        assert (pair.treatment.k, pair.treatment.n) == (5, 6)
        assert pair.complete and pair.pending == ()

    def test_wilson_interval_per_side(self) -> None:
        d = _pair(_ctl(), _trt()).to_dict()
        ci = wilson_interval(5, 6)
        assert d["treatment"]["ci_low"] == round(ci.low, 4)
        assert d["treatment"]["ci_high"] == round(ci.high, 4)
        assert d["control"]["point"] == round(1 / 6, 4)

    def test_discordant_both_ways(self) -> None:
        control = {**CONTROL, T[5]: True}
        pair = _pair(_ctl(control), _trt())
        assert (pair.b, pair.c) == (4, 1)
        assert pair.p == pytest.approx(mcnemar_p(4, 1))

    def test_pending_fails_closed(self) -> None:
        # T0 has no control attempt: read clean there, so its treatment win is not counted;
        # T1 has no treatment attempt: read a miss there
        control = {t: c for t, c in CONTROL.items() if t != T[0]}
        treat = {t: c for t, c in TREAT.items() if t != T[1]}
        pair = _pair(_ctl(control), _trt(treat))
        assert pair.pending == (T[0], T[1])
        assert not pair.complete
        assert (pair.b, pair.c) == (2, 0)  # T2, T3 only
        assert (pair.control.n, pair.treatment.n) == (5, 5)
        d = pair.to_dict()
        assert d["complete"] is False and d["pending"] == [T[0], T[1]]
        assert "PENDING 2" in cc.render(pair)

    def test_harness_only_task_is_not_clean(self) -> None:
        treat = _trt({t: c for t, c in TREAT.items() if t != T[0]})
        harness = ctx_row(
            ORACLE,
            T[0],
            clean=False,
            error="harness: the sandbox did not start",
            labels={"failure_kind": "harness"},
        )
        pair = _pair(_ctl(), [harness, *treat])
        assert pair.treatment.k == 4 and pair.treatment.n == 6
        assert pair.b == 3


class TestDose:
    def test_plain_control_never_imbalanced(self) -> None:
        pair = _pair(_ctl(), _trt(chars=500))
        assert not pair.dose_imbalance
        assert pair.control_dose == cc.SideDose()
        assert pair.treatment_dose.delivered == 6 and pair.treatment_dose.chars == 3000

    def test_imbalance_on_chars(self) -> None:
        placebo = side(PLACEBO, TREAT, chars=100)
        pair = cc.ctx_pair(_trt(chars=200), placebo, task_ids=PLACEBO.task_ids, sets=SETS)
        assert pair.dose_imbalance
        assert "dose_imbalance" in cc.render(pair)

    def test_within_tolerance_is_balanced(self) -> None:
        placebo = side(PLACEBO, TREAT, chars=95)
        pair = cc.ctx_pair(_trt(chars=100), placebo, task_ids=PLACEBO.task_ids, sets=SETS)
        assert not pair.dose_imbalance

    def test_imbalance_on_delivered_fraction(self) -> None:
        # same total characters, but the treatment delivered to 3 of 6 tasks
        treat = [
            ctx_row(ORACLE, t, clean=c, delivered=1 if i < 3 else 0, chars=200)
            for i, (t, c) in enumerate(TREAT.items())
        ]
        placebo = side(PLACEBO, TREAT, chars=100)
        pair = cc.ctx_pair(treat, placebo, task_ids=PLACEBO.task_ids, sets=SETS)
        assert pair.control_dose.chars == pair.treatment_dose.chars == 600
        assert pair.control_dose.fraction == 0.5
        assert pair.dose_imbalance


class TestLinkage:
    def test_placebo_linked_via_matched_to(self) -> None:
        pair = cc.ctx_pair(_ctl(), side(PLACEBO, TREAT), task_ids=PLACEBO.task_ids, sets=SETS)
        assert pair.treatment_set == PLACEBO.digest
        assert pair.control_set == ORACLE.digest

    def test_unrelated_set_is_unlinked(self) -> None:
        other = ctx_set(ctxset.SOURCE_ORACLE, text="A different brief entirely, for test.")
        with pytest.raises(cc.CtxPairRefused) as exc:
            cc.ctx_pair(
                side(other, CONTROL, role=ctxset.ROLE_CONTROL),
                _trt(),
                task_ids=ORACLE.task_ids,
                sets={**SETS, other.digest: other},
            )
        assert exc.value.reason == cc.REASON_UNLINKED

    def test_empty_treatment_is_unlinked(self) -> None:
        _refused(cc.REASON_UNLINKED, _ctl(), [])

    def test_unstored_treatment_set_is_unlinked(self) -> None:
        with pytest.raises(cc.CtxPairRefused) as exc:
            cc.ctx_pair(_ctl(), _trt(), task_ids=ORACLE.task_ids, sets={})
        assert exc.value.reason == cc.REASON_UNLINKED

    def test_task_ids_not_the_sets(self) -> None:
        with pytest.raises(cc.CtxPairRefused) as exc:
            cc.ctx_pair(_ctl(), _trt(), task_ids=ORACLE.task_ids[:-1], sets=SETS)
        assert exc.value.reason == cc.REASON_UNLINKED

    def test_mixed_arm_side(self) -> None:
        mixed = [*_trt(), *side(PLACEBO, {T[0]: True})]
        _refused(cc.REASON_MIXED_ARM, _ctl(), mixed)


#: Each blend field, and a control row changed in that field alone.
BLENDS: dict[str, dict[str, Any]] = {
    "apparatus_version": {"apparatus_version": "2.4"},
    "posture_class": {"labels": {"posture_class": "local/other/host-env"}},
    "builder_executor": {"labels": {"builder_executor": "docker-other"}},
    "checks_arm": {"labels": {LABEL_CHECKS: "fmt=1"}},
    "builder": {"builder": "editblock"},
    "model": {"model": "gpt-oss-120b"},
    "taxonomy": {"labels": {LABEL_TAXONOMY: "org/classes@v9"}},
    "mode": {"mode": "sighted"},
}


class TestRefusals:
    def test_every_blend_field_is_covered(self) -> None:
        assert set(BLENDS) == set(cc.BLEND_FIELDS)

    @pytest.mark.parametrize("field", sorted(BLENDS))
    def test_blend_refused(self, field: str) -> None:
        # one control row built through the validated fixture (GradeRow's own checks run),
        # differing from the rest in that field alone
        ctl = _ctl()
        row = ctl[0]
        odd = ctx_row(
            ORACLE, row.task_id, clean=row.clean, role=ctxset.ROLE_CONTROL, **BLENDS[field]
        )
        assert getattr(odd, field) != getattr(row, field)
        with pytest.raises(cc.CtxPairRefused) as exc:
            _pair([odd, *ctl[1:]], _trt())
        assert exc.value.reason == cc.REASON_BLEND
        assert field in exc.value.detail

    def test_unsealed(self) -> None:
        host = {"builder_executor": "host"}
        _refused(cc.REASON_UNSEALED, _ctl(labels=host), _trt(labels=host))

    def test_gap_mismatch_per_task(self) -> None:
        ctl = _ctl()
        ctl[0] = ctx_row(ORACLE, T[0], clean=False, role=ctxset.ROLE_CONTROL, gap="0")
        _refused(cc.REASON_GAP_MISMATCH, ctl, _trt())

    def test_reasons_are_closed(self) -> None:
        with pytest.raises(ValueError):
            cc.CtxPairRefused("made_up", "x")


class TestCeiling:
    def test_banner_iff_hindsight(self) -> None:
        pair = _pair(_ctl(), _trt())
        assert pair.ceiling and pair.banner == cc.CEILING_BANNER
        d = pair.to_dict()
        assert next(iter(d)) == "banner" and d["banner"] == cc.CEILING_BANNER
        assert cc.render(pair).splitlines()[0] == cc.CEILING_BANNER

    def test_no_banner_on_a_mechanical_set(self) -> None:
        mech = ctxset.parse(
            {
                "schema": ctxset.SCHEMA,
                "source": ctxset.SOURCE_MECH,
                "repo": ORACLE.repo,
                "method": "fixture",
                "drafter": "model-x@" + "c" * 64,
                "entries": [
                    {
                        "task_id": t,
                        "entry_id": f"brief/{t[-6:]}",
                        "version": "1",
                        "text": "Parent-tree facts only.",
                        "produced_at": "2026-11-01T00:00:00Z",
                        "mechanical": True,
                        "source_rev": "d" * 40,
                    }
                    for t in TASKS
                ],
            }
        )
        pair = cc.ctx_pair(
            side(mech, CONTROL, role=ctxset.ROLE_CONTROL),
            side(mech, TREAT),
            task_ids=mech.task_ids,
            sets={mech.digest: mech},
        )
        assert not pair.ceiling and pair.banner == ""
        assert "banner" not in pair.to_dict()
        assert not cc.render(pair).startswith(cc.CEILING_BANNER)
