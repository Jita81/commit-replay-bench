"""Node fixture WITH a locked dependency: ``src`` requires ``cfxdep`` from ``package-lock.json``.

The parent locks ``cfxdep@1.0.0`` and the feat (gold) commit locks ``cfxdep@1.1.0`` and adds
``src/bye.js``, which calls ``farewell`` — only ``1.1.0`` exports it. The tests run under
``node --test`` (in the shipped Node sandbox image), so no test tool is itself a dependency.

Layout::

    package.json, package-lock.json   cfxdep 1.0.0 (lockfileVersion 3)    \\  commit 1
    src/core.js                       hello() → cfxdep.greet()              |
    __tests__/core.test.js            hello                                /
    package.json, package-lock.json   cfxdep 1.1.0                         \\  commit 2 (the feat)
    src/bye.js                        bye() → cfxdep.farewell()             |
    __tests__/bye.test.js             bye                                  /

Navigation
----------
What it is:   The Node fixture with a locked third-party dependency whose version the feat
              commit bumps.
What it does: Builds the two-commit repository whose parent and gold lockfiles select
              different sealed ``node_modules`` sets, for the Node recipe's daemon test.
How:          ``two_commit_repo`` over inline sources; ``integrity`` from ``pkgmirror.integrity``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   tests/fixtures/pkgmirror.py (the tarballs it locks), tests/fixtures/langs/__init__.py
              (the two-commit shape), tests/test_provision_node.py (the consumer)
Tested by:    tests/test_provision_node.py
Touch when:   the Node recipe needs another lock shape (a scoped package, a named install script).
"""

from __future__ import annotations

import json
from pathlib import Path

from crb.core.spec import BELT_BARE, Language, RepoConfig

from .. import pkgmirror
from . import two_commit_repo

SRC_BYE = "src/bye.js"
TEST_BYE = "__tests__/bye.test.js"
NAME = "noderepo-deps"


def package_json(version: str) -> str:
    return json.dumps(
        {"name": NAME, "version": "1.0.0", "devDependencies": {pkgmirror.NAME: version}}, indent=2
    )


def package_lock(version: str) -> str:
    return json.dumps(
        {
            "name": NAME,
            "version": "1.0.0",
            "lockfileVersion": 3,
            "requires": True,
            "packages": {
                "": {
                    "name": NAME,
                    "version": "1.0.0",
                    "devDependencies": {pkgmirror.NAME: version},
                },
                f"node_modules/{pkgmirror.NAME}": {
                    "version": version,
                    "resolved": f"https://registry.npmjs.org/{pkgmirror.NAME}/-/{pkgmirror.tarball_name(version)}",
                    "integrity": pkgmirror.integrity(version),
                    "dev": True,
                },
            },
        },
        indent=2,
    )


_TEST = (
    '"use strict";\nconst test = require("node:test");\nconst assert = require("node:assert");\n'
)

_INITIAL = {
    "package.json": package_json("1.0.0"),
    "package-lock.json": package_lock("1.0.0"),
    "src/core.js": f'const dep = require("{pkgmirror.NAME}");\nexports.hello = () => dep.greet();\n',
    "__tests__/core.test.js": _TEST
    + 'const { hello } = require("../src/core");\n'
    + 'test("hello", () => assert.strictEqual(hello(), "hello"));\n',
}

_FEAT = {
    "package.json": package_json("1.1.0"),
    "package-lock.json": package_lock("1.1.0"),
    SRC_BYE: f'const dep = require("{pkgmirror.NAME}");\nexports.bye = () => dep.farewell();\n',
    TEST_BYE: _TEST
    + 'const { bye } = require("../src/bye");\n'
    + 'test("bye", () => assert.strictEqual(bye(), "goodbye"));\n',
}


def build(tmp_path: Path) -> tuple[Path, str]:
    return two_commit_repo(Path(tmp_path) / "noderepo_deps", _INITIAL, _FEAT)


def config() -> RepoConfig:
    return RepoConfig(
        name="nodedeps",
        language=Language.JAVASCRIPT,
        runner="node",
        src_prefix="src/",
        test_prefix="__tests__/",
        ext=".js",
        belt_scope=BELT_BARE,
    )


__all__ = ["NAME", "SRC_BYE", "TEST_BYE", "build", "config", "package_json", "package_lock"]
