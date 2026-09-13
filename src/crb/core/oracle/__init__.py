"""crb.core.oracle — the oracle-adequacy programme. STANDARD LIBRARY ONLY.

false-Q1 = 0 says a clean grade never lacked a green oracle. This package answers
the harder question the belts cannot: *is the green worth anything?*

* :mod:`~crb.core.oracle.mutation`      — plant deterministic faults in the changed
  lines; ``oracle_strength = killed / total`` (a RED baseline or a harness error is
  never a number).
* :mod:`~crb.core.oracle.adequacy`      — the routing consequence: a clean grade
  licenses auto-delivery only on a strong oracle; weak/unscoreable → human review.
  Its floor is the same number as ``RoutingPolicy.min_oracle_strength``.
* :mod:`~crb.core.oracle.controls`      — the negative-controls gate: seven
  deterministic submissions through the REAL replay path; a VIOLATION is an
  instrument bug, a measured ESCAPE (a cheat that grades clean) is the
  oracle-weakness signal, reported never hidden.
* :mod:`~crb.core.oracle.sealed_corpus` — commitment before measurement:
  stratified, hash-split, sealed manifests with a commitment hash; authored dates
  recorded for contamination reasoning.
"""

from __future__ import annotations

from crb.core.oracle.adequacy import (
    ADEQUATE_FLOOR,
    AUTOSHIP_FLOOR,
    DECISION_AUTO_SHIP,
    DECISION_HUMAN_REVIEW,
    DECISION_NEEDS_HUMAN,
    ORACLE_ADEQUATE,
    ORACLE_STRONG,
    ORACLE_UNSCOREABLE,
    ORACLE_WEAK,
    AdequacyPolicy,
    AdequacyVerdict,
    adequacy_verdict,
    classify_oracle,
    licenses_autoship,
    routing_decision,
)
from crb.core.oracle.controls import (
    CONTROLS,
    ENV_POISON,
    GOLD,
    HARDCODE_CHEAT,
    MEASURE_CONTROLS,
    NOOP,
    REGRESSION,
    STUB,
    TEST_TAMPER,
    VERDICT_ESCAPE,
    VERDICT_NOT_CONSTRUCTIBLE,
    VERDICT_OK,
    VERDICT_SKIP,
    VERDICT_VIOLATION,
    ControlRow,
    ControlsReport,
    TamperGuard,
    controls_for_task,
    run_controls,
)
from crb.core.oracle.mutation import (
    DEFAULT_MAX_MUTANTS,
    CommitOracleScore,
    Mutant,
    MutantOutcome,
    MutationProvenance,
    Mutator,
    PythonAstMutator,
    aggregate_by_cell,
    generate_mutants,
    mutator_for,
    score_task,
)
from crb.core.oracle.sealed_corpus import (
    CorpusManifests,
    SplitFractions,
    build_manifests,
    manifest_hash,
    split_for_sha,
    suspected_exposure,
    verify_outputs,
    write_outputs,
)

__all__ = [
    "ADEQUATE_FLOOR",
    "AUTOSHIP_FLOOR",
    "CONTROLS",
    "DECISION_AUTO_SHIP",
    "DECISION_HUMAN_REVIEW",
    "DECISION_NEEDS_HUMAN",
    "DEFAULT_MAX_MUTANTS",
    "ENV_POISON",
    "GOLD",
    "HARDCODE_CHEAT",
    "MEASURE_CONTROLS",
    "NOOP",
    "ORACLE_ADEQUATE",
    "ORACLE_STRONG",
    "ORACLE_UNSCOREABLE",
    "ORACLE_WEAK",
    "REGRESSION",
    "STUB",
    "TEST_TAMPER",
    "VERDICT_ESCAPE",
    "VERDICT_NOT_CONSTRUCTIBLE",
    "VERDICT_OK",
    "VERDICT_SKIP",
    "VERDICT_VIOLATION",
    "AdequacyPolicy",
    "AdequacyVerdict",
    "CommitOracleScore",
    "ControlRow",
    "ControlsReport",
    "CorpusManifests",
    "Mutant",
    "MutantOutcome",
    "MutationProvenance",
    "Mutator",
    "PythonAstMutator",
    "SplitFractions",
    "TamperGuard",
    "adequacy_verdict",
    "aggregate_by_cell",
    "build_manifests",
    "classify_oracle",
    "controls_for_task",
    "generate_mutants",
    "licenses_autoship",
    "manifest_hash",
    "mutator_for",
    "routing_decision",
    "run_controls",
    "score_task",
    "split_for_sha",
    "suspected_exposure",
    "verify_outputs",
    "write_outputs",
]
