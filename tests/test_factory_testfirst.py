"""crb.factory.testfirst — a test that is green at base is refused; RED is proven, hashed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from crb.core.execution import LocalExecutor
from crb.core.runners import base as rb
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import RepoConfig
from crb.core.workspace import Workspace
from crb.factory import testfirst as tf
from crb.factory.backlog import BacklogItem
from fixtures import pyrepo as pr
from test_factory_build import (
    OPERATOR,
    TEST_MULTIPLY,
    TEST_MULTIPLY_GREEN,
    TEST_MULTIPLY_SRC,
    Harness,
    authored_multiply,
    harness,
    multiply_item,
)

__all__ = ["harness"]  # the fixture is imported by name (pytest discovers it here)


def test_authored_test_validation_and_hash() -> None:
    a = authored_multiply()
    assert len(a.sha256) == 64 and a.operator_authored
    assert a.to_dict() == {"path": TEST_MULTIPLY, "sha256": a.sha256, "author": OPERATOR}
    with pytest.raises(ValueError):
        tf.AuthoredTest("/abs/test.py", "def test_x(): pass", OPERATOR)
    with pytest.raises(ValueError):
        tf.AuthoredTest("tests/../x.py", "def test_x(): pass", OPERATOR)
    with pytest.raises(ValueError):
        tf.AuthoredTest(TEST_MULTIPLY, "   ", OPERATOR)
    with pytest.raises(ValueError):
        tf.AuthoredTest(TEST_MULTIPLY, "def test_x(): pass", "")


def test_identity_check_is_case_and_space_insensitive() -> None:
    tf.assert_distinct_identity("operator:po", "fake:good")
    with pytest.raises(tf.SameIdentityError):
        tf.assert_distinct_identity("fake:good", " Fake:GOOD ")
    with pytest.raises(tf.SameIdentityError):
        tf.assert_distinct_identity("", "fake:good")


def test_worktree_at_head_has_no_commit_parent(harness: Harness, tmp_path: Path) -> None:
    ws = tf.worktree_at(harness.repo.repo, "HEAD", tmp_path / "wt", config=harness.repo.config)
    try:
        assert ws.sha == ws.parent == harness.head
        assert ws.exists(pr.README) and ws.exists(pr.SRC)
        assert ws.touched_files() == []
    finally:
        ws.remove()
    assert not (tmp_path / "wt").exists()


def test_prove_red_records_failing_ids_hash_and_base(harness: Harness) -> None:
    item, authored = multiply_item(), authored_multiply()
    events: list[tuple[str, dict[str, Any]]] = []
    proof = tf.prove_red(
        harness.repo.repo,
        item,
        authored,
        config=harness.repo.config,
        runner=harness.runner,
        executor=harness.executor,
        scratch=harness.scratch,
        on_event=lambda a, p: events.append((a, dict(p))),
    )
    assert proof.item_id == "I-1" and proof.test_path == TEST_MULTIPLY
    assert proof.test_sha256 == authored.sha256
    assert proof.base_sha == harness.head
    assert proof.failing_ids and all(TEST_MULTIPLY in f for f in proof.failing_ids)
    assert proof.runner == "pytest" and proof.executor == {"executor": "local"}
    assert proof.target_scope == (TEST_MULTIPLY,)
    assert proof.author == OPERATOR and not proof.existed_at_base
    assert [a for a, _ in events] == ["red.start", "red.proved"]
    # round-trips and never carries a secret
    back = tf.RedProof.from_dict(json.loads(json.dumps(proof.to_dict())))
    assert back.to_dict() == proof.to_dict()
    # the proving worktree is gone; HEAD did not move; the repo is clean
    assert not any(harness.scratch.glob("red-*"))
    assert harness.repo.repo.rev_parse("HEAD") == proof.base_sha
    assert harness.repo.repo.run("status", "--porcelain").stdout.strip() == ""


def test_green_at_base_is_refused(harness: Harness) -> None:
    item = multiply_item()
    with pytest.raises(tf.NotRed, match="GREEN at base"):
        harness.prove(item, tf.AuthoredTest(TEST_MULTIPLY, TEST_MULTIPLY_GREEN, OPERATOR))
    # the existing, already-green test file is refused too
    with pytest.raises(tf.NotRed, match="GREEN at base"):
        harness.prove(item, tf.AuthoredTest(pr.TEST_CALC, pr.TEST_CALC_SRC, OPERATOR))


def test_non_test_path_and_malformed_oracle_are_refused(harness: Harness) -> None:
    item = multiply_item()
    with pytest.raises(tf.NotRed, match="not a test path"):
        harness.prove(item, tf.AuthoredTest("src/calc/test_x.py", TEST_MULTIPLY_SRC, OPERATOR))
    with pytest.raises(tf.NotRed, match="malformed oracle"):
        harness.prove(item, tf.AuthoredTest(TEST_MULTIPLY, "x = 1\n", OPERATOR))


def test_timeout_and_unattributed_failure_fail_closed(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    item, authored = multiply_item(), authored_multiply()

    def timed_out(*a: Any, **k: Any) -> rb.TestRun:
        return rb.TestRun(124, frozenset(), "…", True, 1.0)

    monkeypatch.setattr(PytestRunner, "run", timed_out)
    with pytest.raises(tf.NotRed, match="timed out"):
        harness.prove(item, authored)

    def unattributed(*a: Any, **k: Any) -> rb.TestRun:
        return rb.TestRun(2, frozenset(), "boom", False, 0.1, "unattributed failure (rc=2)")

    monkeypatch.setattr(PytestRunner, "run", unattributed)
    with pytest.raises(tf.NotRed, match="attributable"):
        harness.prove(item, authored)

    def explodes(*a: Any, **k: Any) -> rb.TestRun:
        raise RuntimeError("runner crashed")

    monkeypatch.setattr(PytestRunner, "run", explodes)
    with pytest.raises(tf.NotRed, match="harness error"):
        harness.prove(item, authored)


def test_red_proof_needs_failing_ids() -> None:
    with pytest.raises(tf.NotRed):
        tf.RedProof("I", "t.py", "0" * 64, (), "pytest", {}, "a" * 40, ("t.py",), OPERATOR)


class _Author:
    name = "author"
    model = "m1"
    provider = "fake"

    def author(
        self,
        workspace: Workspace,
        item: BacklogItem,
        *,
        facts: dict[str, str],
        config: RepoConfig,
        on_event: Any = None,
    ) -> tf.AuthoredTest:
        # a stray source edit here must NOT leak into the proof
        (workspace.root / pr.SRC).write_text("broken = True\n", encoding="utf-8")
        return tf.AuthoredTest(TEST_MULTIPLY, TEST_MULTIPLY_SRC, "whatever-the-author-claims")

    def describe(self) -> dict[str, Any]:
        return {"author": self.name}


def test_author_test_runs_in_disposable_worktree_and_stamps_identity(harness: Harness) -> None:
    item = multiply_item()
    res = tf.author_test(
        harness.repo.repo,
        item,
        _Author(),
        facts={"reproduction": "ImportError"},
        config=harness.repo.config,
        scratch=harness.scratch,
    )
    assert res.author == "author:m1" and res.authored.author == "author:m1"
    assert res.authored.sha256 == authored_multiply().sha256
    assert not any(harness.scratch.glob("author-*"))
    # the proof runs in ANOTHER fresh worktree: the author's stray source edit is gone
    proof = harness.prove(item, res.authored)
    assert proof.author == "author:m1"
    assert harness.repo.repo.show_file(proof.base_sha, pr.SRC) == pr.SRC_FEAT


def test_executor_fixture_is_local(executor: LocalExecutor) -> None:
    assert executor.describe() == {"executor": "local"}
