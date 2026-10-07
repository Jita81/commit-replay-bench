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
              the harness, unless the author's provider refused the call on the production
              path (an ``outage``, outside n — P-293); that every row of one run carries the
              run's arm, ``+L`` included (P-295); and that ``POST /runs`` takes ``arm: S1`` on
              a blind run only.
How:          ``pyrepo``'s feat commit replayed blind through ``crb.core.run.run`` with a
              recording builder that applies the commit's own patch and a scripted author.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md
Works with:   src/crb/builders/adapter.py (the S1 step), src/crb/builders/brief.py
              (``S1Arm``), src/crb/core/ledger.py (the ``authoring`` failure kind),
              src/crb/server/worker.py (``_s1_arm``), src/crb/server/routes/runs.py (``arm`` on
              ``POST /runs``)
Tested by:    tests/test_replay_s1_arm.py
Touch when:   never for a new repository; the S1 arm's steps change (an ADR-0026 amendment).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

import crb.builders as builders_pkg
from crb.builders import adapter
from crb.builders.base import Budget, EscalationLadder, Rung
from crb.builders.brief import LABEL_CONTEXT_ARM, LABEL_CTX_AUTHOR, S1Arm
from crb.core.execution import LocalExecutor
from crb.core.ledger import FAILURE_AUTHORING, cell_stats, derive_failure_kind
from crb.core.prevention import AUTO_CONTEXT, LearningSnapshot
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.workspace import Workspace
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


def test_post_runs_takes_arm_s1_on_a_blind_run_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the S1 test author's builder is credential-checked at submit, like every rung
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-present")
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


class _SdkStatusError(Exception):
    """The shape of the OpenAI SDK's status errors that the production path reads — the
    class name, ``status_code`` and ``response`` (``openai_client._status_of``) — built here
    so the test needs no optional extra: CI installs only ``server``, ``postgres``, ``mcp``
    and ``dev`` from the lock (P-330)."""

    def __init__(self, message: str, *, response: Any) -> None:
        super().__init__(message)
        self.response = response
        self.status_code = response.status_code


#: The SDK's class for each status, by the name the row's error text carries.
_SDK_CLASS = {
    400: "BadRequestError",
    401: "AuthenticationError",
    402: "APIStatusError",
    429: "RateLimitError",
    500: "InternalServerError",
    503: "InternalServerError",
}


def _provider_refusal(status: int) -> Any:
    """An author whose provider answers ``status``, raised exactly as the real author's chat
    raises it: through :func:`crb.builders.openai_client.with_retries` (``OpenAIChat``'s
    path), so the row carries the production text, never a hand-typed one."""
    import httpx

    from crb.builders.openai_client import with_retries

    request = httpx.Request("POST", "https://provider.invalid/v1/chat/completions")
    response = httpx.Response(status, request=request, json={"error": {"message": "no"}})
    kind = type(_SDK_CLASS[status], (_SdkStatusError,), {})

    def call() -> Any:
        raise kind(f"Error code: {status} - refused", response=response)

    def author(ws: Any, subject: str, message: str) -> tuple[str, str]:
        return with_retries(call, max_retries=1, sleep=lambda s: None)  # type: ignore[no-any-return]

    return author


def test_an_author_outage_is_an_outage_never_an_authoring_failure(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """P-293: the S1 test author's provider refused the call (a rate limit, a quota, an
    overloaded server, a refused key): nothing was observed, so the row is an ``outage`` —
    outside n — not an ``authoring`` failure counted against the arm. A call the provider
    answered as a bad request, and an author that ran and produced no RED test, stay
    ``authoring``. The refusal is raised on the production path (``with_retries``)."""
    for status in (429, 402, 503, 401):
        rows, _ = _replay(
            pyrepo,
            tmp_path / f"s{status}",
            s1=S1Arm(author=_provider_refusal(status), author_model="t1"),
        )
        (row,) = rows
        assert row.failure_kind == "outage", (status, row.error)
        assert row.error.startswith("authoring: the test author failed: model_error:"), row.error
        assert cell_stats(rows).n == 0
    red = "authoring: the authored test 'tests/test_x.py' is not RED at the parent: it passes"
    assert derive_failure_kind(clean=False, disqualified=False, error=red) == "authoring"


def test_an_author_call_that_failed_without_a_refusal_is_harness_never_the_arms_miss(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """Rule 4b holds for the test author as it holds for the builder (DL-360, P-720): the
    author's own provider call failed with no refusal (a 400, a 500) or the runner raised
    while proving the test RED — the author produced nothing to judge, so the row is an
    instrument failure, ``harness``, skipped by a reading's first-attempt rule, never an
    ``authoring`` miss counted against the arm. The same ``model_error`` on the builder's
    side reads ``harness`` too."""
    for status in (400, 500):
        rows, _ = _replay(
            pyrepo,
            tmp_path / f"s{status}",
            s1=S1Arm(author=_provider_refusal(status), author_model="t1"),
        )
        (row,) = rows
        assert row.error.startswith("authoring: the test author failed: model_error:"), row.error
        assert row.failure_kind == "harness", (status, row.error)
        builder_side = row.error.removeprefix("authoring: the test author failed: ")
        assert derive_failure_kind(clean=False, disqualified=False, error=builder_side) == (
            "harness"
        )
    proving = "authoring: harness error proving RED: OSError: the sandbox went away"
    assert derive_failure_kind(clean=False, disqualified=False, error=proving) == "harness"


def test_a_miss_whose_text_the_model_chose_is_the_arms_miss_whatever_it_says(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """P-735: rule 3b read ``model_error`` anywhere in an ``authoring:`` error, and the path
    the model chose for its test is part of that error — so a test green at the parent at
    ``tests/test_model_error.py`` read ``harness`` (skipped by a reading, never the arm's miss)
    and at ``tests/test_model_error_rate_limit.py`` read ``outage`` (outside n). Only the head
    the adapter itself writes (``authoring: [the test author failed: ]model_error``) is the
    instrument's; every other word is the model's, and the miss is the arm's."""
    green = "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    for path in ("tests/test_model_error.py", "tests/test_model_error_rate_limit.py"):

        def author(ws: Any, subject: str, message: str, path: str = path) -> tuple[str, str]:
            return path, green

        name = path.rsplit("/", 1)[1]
        rows, _ = _replay(pyrepo, tmp_path / name, s1=S1Arm(author=author, author_model="t1"))
        (row,) = rows
        assert "is not RED at the parent" in row.error and path in row.error, row.error
        assert row.failure_kind == FAILURE_AUTHORING, (path, row.error)
        stats = cell_stats(rows)
        assert (stats.n, stats.clean, stats.n_harness) == (1, 0, 0), path

    def raising(ws: Any, subject: str, message: str) -> tuple[str, str]:
        raise ImportError("cannot import name 'Model_Error' from 'calc' (rate limit 429)")

    rows, _ = _replay(pyrepo, tmp_path / "import", s1=S1Arm(author=raising, author_model="t1"))
    assert rows[0].error.startswith("authoring: the test author failed: ImportError:")
    assert rows[0].failure_kind == FAILURE_AUTHORING, rows[0].error


def test_every_row_of_one_s1_run_carries_the_runs_arm(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    """With the repository's loop on, an S1 run is ``S1@t1+L``: its authoring failures carry
    that arm as its successes do, so a per-arm reading counts them against the arm the run
    measured, never another arm's bucket. A harness refusal before the author runs (an
    unknown rung here) carries the run's arm too."""
    loop = LearningSnapshot(repo="pyrepo", auto_apply=AUTO_CONTEXT, lines=())

    def ok(ws: Any, subject: str, message: str) -> tuple[str, str]:
        return AUTHORED, AUTHORED_SRC

    def green(ws: Any, subject: str, message: str) -> tuple[str, str]:
        return (
            "tests/test_s1_add.py",
            "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        )

    arms = {}
    for name, author in (("ok", ok), ("green", green)):
        rows, _ = _replay(
            pyrepo,
            tmp_path / name,
            s1=S1Arm(author=author, author_model="t1"),
            learning=loop,
        )
        arms[name] = rows[0].labels.get(LABEL_CONTEXT_ARM)
    assert arms == {"ok": "S1@t1+L", "green": "S1@t1+L"}
    # the run's own BuildFn, called on a rung it does not have: refused, and stamped
    fn = adapter.build_fn_for(
        EscalationLadder((Rung("rec", "m"),)),
        budget=Budget(),
        runner=PytestRunner(pyrepo.config),
        executor=LocalExecutor(),
        config=pyrepo.config,
        s1=S1Arm(author=ok, author_model="t1"),
        learning=loop,
    )
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws") as ws:
        refused = fn(ws, pyrepo.feat_task(), "blind", "r9")
    assert refused.error and refused.labels[LABEL_CONTEXT_ARM] == "S1@t1+L"


def test_an_s1_run_whose_test_author_has_no_credential_is_refused_at_submit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-003's class for the S1 test author: a run whose author cannot call its provider
    would write an authoring failure for every commit at $0. The submit check names the
    author's builder, and nothing is queued."""
    for key in ("CEREBRAS_API_KEY", "OPENAI_API_KEY", "CRB_OPENAI_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    with make_env(tmp_path) as env:
        login(env.client, "operator")
        body = {
            "repo": ALPHA,
            "kind": "blind",
            "builder": "fixture_gold",
            "model": "gold",
            "arm": "S1",
            "test_author": "openai_agent:gpt-oss-120b",
        }
        r = env.post("/runs", json=body)
        assert r.status_code == 422, r.text
        err = envelope(r)
        assert err["code"] == "builder_credential_missing"
        assert err["detail"]["builder"] == "openai_agent"
        # a blind run NOT on the S1 arm never calls the author: no author check
        r = env.post(
            "/runs", json={k: v for k, v in body.items() if k not in ("arm", "test_author")}
        )
        assert r.status_code == 201, r.text


def test_the_fixtures_write_each_arm_in_the_mode_its_writer_writes_it(
    pyrepo: pr.PyRepo,
) -> None:
    """P-338: the reading fixtures stamped ``S1`` rows ``sighted``, a shape no writer
    produces — the replay ``S1`` arm runs blind — so the route map and the sign-off, which
    read sighted rows only, passed on the fixture and could never see a real ``S1`` row.
    ``REPLAY_MODE`` is the one table: the arm derivation and the worker's ``S1`` refusal
    agree with it, and the fixtures stamp from it."""
    from crb.core.context_arm import BASE_A0, BASE_S1, BASE_S3, REPLAY_MODE, context_arm_for
    from crb.observability.events import MemorySink
    from fixtures.readings import sealed_row
    from test_worker_test_author import _ctx, _worker

    assert context_arm_for(process_step="replay", mode=REPLAY_MODE[BASE_A0]) == BASE_A0
    assert context_arm_for(process_step="replay", mode=REPLAY_MODE[BASE_S3]) == BASE_S3
    ladder = EscalationLadder((Rung("editblock", "gpt-oss-120b"),))
    other = _ctx(pyrepo, MemorySink(), arm="S1", test_author="editblock:qwen-3-coder")
    wrong = "sighted" if REPLAY_MODE[BASE_S1] == "blind" else "blind"
    with pytest.raises(ValueError, match="blind replay"):
        _worker()._s1_arm(other, ladder, wrong)
    assert _worker()._s1_arm(other, ladder, REPLAY_MODE[BASE_S1]) is not None
    for arm in ("A0", "S1@t1", "S3"):
        base = arm.split("@")[0]
        assert sealed_row("c" * 40, arm=arm).mode == REPLAY_MODE[base], arm
    # the one mode rule every map, route and sign-off reader applies: a certifying arm is
    # kept whatever the mode; the descriptive and ceiling arms stay split by it
    from crb.core.context_arm import mode_admits

    assert mode_admits("blind", "S1@t1", "sighted") and mode_admits("sighted", "S2", "blind")
    assert not mode_admits("blind", "A0", "sighted") and not mode_admits("sighted", "S3", "blind")
    assert not mode_admits("blind", "", "sighted") and mode_admits("blind", "A0", "all")
