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

Navigation
----------
What it is:   The Go fixture whose feat commit changes a package-level function variable.
What it does: Gives the Go ``env_poison`` control its vector: ``var Scale = func…`` is the one
              thing an ``init()`` in a new file can re-assign, so all seven controls are
              constructible on it (the base ``gorepo`` reaches 6/7). Parent + ``scale_test.go``
              is RED on an assertion, so the failure is attributed, not a build error.
How:          ``two_commit_repo`` over inline Go sources (``calc`` with ``Scale``, ``util`` as the
              adjacent package for belt 3); ``config`` returns a ``RepoConfig`` with the requested
              belt scope.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0010-polyglot-negative-controls.md
Works with:   src/crb/core/oracle/controls_go.py (the transforms exercised on it),
              tests/test_oracle_controls_go.py (the consumer), tests/fixtures/langs/gorepo.py (the
              base fixture it varies), tests/fixtures/langs/__init__.py (the shape)
Tested by:    tests/test_oracle_controls_go.py
Touch when:   the Go ``env_poison`` transform gains another vector (a method value, an
              interface) — add the unit here and pin the verdict in the matrix test.
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
    """The two-commit fixture under ``tmp_path / "gorepo-funcvar"``; returns ``(root, feat_sha)``."""
    return two_commit_repo(Path(tmp_path) / "gorepo-funcvar", _INITIAL, _FEAT)


def config(belt_scope: str | tuple[str, ...] = BELT_BARE) -> RepoConfig:
    """The ``RepoConfig`` for the fixture (the ``go`` runner; same shape as ``gorepo.config``)."""
    return RepoConfig(name="gofuncvar", language=Language.GO, runner="go", belt_scope=belt_scope)
