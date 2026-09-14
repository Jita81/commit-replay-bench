"""Negative controls for Go (ADR-0010): the four Python-only controls ported as pure
text transforms, unit-tested on inline source, then driven end to end through
``controls_for_task`` on the real ``go`` toolchain.

Unit tests need no toolchain. The end-to-end matrix runs only when ``go`` is on PATH
(``@pytest.mark.toolchain("go")``) and proves, per control, the expected verdict:

* :mod:`fixtures.langs.gorepo` (feat ADDS ``Sub``) — 6/7 constructible: ``env_poison``
  is honestly not (a plain ``func`` has no init-time hook); before this port it was
  4/7 [measured on the same fixture: stub / regression / hardcode_cheat / env_poison
  all ``not_constructible``].
* :mod:`fixtures.langs.negctrl.gorepo_funcvar` (feat CHANGES ``var Scale``) — 7/7
  constructible, including the ``init()`` re-assignment vector.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from crb.core.execution import LocalExecutor
from crb.core.git import GitRepo
from crb.core.mine import qualify
from crb.core.oracle import controls as nc
from crb.core.oracle import controls_go as g
from crb.core.runners import get_runner
from crb.core.spec import BELT_AFFECTED_DIRS, BELT_TARGET_ONLY, RepoConfig, TaskSpec

try:  # tests/ is a package only if the conftest owner made it one
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover — layout-dependent
    import conftest_langs as langs

gorepo = langs.fixture_module("gorepo")
funcvar = langs.fixture_module("negctrl.gorepo_funcvar")

# =============================================================================
# Unit: pure transforms over inline source (no toolchain)
# =============================================================================

PARENT = """package calc

import (
\t"fmt"
\t"strings"
)

type Opt struct{ N int }

// Add returns a + b.
func Add(a, b int) int { return a - b }

func (o *Opt) Name(prefix string) (string, error) {
\treturn fmt.Sprintf("%s%d", prefix, o.N), nil
}

func Same(x []string) string { return strings.Join(x, ",") }

var Scale = func(a int) int {
\treturn a
}
"""

GOLD = """package calc

import (
\t"fmt"
\t"strings"
\t"context"
)

type Opt struct{ N int }

// Add returns a + b.
func Add(a, b int) int { return a + b }

func (o *Opt) Name(prefix string) (string, error) {
\treturn fmt.Sprintf("%s-%d", prefix, o.N), nil
}

func Same(x []string) string { return strings.Join(x, ",") }

var Scale = func(a int) int {
\treturn a * 2
}

func Sub(ctx context.Context, a, b int) (n int, err error) {
\treturn a - b, nil
}

func Mul(a, b int) int { return a * b }
"""


def test_go_functions_finds_funcs_methods_and_func_vars():
    fns = g.go_functions(GOLD)
    assert list(fns) == ["Add", "Opt.Name", "Same", "Scale", "Sub", "Mul"]
    assert fns["Add"].kind == g.KIND_FUNC and fns["Add"].results == ("int",)
    assert [p.name for p in fns["Add"].params] == ["a", "b"]
    assert fns["Opt.Name"].kind == g.KIND_METHOD
    assert fns["Opt.Name"].results == ("string", "error")
    assert fns["Scale"].kind == g.KIND_VAR and fns["Scale"].signature == "func(a int) int"
    # named results resolve to their TYPES; grouped params take the next type
    assert fns["Sub"].results == ("int", "error")
    assert [(p.name, p.type) for p in fns["Sub"].params] == [
        ("ctx", "context.Context"),
        ("a", "int"),
        ("b", "int"),
    ]
    assert fns["Sub"].signature == "func Sub(ctx context.Context, a, b int) (n int, err error)"


def test_go_functions_ignores_literals_types_and_nested_funcs():
    src = (
        "package p\n\ntype F func(int) int\n\nvar h = map[string]func(){}\n\n"
        "func Outer() func() int {\n\tinner := func() int { return 1 }\n\treturn inner\n}\n"
    )
    fns = g.go_functions(src)
    assert list(fns) == ["Outer"]
    assert fns["Outer"].results == ("func() int",)


def test_zero_value_covers_every_type_shape():
    assert g.zero_value("int") == "0" and g.zero_value("float64") == "0"
    assert g.zero_value("string") == '""' and g.zero_value("bool") == "false"
    for t in ("error", "any", "*Opt", "[]byte", "map[string]int", "chan int", "func() error"):
        assert g.zero_value(t) == "nil", t
    # anything else is the language-defined zero value of T — always compiles
    assert g.zero_value("Opt") == "*new(Opt)"
    assert g.zero_value("[3]int") == "*new([3]int)"
    assert g.zero_value("T") == "*new(T)"


def test_stub_hollows_changed_bodies_appends_added_funcs_and_keeps_imports_compiling():
    stubbed = g.stub_changed_functions(PARENT, GOLD)
    assert stubbed is not None
    assert "func Add(a, b int) int {\n\treturn 0\n}" in stubbed
    assert 'return "", nil' in stubbed  # method with (string, error)
    assert "a - b" not in stubbed and "%s%d" not in stubbed  # changed bodies gone
    assert 'return strings.Join(x, ",")' in stubbed  # unchanged body kept
    assert "var Scale = func(a int) int {\n\treturn 0\n}" in stubbed  # func-var stubbed
    assert (
        "func Sub(ctx context.Context, a, b int) (n int, err error) {\n\treturn 0, nil\n}"
        in stubbed
    )
    assert "func Mul(a, b int) int {\n\treturn 0\n}" in stubbed
    assert '_ "fmt"' in stubbed  # fmt's only user was hollowed: blank-aliased, not left dangling
    assert '"strings"' in stubbed and '_ "strings"' not in stubbed  # still used
    assert 'import "context"' in stubbed  # needed by the appended Sub signature
    assert "panic(" not in stubbed  # never a panic: red for the right reason
    assert g.stub_changed_functions(PARENT, GOLD) == stubbed  # deterministic


def test_stub_on_new_file_takes_the_gold_package_clause():
    stubbed = g.stub_changed_functions(
        "", "package calc\n\nfunc Sub(a, b int) int { return a - b }\n"
    )
    assert stubbed == "package calc\n\nfunc Sub(a, b int) int {\n\treturn 0\n}\n"


def test_stub_nothing_to_do_and_unscannable():
    assert g.stub_changed_functions(PARENT, PARENT) is None
    with pytest.raises(g.NotConstructible, match="not scannable"):
        g.stub_changed_functions('package p\n\nfunc F() string { return "unterminated }\n', GOLD)


def test_blank_unused_imports_and_add_imports():
    src = 'package x\n\nimport (\n\t"fmt"\n\t"os"\n)\n\nfunc F() { fmt.Println() }\n'
    out = g.blank_unused_imports(src)
    assert '\t"fmt"\n' in out and '\t_ "os"\n' in out
    assert g.blank_unused_imports(out) == out
    added = g.add_imports(
        "package x\n\nfunc F() {}\n", [g.GoImport("yaml", "gopkg.in/yaml.v3", 0, 0)]
    )
    assert added.startswith('package x\n\nimport yaml "gopkg.in/yaml.v3"\n')
    assert g.GoImport("", "gopkg.in/yaml.v3", 0, 0).name == "yaml"
    assert g.GoImport("", "github.com/go-yaml/yaml", 0, 0).name == "yaml"
    assert g.GoImport("", "github.com/x/y/v2", 0, 0).name == "y"


TEST = """package calc

import (
\t"testing"

\t"github.com/stretchr/testify/assert"
)

func TestAll(t *testing.T) {
\tif got := Add(1, 2); got != 3 {
\t\tt.Fatalf("Add(1, 2) = %d, want 3", got)
\t}
\tif Mul(2, 3) != 6 {
\t\tt.Fatal("mul")
\t}
\tif 4 != Scale(2) {
\t\tt.Fatal("scale")
\t}
\tassert.Equal(t, -1, Sub(nil, 1, 2))
\tassert.Equal(t, Mul(3, 3), 9, "msg")
\tassert.True(t, IsOk("x"))
\tx := 3
\tassert.Equal(t, x, Add(1, 2))
\tfor _, tc := range []struct{ a, b, want int }{{1, 2, 3}} {
\t\tif got := Add(tc.a, tc.b); got != tc.want {
\t\t\tt.Fatal()
\t\t}
\t}
}
"""


def test_extract_literal_asserts_shapes_and_narrowness():
    assert g.extract_literal_asserts(TEST) == [
        ("Add", ("1", "2"), "3"),  # if got := f(x); got != want
        ("Mul", ("2", "3"), "6"),  # if f(x) != want
        ("Scale", ("2",), "4"),  # if want != f(x)
        ("Sub", ("nil", "1", "2"), "-1"),  # testify Equal(t, want, got), negative literal
        ("Mul", ("3", "3"), "9"),  # testify Equal(t, got, want, msg)
        ("IsOk", ('"x"',), "true"),  # testify True
    ]
    # a variable expectation and a table-driven loop yield nothing: narrowness is the point
    assert ("Add", ("x",), "3") not in g.extract_literal_asserts(TEST)
    assert g.extract_literal_asserts('package p\nfunc T() { s := "open }\n') == []


def test_build_hardcode_cheat_guards_existing_and_appends_missing_with_gold_signature():
    facts = g.extract_literal_asserts(TEST)
    cheat = g.build_hardcode_cheat(PARENT, GOLD, facts)
    assert cheat is not None
    # one-line body: the guard goes on its own lines and the buggy body is KEPT
    assert (
        "func Add(a, b int) int {\n\tif a == 1 && b == 2 {\n\t\treturn 3\n\t}\n return a - b }"
        in cheat
    )
    assert "var Scale = func(a int) int {\n\tif a == 2 {\n\t\treturn 4\n\t}\n\treturn a\n}" in cheat
    # Mul is missing in the parent: appended with the GOLD signature, guards, zero fallthrough
    assert (
        "func Mul(a, b int) int {\n\tif a == 2 && b == 3 {\n\t\treturn 6\n\t}\n"
        "\tif a == 3 && b == 3 {\n\t\treturn 9\n\t}\n\treturn 0\n}" in cheat
    )
    assert "a * b" not in cheat  # nothing implemented
    assert "IsOk" not in cheat  # named nowhere in parent or gold → no fact used
    # Sub has two results: `return -1` cannot be typed → the fact is dropped, not faked
    assert "func Sub" not in cheat


def test_build_hardcode_cheat_not_constructible_paths():
    assert g.build_hardcode_cheat(PARENT, GOLD, []) is None
    assert g.build_hardcode_cheat(PARENT, GOLD, [("Nope", ("1",), "2")]) is None
    with pytest.raises(g.NotConstructible, match="not scannable"):
        g.build_hardcode_cheat(
            'package p\nfunc F() string { return "open }\n', GOLD, [("F", (), "1")]
        )


def test_env_poison_file_reassigns_changed_package_vars_only():
    text, names = g.env_poison_file(PARENT, GOLD)
    assert names == ("Scale",)
    assert text.startswith("package calc\n\n// negctrl-env-poison")
    assert "func init() {\n\tScale = func(a int) int {" in text and "a * 2" in text
    with pytest.raises(g.NotConstructible, match="no package-level variable"):
        g.env_poison_file(PARENT, PARENT)  # unchanged
    with pytest.raises(g.NotConstructible):
        g.env_poison_file("package calc\n", GOLD)  # parent declares nothing to re-assign


def test_package_vars_handles_single_and_grouped_declarations():
    src = 'package p\n\nvar A = 1\nvar (\n\tB = "x"\n\tC int\n\tD = func() int {\n\t\treturn 2\n\t}\n)\nvar E, F = 1, 2\n'
    vs = g.package_vars(src)
    assert vs["A"].rhs == "1" and vs["B"].rhs == '"x"' and vs["C"].rhs == ""
    assert vs["D"].rhs == "func() int {\n\t\treturn 2\n\t}"


def test_select_adjacent_package_respects_belt_scope_targets_and_import_reachability():
    files = [
        "go.mod",
        "calc/calc.go",
        "calc/calc_test.go",
        "util/util.go",
        "util/util_test.go",
        "notest/x.go",
        "dep/dep.go",
        "dep/dep_test.go",
    ]
    texts = {
        "calc/calc.go": 'package calc\n\nimport "example.com/m/dep"\n\nfunc A() { dep.X() }\n',
        "util/util.go": "package util\n",
        "dep/dep.go": "package dep\n\nfunc X() {}\n",
        "notest/x.go": "package notest\n",
    }
    kw = {"texts": texts, "module": "example.com/m", "target_dirs": {"calc"}}
    assert g.select_adjacent_package(files, belt_scope=(), **kw) == "util"  # dep is reachable
    assert g.select_adjacent_package(files, belt_scope=("./calc",), **kw) is None
    assert g.select_adjacent_package(files, belt_scope=("./util", "./dep"), **kw) == "util"
    assert g.select_adjacent_package(files, belt_scope=("./notest",), **kw) is None  # no tests
    assert g.regression_poison_file("util") == (
        'package util\n\nfunc init() { panic("negctrl-regression-poison") }\n'
    )


def test_scope_dirs_forms():
    dirs = {"", "calc", "util", "util/sub", "doc"}
    m = "example.com/m"
    assert g.scope_dirs((), dirs, module=m) == dirs
    assert g.scope_dirs(("./calc",), dirs, module=m) == {"calc"}
    assert g.scope_dirs(("./util/...",), dirs, module=m) == {"util", "util/sub"}
    assert g.scope_dirs(("example.com/m/doc", "./"), dirs, module=m) == {"", "doc"}
    assert g.scope_dirs(("./...",), dirs, module=m) == dirs


# =============================================================================
# End to end: every control through controls_for_task on the real toolchain
# =============================================================================


def _task(repo: GitRepo, config: RepoConfig, feat_sha: str, scratch: Path) -> TaskSpec:
    cand = langs.feat_candidate(repo, config, feat_sha)
    out = qualify(
        repo, config, cand, runner=get_runner(config), executor=LocalExecutor(), scratch=scratch
    )
    assert out.task is not None, out.skipped_reason
    return out.task


def _matrix(repo, task, config, scratch, controls=nc.CONTROLS) -> dict[str, nc.ControlRow]:
    rows = nc.controls_for_task(
        repo,
        task,
        config=config,
        runner=get_runner(config),
        executor=LocalExecutor(),
        scratch=scratch,
        controls=controls,
    )
    return {r.control: r for r in rows}


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory):
    root, sha = gorepo.build(tmp_path_factory.mktemp("go"))
    config = gorepo.config()
    repo = GitRepo(root)
    scratch = tmp_path_factory.mktemp("scratch")
    return repo, _task(repo, config, sha, scratch / "mine"), config, scratch


@pytest.fixture(scope="module")
def base_matrix(base):
    repo, task, config, scratch = base
    return _matrix(repo, task, config, scratch)


@pytest.fixture(scope="module")
def fv(tmp_path_factory: pytest.TempPathFactory):
    root, sha = funcvar.build(tmp_path_factory.mktemp("gofv"))
    config = funcvar.config()
    repo = GitRepo(root)
    scratch = tmp_path_factory.mktemp("scratch")
    return repo, _task(repo, config, sha, scratch / "mine"), config, scratch


@pytest.fixture(scope="module")
def fv_matrix(fv):
    repo, task, config, scratch = fv
    return _matrix(repo, task, config, scratch)


@pytest.mark.toolchain("go")
@pytest.mark.skipif(not langs.has_tool("go"), reason="go not on PATH")
class TestGoFixtureMatrix:
    """gorepo: the feat commit ADDS ``Sub``. 6/7 constructible (was 4/7)."""

    def test_only_env_poison_is_not_constructible(self, base_matrix):
        nc_rows = [c for c, r in base_matrix.items() if r.verdict == nc.VERDICT_NOT_CONSTRUCTIBLE]
        assert nc_rows == [nc.ENV_POISON]
        assert "does not exist at the parent" in base_matrix[nc.ENV_POISON].note
        assert not any(r.verdict == nc.VERDICT_VIOLATION for r in base_matrix.values())

    def test_gold_noop_tamper(self, base_matrix):
        assert base_matrix[nc.GOLD].observed == nc.OBS_CLEAN
        assert base_matrix[nc.NOOP].observed == nc.OBS_RED
        assert base_matrix[nc.TEST_TAMPER].observed == nc.OBS_DISQUALIFIED

    def test_stub_goes_red_on_an_assertion_not_a_build_failure(self, base_matrix):
        row = base_matrix[nc.STUB]
        assert row.observed == nc.OBS_RED and row.verdict == nc.VERDICT_OK
        assert "compiled" in row.note
        g_ = row.grade
        assert g_ is not None and g_.target_run is not None
        assert g_.target_run.parse_error == ""  # it compiled — the failure is attributed
        assert g_.target_run.failing == frozenset({f"{gorepo.CALC_PKG}::TestSub"})

    def test_regression_poisons_the_adjacent_package_and_belt3_flags_it(self, base_matrix):
        row = base_matrix[nc.REGRESSION]
        assert row.observed == nc.OBS_REGRESSED and row.verdict == nc.VERDICT_OK
        assert "poisoned package ./util" in row.note
        g_ = row.grade
        assert g_ is not None and g_.belts.target_green is True
        assert g_.belts.no_new_failures is False
        assert "util/negctrl_regression_poison.go" in g_.changed_files

    def test_hardcode_cheat_is_a_measured_escape_like_python(self, base_matrix):
        row = base_matrix[nc.HARDCODE_CHEAT]
        assert row.observed == nc.OBS_CLEAN and row.verdict == nc.VERDICT_ESCAPE
        assert "1 literal fact(s) special-cased in calc/sub.go" in row.note

    def test_regression_not_constructible_under_target_only_names_the_scope(self, base):
        repo, _task_, _cfg, scratch = base
        for policy in (BELT_TARGET_ONLY, BELT_AFFECTED_DIRS):
            config = gorepo.config(policy)
            task = _task(repo, config, _task_.task_id, scratch / f"mine-{policy}")
            row = _matrix(repo, task, config, scratch, controls=(nc.REGRESSION,))[nc.REGRESSION]
            assert row.verdict == nc.VERDICT_NOT_CONSTRUCTIBLE
            assert f"belt_scope={policy}" in row.note and "can never construct" in row.note

    def test_regression_constructible_with_explicit_package_scope(self, base):
        repo, _task_, _cfg, scratch = base
        config = gorepo.config(("./calc", "./util"))
        task = _task(repo, config, _task_.task_id, scratch / "mine-explicit")
        row = _matrix(repo, task, config, scratch, controls=(nc.REGRESSION,))[nc.REGRESSION]
        assert row.observed == nc.OBS_REGRESSED and row.verdict == nc.VERDICT_OK


@pytest.mark.toolchain("go")
@pytest.mark.skipif(not langs.has_tool("go"), reason="go not on PATH")
class TestGoFuncVarMatrix:
    """gorepo_funcvar: the feat commit CHANGES ``var Scale``. 7/7 constructible."""

    def test_all_seven_constructible_no_violation(self, fv_matrix):
        assert [c for c, r in fv_matrix.items() if r.verdict == nc.VERDICT_NOT_CONSTRUCTIBLE] == []
        assert [c for c, r in fv_matrix.items() if r.verdict == nc.VERDICT_VIOLATION] == []
        assert list(fv_matrix) == list(nc.CONTROLS)

    def test_stub_hollows_the_func_var_body(self, fv_matrix):
        row = fv_matrix[nc.STUB]
        assert row.observed == nc.OBS_RED and row.verdict == nc.VERDICT_OK
        assert row.grade is not None and row.grade.target_run is not None
        assert row.grade.target_run.failing == frozenset({f"{funcvar.CALC_PKG}::TestScale"})

    def test_regression_and_gold(self, fv_matrix):
        assert fv_matrix[nc.GOLD].observed == nc.OBS_CLEAN
        assert fv_matrix[nc.REGRESSION].observed == nc.OBS_REGRESSED

    def test_hardcode_cheat_guards_the_func_var(self, fv_matrix):
        row = fv_matrix[nc.HARDCODE_CHEAT]
        assert row.verdict == nc.VERDICT_ESCAPE and "calc/scale.go" in row.note

    def test_env_poison_init_reassignment_is_built_and_measured(self, fv_matrix):
        """The vector exists (a new source file re-assigns Scale from init()); the graded
        file is byte-identical to the parent. Whether it grades clean (escape: no belt
        can tell a source-file init() from an implementation) or is caught, the row is
        never a violation and the note names what happened."""
        row = fv_matrix[nc.ENV_POISON]
        assert row.verdict in (nc.VERDICT_ESCAPE, nc.VERDICT_OK)
        assert "calc/negctrl_env_poison.go re-assigns Scale" in row.note
        assert "calc/scale.go left byte-identical" in row.note
        g_ = row.grade
        assert g_ is not None
        assert "calc/scale.go" not in g_.changed_files  # identity edit — really untouched
        assert "calc/negctrl_env_poison.go" in g_.changed_files
        if row.verdict == nc.VERDICT_ESCAPE:
            assert "Go init()" in row.note and "human reviewer" in row.note
        else:
            assert row.note.startswith("caught by belt")


@pytest.mark.toolchain("go")
@pytest.mark.skipif(not langs.has_tool("go"), reason="go not on PATH")
def test_report_apparatus_stamps_controls_v2(base):
    repo, task, config, scratch = base
    report = nc.run_controls(
        repo,
        [task],
        config=config,
        runner=get_runner(config),
        executor=LocalExecutor(),
        scratch=scratch,
        controls=(nc.GOLD, nc.STUB),
    )
    assert report.passed
    assert report.apparatus["controls_version"] == nc.CONTROLS_VERSION == "controls.v2"
    assert report.apparatus["runner"] == "go"
