"""The builder in a sealed container, against a real daemon (ADR-0012).

With a reachable daemon and ``crb-test-py:local`` (``python:3.12-slim`` + pytest,
shared with ``test_sandbox_docker``; ``CRB_TEST_SANDBOX_IMAGE`` names a present image to
use instead — CI passes the shipped python reference image), on
:mod:`tests.fixtures.langs.pyrepo_min`:

* a scripted "builder" (a shell script standing in for ``claude -p``, mounted
  read-only at ``/opt/fake/claude``) runs through the **same spawn contract** the
  real adapter uses — ``build_fn_for(container=…)`` → ``ContainerSession.spawn`` →
  ``DockerStream`` → ``StreamStats`` — edits the source and runs the target tests
  *inside* the container; the result is copied back and graded **clean on the host**
  by the unchanged grader (a chained ledger row with an evidence pack);
* inside that container the checkout is its own ``.git`` directory, the host's
  scratch path does not exist, the root filesystem is read-only, the credential is
  present in the environment and nowhere on a command line, and a direct socket to
  the internet fails;
* egress: from the builder container, ``CONNECT`` through the sidecar reaches only
  the allowlisted host (a mock endpoint container), ``example.com`` is ``403``, and
  direct connections (bypassing the proxy) fail — the sidecar's log names both;
* fail closed: a missing builder image and a sidecar that cannot start are
  :class:`SandboxUnavailable`; cancel and the wall clock end in ``docker kill``.

Skipped — with the probe's reason — when no daemon answers ``docker info`` or the
image cannot be built. Checkouts live under ``tests/.cache/sandbox`` (bind-mountable
on colima / Docker Desktop, unlike pytest's ``tmp_path``).

Navigation
----------
What it is:   The sealed-container builder against a real daemon (ADR-0012).
What it does: Pins that a scripted builder (a shell script mounted read-only as ``claude``)
              runs through the SAME spawn contract as the real adapter, edits the source and runs
              the target tests INSIDE the container, and the result is copied back and graded
              clean on the host by the unchanged grader; that from inside the cell the checkout
              is its own ``.git``, the host path does not exist, the root filesystem is
              read-only, the credential is in the environment and nowhere on a command line, and
              a direct socket fails; that egress reaches only the allowlisted host through the
              sidecar (``example.com`` is 403, direct connections fail, the sidecar logs both), a
              TLS handshake with the real endpoint costs no tokens; and that a missing image or
              a sidecar that cannot start is ``SandboxUnavailable`` while cancel and the wall
              clock end in ``docker kill``.
How:          ``crb-test-py:local`` built once per session (or the image
              ``CRB_TEST_SANDBOX_IMAGE`` names); checkouts under the tests cache
              (bind-mountable on colima / Docker Desktop); a mock endpoint container on its own
              egress network; skipped with the probe's reason without a daemon.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0012-builder-in-a-sealed-container.md,
              docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/builders/container.py (under test), src/crb/builders/egress_proxy.py
              (the sidecar), src/crb/builders/adapter.py (``build_fn_for``),
              tests/fixtures/langs/pyrepo_min.py (the fixture), tests/conftest_langs.py (the
              image build and probes), tests/test_builders_container.py (the daemon-free half)
Tested by:    tests/test_builders_container_docker.py
Touch when:   the builder image or the sidecar changes (a from-inside case that proves the wall
              holds, not only that the flag is set); the default allowlist changes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from crb.builders import adapter
from crb.builders.base import Budget, EscalationLadder, Rung
from crb.builders.container import (
    PROXY_ALIAS,
    PROXY_PORT,
    WORKDIR,
    BuilderContainerSettings,
    ContainerSession,
    SealedCheckout,
)
from crb.core.execution import DockerExecutor, DockerSettings, SandboxUnavailable
from crb.core.git import GitRepo
from crb.core.ledger import JsonlLedger, verify_chain
from crb.core.mine import Candidate, qualify
from crb.core.run import RunSpec, run
from crb.core.runners import get_runner
from crb.core.runners.base import BaseRunner
from crb.core.spec import RepoConfig, TaskSpec
from crb.core.workspace import Workspace

try:  # tests/ is a package only if the conftest owner made it one
    from tests import conftest_langs as langs
except ImportError:  # pragma: no cover — layout-dependent
    import conftest_langs as langs

pyrepo_min = langs.fixture_module("pyrepo_min")

pytestmark = [pytest.mark.docker, pytest.mark.slow]

#: ``CRB_TEST_SANDBOX_IMAGE`` when set, else the session-built ``crb-test-py:local``.
IMAGE = langs.sandbox_test_image()
#: An image without python3 — a sidecar started from it cannot come up.
NO_PYTHON_IMAGE = "alpine:latest"

FAKE_CLAUDE = textwrap.dedent(
    """\
    #!/bin/sh
    # A scripted `claude -p`: edit the source, run the target tests INSIDE the
    # container, report stream-json — plus facts about the cell for the test.
    set -u
    printf '%s\\n' '{"type":"system","subtype":"init","model":"fake","tools":["Bash","Edit"]}'
    cat > pkg/sub.py <<'PYEOF'
    def sub(a: int, b: int) -> int:
        return a - b
    PYEOF
    printf '%s\\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/work/pkg/sub.py"}}]}}'
    python -m pytest -q tests/test_sub.py > /tmp/pytest.out 2>&1; rc=$?
    printf '%s\\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"python -m pytest -q tests/test_sub.py"}}]}}'
    gitdir=other; [ -d .git ] && gitdir=dir
    host=absent; [ -e "@HOST_SCRATCH@" ] && host=visible
    key=absent; [ -n "${ANTHROPIC_API_KEY:-}" ] && key=present
    rootfs=ro; touch /usr/hacked 2>/dev/null && rootfs=rw
    net=blocked; python -c "import socket; socket.create_connection(('example.com', 443), timeout=3)" 2>/dev/null && net=open
    probe="cwd=$PWD uid=$(id -u) rc=$rc gitdir=$gitdir host=$host key=$key rootfs=$rootfs net=$net proxy=${HTTPS_PROXY:-none}"
    printf '{"type":"result","subtype":"success","is_error":false,"num_turns":2,"total_cost_usd":0.0,"result":"{\\\\"done\\\\":true,\\\\"summary\\\\":\\\\"%s\\\\"}"}\\n' "$probe"
    """
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _sandbox_ready() -> None:
    reason = langs.docker_unavailable_reason()
    if reason:
        pytest.skip(reason)
    langs.ensure_sandbox_test_image()


@pytest.fixture(scope="module")
def sandbox_root() -> Iterator[Path]:
    """A bind-mountable scratch root under the tests cache (the VM cannot mount ``tmp_path``);
    removed after the module.
    """
    root = langs.CACHE_DIR / "sandbox" / f"builder-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="module")
def built(sandbox_root: Path) -> tuple[GitRepo, str]:
    root, feat_sha = pyrepo_min.build(sandbox_root)
    return GitRepo(root), feat_sha


@pytest.fixture(scope="module")
def config() -> RepoConfig:
    return pyrepo_min.config()


@pytest.fixture(scope="module")
def runner(config: RepoConfig) -> BaseRunner:
    return get_runner(config)


@pytest.fixture(scope="module")
def executor() -> DockerExecutor:
    return DockerExecutor(DockerSettings(image=IMAGE))


@pytest.fixture(scope="module")
def candidate(built: tuple[GitRepo, str], config: RepoConfig) -> Candidate:
    repo, feat_sha = built
    return langs.feat_candidate(repo, config, feat_sha)


@pytest.fixture(scope="module")
def task(
    built: tuple[GitRepo, str],
    config: RepoConfig,
    runner: BaseRunner,
    executor: DockerExecutor,
    candidate: Candidate,
    sandbox_root: Path,
) -> TaskSpec:
    """The feat task qualified once INSIDE the sandbox; a skip reason here is a fixture failure."""
    repo, _ = built
    outcome = qualify(
        repo, config, candidate, runner=runner, executor=executor, scratch=sandbox_root / "mine"
    )
    assert outcome.task is not None, outcome.skipped_reason
    return outcome.task


@pytest.fixture(scope="module")
def fake_claude_dir(sandbox_root: Path) -> Path:
    """A directory holding the scripted ``claude`` (a shell script) the session mounts read-only at
    ``/opt/fake/claude``.
    """
    d = sandbox_root / "fake-claude"
    d.mkdir()
    script = d / "claude"
    script.write_text(FAKE_CLAUDE.replace("@HOST_SCRATCH@", str(sandbox_root)), encoding="utf-8")
    script.chmod(0o755)
    return d


@pytest.fixture
def trial(
    built: tuple[GitRepo, str], config: RepoConfig, candidate: Candidate, sandbox_root: Path
) -> Iterator[Workspace]:
    """A fresh worktree per test under ``sandbox_root`` with the feat tests overlaid, removed
    afterwards.
    """
    repo, _ = built
    ws = langs.trial_worktree(
        repo, candidate, sandbox_root / f"trial-{uuid.uuid4().hex[:8]}", config
    )
    yield ws
    ws.remove()


@pytest.fixture
def sealed(trial: Workspace, candidate: Candidate) -> Iterator[SealedCheckout]:
    """The trial exported as a ``SealedCheckout`` beside it, removed afterwards."""
    s = SealedCheckout.create(
        trial, trial.root.parent / f"{trial.root.name}-sealed", test_files=candidate.test_files
    )
    yield s
    s.remove()


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [shutil.which("docker") or "docker", *args],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _settings(**kw: Any) -> BuilderContainerSettings:
    base: dict[str, Any] = {"image": IMAGE, "proxy_image": IMAGE}
    base.update(kw)
    return BuilderContainerSettings(**base)


def _summary(result: str) -> dict[str, str]:
    """``k=v k=v …`` (the fake builder's probe line) → dict."""
    return dict(part.split("=", 1) for part in result.split() if "=" in part)


# ---------------------------------------------------------------------------
# End to end: scripted builder in the container → copy back → graded clean on the host
# ---------------------------------------------------------------------------


def test_scripted_builder_in_container_grades_clean(
    built: tuple[GitRepo, str],
    task: TaskSpec,
    config: RepoConfig,
    runner: BaseRunner,
    executor: DockerExecutor,
    sandbox_root: Path,
    fake_claude_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _ = built
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")
    settings = _settings(extra_ro_mounts={str(fake_claude_dir): "/opt/fake"})
    ladder = EscalationLadder((Rung("claude_code", "claude-sonnet-5"),))
    ledger = JsonlLedger(sandbox_root / "ledger.jsonl")
    spec = RunSpec(
        run_id="run-sealed-docker",
        config=config,
        runner=runner,
        executor=executor,
        scratch=sandbox_root / "scratch",
        ledger=ledger,
        evidence_dir=sandbox_root / "evidence",
        ladder=adapter.ladder_labels(ladder),
    )
    events: list[tuple[str, dict[str, Any]]] = []
    fn = adapter.build_fn_for(
        ladder,
        budget=Budget(wall_clock_s=300),
        runner=runner,
        executor=executor,
        config=config,
        on_event=lambda a, p: events.append((a, dict(p))),
        builder_overrides={"claude_binary": "/opt/fake/claude", "auth": "api_key"},
        container=settings,
    )
    summary = run(spec, repo, [task], fn, on_event=lambda a, p: events.append((a, dict(p))))
    assert summary.stopped_reason == "", summary.stopped_reason
    assert (summary.tasks, summary.clean, summary.rows) == (1, 1, 1)
    (row,) = ledger.rows()
    assert row.clean and row.error == "" and row.evidence_pack_hash
    assert verify_chain([row]) == 1
    assert row.builder == "claude_code" and row.model == "claude-sonnet-5"
    actions = [a for a, _ in events]
    assert "builder.sealed" in actions and "builder.copy_back" in actions
    sealed_ev = next(p for a, p in events if a == "builder.sealed")
    assert sealed_ev["image"] == IMAGE and sealed_ev["network"] == "proxy"
    copy = next(p for a, p in events if a == "builder.copy_back")
    assert copy["copied"] == [pyrepo_min.SRC_SUB] and copy["refused"] == []
    done = next(p for a, p in events if a == "build.done")
    assert done["error"] == "" and done["turns"] == 2
    # the sealed checkout and the containers are gone
    assert not list((sandbox_root / "scratch").glob("*-sealed"))
    for prefix in ("crb-build-", "crb-proxy-"):
        left = _docker("ps", "-a", "-q", "--filter", f"name={prefix}{task.short_id}").stdout
        assert left.strip() == ""


def test_the_cell_seen_from_inside(
    sealed: SealedCheckout, fake_claude_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run the scripted builder through the spawn contract and read its probe line."""
    from crb.builders.base import BuildBrief
    from crb.builders.claude_code import ClaudeCodeBuilder

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")
    settings = _settings(extra_ro_mounts={str(fake_claude_dir): "/opt/fake"})
    with ContainerSession(settings, sealed, label="probe") as session:
        overrides = {**session.overrides_for("claude_code"), "claude_binary": "/opt/fake/claude"}
        builder = ClaudeCodeBuilder(model="claude-sonnet-5", **overrides)
        brief = BuildBrief(
            subject="feat: sub",
            message="feat: sub",
            repo="pyfix-min",
            language="python",
            test_files=(pyrepo_min.TEST_SUB,),
            target_tests=(pyrepo_min.TEST_SUB,),
            config=pyrepo_min.config(),
        )
        outcome = builder.build(sealed.workspace(), brief, Budget(wall_clock_s=300))
    assert outcome.stop_reason == "done" and outcome.done, outcome.to_dict()
    facts = _summary(outcome.summary)
    assert facts["cwd"] == WORKDIR
    assert facts["uid"] == str(os.getuid())  # the worker's uid, never root
    assert facts["rc"] == "0"  # the builder's OWN test run passed inside the container
    assert facts["gitdir"] == "dir"  # its own repository, not a gitdir: pointer
    assert facts["host"] == "absent"  # the host scratch tree is not mounted
    assert facts["key"] == "present"  # the credential arrived through the environment …
    assert facts["rootfs"] == "ro"
    assert facts["net"] == "blocked"  # no direct route out
    assert facts["proxy"] == f"http://{PROXY_ALIAS}:{PROXY_PORT}"
    assert outcome.extra["session"]["model"] == "fake"
    assert outcome.tool_calls == 2 and outcome.errors == ()
    # … and the docker client's argv never carried it
    assert "sk-ant-test" not in " ".join(
        session.run_args({"ANTHROPIC_API_KEY": "sk-ant-test-x"}, timeout_s=1)
    )
    # the edit landed in the sealed checkout, not (yet) in the real worktree
    assert (sealed.root / pyrepo_min.SRC_SUB).exists()
    assert not (sealed.source.root / pyrepo_min.SRC_SUB).exists()


# ---------------------------------------------------------------------------
# Egress: only the allowlisted host, only through the sidecar
# ---------------------------------------------------------------------------


EGRESS_PROBE = textwrap.dedent(
    """\
    import json, socket
    MOCK = %r
    out = {}
    def via_proxy(host, port):
        s = socket.create_connection(("proxy", 3128), timeout=15)
        s.sendall(f"CONNECT {host}:{port} HTTP/1.1\\r\\nHost: {host}:{port}\\r\\n\\r\\n".encode())
        head = b""
        while b"\\r\\n\\r\\n" not in head:
            c = s.recv(4096)
            if not c:
                break
            head += c
        return s, head.split(b"\\r\\n")[0].decode()
    s, out["mock_via_proxy"] = via_proxy(MOCK, 8443)
    if "200" in out["mock_via_proxy"]:
        s.sendall(b"GET / HTTP/1.0\\r\\n\\r\\n")
        out["mock_body"] = s.recv(4096).split(b"\\r\\n")[0].decode()
    _, out["example_via_proxy"] = via_proxy("example.com", 443)
    for name, target in (("direct_example", ("example.com", 443)), ("direct_mock", (MOCK, 8443))):
        try:
            socket.create_connection(target, timeout=5)
            out[name] = "CONNECTED"
        except OSError as e:
            out[name] = type(e).__name__
    print(json.dumps(out))
    """
)


@pytest.fixture
def mock_endpoint() -> Iterator[tuple[str, str]]:
    """A 'model endpoint' container on its own egress network: ``(network, host)``."""
    tag = uuid.uuid4().hex[:8]
    net, name = f"crb-test-egress-{tag}", f"crb-mock-{tag}"
    assert _docker("network", "create", net).returncode == 0
    r = _docker(
        "run",
        "-d",
        "--rm",
        "--name",
        name,
        f"--network={net}",
        IMAGE,
        "python3",
        "-m",
        "http.server",
        "8443",
        "--bind",
        "0.0.0.0",
    )
    assert r.returncode == 0, r.stderr
    try:
        yield net, name
    finally:
        _docker("rm", "-f", name)
        _docker("network", "rm", net)


def test_egress_allowlist_holds_from_inside(
    sealed: SealedCheckout, mock_endpoint: tuple[str, str]
) -> None:
    net, mock = mock_endpoint
    settings = _settings(allow_hosts=(f"{mock}:8443",), egress_network=net)
    with ContainerSession(settings, sealed, label="egress") as session:
        handle = session.spawn(
            ["python3", "-c", EGRESS_PROBE % mock], {"HOME": "/tmp"}, sealed.root, 120
        )
        lines = list(handle.lines())
        assert handle.returncode == 0, (lines, handle.stderr_tail)
        out = json.loads(lines[-1])
    assert out["mock_via_proxy"].startswith("HTTP/1.1 200"), out
    assert out["mock_body"].startswith("HTTP/1.0 200"), out
    assert out["example_via_proxy"].startswith("HTTP/1.1 403"), out
    assert out["direct_example"] != "CONNECTED", out
    assert out["direct_mock"] != "CONNECTED", out
    assert f"allow {mock}:8443" in session.proxy_log
    assert "deny example.com:443" in session.proxy_log


LIVE_TLS_PROBE = textwrap.dedent(
    """\
    import socket, ssl, sys
    HOST = "api.anthropic.com"
    s = socket.create_connection(("proxy", 3128), timeout=20)
    s.sendall(f"CONNECT {HOST}:443 HTTP/1.1\\r\\nHost: {HOST}:443\\r\\n\\r\\n".encode())
    head = b""
    while b"\\r\\n\\r\\n" not in head:
        c = s.recv(4096)
        if not c:
            break
        head += c
    status = head.split(b"\\r\\n")[0].decode()
    if not status.startswith("HTTP/1.1 200"):
        print("TUNNEL " + status)
        sys.exit(0)
    tls = ssl.create_default_context().wrap_socket(s, server_hostname=HOST)
    tls.sendall(b"GET /v1/models HTTP/1.0\\r\\nHost: api.anthropic.com\\r\\n\\r\\n")
    print("TLS " + tls.recv(200).split(b"\\r\\n")[0].decode())
    """
)


@pytest.mark.network("api.anthropic.com")
def test_default_allowlist_reaches_the_real_endpoint_over_tls(sealed: SealedCheckout) -> None:
    """Zero model spend: a TLS handshake with api.anthropic.com through the sidecar
    (the default allowlist), then an unauthenticated GET — any HTTP status proves
    the tunnel carries TLS end to end. Skipped when the host has no internet."""
    with ContainerSession(_settings(), sealed, label="live") as session:
        handle = session.spawn(["python3", "-c", LIVE_TLS_PROBE], {"HOME": "/tmp"}, sealed.root, 90)
        lines = [ln for ln in handle.lines() if ln.strip()]
    assert lines, handle.stderr_tail
    if lines[-1].startswith("TUNNEL HTTP/1.1 502"):
        pytest.skip("no route to api.anthropic.com from this host (proxy answered 502)")
    assert lines[-1].startswith("TLS HTTP/1.1 "), lines
    assert "allow api.anthropic.com:443" in session.proxy_log


def test_no_allowlist_means_no_network_and_no_sidecar(sealed: SealedCheckout) -> None:
    settings = _settings(allow_hosts=())
    with ContainerSession(settings, sealed, label="nonet") as session:
        assert session.network == "none" and session.proxy_url == ""
        handle = session.spawn(
            [
                "python3",
                "-c",
                "import socket\ntry:\n    socket.create_connection(('proxy', 3128), timeout=3)\n    print('open')\nexcept OSError as e:\n    print(type(e).__name__)",
            ],
            {},
            sealed.root,
            60,
        )
        (line,) = [ln for ln in handle.lines() if ln.strip()]
    assert line != "open"
    assert _docker("ps", "-a", "-q", "--filter", f"name={session.proxy_name}").stdout.strip() == ""


# ---------------------------------------------------------------------------
# Fail closed; cancel and wall clock end in `docker kill`
# ---------------------------------------------------------------------------


def test_missing_builder_image_fails_closed(sealed: SealedCheckout) -> None:
    with pytest.raises(SandboxUnavailable, match="not present"):
        ContainerSession(_settings(image="crb-no-such-image:none"), sealed).__enter__()


def test_sidecar_that_cannot_start_fails_closed(sealed: SealedCheckout) -> None:
    langs.ensure_docker_image(NO_PYTHON_IMAGE, "FROM alpine:latest\n")
    session = ContainerSession(_settings(proxy_image=NO_PYTHON_IMAGE), sealed, label="badproxy")
    with pytest.raises(SandboxUnavailable, match=r"egress proxy (unhealthy|start failed)"):
        session.__enter__()
    # nothing is left behind
    assert _docker("ps", "-a", "-q", "--filter", f"name={session.proxy_name}").stdout.strip() == ""
    assert (
        _docker("network", "ls", "-q", "--filter", f"name={session.network}").stdout.strip() == ""
    )


def test_cancel_kills_the_container(sealed: SealedCheckout) -> None:
    flag = {"cancel": False}
    with ContainerSession(
        _settings(allow_hosts=()), sealed, cancel=lambda: flag["cancel"], label="cancel"
    ) as session:
        handle = session.spawn(["sleep", "60"], {}, sealed.root, 60)
        started = time.monotonic()
        it = handle.lines()
        flag["cancel"] = True
        list(it)
        assert time.monotonic() - started < 30
        assert handle.cancelled and not handle.timed_out
        assert _docker("ps", "-q", "--filter", f"name={session.build_name}").stdout.strip() == ""


def test_wall_clock_kills_the_container(sealed: SealedCheckout) -> None:
    with ContainerSession(_settings(allow_hosts=()), sealed, label="clock") as session:
        handle = session.spawn(["sleep", "60"], {}, sealed.root, 3)
        started = time.monotonic()
        list(handle.lines())
        assert time.monotonic() - started < 30
        assert handle.timed_out and not handle.cancelled
        assert _docker("ps", "-q", "--filter", f"name={session.build_name}").stdout.strip() == ""


def test_spawn_refuses_any_other_cwd(sealed: SealedCheckout, tmp_path: Path) -> None:
    with (
        ContainerSession(_settings(allow_hosts=()), sealed, label="cwd") as session,
        pytest.raises(SandboxUnavailable, match="only the sealed checkout"),
    ):
        session.spawn(["true"], {}, tmp_path, 10)
