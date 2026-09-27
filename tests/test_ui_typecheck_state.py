"""The UI type-check keeps its incremental state inside the checkout it checks (P-150).

``npm run typecheck`` is ``tsc -b``: a build-mode check that skips work its ``.tsbuildinfo``
says is up to date. That file lived under ``ui/node_modules/.tmp/``. A worktree set up the way
this repository's agents are told to — ``ui/node_modules`` a symlink to one shared install —
therefore shared ONE build-info file with every other checkout, and on 2026-09-27 the check
passed on a tree with a type error in ``FactoryPage.test.tsx`` (commit 6cbdecc on
``feat/ns4-s``); a later run of the same command on the same tree found it. A gate that can
pass on a tree it did not check is not a gate. The build info now lives in ``ui/.tsbuild/``,
inside the checkout and ignored by git, so no two checkouts can share it.

Navigation
----------
What it is:   The guard that the UI type-check's incremental state belongs to one checkout.
What it does: Reads every ``ui/tsconfig*.json`` that sets ``tsBuildInfoFile`` and fails
              when that path runs through ``node_modules`` (shared when it is a symlink) or
              leaves the ``ui/`` directory, and when ``ui/.gitignore`` does not ignore it.
How:          ``json`` over the tsconfig files (they carry no comments); a path check.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   ui/tsconfig.app.json and ui/tsconfig.node.json (where ``tsBuildInfoFile`` is
              set), ui/.gitignore (ignores ``ui/.tsbuild/``), docs/PREVENTION.md (P-150)
Tested by:    (this is a test file)
Touch when:   never for a new repository (the UI's own build settings); a new tsconfig with
              build info is added, or the type-check stops being ``tsc -b``.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

UI = Path(__file__).resolve().parent.parent / "ui"


def _build_info_paths() -> dict[str, str]:
    out: dict[str, str] = {}
    for cfg in sorted(UI.glob("tsconfig*.json")):
        opts = json.loads(cfg.read_text(encoding="utf-8")).get("compilerOptions", {})
        if "tsBuildInfoFile" in opts:
            out[cfg.name] = str(opts["tsBuildInfoFile"])
    return out


def test_every_build_info_file_lives_in_this_checkout_and_never_under_node_modules() -> None:
    paths = _build_info_paths()
    assert paths, "tsc -b keeps a build-info file; a tsconfig should name where"
    for name, raw in paths.items():
        p = PurePosixPath(raw)
        assert "node_modules" not in p.parts, (
            f"{name}: {raw} sits under node_modules, which a worktree may share by symlink — "
            "the type-check would then skip a tree it never checked (P-150)"
        )
        assert ".." not in p.parts and not p.is_absolute(), f"{name}: {raw} leaves ui/"


def test_the_build_info_directory_is_ignored_by_git() -> None:
    ignored = {
        line.strip().rstrip("/")
        for line in (UI / ".gitignore").read_text(encoding="utf-8").splitlines()
    }
    for name, raw in _build_info_paths().items():
        top = PurePosixPath(raw).parts[0]  # "./.tsbuild/x" normalises to (".tsbuild", "x")
        assert top in ignored, f"{name}: {top} is not in ui/.gitignore"
