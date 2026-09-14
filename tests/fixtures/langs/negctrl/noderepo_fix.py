"""JavaScript fixture whose feat commit FIXES an existing module, in four flavours.

Same shape and helpers as :mod:`fixtures.langs.noderepo` (``node`` / ``vitest`` /
``jest`` / ``mocha``; ``__tests__`` or ``test``; CommonJS except vitest):

    package.json
    src/calc.js            add                \\  commit 1
    <tests>/calc.test.js   "add works"         |
    src/mul.js             mul  (BUGGY: a + b) /
    src/mul.js             mul  (a * b)       \\  commit 2 (the fix)
    <tests>/mul.test.js    "mul works"        /

Parent + ``mul.test.js`` overlaid → the test LOADS and fails on its assertion
(``mul(3, 2)`` is 5, not 6): RED and attributed by every reporter. That is what
``env_poison`` needs — an existing module whose exports a collection-time hook can
replace with the gold copy.
"""

from __future__ import annotations

from pathlib import Path

from crb.core.spec import BELT_BARE, Language, RepoConfig

from .. import noderepo, two_commit_repo

TOOLS = noderepo.TOOLS
ADD_TEST_ID = noderepo.ADD_TEST_ID
MUL_TEST_ID = "mul works"

SRC_ADD = noderepo.SRC_ADD
SRC_MUL = "src/mul.js"


def test_dir(tool: str) -> str:
    return noderepo.test_dir(tool)


def test_add(tool: str) -> str:
    return noderepo.test_add(tool)


def test_mul(tool: str) -> str:
    return f"{test_dir(tool)}/mul.test.js"


def mul_source(tool: str, *, buggy: bool) -> str:
    return noderepo.src_module("mul", "a + b" if buggy else "a * b", tool)


def build(
    tmp_path: Path, tool: str = "node", *, node_modules: Path | None = None
) -> tuple[Path, str]:
    if tool not in TOOLS:
        raise ValueError(f"tool must be one of {TOOLS}, got {tool!r}")
    initial = {
        "package.json": noderepo._package_json(tool),
        ".gitignore": "node_modules\n",
        SRC_ADD: noderepo.add_source(tool),
        test_add(tool): noderepo.test_module("add", "calc", "1, 2", "3", ADD_TEST_ID, tool),
        SRC_MUL: mul_source(tool, buggy=True),
    }
    feat = {
        SRC_MUL: mul_source(tool, buggy=False),
        test_mul(tool): noderepo.test_module("mul", "mul", "3, 2", "6", MUL_TEST_ID, tool),
    }
    root, feat_sha = two_commit_repo(Path(tmp_path) / f"noderepo-fix-{tool}", initial, feat)
    if node_modules is not None:
        (root / "node_modules").symlink_to(Path(node_modules).resolve())
    return root, feat_sha


def config(tool: str = "node", belt_scope: str | tuple[str, ...] = BELT_BARE) -> RepoConfig:
    if tool not in TOOLS:
        raise ValueError(f"tool must be one of {TOOLS}, got {tool!r}")
    return RepoConfig(
        name=f"nodefix-{tool}-fix",
        language=Language.JAVASCRIPT,
        runner=tool,
        src_prefix="src/",
        test_prefix=test_dir(tool) + "/",
        ext=".js",
        belt_scope=belt_scope,
    )
