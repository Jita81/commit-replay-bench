"""Rust fixture: cargo package ``calc`` with a lib, a unit test and integration tests.

Layout::

    Cargo.toml / Cargo.lock   (no dependencies; the lockfile is committed so a
                               build never dirties the worktree)
    src/lib.rs      add + #[cfg(test)] unit test      \\  commit 1
    tests/calc.rs   integration test for add          /
    src/sub.rs      sub                               \\  commit 2 (the feat):
    src/lib.rs      + ``pub mod sub;``                 |  lib.rs is MODIFIED, sub.rs
    tests/sub.rs    integration test for sub          /   and tests/sub.rs are NEW

Cargo's target scope is the integration-test *binary* (``tests/sub.rs`` →
``--test sub``); the belt is the whole ``cargo test``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from crb.core.spec import BELT_BARE, Language, RepoConfig

from . import FEAT_SUBJECT, INITIAL_SUBJECT, commit_all, init_repo, write_files

SRC_LIB = "src/lib.rs"
SRC_SUB = "src/sub.rs"
TEST_CALC = "tests/calc.rs"
TEST_SUB = "tests/sub.rs"

#: Test ids as the cargo harness prints them (unit tests carry their module path).
UNIT_ADD_ID = "tests::add_unit"
INTEGRATION_ADD_ID = "add_integration"
INTEGRATION_SUB_ID = "sub_integration"

_CARGO_TOML = '[package]\nname = "calc"\nversion = "0.1.0"\nedition = "2021"\n\n[dependencies]\n'

LIB_INITIAL = (
    "/// Returns a + b.\n"
    "pub fn add(a: i64, b: i64) -> i64 {\n    a + b\n}\n\n"
    "#[cfg(test)]\nmod tests {\n"
    "    #[test]\n    fn add_unit() {\n        assert_eq!(super::add(1, 2), 3);\n    }\n"
    "}\n"
)
LIB_FEAT = "pub mod sub;\n\n" + LIB_INITIAL
LIB_BROKEN = LIB_FEAT.replace("    a + b\n", "    a + b + 1\n")

_INITIAL = {
    "Cargo.toml": _CARGO_TOML,
    ".gitignore": "target\n",
    SRC_LIB: LIB_INITIAL,
    TEST_CALC: "#[test]\nfn add_integration() {\n    assert_eq!(calc::add(2, 2), 4);\n}\n",
}

_FEAT = {
    SRC_LIB: LIB_FEAT,
    SRC_SUB: "/// Returns a - b.\npub fn sub(a: i64, b: i64) -> i64 {\n    a - b\n}\n",
    TEST_SUB: "#[test]\nfn sub_integration() {\n    assert_eq!(calc::sub::sub(3, 2), 1);\n}\n",
}


def build(tmp_path: Path) -> tuple[Path, str]:
    root = Path(tmp_path) / "rustrepo"
    init_repo(root)
    write_files(root, _INITIAL)
    # Commit the lockfile: cargo would otherwise create it on first build and the
    # untracked file would read as a source change (belt 4) in every worktree.
    subprocess.run(
        ["cargo", "generate-lockfile", "--offline", "--quiet"],
        cwd=root,
        env={**os.environ, "CARGO_TERM_COLOR": "never"},
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    commit_all(root, INITIAL_SUBJECT)
    write_files(root, _FEAT)
    feat_sha = commit_all(root, FEAT_SUBJECT)
    return root, feat_sha


def config(belt_scope: str | tuple[str, ...] = BELT_BARE) -> RepoConfig:
    return RepoConfig(
        name="rustfix",
        language=Language.RUST,
        runner="cargo",
        belt_scope=belt_scope,
        runner_opts={"offline": True},
    )
