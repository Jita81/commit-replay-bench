"""JavaScript fixture in four flavours: ``node --test``, ``vitest``, ``jest``, ``mocha``.

``build(tmp_path, tool=...)`` picks the flavour. The shape is identical:

    package.json
    src/calc.js            add            \\  commit 1
    <tests>/calc.test.js   "add works"    /
    src/sub.js             sub            \\  commit 2 (the feat)
    <tests>/sub.test.js    "sub works"    /

where ``<tests>`` is ``__tests__`` (node / jest / vitest — all three discover it
by default) or ``test`` (mocha's default spec dir), so a BARE belt run finds
both files in every flavour. Module system: ESM for vitest (it transforms test
files through vite), CommonJS for the other three (jest needs no ESM flags).

Only ``node --test`` is dependency-free. The other three need ``node_modules``:
pass the session cache from :func:`conftest_langs.npm_cache` as ``node_modules``
and ``build`` symlinks it into the repo (``.gitignore`` hides the link, and
:class:`~crb.core.workspace.Workspace` re-links it into every worktree).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from crb.core.spec import BELT_BARE, Language, RepoConfig

from . import two_commit_repo

TOOLS: tuple[str, ...] = ("node", "vitest", "jest", "mocha")

#: Test ids as each tool's reporter prints them — deliberately the same string.
ADD_TEST_ID = "add works"
SUB_TEST_ID = "sub works"

_TEST_SCRIPT = {
    "node": "node --test",
    "vitest": "vitest run",
    "jest": "jest --ci",
    "mocha": "mocha",
}


def test_dir(tool: str) -> str:
    return "test" if tool == "mocha" else "__tests__"


def is_esm(tool: str) -> bool:
    return tool == "vitest"


def src_module(name: str, body: str, tool: str) -> str:
    """A one-function source module in the flavour's module system."""
    if is_esm(tool):
        return f"export function {name}(a, b) {{\n  return {body};\n}}\n"
    return f'"use strict";\n\nfunction {name}(a, b) {{\n  return {body};\n}}\n\nmodule.exports = {{ {name} }};\n'


def test_module(fn: str, module: str, call: str, expected: str, title: str, tool: str) -> str:
    """A one-test file asserting ``fn(call) === expected``; ``module`` is the src stem."""
    if tool == "node":
        return (
            '"use strict";\n'
            'const test = require("node:test");\n'
            'const assert = require("node:assert/strict");\n'
            f'const {{ {fn} }} = require("../src/{module}");\n\n'
            f'test("{title}", () => {{\n  assert.equal({fn}({call}), {expected});\n}});\n'
        )
    if tool == "jest":
        return (
            '"use strict";\n'
            f'const {{ {fn} }} = require("../src/{module}");\n\n'
            f'test("{title}", () => {{\n  expect({fn}({call})).toBe({expected});\n}});\n'
        )
    if tool == "vitest":
        return (
            'import { expect, test } from "vitest";\n'
            f'import {{ {fn} }} from "../src/{module}.js";\n\n'
            f'test("{title}", () => {{\n  expect({fn}({call})).toBe({expected});\n}});\n'
        )
    if tool == "mocha":
        return (
            '"use strict";\n'
            'const assert = require("node:assert/strict");\n'
            f'const {{ {fn} }} = require("../src/{module}");\n\n'
            f'it("{title}", () => {{\n  assert.equal({fn}({call}), {expected});\n}});\n'
        )
    raise ValueError(f"unknown node tool {tool!r}")


SRC_ADD = "src/calc.js"
SRC_SUB = "src/sub.js"


def test_add(tool: str) -> str:
    return f"{test_dir(tool)}/calc.test.js"


def test_sub(tool: str) -> str:
    return f"{test_dir(tool)}/sub.test.js"


def add_source(tool: str, *, broken: bool = False) -> str:
    return src_module("add", "a + b + 1" if broken else "a + b", tool)


def _package_json(tool: str, *, scripts: Mapping[str, str] | None = None) -> str:
    pkg: dict[str, object] = {
        "name": "calcfix",
        "version": "0.1.0",
        "private": True,
        "scripts": {"test": _TEST_SCRIPT[tool], **(scripts or {})},
    }
    if is_esm(tool):
        pkg["type"] = "module"
    return json.dumps(pkg, indent=2) + "\n"


#: The TypeScript flavour's type-checked module (compiles clean; nothing imports it, so
#: the ``node --test`` belts never see it — only belt 5's ``tsc`` does).
SRC_TYPES = "src/types.ts"
TYPES_OK = "export function describe(n: number): string {\n  return `n=${n}`;\n}\n"
#: The same module with a type error on line 2 (a number assigned to a string).
TYPES_BROKEN = (
    "export function describe(n: number): string {\n  const out: string = n;\n  return out;\n}\n"
)
#: nhsuk-frontend / nhsuk-react-components' script, verbatim (``lint:types`` is the evidence).
LINT_TYPES_NHS = "tsc --build tsconfig.json --pretty"
#: The version-agnostic form the toolchain test runs under a real ``tsc``.
LINT_TYPES_NOEMIT = "tsc --noEmit -p tsconfig.json"


def ts_extra(
    tool: str = "node",
    *,
    lint_types: str = LINT_TYPES_NHS,
    types_source: str = TYPES_OK,
    check_js: bool = False,
) -> dict[str, str]:
    """The ``extra`` that makes the fixture a TypeScript-gated repository in the NHS
    shape: ``tsconfig.json`` (strict, ``noEmit``, ``src/**``), ``package.json`` with a
    ``lint:types`` script, and one ``.ts`` module (``SRC_TYPES``). ``check_js`` turns on
    ``allowJs``/``checkJs`` so the ``.js`` sources are type-checked too (nhsuk-frontend's
    ``tsconfig.base.json`` does)."""
    compiler: dict[str, object] = {
        "strict": True,
        "noEmit": True,
        "target": "ES2022",
        "module": "ESNext",
        "moduleResolution": "Bundler",
        "skipLibCheck": True,
        "types": [],
    }
    if check_js:
        compiler.update({"allowJs": True, "checkJs": True})
    tsconfig = {"compilerOptions": compiler, "include": ["src/**/*"]}
    return {
        "package.json": _package_json(tool, scripts={"lint:types": lint_types}),
        "tsconfig.json": json.dumps(tsconfig, indent=2) + "\n",
        SRC_TYPES: types_source,
    }


def build(
    tmp_path: Path,
    tool: str = "node",
    *,
    node_modules: Path | None = None,
    extra: Mapping[str, str] | None = None,
) -> tuple[Path, str]:
    """``extra`` = more files in the initial commit (a lint config the parent carries)."""
    if tool not in TOOLS:
        raise ValueError(f"tool must be one of {TOOLS}, got {tool!r}")
    initial = {
        "package.json": _package_json(tool),
        ".gitignore": "node_modules\n",
        SRC_ADD: add_source(tool),
        test_add(tool): test_module("add", "calc", "1, 2", "3", ADD_TEST_ID, tool),
        **(extra or {}),
    }
    feat = {
        SRC_SUB: src_module("sub", "a - b", tool),
        test_sub(tool): test_module("sub", "sub", "3, 2", "1", SUB_TEST_ID, tool),
    }
    root, feat_sha = two_commit_repo(Path(tmp_path) / f"noderepo-{tool}", initial, feat)
    if node_modules is not None:
        (root / "node_modules").symlink_to(Path(node_modules).resolve())
    return root, feat_sha


def config(tool: str = "node", belt_scope: str | tuple[str, ...] = BELT_BARE) -> RepoConfig:
    if tool not in TOOLS:
        raise ValueError(f"tool must be one of {TOOLS}, got {tool!r}")
    return RepoConfig(
        name=f"nodefix-{tool}",
        language=Language.JAVASCRIPT,
        runner=tool,
        src_prefix="src/",
        test_prefix=test_dir(tool) + "/",
        ext=".js",
        belt_scope=belt_scope,
    )
