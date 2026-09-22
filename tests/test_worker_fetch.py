"""The worker fetches before it builds on the base (F39) and syncs merge outcomes first (B-9 / F30).

Navigation
----------
What it is:   The worker's fetch-before-run suite: a factory run on a URL-registered
              repository fast-forwards the clone's default branch to the remote's before
              the RED proof and the build, records ``repo.fetch.start`` / ``repo.fetch.done``
              with the before / after shas and the base in the apparatus, and REFUSES the run
              when the fetch fails or the local branch cannot fast-forward. Plus the rule for
              which kinds fetch, and the outcome sync at the start of a factory run.
What it does: Pins that the second factory run builds on the commit pushed to the remote
              after the first (the proof's ``base_sha`` moves), that a fresh clone is not
              fetched again, that a ``probe`` never fetches, that an unreachable remote or a
              diverged local branch ends the run ``failed`` with the reason and an error
              ``repo.fetch.done`` (no build, no RED proof), that a linked-only rule governs
              replay / mine, and that an unlinked repository's factory run records the sync
              as skipped without touching GitHub.
How:          ``fixtures.remote.bare_remote`` over ``pyrepo`` with the developer switch;
              ``test_worker``'s harness, ``FakeBuilder`` and ``_multiply_backlog``; a second
              clone pushes commits to the bare remote.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0014-github-app-is-the-connection.md
Works with:   src/crb/server/worker.py (``_fetch_default_branch``, ``_fetch_before``,
              ``_sync_outcomes`` — under test), tests/fixtures/remote.py, tests/test_worker.py,
              tests/test_worker_clone.py (the clone half)
Tested by:    tests/test_worker_fetch.py
Touch when:   the fetch rule (which kinds, which branch) or its events change (docs/API.md
              and docs/GITHUB-APP.md §5 first).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from crb.core.git import LOCAL_CLONE_ENV, GitRepo
from crb.factory import evidence as fe
from crb.observability.events import StepStatus
from crb.server.worker import FETCH_KINDS_LINKED
from crb.store.jobs import STATUS_FAILED, STATUS_SUCCEEDED
from crb.store.models import Run
from fixtures import pyrepo as pr
from fixtures.langs import git
from fixtures.remote import bare_remote
from test_worker import Harness, _multiply_backlog
from test_worker_clone import add_url_repo


@pytest.fixture
def remote(pyrepo: pr.PyRepo, tmp_path: Path) -> str:
    return bare_remote(pyrepo.path, tmp_path / "remote.git")


@pytest.fixture
def h(tmp_path: Path, pyrepo: pr.PyRepo, monkeypatch: pytest.MonkeyPatch) -> Harness:
    """An empty harness with the developer clone switch on (the cases register URL repos)."""
    monkeypatch.setenv(LOCAL_CLONE_ENV, "1")
    return Harness(tmp_path, pyrepo)


def push_commit(remote: str, tmp_path: Path, name: str = "NOTE.md") -> str:
    """Commit ``name`` on ``main`` through a second clone and push it; returns the new sha."""
    work = tmp_path / f"pusher-{name}"
    git(tmp_path, "clone", "--quiet", remote, str(work))
    (work / name).write_text(f"{name}\n", encoding="utf-8")
    git(work, "add", name)
    git(work, "commit", "--quiet", "-m", f"docs: {name}")
    git(work, "push", "--quiet", "origin", "main")
    return git(work, "rev-parse", "HEAD").strip()


def _fetch_events(h: Harness, run_id: str) -> list:
    return [e for e in h.events(run_id) if e.action.startswith("repo.fetch")]


def test_factory_run_fetches_and_fast_forwards_the_default_branch_before_it_builds(
    h: Harness, remote: str, tmp_path: Path
) -> None:
    """F39 end to end: run 1 clones (a fresh clone is at the remote's head — no fetch);
    a commit lands on the remote; run 2 fetches, fast-forwards ``main`` from the old sha to
    the new one, records it, and the RED proof and the build start from the NEW base."""
    add_url_repo(h, remote)
    home, _item, _backlog = _multiply_backlog(h)
    run1 = h.enqueue("factory", ladder_json=["fake:m0"])
    done1 = h.run_one()
    assert done1.status == STATUS_SUCCEEDED, done1.error
    dest = h.home / "repos" / pr.REPO_NAME
    assert GitRepo(dest).rev_parse() == h.pyrepo.docs_sha
    actions = [e.action for e in h.events(run1.id)]
    assert "repo.clone.done" in actions and not _fetch_events(h, run1.id)
    assert done1.apparatus_json["base_sha"] == h.pyrepo.docs_sha
    proof1 = [e for e in home.events() if e.kind == fe.EV_RED_PROOF][-1]
    assert proof1.payload["base_sha"] == h.pyrepo.docs_sha
    # the fork moves on (a human merges something): the next run must build on it
    new_sha = push_commit(remote, tmp_path)
    assert new_sha != h.pyrepo.docs_sha
    run2 = h.enqueue("factory", ladder_json=["fake:m0"])
    done2 = h.run_one()
    assert done2.status == STATUS_SUCCEEDED, done2.error
    start, finish = _fetch_events(h, run2.id)
    assert start.action == "repo.fetch.start" and start.stage == "system"
    assert start.payload == {
        "url": remote,
        "branch": "main",
        "dest": str(dest),
        "github_app": False,
    }
    assert finish.action == "repo.fetch.done" and finish.status is StepStatus.OK
    assert finish.payload["before"] == h.pyrepo.docs_sha and finish.payload["after"] == new_sha
    assert finish.payload["fast_forwarded"] is True and finish.payload["branch"] == "main"
    assert finish.duration_ms is not None and finish.duration_ms >= 0
    # the clone IS the fork's default branch now, and everything downstream used it
    assert GitRepo(dest).rev_parse() == new_sha and GitRepo(dest).rev_parse("main") == new_sha
    assert done2.apparatus_json["base_sha"] == new_sha
    proof2 = [e for e in home.events() if e.kind == fe.EV_RED_PROOF][-1]
    assert proof2.payload["base_sha"] == new_sha
    assert [e.action for e in h.events(run2.id)].index("repo.fetch.done") < [
        e.action for e in h.events(run2.id)
    ].index("item.start")
    # nothing new on the remote: the fetch still runs, records equal shas, no fast-forward
    run3 = h.enqueue("factory", ladder_json=["fake:m0"])
    assert h.run_one().status == STATUS_SUCCEEDED
    _, finish3 = _fetch_events(h, run3.id)
    assert finish3.payload["before"] == finish3.payload["after"] == new_sha
    assert finish3.payload["fast_forwarded"] is False
    assert home.evidence().verify() == len(home.events())


def test_probe_never_fetches_and_the_linked_only_rule_governs_replay_and_mine(
    h: Harness, remote: str, tmp_path: Path
) -> None:
    add_url_repo(h, remote)
    h.add_task(h.pyrepo.feat_task())
    run = h.enqueue("probe")
    assert h.run_one().status == STATUS_SUCCEEDED
    push_commit(remote, tmp_path)
    run2 = h.enqueue("probe")
    assert h.run_one().status == STATUS_SUCCEEDED
    assert not _fetch_events(h, run.id) and not _fetch_events(h, run2.id)
    # a mine on a URL-only repository does not fetch either: the rule is factory always,
    # replay / blind / mine only when linked through the GitHub App
    run3 = h.enqueue("mine")
    assert h.run_one().status == STATUS_SUCCEEDED
    assert not _fetch_events(h, run3.id)
    w = h.worker
    assert {"replay", "blind", "mine"} == FETCH_KINDS_LINKED
    assert w._fetch_before("factory", {}, remote) is True
    assert w._fetch_before("factory", {}, "") is False  # no URL: nothing to fetch from
    assert w._fetch_before("mine", {}, remote) is False
    assert w._fetch_before("probe", {"github": {"installation_id": 77}}, remote) is False
    # linked (the app configured on this deployment) → replay / blind / mine fetch first
    from dataclasses import replace

    from crb.server.settings import GitHubAppSettings

    w.settings = replace(
        w.settings, github=GitHubAppSettings(app_id="4242", app_slug="crb", private_key="pem")
    )
    linked = {"github": {"installation_id": 77, "full_name": "acme/alpha"}}
    assert all(w._fetch_before(k, linked, remote) for k in ("replay", "blind", "mine"))
    assert w._fetch_before("probe", linked, remote) is False


def test_an_unreachable_remote_refuses_the_run_before_any_build(
    h: Harness, remote: str, tmp_path: Path
) -> None:
    """A fetch that fails ends the run ``failed`` with the reason — never a build on a base
    the remote may have moved past. The clone is left as it was."""
    add_url_repo(h, remote)
    home, _item, _backlog = _multiply_backlog(h)
    h.enqueue("factory", ladder_json=["fake:m0"])
    assert h.run_one().status == STATUS_SUCCEEDED
    n_events = len(home.events())
    shutil.rmtree(Path(remote.removeprefix("file://")))
    run = h.enqueue("factory", ladder_json=["fake:m0"])
    done = h.run_one()
    assert done.status == STATUS_FAILED
    assert done.error.startswith(
        "FetchRefused: repo 'pyrepo': the clone could not be brought up to date"
    )
    assert (
        "git fetch failed" in done.error
        and "refused so it does not build on a stale base" in done.error
    )
    _start, finish = _fetch_events(h, run.id)
    assert finish.action == "repo.fetch.done" and finish.status is StepStatus.ERROR
    assert finish.error_code == "FetchRefused" and "stale base" in finish.error_message
    assert finish.payload["branch"] == "main" and finish.payload["url"] == remote
    # no item was started, nothing was proved or built; the chain did not grow
    assert not [e for e in h.events(run.id) if e.stage == "factory"]
    assert len(home.events()) == n_events
    assert GitRepo(h.home / "repos" / pr.REPO_NAME).rev_parse() == h.pyrepo.docs_sha


def test_a_diverged_local_default_branch_refuses_the_run(
    h: Harness, remote: str, tmp_path: Path
) -> None:
    """The clone's ``main`` has a commit the remote does not (someone worked in the clone):
    it cannot fast-forward, so the run is refused with the two shas named — the product
    never merges or resets a base on its own."""
    add_url_repo(h, remote)
    _multiply_backlog(h)
    h.enqueue("factory", ladder_json=["fake:m0"])
    assert h.run_one().status == STATUS_SUCCEEDED
    dest = h.home / "repos" / pr.REPO_NAME
    (dest / "LOCAL.md").write_text("local\n", encoding="utf-8")
    git(dest, "add", "LOCAL.md")
    git(dest, "commit", "--quiet", "-m", "local: stray commit")
    local = git(dest, "rev-parse", "HEAD").strip()
    new_sha = push_commit(remote, tmp_path)
    run = h.enqueue("factory", ladder_json=["fake:m0"])
    done = h.run_one()
    assert done.status == STATUS_FAILED
    assert (
        f"local 'main' at {local[:12]} cannot fast-forward to the remote's {new_sha[:12]}"
        in done.error
    )
    _, finish = _fetch_events(h, run.id)
    assert finish.status is StepStatus.ERROR
    assert GitRepo(dest).rev_parse() == local, "the clone was left as it was"


def test_a_clone_left_on_another_branch_is_put_back_on_the_default_branch(
    h: Harness, remote: str, tmp_path: Path
) -> None:
    """The clone sits on a scratch branch and its local ``main`` is gone (someone tidied
    the clone by hand): the fetch recreates ``main`` at the remote's head and checks it
    out, so the base is still the fork's default branch; ``before`` is empty."""
    add_url_repo(h, remote)
    _multiply_backlog(h)
    h.enqueue("factory", ladder_json=["fake:m0"])
    assert h.run_one().status == STATUS_SUCCEEDED
    dest = h.home / "repos" / pr.REPO_NAME
    git(dest, "checkout", "--quiet", "-b", "scratch")
    git(dest, "branch", "-D", "main")
    new_sha = push_commit(remote, tmp_path)
    run = h.enqueue("factory", ladder_json=["fake:m0"])
    done = h.run_one()
    assert done.status == STATUS_SUCCEEDED, done.error
    _, finish = _fetch_events(h, run.id)
    assert (finish.payload["before"], finish.payload["after"]) == ("", new_sha)
    assert finish.payload["fast_forwarded"] is True
    assert git(dest, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
    assert GitRepo(dest).rev_parse() == new_sha and done.apparatus_json["base_sha"] == new_sha


def test_factory_run_on_an_unlinked_repository_skips_the_outcome_sync(h: Harness) -> None:
    """B-9 / F30 at the worker: without a GitHub App link there is nothing to read the
    pull request through — the run records the sync as skipped (with the reason) and
    goes on; nothing is ever fetched from GitHub."""
    h.add_repo()
    _multiply_backlog(h)
    run = h.enqueue("factory", ladder_json=["fake:m0"])
    assert h.run_one().status == STATUS_SUCCEEDED
    (synced,) = [e for e in h.events(run.id) if e.action == "outcomes.synced"]
    assert synced.stage == "factory" and synced.status is StepStatus.SKIPPED
    assert synced.payload["reason"] == "not linked through the GitHub App on its own host"
    assert h.worker._github_app_client is None, "no app client was ever built"
    assert isinstance(run, Run)


def test_factory_run_on_a_linked_repository_syncs_outcomes_through_the_installation_token(
    tmp_path: Path, pyrepo: pr.PyRepo
) -> None:
    """B-9 / F30 at the worker, against a fake GitHub: two delivered pull requests, one
    merged and one still open — ``delivery.merged`` lands on the item's chain once, the
    open one records nothing, the trace carries ``outcomes.synced`` with the report, and
    the second sync reads only the open one; a closed-only chain is still read (and its
    later merge recorded), a merged-only one mints no token. A token that cannot be
    minted is an error event on the trace, never a failed run."""
    import httpx
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from crb.factory.backlog import KIND_CODE, BacklogItem
    from crb.observability.events import Emitter, MemorySink
    from crb.server import worker as w
    from crb.server.factory_state import FactoryHome
    from crb.server.github_app import GitHubApp
    from crb.server.settings import GitHubAppSettings
    from test_server_github_app import FakeGitHub, pull_request_api

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    gh = FakeGitHub(key.public_key())
    gh.pulls = {
        ("acme/calc", 7): pull_request_api(7, "merged"),
        ("acme/calc", 8): pull_request_api(8, "open"),
    }
    settings = w.WorkerSettings(
        home=tmp_path / "home",
        github=GitHubAppSettings(app_id="4242", app_slug="crb", private_key=pem),
    )
    worker = w.Worker.__new__(w.Worker)
    worker.settings = settings
    worker._github_app_client = GitHubApp(settings.github, httpx.Client(transport=gh.transport()))
    home = FactoryHome(settings.home, "calc")
    item = BacklogItem(id="I-1", title="one", kind=KIND_CODE, capability_class="bug.fix")
    item2 = BacklogItem(id="I-2", title="two", kind=KIND_CODE, capability_class="bug.fix")
    home.register_backlog([item, item2], actor="tester")
    ev = home.evidence(actor="worker")
    for item_id, number in (("I-1", 7), ("I-2", 8)):
        ev.record_delivery(
            {
                "item_id": item_id,
                "branch": f"crb/{item_id}",
                "base": "main",
                "commit_sha": "a" * 40,
                "pr_url": f"https://github.com/acme/Calc/pull/{number}",
                "pr_number": number,
                "pack_hash": "p" * 64,
                "body_sha256": "b" * 64,
            }
        )
    sink = MemorySink()
    ctx = w.RunContext(
        run=Run(id="r" * 32, repo="calc", kind="factory", actor="operator:1"),
        emitter=Emitter(sink, trace_id="r" * 32, actor="operator:1", repo="calc"),
        config=pyrepo.config,
        git=pyrepo.repo,
    )
    cfg = {"github": {"installation_id": 78, "full_name": "acme/Calc", "default_branch": "main"}}
    remote = "https://github.com/acme/Calc.git"
    worker._sync_outcomes(ctx, home, cfg, remote)
    (synced,) = [e for e in sink.events if e.action == "outcomes.synced"]
    assert synced.stage == "factory" and synced.status is StepStatus.OK
    assert synced.payload == {"checked": 2, "merged": 1, "closed": 0, "open": 1, "errors": []}
    merged = home.evidence().outcome_for("I-1", 7)
    assert merged is not None and merged.kind == fe.EV_DELIVERY_MERGED
    assert merged.actor == "operator:1" and merged.payload["merged_by"] == "paul"
    assert home.evidence().outcome_for("I-2", 8) is None
    assert [c[1] for c in gh.calls if "/pulls/" in c[1]] == [
        "/repos/acme/Calc/pulls/7",
        "/repos/acme/Calc/pulls/8",
    ]
    # the token travelled as the installation's bearer; it is nowhere in the trace or chain
    assert all("ghs_token" not in str(e.to_dict()) for e in sink.events)
    assert all("ghs_token" not in str(e.to_dict()) for e in home.events())
    # second sync: only #8 is read; the chain does not grow
    gh.calls.clear()
    n = len(home.events())
    worker._sync_outcomes(ctx, home, cfg, remote)
    assert [c[1] for c in gh.calls if "/pulls/" in c[1]] == ["/repos/acme/Calc/pulls/8"]
    assert len(home.events()) == n
    # #8 closes without merging: recorded. Now EVERY delivery has an outcome, and the
    # closed one is still pending (a person can reopen and merge it): the worker mints
    # the token and reads it again — never ``checked: 0`` while a closed delivery exists
    gh.pulls[("acme/calc", 8)] = pull_request_api(8, "closed")
    worker._sync_outcomes(ctx, home, cfg, remote)
    assert sink.events[-1].payload["closed"] == 1
    gh.calls.clear()
    worker._sync_outcomes(ctx, home, cfg, remote)
    assert [c[1] for c in gh.calls if "/pulls/" in c[1]] == ["/repos/acme/Calc/pulls/8"]
    assert sink.events[-1].payload == {
        "checked": 1,
        "merged": 0,
        "closed": 0,
        "open": 0,
        "errors": [],
    }
    gh.pulls[("acme/calc", 8)] = pull_request_api(8, "merged", merged_by="ada")
    worker._sync_outcomes(ctx, home, cfg, remote)
    assert sink.events[-1].payload["merged"] == 1
    reopened = home.evidence().outcome_for("I-2", 8)
    assert reopened is not None and reopened.kind == fe.EV_DELIVERY_MERGED
    assert reopened.payload["merged_by"] == "ada"
    # both merged: nothing pending — no token minted, no read, checked 0
    gh.calls.clear()
    worker._sync_outcomes(ctx, home, cfg, remote)
    assert gh.calls == [] and sink.events[-1].payload["checked"] == 0
    # a fresh delivery (#9, open) so the syncs below have something to mint a token for
    ev.record_delivery(
        {
            "item_id": "I-1",
            "branch": "crb/I-1",
            "base": "main",
            "commit_sha": "c" * 40,
            "pr_url": "https://github.com/acme/Calc/pull/9",
            "pr_number": 9,
            "pack_hash": "p" * 64,
            "body_sha256": "b" * 64,
        }
    )
    gh.pulls[("acme/calc", 9)] = pull_request_api(9, "open")
    # a repository whose URL is off the app's host gets no token — the sync is skipped
    worker._sync_outcomes(ctx, home, cfg, "https://example.invalid/acme/Calc.git")
    assert sink.events[-1].status is StepStatus.SKIPPED
    # a dead credential: one error event, nothing raised
    worker._github_app_client = GitHubApp(
        settings.github,
        httpx.Client(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(401, json={"message": "Bad credentials"})
            )
        ),
    )
    worker._sync_outcomes(ctx, home, cfg, remote)
    last = sink.events[-1]
    assert last.action == "outcomes.synced" and last.status is StepStatus.ERROR
    assert "Bad credentials" in last.error_message and "ghs_" not in last.error_message
