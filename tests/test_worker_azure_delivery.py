"""The worker's Azure Repos delivery wiring (ADR-0057): which remote gets the tracker token.

Navigation
----------
What it is:   The worker half of Azure Repos delivery: the switch, the same-organisation
              rule, the credentials provider, the clone and fetch header, the default
              branch and the events.
What it does: Pins that with the switch off (the default) nothing changes and the token is
              never read; that with it on an Azure remote in the board's own organisation
              gets the Azure seams (in ``_delivery_seams``, what the factory run's
              ``FactorySpec`` takes) and a provider that reads the token at each push; that a
              remote in another organisation gets no token; that the header goes to git
              through the environment, never argv; that no event carries the token; and that
              a missing ``origin/HEAD`` refuses the run rather than guessing ``main``.
How:          A ``Worker`` built with ``__new__`` and only its settings, the token reader
              replaced by a function; a fake clone answering ``git.run``; ``subprocess.run``
              monkeypatched to capture the fetch's argv and environment. No network, no git.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0057-azure-repos-pr-delivery.md
Works with:   src/crb/server/worker.py (``_azure_target``, ``_azure_auth_header``,
              ``_azure_delivery``, ``_delivery_seams`` — under test), src/crb/server/intake.py
              (``build_tracker`` passes the switch on), src/crb/server/settings.py (the switch),
              src/crb/factory/delivery_azure.py (the seams it chooses),
              tests/test_server_github_app.py (the same checks for the GitHub App)
Tested by:    tests/test_worker_azure_delivery.py
Touch when:   never for a new repository; the same-organisation rule, the switch or the
              default-branch rule changes (docs/adr/0057-azure-repos-pr-delivery.md first).
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from crb.core import git as core_git
from crb.factory.delivery import NoGitCredentialsError
from crb.factory.delivery_azure import (
    azure_close_pr_fn,
    azure_comment_pr_fn,
    azure_open_pr_fn,
)
from crb.observability.events import Emitter, MemorySink
from crb.server import worker as w
from crb.server.intake import build_tracker
from crb.server.settings import FactorySettings, IntakeSettings

TOKEN = "azpat" + "q" * 47
BASIC = base64.b64encode(f":{TOKEN}".encode()).decode()
BOARD = "https://dev.azure.com/acme"
REMOTE = "https://acme@dev.azure.com/acme/Payments/_git/ledger"
WEB = "https://dev.azure.com/acme/Payments/_git/ledger"


class _Tokens:
    """The tracker token reader, counting its reads; the next value can be changed."""

    def __init__(self, value: str = TOKEN) -> None:
        self.value = value
        self.reads = 0

    def __call__(self) -> str:
        self.reads += 1
        return self.value


def _worker(
    tmp_path: Path,
    *,
    switch: bool = True,
    tracker: str = "ado",
    board: str = BOARD,
    tokens: _Tokens | None = None,
) -> tuple[w.Worker, _Tokens]:
    worker = w.Worker.__new__(w.Worker)
    worker.settings = w.WorkerSettings(
        home=tmp_path / "home",
        factory=FactorySettings(azure_repos_delivery=switch),
        intake=IntakeSettings(tracker=tracker, url=board, project="Payments", column="Ready"),
    )
    worker._github_app_client = None
    reader = tokens or _Tokens()
    worker._tracker_token = reader  # type: ignore[method-assign]
    return worker, reader


class _FakeClone:
    """A clone that answers the few ``git.run`` calls the worker makes, by argv."""

    git_binary = "git"

    def __init__(self, path: Path, answers: dict[tuple[str, ...], str]) -> None:
        self.path = path
        self._answers = answers

    def run(self, *args: str) -> Any:
        out = self._answers.get(args)
        return SimpleNamespace(ok=out is not None, stdout=out or "", stderr="")


def _clone_on(tmp_path: Path, branch: str = "master", *, origin_head: bool = True) -> _FakeClone:
    answers = {
        ("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}"): "abc123",
        ("rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}^{{commit}}"): "abc123",
        ("rev-parse", "--abbrev-ref", "HEAD"): branch,
    }
    if origin_head:
        answers[("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")] = (
            f"origin/{branch}"
        )
    return _FakeClone(tmp_path, answers)


# --- the switch -------------------------------------------------------------------------


def test_azure_repos_delivery_defaults_off_and_is_in_redacted() -> None:
    assert FactorySettings().azure_repos_delivery is False
    assert FactorySettings().redacted()["azure_repos_delivery"] is False
    assert FactorySettings(azure_repos_delivery=True).redacted()["azure_repos_delivery"] is True


def test_switch_off_wiring_identical_to_today(tmp_path: Path) -> None:
    """Off (the default), an Azure remote gets no header, no seams and no token read —
    exactly as before the switch existed; on, nothing changes for a GitHub remote or for a
    deployment whose tracker is not Azure DevOps."""
    clone = _clone_on(tmp_path)
    off, reads = _worker(tmp_path, switch=False)
    assert off._azure_target(REMOTE) is None
    assert off._azure_auth_header(REMOTE) is None
    assert off._azure_delivery(REMOTE, clone) is None  # type: ignore[arg-type]
    assert reads.reads == 0

    on, reads = _worker(tmp_path)
    github = "https://github.com/acme/ledger.git"
    assert on._azure_target(github) is None and on._azure_auth_header(github) is None
    assert on._azure_delivery(github, clone) is None  # type: ignore[arg-type]
    jira, jira_reads = _worker(tmp_path, tracker="jira", board="https://acme.atlassian.net")
    assert jira._azure_target(REMOTE) is None and jira._azure_auth_header(REMOTE) is None
    assert reads.reads == 0 and jira_reads.reads == 0


def test_azure_remote_with_switch_on_uses_azure_seams(tmp_path: Path) -> None:
    worker, reads = _worker(tmp_path)
    azure = worker._azure_delivery(REMOTE, _clone_on(tmp_path))  # type: ignore[arg-type]
    assert azure is not None
    assert azure.open_pr_fn is azure_open_pr_fn
    assert azure.comment_pr_fn is azure_comment_pr_fn
    assert azure.close_pr_fn is azure_close_pr_fn
    assert azure.default_branch == "master"
    creds = azure.creds.resolve("ledger")
    # the push goes to the repository's address without the user name the remote carried
    assert creds.remote == WEB and creds.token == TOKEN
    assert reads.reads == 1
    # the legacy organisation host is the same organisation
    legacy = "https://acme.visualstudio.com/Payments/_git/ledger"
    assert worker._azure_target(legacy) is not None


# --- the factory run's delivery seams ---------------------------------------------------


def test_factory_run_seams_azure_when_switch_on_and_no_github_app(tmp_path: Path) -> None:
    """The factory run's ``FactorySpec`` takes its delivery half from ``_delivery_seams``:
    with no GitHub App link, the switch on and an Azure remote in the board's organisation,
    every seam is Azure's and the target is the clone's ``origin/HEAD``."""
    worker, reads = _worker(tmp_path)
    seams = worker._delivery_seams({}, REMOTE, _clone_on(tmp_path, "develop"), deliver=True)  # type: ignore[arg-type]
    assert seams["open_pr_fn"] is azure_open_pr_fn
    assert seams["comment_pr_fn"] is azure_comment_pr_fn
    assert seams["close_pr_fn"] is azure_close_pr_fn
    assert seams["target_default_branch"] == "develop"
    assert isinstance(seams["creds"], w._AzureReposProvider)
    assert reads.reads == 0  # the token is read at the push, not here
    assert set(seams) == {
        "creds",
        "open_pr_fn",
        "comment_pr_fn",
        "close_pr_fn",
        "target_default_branch",
    }


def test_factory_run_seams_none_when_switch_off_or_not_delivering(tmp_path: Path) -> None:
    """Off, or a run that does not deliver: no credentials, no seams, the GitHub default
    branch rule, no token read — and a clone with no ``origin/HEAD`` is not refused."""
    bare = _clone_on(tmp_path, origin_head=False)
    for switch, deliver in ((False, True), (True, False)):
        worker, reads = _worker(tmp_path, switch=switch)
        seams = worker._delivery_seams({}, REMOTE, bare, deliver=deliver)  # type: ignore[arg-type]
        assert seams == {
            "creds": None,
            "open_pr_fn": None,
            "comment_pr_fn": None,
            "close_pr_fn": None,
            "target_default_branch": "main",
        }
        assert reads.reads == 0
    worker, _ = _worker(tmp_path, switch=False)
    cfg = {"github": {"default_branch": "trunk"}}
    seams = worker._delivery_seams(cfg, REMOTE, bare, deliver=True)  # type: ignore[arg-type]
    assert seams["target_default_branch"] == "trunk"


def test_factory_run_seams_github_app_wins_and_carries_api_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A linked GitHub App comes first even with the switch on: Azure is never consulted
    (a clone with no ``origin/HEAD`` is not refused), and each GitHub seam passes the
    deployment's API base on."""
    worker, reads = _worker(tmp_path)
    app_creds = object()
    worker._delivery_credentials = lambda cfg, remote: app_creds  # type: ignore[method-assign,assignment,return-value]
    calls: list[tuple[str, dict[str, Any]]] = []

    def capture(name: str) -> Any:
        def fn(**kw: Any) -> Any:
            calls.append((name, kw))
            return ("https://pr", 1)

        return fn

    for name in ("github_open_pr_fn", "github_comment_pr_fn", "github_close_pr_fn"):
        monkeypatch.setattr(w, name, capture(name))
    cfg = {"github": {"default_branch": "trunk"}}
    seams = worker._delivery_seams(
        cfg, REMOTE, _clone_on(tmp_path, origin_head=False), deliver=True
    )  # type: ignore[arg-type]
    assert seams["creds"] is app_creds and seams["target_default_branch"] == "trunk"
    seams["open_pr_fn"](title="t")
    seams["comment_pr_fn"](body="b")
    seams["close_pr_fn"](number=1)
    base = worker.settings.github.api_url
    assert [(n, kw["api_base"]) for n, kw in calls] == [
        ("github_open_pr_fn", base),
        ("github_comment_pr_fn", base),
        ("github_close_pr_fn", base),
    ]
    assert reads.reads == 0


def test_factory_run_seams_azure_without_origin_head_refuses(tmp_path: Path) -> None:
    worker, _ = _worker(tmp_path)
    with pytest.raises(w.FetchRefused, match="origin/HEAD"):
        worker._delivery_seams({}, REMOTE, _clone_on(tmp_path, origin_head=False), deliver=True)  # type: ignore[arg-type]


def test_tracker_build_passes_the_switch_as_pull_request_links() -> None:
    """The ADO adapter reads a pull request (to attach Azure's own link) only when the
    server built it with the switch on; the default is off."""
    intake = IntakeSettings(tracker="ado", url=BOARD, project="Payments", column="Ready")
    assert build_tracker(intake, TOKEN).config.pull_request_links is False  # type: ignore[attr-defined]
    on = build_tracker(intake, TOKEN, pull_request_links=True)
    assert on.config.pull_request_links is True  # type: ignore[attr-defined]


# --- the token ---------------------------------------------------------------------------


def test_worker_gives_no_token_to_another_organisation(tmp_path: Path) -> None:
    """Every organisation shares ``dev.azure.com``, so the organisation is compared, not
    the host; a lookalike host, plain http and an SSH remote get nothing either."""
    worker, reads = _worker(tmp_path)
    clone = _clone_on(tmp_path)
    for remote in (
        "https://dev.azure.com/fabrikam/Payments/_git/ledger",
        "https://fabrikam.visualstudio.com/Payments/_git/ledger",
        "https://dev.azure.com.evil.example/acme/Payments/_git/ledger",
        "http://dev.azure.com/acme/Payments/_git/ledger",
        "git@ssh.dev.azure.com:v3/acme/Payments/ledger",
    ):
        assert worker._azure_target(remote) is None, remote
        assert worker._azure_auth_header(remote) is None, remote
        assert worker._azure_delivery(remote, clone) is None, remote  # type: ignore[arg-type]
    assert reads.reads == 0


def test_azure_provider_reads_token_at_resolve(tmp_path: Path) -> None:
    tokens = _Tokens()
    worker, _ = _worker(tmp_path, tokens=tokens)
    azure = worker._azure_delivery(REMOTE, _clone_on(tmp_path))  # type: ignore[arg-type]
    assert azure is not None and tokens.reads == 0  # nothing read until a push needs it
    assert azure.creds.resolve("ledger").token == TOKEN
    tokens.value = "azpat" + "r" * 47  # the operator rotated the token between pushes
    assert azure.creds.resolve("ledger").token == "azpat" + "r" * 47
    assert tokens.reads == 2
    # the provider keeps the reader, never a token
    assert TOKEN not in repr(vars(azure.creds)) and "azpat" not in repr(azure.creds)
    tokens.value = ""
    with pytest.raises(NoGitCredentialsError, match="tracker token"):
        azure.creds.resolve("ledger")


def test_azure_clone_header_goes_through_env_not_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker, _ = _worker(tmp_path)
    header = worker._azure_auth_header(REMOTE)
    assert header == f"Authorization: Basic {BASIC}"

    seen: list[dict[str, Any]] = []

    def fake_run(argv: list[str], **kw: Any) -> Any:
        seen.append({"argv": list(argv), "env": dict(kw.get("env") or {})})
        if "clone" in argv:
            (Path(argv[-1]) / ".git").mkdir(parents=True)
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    # the fetch before a factory run
    monkeypatch.setattr(w.subprocess, "run", fake_run)
    worker._fetch_default_branch("ledger", {}, _clone_on(tmp_path), REMOTE, None)  # type: ignore[arg-type]
    # and the first clone
    monkeypatch.setattr(core_git.subprocess, "run", fake_run)
    monkeypatch.setattr(core_git.GitRepo, "is_repo", lambda self: True)
    monkeypatch.setattr(core_git.GitRepo, "rev_parse", lambda self, *a, **k: "abc123")
    core_git.clone_repo(REMOTE, tmp_path / "dest", auth_header=header, auth_scope=REMOTE)

    assert len(seen) == 2
    for call in seen:
        argv = " ".join(call["argv"])
        assert TOKEN not in argv and BASIC not in argv
        # scoped to the remote, and no redirect may carry it to another host
        assert call["env"]["GIT_CONFIG_COUNT"] == "2"
        assert call["env"]["GIT_CONFIG_KEY_0"] == f"http.{REMOTE}.extraheader"
        assert call["env"]["GIT_CONFIG_VALUE_0"] == header
        assert call["env"]["GIT_CONFIG_KEY_1"] == "http.followRedirects"
        assert call["env"]["GIT_CONFIG_VALUE_1"] == "false"


def test_worker_azure_events_carry_no_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    worker, _ = _worker(tmp_path)
    sink = MemorySink()
    monkeypatch.setattr(
        w.subprocess, "run", lambda argv, **kw: SimpleNamespace(returncode=0, stderr="", stdout="")
    )
    with caplog.at_level(logging.DEBUG):
        worker._fetch_default_branch(
            "ledger",
            {},
            _clone_on(tmp_path),  # type: ignore[arg-type]
            REMOTE,
            Emitter(sink, trace_id="run-1", actor="op", repo="ledger"),
        )
    events = sink.events
    start = next(e for e in events if e.action == "repo.fetch.start")
    assert start.payload["azure_repos"] is True and start.payload["github_app"] is False
    text = repr(events) + caplog.text
    assert TOKEN not in text and BASIC not in text


def test_azure_default_branch_from_origin_head_else_refused(tmp_path: Path) -> None:
    worker, _ = _worker(tmp_path)
    azure = worker._azure_delivery(REMOTE, _clone_on(tmp_path, "develop"))  # type: ignore[arg-type]
    assert azure is not None and azure.default_branch == "develop"
    with pytest.raises(w.FetchRefused, match="origin/HEAD") as err:
        worker._azure_delivery(REMOTE, _clone_on(tmp_path, origin_head=False))  # type: ignore[arg-type]
    assert "'main'" not in str(err.value) and TOKEN not in str(err.value)
