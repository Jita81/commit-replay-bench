"""The worker's binding of the spend rules to one run: the ledger as it stood at run start.

:mod:`crb.core.spend` holds the rules as pure functions over observations. This module
turns the ledger into those observations ONCE, when a replay or blind run starts, and
binds them to the run's repository, mode and ladder:

* ``escalation_gate(size, next_rung_index)`` for :class:`crb.core.run.RunSpec` — the
  measured escalation rule (default) or ``always``;
* ``budget_for_task(task, mode, rung, rung_budget)`` for
  :func:`crb.builders.adapter.build_fn_for` — the calibrated budget profile, only when the
  run or the repository asked for it (``None`` otherwise, so the attempt runs under the
  rung's budget exactly as before). Turns come from the clean rows' evidence packs
  (``builder.turns``), read once.

The policy (run > repository > default) and the rules' constants are stamped into the
run's apparatus (``extra.spend``), and every decision is on the row it shaped.

Navigation
----------
What it is:   The run-start binding of the spend rules — a snapshot of the ledger turned into
              an escalation gate and, when asked for, a per-attempt calibrated budget.
What it does: Reads every ledger row once (prior data only), reads the recorded turns of the
              clean rows' packs when the profile is calibrated, resolves the policy (run >
              repository > default) and returns the two hooks plus the apparatus record.
How:          ``build_spend_hooks`` → ``observation_from_row`` per row → closures over
              ``escalation_decision`` and ``calibrate``; ``pack_turns`` reads
              ``EvidencePackRow.body_json.builder.turns`` in chunks.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md
Works with:   src/crb/core/spend.py (the rules), src/crb/server/worker.py (``_run_replay``
              calls ``build_spend_hooks`` and passes the hooks on), src/crb/core/run.py (the
              gate), src/crb/builders/adapter.py (``budget_for_task``), src/crb/store/models.py
              (``EvidencePackRow``, where the turns are)
Tested by:    tests/test_worker_spend.py
Touch when:   the observation a rule reads changes (turns, latency, a new cap); never for a
              new repository — ``RepoConfig.spend`` is the per-repository switch.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from crb.builders.base import Budget, EscalationLadder, Rung
from crb.core.ledger import GradeRow
from crb.core.spec import TaskSpec
from crb.core.spend import (
    CALIBRATION_CEILING,
    CALIBRATION_MARGIN,
    CALIBRATION_MIN_CLEAN,
    CALIBRATION_QUANTILE,
    ESCALATION_BAR,
    ESCALATION_MIN_N,
    PROFILE_CALIBRATED,
    EscalationDecision,
    EscalationGate,
    SpendObservation,
    SpendPolicy,
    calibrate,
    escalation_decision,
    observation_from_row,
    resolve_policy,
)
from crb.store.models import EvidencePackRow

#: ``budget_for_task`` as :func:`crb.builders.adapter.build_fn_for` takes it.
BudgetForTask = Callable[[TaskSpec, str, Rung, Budget], tuple[Budget, Mapping[str, str]]]
#: The label every row carries for the caps its attempt actually ran under.
LABEL_BUDGET_TIER = "budget_tier"
#: Pack hashes read per query when collecting turns.
_CHUNK = 500


@dataclass(frozen=True)
class SpendHooks:
    """What one run runs under: the policy, the gate, and (when calibrated) the budget hook."""

    policy: SpendPolicy
    escalation_gate: EscalationGate
    budget_for_task: BudgetForTask | None
    n_observations: int

    def apparatus(self) -> dict[str, Any]:
        """``extra.spend`` on the run's apparatus: the policy, its sources and the rules'
        numbers, so a row's decision can be read back without the code."""
        return {
            **self.policy.to_dict(),
            "observations": self.n_observations,
            "escalation_rule": {"bar": ESCALATION_BAR, "min_n": ESCALATION_MIN_N},
            "calibration_rule": {
                "min_clean": CALIBRATION_MIN_CLEAN,
                "quantile": CALIBRATION_QUANTILE,
                "margin": CALIBRATION_MARGIN,
                "ceiling": CALIBRATION_CEILING,
            },
        }


def pack_turns(factory: sessionmaker[Session], pack_hashes: Iterable[str]) -> dict[str, int]:
    """``pack_hash → builder.turns`` for the packs that recorded a positive turn count."""
    wanted = sorted({h for h in pack_hashes if h})
    out: dict[str, int] = {}
    with factory() as s:
        for i in range(0, len(wanted), _CHUNK):
            chunk = wanted[i : i + _CHUNK]
            q = select(EvidencePackRow.pack_hash, EvidencePackRow.body_json).where(
                EvidencePackRow.pack_hash.in_(chunk)
            )
            for pack_hash, body in s.execute(q):
                builder = (body or {}).get("builder") if isinstance(body, Mapping) else None
                turns = builder.get("turns") if isinstance(builder, Mapping) else None
                if isinstance(turns, int) and turns > 0:
                    out[str(pack_hash)] = turns
    return out


def observations(
    rows: Sequence[GradeRow], turns: Mapping[str, int] | None = None
) -> list[SpendObservation]:
    """Every row as the spend rules read it, with its pack's turns when known."""
    t = turns or {}
    return [observation_from_row(r, turns=t.get(r.evidence_pack_hash)) for r in rows]


def build_spend_hooks(
    *,
    rows: Sequence[GradeRow],
    repo: str,
    mode: str,
    ladder: EscalationLadder,
    params: Mapping[str, Any],
    repo_spend: Mapping[str, Any],
    tier_fn: Callable[[Budget], str],
    turns_for: Callable[[Iterable[str]], Mapping[str, int]] | None = None,
) -> SpendHooks:
    """Bind the rules to one run (module docstring). ``rows`` is the ledger BEFORE the run;
    ``turns_for`` (pack hashes → turns) is called once, only for a calibrated profile.
    Raises ``ValueError`` for a policy value the rules do not know."""
    policy = resolve_policy(params, repo_spend)
    turns: Mapping[str, int] = {}
    if policy.budget_profile == PROFILE_CALIBRATED and turns_for is not None:
        turns = turns_for(r.evidence_pack_hash for r in rows if r.clean)
    obs = observations(rows, turns)
    rungs: tuple[Rung, ...] = tuple(ladder.rungs)

    def gate(size: str, next_index: int) -> EscalationDecision:
        rung = rungs[next_index]
        return escalation_decision(
            obs,
            policy=policy.escalation,
            repo=repo,
            mode=mode,
            size=size,
            builder=rung.builder,
            model=rung.model,
        )

    budget_for_task: BudgetForTask | None = None
    if policy.budget_profile == PROFILE_CALIBRATED:

        def calibrated(
            task: TaskSpec, mode_: str, rung: Rung, rung_budget: Budget
        ) -> tuple[Budget, Mapping[str, str]]:
            cal = calibrate(
                obs,
                repo=repo,
                mode=mode_,
                size=task.size,
                builder=rung.builder,
                model=rung.model,
                floor=rung_budget.to_dict(),
            )
            chosen = replace(rung_budget, **dict(cal.caps))
            return chosen, {**cal.labels(), LABEL_BUDGET_TIER: tier_fn(chosen)}

        budget_for_task = calibrated
    return SpendHooks(policy, gate, budget_for_task, len(obs))


__all__ = [
    "LABEL_BUDGET_TIER",
    "BudgetForTask",
    "SpendHooks",
    "build_spend_hooks",
    "observations",
    "pack_turns",
]
