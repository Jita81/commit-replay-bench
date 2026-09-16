"""``crb.core`` imports nothing but the standard library and itself — checked positively.

Navigation
----------
What it is:   The positive form of ADR-0008's first rule: every ``import`` in ``src/crb/core``
              resolves to the standard library or to ``crb.core`` itself.
What it does: Walks every module under ``src/crb/core`` with ``ast``, collects the top-level
              name of each ``import`` / ``from … import``, and asserts it is in
              ``sys.stdlib_module_names`` or is ``crb.core``. A ``crb.builders`` / ``uvicorn``
              / ``psycopg`` import fails here whether or not import-linter's ``forbidden`` list
              names it — that contract only rejects what it lists (CodeRabbit on PR #5,
              2026-09-16); this one rejects everything it does not allow.
How:          ``ast.walk`` over each file; ``TYPE_CHECKING``-guarded imports are checked too
              (a typing-only dependency on the store is still a dependency the layer must not
              have).
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0008-stdlib-core-and-downward-layers.md
Works with:   pyproject.toml (the import-linter contracts this complements), src/crb/core/
              (the layer under test), docs/CONTRIBUTING.md (the layering rule for contributors)
Tested by:    tests/test_core_is_stdlib_only.py
Touch when:   a stdlib module is intentionally shadowed by a vendored copy under ``crb.core``
              (add it to ``ALLOWED_EXTRA``), never to let a third-party package into the core.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "src" / "crb" / "core"
#: Names allowed beyond the standard library: the layer itself.
ALLOWED_EXTRA: frozenset[str] = frozenset({"crb"})


def _top_level_imports(path: Path) -> set[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[tuple[str, int]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add((node.module, node.lineno))
    return found


def test_every_core_import_is_stdlib_or_core_itself() -> None:
    offenders: list[str] = []
    files = sorted(CORE.rglob("*.py"))
    assert len(files) > 20, "crb.core not found where expected"
    for f in files:
        for name, line in _top_level_imports(f):
            top = name.split(".")[0]
            if top in sys.stdlib_module_names:
                continue
            if top in ALLOWED_EXTRA and name.startswith("crb.core"):
                continue
            offenders.append(f"{f.relative_to(CORE.parents[1])}:{line}: {name}")
    assert not offenders, "crb.core must import only the standard library:\n" + "\n".join(offenders)
