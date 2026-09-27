"""Go fixture WITH a module dependency: ``example.com/app`` requires ``example.com/dep``.

The shape of the two defects the sealed posture was found with (ADR-0019):

* **D4** — the parent requires ``example.com/dep v1.0.0`` and the feat (gold) commit bumps it
  to ``v1.1.0`` (its new code calls ``dep.Farewell``, which only ``v1.1.0`` has), so one
  module cache must hold both versions for the parent and the gold to build offline;
* **D5** — ``writer/writer_test.go`` writes a file into its own package directory and reads it
  back, as cobra's ``TestDeadcodeElimination`` does. It passes on the host and in a
  throwaway copy of the tree, and fails on a read-only tree.

Layout::

    go.mod, go.sum          module example.com/app; require example.com/dep v1.0.0   \\ commit 1
    app/app.go              Hello() → dep.Greeting()                                 |
    app/app_test.go         TestHello                                                 |
    writer/writer.go        Name                                                      |
    writer/writer_test.go   TestWritesIntoItsPackage (writes ./generated.txt)        /
    go.mod, go.sum          require example.com/dep v1.1.0                           \\ commit 2
    app/bye.go              Bye() → dep.Farewell()                                     |  (the feat)
    app/bye_test.go         TestBye                                                   /

The module ``example.com/dep`` is served by :mod:`tests.fixtures.goproxy`.

Navigation
----------
What it is:   The Go fixture with a third-party module and a tree-writing test — the D4 and D5
              shapes of ADR-0019 in a repository small enough for every test to build.
What it does: Builds the two-commit repository whose parent and gold need different versions of
              ``example.com/dep`` and whose ``writer`` package writes into its own directory.
How:          ``two_commit_repo`` over inline sources; ``go.sum`` from ``goproxy.go_sum``;
              ``config`` returns a ``RepoConfig`` for the ``go`` runner.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         none
Works with:   tests/fixtures/goproxy.py (the mirror the dependency comes from),
              tests/fixtures/langs/__init__.py (the two-commit shape), tests/test_provision_go.py
              (fetches its dependencies), tests/test_sandbox_images_docker.py (the D5 regression)
Tested by:    tests/test_provision_go.py, tests/test_sandbox_images_docker.py
Touch when:   a provisioning test needs another dependency shape (a local replace, a vendor
              tree) — add a variant builder rather than changing these two commits.
"""

from __future__ import annotations

from pathlib import Path

from crb.core.spec import BELT_BARE, Language, RepoConfig

from .. import goproxy
from . import two_commit_repo

MODULE = "example.com/app"
APP_PKG = f"{MODULE}/app"
WRITER_PKG = f"{MODULE}/writer"
WRITER_TEST_ID = f"{WRITER_PKG}::TestWritesIntoItsPackage"

SRC_BYE = "app/bye.go"
TEST_BYE = "app/bye_test.go"


def go_mod(version: str) -> str:
    return f"module {MODULE}\n\ngo 1.22\n\nrequire {goproxy.MODULE} {version}\n"


_INITIAL = {
    "go.mod": go_mod("v1.0.0"),
    "go.sum": goproxy.go_sum(["v1.0.0"]),
    "app/app.go": (
        f'package app\n\nimport "{goproxy.MODULE}"\n\n'
        "// Hello greets.\nfunc Hello() string { return dep.Greeting() }\n"
    ),
    "app/app_test.go": (
        'package app\n\nimport "testing"\n\n'
        "func TestHello(t *testing.T) {\n"
        '\tif Hello() != "hello" {\n\t\tt.Fatal("bad greeting")\n\t}\n}\n'
    ),
    "writer/writer.go": 'package writer\n\n// Name is what the test writes.\nconst Name = "generated.txt"\n',
    "writer/writer_test.go": (
        'package writer\n\nimport (\n\t"os"\n\t"testing"\n)\n\n'
        "// Writes into its own package directory, as cobra's TestDeadcodeElimination does.\n"
        "func TestWritesIntoItsPackage(t *testing.T) {\n"
        '\tif err := os.WriteFile(Name, []byte("x"), 0o644); err != nil {\n'
        '\t\tt.Fatalf("could not write: %v", err)\n\t}\n'
        "\tdefer os.Remove(Name)\n"
        "\tif _, err := os.Stat(Name); err != nil {\n\t\tt.Fatal(err)\n\t}\n}\n"
    ),
}

_FEAT = {
    "go.mod": go_mod("v1.1.0"),
    "go.sum": goproxy.go_sum(["v1.1.0"]),
    SRC_BYE: (
        f'package app\n\nimport "{goproxy.MODULE}"\n\n'
        "// Bye says goodbye.\nfunc Bye() string { return dep.Farewell() }\n"
    ),
    TEST_BYE: (
        'package app\n\nimport "testing"\n\n'
        "func TestBye(t *testing.T) {\n"
        '\tif Bye() != "goodbye" {\n\t\tt.Fatal("bad farewell")\n\t}\n}\n'
    ),
}


def build(tmp_path: Path) -> tuple[Path, str]:
    """``(repo, feat_sha)`` under ``tmp_path/gorepo_deps``."""
    return two_commit_repo(Path(tmp_path) / "gorepo_deps", _INITIAL, _FEAT)


def config() -> RepoConfig:
    return RepoConfig(name="godeps", language=Language.GO, runner="go", belt_scope=BELT_BARE)


__all__ = [
    "APP_PKG",
    "MODULE",
    "SRC_BYE",
    "TEST_BYE",
    "WRITER_TEST_ID",
    "build",
    "config",
    "go_mod",
]
