"""Go fixture: module ``example.com/m``, package ``calc`` (+ a sibling package ``util``).

Layout::

    go.mod                 module example.com/m (no external deps)
    calc/calc.go           Add            \\  commit 1
    calc/calc_test.go      TestAdd         |
    util/util.go           Twice           |  (second package: the Go target scope is a
    util/util_test.go      TestTwice      /   whole package, so a same-package regression
                                              shows in belt 2; ``util`` lets belt 3 be
                                              exercised on its own)
    calc/sub.go            Sub            \\  commit 2 (the feat)
    calc/sub_test.go       TestSub        /

Go's ``is_test`` is suffix-based (``*_test.go``), so no prefixes are configured.
"""

from __future__ import annotations

from pathlib import Path

from crb.core.spec import BELT_BARE, Language, RepoConfig

from . import two_commit_repo

MODULE = "example.com/m"
CALC_PKG = f"{MODULE}/calc"
UTIL_PKG = f"{MODULE}/util"

SRC_ADD = "calc/calc.go"
TEST_ADD = "calc/calc_test.go"
SRC_TWICE = "util/util.go"
TEST_TWICE = "util/util_test.go"
SRC_SUB = "calc/sub.go"
TEST_SUB = "calc/sub_test.go"

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
    SRC_SUB: "package calc\n\n// Sub returns a - b.\nfunc Sub(a, b int) int { return a - b }\n",
    TEST_SUB: (
        'package calc\n\nimport "testing"\n\n'
        "func TestSub(t *testing.T) {\n"
        "\tif got := Sub(3, 2); got != 1 {\n"
        '\t\tt.Fatalf("Sub(3, 2) = %d, want 1", got)\n'
        "\t}\n}\n"
    ),
}

#: Source edits that break a neighbouring test (used by the regression tests).
BREAK_ADD = (
    "package calc\n\n// Add is broken on purpose.\nfunc Add(a, b int) int { return a + b + 1 }\n"
)
BREAK_TWICE = (
    "package util\n\n// Twice is broken on purpose.\nfunc Twice(a int) int { return a * 3 }\n"
)


def build(tmp_path: Path) -> tuple[Path, str]:
    return two_commit_repo(Path(tmp_path) / "gorepo", _INITIAL, _FEAT)


def config(belt_scope: str | tuple[str, ...] = BELT_BARE) -> RepoConfig:
    return RepoConfig(name="gofix", language=Language.GO, runner="go", belt_scope=belt_scope)
