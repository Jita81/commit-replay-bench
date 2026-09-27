"""Replay's ``S1`` arm: the factory's own path, replayed against real held-out tests.

Navigation
----------
What it is:   The suite for the replay ``S1`` arm (G-934, ``product.truth.216``; ADR-0026 item
              1): a test author on a model other than the builder's writes one failing test in
              a sealed one-commit checkout of the parent, it must be RED there, the builder
              builds against it, and the grade is the commit's held-out tests with the
              authored test removed first.
What it does: Pins that the author works in a checkout holding one commit and no target test
              file; that the builder is shown the authored test and never the held-out one;
              that the authored test is gone before the grade (a test that would still fail
              after the change, left in place, would fail the regression belt); that an
              authoring failure — a test green at the parent, an author that raises — is an
              ``authoring`` row that counts against the arm and never against the builder or
              the harness; and that ``POST /runs`` takes ``arm: S1`` on a blind run only.
How:          ``pyrepo``'s feat commit replayed blind through ``crb.core.run.run`` with a
              recording builder that applies the commit's own patch and a scripted author.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md
Works with:   src/crb/builders/adapter.py (the S1 step), src/crb/builders/brief.py
              (``S1Arm``), src/crb/core/ledger.py (the ``authoring`` failure kind),
              src/crb/server/worker.py (``_s1_arm``), src/crb/server/routes/runs.py (``arm`` on
              ``POST /runs``)
Tested by:    tests/test_replay_s1_arm.py
Touch when:   the S1 arm's steps change (an ADR-0026 amendment).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

import crb.builders as builders_pkg
from crb.builders.brief import LABEL_CONTEXT_ARM, LABEL_CTX_AUTHOR, S1Arm
from crb.core.ledger import FAILURE_AUTHORING, cell_stats, derive_failure_kind
from fixtures import pyrepo as pr
from fixtures.server_seed import ALPHA, envelope, login, make_env
from test_builders_brief import Recorder, _replay


@pytest.fixture(autouse=True)
def _register(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(builders_pkg._REGISTRY, "rec", Recorder)
    Recorder.briefs = []


#: A test that is RED at the parent and STILL RED after the commit's own change (the commit
#: adds `subtract`, not `multiply`): left in the worktree it would fail the regression belt.
AUTHORED = "tests/test_s1_multiply.py"
AUTHORED_SRC = (
    "from calc import multiply\n\n\ndef test_multiply():\n    assert multiply(3, 4) == 12\n"
)


def test_the_s1_arm_authors_in_the_sealed_parent_checkout_and_grades_on_the_held_out_tests(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}

    def author(ws: Any, subject: str, message: str) -> tuple[str, str]:
        root = Path(ws.root)
        count = subprocess.run(
            ["git", "-C", str(root), "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        seen["commits"] = count
        seen["target_test_present"] = (root / "tests" / "test_subtract.py").exists()
        seen["commit_reachable"] = (
            subprocess.run(
                ["git", "-C", str(root), "cat-file", "-e", pyrepo.feat_task().task_id],
                capture_output=True,
            ).returncode
            == 0
        )
        seen["subject"] = subject
        return AUTHORED, AUTHORED_SRC

    rows, summary = _replay(
        pyrepo, tmp_path, s1=S1Arm(author=author, author_model="t1", author_stamp="fake-author")
    )
    assert seen == {
        "commits": "1",
        "target_test_present": False,
        "commit_reachable": False,
        "subject": pyrepo.feat_task().subject,
    }
    (brief,) = Recorder.briefs
    assert brief.sighted and brief.test_files == (AUTHORED,)
    assert "tests/test_subtract.py" not in brief.test_files + brief.target_tests
    (row,) = rows
    # the grade is the commit's held-out test, and the authored test (still failing after
    # the change) was gone before it: the row is clean
    assert row.mode == "blind" and row.clean and summary.clean == 1
    assert row.labels[LABEL_CONTEXT_ARM] == "S1@t1"
    assert row.labels[LABEL_CTX_AUTHOR] == "fake-author"


def test_an_authoring_failure_counts_against_the_arm_never_the_builder(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """No RED test at the parent → an ``authoring`` row: in the arm's n, never clean, not a
    model failure and not a harness failure. The builder is never called."""
    green = "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"

    def author(ws: Any, subject: str, message: str) -> tuple[str, str]:
        return "tests/test_s1_add.py", green

    rows, _ = _replay(pyrepo, tmp_path / "green", s1=S1Arm(author=author, author_model="t1"))
    (row,) = rows
    assert Recorder.briefs == []
    assert row.failure_kind == FAILURE_AUTHORING and not row.clean
    assert "is not RED at the parent" in row.error
    assert row.labels[LABEL_CONTEXT_ARM] == "S1@t1"
    stats = cell_stats(rows)
    assert (stats.n, stats.clean, stats.model_n, stats.n_harness) == (1, 0, 0, 0)

    def raising(ws: Any, subject: str, message: str) -> tuple[str, str]:
        raise RuntimeError("the model said no")

    rows2, _ = _replay(pyrepo, tmp_path / "raise", s1=S1Arm(author=raising, author_model="t1"))
    assert rows2[0].failure_kind == FAILURE_AUTHORING
    # the rule, pinned: the adapter's prefix is the ledger's
    assert derive_failure_kind(clean=False, disqualified=False, error="authoring: x") == "authoring"


def test_post_runs_takes_arm_s1_on_a_blind_run_only(tmp_path: Path) -> None:
    with make_env(tmp_path) as env:
        login(env.client, "operator")
        body = {"repo": ALPHA, "kind": "replay", "builder": "fixture_gold", "model": "gold"}
        r = env.post("/runs", json={**body, "arm": "S1"})
        assert r.status_code == 422 and "blind runs only" in envelope(r)["message"]
        r = env.post(
            "/runs",
            json={
                **body,
                "kind": "blind",
                "arm": "S1",
                "test_author": "claude_code:claude-haiku-4",
            },
        )
        assert r.status_code == 201, r.text
        with env.factory() as s:
            from crb.store.models import Run

            run = s.get(Run, r.json()["id"])
            assert run is not None
            assert run.params_json["arm"] == "S1"
            assert run.params_json["test_author"] == "claude_code:claude-haiku-4"


def test_the_s1_author_is_never_a_build_rungs_model(pyrepo: pr.PyRepo) -> None:
    """DL-050, DL-059 C3: the worker refuses an ``S1`` replay whose test author shares a
    model with a build rung — the same identity check the factory applies — and one with no
    author, or on a sighted run, before anything is built."""
    from crb.builders.base import EscalationLadder, Rung
    from crb.factory.testfirst import SameIdentityError
    from crb.observability.events import MemorySink
    from test_worker_test_author import _ctx, _worker

    ladder = EscalationLadder((Rung("editblock", "gpt-oss-120b"),))
    sink = MemorySink()
    same = _ctx(pyrepo, sink, arm="S1", test_author="openai_agent:gpt-oss-120b")
    with pytest.raises(SameIdentityError):
        _worker()._s1_arm(same, ladder, "blind")
    with pytest.raises(ValueError, match="needs a test author"):
        _worker()._s1_arm(_ctx(pyrepo, sink, arm="S1"), ladder, "blind")
    other = _ctx(pyrepo, sink, arm="S1", test_author="editblock:qwen-3-coder")
    with pytest.raises(ValueError, match="blind replay"):
        _worker()._s1_arm(other, ladder, "sighted")
    arm = _worker()._s1_arm(other, ladder, "blind")
    assert arm is not None and arm.arm.startswith("S1@") and "qwen" in arm.arm
    assert _worker()._s1_arm(_ctx(pyrepo, sink), ladder, "blind") is None
