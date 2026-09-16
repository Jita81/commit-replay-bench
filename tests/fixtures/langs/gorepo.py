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

Navigation
----------
What it is:   The Go fixture: module ``example.com/m`` with package ``calc`` and a sibling
              package ``util``.
What it does: Builds the two-commit shape for the ``go test -json`` runner; the sibling package
              lets belt 3 be shown failing on its own because Go's target scope is a whole
              package (a same-package regression shows in belt 2 instead). ``build(extra=…)``
              lets a test commit a lint config on the parent.
How:          ``two_commit_repo`` over inline Go sources; ``config`` returns a ``RepoConfig`` with
              suffix-based test detection (``*_test.go``) and the requested belt scope.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0010-polyglot-negative-controls.md
Works with:   tests/fixtures/langs/__init__.py (the shape), src/crb/core/runners/go_runner.py
              (the runner under test), tests/test_runners_go.py, tests/test_oracle_controls_go.py
              and tests/test_lint.py (the consumers), tests/fixtures/langs/negctrl/gorepo_funcvar.py
              (the variant whose feat commit changes an existing unit)
Tested by:    tests/test_runners_go.py, tests/test_oracle_controls_go.py, tests/test_grade.py
Touch when:   the Go runner's scope or parse rules change in a way the fixture cannot exercise;
              a test needs another package or file in the parent (use ``extra``).
"""

from __future__ import annotations

from collections.abc import Mapping
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


def build(tmp_path: Path, *, extra: Mapping[str, str] | None = None) -> tuple[Path, str]:
    """``extra`` = more files in the initial commit (a lint config the parent carries)."""
    return two_commit_repo(Path(tmp_path) / "gorepo", {**_INITIAL, **(extra or {})}, _FEAT)


def config(belt_scope: str | tuple[str, ...] = BELT_BARE) -> RepoConfig:
    """The ``RepoConfig`` for the fixture: the ``go`` runner with suffix-based test detection."""
    return RepoConfig(name="gofix", language=Language.GO, runner="go", belt_scope=belt_scope)
