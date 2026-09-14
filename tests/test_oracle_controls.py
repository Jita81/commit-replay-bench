"""Negative controls — prove the replay instrument rejects what it must reject, through
the REAL code path (real throwaway git repo + real pytest subprocess via the crb
``Workspace`` + ``grade``; no docker, no network, no model).

A control violation = instrument bug -> the report does not pass. A measured oracle
escape = a finding about the target tests -> the report still passes, with the
escape reported prominently. Every transform is also unit-tested as a pure function.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from crb.core.execution import LocalExecutor, SandboxUnavailable
from crb.core.grade import Belts, GradeResult
from crb.core.oracle import controls as nc
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import Language, RepoConfig
from crb.core.version import APPARATUS_VERSION
from crb.core.workspace import Workspace
from fixtures.oracle_repo import (
    build_controls_repo,
    fixture_config,
    make_task,
    make_task_unchecked,
)


# --- fixtures -------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def fixture_repo(tmp_path_factory):
    return build_controls_repo(tmp_path_factory.mktemp("ncrepo"))


@pytest.fixture(scope="module")
def scratch(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("scratch")


@pytest.fixture(scope="module")
def harness():
    config = fixture_config()
    return {"config": config, "runner": PytestRunner(config), "executor": LocalExecutor()}


@pytest.fixture(scope="module")
def fix_task(fixture_repo, scratch):
    return make_task(fixture_repo, fixture_repo.fix, ("mod.py",), ("tests/test_mod.py",), scratch)


def _run(fixture_repo, task, harness, scratch, controls=nc.CONTROLS):
    return nc.controls_for_task(
        fixture_repo.git, task, scratch=scratch, controls=controls, **harness
    )


@pytest.fixture(scope="module")
def control_matrix(fixture_repo, fix_task, harness, scratch):
    rows = _run(fixture_repo, fix_task, harness, scratch)
    assert [r.control for r in rows] == list(nc.CONTROLS)
    return {r.control: r for r in rows}


# --- the seven controls, through the real replay path ------------------------------------
def test_gold_control_goes_green_no_regression(control_matrix):
    row = control_matrix[nc.GOLD]
    assert row.observed == nc.OBS_CLEAN and row.verdict == nc.VERDICT_OK
    assert row.grade is not None and row.grade.clean and row.grade.belts.all_true


def test_noop_control_stays_red(control_matrix):
    row = control_matrix[nc.NOOP]
    assert row.observed == nc.OBS_RED and row.verdict == nc.VERDICT_OK
    assert row.grade is not None and row.grade.belts.target_green is False


def test_tamper_control_is_disqualified_never_clean(control_matrix):
    row = control_matrix[nc.TEST_TAMPER]
    assert row.observed == nc.OBS_DISQUALIFIED  # the re-hash before grading caught it
    assert row.observed != nc.OBS_CLEAN
    assert row.verdict == nc.VERDICT_OK
    assert "modified" in row.note
    # and belt 1 inside the grader caught it independently (belt-and-braces)
    assert row.grade is not None and row.grade.disqualified
    assert row.grade.tamper_files == ("tests/test_mod.py",)


def test_stub_control_fails(control_matrix):
    row = control_matrix[nc.STUB]
    assert row.observed == nc.OBS_RED and row.verdict == nc.VERDICT_OK


def test_regression_control_is_regressed_never_clean(control_matrix):
    """Target green + poisoned adjacent module MUST land in ``regressed`` — the single
    most important verdict distinction. Clean here would be an instrument bug."""
    row = control_matrix[nc.REGRESSION]
    assert row.observed == nc.OBS_REGRESSED
    assert row.observed != nc.OBS_CLEAN
    assert row.verdict == nc.VERDICT_OK
    assert "poisoned helper.py" in row.note
    g = row.grade
    assert g is not None and g.belts.target_green and g.belts.no_new_failures is False
    assert g.new_failures == ("tests/test_helper.py",)


def test_hardcode_cheat_slipping_through_is_a_measured_escape(control_matrix):
    """The fix task's target test pins ONE literal case and the suite has no other
    belt for `add` — the cheat grades clean. That is a MEASURED ORACLE ESCAPE (a
    finding about the oracle), reported as ESCAPE, never as a VIOLATION."""
    row = control_matrix[nc.HARDCODE_CHEAT]
    assert row.observed == nc.OBS_CLEAN
    assert row.verdict == nc.VERDICT_ESCAPE
    assert row.verdict != nc.VERDICT_VIOLATION
    assert row.expected == nc.CAUGHT_OR_FLAGGED
    assert "ESCAPE" in row.note and "every belt held" in row.note


def test_env_poison_is_disqualified_by_belt_1_test_infrastructure(control_matrix):
    """The fix task's parent has no conftest and no behaviour lock, so before belt 1
    covered test infrastructure the gold-via-conftest pollution graded clean (a measured
    escape, review §4.3). Now the new root ``conftest.py`` IS the oracle: belt 1b
    disqualifies it before any test runs, and the note names the belt."""
    row = control_matrix[nc.ENV_POISON]
    assert row.observed == nc.OBS_DISQUALIFIED
    assert row.verdict == nc.VERDICT_OK
    assert row.expected == nc.CAUGHT_OR_FLAGGED
    assert row.note.startswith("caught by belt 1") and "conftest.py" in row.note
    g = row.grade
    assert g is not None and g.disqualified and "test infrastructure" in g.dq_reason
    assert g.changed_files == () and g.target_run is None  # nothing ran: DQ short-circuits


# --- the other commit shapes -----------------------------------------------------------------
def test_hardcode_cheat_caught_when_target_test_exceeds_its_literals(
    fixture_repo, harness, scratch
):
    """The poly target test mixes an extractable literal assert with a loop assert the
    cheat cannot parse — the hard-coded patch leaves the target RED = caught."""
    task = make_task(
        fixture_repo, fixture_repo.poly, ("poly.py",), ("tests/test_poly.py",), scratch
    )
    (row,) = _run(fixture_repo, task, harness, scratch, controls=(nc.HARDCODE_CHEAT,))
    assert row.observed == nc.OBS_RED and row.verdict == nc.VERDICT_OK
    assert row.note.startswith("caught")


def test_env_poison_on_an_existing_conftest_is_disqualified_before_belt_3(
    fixture_repo, harness, scratch
):
    """The sub task's parent HAS a root conftest other suite tests depend on. Belt 3
    used to catch the clobbered conftest as a regression; belt 1b now fires first —
    an edited conftest is oracle tamper, disqualified before a single test runs."""
    task = make_task(fixture_repo, fixture_repo.sub, ("sub.py",), ("tests/test_sub.py",), scratch)
    (row,) = _run(fixture_repo, task, harness, scratch, controls=(nc.ENV_POISON,))
    assert row.observed == nc.OBS_DISQUALIFIED and row.verdict == nc.VERDICT_OK
    assert "caught" in row.note and "belt 1" in row.note


def test_new_file_commit_grades_gold_clean_and_env_poison_not_constructible(
    fixture_repo, harness, scratch
):
    """crb overlays files directly (no whole-file applier), so GOLD on a new-file commit
    is a legitimate clean; env-poison has no module to pollute at the parent and
    honestly reads not_constructible; the hardcode cheat CAN be built (a lookup-table
    module) and its clean grade is a measured escape."""
    task = make_task(
        fixture_repo, fixture_repo.new, ("newmod.py",), ("tests/test_newmod.py",), scratch
    )
    rows = {r.control: r for r in _run(fixture_repo, task, harness, scratch)}
    assert rows[nc.GOLD].verdict == nc.VERDICT_OK and rows[nc.GOLD].observed == nc.OBS_CLEAN
    assert rows[nc.ENV_POISON].verdict == nc.VERDICT_NOT_CONSTRUCTIBLE
    assert rows[nc.ENV_POISON].observed == nc.OBS_NOT_CONSTRUCTIBLE
    assert "does not exist at the parent" in rows[nc.ENV_POISON].note
    assert rows[nc.HARDCODE_CHEAT].verdict == nc.VERDICT_ESCAPE
    assert rows[nc.STUB].observed == nc.OBS_RED and rows[nc.NOOP].observed == nc.OBS_RED


def test_regression_not_constructible_when_source_is_alone_in_its_directory(
    fixture_repo, harness, scratch
):
    task = make_task(
        fixture_repo, fixture_repo.alone, ("pkg/alone.py",), ("tests/test_alone.py",), scratch
    )
    (row,) = _run(fixture_repo, task, harness, scratch, controls=(nc.REGRESSION,))
    assert row.verdict == nc.VERDICT_NOT_CONSTRUCTIBLE and row.observed == nc.OBS_NOT_CONSTRUCTIBLE
    assert row.grade is None


def test_task_without_red_oracle_skips_all_controls(fixture_repo, harness, scratch):
    task = make_task_unchecked(
        fixture_repo, fixture_repo.green, ("mod.py",), ("tests/test_mod.py",)
    )
    rows = _run(fixture_repo, task, harness, scratch)
    assert [r.verdict for r in rows] == [nc.VERDICT_SKIP] * len(
        nc.CONTROLS
    )  # vacuous, never a violation
    assert all("no RED oracle" in r.note for r in rows)


def test_bad_gold_is_a_violation_and_fails_the_gate(fixture_repo, harness, scratch):
    """A commit whose own source cannot satisfy its shipped test: GOLD grades red —
    the instrument cannot grade the repo's history = VIOLATION = gate FAIL."""
    task = make_task(
        fixture_repo, fixture_repo.bad_gold, ("bad.py",), ("tests/test_bad.py",), scratch
    )
    report = nc.run_controls(
        fixture_repo.git, [task], scratch=scratch, controls=(nc.GOLD, nc.NOOP), **harness
    )
    assert not report.passed
    (gold,) = report.violations
    assert gold.control == nc.GOLD and gold.observed == nc.OBS_RED
    assert "observed=red" in gold.note
    d = report.to_dict()
    assert d["violations"] == 1 and d["passed"] is False and d["escapes"] == 0
    assert "gate: FAIL" in report.render_markdown()


def test_regression_poison_target_selection_is_deterministic(fixture_repo, fix_task, scratch):
    """fix task: helper.py is same-dir, imported by tests/test_helper.py (wider suite)
    but by neither the target test nor mod.py -> the ONE valid poison target."""
    config = fixture_config()
    with Workspace.create(
        fixture_repo.git, fix_task.task_id, scratch / "poison", config=config
    ) as ws:
        ws.overlay_tests(fix_task.test_files)
        assert nc.pick_regression_poison_target(ws, fix_task, config) == "helper.py"
        assert nc.pick_regression_poison_target(ws, fix_task, config) == "helper.py"


# --- the report is the CI gate -----------------------------------------------------------------
def test_report_passes_with_escapes_reported_prominently(fixture_repo, fix_task, harness, scratch):
    """MEASURED ESCAPES are findings, not instrument bugs: the fix task yields one
    (hardcode_cheat; env_poison is now DQ'd by belt 1b) yet the gate passes, with a
    prominent escapes section."""
    report = nc.run_controls(fixture_repo.git, [fix_task], scratch=scratch, **harness)
    assert report.passed
    assert [r.control for r in report.rows] == list(nc.CONTROLS)
    assert [r.control for r in report.escapes] == [nc.HARDCODE_CHEAT]
    assert report.violations == () and report.not_constructible == () and report.skipped == ()
    assert report.task_ids == (fix_task.task_id,)
    d = report.to_dict()
    assert d["schema"] == "crb.negative_controls.v1"
    assert d["n_tasks"] == 1 and d["n_rows"] == 7
    assert d["violations"] == 0 and d["escapes"] == 1 and d["passed"] is True
    assert [r["control"] for r in d["escape_rows"]] == [nc.HARDCODE_CHEAT]
    assert d["apparatus"]["transform"] == {"language": "python", "family": "ast"}
    assert d["apparatus"]["apparatus_version"] == APPARATUS_VERSION
    assert d["apparatus"]["controls"] == list(nc.CONTROLS)
    assert d["apparatus"]["runner"] == "pytest" and d["apparatus"]["executor"] == {
        "executor": "local"
    }
    by_control = {r["control"]: r for r in d["rows"]}
    assert all(
        by_control[c]["verdict"] == nc.VERDICT_OK
        for c in (nc.GOLD, nc.NOOP, nc.TEST_TAMPER, nc.STUB, nc.REGRESSION, nc.ENV_POISON)
    )
    assert by_control[nc.GOLD]["grade"]["clean"] is True
    md = report.render_markdown()
    assert "| gold |" in md and "violations: 0" in md and "gate: PASS" in md
    assert "MEASURED ORACLE ESCAPES" in md and "escapes: 1" in md


def test_unknown_control_is_refused(fixture_repo, fix_task, harness, scratch):
    with pytest.raises(ValueError, match="unknown control"):
        _run(fixture_repo, fix_task, harness, scratch, controls=("gold", "bogus"))
    with pytest.raises(ValueError):
        nc.ControlRow("a" * 40, "r", "bogus", "clean", "clean", nc.VERDICT_OK)


def test_harness_error_is_a_violation_never_a_pass(fixture_repo, fix_task, harness, scratch):
    class Exploding:
        name = "exploding"

        def run(self, executor, root, scope, *, timeout=0):
            raise RuntimeError("toolchain missing")

    rows = nc.controls_for_task(
        fixture_repo.git,
        fix_task,
        config=harness["config"],
        runner=Exploding(),
        executor=harness["executor"],
        scratch=scratch,
        controls=(nc.GOLD, nc.NOOP),
    )
    assert [r.verdict for r in rows] == [nc.VERDICT_VIOLATION] * 2
    assert all(r.observed == nc.OBS_ERROR and "harness error" in r.note for r in rows)
    assert not nc.ControlsReport(rows).passed


def test_sandbox_unavailable_propagates(fixture_repo, fix_task, harness, scratch):
    class NoSandbox:
        name = "nosandbox"

        def run(self, executor, root, scope, *, timeout=0):
            raise SandboxUnavailable("no docker")

        def run_for(self, executor, root, scope, *, timeout=0, authored=None):
            return self.run(executor, root, scope, timeout=timeout)

    with pytest.raises(SandboxUnavailable):
        nc.controls_for_task(
            fixture_repo.git,
            fix_task,
            config=harness["config"],
            runner=NoSandbox(),
            executor=harness["executor"],
            scratch=scratch,
            controls=(nc.GOLD,),
        )


# --- the tamper guard -----------------------------------------------------------------------------
def test_tamper_guard_rehashes_the_oracle(fixture_repo, fix_task, scratch):
    config = fixture_config()
    with Workspace.create(
        fixture_repo.git, fix_task.task_id, scratch / "guard", config=config
    ) as ws:
        ws.overlay_tests(fix_task.test_files)
        guard = nc.TamperGuard(ws, fix_task.test_files)
        guard.snapshot()
        assert guard.check() == () and not guard.tests_touched
        (ws.root / "tests/test_mod.py").write_text(nc.TRIVIAL_TEST)  # out-of-band write
        assert guard.check() == ("tests/test_mod.py",)
        assert guard.tests_touched and "modified since overlay" in guard.tamper_note


# --- observe(): the projection of a GradeResult onto the control vocabulary --------------------
def _gr(**kw) -> GradeResult:
    base = {"task_id": "a" * 40, "repo": "r", "mode": "sighted", "clean": False, "belts": Belts()}
    base.update(kw)
    return GradeResult(**base)


def test_observe_projection_fails_closed():
    full = Belts(True, True, True, True)
    assert nc.observe(_gr(clean=True, belts=full)) == nc.OBS_CLEAN
    assert nc.observe(_gr(disqualified=True, dq_reason="x")) == nc.OBS_DISQUALIFIED
    assert nc.observe(_gr(error="boom", belts=full)) == nc.OBS_ERROR
    assert nc.observe(_gr(belts=Belts(True, False))) == nc.OBS_RED
    assert nc.observe(_gr(belts=Belts(True, True, False, True))) == nc.OBS_REGRESSED
    assert nc.observe(_gr(belts=Belts(True, True, True, False))) == nc.OBS_NO_SOURCE_CHANGE
    assert nc.observe(_gr(belts=Belts(True, True, None, None))) == nc.OBS_ERROR  # unattributed


def test_expected_labels():
    assert nc.expected_label(nc.GOLD) == "clean"
    assert nc.expected_label(nc.TEST_TAMPER) == "disqualified|red"
    assert nc.expected_label(nc.HARDCODE_CHEAT) == nc.CAUGHT_OR_FLAGGED
    assert set(nc.MEASURE_CONTROLS) < set(nc.CONTROLS)
    assert nc.OBS_CLEAN not in nc.EXPECTED[nc.HARDCODE_CHEAT]  # clean = escape, by definition


# --- AST stubbing is deterministic and surgical ---------------------------------------------------
def test_stub_transform_swaps_changed_bodies_and_adds_missing_defs():
    parent = "def add(a, b):\n    return a - b\n\n\ndef same(x):\n    return x\n"
    gold = (
        "def add(a, b):\n    return a + b\n\n\ndef same(x):\n    return x\n\n\n"
        "def mul(a, b):\n    return a * b\n"
    )
    stubbed = nc.stub_changed_functions(parent, gold)
    compile(stubbed, "<stub>", "exec")  # must survive collection
    assert "raise NotImplementedError" in stubbed
    assert "a - b" not in stubbed  # changed body hollowed out
    assert "def same(x):\n    return x" in stubbed  # untouched body kept
    assert "def mul" in stubbed and "a * b" not in stubbed  # added fn present but stubbed
    assert nc.stub_changed_functions(parent, gold) == stubbed  # deterministic


def test_stub_transform_handles_one_liner_defs_and_methods():
    stubbed = nc.stub_changed_functions("def f(): return 1\n", "def f(): return 2\n")
    compile(stubbed, "<stub>", "exec")
    assert "raise NotImplementedError" in stubbed and "return 1" not in stubbed
    parent = "class A:\n    def m(self):\n        return 1\n\n    def k(self):\n        return 3\n"
    gold = "class A:\n    def m(self):\n        return 2\n\n    def k(self):\n        return 3\n"
    stubbed = nc.stub_changed_functions(parent, gold)
    compile(stubbed, "<stub>", "exec")
    assert "return 1" not in stubbed and "return 3" in stubbed


def test_stub_transform_degrades_to_identity_on_unparseable_source():
    assert (
        nc.stub_changed_functions("def broken(:\n", "def f():\n    return 1\n") == "def broken(:\n"
    )


# --- literal-assert extraction + cheat construction are pure and deterministic ------------------
def test_extract_literal_asserts_shapes():
    src = (
        "from mod import add\nimport mod\n\n\ndef test_add():\n"
        "    assert add(1, 2) == 3\n"  # simple call == literal
        "    assert 6 == mod.mul(2, 3)\n"  # reversed, attribute call
        "    assert add(1, 2) == add(2, 1)\n"  # non-literal expected -> skipped
        "    assert add(x, 2) == 3\n"  # non-literal arg -> skipped
        "    assert add(a=1, b=2) == 3\n"  # keyword call -> skipped (narrowness)
        "    assert add(1, 2) >= 3\n"  # non-Eq compare -> skipped
    )
    assert nc.extract_literal_asserts(src) == [("add", (1, 2), 3), ("mul", (2, 3), 6)]
    assert nc.extract_literal_asserts("def broken(:\n") == []  # unparseable -> no facts


def test_build_hardcode_cheat_guards_existing_and_appends_missing():
    parent = "def add(a, b):\n    return a - b\n"
    cheat = nc.build_hardcode_cheat(parent, [("add", (1, 2), 3), ("mul", (2, 3), 6)])
    assert cheat is not None
    compile(cheat, "<cheat>", "exec")
    assert "if (a, b,) == (1, 2):" in cheat and "return 3" in cheat
    assert "return a - b" in cheat  # buggy body KEPT — nothing implemented
    assert "def mul(*args, **kwargs):" in cheat and "if args == (2, 3):" in cheat
    ns: dict = {}
    exec(cheat, ns)
    assert ns["add"](1, 2) == 3 and ns["add"](2, 3) == -1
    assert ns["mul"](2, 3) == 6
    with pytest.raises(NotImplementedError):
        ns["mul"](3, 3)


def test_build_hardcode_cheat_not_constructible_without_facts():
    assert nc.build_hardcode_cheat("def add(a, b):\n    return a - b\n", []) is None
    assert nc.build_hardcode_cheat("def broken(:\n", [("add", (1, 2), 3)]) is None


def test_build_hardcode_cheat_on_empty_parent_is_a_lookup_module():
    cheat = nc.build_hardcode_cheat("", [("mul", (2, 3), 6)])
    assert cheat is not None and "def mul(*args, **kwargs):" in cheat
    compile(cheat, "<cheat>", "exec")


# --- the regression selector + env-poison text are pure --------------------------------------------
def test_select_poison_target_is_pure_and_ordered():
    pick = nc.select_poison_target(
        ["z.py", "helper.py", "a.py"],
        target_texts=["from mod import add\n"],
        src_texts=["import z\n"],  # z is transitively used by the module under test
        suite_texts=["import helper\n", "import z\n"],
    )
    assert pick == "helper.py"
    assert (
        nc.select_poison_target(
            ["a.py"], target_texts=["import a"], src_texts=[], suite_texts=["import a"]
        )
        is None
    )
    assert nc.select_poison_target([], target_texts=[], src_texts=[], suite_texts=[]) is None


def test_poison_module_and_env_poison_conftest_texts():
    assert nc.poison_module("x = 1\n").startswith(nc.REGRESSION_POISON + "\n")
    text = nc.env_poison_conftest("pkg.mod", "pkg/mod.py", "def f():\n    return 1\n")
    compile(text, "conftest.py", "exec")
    assert "import pkg.mod as _poisoned" in text and "NEGCTRL_ENV_POISON" in text
    assert "exec(compile(_gold, 'pkg/mod.py'" in text


def test_module_name_for_honours_pythonpath_suffix():
    cfg = RepoConfig(name="r", language=Language.PYTHON, test_prefix="tests/")
    assert nc.module_name_for("pkg/mod.py", cfg) == "pkg.mod"
    assert nc.module_name_for("pkg/__init__.py", cfg) == "pkg"
    src_cfg = RepoConfig(
        name="r",
        language=Language.PYTHON,
        test_prefix="tests/",
        runner_opts={"pythonpath_suffix": ":src"},
    )
    assert nc.module_name_for("src/pkg/mod.py", src_cfg) == "pkg.mod"
    assert nc.module_name_for("other/mod.py", src_cfg) == "other.mod"


def test_regression_control_on_target_only_belt_names_the_config_weakness() -> None:
    """With belt_scope=TARGET_ONLY belt 3 re-runs only the target tests, so the regression
    control's poisoned neighbour is invisible: that is a VIOLATION (the gate fails, the
    cells cannot be trusted) whose note tells the operator to widen the belt — measured on
    pallets/click during the walkthrough."""
    from crb.core.oracle import controls as c

    assert c.REGRESSION in c.EXPECTED and c.OBS_REGRESSED in c.EXPECTED[c.REGRESSION]
    # OBS_RED on the regression control is 'not constructible' (poison broke the target),
    # never a violation: the grader credited nothing.
    assert c.OBS_RED not in c.EXPECTED[c.REGRESSION]


# --- language dispatch (ADR-0010): python keeps the AST path; go/js are text; jvm/rust honest --
def test_language_dispatch_refuses_jvm_and_rust_honestly(fixture_repo, fix_task, scratch, harness):
    """A language with no transform yet must read ``not_constructible`` with the reason —
    never a violation, never silently graded with the Python transforms."""
    from crb.core.spec import Language

    for lang, runner in ((Language.JVM, "maven"), (Language.RUST, "cargo")):
        config = RepoConfig(name="other", language=lang, runner=runner)
        with Workspace.create(
            fixture_repo.git, fix_task.task_id, scratch / f"dispatch-{lang.value}", config=config
        ) as ws:
            ws.overlay_tests(fix_task.test_files)
            for control in (nc.STUB, nc.REGRESSION, nc.HARDCODE_CHEAT, nc.ENV_POISON):
                with pytest.raises(nc.NOT_CONSTRUCTIBLE_ERRORS) as ei:
                    nc._apply_control(
                        control,
                        ws,
                        fix_task,
                        config,
                        runner=harness["runner"],
                        executor=harness["executor"],
                    )
                assert f"no transform for {lang.value} yet" in str(ei.value)
                assert "python, go, javascript" in str(ei.value)
            # the language-agnostic controls still work on any language
            assert (
                nc._apply_control(
                    nc.NOOP,
                    ws,
                    fix_task,
                    config,
                    runner=harness["runner"],
                    executor=harness["executor"],
                )
                == ""
            )


def test_caught_and_escape_notes_name_the_belt_and_the_meaning(control_matrix):
    """A reader must see WHICH belt caught a measurement control, and an env_poison
    escape must read as a belt-1 gap (review §4.3), not as weak repository tests."""
    from crb.core.spec import Language

    py = fixture_config()
    assert "belt-1 coverage gap" in nc._escape_note(nc.ENV_POISON, py)
    assert "NOT a weakness of the repository's tests" in nc._escape_note(nc.ENV_POISON, py)
    go = RepoConfig(name="g", language=Language.GO)
    assert "Go init()" in nc._escape_note(nc.ENV_POISON, go)
    assert "lookup" in nc._escape_note(nc.HARDCODE_CHEAT, py)
    caught = control_matrix[nc.ENV_POISON].note
    assert (
        caught.startswith("caught by belt 1: test infrastructure modified")
        and "conftest.py" in caught
    )
    guard = nc.TamperGuard.__new__(nc.TamperGuard)
    guard.tamper_note = ""
    dq = _gr(disqualified=True, dq_reason="test infrastructure modified: jest.config.js")
    assert nc._caught_note(nc.OBS_DISQUALIFIED, guard, dq) == (
        "caught by belt 1: test infrastructure modified: jest.config.js"
    )
    assert nc._caught_note(nc.OBS_REGRESSED, guard, dq).startswith("caught by belt 3")
    assert nc._caught_note(nc.OBS_RED, guard, dq).startswith("caught by belt 2")
    assert nc.CONTROLS_VERSION == "controls.v2"
    assert nc.TRANSFORM_LANGUAGES == (Language.PYTHON, Language.GO, Language.JAVASCRIPT)
