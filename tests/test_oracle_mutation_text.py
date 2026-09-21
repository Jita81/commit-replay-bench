"""Tests for the C-family text mutator (``crb.core.oracle.mutators_text``) and its
wiring into the scorer (``uncompilable`` outcomes, registration, provenance).

Three layers:

1. **Pure** — the scanner (strings/comments/regex/templates/lifetimes are opaque;
   ``<=`` is one token), each operator on tiny per-language snippets, determinism
   (byte-identical reruns), boundedness (stable prefix), structural well-formedness,
   the operator table + hash, and registration in ``mutator_for``.
2. **Hermetic scoring** — a real git worktree on the Go fixture with a SCRIPTED runner
   (no toolchain): an unattributed build failure on a mutant is ``uncompilable`` and
   excluded from the denominator; on the baseline it stays ``unscoreable``; the
   source is restored byte-exact.
3. **End to end per language** (``@pytest.mark.toolchain``) — a richer feat commit
   whose target test exercises ONE path: the obvious mutants (``a - b`` → ``a + b``,
   the negated condition) are killed, the untested branch escapes, and — in the
   compiled languages — a deleted declaration is rejected by the toolchain and
   excluded, never counted as a kill.

Navigation
----------
What it is:   The C-family text mutator's test suite (``crb.core.oracle.mutators_text``) and its
              wiring into the scorer.
What it does: Pins the scanner (strings, comments, regex, template literals, lifetimes and raw
              strings are opaque; ``<=`` is one token), each operator on per-language snippets,
              confinement, determinism, boundedness, structural well-formedness, the operator
              table and hash, registration for Go / JavaScript / JVM / Rust (Python keeps the AST
              mutator); that an unattributed build failure on a mutant is ``uncompilable`` and
              leaves the denominator (never a kill) while on the baseline it stays
              ``unscoreable``; the mtime-ordered build-cache regression caught by the Maven
              end-to-end; and, per toolchain, that the obvious mutants die, the untested branch
              escapes and a deleted declaration is rejected by the compiler.
How:          Pure ``generate`` calls for layer 1; a scripted runner on the Go fixture for layer
              2; PATH-gated real toolchains on richer feat commits for layer 3.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0009-text-level-mutators.md
Works with:   src/crb/core/oracle/mutators_text.py (under test), src/crb/core/oracle/mutation.py
              (the scorer it registers with), tests/fixtures/langs/gorepo.py,
              tests/fixtures/langs/noderepo.py, tests/fixtures/langs/jvmrepo.py and
              tests/fixtures/langs/rustrepo.py (the per-language end-to-ends)
Tested by:    tests/test_oracle_mutation_text.py
Touch when:   a language is added to the text mutator (a scanner case for its literal syntax,
              an operator case per family, the registration case and an end-to-end); an operator
              is added (the table hash changes — an apparatus consequence).
"""

from __future__ import annotations

import importlib
import json
import time
from collections.abc import Mapping
from pathlib import Path

import pytest

from crb.core.execution import LocalExecutor
from crb.core.git import GitRepo
from crb.core.oracle import mutation as ms
from crb.core.oracle import mutators_text as mt
from crb.core.runners import get_runner
from crb.core.runners.base import TestRun as Run
from crb.core.spec import RepoConfig, TaskSpec
from crb.core.workspace import Workspace

try:  # tests/ is a package only if the conftest owner made it one
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover — layout-dependent
    import conftest_langs as langs

gorepo = langs.fixture_module("gorepo")
fixtures = importlib.import_module("fixtures.langs")  # the shared builders (on sys.path now)
noderepo = langs.fixture_module("noderepo")
jvmrepo = langs.fixture_module("jvmrepo")
rustrepo = langs.fixture_module("rustrepo")

ALL = set(range(1, 200))


def _gen(lang: str, src: str, lines: set[int] | None = None, **kw: int) -> list[ms.Mutant]:
    return mt.TextLineMutator(lang).generate(src, ALL if lines is None else lines, **kw)


def _line(m: ms.Mutant) -> str:
    return m.mutated_source.splitlines()[m.line - 1]


def _by_desc(mutants: list[ms.Mutant]) -> dict[str, ms.Mutant]:
    return {m.description: m for m in mutants}


# =============================================================================
# 1. the scanner
# =============================================================================


def _kinds(lang: str, src: str) -> list[tuple[str, str]]:
    return [(t.kind, t.text) for t in mt.tokenize(src, mt.PROFILES[lang])]


def test_strings_chars_and_comments_are_opaque_tokens():
    go = "x := \"a + b\" + '+' // c + d\n/* e\n+ f */ y := `g + h`\n"
    toks = _kinds("go", go)
    assert ("str", '"a + b"') in toks and ("str", "'+'") in toks
    assert ("comment", "// c + d") in toks and ("comment", "/* e\n+ f */") in toks
    assert ("str", "`g + h`") in toks
    # the ONLY operator-kind `+` is the real one between the literals
    assert [t for t in toks if t[0] == "op" and t[1] == "+"] == [("op", "+")]


def test_compound_operators_are_single_tokens():
    js = "a <= b; c >= d; e === f; g !== h; i => j; k ?? l; m?.n; o ** p; q++; r <<= 2;"
    ops = [t[1] for t in _kinds("javascript", js) if t[0] == "op"]
    assert ops == ["<=", ">=", "===", "!==", "=>", "??", "?.", "**", "++", "<<="]
    go = "ch <- v; x := y; z &^= w; a != b"
    assert [t[1] for t in _kinds("go", go) if t[0] == "op"] == ["<-", ":=", "&^=", "!="]
    rs = "a::b; c -> d; 0..5; 1..=2; e != f"
    assert [t[1] for t in _kinds("rust", rs) if t[0] == "op"] == ["::", "->", "..", "..=", "!="]


def test_js_regex_and_template_literals_are_opaque():
    js = "const re = /a+b/g; const t = `x ${a + 1} y`; const q = a / b / c;\n"
    toks = _kinds("javascript", js)
    assert ("str", "/a+b/g") in toks
    assert ("str", "`x ${a + 1} y`") in toks
    # `a / b / c` after an identifier is division, not a regex
    assert [t for t in toks if t == ("op", "/")] == [("op", "/"), ("op", "/")]
    assert not [t for t in toks if t[0] == "op" and t[1] == "+"]


def test_rust_lifetimes_chars_and_raw_strings():
    rs = "fn f<'a>(x: &'a str) -> char { let c = '\\''; let r = r#\"a + b\"#; let b = b\"q+\"; 'x' }\n"
    toks = _kinds("rust", rs)
    assert ("id", "'a") in toks  # a lifetime is an identifier-like token, never a literal
    assert ("str", "'\\''") in toks and ("str", "'x'") in toks
    assert ("str", 'r#"a + b"#') in toks and ("str", 'b"q+"') in toks
    assert not [t for t in toks if t[0] == "op" and t[1] == "+"]
    nested = "/* a /* b */ c */ x + 1\n"
    assert ("comment", "/* a /* b */ c */") in _kinds("rust", nested)


def test_java_text_blocks_and_numbers():
    java = 'String s = """\n  a + b\n  """; long n = 1_000L; float f = .5f; int h = 0xFF;\n'
    toks = _kinds("jvm", java)
    assert ("str", '"""\n  a + b\n  """') in toks
    assert ("num", "1_000L") in toks and ("num", ".5f") in toks and ("num", "0xFF") in toks


def test_unterminated_literal_is_unscannable_and_yields_no_mutants():
    with pytest.raises(mt.ScanError):
        mt.tokenize('x = "open\n', mt.PROFILES["javascript"])
    assert _gen("javascript", 'x = "open + 1\n') == []
    assert _gen("go", "/* never closed\n x := 1 + 2\n") == []


def test_brackets_balanced():
    ok = mt.tokenize("f(a[1], {b: (c)})", mt.PROFILES["javascript"])
    assert mt.brackets_balanced(ok)
    assert not mt.brackets_balanced(mt.tokenize("f(a]", mt.PROFILES["javascript"]))
    assert not mt.brackets_balanced(mt.tokenize("f(a", mt.PROFILES["javascript"]))


# =============================================================================
# 1b. each operator, per language
# =============================================================================


def test_arith_flip_binary_only_and_not_in_literals():
    go = 'x := a - b*c + "p - q" // r + s\n'
    got = _by_desc(_gen("go", go))
    assert _line(got["- -> +"]) == 'x := a + b*c + "p - q" // r + s'
    assert _line(got["* -> /"]) == 'x := a - b/c + "p - q" // r + s'
    assert _line(got["+ -> -"]) == 'x := a - b*c - "p - q" // r + s'
    # unary minus and a pointer/deref star are not binary operators
    assert not [m for m in _gen("go", "y := -1\n") if m.op == "arith_flip"]
    assert not [m for m in _gen("rust", "let p = *q;\n") if m.op == "arith_flip"]
    assert not [m for m in _gen("javascript", "return -x;\n") if m.op == "arith_flip"]


def test_cmp_flip_including_js_strict_equality_and_spaced_generics_rule():
    js = "if (a === b || c !== d || e == f || g != h) {}\n"
    descs = {m.description for m in _gen("javascript", js) if m.op == "cmp_flip"}
    assert descs == {"=== -> !==", "!== -> ===", "== -> !=", "!= -> =="}
    java = "List<String> xs = f(); if (a < b && c >= d) {}\n"
    descs = {m.description for m in _gen("jvm", java) if m.op == "cmp_flip"}
    assert descs == {"< -> <=", ">= -> >"}  # List<String> is a generic, not a comparison
    rs = "let v: Vec<i32> = vec![]; if a > b {}\n"
    assert {m.description for m in _gen("rust", rs) if m.op == "cmp_flip"} == {"> -> >="}


def test_bool_flip_and_or_literals_and_negation_drop():
    go = "ok := a && !b || true\n"
    got = _by_desc(_gen("go", go))
    assert _line(got["&& -> ||"]) == "ok := a || !b || true"
    assert _line(got["|| -> &&"]) == "ok := a && !b && true"
    assert _line(got["true -> false"]) == "ok := a && !b || false"
    assert _line(got["!x -> x"]) == "ok := a && b || true"
    # `!=` is never a negation, a Rust macro bang is never dropped, a closure `||` is not an `or`
    assert not [m for m in _gen("go", "if a != b {\n}\n") if m.description == "!x -> x"]
    rs = 'let x = v.unwrap_or_else(|| 0); println!("{}", x);\n'
    assert not [m for m in _gen("rust", rs) if m.op == "bool_flip"]
    # TS non-null assertion `x!` is postfix, never dropped
    assert not [m for m in _gen("javascript", "const y = x!.z;\n") if m.op == "bool_flip"]


def test_negate_cond_braces_and_parens_families():
    go = "if err := f(); err != nil {\n}\n"
    got = _by_desc(_gen("go", go))
    assert _line(got["if cond -> if !(cond)"]) == "if err := f(); !(err != nil) {"
    rs = "if let Some(v) = o {\n}\nif a > b {\n}\n"
    ms_rs = [m for m in _gen("rust", rs) if m.op == "negate_cond"]
    assert [(m.line, _line(m)) for m in ms_rs] == [(3, "if !(a > b) {")]  # `if let` skipped
    js = "if (a && (b || c)) {\n}\n"
    (m,) = [m for m in _gen("javascript", js) if m.op == "negate_cond"]
    assert _line(m) == "if (!(a && (b || c))) {"
    java = "} else if (x.isEmpty()) {\n"
    (m,) = [m for m in _gen("jvm", java) if m.op == "negate_cond"]
    assert _line(m) == "} else if (!(x.isEmpty())) {"


def test_off_by_one_on_integer_literals_only():
    java = "int a = 5; long b = 10L; double c = 1.5; int d = 0x10; int e = 1_000; int f = 07;\n"
    descs = {m.description for m in _gen("jvm", java) if m.op == "off_by_one"}
    assert descs == {"5 -> 6", "10L -> 11L"}
    rs = "let a = 5u32; let b = 1e3; let c = 0;\n"
    descs = {m.description for m in _gen("rust", rs) if m.op == "off_by_one"}
    assert descs == {"5u32 -> 6u32", "0 -> 1"}
    js = "const a = 7n; const b = arr[0];\n"
    descs = {m.description for m in _gen("javascript", js) if m.op == "off_by_one"}
    assert descs == {"7n -> 8n", "0 -> 1"}
    # a literal inside a string is never a literal
    assert not [m for m in _gen("go", 'x := "v1"\n') if m.op == "off_by_one"]


def test_return_value_only_when_obviously_typable():
    src = "return true;\nreturn 3;\nreturn null;\nreturn a - b;\nreturn nil\nreturn undefined;\n"
    got = [m for m in _gen("javascript", src) if m.op == "return_value"]
    assert [(m.line, m.description) for m in got] == [
        (1, "return true -> return false"),
        (2, "return 3 -> return 4"),
    ]
    go = "func f() (int, error) {\n\treturn 0, nil\n}\n"
    assert not [m for m in _gen("go", go) if m.op == "return_value"]  # multi-value: skipped
    java = "return false;\n"
    (m,) = [m for m in _gen("jvm", java) if m.op == "return_value"]
    assert _line(m) == "return true;"


def test_delete_stmt_only_single_line_statements():
    js = (
        '"use strict";\n'
        "import x from 'y';\n"
        "function f(a) {\n"
        "  const d = a - 1;\n"
        "  foo(\n"
        "    d,\n"
        "  );\n"
        "  return d;\n"
        "}\n"
        "module.exports = { f };\n"
    )
    dels = [m for m in _gen("javascript", js) if m.op == "delete_stmt"]
    assert [m.line for m in dels] == [4, 8]  # directive, import, block lines, split call: never
    assert _line(dels[0]) == "" and dels[0].mutated_source.count("\n") == js.count("\n")
    go = 'package calc\n\nimport "fmt"\n\nfunc f() {\n\tx := 1\n\tfmt.Println(x,\n\t\t2)\n\treturn\n}\n'
    assert [m.line for m in _gen("go", go) if m.op == "delete_stmt"] == [6, 9]
    rs = "use std::fmt;\npub mod sub;\n#[derive(Debug)]\nfn f() {\n    let a = 1;\n    a\n}\n"
    assert [m.line for m in _gen("rust", rs) if m.op == "delete_stmt"] == [5]
    java = "@Override\npublic int f() {\n    int a = 1;\n    return a;\n}\n"
    assert [m.line for m in _gen("jvm", java) if m.op == "delete_stmt"] == [3, 4]


def test_confined_to_exactly_the_changed_lines():
    go = "package calc\n\nfunc F(a, b int) int {\n\tif a < b {\n\t\treturn a + b\n\t}\n\treturn a - b\n}\n"
    only = _gen("go", go, {7})
    assert only and {m.line for m in only} == {7}
    assert {m.description for m in only} == {"- -> +", "statement deleted"}
    assert _gen("go", go, {2}) == []  # a blank line yields nothing


# =============================================================================
# 1c. determinism, boundedness, well-formedness, the table + hash, registration
# =============================================================================

_RICH_GO = (
    "package calc\n\n"
    "func Clamp(a, b int, floor bool) int {\n"
    "\td := a - b\n"
    "\tif floor && d < 0 {\n"
    "\t\treturn 0\n"
    "\t}\n"
    "\treturn d\n"
    "}\n"
)


def test_two_runs_are_byte_identical():
    a = _gen("go", _RICH_GO, max_mutants=100)
    b = _gen("go", _RICH_GO, max_mutants=100)
    assert [(m.mutant_id, m.mutated_source) for m in a] == [
        (m.mutant_id, m.mutated_source) for m in b
    ]
    assert a and {m.op for m in a} <= set(mt.TEXT_OPERATORS)
    assert all(m.mutated_source != _RICH_GO for m in a)
    assert len({m.mutated_source for m in a}) == len(a)  # deduped by content


def test_max_mutants_bounds_to_a_stable_prefix():
    full = _gen("go", _RICH_GO, max_mutants=100)
    assert len(full) > 3
    bounded = _gen("go", _RICH_GO, max_mutants=3)
    assert [(m.mutant_id, m.mutated_source) for m in bounded] == [
        (m.mutant_id, m.mutated_source) for m in full[:3]
    ]
    assert _gen("go", _RICH_GO, max_mutants=0) == []
    assert [m.mutant_id for m in full][:2] == ["m01_delete_stmt_L4", "m02_arith_flip_L4"]


def test_every_mutant_is_structurally_well_formed():
    for lang, src in (
        ("go", _RICH_GO),
        (
            "javascript",
            'function f(a) {\n  if (a > 1 && !x) { return `${a + 1}`; }\n  return "s+t";\n}\n',
        ),
        (
            "jvm",
            "class A {\n    int f(int a) {\n        if (a > 1 && !x) { return 0; }\n        return a - 1;\n    }\n}\n",
        ),
        ("rust", "pub fn f(a: i64) -> i64 {\n    if a > 1 && !x { return 0; }\n    a - 1\n}\n"),
    ):
        prof = mt.PROFILES[lang]
        mutants = _gen(lang, src, max_mutants=100)
        assert mutants, lang
        for m in mutants:
            assert mt.brackets_balanced(mt.tokenize(m.mutated_source, prof)), (lang, m)


def test_operator_table_shares_the_ast_taxonomy():
    assert mt.TEXT_OPERATORS == (
        "cmp_flip",
        "arith_flip",
        "bool_flip",
        "negate_cond",
        "off_by_one",
        "return_value",
        "delete_stmt",
    )
    # the five shared names carry the same ranks as the AST table
    ast_ranks = {o["op"]: o["rank"] for o in ms.PythonAstMutator().describe()["operators"]}
    text_ranks = {o["op"]: o["rank"] for o in mt.TextLineMutator("go").describe()["operators"]}
    for op in ("cmp_flip", "arith_flip", "bool_flip", "negate_cond", "off_by_one"):
        assert ast_ranks[op] == text_ranks[op]
    ops = {m.op for m in _gen("go", _RICH_GO, max_mutants=100)}
    assert ops == set(mt.TEXT_OPERATORS)


def test_operator_set_hash_covers_the_text_table_and_differs_per_language():
    hashes = {lang: ms.operator_set_hash(mt.TextLineMutator(lang)) for lang in mt.TEXT_LANGUAGES}
    assert len(set(hashes.values())) == len(mt.TEXT_LANGUAGES)
    assert all(len(h) == 64 for h in hashes.values())
    assert ms.operator_set_hash(mt.TextLineMutator("go")) == hashes["go"]  # stable
    assert hashes["go"] != ms.operator_set_hash(ms.PythonAstMutator())
    desc = mt.TextLineMutator("rust").describe()
    assert desc["family"] == "text" and desc["version"] == mt.TEXT_MUTATION_VERSION
    assert "- -> +" in desc["arith_flips"] and "< -> <=" in desc["cmp_flips"]
    assert "!x -> x" not in desc["bool_flips"] and "true -> false" in desc["bool_flips"]
    assert desc["profile"]["language"] == "rust" and desc["profile"]["semicolons"] is True
    assert ms.PythonAstMutator().describe()["family"] == "ast"


def test_registered_for_the_four_languages_and_python_keeps_the_ast_mutator():
    for lang, suffix in (("go", "a.go"), ("javascript", "a.ts"), ("jvm", "A.kt"), ("rust", "a.rs")):
        m = ms.mutator_for(lang)
        assert isinstance(m, mt.TextLineMutator) and m.language == lang
        assert m.accepts(suffix) and not m.accepts("a.py")
        assert ms.mutator_family(m) == "text"
    assert isinstance(ms.mutator_for("python"), ms.PythonAstMutator)
    assert ms.mutator_family(ms.mutator_for("python")) == "ast"
    assert ms.mutator_for("cobol") is None
    assert ms.MUTATOR_FAMILIES == ("ast", "text")
    with pytest.raises(ValueError):
        mt.TextLineMutator("cobol")


# =============================================================================
# 2. hermetic scoring: uncompilable vs unscoreable (scripted runner, no toolchain)
# =============================================================================


def test_compile_failure_rule():
    unattributed = Run(2, frozenset(), "build failed", parse_error="unattributed failure (rc=2)")
    assert ms.compile_failure(unattributed)
    attributed = Run(1, frozenset({"pkg::TestSub"}), "--- FAIL: TestSub")
    assert not ms.compile_failure(attributed)
    assert not ms.compile_failure(Run(0, frozenset()))  # green
    assert not ms.compile_failure(Run(124, frozenset(), "", True))  # timeout = a kill
    # parse_error on a green exit is not a compile failure either (fail-closed elsewhere)
    assert not ms.compile_failure(Run(0, frozenset(), parse_error="junit parse error"))


class _StubRunner:
    """A runner whose verdicts are scripted: first the baseline, then one per mutant."""

    name = "stub"

    def __init__(self, runs):
        self._runs = list(runs)
        self.calls = 0

    def run_for(self, executor, root, scope, *, timeout=0, authored=None):
        return self.run(executor, root, scope, timeout=timeout)

    def run(self, executor, root, scope, *, timeout=0):
        self.calls += 1
        item = self._runs.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


GREEN = Run(0, frozenset())
KILLED = Run(1, frozenset({"example.com/m/calc::TestSub"}), "--- FAIL: TestSub")
BUILD_FAILED = Run(
    1, frozenset(), "FAIL\texample.com/m/calc [build failed]", parse_error="unattributed failure"
)


@pytest.fixture(scope="module")
def go_fixture(tmp_path_factory) -> tuple[GitRepo, str]:
    """The Go fixture as ``(repo, feat_sha)`` for the hermetic scoring layer (no toolchain runs)."""
    root, feat_sha = gorepo.build(tmp_path_factory.mktemp("go-hermetic"))
    return GitRepo(root), feat_sha


def _go_task(feat_sha: str) -> TaskSpec:
    return TaskSpec(
        task_id=feat_sha,
        repo="gofix",
        subject=fixtures.FEAT_SUBJECT,
        authored="2026-01-01T00:00:00+00:00",
        test_files=(gorepo.TEST_SUB,),
        src_files=(gorepo.SRC_SUB,),
        target_tests=("./calc",),
        belt_scope=(),
        language="go",
    )


def test_uncompilable_mutant_is_excluded_from_the_denominator(go_fixture, tmp_path):
    repo, feat_sha = go_fixture
    task = _go_task(feat_sha)
    ws = Workspace.create(repo, feat_sha, tmp_path / "ws", config=gorepo.config())
    try:
        ws.overlay_tests(task.test_files)
        ws.overlay_sources(task.src_files)
        original = (ws.root / gorepo.SRC_SUB).read_bytes()
        lines = {4}  # `func Sub(a, b int) int { return a - b }`
        n = len(ms.mutator_for("go").generate(original.decode(), lines, max_mutants=20))
        assert n == 1  # the `- -> +` flip; the one-line body is a block line (no deletion)
        # script: baseline GREEN, then the one mutant is a build failure
        runner = _StubRunner([GREEN, BUILD_FAILED])
        score = ms.score_task(
            ws,
            task,
            config=gorepo.config(),
            runner=runner,
            executor=LocalExecutor(),
            changed_lines={gorepo.SRC_SUB: lines},
        )
        assert score.total == 0 and score.killed == 0 and score.errors == 0
        assert score.uncompilable == 1 and score.oracle_strength is None
        assert not score.scoreable and "uncompilable=1" in score.note
        (o,) = score.outcomes
        assert o.status == "uncompilable" and o.uncompilable and o.killed is None
        assert "unattributed" in o.error and "[build failed]" in o.tail
        assert o.diff and "+" in o.diff
        assert (ws.root / gorepo.SRC_SUB).read_bytes() == original  # restored byte-exact
        assert score.provenance.mutator_family == "text"
        assert score.provenance.mutator == "TextLineMutator" and score.provenance.language == "go"
        assert score.provenance.operator_set_hash == ms.operator_set_hash(mt.TextLineMutator("go"))
        assert (
            score.to_dict()["uncompilable"] == 1 and score.to_dict()["outcomes"][0]["uncompilable"]
        )
        assert ms.aggregate_by_cell([score]) == {}  # unscoreable never enters a cell
    finally:
        ws.remove()


def test_mixed_outcomes_count_only_graded_mutants(go_fixture, tmp_path):
    """killed + escaped form the denominator; uncompilable and harness errors do not."""
    repo, feat_sha = go_fixture
    src = _RICH_GO
    ws = Workspace.create(repo, feat_sha, tmp_path / "ws", config=gorepo.config())
    try:
        (ws.root / gorepo.SRC_SUB).write_text(src, encoding="utf-8")
        ws.overlay_tests((gorepo.TEST_SUB,))
        task = _go_task(feat_sha)
        n = len(ms.mutator_for("go").generate(src, ALL, max_mutants=20))
        assert n >= 6
        runs = [GREEN, BUILD_FAILED, KILLED, GREEN, RuntimeError("boom"), *([KILLED] * (n - 4))]
        events: list[tuple[str, Mapping[str, object]]] = []
        score = ms.score_task(
            ws,
            task,
            config=gorepo.config(),
            runner=_StubRunner(runs),
            executor=LocalExecutor(),
            changed_lines={gorepo.SRC_SUB: ALL},
            on_event=lambda a, p: events.append((a, dict(p))),
        )
        assert score.uncompilable == 1 and score.errors == 1
        assert score.total == n - 2 and score.killed == n - 3
        assert score.oracle_strength == round((n - 3) / (n - 2), 4)
        assert [o.status for o in score.outcomes][:4] == [
            "uncompilable",
            "killed",
            "escaped",
            "error",
        ]
        assert (ws.root / gorepo.SRC_SUB).read_text(encoding="utf-8") == src
        kinds = [a for a, _ in events]
        assert "oracle.mutation.uncompilable" in kinds and "oracle.mutation.error" in kinds
        scored = next(p for a, p in events if a == "oracle.mutation.scored")
        assert scored["uncompilable"] == 1 and scored["errors"] == 1 and scored["total"] == n - 2
        cell = ms.aggregate_by_cell([score])[score.cell]
        assert cell["uncompilable"] == 1 and cell["mutants"] == n - 2
        report = ms.to_report([score])
        assert report["summary"]["uncompilable"] == 1 and report["tasks"][0]["uncompilable"] == 1
        assert "uncompilable: 1" in ms.render_markdown(report)
        assert json.dumps(report, sort_keys=True) == json.dumps(
            ms.to_report([score]), sort_keys=True
        )
    finally:
        ws.remove()


def test_red_baseline_with_parse_error_stays_unscoreable_not_uncompilable(go_fixture, tmp_path):
    repo, feat_sha = go_fixture
    ws = Workspace.create(repo, feat_sha, tmp_path / "ws", config=gorepo.config())
    try:
        task = _go_task(feat_sha)
        ws.overlay_tests(task.test_files)  # parent + tests only: the target does not compile
        runner = _StubRunner([BUILD_FAILED])
        score = ms.score_task(
            ws,
            task,
            config=gorepo.config(),
            runner=runner,
            executor=LocalExecutor(),
            changed_lines={gorepo.SRC_SUB: ALL},
        )
        assert runner.calls == 1 and score.total == 0 and score.uncompilable == 0
        assert score.oracle_strength is None and score.note.startswith("baseline RED")
    finally:
        ws.remove()


def test_every_graded_version_is_newer_than_wall_clock(go_fixture, tmp_path):
    """Regression (caught by the Maven e2e): mtime-ORDERED build caches — Maven's
    stale-source check, cargo's fingerprints — skip recompilation when the source is
    older than the artefact compiled from the previous version, so the tests would run
    against the PREVIOUS code (a false escape / false kill). Every mutant and every
    restore must therefore be stamped strictly newer than wall-clock at write time."""
    repo, feat_sha = go_fixture
    src = _RICH_GO
    ws = Workspace.create(repo, feat_sha, tmp_path / "ws", config=gorepo.config())
    try:
        (ws.root / gorepo.SRC_SUB).write_text(src, encoding="utf-8")
        ws.overlay_tests((gorepo.TEST_SUB,))
        task = _go_task(feat_sha)
        n = len(ms.mutator_for("go").generate(src, ALL, max_mutants=20))
        seen: list[tuple[float, float]] = []

        class Clock(_StubRunner):
            def run(self, executor, root, scope, *, timeout=0):
                seen.append(((root / gorepo.SRC_SUB).stat().st_mtime, time.time()))
                return super().run(executor, root, scope, timeout=timeout)

        ms.score_task(
            ws,
            task,
            config=gorepo.config(),
            runner=Clock([GREEN, *([KILLED] * n)]),
            executor=LocalExecutor(),
            changed_lines={gorepo.SRC_SUB: ALL},
        )
        graded = seen[1:]  # the baseline is the untouched overlay
        assert len(graded) == n
        # Newer than any artefact built BEFORE the write: the previous run's wall clock is
        # the latest moment an artefact could have been compiled, and the write comes
        # after it. (Comparing with the wall clock read AFTER the write flaked on a slow
        # CI runner whenever the second boundary fell between the stamp and the read —
        # the stamp is an integer second, so 101 > 100.95 held but 101 > 101.05 did not.)
        before = [now for _, now in seen[:-1]]
        assert all(mtime > prev for (mtime, _), prev in zip(graded, before, strict=True))
        mtimes = [m for m, _ in graded]
        assert mtimes == sorted(mtimes) and len(set(mtimes)) == n  # strictly increasing
        restored = (ws.root / gorepo.SRC_SUB).stat().st_mtime
        assert restored > graded[-1][0] and restored > graded[-1][1]
    finally:
        ws.remove()


def test_uncompilable_outcome_cannot_also_be_graded():
    with pytest.raises(ValueError):
        ms.MutantOutcome("m01", "cmp_flip", 1, "d", True, "", uncompilable=True)
    o = ms.MutantOutcome("m01", "cmp_flip", 1, "d", None, "", uncompilable=True)
    assert o.status == "uncompilable" and o.to_dict()["status"] == "uncompilable"


# =============================================================================
# 3. end to end per language — the real toolchains
# =============================================================================

_E2E_SUBJECT = "feat: add floored sub"

#: The shared shape: ``d = a - b; if (floor && d < 0) return 0; return d`` with a
#: target test that exercises ONLY the non-floor path — so the ``-`` flip and the
#: negated condition die, the floor branch escapes, and a deleted declaration is
#: rejected by the compiler.

_GO_SUB = (
    "package calc\n\n"
    "// Sub returns a - b, floored at zero when floor is set.\n"
    "func Sub(a, b int, floor bool) int {\n"
    "\td := a - b\n"
    "\tif floor && d < 0 {\n"
    "\t\treturn 0\n"
    "\t}\n"
    "\treturn d\n"
    "}\n"
)
_GO_SUB_TEST = (
    'package calc\n\nimport "testing"\n\n'
    "func TestSub(t *testing.T) {\n"
    "\tif got := Sub(3, 2, false); got != 1 {\n"
    '\t\tt.Fatalf("Sub(3, 2, false) = %d, want 1", got)\n'
    "\t}\n}\n"
)
_JS_SUB = (
    '"use strict";\n\n'
    "function sub(a, b, floor) {\n"
    "  const d = a - b;\n"
    "  if (floor && d < 0) {\n"
    "    return 0;\n"
    "  }\n"
    "  return d;\n"
    "}\n\n"
    "module.exports = { sub };\n"
)
_JAVA_SUB = (
    "package ex;\n\n"
    "public final class Sub {\n"
    "    private Sub() {}\n\n"
    "    public static int sub(int a, int b, boolean floor) {\n"
    "        int d = a - b;\n"
    "        if (floor && d < 0) {\n"
    "            return 0;\n"
    "        }\n"
    "        return d;\n"
    "    }\n"
    "}\n"
)
_JAVA_SUB_TEST = (
    "package ex;\n\n"
    "import static org.junit.jupiter.api.Assertions.assertEquals;\n\n"
    "import org.junit.jupiter.api.Test;\n\n"
    "class SubTest {\n"
    "    @Test\n"
    "    void subWorks() {\n"
    "        assertEquals(1, Sub.sub(3, 2, false));\n"
    "    }\n"
    "}\n"
)
_RS_SUB = (
    "/// Returns a - b, floored at zero when `floor` is set.\n"
    "pub fn sub(a: i64, b: i64, floor: bool) -> i64 {\n"
    "    let d = a - b;\n"
    "    if floor && d < 0 {\n"
    "        return 0;\n"
    "    }\n"
    "    d\n"
    "}\n"
)
_RS_SUB_TEST = (
    "#[test]\nfn sub_integration() {\n    assert_eq!(calc::sub::sub(3, 2, false), 1);\n}\n"
)


def _e2e_task(
    sha: str, config: RepoConfig, src: tuple[str, ...], tests: tuple[str, ...]
) -> TaskSpec:
    runner = get_runner(config)
    return TaskSpec(
        task_id=sha,
        repo=config.name,
        subject=_E2E_SUBJECT,
        authored="2026-01-01T00:00:00+00:00",
        test_files=tests,
        src_files=src,
        target_tests=runner.target_scope(tests),
        belt_scope=(),
        language=config.language.value,
    )


def _score_e2e(
    repo: GitRepo, task: TaskSpec, config: RepoConfig, dest: Path
) -> tuple[ms.CommitOracleScore, dict[str, bytes]]:
    """Score at the GOLD state; return the score and the restored bytes of every source."""
    ws = Workspace.create(repo, task.task_id, dest, config=config)
    try:
        ws.overlay_tests(task.test_files)
        ws.overlay_sources(task.src_files)
        before = {p: (ws.root / p).read_bytes() for p in task.src_files}
        tests_before = {p: (ws.root / p).read_bytes() for p in task.test_files}
        score = ms.score_task(
            ws, task, config=config, runner=get_runner(config), executor=LocalExecutor()
        )
        after = {p: (ws.root / p).read_bytes() for p in task.src_files}
        assert {p: (ws.root / p).read_bytes() for p in task.test_files} == tests_before
        assert after == before
        return score, after
    finally:
        ws.remove()


def _assert_shape(score: ms.CommitOracleScore, *, compiled: bool) -> None:
    by = {(o.op, o.description): o for o in score.outcomes}
    assert by[("arith_flip", "- -> +")].status == "killed"  # the obvious mutant dies
    negs = [o for o in score.outcomes if o.op == "negate_cond"]
    assert negs and all(o.status == "killed" for o in negs)
    escaped = {o.description for o in score.escaped}
    assert "&& -> ||" in escaped and "< -> <=" in escaped  # the floor branch is never exercised
    assert score.total == score.killed + len(score.escaped)
    assert score.total > 0 and score.oracle_strength == round(score.killed / score.total, 4)
    assert score.errors == 0
    if compiled:
        unc = [o for o in score.outcomes if o.status == "uncompilable"]
        assert unc and all(o.op == "delete_stmt" and o.killed is None for o in unc)
        assert score.uncompilable == len(unc)
        assert score.uncompilable + score.total == len(score.outcomes)
    else:
        assert score.uncompilable == 0
    assert score.provenance.mutator_family == "text"
    assert score.provenance.mutator == "TextLineMutator"
    assert score.baseline is not None and score.baseline.green


@pytest.mark.toolchain("go")
@pytest.mark.skipif(not langs.has_tool("go"), reason="go not on PATH")
def test_e2e_go(tmp_path_factory):
    config = gorepo.config()
    root, sha = fixtures.two_commit_repo(
        tmp_path_factory.mktemp("go-e2e") / "repo",
        {"go.mod": "module example.com/m\n\ngo 1.22\n", gorepo.SRC_ADD: "package calc\n"},
        {gorepo.SRC_SUB: _GO_SUB, gorepo.TEST_SUB: _GO_SUB_TEST},
    )
    task = _e2e_task(sha, config, (gorepo.SRC_SUB,), (gorepo.TEST_SUB,))
    score, _ = _score_e2e(GitRepo(root), task, config, tmp_path_factory.mktemp("go-ws") / "ws")
    _assert_shape(score, compiled=True)
    unc = {o.line for o in score.outcomes if o.status == "uncompilable"}
    assert unc == {5, 9}  # `d := a - b` (undefined: d) and `return d` (missing return)
    assert all("[build failed]" in o.tail for o in score.outcomes if o.status == "uncompilable")
    assert score.provenance.language == "go" and score.provenance.runner == "go"


@pytest.mark.toolchain("node")
@pytest.mark.skipif(not langs.has_tool("node"), reason="node not on PATH")
def test_e2e_javascript_node_test(tmp_path_factory):
    config = noderepo.config("node")
    test_path = noderepo.test_sub("node")
    root, sha = fixtures.two_commit_repo(
        tmp_path_factory.mktemp("js-e2e") / "repo",
        {
            "package.json": '{"name": "calcfix", "private": true, "scripts": {"test": "node --test"}}\n'
        },
        {
            noderepo.SRC_SUB: _JS_SUB,
            test_path: noderepo.test_module("sub", "sub", "3, 2, false", "1", "sub works", "node"),
        },
    )
    task = _e2e_task(sha, config, (noderepo.SRC_SUB,), (test_path,))
    score, _ = _score_e2e(GitRepo(root), task, config, tmp_path_factory.mktemp("js-ws") / "ws")
    _assert_shape(score, compiled=False)
    # JavaScript has no compile step: a deleted declaration is a RUNTIME fault, observed
    dels = {o.line: o.status for o in score.outcomes if o.op == "delete_stmt"}
    assert dels[4] == "killed" and dels[8] == "killed" and dels[6] == "escaped"
    assert score.provenance.language == "javascript" and score.provenance.runner == "node"


@pytest.mark.toolchain("mvn")
@pytest.mark.skipif(not langs.has_tool("mvn"), reason="mvn not on PATH")
@pytest.mark.skipif(not jvmrepo.java_home(), reason="no JDK: neither brew openjdk nor $JAVA_HOME")
def test_e2e_jvm_maven(tmp_path_factory):
    langs.maven_warmup(tmp_path_factory.mktemp("mvn-warm"))
    config = jvmrepo.config(offline=True)
    root, sha = fixtures.two_commit_repo(
        tmp_path_factory.mktemp("jvm-e2e") / "repo",
        {"pom.xml": jvmrepo.POM, ".gitignore": "target\n", jvmrepo.SRC_CALC: jvmrepo.CALC_JAVA},
        {jvmrepo.SRC_SUB: _JAVA_SUB, jvmrepo.TEST_SUB: _JAVA_SUB_TEST},
    )
    task = _e2e_task(sha, config, (jvmrepo.SRC_SUB,), (jvmrepo.TEST_SUB,))
    score, _ = _score_e2e(GitRepo(root), task, config, tmp_path_factory.mktemp("jvm-ws") / "ws")
    _assert_shape(score, compiled=True)
    unc = {o.line for o in score.outcomes if o.status == "uncompilable"}
    assert unc == {7, 11}  # `int d = a - b;` (cannot find symbol) and `return d;` (missing return)
    assert score.provenance.language == "jvm" and score.provenance.runner == "maven"


@pytest.mark.toolchain("cargo")
@pytest.mark.skipif(not langs.has_tool("cargo"), reason="cargo not on PATH")
def test_e2e_rust_cargo(tmp_path_factory):
    config = rustrepo.config()
    base = tmp_path_factory.mktemp("rs-e2e")
    root, _ = rustrepo.build(base)  # the stock two commits (with a committed lockfile)
    fixtures.write_files(root, {rustrepo.SRC_SUB: _RS_SUB, rustrepo.TEST_SUB: _RS_SUB_TEST})
    sha = fixtures.commit_all(root, _E2E_SUBJECT)
    task = _e2e_task(sha, config, (rustrepo.SRC_SUB,), (rustrepo.TEST_SUB,))
    score, _ = _score_e2e(GitRepo(root), task, config, tmp_path_factory.mktemp("rs-ws") / "ws")
    _assert_shape(score, compiled=True)
    unc = {o.line for o in score.outcomes if o.status == "uncompilable"}
    assert unc == {3}  # `let d = a - b;` — `d` unresolved; the tail expression is not a statement
    assert score.provenance.language == "rust" and score.provenance.runner == "cargo"


@pytest.mark.toolchain("go")
@pytest.mark.skipif(not langs.has_tool("go"), reason="go not on PATH")
def test_e2e_go_stock_fixture_kills_its_one_mutant_and_git_derives_the_lines(tmp_path_factory):
    """The stock fixture's ``func Sub(a, b int) int { return a - b }`` yields exactly the
    ``- -> +`` flip on a git-derived changed line, and the feat's test kills it."""
    config = gorepo.config()
    root, sha = gorepo.build(tmp_path_factory.mktemp("go-stock"))
    task = _e2e_task(sha, config, (gorepo.SRC_SUB,), (gorepo.TEST_SUB,))
    score, _ = _score_e2e(
        GitRepo(root), task, config, tmp_path_factory.mktemp("go-stock-ws") / "ws"
    )
    assert score.total == 1 and score.killed == 1 and score.oracle_strength == 1.0
    assert score.outcomes[0].description == "- -> +" and score.outcomes[0].line == 4
    assert score.uncompilable == 0 and score.errors == 0
