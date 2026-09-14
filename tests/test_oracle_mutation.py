"""Hermetic tests for the mutation oracle-strength scorer (``crb.core.oracle.mutation``).

Fixture task (``fixtures.oracle_repo``): ONE source module and ONE target test file
that is deliberately lopsided — a STRONG oracle for ``is_admin`` (pins both truth
directions, so the ``==`` flip and the return-None mutants die) and a WEAK oracle for
``discount`` (never exercises the ``total > 100`` branch, so mutants there escape —
the proven blind spot). Real git worktree + real pytest subprocess through the crb
``PytestRunner`` + ``LocalExecutor``; no docker, no network, no model.

Locked-in guarantees: kill/escape detection, seed-free determinism (two runs
byte-identical), boundedness (``max_mutants`` truncates a stable prefix), mutants
NEVER touch test files, the source is restored byte-exact even on exception, a RED
baseline / harness error is never a strength number, and the provenance stamp.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crb.core.execution import LocalExecutor, SandboxUnavailable
from crb.core.oracle import mutation as ms
from crb.core.routing import DEFAULT_POLICY as ROUTING_POLICY
from crb.core.runners.base import TestRun as Run
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.version import APPARATUS_VERSION
from crb.core.workspace import Workspace
from fixtures.oracle_repo import (
    MUT_ALL_LINES,
    MUT_DISCOUNT_LINES,
    MUT_IS_ADMIN_LINES,
    MUT_SRC,
    MUT_TEST,
    build_controls_repo,
    fixture_config,
    make_task,
)

SRC_PATH = "mod2.py"
TEST_PATH = "tests/test_mod2.py"


# --- fixtures ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def fixture_repo(tmp_path_factory):
    return build_controls_repo(tmp_path_factory.mktemp("mutrepo"))


@pytest.fixture(scope="module")
def scratch(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("scratch")


@pytest.fixture(scope="module")
def task(fixture_repo, scratch):
    return make_task(fixture_repo, fixture_repo.mut, (SRC_PATH,), (TEST_PATH,), scratch)


@pytest.fixture(scope="module")
def gold_ws(fixture_repo, task, scratch):
    """A workspace at the GOLD state (parent + tests + sources overlaid): target GREEN."""
    ws = Workspace.create(fixture_repo.git, task.task_id, scratch / "gold", config=fixture_config())
    ws.overlay_tests(task.test_files)
    ws.overlay_sources(task.src_files)
    yield ws
    ws.remove()


@pytest.fixture(scope="module")
def harness():
    config = fixture_config()
    return {"config": config, "runner": PytestRunner(config), "executor": LocalExecutor()}


def _score(ws, task, harness, lines, **kw) -> ms.CommitOracleScore:
    return ms.score_task(
        ws, task, changed_lines=None if lines is None else {SRC_PATH: set(lines)}, **harness, **kw
    )


@pytest.fixture(scope="module")
def strong(gold_ws, task, harness):
    return _score(gold_ws, task, harness, MUT_IS_ADMIN_LINES)


@pytest.fixture(scope="module")
def weak(gold_ws, task, harness):
    return _score(gold_ws, task, harness, MUT_DISCOUNT_LINES)


class _StubRunner:
    """A runner whose verdicts are scripted: first the baseline, then one per mutant."""

    name = "stub"

    def __init__(self, runs):
        self._runs = list(runs)
        self.calls = 0

    def run_for(self, executor, root, scope, *, timeout=0, authored=None):
        # the core binds the task's author date for era-selected services (C15);
        # a scripted double has no services, so it is the plain run
        return self.run(executor, root, scope, timeout=timeout)

    def run(self, executor, root, scope, *, timeout=0):
        self.calls += 1
        item = self._runs.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


GREEN = Run(0, frozenset())
RED = Run(1, frozenset({"tests/test_mod2.py::test_x"}))


# --- kill / escape detection ------------------------------------------------------------
def test_strong_oracle_kills_everything_in_is_admin(strong):
    assert strong.total == 2  # return-None + the == flip
    assert {o.op for o in strong.outcomes} == {"return_none", "cmp_flip"}
    assert all(o.killed for o in strong.outcomes)
    assert strong.oracle_strength == 1.0
    assert strong.escaped == ()
    assert strong.errors == 0 and strong.note == ""
    assert strong.baseline is not None and strong.baseline.green


def test_weak_oracle_lets_untested_branch_escape(weak):
    by_op = {(o.op, o.line): o for o in weak.outcomes}
    # the untested `total > 100` branch is a proven blind spot:
    assert by_op[("cmp_flip", 6)].killed is False  # > -> >= escapes
    assert by_op[("arith_flip", 7)].killed is False  # - -> + in dead branch escapes
    assert by_op[("return_none", 7)].killed is False  # dead-branch return None escapes
    # but the oracle is not totally blind — these die on discount(50) == 50:
    assert by_op[("negate_cond", 6)].killed is True  # inverts the branch actually taken
    assert by_op[("return_none", 8)].killed is True  # the exercised return
    assert weak.oracle_strength is not None and 0 < weak.oracle_strength < 1.0
    assert len(weak.escaped) == weak.total - weak.killed >= 3
    # every escaped mutant carries its diff — the blind-spot catalogue evidence
    assert all(o.diff and "+" in o.diff and o.path == SRC_PATH for o in weak.escaped)
    assert all(o.status == "escaped" for o in weak.escaped)


def test_confinement_to_changed_functions(strong):
    """Mutants confined to the changed lines/functions — is_admin only => nothing in discount."""
    assert all(o.line <= 2 for o in strong.outcomes)


# --- determinism (seed-free reproducibility) --------------------------------------------
def test_two_runs_are_byte_identical(gold_ws, task, harness, strong):
    again = _score(gold_ws, task, harness, MUT_IS_ADMIN_LINES)
    # wall-clock lives in the captured evidence (pytest's "passed in 0.09s" tail and
    # duration_s) — everything that is a VERDICT, id, diff or provenance must match
    timing = {"duration_s", "tail"}

    def norm(s):
        d = s.to_dict()
        d["baseline"] = {k: v for k, v in d["baseline"].items() if k not in timing}
        d["outcomes"] = [{k: v for k, v in o.items() if k not in timing} for o in d["outcomes"]]
        return json.dumps(d, sort_keys=True)

    assert [o.mutant_id for o in again.outcomes] == [o.mutant_id for o in strong.outcomes]
    assert [o.killed for o in again.outcomes] == [o.killed for o in strong.outcomes]
    assert norm(again) == norm(strong)
    r1, r2 = ms.to_report([strong]), ms.to_report([again])
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


def test_generate_mutants_is_pure_and_deterministic():
    a = ms.generate_mutants(MUT_SRC, MUT_ALL_LINES)
    b = ms.generate_mutants(MUT_SRC, MUT_ALL_LINES)
    assert [(m.mutant_id, m.mutated_source) for m in a] == [
        (m.mutant_id, m.mutated_source) for m in b
    ]
    assert a  # the fixture region really yields mutants
    # every mutant compiles (a broken mutant would be trivially "killed" — honesty leak)
    for m in a:
        compile(m.mutated_source, SRC_PATH, "exec")
        assert m.mutated_source != MUT_SRC
    assert {m.op for m in a} <= set(ms.PYTHON_OPERATORS)


def test_the_operator_set_is_exactly_the_seven_upstream_operators():
    assert ms.PYTHON_OPERATORS == (
        "cmp_flip",
        "arith_flip",
        "bool_flip",
        "negate_cond",
        "off_by_one",
        "return_none",
        "swap_branches",
    )
    src = "def f(a, b, c):\n    if a and b:\n        return a + 1\n    else:\n        return c\n"
    ops = {m.op for m in ms.generate_mutants(src, {2, 3, 5}, max_mutants=100)}
    assert ops == {
        "bool_flip",
        "negate_cond",
        "swap_branches",
        "arith_flip",
        "off_by_one",
        "return_none",
    }


def test_unparseable_source_yields_no_mutants():
    assert ms.generate_mutants("def broken(:\n", {1}) == []


# --- boundedness --------------------------------------------------------------------------
def test_max_mutants_bounds_to_a_stable_prefix():
    full = ms.generate_mutants(MUT_SRC, MUT_ALL_LINES, max_mutants=100)
    assert len(full) > 3
    bounded = ms.generate_mutants(MUT_SRC, MUT_ALL_LINES, max_mutants=3)
    assert len(bounded) == 3
    assert [(m.mutant_id, m.mutated_source) for m in bounded] == [
        (m.mutant_id, m.mutated_source) for m in full[:3]
    ]
    assert ms.generate_mutants(MUT_SRC, MUT_ALL_LINES, max_mutants=0) == []


def test_score_task_honours_max_mutants(gold_ws, task, harness):
    score = _score(gold_ws, task, harness, MUT_ALL_LINES, max_mutants=2)
    assert score.total == 2
    assert score.provenance.max_mutants == 2


# --- mutants never touch test files; source restored byte-exact -------------------------
def test_test_files_never_touched_and_source_restored(gold_ws, task, harness):
    test_file = gold_ws.root / TEST_PATH
    before = test_file.read_bytes()
    score = _score(gold_ws, task, harness, MUT_ALL_LINES)
    assert score.total > 0
    assert test_file.read_bytes() == before  # oracle untouched
    assert (gold_ws.root / SRC_PATH).read_text() == MUT_SRC  # source restored after scoring
    assert test_file.read_text() == MUT_TEST


def test_refuses_to_mutate_a_test_file(gold_ws, task, harness):
    bad = task.with_(src_files=[TEST_PATH])
    with pytest.raises(ValueError, match="never touch the oracle"):
        _score(gold_ws, bad, harness, {1})
    assert (gold_ws.root / TEST_PATH).read_text() == MUT_TEST


def test_source_restored_byte_exact_when_the_harness_raises(gold_ws, task, harness):
    """A SandboxUnavailable mid-run propagates (infrastructure) — and the file under
    mutation is still restored byte-exact by the ``finally``."""
    runner = _StubRunner([GREEN, GREEN, SandboxUnavailable("docker gone")])
    original = (gold_ws.root / SRC_PATH).read_bytes()
    with pytest.raises(SandboxUnavailable):
        ms.score_task(
            gold_ws,
            task,
            config=harness["config"],
            runner=runner,
            executor=harness["executor"],
            changed_lines={SRC_PATH: set(MUT_ALL_LINES)},
        )
    assert (gold_ws.root / SRC_PATH).read_bytes() == original


# --- not-scoreable honesty ----------------------------------------------------------------
def test_red_baseline_is_not_scoreable(gold_ws, task, harness):
    runner = _StubRunner([RED])
    score = ms.score_task(
        gold_ws,
        task,
        config=harness["config"],
        runner=runner,
        executor=harness["executor"],
        changed_lines={SRC_PATH: set(MUT_ALL_LINES)},
    )
    assert score.total == 0 and score.killed == 0
    assert score.oracle_strength is None and not score.scoreable
    assert score.note.startswith("baseline RED")
    assert runner.calls == 1  # no mutant was ever run against a RED baseline
    # a not-scoreable task never enters a cell aggregate as strength
    assert ms.aggregate_by_cell([score]) == {}


def test_baseline_harness_error_is_not_scoreable(gold_ws, task, harness):
    runner = _StubRunner([RuntimeError("pytest exploded")])
    score = ms.score_task(
        gold_ws,
        task,
        config=harness["config"],
        runner=runner,
        executor=harness["executor"],
        changed_lines={SRC_PATH: set(MUT_ALL_LINES)},
    )
    assert score.oracle_strength is None and score.total == 0
    assert "harness error" in score.note


def test_no_mutants_region_is_not_scoreable(gold_ws, task, harness):
    score = _score(gold_ws, task, harness, {3})  # a blank line touches no function
    assert score.total == 0 and score.oracle_strength is None
    assert "no mutants" in score.note


def test_no_mutator_for_language_is_not_scoreable(gold_ws, task, harness):
    # go/javascript/jvm/rust now have the text mutator (W3-D); an UNREGISTERED language
    # is still honestly not scoreable — never silently scored with the Python mutator.
    assert ms.mutator_for("cobol") is None
    score = _score(gold_ws, task.with_(language="cobol"), harness, MUT_ALL_LINES)
    assert score.oracle_strength is None and "no mutator" in score.note


def test_harness_error_on_a_mutant_is_neither_kill_nor_escape(gold_ws, task, harness):
    n = len(ms.generate_mutants(MUT_SRC, MUT_ALL_LINES))
    runs = [GREEN, RuntimeError("boom"), *([RED] * (n - 1))]
    runner = _StubRunner(runs)
    score = ms.score_task(
        gold_ws,
        task,
        config=harness["config"],
        runner=runner,
        executor=harness["executor"],
        changed_lines={SRC_PATH: set(MUT_ALL_LINES)},
    )
    assert score.errors == 1
    assert score.total == n - 1 and score.killed == n - 1
    assert score.oracle_strength == 1.0  # over the graded mutants only
    errored = [o for o in score.outcomes if o.killed is None]
    assert len(errored) == 1 and errored[0].status == "error" and "boom" in errored[0].error
    assert (gold_ws.root / SRC_PATH).read_text() == MUT_SRC


def test_all_mutants_erroring_is_not_scoreable(gold_ws, task, harness):
    n = len(ms.generate_mutants(MUT_SRC, MUT_IS_ADMIN_LINES))
    runner = _StubRunner([GREEN, *[RuntimeError("boom")] * n])
    score = ms.score_task(
        gold_ws,
        task,
        config=harness["config"],
        runner=runner,
        executor=harness["executor"],
        changed_lines={SRC_PATH: set(MUT_IS_ADMIN_LINES)},
    )
    assert score.total == 0 and score.errors == n and score.oracle_strength is None
    assert "harness error" in score.note


def test_timeout_counts_as_a_kill_and_is_recorded(gold_ws, task, harness):
    n = len(ms.generate_mutants(MUT_SRC, MUT_IS_ADMIN_LINES))
    hung = Run(124, frozenset(), "TIMEOUT", True)
    runner = _StubRunner([GREEN, *[hung] * n])
    score = ms.score_task(
        gold_ws,
        task,
        config=harness["config"],
        runner=runner,
        executor=harness["executor"],
        changed_lines={SRC_PATH: set(MUT_IS_ADMIN_LINES)},
    )
    assert score.killed == score.total == n
    assert all(o.timed_out for o in score.outcomes)  # recomputable without them


def test_score_invariant_no_strength_without_mutants():
    with pytest.raises(ValueError):
        ms.CommitOracleScore("a" * 40, "r", (), "bug.fix", "S", 0, 0, 1.0)
    with pytest.raises(ValueError):
        ms.CommitOracleScore("a" * 40, "r", (), "bug.fix", "S", 1, 2, 1.0)


def test_sequential_scores_on_one_workspace_stay_honest(strong, weak):
    """Regression: ``.pyc`` caches validate on (int-second mtime, size), so a restore of
    the same size within the same second could re-run the LAST MUTANT's bytecode and
    turn the next baseline falsely RED. Distinct per-version mtimes make that
    impossible: both scores on the same workspace are scoreable."""
    assert strong.total > 0 and strong.note == ""
    assert weak.total > 0 and weak.note == ""


# --- changed-line derivation --------------------------------------------------------------
def test_changed_lines_from_diff():
    diff = (
        "--- a/mod.py\n+++ b/mod.py\n"
        "@@ -3,0 +4,2 @@ def f():\n+x\n+y\n"
        "@@ -10,2 +12 @@ def g():\n-a\n-b\n+c\n"
        "@@ -8,1 +7,0 @@ def h():\n-gone\n"
    )
    assert ms.changed_lines_from_diff(diff) == {4, 5, 12, 7}
    assert ms.changed_lines_from_diff("") == set()


def test_changed_lines_derived_from_git_by_default(gold_ws, task, harness):
    lines = ms.changed_lines_for(gold_ws, SRC_PATH)
    assert lines and lines <= set(range(1, MUT_SRC.count("\n") + 2))
    score = _score(gold_ws, task, harness, None)  # no override -> git diff parent..sha
    assert score.src_paths == (SRC_PATH,)
    assert {o.line for o in score.outcomes} >= {2, 6, 7, 8}
    assert score.total > 0 and score.oracle_strength is not None


# --- aggregation + reports ----------------------------------------------------------------
def test_aggregate_by_cell_and_report(strong, weak):
    cells = ms.aggregate_by_cell([strong, weak])
    assert list(cells) == [strong.cell]
    cell = cells[strong.cell]
    assert cell["tasks"] == 2
    assert cell["mutants"] == strong.total + weak.total
    assert cell["killed"] == strong.killed + weak.killed
    assert cell["oracle_strength"] == round(cell["killed"] / cell["mutants"], 4)

    report = ms.to_report([strong, weak])
    assert report["schema"] == "crb.oracle_strength.v1"
    assert report["summary"]["scoreable"] == 2
    assert report["summary"]["escaped"] == len(weak.escaped)
    assert report["provenance"]["apparatus_version"] == APPARATUS_VERSION
    md = ms.render_markdown(report)
    assert "Blind-spot catalogue" in md
    for o in weak.escaped:  # every escaped mutant is listed with its diff
        assert o.mutant_id in md
    assert "```diff" in md


def test_markdown_reports_clean_sweep(strong):
    md = ms.render_markdown(ms.to_report([strong]))
    assert "None — every generated mutant was killed." in md


def test_oracle_strength_stamp(weak):
    stamp = ms.oracle_strength_stamp(weak)
    assert f"oracle_strength={weak.oracle_strength:.2f}" in stamp
    assert f"killed={weak.killed}/{weak.total}" in stamp
    assert f"task={weak.task_id[:12]}" in stamp
    red = ms.CommitOracleScore("a" * 40, "r", ("mod.py",), "bug.fix", "S", 0, 0, None, note="RED")
    assert "n/a" in ms.oracle_strength_stamp(red)


# --- provenance stamp ---------------------------------------------------------------------
def test_provenance_stamps_apparatus_and_operator_set(strong):
    p = strong.provenance
    assert p.apparatus_version == APPARATUS_VERSION
    assert p.mutation_version == "mutation.v1"
    assert p.language == "python" and p.mutator == "PythonAstMutator"
    assert p.operator_set_hash == ms.operator_set_hash(ms.PythonAstMutator())
    assert len(p.operator_set_hash) == 64
    assert p.runner == "pytest" and p.executor == {"executor": "local"}
    assert strong.to_dict()["provenance"]["operator_set_hash"] == p.operator_set_hash


def test_operator_set_hash_is_stable_and_describes_the_operators():
    a, b = ms.PythonAstMutator(), ms.PythonAstMutator()
    assert ms.operator_set_hash(a) == ms.operator_set_hash(b)
    desc = a.describe()
    assert [o["op"] for o in desc["operators"]] == list(ms.PYTHON_OPERATORS)


def test_a_custom_mutator_plugs_in_through_the_protocol(gold_ws, task, harness):
    class OneMutant:
        language = "python"
        operators = ("noop_edit",)

        def accepts(self, path):
            return path.endswith(".py")

        def generate(self, source, changed_lines, *, max_mutants, path):
            return [
                ms.Mutant("m01_noop_edit_L1", "noop_edit", 1, 0, "identity", source + "\n", path)
            ]

        def describe(self):
            return {"language": "python", "operators": ["noop_edit"]}

    score = _score(gold_ws, task, harness, MUT_ALL_LINES, mutator=OneMutant())
    assert score.total == 1 and score.provenance.mutator == "OneMutant"
    assert score.outcomes[0].killed is False  # an identity edit is the definitional escape
    assert (gold_ws.root / SRC_PATH).read_text() == MUT_SRC


def test_strength_number_is_what_routing_consumes(weak):
    """The scorer's number is the ledger's ``oracle_strength``; the routing floor and
    the adequacy floor are one constant (0.80)."""
    assert ROUTING_POLICY.min_oracle_strength == 0.8
    assert (
        weak.oracle_strength is not None
        and weak.oracle_strength < ROUTING_POLICY.min_oracle_strength
    )
