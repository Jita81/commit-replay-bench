"""Each writer of an evidence pack has its own temporary file (P-122; ADR-0025 item 13).

``write_pack`` wrote every pack through ``<hash>.json.tmp``, so two processes writing the same
pack (a reclaimed run and its original worker; two runs of one task) raced on one temporary
file, and one could rename the other's half-written bytes into place. The temporary name is
now ``<hash>.json.<pid>.<8 hex>.tmp``: the writer's own.

Navigation
----------
What it is:   The test of the pack writer's temporary name.
What it does: Pins that the temporary file is named for its process and a random token, that
              two writes of one pack never share a temporary path, that nothing is left behind,
              and that the stored pack is the pack's canonical JSON under its hash.
How:          ``write_pack`` on a hand-built pack, observing ``Path.replace``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md; ADR-0025 item 13
Works with:   src/crb/core/run.py (``write_pack``), src/crb/core/evidence.py (the pack),
              docs/PREVENTION.md (P-122, the row this test closes)
Tested by:    tests/test_write_pack.py
Touch when:   never for a new repository; the pack store changes how it writes.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest

from crb.core import grade as g
from crb.core.evidence import ApparatusStamp, EvidencePack
from crb.core.run import write_pack
from crb.core.spec import TaskSpec


def _pack() -> EvidencePack:
    task = TaskSpec(
        task_id="a" * 40,
        repo="r",
        subject="s",
        authored="2026-01-01T00:00:00+00:00",
        test_files=("tests/t.py",),
        src_files=("x.py",),
        target_tests=("tests/t.py",),
        belt_scope=("tests/",),
    )
    grade = g.GradeResult("a" * 40, "r", "sighted", clean=False, belts=g.Belts(True))
    return EvidencePack(
        task=task, grade=grade, apparatus=ApparatusStamp(runner="pytest"), run_id="run"
    )


def test_every_pack_write_has_a_temporary_file_of_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pack = _pack()
    seen: list[Path] = []
    real_replace = Path.replace

    def replace(self: Path, target: Any) -> Any:
        seen.append(self)
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", replace)
    first = write_pack(pack, tmp_path / "a")
    second = write_pack(pack, tmp_path / "b")
    assert len(seen) == 2
    for tmp in seen:
        assert re.fullmatch(rf"{pack.pack_hash}\.json\.{os.getpid()}\.[0-9a-f]{{8}}\.tmp", tmp.name)
    assert seen[0].name != seen[1].name  # the random token differs even in one process
    for path in (first, second):
        assert path.name == f"{pack.pack_hash}.json"
        assert path.read_text(encoding="utf-8") == pack.to_json()
        assert [p.name for p in path.parent.iterdir()] == [path.name]  # nothing left behind
