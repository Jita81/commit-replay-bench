"""crb.core.api_surface — belt 6's extractors and comparison, on real source text and real
git trees.

Navigation
----------
What it is:   The unit suite for belt 6 ``api_stable``: the Go, Python and JS/TS surface
              extractors, the parent/trial/gold comparison and the tree reader over a real
              fixture repository.
What it does: Pins that an exported signature change is a finding, that the same change made
              by the gold is not, that a private change never is, that parameter NAMES are not
              Go/JS API but are Python API, that non-public units (``internal/``, ``package
              main``, ``_private`` modules, tool configs) are skipped, and — when a Go
              toolchain is present — that the Go scanner finds exactly the exported
              declarations ``go/ast`` finds.
How:          Extractors on inline sources; ``evaluate`` over an in-memory ``Trees`` and over
              ``WorkspaceTrees`` on a hermetic two-commit git repository; a small ``go/ast``
              program run with ``go run`` as the cross-check oracle.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0024-working-by-construction.md
Works with:   src/crb/core/api_surface.py (under test), tests/fixtures/langs/__init__.py (the
              hermetic git helpers), tests/test_grade_api_belt.py (the belt inside the grader)
Tested by:    tests/test_api_surface.py
Touch when:   an extractor learns a new declaration form (add its source here) or a language
              gains an extractor.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from crb.core import api_surface as api
from crb.core.git import GitRepo
from crb.core.workspace import Workspace
from fixtures.langs import commit_all, init_repo, write_files

GO_SRC = """package calc

import "fmt"

// Add returns a + b. { a brace in a comment
func Add(a, b int) int { return a + b }

func sub(a int) int { s := "}"; _ = s; return a }

type Options struct {
	Name string `json:"name"`
	count int
	A, B  map[string]int
	*Embedded
	fmt.Stringer
}

type Embedded struct{}

type Shape interface {
	Area() float64
	perim() float64
}

func (o *Options) Set(v string) error { return nil }

func (o *options) Hidden() {}

type options struct{}

type Set[T comparable] struct{ items map[T]struct{} }

func (s *Set[T]) Add(v T) {}

type Kind int

const (
	KindA Kind = iota
	KindB
	kindc
)

var Default = &Options{}

var X, y int

func Many(fn func(int) error, xs ...string) (n int, err error) { return }

func Iface() interface{} { return nil }

func init() { _ = fmt.Sprint(Default) }
"""


class MemTrees:
    """An in-memory :class:`api.Trees` — ``{tree: {rel: text}}``."""

    def __init__(self, trees: dict[str, dict[str, str]]) -> None:
        self.trees = trees

    def read(self, tree: str, rel: str) -> str | None:
        return self.trees.get(tree, {}).get(rel)

    def listdir(self, tree: str, directory: str) -> list[str]:
        prefix = f"{directory}/" if directory else ""
        return [
            r
            for r in self.trees.get(tree, {})
            if r.startswith(prefix) and "/" not in r[len(prefix) :]
        ]


def _three(parent: dict[str, str], trial: dict[str, str], gold: dict[str, str]) -> MemTrees:
    return MemTrees({"parent": parent, "trial": trial, "gold": gold})


# --- Go -------------------------------------------------------------------------------------


def test_go_surface_is_the_exported_declarations_with_types_only() -> None:
    s = api.go_surface(GO_SRC)
    assert s["Add"] == "func(int,int)int"
    assert s["Options.Set"] == "func(string)error"
    assert s["Set.Add"] == "func(T)"
    assert s["Many"] == "func(func(int)error,...string)(int,error)"
    assert s["Iface"] == "func()interface{}"
    assert s["Options"].startswith("type struct{") and "count" not in s["Options"]
    assert "Name string" in s["Options"] and "embed *Embedded" in s["Options"]
    assert s["Shape"] == "type interface{Area()float64}"  # perim is unexported
    assert {"KindA", "KindB", "Default", "X"} <= set(s)
    # unexported names, methods on unexported types, init and y never appear
    assert not {"sub", "options", "options.Hidden", "init", "y", "kindc"} & set(s)


def test_go_parameter_names_and_formatting_are_not_api() -> None:
    a = api.go_surface("package p\n\nfunc F(a, b int) (err error) { return }\n")
    b = api.go_surface("package p\n\nfunc F(x int,   y int) error {\n\treturn nil\n}\n")
    assert a == b == {"F": "func(int,int)error"}


@pytest.mark.skipif(shutil.which("go") is None, reason="go not on PATH")
@pytest.mark.toolchain("go")
def test_go_scanner_agrees_with_go_ast_on_which_names_are_exported(tmp_path: Path) -> None:
    """The oracle: ``go/ast`` lists the exported top-level declarations (methods as
    ``Recv.Name``); the scanner must find the same set on the same file."""
    program = tmp_path / "oracle" / "main.go"
    program.parent.mkdir()
    program.write_text(
        """package main

import (
	"encoding/json"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"strings"
)

func recv(e ast.Expr) string {
	switch t := e.(type) {
	case *ast.StarExpr:
		return recv(t.X)
	case *ast.IndexExpr:
		return recv(t.X)
	case *ast.IndexListExpr:
		return recv(t.X)
	case *ast.Ident:
		return t.Name
	}
	return ""
}

func main() {
	f, err := parser.ParseFile(token.NewFileSet(), os.Args[1], nil, 0)
	if err != nil {
		panic(err)
	}
	var out []string
	for _, d := range f.Decls {
		switch d := d.(type) {
		case *ast.FuncDecl:
			if !d.Name.IsExported() {
				continue
			}
			if d.Recv != nil {
				r := recv(d.Recv.List[0].Type)
				if !ast.IsExported(r) {
					continue
				}
				out = append(out, r+"."+d.Name.Name)
			} else {
				out = append(out, d.Name.Name)
			}
		case *ast.GenDecl:
			for _, s := range d.Specs {
				switch s := s.(type) {
				case *ast.TypeSpec:
					if s.Name.IsExported() {
						out = append(out, s.Name.Name)
					}
				case *ast.ValueSpec:
					for _, n := range s.Names {
						if n.IsExported() {
							out = append(out, n.Name)
						}
					}
				}
			}
		}
	}
	_ = strings.Join
	json.NewEncoder(os.Stdout).Encode(out)
}
""",
        encoding="utf-8",
    )
    # not ``.go``: ``go run`` would take it for a second file of the oracle program
    source = tmp_path / "calc.go.txt"
    source.write_text(GO_SRC, encoding="utf-8")
    res = subprocess.run(
        ["go", "run", str(program), str(source)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        cwd=tmp_path,
        env={**_go_env(tmp_path)},
    )
    assert res.returncode == 0, res.stderr
    expected = set(json.loads(res.stdout))
    assert set(api.go_surface(GO_SRC)) == expected


def _go_env(tmp_path: Path) -> dict[str, str]:
    import os

    env = dict(os.environ)
    env.setdefault("GOCACHE", str(tmp_path / "gocache"))
    env["GOFLAGS"] = "-mod=mod"
    env["GO111MODULE"] = "on"
    return env


# --- Python -----------------------------------------------------------------------------------


def test_python_surface_names_kinds_and_defaults_but_not_annotations() -> None:
    src = (
        "import os\n"
        "def f(a: int, b: int = 1, *, c, d=2, **kw) -> int: ...\n"
        "def _h(): ...\n"
        "class C:\n"
        "    x: int = 3\n"
        "    def __init__(self, a): ...\n"
        "    def _p(self): ...\n"
        "    @property\n"
        "    def v(self): ...\n"
        "VALUE = 1\n"
    )
    s = api.python_surface(src)
    assert s["f"] == "def(a,b=,*,c,d=,**kw)"
    assert s["C.__init__"] == "def(self,a)" and s["C.v"] == "@property def(self)"
    assert s["C.x"] == "attr=" and s["VALUE"] == "var"
    assert not {"_h", "C._p", "os"} & set(s)  # private names; a plain module's imports
    # annotations are not API; a default's presence is
    assert api.python_surface("def f(a, b=2): ...\n") == api.python_surface(
        "def f(a: str, b: int = 99) -> None: ...\n"
    )
    assert api.python_surface("def f(a, b): ...\n") != api.python_surface("def f(a, b=1): ...\n")


def test_python_all_decides_and_package_init_reexports_count() -> None:
    src = '__all__ = ["f", "g"]\nfrom .x import g, h\ndef f(): ...\ndef k(): ...\n'
    assert set(api.python_surface(src)) == {"f", "g"}
    init = "from .core import Command as Command\nfrom .core import _hidden\n"
    assert api.python_surface(init, is_package_init=True) == {"Command": "import .core:Command"}


def test_a_private_import_in_a_package_init_without_all_is_not_a_finding() -> None:
    """click's ``__init__.py`` has no ``__all__`` and re-exports with ``X as X``: adding
    ``import os`` or ``from __future__ import annotations`` changes no API (P-030)."""
    init = "from .core import Command as Command\n"
    trial = (
        "from __future__ import annotations\nimport os\nfrom typing import Any\n"
        "from .core import Command as Command\n"
    )
    s = api.python_surface(trial, is_package_init=True)
    assert s == {"Command": "import .core:Command"}
    tree = {"src/click/__init__.py": init}
    run = api.evaluate(
        ["src/click/__init__.py"], _three(tree, {"src/click/__init__.py": trial}, tree)
    )
    assert run.ok is True and not run.findings
    # a relative import and an explicit re-export are still the package's API
    added = init + "from .types import Choice\nfrom json import dumps as dumps\n"
    assert set(api.python_surface(added, is_package_init=True)) == {"Command", "Choice", "dumps"}
    # with __all__ its names decide, whatever the import
    declared = '__all__ = ["path"]\nimport os.path as path\n'
    assert set(api.python_surface(declared, is_package_init=True)) == {"path"}


# --- JavaScript / TypeScript ------------------------------------------------------------------


def test_js_commonjs_class_export_records_public_methods_by_shape() -> None:
    src = (
        "const Emitter = require('events')\n"
        "module.exports = class Application extends Emitter {\n"
        "  constructor (options) { super(); this.x = '}' }\n"
        "  listen (...args) { return 1 }\n"
        "  _private () {}\n"
        "  static create (a, b = {}) {}\n"
        "}\n"
    )
    s = api.js_surface(src)
    assert s["default"] == "class"
    assert s["default.constructor"] == "method(p)"
    assert s["default.listen"] == "method(...)"
    assert s["default.create"] == "static method(p,p?)"
    assert "default._private" not in s


def test_js_an_optional_argument_made_required_is_an_api_change() -> None:
    """The nhsuk-frontend review finding: ``$root`` made a REQUIRED parameter."""
    before = "export class Header {\n  constructor($root = document, options = {}) {}\n}\n"
    after = "export class Header {\n  constructor($root, options = {}) {}\n}\n"
    renamed = "export class Header {\n  constructor(root = document, opts = {}) {}\n}\n"
    assert api.js_surface(before)["Header.constructor"] == "method(p?,p?)"
    assert api.js_surface(after)["Header.constructor"] == "method(p,p?)"
    assert api.js_surface(before) == api.js_surface(renamed)  # names are not JS API


def test_js_es_exports_lists_defaults_and_typescript_declarations() -> None:
    src = (
        "import { x } from './x.mjs'\n"
        "export function initHeader(options) {}\n"
        "export const helper = (a, b) => a\n"
        "export { x as y }\n"
        "export * from './all.mjs'\n"
        "export interface Props { a: string; b?: number }\n"
        "function local() {}\n"
    )
    s = api.js_surface(src)
    assert s["initHeader"] == "function(p)" and s["helper"] == "function(p,p)"
    assert s["y"] == "var" and s["*"] == "reexport-all x1"
    assert s["Props"].startswith("interface ")
    assert "local" not in s


# --- units and the comparison -----------------------------------------------------------------


def test_units_skip_what_is_not_public_api() -> None:
    changed = [
        "calc/calc.go",
        "internal/x/x.go",
        "cmd/tool/testdata/a.go",
        "pkg/_private.py",
        "pkg/public.py",
        "jest.config.js",
        "src/header.mjs",
        "docs/conf.py",
        "README.md",
    ]
    assert set(api.units_for(changed)) == {"calc", "pkg/public.py", "src/header.mjs"}


def test_a_go_doc_package_is_public_api() -> None:
    """cobra publishes ``github.com/spf13/cobra/doc`` (``GenMarkdownTree``): for Go only the
    go tool's own conventions make a directory private (P-029)."""
    assert set(api.units_for(["doc/md_docs.go", "command.go", "examples/x/x.go"])) == {
        "doc",
        ".",
        "examples/x",
    }
    assert api.units_for(["_hidden/a.go", ".tool/a.go", "vendor/v/a.go"]) == {}
    parent = {
        "doc/md_docs.go": "package doc\n\nfunc GenMarkdownTree(cmd *C, dir string) error { return nil }\n"
    }
    trial = {"doc/md_docs.go": "package doc\n\nfunc GenMarkdownTree(cmd *C) error { return nil }\n"}
    run = api.evaluate(["doc/md_docs.go"], _three(parent, trial, parent))
    assert run.ok is False and [f.label for f in run.findings] == ["changed:doc:GenMarkdownTree"]
    # a Python or JS docs/ directory is still not a public unit
    assert api.units_for(["docs/conf.py", "doc/helper.js"]) == {}


def test_a_signature_change_is_a_finding_the_gold_mirroring_it_is_not() -> None:
    parent = {"m.py": "def f(a): ...\n"}
    changed = {"m.py": "def f(a, b): ...\n"}
    same_gold = _three(parent, changed, changed)
    other_gold = _three(parent, changed, {"m.py": "def f(a, *, b=None): ...\n"})
    ok = api.evaluate(["m.py"], same_gold)
    assert ok.ok is True and ok.matched == 1 and not ok.findings
    bad = api.evaluate(["m.py"], other_gold)
    assert bad.ok is False
    (f,) = bad.findings
    assert (f.kind, f.unit, f.symbol) == ("changed", "m.py", "f")
    assert bad.label == "false" and bad.summary() == "changed:m.py:f"


def test_a_private_change_and_a_body_only_change_are_not_findings() -> None:
    parent = {"m.py": "def f(a):\n    return a\n"}
    trial = {"m.py": "def f(a):\n    return _g(a)\n\ndef _g(a):\n    return a + 1\n"}
    run = api.evaluate(["m.py"], _three(parent, trial, parent))
    assert run.ok is True and run.matched == 0


def test_an_added_export_the_gold_does_not_have_is_a_finding() -> None:
    """The cobra review finding: an exported setter the maintainers never added."""
    parent = {
        "c/c.go": "package c\n\ntype CompletionOptions struct {\n\tDisable bool\n}\n",
    }
    gold = {
        "c/c.go": (
            "package c\n\ntype CompletionOptions struct {\n\tDisable bool\n"
            "\tDefaultShellCompDirective *int\n}\n"
        ),
    }
    trial = {
        "c/c.go": (
            "package c\n\ntype CompletionOptions struct {\n\tDisable bool\n\tdef *int\n}\n\n"
            "func (o *CompletionOptions) SetDefaultShellCompDirective(d int) { o.def = &d }\n"
        ),
    }
    run = api.evaluate(["c/c.go"], _three(parent, trial, gold))
    assert run.ok is False
    assert [f.label for f in run.findings] == [
        "added:c:CompletionOptions.SetDefaultShellCompDirective"
    ]


def test_a_go_package_is_one_unit_so_a_moved_declaration_is_not_a_finding() -> None:
    parent = {"p/a.go": "package p\n\nfunc F(x int) int { return x }\n", "p/b.go": "package p\n"}
    trial = {"p/a.go": "package p\n", "p/b.go": "package p\n\nfunc F(y int) int { return y }\n"}
    run = api.evaluate(["p/a.go", "p/b.go"], _three(parent, trial, parent))
    assert run.ok is True and run.units == ("p",)


def test_package_main_and_unparsable_units_are_not_evaluated_never_a_verdict() -> None:
    main = {"cmd/main.go": "package main\n\nfunc Run() {}\n"}
    run = api.evaluate(["cmd/main.go"], _three(main, main, main))
    assert run.ok is None and "cmd" in run.note
    broken = api.evaluate(["m.py"], _three({"m.py": "def f(:\n"}, {"m.py": "x = 1\n"}, {}))
    assert broken.ok is None
    assert api.evaluate(["README.md"], _three({}, {}, {})).ok is None


def test_an_api_run_cannot_contradict_its_findings() -> None:
    f = api.ApiFinding("m.py", "f", "changed")
    with pytest.raises(ValueError, match="cannot be ok"):
        api.ApiRun(True, ("m.py",), (f,))
    with pytest.raises(ValueError, match="at least one finding"):
        api.ApiRun(False, ("m.py",), ())


# --- the tree reader over a real repository ---------------------------------------------------


def test_workspace_trees_read_parent_gold_and_trial_from_a_real_repository(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    init_repo(root)
    write_files(
        root,
        {"go.mod": "module example.com/m\n\ngo 1.22\n", "p/a.go": "package p\n\nfunc A() {}\n"},
    )
    commit_all(root, "chore: initial")
    write_files(root, {"p/b.go": "package p\n\nfunc B(x int) {}\n"})
    sha = commit_all(root, "feat: add B")
    ws = Workspace.create(GitRepo(root), sha, tmp_path / "trial")
    try:
        (ws.root / "p" / "b.go").write_text("package p\n\nfunc B(x string) {}\n", encoding="utf-8")
        trees = api.WorkspaceTrees(ws)
        assert sorted(trees.listdir("parent", "p")) == ["p/a.go"]
        assert sorted(trees.listdir("gold", "p")) == ["p/a.go", "p/b.go"]
        assert sorted(trees.listdir("trial", "p")) == ["p/a.go", "p/b.go"]
        run = api.evaluate(["p/b.go"], trees)
        assert run.ok is False
        assert [f.label for f in run.findings] == ["added:p:B"]
        assert run.findings[0].gold == "func(int)" and run.findings[0].after == "func(string)"
    finally:
        ws.remove()
