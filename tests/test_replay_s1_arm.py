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
              run's arm, ``+L`` included (P-295); that ``POST /runs`` takes ``arm: S1`` on
              a blind run only; and that the RED runs under the task's PARENT binding, must be
              a test the author defined, and is ``harness`` when it names no test while the
              env probe is red under that binding (P-800).
How:          ``pyrepo``'s feat commit replayed blind through ``crb.core.run.run`` with a
              recording builder that applies the commit's own patch and a scripted author;
              the binding cases drive the Go fixture's feat commit through the run's own
              ``BuildFn`` with a docker-named executor that records and runs nothing.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md
Works with:   src/crb/builders/adapter.py (the S1 step), src/crb/builders/brief.py
              (``S1Arm``), src/crb/core/ledger.py (the ``authoring`` failure kind),
              src/crb/server/worker.py (``_s1_arm``), src/crb/server/routes/runs.py (``arm`` on
              ``POST /runs``), src/crb/core/runners/go_runner.py (the Go ids and the env probe
              the RED is read with), src/crb/core/deps.py (the sealed bindings),
              tests/fixtures/langs/gorepo.py (the Go fixture)
Tested by:    tests/test_replay_s1_arm.py
Touch when:   never for a new repository; the S1 arm's steps change (an ADR-0026 amendment).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, ClassVar

import pytest

import crb.builders as builders_pkg
from crb.builders import adapter
from crb.builders.base import STOP_DONE, Budget, BuildOutcome, EscalationLadder, Rung
from crb.builders.brief import LABEL_CONTEXT_ARM, LABEL_CTX_AUTHOR, S1Arm
from crb.core.deps import SCHEME_GO, BundleMount, DepsBinding, TaskDeps, register_store_root
from crb.core.execution import Command, ExecResult, LocalExecutor
from crb.core.git import GitRepo
from crb.core.ledger import FAILURE_AUTHORING, FAILURE_HARNESS, cell_stats, derive_failure_kind
from crb.core.prevention import AUTO_CONTEXT, LearningSnapshot
from crb.core.runners.go_runner import GoRunner
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import TaskSpec
from crb.core.workspace import Workspace
from fixtures import pyrepo as pr
from fixtures.server_seed import ALPHA, envelope, login, make_env
from test_builders_brief import Recorder, _replay

try:
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover
    import conftest_langs as langs  # type: ignore[no-redef]

gorepo = langs.fixture_module("gorepo")


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


# --- the S1 RED under the parent's binding, from the authored test (F87-1, P-800) ---------

#: Two sealed sets, both at ``/deps/gomod``: the parent's and the builder's. The RED and its
#: probe must carry the PARENT's (ADR-0019), never the builder's and never none.
PARENT_KEY = "dep_" + "a" * 64
BUILDER_KEY = "dep_" + "b" * 64
GO_AUTHORED = "calc/new_test.go"
GO_AUTHORED_SRC = (
    'package calc\n\nimport "testing"\n\n'
    'func TestNew(t *testing.T) {\n\tif Add(2, 2) != 5 {\n\t\tt.Fatal("want 5")\n\t}\n}\n'
)


def _go_events(*events: tuple[str, str]) -> str:
    """``go test -json`` lines for ``(action, test)`` pairs in the fixture's ``calc``
    package, ending with the binary's own summary and the package's verdict."""
    pkg = gorepo.CALC_PKG
    lines = [{"Action": a, "Package": pkg, "Test": t} for a, t in events]
    failed = any(a == "fail" for a, _ in events)
    lines.append({"Action": "output", "Package": pkg, "Output": "FAIL\n" if failed else "PASS\n"})
    lines.append({"Action": "fail" if failed else "pass", "Package": pkg})
    return "\n".join(json.dumps(x) for x in lines) + "\n"


#: The sealed posture with nothing loadable: every package fails to build, naming no test.
_UNLOADABLE = "calc/calc.go:3:8: no required module provides package github.com/spf13/pflag"


class _Docker:
    """A docker-named executor that runs nothing: it records each command (and whether the
    authored test was on disk when it ran) and answers ``go test`` with ``red`` and the
    ``go list`` env probe with ``probe``."""

    name = "docker"

    def __init__(self, red: ExecResult, probe: ExecResult | None = None) -> None:
        self.red, self.probe = red, probe or ExecResult(0, "", "")
        self.cmds: list[tuple[Command, bool]] = []

    def run(self, cmd: Command) -> ExecResult:
        self.cmds.append((cmd, (Path(cmd.root) / GO_AUTHORED).exists()))
        if cmd.argv[1:2] == ("test",):
            return self.red
        if cmd.argv[1:2] == ("list",):
            return self.probe
        return ExecResult(0, "", "")

    def tool(self, name: str, host_override: str | None = None) -> str:
        return name

    def describe(self) -> dict[str, Any]:
        return {"executor": self.name}

    def posture_facts(self) -> dict[str, str]:
        return {"executor": self.name, "tree": "copy", "network": "none"}

    def ran(self, verb: str) -> list[tuple[Command, bool]]:
        return [(c, present) for c, present in self.cmds if c.argv[1:2] == (verb,)]


class _Idle:
    """Registered as ``idle``: records that it was called and changes nothing."""

    name = "idle"
    calls: ClassVar[int] = 0

    def __init__(self, *, model: str = "m", provider: str = "", **cfg: Any) -> None:
        self.model, self.provider = model, provider

    def describe(self) -> dict[str, Any]:
        return {"builder": self.name, "model": self.model}

    def build(
        self, workspace: Any, brief: Any, budget: Budget, *, on_event: Any = None
    ) -> BuildOutcome:
        _Idle.calls += 1
        return BuildOutcome(
            builder=self.name,
            model=self.model,
            provider=self.provider,
            mode=brief.mode,
            done=True,
            stop_reason=STOP_DONE,
            budget=budget,
        )


def _sealed_go_deps(tmp_path: Path) -> Any:
    """A sealed ``TaskDeps`` whose parent and builder sets both sit at ``/deps/gomod``."""
    store = register_store_root(tmp_path / "store")

    def binding(role: str, key: str) -> DepsBinding:
        host = store / "go" / key / "gomod"
        host.mkdir(parents=True)
        return DepsBinding(
            role=role,
            lang="go",
            scheme=SCHEME_GO,
            key=key,
            digest="sha256:" + key[-64:],
            mounts=(BundleMount(host, "/deps/gomod", key),),
            env={"GOMODCACHE": "/deps/gomod", "GOPROXY": "off", "GOSUMDB": "off"},
            local_env={"GOMODCACHE": str(host), "GOPROXY": "off"},
        )

    parent, builder = binding("parent", PARENT_KEY), binding("builder", BUILDER_KEY)
    return TaskDeps("sealed", "go", parent=parent, gold=parent, builder=builder)


def _s1_on_go(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    executor: _Docker,
    *,
    src: str = GO_AUTHORED_SRC,
    baseline: tuple[str, ...] = (),
    parent: dict[str, str] | None = None,
) -> tuple[Any, Any]:
    """One S1 attempt on the Go fixture's feat commit through the run's own ``BuildFn``,
    under the sealed binding (``parent`` = more files at the parent); returns the attempt
    and the task's deps."""
    monkeypatch.setitem(builders_pkg._REGISTRY, "idle", _Idle)
    monkeypatch.setattr(_Idle, "calls", 0)
    root, feat = gorepo.build(tmp_path, extra=parent)
    repo, cfg = GitRepo(root), gorepo.config()
    deps = _sealed_go_deps(tmp_path)
    task = TaskSpec(
        task_id=feat,
        repo=cfg.name,
        subject="feat: add Sub",
        authored=repo.author_date(feat),
        test_files=(gorepo.TEST_SUB,),
        src_files=(gorepo.SRC_SUB,),
        target_tests=("./calc",),
        belt_scope=(),
        language="go",
        baseline_failing=baseline,
    )

    def author(ws: Any, subject: str, message: str) -> tuple[str, str]:
        return GO_AUTHORED, src

    ladder = EscalationLadder((Rung("idle", "m"),))
    fn = adapter.build_fn_for(
        ladder,
        budget=Budget(),
        runner=GoRunner(cfg),
        executor=executor,
        config=cfg,
        s1=S1Arm(author=author, author_model="t1"),
        deps_for=lambda t: deps,
    )
    with Workspace.create(repo, feat, tmp_path / "ws", config=cfg) as ws:
        attempt = fn(ws, task, "blind", adapter.ladder_labels(ladder)[0])
        assert not (ws.root / GO_AUTHORED).exists()
    return attempt, deps


def _bound_to(cmd: Command, deps: Any) -> bool:
    """``cmd`` reads the PARENT's sealed set: its module cache, offline, mounted."""
    return (
        cmd.env.get("GOMODCACHE") == "/deps/gomod"
        and cmd.env.get("GOPROXY") == "off"
        and deps.parent.mounts[0] in cmd.ro_mounts
        and deps.builder.mounts[0] not in cmd.ro_mounts
    )


def test_s1_red_runs_under_the_parent_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F87-1 part 1: the S1 RED ran with no binding, so under the sealed docker posture the
    Go runner pointed ``GOMODCACHE`` at an empty ``/tmp/gomod`` with the network off and
    mounted nothing; every cobra package failed to build and every authored test read
    "not RED at the parent" — the instrument's fault, recorded as the arm's miss. The RED
    now runs under the task's PARENT binding, as qualification proves the held-out tests."""
    red = ExecResult(1, _go_events(("run", "TestNew"), ("fail", "TestNew")), "")
    executor = _Docker(red)
    attempt, deps = _s1_on_go(tmp_path, monkeypatch, executor)
    ((cmd, present),) = executor.ran("test")
    assert present, "the RED ran without the authored test on disk"
    assert "/tmp/gomod" not in cmd.env.values(), cmd.env
    assert _bound_to(cmd, deps), (cmd.env, cmd.ro_mounts)
    # RED on the authored test itself: the builder is called, and no probe was needed
    assert not (attempt.error or "").startswith("authoring:"), attempt.error
    assert _Idle.calls == 1 and executor.ran("list") == []


def test_s1_red_requires_the_authored_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """F87-1 part 3: the Go RED scope is the whole package, and any failing id was taken as
    the authored test's RED — so an old test already failing there (``TestOld``) passed a
    test that discriminates nothing (``TestNew`` passes). The RED must be a test the author
    defined, less the task's baseline; otherwise it is the arm's ``authoring`` miss."""
    old = ExecResult(
        1,
        _go_events(
            ("run", "TestOld"), ("fail", "TestOld"), ("run", "TestNew"), ("pass", "TestNew")
        ),
        "",
    )
    executor = _Docker(old)
    attempt, _ = _s1_on_go(tmp_path, monkeypatch, executor)
    assert attempt.error.startswith("authoring: the authored test 'calc/new_test.go' is not RED")
    assert "no test it defines fails there" in attempt.error, attempt.error
    assert derive_failure_kind(clean=False, disqualified=False, error=attempt.error) == (
        FAILURE_AUTHORING
    )
    assert _Idle.calls == 0
    # the authored test failing only as a baseline id is no RED either
    mine = ExecResult(1, _go_events(("run", "TestNew"), ("fail", "TestNew")), "")
    attempt, _ = _s1_on_go(
        tmp_path / "baseline",
        monkeypatch,
        _Docker(mine),
        baseline=(f"{gorepo.CALC_PKG}::TestNew",),
    )
    assert "no test it defines fails there" in attempt.error, attempt.error
    # the rule, per runner: a Go subtest is its test's; a pytest id is the authored file's,
    # a collection error included; a runner whose ids name neither keeps any failing id
    pkg = gorepo.CALC_PKG
    failing = frozenset({f"{pkg}::TestNew/sub", f"{pkg}::TestOld"})
    assert adapter.authored_red("go", GO_AUTHORED, GO_AUTHORED_SRC, failing, ()) == {
        f"{pkg}::TestNew/sub"
    }
    py = frozenset({"tests/test_s1.py::test_a[1]", "tests/test_s1.py", "tests/test_x.py::test_b"})
    assert adapter.authored_red("pytest", "tests/test_s1.py", "", py, ("tests/test_s1.py",)) == {
        "tests/test_s1.py::test_a[1]"
    }
    assert adapter.authored_red("jest", "a.test.js", "", frozenset({"adds"}), ()) is None


#: An authored Go file whose one test is a fuzz target: ``go test`` runs its seed corpus,
#: and a failing seed reports ``FuzzNew/seed#0`` and then ``FuzzNew``.
GO_FUZZ_SRC = (
    'package calc\n\nimport "testing"\n\n'
    "func FuzzNew(f *testing.F) {\n\tf.Add(2)\n\tf.Fuzz(func(t *testing.T, n int) {\n"
    '\t\tif Add(n, n) != 5 {\n\t\t\tt.Fatal("want 5")\n\t\t}\n\t})\n}\n'
)
#: A testify suite method, and the runner that runs it: ``TestCalcSuite/TestNew``.
GO_SUITE_METHOD = "func (s *CalcSuite) TestNew() {\n\ts.Equal(5, Add(2, 2))\n}\n"
GO_SUITE_RUNNER = "func TestCalcSuite(t *testing.T) {\n\tsuite.Run(t, new(CalcSuite))\n}\n"


def test_s1_red_counts_each_top_level_go_test_the_author_defines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RT2-V2-1: the Go rule read only ``func TestX(t *testing.T)``, so the two other
    top-level tests ``go test`` runs — a fuzz target's seed corpus (``FuzzNew/seed#0``) and
    an example with an ``// Output:`` comment (``ExampleNew``) — were refused "no test it
    defines fails there" while the authored test was the one failing. Each now counts by
    its own name, and an old test failing beside it still never does. A testify suite
    method counts only under a runner the file defines: an id's second segment is any
    subtest's name (an old test's ``t.Run("TestNew", …)`` carries it too), so a method that
    a runner in another file runs stays refused — a limit the refusal now states."""
    pkg = gorepo.CALC_PKG
    old = f"{pkg}::TestOld"
    seeds = frozenset({f"{pkg}::FuzzNew/seed#0", f"{pkg}::FuzzNew"})
    assert adapter.authored_red("go", GO_AUTHORED, GO_FUZZ_SRC, seeds | {old}, ()) == seeds
    example = (
        'package calc\n\nimport "fmt"\n\n'
        "func ExampleNew() {\n\tfmt.Println(Add(2, 2))\n\t// Output: 5\n}\n"
    )
    failing = frozenset({f"{pkg}::ExampleNew", old})
    assert adapter.authored_red("go", GO_AUTHORED, example, failing, ()) == {f"{pkg}::ExampleNew"}
    # a function that only looks like one is not a test go runs — each lookalike's id is
    # offered as failing, so each signature check is pinned (R6A-LASTFIX-R1-3)
    lookalike = (
        "package calc\n\nfunc FuzzNew(n int) {}\n\nfunc FuzzT(t *testing.T) {}\n\n"
        "func ExampleNew(n int) {}\n"
    )
    offered = seeds | {f"{pkg}::FuzzT", f"{pkg}::ExampleNew"}
    assert adapter.authored_red("go", GO_AUTHORED, lookalike, offered, ()) == frozenset()
    # a suite: counted under its own runner, refused when another file's runner runs it
    in_suite = frozenset({f"{pkg}::TestCalcSuite/TestNew", f"{pkg}::TestCalcSuite"})
    whole = "package calc\n\n" + GO_SUITE_RUNNER + GO_SUITE_METHOD
    assert adapter.authored_red("go", GO_AUTHORED, whole, in_suite, ()) == in_suite
    method_only = "package calc\n\n" + GO_SUITE_METHOD
    assert adapter.authored_red("go", GO_AUTHORED, method_only, in_suite, ()) == frozenset()
    # through the BuildFn: the failing seed is the authored test's RED, and the builder runs
    fuzz = ExecResult(
        1,
        _go_events(
            ("run", "FuzzNew"),
            ("run", "FuzzNew/seed#0"),
            ("fail", "FuzzNew/seed#0"),
            ("fail", "FuzzNew"),
        ),
        "",
    )
    attempt, _ = _s1_on_go(tmp_path / "fuzz", monkeypatch, _Docker(fuzz), src=GO_FUZZ_SRC)
    assert not (attempt.error or "").startswith("authoring:"), attempt.error
    assert _Idle.calls == 1
    suite = ExecResult(
        1,
        _go_events(
            ("run", "TestCalcSuite"),
            ("run", "TestCalcSuite/TestNew"),
            ("fail", "TestCalcSuite/TestNew"),
            ("fail", "TestCalcSuite"),
        ),
        "",
    )
    attempt, _ = _s1_on_go(tmp_path / "suite", monkeypatch, _Docker(suite), src=method_only)
    assert "no test it defines fails there; " + adapter.GO_RED_RULE in attempt.error, attempt.error
    assert derive_failure_kind(clean=False, disqualified=False, error=attempt.error) == (
        FAILURE_AUTHORING
    )
    assert _Idle.calls == 0


#: An authored Go file whose one live test passes: a ``"/*"`` declared above it opens no
#: comment, and an earlier draft kept in a block comment and a raw string names an old
#: failing fuzz target, example and test at column 0.
GO_DRAFT_SRC = (
    'package calc\n\nimport "testing"\n\nvar open = "/*"\n\n'
    "func TestNewAdds(t *testing.T) {\n\tt.Log(open)\n\tif Add(2, 2) != 4 {\n"
    '\t\tt.Fatal("want 4")\n\t}\n}\n\n'
    "/*\nAn earlier draft:\n\nfunc FuzzOld(f *testing.F) {}\n\nfunc ExampleAdd() {}\n*/\n\n"
    "var draft = `\nfunc TestRawOld(t *testing.T) {}\n`\n"
)


def test_s1_red_reads_a_go_test_only_from_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R6A-LASTFIX-R1-1: the Go rule matched ``^func`` over the file's raw text, so a draft
    kept in a block comment or a raw string "declared" ``FuzzOld``, ``ExampleAdd`` and
    ``TestRawOld``; an old test failing under one of those names in the package became the
    authored test's RED while the authored test itself passed. A test counts only from the
    file's code, each comment and string literal blanked first, read left to right: a
    ``"/*"`` or a stray backtick inside a string, a rune or a ``//`` comment opens nothing
    (R6A-FIXCHECK-R2-1: no case pinned the string, rune or line-comment reading)."""
    pkg = gorepo.CALC_PKG
    old = frozenset(
        f"{pkg}::{name}" for name in ("FuzzOld/seed#0", "FuzzOld", "ExampleAdd", "TestRawOld")
    )
    assert adapter.authored_red("go", GO_AUTHORED, GO_DRAFT_SRC, old, ()) == frozenset()
    # the live test still counts: the "/*" above it is a string, not a comment's start that
    # would run to the draft's "*/" and hide the test
    mine = old | {f"{pkg}::TestNewAdds"}
    assert adapter.authored_red("go", GO_AUTHORED, GO_DRAFT_SRC, mine, ()) == {
        f"{pkg}::TestNewAdds"
    }
    # a backtick in a string, a rune or a line comment opens no raw string: read as one, it
    # would run to the draft's opening backtick, hide the live test and bare TestRawOld
    for stray in ('var tick = "`"', "var rtick = '`'", "// a stray ` here"):
        src = GO_DRAFT_SRC.replace("var open", f"{stray}\n\nvar open", 1)
        counted = adapter.authored_red("go", GO_AUTHORED, src, mine, ())
        assert counted == {f"{pkg}::TestNewAdds"}, stray
    # through the BuildFn: the old failures are no RED, and the builder never runs
    drafts = ExecResult(
        1,
        _go_events(
            ("run", "TestNewAdds"),
            ("pass", "TestNewAdds"),
            ("run", "FuzzOld"),
            ("run", "FuzzOld/seed#0"),
            ("fail", "FuzzOld/seed#0"),
            ("fail", "FuzzOld"),
        ),
        "",
    )
    attempt, _ = _s1_on_go(tmp_path, monkeypatch, _Docker(drafts), src=GO_DRAFT_SRC)
    assert "no test it defines fails there; " + adapter.GO_RED_RULE in attempt.error, attempt.error
    assert _Idle.calls == 0


#: An old internal test file at the parent: a fuzz target whose seed always fails and an
#: example whose ``// Output:`` is wrong — both failing there, outside the task's baseline.
GO_OLD_SRC = (
    'package calc\n\nimport (\n\t"fmt"\n\t"testing"\n)\n\n'
    "func FuzzOld(f *testing.F) {\n\tf.Add(1)\n"
    '\tf.Fuzz(func(t *testing.T, n int) { t.Fatal("old") })\n}\n\n'
    "func ExampleAdd() {\n\tfmt.Println(Add(1, 1))\n\t// Output: 3\n}\n"
)
#: The authored file in the EXTERNAL test package, redeclaring both names (``go vet`` and
#: ``go test`` accept it): both pass, yet each reports the old one's id too.
GO_EXTERNAL_SRC = (
    'package calc_test\n\nimport (\n\t"fmt"\n\t"testing"\n\n\t"example.com/m/calc"\n)\n\n'
    "func FuzzOld(f *testing.F) {\n\tf.Add(1)\n\tf.Fuzz(func(t *testing.T, n int) {})\n}\n\n"
    "func ExampleAdd() {\n\tfmt.Println(calc.Add(1, 1))\n\t// Output: 2\n}\n"
)
#: ``GO_OLD_SRC`` with ``FuzzOld`` opened in each shape ``go vet`` and ``go test`` accept
#: that no column-0 ``func`` line shows: after a comment, indented, and with a comment
#: between ``func`` and the name (the last two gofmt-clean) — REDFIX-FIXCHECK-R2-2.
GO_OLD_SHAPES = tuple(
    GO_OLD_SRC.replace("func FuzzOld", shape)
    for shape in (
        "/* legacy */ func FuzzOld",
        "\tfunc FuzzOld",
        "func /* x */ FuzzOld",
        "func // x\nFuzzOld",
    )
)


def test_s1_red_never_counts_a_go_name_another_test_file_declares(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R6A-LASTFIX-R1-2: a Go test name is NOT unique within its package's test binary — a
    ``package calc`` and a ``package calc_test`` file in one directory may each declare
    ``FuzzOld``, and both report ``<pkg>::FuzzOld``. An authored external file redeclaring
    an old failing internal test's name therefore took that old failure as its RED while
    its own copy passed. A name another test file in the directory declares at the parent
    never counts, in any shape go accepts it in (REDFIX-FIXCHECK-R2-2); the author's other
    names still do."""
    pkg = gorepo.CALC_PKG
    old = frozenset({f"{pkg}::FuzzOld/seed#0", f"{pkg}::FuzzOld", f"{pkg}::ExampleAdd"})
    taken = {"FuzzOld", "ExampleAdd"}
    assert adapter.authored_red("go", GO_AUTHORED, GO_EXTERNAL_SRC, old, (), beside=taken) == (
        frozenset()
    )
    new = GO_EXTERNAL_SRC + 'func TestNew(t *testing.T) {\n\tt.Fatal("want 5")\n}\n'
    mine = old | {f"{pkg}::TestNew"}
    assert adapter.authored_red("go", GO_AUTHORED, new, mine, (), beside=taken) == {
        f"{pkg}::TestNew"
    }
    # through the BuildFn, old_test.go at the parent in each shape: no RED, no builder run
    both = ExecResult(
        1,
        _go_events(
            ("run", "FuzzOld"),
            ("run", "FuzzOld/seed#0"),
            ("fail", "FuzzOld/seed#0"),
            ("fail", "FuzzOld"),
            ("run", "ExampleAdd"),
            ("fail", "ExampleAdd"),
            ("run", "FuzzOld"),
            ("run", "FuzzOld/seed#0"),
            ("pass", "FuzzOld/seed#0"),
            ("pass", "FuzzOld"),
            ("run", "ExampleAdd"),
            ("pass", "ExampleAdd"),
        ),
        "",
    )
    for i, old_src in enumerate((GO_OLD_SRC, *GO_OLD_SHAPES)):
        attempt, _ = _s1_on_go(
            tmp_path / str(i),
            monkeypatch,
            _Docker(both),
            src=GO_EXTERNAL_SRC,
            parent={"calc/old_test.go": old_src},
        )
        refusal = "no test it defines fails there; " + adapter.GO_RED_RULE
        assert refusal in attempt.error, (old_src, attempt.error)
        assert _Idle.calls == 0


def test_s1_unattributed_red_with_red_env_probe_is_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F87-1 part 1: a RED that names no test (nothing built) while the runner's env probe
    is red under the SAME parent binding is the posture's fault, not the author's: the row
    is ``harness`` (rule 4b), reported and never counted as the arm's miss. The label does
    not buy a retry — nothing here re-runs, and after a reservation (round 5's
    reserved.v1) a harness row is a miss. The probe runs with the authored test removed, so
    an author's own bad import can never be read as the posture's; with the probe green the
    refusal stays the arm's ``authoring`` miss."""
    unbuilt = ExecResult(1, "", _UNLOADABLE)
    executor = _Docker(unbuilt, probe=ExecResult(1, "", _UNLOADABLE))
    attempt, deps = _s1_on_go(tmp_path, monkeypatch, executor)
    assert attempt.error.startswith("authoring: harness error proving RED:"), attempt.error
    assert derive_failure_kind(clean=False, disqualified=False, error=attempt.error) == (
        FAILURE_HARNESS
    )
    assert _Idle.calls == 0
    ((probe, present),) = executor.ran("list")
    assert not present, "the probe ran with the authored test still in the tree"
    assert _bound_to(probe, deps), (probe.env, probe.ro_mounts)
    assert len(executor.ran("test")) == 1, "the RED was re-run"
    # the posture loads the parent: the same unattributed RED is the arm's miss
    green_probe = _Docker(unbuilt, probe=ExecResult(0, "", ""))
    attempt, _ = _s1_on_go(tmp_path / "loads", monkeypatch, green_probe)
    assert "failed without attributable test ids" in attempt.error, attempt.error
    assert derive_failure_kind(clean=False, disqualified=False, error=attempt.error) == (
        FAILURE_AUTHORING
    )
    # the tree could not be copied for the RED: the instrument's, before any probe
    copy = _Docker(ExecResult(125, "", "copy failed", env_error="tree_copy_failed"))
    attempt, _ = _s1_on_go(tmp_path / "copy", monkeypatch, copy)
    assert attempt.error.startswith("authoring: harness error proving RED:"), attempt.error
    assert copy.ran("list") == []
