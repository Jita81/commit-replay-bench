"""Go fixture whose feat commit CHANGES a package-level function variable.

Layout::

    go.mod                 module example.com/m
    calc/calc.go           Add                   \\  commit 1
    calc/calc_test.go      TestAdd                |
    calc/scale.go          var Scale = func(a) a  |  (the variable env_poison re-assigns)
    util/util.go           Twice                  |  (adjacent package for belt 3)
    util/util_test.go      TestTwice             /
    calc/scale.go          var Scale = func(a) 2a \\  commit 2 (the fix)
    calc/scale_test.go     TestScale             /

Parent + ``scale_test.go`` overlaid → ``TestScale`` fails on an assertion (RED,
attributed); gold → GREEN with no new failures.
"""

from __future__ import annotations

from pathlib import Path

from crb.core.spec import BELT_BARE, Language, RepoConfig

from .. import two_commit_repo

MODULE = "example.com/m"
CALC_PKG = f"{MODULE}/calc"
UTIL_PKG = f"{MODULE}/util"

SRC_ADD = "calc/calc.go"
TEST_ADD = "calc/calc_test.go"
SRC_SCALE = "calc/scale.go"
TEST_SCALE = "calc/scale_test.go"
SRC_TWICE = "util/util.go"
TEST_TWICE = "util/util_test.go"

SCALE_PARENT = (
    "package calc\n\n// Scale is the scaling hook (identity until configured).\n"
    "var Scale = func(a int) int {\n\treturn a\n}\n"
)
SCALE_GOLD = "package calc\n\n// Scale doubles its input.\nvar Scale = func(a int) int {\n\treturn a * 2\n}\n"

_INITIAL = {
    "go.mod": f"module {MODULE}\n\ngo 1.22\n",
    SRC_ADD: "package calc\n\n// Add returns a + b.\nfunc Add(a, b int) int { return a + b }\n",
    TEST_ADD: (
        'package calc\n\nimport "testing"\n\n'
        "func TestAdd(t *testing.T) {\n"
        "\tif got := Add(1, 2); got != 3 {\n"
        '\t\tt.Fatalf("Add(1, 2) = %d, want 3", got)\n'
        "\t}\n}\n"
    ),
    SRC_SCALE: SCALE_PARENT,
    SRC_TWICE: "package util\n\n// Twice returns 2 * a.\nfunc Twice(a int) int { return a * 2 }\n",
    TEST_TWICE: (
        'package util\n\nimport "testing"\n\n'
        "func TestTwice(t *testing.T) {\n"
        "\tif got := Twice(2); got != 4 {\n"
        '\t\tt.Fatalf("Twice(2) = %d, want 4", got)\n'
        "\t}\n}\n"
    ),
}

_FEAT = {
    SRC_SCALE: SCALE_GOLD,
    TEST_SCALE: (
        'package calc\n\nimport "testing"\n\n'
        "func TestScale(t *testing.T) {\n"
        "\tif got := Scale(2); got != 4 {\n"
        '\t\tt.Fatalf("Scale(2) = %d, want 4", got)\n'
        "\t}\n}\n"
    ),
}


def build(tmp_path: Path) -> tuple[Path, str]:
    return two_commit_repo(Path(tmp_path) / "gorepo-funcvar", _INITIAL, _FEAT)


def config(belt_scope: str | tuple[str, ...] = BELT_BARE) -> RepoConfig:
    return RepoConfig(name="gofuncvar", language=Language.GO, runner="go", belt_scope=belt_scope)
