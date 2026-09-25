"""crb.core.spend — the calibrated budget profile and the measured escalation rule.

Navigation
----------
What it is:   The unit suite for the spend rules (value programme stream K, leaks: 47 budget
              stops costing $28.87 for no output; escalation r2/r3 = 2 clean of 40).
What it does: Pins the nearest-rank p90, the calibration levels (repo × mode × size, then
              mode × size), the minimum n, the floor (never below the run's caps) and ceiling
              (never above twice them), the turn-derived tool-call scaling, the labels a
              calibrated or floored attempt carries; the escalation rule's levels, minimum n,
              bar, the ``always`` switch and the labels; the policy precedence (run >
              repository > default) and the per-repository surface's validation; and that an
              ``r1`` or an invalid row never feeds a decision.
How:          Hand-built ``SpendObservation`` lists; no store, no worker.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/core/spend.py (under test), tests/test_worker_spend.py (the same rules
              bound to a run end to end)
Tested by:    tests/test_spend.py
Touch when:   a bar, a minimum n, the margin or the ceiling changes; a cap is added to Budget.
"""

from __future__ import annotations

import pytest

from crb.core.ledger import GradeRow
from crb.core.spec import Language, RepoConfig
from crb.core.spend import (
    ESCALATION_ALWAYS,
    ESCALATION_MEASURED,
    LABEL_BUDGET_CALIBRATION,
    LABEL_BUDGET_PROFILE,
    LABEL_ESCALATION,
    LABEL_ESCALATION_RULE,
    PROFILE_CALIBRATED,
    SpendObservation,
    calibrate,
    escalation_decision,
    is_escalated_trial,
    observation_from_row,
    quantile,
    resolve_policy,
    validate_spend_config,
)

FLOOR = {"wall_clock_s": 900, "max_turns": 25, "max_tool_calls": 25}


def obs(
    *,
    repo: str = "cobra",
    mode: str = "blind",
    size: str = "M",
    trial: str = "r1",
    clean: bool = True,
    valid: bool = True,
    latency_s: float = 100.0,
    turns: int | None = None,
    builder: str = "claude_code",
    model: str = "claude-sonnet-5",
) -> SpendObservation:
    return SpendObservation(
        repo=repo,
        mode=mode,
        size=size,
        builder=builder,
        model=model,
        trial=trial,
        clean=clean,
        valid=valid,
        latency_s=latency_s,
        turns=turns,
    )


def cal(observations: list[SpendObservation], **kw: object) -> object:
    args: dict[str, object] = {
        "repo": "cobra",
        "mode": "blind",
        "size": "M",
        "builder": "claude_code",
        "model": "claude-sonnet-5",
        "floor": FLOOR,
    }
    args.update(kw)
    return calibrate(observations, **args)  # type: ignore[arg-type]


# --- the calibrated budget ---------------------------------------------------------------


def test_quantile_is_nearest_rank() -> None:
    assert quantile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.9) == 9
    assert quantile([5], 0.9) == 5
    assert quantile([3, 1, 2], 0.5) == 2


def test_too_few_clean_completions_keep_the_floor_and_say_so() -> None:
    c = cal([obs(latency_s=880)] * 7)
    assert c.applied is False and dict(c.caps) == FLOOR  # type: ignore[attr-defined]
    labels = c.labels()  # type: ignore[attr-defined]
    assert labels[LABEL_BUDGET_PROFILE] == PROFILE_CALIBRATED
    assert labels[LABEL_BUDGET_CALIBRATION].startswith("floor:n=7<8")


def test_a_cell_whose_clean_completions_ran_long_gets_more_room_within_the_ceiling() -> None:
    rows = [
        obs(latency_s=float(s), turns=t)
        for s, t in zip(range(700, 1500, 100), range(20, 36, 2), strict=True)
    ]
    c = cal(rows)
    assert c.applied is True and c.n == 8  # type: ignore[attr-defined]
    # p90 of 700..1400 = 1400 → × 1.5 = 2100 → ceiling 2 × 900 = 1800
    assert c.caps["wall_clock_s"] == 1800  # type: ignore[attr-defined]
    # p90 of turns 20..34 = 34 → × 1.5 = 51 → ceiling 50
    assert c.caps["max_turns"] == 50  # type: ignore[attr-defined]
    assert c.caps["max_tool_calls"] == 50  # type: ignore[attr-defined]
    assert c.level == "repo+mode+size=cobra|blind|M"  # type: ignore[attr-defined]


def test_a_cell_whose_clean_completions_were_quick_never_cuts_below_the_floor() -> None:
    c = cal([obs(latency_s=30, turns=5)] * 10)
    assert dict(c.caps) == FLOOR  # type: ignore[attr-defined]
    assert c.applied is True  # measured — the floor was simply higher than p90 × margin


def test_without_recorded_turns_only_the_wall_clock_moves() -> None:
    c = cal([obs(latency_s=800)] * 8)
    assert c.caps == {"wall_clock_s": 1200, "max_turns": 25, "max_tool_calls": 25}  # type: ignore[attr-defined]
    assert "p90_turns=unknown" in c.labels()[LABEL_BUDGET_CALIBRATION]  # type: ignore[attr-defined]


def test_the_repository_level_falls_back_to_mode_and_size() -> None:
    rows = [obs(repo="click", latency_s=800)] * 5 + [obs(repo="koa", latency_s=800)] * 5
    c = cal(rows)
    assert c.applied and c.level == "mode+size=blind|M" and c.n == 10  # type: ignore[attr-defined]


def test_only_clean_valid_rows_of_the_same_builder_and_model_calibrate() -> None:
    noise = (
        [obs(clean=False, latency_s=900)] * 20
        + [obs(valid=False, latency_s=900)] * 20
        + [obs(model="claude-opus-5", latency_s=900)] * 20
        + [obs(mode="sighted", latency_s=900)] * 20
    )
    assert cal(noise).applied is False  # type: ignore[attr-defined]


# --- the measured escalation rule --------------------------------------------------------


def dec(observations: list[SpendObservation], policy: str = ESCALATION_MEASURED, **kw: object):  # type: ignore[no-untyped-def]
    args: dict[str, object] = {
        "policy": policy,
        "repo": "cobra",
        "mode": "blind",
        "size": "M",
        "builder": "claude_code",
        "model": "claude-sonnet-5",
    }
    args.update(kw)
    return escalation_decision(observations, **args)  # type: ignore[arg-type]


def test_a_rung_whose_escalations_yield_under_the_bar_stops_the_climb() -> None:
    history = [obs(trial="r2", clean=False)] * 19 + [obs(trial="r3", clean=True)]
    d = dec(history)
    assert d.climb is False
    assert d.labels[LABEL_ESCALATION] == "stopped"
    assert (
        d.labels[LABEL_ESCALATION_RULE] == "measured:repo+mode+size=cobra|blind|M:yield=1/20<0.10"
    )


def test_a_rung_at_or_over_the_bar_climbs_and_says_why() -> None:
    history = [obs(trial="r2", clean=False)] * 9 + [obs(trial="r2", clean=True)]
    d = dec(history)
    assert d.climb is True and d.labels[LABEL_ESCALATION] == "climbed"
    assert d.labels[LABEL_ESCALATION_RULE].endswith("yield=1/10>=0.10")


def test_too_few_prior_escalations_climb_as_before() -> None:
    d = dec([obs(trial="r2", clean=False)] * 9)
    assert d.climb is True
    assert d.labels[LABEL_ESCALATION_RULE] == "measured:insufficient:n=9<10:bar=0.10"


def test_first_attempts_and_invalid_rows_never_count_as_escalations() -> None:
    history = [obs(trial="r1", clean=False)] * 50 + [obs(trial="r2", clean=False, valid=False)] * 50
    assert dec(history).climb is True


def test_the_levels_widen_from_repository_to_mode() -> None:
    history = [obs(trial="r2", clean=False, repo="click", size="S")] * 10
    d = dec(history)  # no cobra rows, no blind|M rows — blind rows at any size decide
    assert d.climb is False and "mode=blind" in d.labels[LABEL_ESCALATION_RULE]


def test_always_climbs_whatever_the_history() -> None:
    d = dec([obs(trial="r2", clean=False)] * 40, policy=ESCALATION_ALWAYS)
    assert d.climb is True and d.labels[LABEL_ESCALATION_RULE] == "always"


def test_escalated_trials_are_r2_and_later() -> None:
    assert [is_escalated_trial(t) for t in ("r1", "r2", "r3", "r10", "w1r1", "")] == [
        False,
        True,
        True,
        True,
        False,
        False,
    ]


# --- policy and the per-repository surface ------------------------------------------------


def test_the_run_wins_over_the_repository_which_wins_over_the_default() -> None:
    p = resolve_policy({}, {})
    assert (p.budget_profile, p.escalation) == ("default", "measured")
    assert p.sources == {"budget_profile": "default", "escalation": "default"}
    p = resolve_policy({}, {"budget_profile": "calibrated", "escalation": "always"})
    assert (p.budget_profile, p.escalation) == ("calibrated", "always")
    assert p.sources == {"budget_profile": "repository", "escalation": "repository"}
    p = resolve_policy({"escalation": "measured"}, {"escalation": "always"})
    assert p.escalation == "measured" and p.sources["escalation"] == "run"


def test_the_repository_surface_refuses_what_it_does_not_know() -> None:
    assert validate_spend_config({"escalation": "always"}) == {"escalation": "always"}
    with pytest.raises(ValueError, match="not a spend setting"):
        validate_spend_config({"max_turns": 50})
    with pytest.raises(ValueError, match="must be one of"):
        validate_spend_config({"budget_profile": "generous"})
    with pytest.raises(ValueError, match="must be one of"):
        resolve_policy({"escalation": "sometimes"}, {})


def test_repo_config_carries_the_spend_surface_through_its_json_shape() -> None:
    cfg = RepoConfig.from_dict("click", {"language": "python", "spend": {"escalation": "always"}})
    assert cfg.spend == {"escalation": "always"}
    assert RepoConfig.from_dict("click", cfg.to_dict()).spend == {"escalation": "always"}
    with pytest.raises(ValueError, match=r"spend\.budget_profile"):
        RepoConfig(name="click", language=Language.PYTHON, spend={"budget_profile": "x"})


def test_observation_from_row_follows_the_failure_rule() -> None:
    base = {
        "repo": "cobra",
        "task_id": "a" * 40,
        "tests_unmodified": True,
        "target_green": False,
        "no_new_failures": True,
        "source_changed": True,
        "mode": "blind",
        "size": "M",
        "builder": "claude_code",
        "model": "claude-sonnet-5",
        "trial": "r2",
        "latency_s": 12.5,
    }
    red = observation_from_row(GradeRow(clean=False, **base), turns=7)  # type: ignore[arg-type]
    assert red.valid and red.escalated and red.turns == 7 and red.latency_s == 12.5
    harness = observation_from_row(GradeRow(clean=False, error="sandbox died", **base))  # type: ignore[arg-type]
    outage = observation_from_row(
        GradeRow(clean=False, error="model_error: usage limit reached", **base)  # type: ignore[arg-type]
    )
    assert harness.valid is False and outage.valid is False
