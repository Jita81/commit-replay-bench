"""Negative controls for JavaScript (ADR-0010): the four Python-only controls ported as
pure text transforms, unit-tested on inline source, then driven end to end through
``controls_for_task`` on the four real runners (``node --test``, vitest, jest, mocha).

Unit tests need no toolchain. The end-to-end matrices run only when ``node`` is on
PATH (``@pytest.mark.toolchain("node")``); vitest / jest / mocha are installed once per
session by :func:`conftest_langs.npm_cache` (skipped with npm's reason when offline).

* :mod:`fixtures.langs.noderepo` (feat ADDS ``sub``) — 6/7 constructible per tool:
  ``env_poison`` is honestly not (nothing exists at the parent to pollute); before this
  port it was 4/7 [measured on the node flavour: stub / regression / hardcode_cheat /
  env_poison all ``not_constructible``].
* :mod:`fixtures.langs.negctrl.noderepo_fix` (feat FIXES ``mul``) — 7/7 constructible
  for jest / vitest / mocha through each runner's own collection-time hook; 6/7 for
  ``node --test``, which has no configuration file (``env_poison`` names that reason).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crb.core.execution import LocalExecutor
from crb.core.git import GitRepo
from crb.core.mine import qualify
from crb.core.oracle import controls as nc
from crb.core.oracle import controls_js as j
from crb.core.runners import get_runner
from crb.core.spec import BELT_TARGET_ONLY, RepoConfig, TaskSpec

try:  # tests/ is a package only if the conftest owner made it one
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover — layout-dependent
    import conftest_langs as langs

noderepo = langs.fixture_module("noderepo")
nodefix = langs.fixture_module("negctrl.noderepo_fix")

# =============================================================================
# Unit: pure transforms over inline source (no toolchain)
# =============================================================================

PARENT_CJS = """"use strict";

const helper = require("./helper");

function add(a, b) {
  return a - b;
}

const scale = (x, factor = 2) => {
  return x;
};

exports.norm = function (s) {
  return s.trim();
};

class Calc {
  constructor(base) {
    this.base = base;
  }
  async total(items) {
    return items.reduce((a, b) => a + b, this.base);
  }
  static of(v) { return new Calc(v); }
}

module.exports = { add, scale, Calc };
"""

GOLD_CJS = (
    PARENT_CJS.replace("return a - b;", "return a + b;")
    .replace("return x;", "return x * factor;")
    .replace(
        "module.exports = { add, scale, Calc };",
        "function mul(a, b) {\n  return a * b;\n}\n\nmodule.exports = { add, scale, Calc, mul };",
    )
)

GOLD_ESM = "export function sub(a, b) {\n  return a - b;\n}\n\nexport default function main() {\n  return 1;\n}\n"


def test_js_functions_finds_every_shape():
    fns = j.js_functions(GOLD_CJS)
    assert list(fns) == ["add", "scale", "norm", "Calc.constructor", "Calc.total", "Calc.of", "mul"]
    assert fns["add"].kind == j.KIND_FUNCTION and fns["add"].params == ("a", "b")
    assert fns["scale"].kind == j.KIND_ARROW and fns["scale"].params == ("x", "factor")
    assert fns["scale"].params_text == "x, factor = 2"
    assert fns["norm"].kind == j.KIND_FUNCTION  # anonymous expression named by its target
    assert fns["Calc.total"].kind == j.KIND_METHOD and fns["Calc.total"].async_
    esm = j.js_functions(GOLD_ESM)
    assert esm["sub"].exported and not esm["sub"].default_export
    assert esm["main"].exported and esm["main"].default_export


def test_js_functions_skips_control_flow_expression_arrows_and_unnamed_expressions():
    src = (
        "if (x) {\n  y();\n}\nwhile (a) { b(); }\nconst f = (a) => a + 1;\n"
        "setTimeout(function () { go(); }, 1);\nfor (const k of ks) { use(k); }\n"
    )
    assert j.js_functions(src) == {}


def test_stub_hollows_changed_units_and_appends_added_with_cjs_wiring():
    stubbed = j.stub_changed_functions(PARENT_CJS, GOLD_CJS)
    assert stubbed is not None
    assert "function add(a, b) {\n  return undefined;\n}" in stubbed
    assert "const scale = (x, factor = 2) => {\n  return undefined;\n};" in stubbed
    assert "return s.trim();" in stubbed  # unchanged unit kept
    assert "function mul(a, b) {\n  return undefined;\n}" in stubbed  # added → appended
    assert stubbed.rstrip().endswith("module.exports.mul = mul;")  # exported like the gold
    assert "a * b" not in stubbed
    assert j.stub_changed_functions(PARENT_CJS, GOLD_CJS) == stubbed


def test_stub_on_new_files_matches_the_gold_module_system():
    esm = j.stub_changed_functions("", GOLD_ESM)
    assert esm == (
        "export function sub(a, b) {\n  return undefined;\n}\n\n"
        "export default function main() {\n  return undefined;\n}\n"
    )
    cjs = j.stub_changed_functions(
        "",
        '"use strict";\n\nfunction sub(a, b) {\n  return a - b;\n}\n\nmodule.exports = { sub };\n',
    )
    assert cjs == (
        '"use strict";\n\nfunction sub(a, b) {\n  return undefined;\n}\n\nmodule.exports = { sub };\n'
    )


def test_stub_nothing_to_do_and_unscannable():
    assert j.stub_changed_functions(PARENT_CJS, PARENT_CJS) is None
    with pytest.raises(j.NotConstructible, match="not scannable"):
        j.stub_changed_functions('function f() { return "open; }\n', GOLD_CJS)


TEST = """"use strict";
const assert = require("node:assert/strict");
const { add, mul, scale } = require("../src/calc");

test("all", () => {
  expect(add(1, 2)).toBe(3);
  expect(mul(2, 3)).toEqual(6);
  expect(scale(-1)).toBe(-2);
  expect(add(x, 2)).toBe(3);
  expect(norm("  a ")).toStrictEqual("a");
  expect(list()).toEqual([1, "two", { three: 3, "four": [4] }]);
  assert.equal(add(3, 2), 5);
  assert.deepEqual([1], mul(1, 1));
  t.is(add(0, 0), 0);
  assert.equal(add(1, 2), add(2, 1));
  expect(add(1, 2)).toBeGreaterThan(2);
});
"""


def test_extract_literal_asserts_shapes_and_narrowness():
    assert j.extract_literal_asserts(TEST) == [
        ("add", ("1", "2"), "3"),
        ("mul", ("2", "3"), "6"),
        ("scale", ("-1",), "-2"),
        ("norm", ('"  a "',), '"a"'),
        ("list", (), '[1, "two", { three: 3, "four": [4] }]'),
        ("add", ("3", "2"), "5"),
        ("mul", ("1", "1"), "[1]"),
        ("add", ("0", "0"), "0"),
    ]
    assert j.extract_literal_asserts("const s = 'open;\n") == []


def test_build_hardcode_cheat_guards_existing_and_appends_missing():
    facts = j.extract_literal_asserts(TEST)
    cheat = j.build_hardcode_cheat(PARENT_CJS, GOLD_CJS, facts)
    assert cheat is not None
    assert (
        "function add(a, b) {\n  if (a === 1 && b === 2) {\n    return 3;\n  }\n"
        "  if (a === 3 && b === 2) {\n    return 5;\n  }\n  if (a === 0 && b === 0) {\n"
        "    return 0;\n  }\n  return a - b;\n}"
    ) in cheat  # buggy body KEPT below the guards
    assert "if (x === -1) {\n    return -2;\n  }" in cheat  # arrow unit guarded
    assert 'if (s === "  a ") {\n    return "a";\n  }' in cheat  # exports.norm guarded
    assert (
        "function mul(a, b) {\n  if (a === 2 && b === 3) {\n    return 6;\n  }\n"
        "  if (a === 1 && b === 1) {\n    return [1];\n  }\n  return undefined;\n}"
    ) in cheat  # missing in the parent: appended with the gold signature
    assert cheat.rstrip().endswith("module.exports.mul = mul;")
    assert "a * b" not in cheat and "list" not in cheat  # nothing implemented / unknown fn dropped


def test_build_hardcode_cheat_new_esm_file_and_not_constructible():
    cheat = j.build_hardcode_cheat("", GOLD_ESM, [("sub", ("3", "2"), "1")])
    assert (
        cheat
        == "export function sub(a, b) {\n  if (a === 3 && b === 2) {\n    return 1;\n  }\n  return undefined;\n}\n"
    )
    assert j.build_hardcode_cheat(PARENT_CJS, GOLD_CJS, []) is None
    assert j.build_hardcode_cheat(PARENT_CJS, GOLD_CJS, [("nope", ("1",), "2")]) is None


def test_js_imports_resolve_relative_specifiers_against_the_importer():
    assert j.js_imports(TEST, "__tests__/calc.test.js") == frozenset({"src/calc"})
    got = j.js_imports(
        'import { x } from "../src/calc.js";\nimport("./y")\n', "__tests__/a.test.js"
    )
    assert got == frozenset({"src/calc.js", "src/calc", "__tests__/y"})
    assert j.js_imports('require("lodash")', "a.js") == frozenset()  # bare specifiers ignored
    assert j.module_keys("src/index.js") == frozenset({"src/index.js", "src/index", "src"})


def test_select_poison_target_and_belt_test_files():
    pick = j.select_poison_target(
        ["src/calc.js", "src/helper.js", "src/other.js"],
        target_tests={"__tests__/sub.test.js": 'const { sub } = require("../src/sub");'},
        src_files={"src/sub.js": 'const h = require("./helper");'},  # transitively used
        belt_tests={
            "__tests__/calc.test.js": 'const { add } = require("../src/calc");',
            "__tests__/h.test.js": 'require("../src/helper")',
        },
    )
    assert pick == "src/calc.js"
    is_test = lambda p: p.startswith(("__tests__/", "test/"))  # noqa: E731
    files = ["__tests__/a.test.js", "__tests__/b.test.js", "src/x.js", "test/c.test.js"]
    assert j.belt_test_files(
        files, belt_scope=(), is_test=is_test, target_tests=["__tests__/a.test.js"]
    ) == ["__tests__/b.test.js", "test/c.test.js"]
    assert j.belt_test_files(
        files, belt_scope=("__tests__/",), is_test=is_test, target_tests=["__tests__/a.test.js"]
    ) == ["__tests__/b.test.js"]
    assert (
        j.belt_test_files(
            files,
            belt_scope=("__tests__/a.test.js",),
            is_test=is_test,
            target_tests=["__tests__/a.test.js"],
        )
        == []
    )
    assert j.poison_module('"use strict";\nx();\n').startswith(
        'throw new Error("negctrl-regression-poison");\n"use strict";'
    )


def test_env_poison_plan_per_tool():
    root = {"package.json": '{"name": "x"}'}
    with pytest.raises(j.NotConstructible, match="no configuration-file hook"):
        j.env_poison_plan("node", target="src/calc.js", gold_src=GOLD_CJS, root_files=root)
    files, note = j.env_poison_plan(
        "jest", target="src/calc.js", gold_src=GOLD_CJS, root_files=root
    )
    assert sorted(files) == [
        "jest.config.cjs",
        "negctrl_env_poison.cjs",
        "src/calc.negctrl_env_poison_gold.js",
    ]
    assert (
        "new jest.config.cjs" in note and files["src/calc.negctrl_env_poison_gold.js"] == GOLD_CJS
    )
    assert 'setupFiles: ["<rootDir>/negctrl_env_poison.cjs"]' in files["jest.config.cjs"]
    setup = files["negctrl_env_poison.cjs"]
    assert "require(target)" in setup and "Object.assign(real, fake)" in setup and "try {" in setup
    files, note = j.env_poison_plan(
        "mocha", target="src/calc.js", gold_src=GOLD_CJS, root_files=root
    )
    assert json.loads(files[".mocharc.json"]) == {"require": ["./negctrl_env_poison.cjs"]}
    files, note = j.env_poison_plan(
        "vitest", target="src/calc.js", gold_src=GOLD_CJS, root_files=root
    )
    assert sorted(files) == [
        "negctrl_env_poison.mjs",
        "src/calc.negctrl_env_poison_gold.js",
        "vitest.config.mjs",
    ]
    assert (
        'vi.mock("./src/calc.js", () => import("./src/calc.negctrl_env_poison_gold.js"));'
        in files["negctrl_env_poison.mjs"]
    )


def test_env_poison_plan_merges_json_configs_and_refuses_js_configs():
    files, note = j.env_poison_plan(
        "jest",
        target="src/calc.js",
        gold_src=GOLD_CJS,
        root_files={"package.json": '{"name": "x", "jest": {"setupFiles": ["./a.js"]}}'},
    )
    assert json.loads(files["package.json"])["jest"]["setupFiles"] == [
        "./a.js",
        "<rootDir>/negctrl_env_poison.cjs",
    ]
    assert "merged into package.json#jest" in note
    files, _ = j.env_poison_plan(
        "mocha",
        target="src/calc.js",
        gold_src=GOLD_CJS,
        root_files={".mocharc.json": '{"require": "./x.js"}'},
    )
    assert json.loads(files[".mocharc.json"])["require"] == ["./x.js", "./negctrl_env_poison.cjs"]
    for tool, cfg in (
        ("jest", "jest.config.js"),
        ("mocha", ".mocharc.yml"),
        ("vitest", "vite.config.ts"),
    ):
        with pytest.raises(j.NotConstructible, match="cannot be merged textually"):
            j.env_poison_plan(tool, target="src/calc.js", gold_src=GOLD_CJS, root_files={cfg: "x"})
    with pytest.raises(j.NotConstructible, match="not valid JSON"):
        j.env_poison_plan(
            "jest", target="src/calc.js", gold_src=GOLD_CJS, root_files={"package.json": "{"}
        )


def test_structurally_sound():
    assert j.structurally_sound("function f() { return `a${b}`; }")
    assert not j.structurally_sound("function f( { }")
    assert not j.structurally_sound('const s = "open;')


# =============================================================================
# End to end: every control through controls_for_task on the four real runners
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


@pytest.fixture(scope="module", params=noderepo.TOOLS)
def tool(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture(scope="module")
def node_modules(tool: str):
    return None if tool == "node" else langs.npm_cache(tool)


@pytest.fixture(scope="module")
def base(tool: str, node_modules, tmp_path_factory: pytest.TempPathFactory):
    root, sha = noderepo.build(tmp_path_factory.mktemp(tool), tool, node_modules=node_modules)
    config = noderepo.config(tool)
    repo = GitRepo(root)
    scratch = tmp_path_factory.mktemp("scratch")
    return repo, _task(repo, config, sha, scratch / "mine"), config, scratch


@pytest.fixture(scope="module")
def base_matrix(base):
    repo, task, config, scratch = base
    return _matrix(repo, task, config, scratch)


@pytest.fixture(scope="module")
def fix(tool: str, node_modules, tmp_path_factory: pytest.TempPathFactory):
    root, sha = nodefix.build(
        tmp_path_factory.mktemp(f"fix-{tool}"), tool, node_modules=node_modules
    )
    config = nodefix.config(tool)
    repo = GitRepo(root)
    scratch = tmp_path_factory.mktemp("scratch")
    return repo, _task(repo, config, sha, scratch / "mine"), config, scratch


@pytest.fixture(scope="module")
def fix_matrix(fix):
    repo, task, config, scratch = fix
    return _matrix(repo, task, config, scratch)


@pytest.mark.toolchain("node")
@pytest.mark.skipif(not langs.has_tool("node"), reason="node not on PATH")
class TestNodeFixtureMatrix:
    """noderepo: the feat commit ADDS ``sub``. 6/7 constructible per tool (was 4/7)."""

    def test_only_env_poison_is_not_constructible(self, base_matrix, tool):
        nc_rows = [c for c, r in base_matrix.items() if r.verdict == nc.VERDICT_NOT_CONSTRUCTIBLE]
        assert nc_rows == [nc.ENV_POISON], tool
        assert "does not exist at the parent" in base_matrix[nc.ENV_POISON].note
        assert not any(r.verdict == nc.VERDICT_VIOLATION for r in base_matrix.values())

    def test_gold_noop_tamper(self, base_matrix):
        assert base_matrix[nc.GOLD].observed == nc.OBS_CLEAN
        assert base_matrix[nc.NOOP].observed == nc.OBS_RED
        assert base_matrix[nc.TEST_TAMPER].observed == nc.OBS_DISQUALIFIED

    def test_stub_goes_red_on_an_assertion(self, base_matrix, tool):
        row = base_matrix[nc.STUB]
        assert row.observed == nc.OBS_RED and row.verdict == nc.VERDICT_OK
        assert "parsed" in row.note
        g_ = row.grade
        assert g_ is not None and g_.target_run is not None
        # the module loads (no syntax/import failure) and the ASSERTION fails
        assert g_.target_run.parse_error == ""
        assert g_.target_run.failing == frozenset({noderepo.SUB_TEST_ID})

    def test_regression_poisons_the_adjacent_module_and_belt3_flags_it(self, base_matrix, tool):
        row = base_matrix[nc.REGRESSION]
        assert row.observed == nc.OBS_REGRESSED and row.verdict == nc.VERDICT_OK
        assert f"poisoned {noderepo.SRC_ADD}" in row.note
        assert noderepo.test_add(tool) in row.note  # the belt test that loads it is named
        g_ = row.grade
        assert g_ is not None and g_.belts.target_green is True
        assert g_.belts.no_new_failures is False

    def test_hardcode_cheat_is_a_measured_escape_like_python(self, base_matrix):
        row = base_matrix[nc.HARDCODE_CHEAT]
        assert row.observed == nc.OBS_CLEAN and row.verdict == nc.VERDICT_ESCAPE
        assert f"1 literal fact(s) special-cased in {noderepo.SRC_SUB}" in row.note

    def test_regression_not_constructible_under_target_only_names_the_scope(self, base, tool):
        repo, _task_, _cfg, scratch = base
        config = noderepo.config(tool, BELT_TARGET_ONLY)
        task = _task(repo, config, _task_.task_id, scratch / "mine-target-only")
        row = _matrix(repo, task, config, scratch, controls=(nc.REGRESSION,))[nc.REGRESSION]
        assert row.verdict == nc.VERDICT_NOT_CONSTRUCTIBLE
        assert "TARGET_ONLY can never construct" in row.note


@pytest.mark.toolchain("node")
@pytest.mark.skipif(not langs.has_tool("node"), reason="node not on PATH")
class TestNodeFixMatrix:
    """noderepo_fix: the feat commit FIXES ``mul``. 7/7 for jest / vitest / mocha; node
    --test has no hook so env_poison is honestly not constructible there."""

    def test_no_violation_and_constructibility_per_tool(self, fix_matrix, tool):
        assert [c for c, r in fix_matrix.items() if r.verdict == nc.VERDICT_VIOLATION] == []
        nc_rows = [c for c, r in fix_matrix.items() if r.verdict == nc.VERDICT_NOT_CONSTRUCTIBLE]
        if tool == "node":
            assert nc_rows == [nc.ENV_POISON]
            assert "no configuration-file hook" in fix_matrix[nc.ENV_POISON].note
        else:
            assert nc_rows == []

    def test_stub_hollows_the_fixed_function(self, fix_matrix):
        row = fix_matrix[nc.STUB]
        assert row.observed == nc.OBS_RED and row.verdict == nc.VERDICT_OK
        assert row.grade is not None and row.grade.target_run is not None
        assert row.grade.target_run.failing == frozenset({nodefix.MUL_TEST_ID})

    def test_gold_regression_hardcode(self, fix_matrix):
        assert fix_matrix[nc.GOLD].observed == nc.OBS_CLEAN
        assert fix_matrix[nc.REGRESSION].observed == nc.OBS_REGRESSED
        row = fix_matrix[nc.HARDCODE_CHEAT]
        assert row.verdict == nc.VERDICT_ESCAPE and nodefix.SRC_MUL in row.note

    def test_env_poison_takes_effect_through_the_runner_hook(self, fix_matrix, tool):
        """The vector must actually flip the target: the graded ``src/mul.js`` is
        byte-identical to the parent and the green (or the DQ once belt 1 covers test
        infrastructure — workstream A1) comes from the hook. ``red`` here would mean the
        poison did NOT take effect, which is the one outcome that must not pass."""
        if tool == "node":
            pytest.skip("node --test has no collection-time hook (asserted above)")
        row = fix_matrix[nc.ENV_POISON]
        assert row.observed in (nc.OBS_CLEAN, nc.OBS_DISQUALIFIED), row.note
        assert f"{nodefix.SRC_MUL} left byte-identical" in row.note
        hook = {"jest": "jest.config.cjs", "mocha": ".mocharc.json", "vitest": "vitest.config.mjs"}[
            tool
        ]
        assert hook in row.note
        g_ = row.grade
        assert g_ is not None
        if row.observed == nc.OBS_CLEAN:
            assert row.verdict == nc.VERDICT_ESCAPE
            assert "belt-1 coverage gap" in row.note  # never "the repo's tests are weak"
            assert nodefix.SRC_MUL not in g_.changed_files
            assert hook in g_.changed_files
        else:
            assert row.verdict == nc.VERDICT_OK and row.note.startswith("caught by belt 1")
