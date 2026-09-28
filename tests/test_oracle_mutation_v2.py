"""Oracle scoring v2 (``mutation.v2``, ADR-0025 item 7; G-974).

``mutation.v1`` kept a stable prefix of the candidates in file order, so a change to several
files was scored on its first file's earliest lines, and it counted a timeout and an exit-0
run whose output did not parse as kills (external assessment 2026-09-25, A6). v2:

* generates every candidate of every changed file, ranks each file's by
  ``sha256(task_id|path|line|col|op)``, and takes files in path order one candidate each in
  turn up to ``max_mutants`` — the sampler ``hash-rr.v1``, recorded with the candidates per
  file;
* counts a ``timeout`` and an ``unattributed`` run apart — neither a kill nor an escape;
* reads a score with more than half its planned mutants excluded as not scoreable.

v2 is the scorer of apparatus 2.4 (ADR-0025 item 14): these tests set the stamp stream R's
bump will set, and one test pins that below 2.4 the scorer is v1 as it stood (P-121).

Navigation
----------
What it is:   The tests of the v2 sampler and outcome rule, on a two-file change with a
              scripted runner (no toolchain, no git history).
What it does: Pins that the sample reaches both files, is exactly the hash-ranked round-robin,
              is deterministic and differs between commits; that timeouts and unparsed exit-0
              runs are counted apart; that more than half excluded is not scoreable while half
              is; the provenance and version stamps; and that below apparatus 2.4 the scorer,
              its stamp and its operator-set hash are v1's.
How:          A bound ``Workspace`` over a temporary directory holding two source files, the
              ``PythonAstMutator`` and a stub runner that scripts the baseline and each mutant.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0009-text-level-mutators.md; ADR-0025 item 7 (stream G; the draft stream R
              commits)
Works with:   src/crb/core/oracle/mutation.py (under test), tests/test_oracle_mutation.py (the
              scorer's own suite on a real repository), docs/dod/journeys/prove-the-instrument.md
              (prove-the-instrument.truth.19, the criterion this closes)
Tested by:    tests/test_oracle_mutation_v2.py
Touch when:   the sampler or the exclusion rule changes (a new ``mutation_version``, with the
              apparatus bump it rides).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from crb.core import version as crb_version
from crb.core.execution import LocalExecutor
from crb.core.git import GitRepo
from crb.core.oracle import mutation as ms
from crb.core.runners.base import TestRun as Run
from crb.core.spec import Language, RepoConfig, TaskSpec
from crb.core.workspace import Workspace

A = "pkg/alpha.py"
B = "pkg/beta.py"
#: Many candidates in the FIRST file (in path order): v1's prefix never left it.
SRC_A = "".join(
    f"def f{i}(x):\n    if x > {i}:\n        return x + {i}\n    return x - {i}\n\n\n"
    for i in range(10)
)
SRC_B = "def g(x):\n    if x < 3:\n        return x * 2\n    return x\n"
GREEN = Run(0, frozenset())
RED = Run(1, frozenset({"tests/test_pkg.py::test_x"}))
HUNG = Run(124, frozenset(), "TIMEOUT", True)
UNPARSED = Run(0, frozenset(), "…", parse_error="no reporter output")


class _Stub:
    """A runner whose verdicts are scripted: the baseline, then one per mutant (repeating
    the last when the script runs out)."""

    name = "stub"

    def __init__(self, *runs: Run) -> None:
        self._runs = list(runs)

    def run_for(self, executor: Any, root: Path, scope: Any, **kw: Any) -> Run:
        return self._runs.pop(0) if len(self._runs) > 1 else self._runs[0]


def _lines(src: str) -> set[int]:
    return set(range(1, src.count("\n") + 2))


def _setup(tmp_path: Path, task_id: str = "a" * 40) -> tuple[Workspace, TaskSpec, RepoConfig]:
    for rel, src in ((A, SRC_A), (B, SRC_B)):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src, encoding="utf-8")
    ws = Workspace(GitRepo(tmp_path), tmp_path, sha=task_id, parent=task_id)
    config = RepoConfig(name="r", language=Language.PYTHON, test_prefix="tests/")
    task = TaskSpec(
        task_id=task_id,
        repo="r",
        subject="two files",
        authored="2026-01-01T00:00:00+00:00",
        test_files=("tests/test_pkg.py",),
        src_files=(B, A),  # the commit's own order is not the sampler's
        target_tests=("tests/test_pkg.py",),
        belt_scope=("tests/",),
        language="python",
    )
    return ws, task, config


def _score(tmp_path: Path, *runs: Run, task_id: str = "a" * 40, **kw: Any) -> ms.CommitOracleScore:
    ws, task, config = _setup(tmp_path, task_id)
    return ms.score_task(
        ws,
        task,
        config=config,
        runner=_Stub(GREEN, *runs),  # type: ignore[arg-type]
        executor=LocalExecutor(),
        changed_lines={A: _lines(SRC_A), B: _lines(SRC_B)},
        **kw,
    )


@pytest.fixture(autouse=True)
def _at_apparatus_2_4(monkeypatch: pytest.MonkeyPatch) -> None:
    """``mutation.v2`` is the scorer of apparatus 2.4 (ADR-0025 item 14): these tests run
    the stamp stream R's bump will set; below it the scorer is ``mutation.v1``."""
    monkeypatch.setattr(crb_version, "APPARATUS_VERSION", "2.4")


def test_the_version_and_the_sampler_are_stamped(tmp_path: Path) -> None:
    score = _score(tmp_path, RED)
    assert ms.mutation_version() == ms.MUTATION_V2 == "mutation.v2"
    prov = score.provenance.to_dict()
    assert prov["apparatus_version"] == "2.4"
    assert prov["mutation_version"] == "mutation.v2" and prov["sampler"] == "hash-rr.v1"
    every_a = ms.generate_mutants(SRC_A, _lines(SRC_A), max_mutants=10_000, path=A)
    every_b = ms.generate_mutants(SRC_B, _lines(SRC_B), max_mutants=10_000, path=B)
    assert prov["candidates_per_file"] == {A: len(every_a), B: len(every_b)}
    assert len(every_a) > ms.DEFAULT_MAX_MUTANTS > 2 * len(every_b)


def test_a_two_file_change_is_sampled_from_both_files_round_robin(tmp_path: Path) -> None:
    score = _score(tmp_path, RED)
    paths = [o.path for o in score.outcomes]
    n_b = score.provenance.candidates_per_file[B]
    assert len(paths) == ms.DEFAULT_MAX_MUTANTS
    # path order, one each in turn, until beta runs out; then alpha fills the rest
    assert paths[: 2 * n_b] == [A, B] * n_b
    assert paths.count(B) == n_b and paths.count(A) == ms.DEFAULT_MAX_MUTANTS - n_b


def test_the_sample_is_the_hash_ranking_not_the_earliest_lines(tmp_path: Path) -> None:
    task_id = "a" * 40
    score = _score(tmp_path, RED, task_id=task_id)
    every_a = ms.generate_mutants(SRC_A, _lines(SRC_A), max_mutants=10_000, path=A)
    want = sorted(every_a, key=lambda m: (ms.rank_key(task_id, m), m.description))
    taken = [(o.line, o.op, o.description) for o in score.outcomes if o.path == A]
    assert taken == [(m.line, m.op, m.description) for m in want[: len(taken)]]
    earliest = sorted(every_a, key=lambda m: (m.line, m.col))[: len(taken)]
    assert taken != [(m.line, m.op, m.description) for m in earliest]


def test_the_sample_is_deterministic_and_seeded_by_the_commit(tmp_path: Path) -> None:
    one = _score(tmp_path / "1", RED)
    two = _score(tmp_path / "2", RED)
    other = _score(tmp_path / "3", RED, task_id="b" * 40)
    ids = [(o.path, o.line, o.op, o.description) for o in one.outcomes]
    assert ids == [(o.path, o.line, o.op, o.description) for o in two.outcomes]
    assert ids != [(o.path, o.line, o.op, o.description) for o in other.outcomes]


def test_a_timeout_and_an_unparsed_exit_zero_are_neither_kills_nor_escapes(
    tmp_path: Path,
) -> None:
    runs = [HUNG, UNPARSED, *[RED] * 18]
    score = _score(tmp_path, *runs)
    assert (score.timeouts, score.unattributed, score.errors, score.uncompilable) == (1, 1, 0, 0)
    assert score.total == 18 and score.killed == 18 and score.oracle_strength == 1.0
    statuses = [o.status for o in score.outcomes]
    assert statuses[:2] == [ms.OUTCOME_TIMEOUT, ms.OUTCOME_UNATTRIBUTED]
    assert all(o.killed is None for o in score.outcomes[:2])
    d = score.to_dict()
    assert d["timeouts"] == 1 and d["unattributed"] == 1


def test_more_than_half_excluded_is_not_scoreable_and_half_is(tmp_path: Path) -> None:
    n = ms.DEFAULT_MAX_MUTANTS
    over = _score(tmp_path / "over", *[HUNG] * (n // 2 + 1), *[RED] * n)
    assert over.oracle_strength is None and not over.scoreable
    assert over.total == n // 2 - 1  # the graded minority is kept, and reads no strength
    assert "more than half" in over.note and f"timeouts={n // 2 + 1}" in over.note
    half = _score(tmp_path / "half", *[UNPARSED] * (n // 2), *[RED] * n)
    assert half.scoreable and half.oracle_strength == 1.0 and half.unattributed == n // 2
    report = ms.to_report([over, half])
    assert report["summary"]["scoreable"] == 1 and report["summary"]["timeouts"] == n // 2 + 1


def test_a_timed_out_outcome_cannot_be_a_kill() -> None:
    with pytest.raises(ValueError, match="timed out"):
        ms.MutantOutcome("m01", "cmp_flip", 1, "x", True, "", timed_out=True)
    with pytest.raises(ValueError, match="unattributed"):
        ms.MutantOutcome("m01", "cmp_flip", 1, "x", False, "", unattributed=True)


def test_below_2_4_the_scorer_is_mutation_v1_as_it_stood(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-121: the scoring rule follows the apparatus, so a score stamped 2.3 is a v1 score —
    the stable prefix of the first file's earliest candidates, a timeout read as a kill, no
    sampler in the stamp — and never one of v2 under a 2.3 stamp."""
    monkeypatch.setattr(crb_version, "APPARATUS_VERSION", "2.3")
    score = _score(tmp_path, HUNG, RED)
    prov = score.provenance.to_dict()
    assert prov["apparatus_version"] == "2.3" and prov["mutation_version"] == "mutation.v1"
    assert "sampler" not in prov and "candidates_per_file" not in prov
    assert ms.PythonAstMutator().describe()["version"] == "mutation.v1"
    every_b = ms.generate_mutants(SRC_B, _lines(SRC_B), max_mutants=10_000, path=B)
    prefix = [*every_b, *ms.generate_mutants(SRC_A, _lines(SRC_A), max_mutants=10_000, path=A)]
    taken = [(o.path, o.line, o.op, o.description) for o in score.outcomes]
    want = prefix[: ms.DEFAULT_MAX_MUTANTS]
    assert taken == [(m.path, m.line, m.op, m.description) for m in want]
    assert score.outcomes[0].timed_out and score.outcomes[0].killed is True
    assert score.timeouts == 0 and score.killed == score.total == ms.DEFAULT_MAX_MUTANTS


def test_the_operator_set_hash_moves_with_the_scorer() -> None:
    """The hash names the scorer too: a 2.3 score and a 2.4 score never share one."""
    mut = ms.PythonAstMutator()
    v2 = ms.operator_set_hash(mut)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(crb_version, "APPARATUS_VERSION", "2.3")
        assert ms.operator_set_hash(mut) != v2


@pytest.mark.parametrize(
    ("apparatus", "rule"),
    [("2.3", ms.MUTATION_V2), ("2.0", ms.MUTATION_V2), ("2.4", ms.MUTATION_V1)],
)
def test_a_stamp_whose_rule_is_not_its_apparatus_rule_is_refused(apparatus: str, rule: str) -> None:
    """P-127: the class P-121 named, closed where every score is stamped. A provenance that
    names a rule other than its apparatus's cannot be built, whoever builds it — so a score
    stamped 2.3 is never a v2 score even if a caller asks for one."""
    with pytest.raises(ValueError, match="rule of apparatus"):
        ms.MutationProvenance(apparatus_version=apparatus, mutation_version=rule)
    ok = ms.MutationProvenance(apparatus_version=apparatus)
    assert ok.mutation_version == ms.mutation_version(apparatus)
