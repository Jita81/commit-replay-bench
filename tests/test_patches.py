"""crb.core.patches — every graded attempt keeps its patch, redacted, content-addressed.

Navigation
----------
What it is:   The regression suite for the patch store (value programme stream K, leak 1: the
              2026-09-25 export had 0 of 190 clean patches retrievable).
What it does: Pins that a replay attempt — clean or red — keeps the grader's own patch text
              under the hash of its stored bytes, that the pack's ``notes.patch`` commits to it,
              that the full-text hash equals the grade's diff anchor, that redaction and the
              cap are recorded, that a damaged file is never read back, that a store failure
              never changes a grade, and that a spec without a store keeps nothing (old rows).
How:          ``run_task`` over the ``pyrepo`` fixture with a gold / a wrong edit / a no-op
              build; the pack JSON is read back from the evidence directory.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md
Works with:   src/crb/core/patches.py (under test), src/crb/core/run.py (keeps the patch before
              the pack), src/crb/core/workspace.py (``patch_text`` is ``diff_stats``' text),
              tests/test_server_routes_grades.py (the route that serves the kept bytes)
Tested by:    tests/test_patches.py
Touch when:   the patch note or the store layout changes; ``Workspace.diff_stats`` changes what
              it hashes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from crb.core.evidence import BuilderRef
from crb.core.execution import LocalExecutor
from crb.core.ledger import JsonlLedger
from crb.core.patches import (
    NOTE_KEY,
    PatchStore,
    keep_patch,
    kept_patch_note,
    prepare,
)
from crb.core.run import BuildAttempt, RunSpec, run_task
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import TaskSpec
from crb.core.workspace import Workspace
from fixtures import pyrepo as pr


def _spec(
    pyrepo: pr.PyRepo,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp: Path,
    *,
    store: bool = True,
) -> RunSpec:
    return RunSpec(
        run_id="run-patches",
        config=pyrepo.config,
        runner=runner,
        executor=executor,
        scratch=tmp / "scratch",
        ledger=JsonlLedger(tmp / "ledger.jsonl"),
        evidence_dir=tmp / "evidence",
        patch_store=PatchStore.under(tmp / "evidence") if store else None,
    )


def _attempt() -> BuildAttempt:
    return BuildAttempt(BuilderRef(name="fixture", model="m", provider="p", mode="sighted"))


def _pack(tmp: Path, pack_hash: str) -> dict[str, object]:
    return json.loads((tmp / "evidence" / f"{pack_hash}.json").read_text(encoding="utf-8"))


def test_a_clean_attempt_keeps_the_exact_patch_the_grader_hashed(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
) -> None:
    def build_fn(ws: Workspace, task: TaskSpec, mode: str, rung: str) -> BuildAttempt:
        pr.apply_gold(ws)
        return _attempt()

    outcome = run_task(_spec(pyrepo, runner, executor, tmp_path), pyrepo.repo, feat_task, build_fn)
    (row,) = outcome.rows
    assert row.clean
    pack = _pack(tmp_path, row.evidence_pack_hash)
    note = kept_patch_note(pack)
    diff_anchor = pack["grade"]["diff"]["diff_sha256"]  # type: ignore[index]
    assert note["sha256"] == diff_anchor and note["anchored"] is True
    data = PatchStore.under(tmp_path / "evidence").get(str(note["stored_sha256"]))
    assert data is not None
    # the worktree is gone (retain.worktrees was off) — the kept bytes are the only copy
    assert not any((tmp_path / "scratch").glob("run-*"))
    assert hashlib.sha256(data).hexdigest() == diff_anchor  # nothing to redact here
    assert pr.SRC in data.decode("utf-8") and note["redacted"] is False
    assert note["truncated"] is False and note["bytes"] == len(data)


def test_a_red_attempt_keeps_its_patch_too_anchored_by_the_pack_alone(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
) -> None:
    def build_fn(ws: Workspace, task: TaskSpec, mode: str, rung: str) -> BuildAttempt:
        with (ws.root / pr.SRC).open("a", encoding="utf-8") as fh:
            fh.write("\n# a wrong attempt\n")
        return _attempt()

    outcome = run_task(_spec(pyrepo, runner, executor, tmp_path), pyrepo.repo, feat_task, build_fn)
    (row,) = outcome.rows
    assert not row.clean and not row.disqualified
    note = kept_patch_note(_pack(tmp_path, row.evidence_pack_hash))
    assert note["anchored"] is None  # the grade stopped before hashing a diff
    data = PatchStore.under(tmp_path / "evidence").get(str(note["stored_sha256"]))
    assert data is not None and b"a wrong attempt" in data


def test_a_spec_without_a_store_keeps_nothing_and_its_pack_says_nothing(
    pyrepo: pr.PyRepo,
    feat_task: TaskSpec,
    runner: PytestRunner,
    executor: LocalExecutor,
    tmp_path: Path,
) -> None:
    def build_fn(ws: Workspace, task: TaskSpec, mode: str, rung: str) -> BuildAttempt:
        pr.apply_gold(ws)
        return _attempt()

    outcome = run_task(
        _spec(pyrepo, runner, executor, tmp_path, store=False), pyrepo.repo, feat_task, build_fn
    )
    (row,) = outcome.rows
    pack = _pack(tmp_path, row.evidence_pack_hash)
    assert NOTE_KEY not in pack["notes"]  # type: ignore[operator]
    assert not (tmp_path / "evidence" / "patches").exists()


def test_the_store_is_content_addressed_and_refuses_a_damaged_file(tmp_path: Path) -> None:
    store = PatchStore(tmp_path / "patches")
    kept = store.put("diff --git a/x b/x\n+one\n")
    assert kept.stored_sha256 == kept.sha256  # nothing redacted, nothing cut
    again = store.put("diff --git a/x b/x\n+one\n")
    assert again.stored_sha256 == kept.stored_sha256  # stored once
    path = store.path_for(kept.stored_sha256)
    assert path.name == f"{kept.stored_sha256}.diff"
    assert store.get(kept.stored_sha256) == b"diff --git a/x b/x\n+one\n"
    path.write_bytes(b"diff --git a/x b/x\n+two\n")  # damaged / tampered on disk
    assert store.get(kept.stored_sha256) is None
    assert store.get("not-a-hash") is None


def test_redaction_and_the_cap_are_applied_after_hashing_and_recorded(tmp_path: Path) -> None:
    secret = "+token = ghp_" + "a" * 36 + "\n"
    text = "diff --git a/cfg b/cfg\n" + secret + "+" + "x" * 5000 + "\n"
    full_sha, raw, redacted, truncated = prepare(text, cap=1000)
    assert full_sha == hashlib.sha256(text.encode()).hexdigest()  # the full text's hash
    assert redacted and truncated and len(raw) <= 1000
    assert b"ghp_" not in raw
    kept = PatchStore(tmp_path).put(text, cap=1000, diff_sha256=full_sha)
    assert kept.anchored is True and kept.redacted and kept.truncated
    assert kept.stored_sha256 != kept.sha256
    assert PatchStore(tmp_path).get(kept.stored_sha256) == raw


def test_keeping_a_patch_never_raises_into_the_grade(tmp_path: Path) -> None:
    class Broken:
        def patch_text(self) -> str:
            raise OSError("disk gone")

    note = keep_patch(Broken(), PatchStore(tmp_path))  # type: ignore[arg-type]
    assert note == {"error": "OSError: disk gone"}


@pytest.mark.parametrize("pack", [None, {}, {"notes": {}}, {"notes": {"patch": "x"}}])
def test_a_pack_without_a_patch_note_reads_as_empty(pack: dict[str, object] | None) -> None:
    assert kept_patch_note(pack) == {}
