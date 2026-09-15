"""The builder in a sealed container (ADR-0012) — everything that needs no daemon.

* :class:`SealedCheckout`: the export holds exactly one reachable commit, the gold
  commit (and even its source blob) is **absent from the object store**, ``.git`` is
  its own directory (not a ``gitdir:`` file into the main clone), the overlaid tests
  are byte-identical to the real worktree's, ``export-ignore``/``export-subst`` are
  undone, harness fix-ups are replicated.
* ``copy_back``: modified / added / deleted files land in the real worktree, a
  tampered test lands too (belt 1 must see it), symlinks and ``.git`` are refused,
  unchanged files are untouched.
* The ``docker run`` shape for the builder: every hardening flag, secrets as
  ``--env NAME`` only (never a value on argv), the container environment.
* The egress proxy's policy, in process: CONNECT to an allowlisted ``host:port``
  tunnels, anything else is 403, non-CONNECT is 405.
* The adapter's sealed path with a fake session: the builder never sees the real
  worktree, the result is graded clean on it, and a sandbox failure propagates.

Navigation
----------
What it is:   The sealed-container builder's test suite (ADR-0012) — everything that needs no
              daemon.
What it does: Pins that a ``SealedCheckout`` holds exactly one reachable commit with the gold
              commit and its source blob ABSENT from the object store, its own ``.git``
              directory, byte-identical overlaid tests, export attributes undone and harness
              fix-ups replicated; that ``copy_back`` transfers modified / added / deleted files
              (a tampered test too — belt 1 must see it), keeps the executable bit and refuses
              symlinks and ``.git``; the ``docker run`` shape (every hardening flag, secrets as
              ``--env NAME`` only, never a value on argv), the settings' fail-closed parsing, the
              probe; the egress proxy in process (CONNECT to an allowlisted ``host:port``
              tunnels, anything else 403, non-CONNECT 405); and the adapter's sealed path with a
              fake session — the builder never sees the real worktree, the result is graded
              clean on it, a sandbox failure propagates, an unsealable builder keeps the real
              worktree.
How:          ``SealedCheckout`` on a ``pyrepo`` trial; a local HTTP upstream + the proxy on
              ephemeral ports; ``FakeSession`` stands in for ``ContainerSession``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0012-builder-in-a-sealed-container.md,
              docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/builders/container.py (under test), src/crb/builders/egress_proxy.py
              (the sidecar policy), src/crb/builders/adapter.py (the sealed path),
              src/crb/core/workspace.py (the real worktree the checkout is exported from),
              tests/test_builders_container_docker.py (the same contract against a daemon),
              docs/SECURITY.md (builder containment, §3.2)
Tested by:    tests/test_builders_container.py
Touch when:   a hardening flag, mount or environment rule of the builder container changes
              (the argv case lists every one; update docs/SECURITY.md and the ADR); the export
              gains a fix-up kind.
"""

from __future__ import annotations

import http.server
import os
import socket
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import pytest

import crb.builders as builders_pkg
from crb.builders import adapter, base, egress_proxy
from crb.builders.base import (
    STOP_DONE,
    Budget,
    BuildBrief,
    BuildOutcome,
    EscalationLadder,
    EventFn,
    GitArchaeologyGuard,
    Rung,
)
from crb.builders.claude_code import StreamStats
from crb.builders.container import (
    WORKDIR,
    BuilderContainerSettings,
    SealedCheckout,
    builder_run_args,
    client_env,
    container_env,
    is_secret_env_name,
    probe_builder_container,
)
from crb.core.execution import LocalExecutor, SandboxUnavailable
from crb.core.ledger import JsonlLedger, verify_chain
from crb.core.run import RunSpec, run
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.workspace import HARNESS_SYMLINK, Workspace, sha256_bytes
from fixtures import pyrepo as pr


def _git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(path), *args], capture_output=True, text=True, check=False
    )


@pytest.fixture
def sealed(trial: Workspace, tmp_path: Path) -> Iterator[SealedCheckout]:
    """A ``SealedCheckout`` of the sighted trial (the feat test overlaid), removed afterwards."""
    s = SealedCheckout.create(trial, tmp_path / "sealed", test_files=[pr.TEST_SUBTRACT])
    try:
        yield s
    finally:
        s.remove()


# ---------------------------------------------------------------------------
# SealedCheckout — what the builder can and cannot see
# ---------------------------------------------------------------------------


def test_sealed_checkout_has_one_commit_and_no_gold(
    pyrepo: pr.PyRepo, trial: Workspace, sealed: SealedCheckout
) -> None:
    root = sealed.root
    assert _git(root, "rev-list", "--count", "HEAD").stdout.strip() == "1"
    assert _git(root, "rev-list", "--count", "--all").stdout.strip() == "1"
    assert _git(root, "rev-parse", "HEAD").stdout.strip() == sealed.commit
    # the control: the real worktree CAN reach the gold commit (shared object store)
    assert _git(trial.root, "cat-file", "-e", pyrepo.feat_sha).returncode == 0
    # the sealed checkout cannot — not the commit, not even the answer's blob
    assert _git(root, "cat-file", "-e", pyrepo.feat_sha).returncode != 0
    gold_blob = _git(trial.root, "rev-parse", f"{pyrepo.feat_sha}:{pr.SRC}").stdout.strip()
    assert len(gold_blob) == 40
    assert _git(root, "cat-file", "-e", gold_blob).returncode != 0
    assert _git(root, "cat-file", "-e", pyrepo.docs_sha).returncode != 0
    # its own repository: a .git DIRECTORY, no alternates, one worktree, no remote
    assert (root / ".git").is_dir()
    assert not (root / ".git" / "objects" / "info" / "alternates").exists()
    assert len(_git(root, "worktree", "list").stdout.strip().splitlines()) == 1
    assert _git(root, "remote").stdout.strip() == ""
    assert str(pyrepo.path) not in (root / ".git" / "config").read_text()


def test_sealed_tree_equals_parent_and_tests_are_overlaid(
    pyrepo: pr.PyRepo, trial: Workspace, sealed: SealedCheckout
) -> None:
    parent = pyrepo.initial_sha
    expected = set(_git(trial.root, "ls-tree", "-r", "--name-only", parent).stdout.split())
    tracked = set(_git(sealed.root, "ls-tree", "-r", "--name-only", "HEAD").stdout.split())
    assert tracked == expected
    for rel in expected:
        assert (sealed.root / rel).read_bytes() == subprocess.run(
            ["git", "-C", str(trial.root), "show", f"{parent}:{rel}"],
            capture_output=True,
            check=True,
        ).stdout
    # the source is the PARENT's (no feat), the test is the COMMIT's (overlaid)
    assert (sealed.root / pr.SRC).read_text() == pr.SRC_INITIAL
    assert (sealed.root / pr.TEST_SUBTRACT).read_bytes() == (
        trial.root / pr.TEST_SUBTRACT
    ).read_bytes()
    ws = sealed.workspace()
    assert ws.root == sealed.root and ws.parent == sealed.commit
    assert ws.touched_files() == [pr.TEST_SUBTRACT]  # exactly as the real worktree
    assert trial.touched_files() == [pr.TEST_SUBTRACT]
    ok, offending = ws.tests_byte_identical([pr.TEST_SUBTRACT])
    assert ok and offending == []
    # the oracle reference is a dangling commit (no ref) — not reachable from HEAD
    assert sealed.oracle_commit != sealed.commit
    assert (
        _git(sealed.root, "merge-base", "--is-ancestor", sealed.oracle_commit, "HEAD").returncode
        != 0
    )


def test_sealed_checkout_blind_mode_has_no_tests(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    ws = pyrepo.trial(tmp_path / "blind", overlay_tests=False)
    try:
        s = SealedCheckout.create(ws, tmp_path / "sealed-blind")
        try:
            assert not (s.root / pr.TEST_SUBTRACT).exists()
            assert s.oracle_commit == s.commit
            assert s.workspace().touched_files() == []
        finally:
            s.remove()
    finally:
        ws.remove()


def test_export_attributes_are_undone(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    """``git archive`` honours export-ignore/export-subst; the sealed tree must not."""
    root = pyrepo.path
    (root / ".gitattributes").write_text("docs/ export-ignore\nVERSION export-subst\n")
    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text("# guide\n")
    (root / "VERSION").write_text("$Format:%H$\n")
    pr.git(root, "add", "-A")
    pr.git(root, "commit", "-q", "-m", "chore: attributes")
    (root / pr.SRC).write_text(pr.SRC_FEAT + "\n# more\n")
    pr.git(root, "add", "-A")
    feat2 = pr._commit(root, "feat: again")
    ws = Workspace.create(pyrepo.repo, feat2, tmp_path / "trial2", config=pyrepo.config)
    try:
        s = SealedCheckout.create(ws, tmp_path / "sealed2")
        try:
            assert (s.root / "docs" / "guide.md").read_text() == "# guide\n"
            assert (s.root / "VERSION").read_text() == "$Format:%H$\n"
            tracked = set(_git(s.root, "ls-tree", "-r", "--name-only", "HEAD").stdout.split())
            assert {"docs/guide.md", "VERSION", ".gitattributes"} <= tracked
        finally:
            s.remove()
    finally:
        ws.remove()


def test_harness_fixups_are_replicated(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    ws = pyrepo.trial(tmp_path / "trial-h")
    try:
        stub = ws.root / "stub.cfg"
        stub.write_bytes(b"stub\n")
        ws.harness_files["stub.cfg"] = sha256_bytes(b"stub\n")
        target = tmp_path / "shared-node_modules"
        target.mkdir()
        (ws.root / "node_modules").symlink_to(target)
        ws.harness_files["node_modules"] = HARNESS_SYMLINK
        s = SealedCheckout.create(ws, tmp_path / "sealed-h", test_files=[pr.TEST_SUBTRACT])
        try:
            assert (s.root / "stub.cfg").read_bytes() == b"stub\n"
            assert (s.root / "node_modules").is_symlink()
            assert os.readlink(s.root / "node_modules") == str(target)
            assert s.link_targets == {"node_modules": str(target)}
            # neither is a builder change in the sealed view (excluded / unchanged)
            assert s.workspace().touched_files() == [pr.TEST_SUBTRACT]
            assert "/node_modules" in (s.root / ".git" / "info" / "exclude").read_text()
        finally:
            s.remove()
    finally:
        ws.remove()


# ---------------------------------------------------------------------------
# copy_back — the builder's result reaches the real worktree; nothing else does
# ---------------------------------------------------------------------------


def test_copy_back_transfers_modified_added_deleted_and_tampered(
    trial: Workspace, sealed: SealedCheckout
) -> None:
    (sealed.root / pr.SRC).write_text(pr.SRC_FEAT)
    (sealed.root / "src" / "calc" / "extra.py").write_text("X = 1\n")
    (sealed.root / "pytest.ini").unlink()
    (sealed.root / pr.TEST_SUBTRACT).write_text("def test_subtract():\n    assert True\n")
    kinds = {c.path: c.kind for c in sealed.diff_against_parent()}
    assert kinds == {
        pr.SRC: "modified",
        "src/calc/extra.py": "added",
        "pytest.ini": "deleted",
        pr.TEST_SUBTRACT: "added",
    }
    result = sealed.copy_back(trial)
    assert set(result.copied) == {pr.SRC, "src/calc/extra.py", pr.TEST_SUBTRACT}
    assert result.deleted == ("pytest.ini",)
    assert result.refused == ()
    assert (trial.root / pr.SRC).read_text() == pr.SRC_FEAT
    assert (trial.root / "src" / "calc" / "extra.py").read_text() == "X = 1\n"
    assert not (trial.root / "pytest.ini").exists()
    # the tampered oracle DID cross: belt 1 on the real worktree catches it
    ok, offending = trial.tests_byte_identical([pr.TEST_SUBTRACT])
    assert not ok and offending == [pr.TEST_SUBTRACT]
    assert sorted(trial.touched_files()) == sorted(
        [pr.SRC, "src/calc/extra.py", "pytest.ini", pr.TEST_SUBTRACT]
    )


def test_copy_back_leaves_unchanged_files_alone(trial: Workspace, sealed: SealedCheckout) -> None:
    before = {p: (trial.root / p).stat().st_mtime_ns for p in trial.touched_files()}
    result = sealed.copy_back(trial)
    assert result.copied == () and result.deleted == () and result.refused == ()
    assert result.unchanged == (pr.TEST_SUBTRACT,)
    assert {p: (trial.root / p).stat().st_mtime_ns for p in before} == before


def test_copy_back_refuses_symlinks_and_git(trial: Workspace, sealed: SealedCheckout) -> None:
    (sealed.root / "src" / "calc" / "evil.py").symlink_to("../../.git/config")
    (sealed.root / "src" / "calc" / "out.txt").symlink_to("/etc/hostname")
    (trial.root / "src" / "calc" / "link.py").symlink_to("__init__.py")  # dest is a link
    (sealed.root / "src" / "calc" / "link.py").write_text("x = 1\n")
    result = sealed.copy_back(trial)
    assert result.copied == ()
    assert any("evil.py" in r and "symlink" in r for r in result.refused)
    assert any("out.txt" in r and "symlink" in r for r in result.refused)
    assert any("link.py" in r and "destination is a symlink" in r for r in result.refused)
    assert not (trial.root / "src" / "calc" / "evil.py").exists()
    assert not (trial.root / "src" / "calc" / "evil.py").is_symlink()
    assert (trial.root / "src" / "calc" / "link.py").is_symlink()
    assert (trial.root / ".git").is_file()  # the worktree's gitdir pointer is untouched


def test_copy_back_keeps_executable_bit(trial: Workspace, sealed: SealedCheckout) -> None:
    script = sealed.root / "tool.sh"
    script.write_text("#!/bin/sh\necho hi\n")
    script.chmod(0o755)
    sealed.copy_back(trial)
    assert (trial.root / "tool.sh").stat().st_mode & 0o111


# ---------------------------------------------------------------------------
# Settings + the docker run shape
# ---------------------------------------------------------------------------


def test_settings_from_env_default_is_host() -> None:
    assert BuilderContainerSettings.from_env({}) is None
    assert BuilderContainerSettings.from_env({"CRB_BUILDER__EXECUTOR": "host"}) is None
    with pytest.raises(SandboxUnavailable, match="IMAGE"):
        BuilderContainerSettings.from_env({"CRB_BUILDER__EXECUTOR": "docker"})
    with pytest.raises(SandboxUnavailable, match="not one of"):
        BuilderContainerSettings.from_env({"CRB_BUILDER__EXECUTOR": "podman"})


def test_settings_from_env_parses_everything() -> None:
    s = BuilderContainerSettings.from_env(
        {
            "CRB_BUILDER__EXECUTOR": "docker",
            "CRB_BUILDER__IMAGE": "crb-builder:local",
            "CRB_BUILDER__PROXY_IMAGE": "python:3.12-slim",
            "CRB_BUILDER__ALLOW_HOSTS": "api.anthropic.com, my.openai.azure.com:443",
            "CRB_BUILDER__EGRESS_NETWORK": "egress",
            "CRB_BUILDER__MEMORY": "8g",
            "CRB_BUILDER__PIDS_LIMIT": "2048",
            "CRB_BUILDER__USER": "10001:10001",
        }
    )
    assert s is not None
    assert s.image == "crb-builder:local" and s.proxy_image == "python:3.12-slim"
    assert s.allow_hosts == ("api.anthropic.com", "my.openai.azure.com:443")
    assert s.egress_network == "egress" and s.memory == "8g" and s.pids_limit == 2048
    assert s.user == "10001:10001" and s.networked
    d = s.describe()
    assert d["builder_executor"] == "docker" and d["allow_hosts"] == list(s.allow_hosts)


def test_settings_fail_closed() -> None:
    with pytest.raises(SandboxUnavailable, match="root"):
        BuilderContainerSettings(image="i", user="0:0")
    with pytest.raises(SandboxUnavailable, match="root"):
        BuilderContainerSettings(image="i", user="root")
    with pytest.raises(SandboxUnavailable, match="allowlist"):
        BuilderContainerSettings(image="i", allow_hosts=("bad host",))
    with pytest.raises(SandboxUnavailable, match="allowlist"):
        BuilderContainerSettings(image="i", allow_hosts=("*.anthropic.com",))
    with pytest.raises(SandboxUnavailable, match=r"docker\.sock"):
        BuilderContainerSettings(image="i", extra_ro_mounts={"/var/run/docker.sock": "/x"})
    s = BuilderContainerSettings(image="i", allow_hosts=())
    assert not s.networked and s.describe()["egress_network"] == "none"
    assert s.user == f"{os.getuid()}:{os.getgid()}"
    assert s.proxy_image == "i"


def test_builder_run_args_hardening_and_secret_handling(tmp_path: Path) -> None:
    s = BuilderContainerSettings(image="crb-builder:local", user="10001:10001", memory="3g")
    env = {
        "ANTHROPIC_API_KEY": "sk-ant-verysecret",
        "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-secret",
        "HOME": "/tmp",
        "CI": "1",
        "HTTPS_PROXY": "http://proxy:3128",
    }
    args = builder_run_args(
        s,
        checkout=tmp_path / "sealed",
        env=env,
        timeout_s=600,
        network="crb-b-x",
        extra_ro_mounts={"/srv/nm": "/srv/nm"},
    )
    joined = " ".join(args)
    for flag in (
        "--init",
        "--network=crb-b-x",
        "--memory=3g",
        "--cpus=2",
        "--pids-limit=1024",
        "--user=10001:10001",
        "--cap-drop=ALL",
        "--read-only",
        "--stop-timeout=600",
    ):
        assert flag in args, flag
    assert args[args.index("--security-opt") + 1] == "no-new-privileges"
    assert args[args.index("--tmpfs") + 1] == "/tmp:rw,nosuid,nodev,size=1g"
    assert f"type=bind,src={tmp_path / 'sealed'},dst={WORKDIR}" in args  # rw, no `readonly`
    assert "type=bind,src=/srv/nm,dst=/srv/nm,readonly" in args
    assert args[args.index("--workdir") + 1] == WORKDIR
    assert args[-1] == "crb-builder:local"
    # secrets: NAME only; non-secrets: NAME=value
    envs = [args[i + 1] for i, a in enumerate(args) if a == "--env"]
    assert "ANTHROPIC_API_KEY" in envs and "CLAUDE_CODE_OAUTH_TOKEN" in envs
    assert "HOME=/tmp" in envs and "CI=1" in envs and "HTTPS_PROXY=http://proxy:3128" in envs
    assert "verysecret" not in joined and "oat01" not in joined
    assert is_secret_env_name("AZURE_OPENAI_API_KEY") and not is_secret_env_name("HOME")


def test_container_env_and_client_env(monkeypatch: pytest.MonkeyPatch) -> None:
    inside = container_env(
        {"PATH": "/usr/bin", "HOME": "/Users/x", "TMPDIR": "/var/x", "USER": "x", "FOO": "1"},
        proxy_url="http://proxy:3128",
    )
    assert inside["HOME"] == "/tmp" and inside["TMPDIR"] == "/tmp" and inside["FOO"] == "1"
    assert "PATH" not in inside and "USER" not in inside
    assert inside["HTTPS_PROXY"] == "http://proxy:3128" and inside["NO_PROXY"] == ""
    assert "HTTPS_PROXY" not in container_env({}, proxy_url="")
    monkeypatch.setenv("DOCKER_HOST", "unix:///tmp/colima.sock")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "leak")
    monkeypatch.setenv("SOMETHING_ELSE", "leak")
    ce = client_env({"ANTHROPIC_API_KEY": "sk-1"})
    assert ce["DOCKER_HOST"] == "unix:///tmp/colima.sock" and ce["ANTHROPIC_API_KEY"] == "sk-1"
    assert "AWS_SECRET_ACCESS_KEY" not in ce and "SOMETHING_ELSE" not in ce
    assert "PATH" in ce


def test_probe_reports_off_and_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CRB_BUILDER__EXECUTOR", raising=False)
    assert probe_builder_container()[0] == "off"
    status, detail = probe_builder_container(
        BuilderContainerSettings(image="i", docker_binary="/nonexistent/docker")
    )
    assert status == "down" and "docker" in detail
    monkeypatch.setenv("CRB_BUILDER__EXECUTOR", "docker")
    status, detail = probe_builder_container()
    assert status == "down" and "IMAGE" in detail


# ---------------------------------------------------------------------------
# StreamStats: container paths are the guard's host paths
# ---------------------------------------------------------------------------


def test_stream_stats_translates_container_paths(trial: Workspace) -> None:
    guard = base.TestFileGuard(trial.root, pr.default_config(), [pr.TEST_SUBTRACT])
    stats = StreamStats(GitArchaeologyGuard(cwd=trial.root), guard, workdir_alias="/work")
    assert stats.host_view("/work/src/x.py") == f"{trial.root}/src/x.py"
    assert stats.host_view("/workspace/x") == "/workspace/x"  # not a component match
    assert (
        stats.host_view("cd /work && git diff /work/src")
        == f"cd {trial.root} && git diff {trial.root}/src"
    )
    stats.feed(
        '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit",'
        '"input":{"file_path":"/work/src/calc/__init__.py"}}]}}',
        keep=False,
    )
    assert stats.refused == [] and stats.write_paths == ["/work/src/calc/__init__.py"]
    stats.feed(
        '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit",'
        '"input":{"file_path":"/work/tests/test_subtract.py"}}]}}',
        keep=False,
    )
    assert any("immutable" in r for r in stats.refused)
    stats.feed(
        '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash",'
        '"input":{"command":"git diff /work/src/calc/__init__.py"}}]}}',
        keep=False,
    )
    assert stats.violations == []
    stats.feed(
        '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash",'
        '"input":{"command":"git log --oneline"}}]}}',
        keep=False,
    )
    assert len(stats.violations) == 1 and "archaeology" in stats.violations[0]
    # the transcript keeps what the agent actually ran
    assert stats.bash_commands[0] == "git diff /work/src/calc/__init__.py"


# ---------------------------------------------------------------------------
# The egress proxy, in process
# ---------------------------------------------------------------------------


class _Quiet(http.server.BaseHTTPRequestHandler):
    """A silent HTTP handler for the upstream the proxy tunnels to."""

    def do_GET(self) -> None:
        body = b"model-endpoint-ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a: Any) -> None:
        pass


@pytest.fixture
def upstream() -> Iterator[int]:
    """A local HTTP server on an ephemeral port — the only host the proxy's allowlist names."""
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Quiet)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()


@pytest.fixture
def proxy(upstream: int) -> Iterator[tuple[int, list[str]]]:
    """An ``EgressProxy`` allowing only ``127.0.0.1:<upstream>``; yields its port and captured log
    lines.
    """
    lines: list[str] = []
    server = egress_proxy.EgressProxy(("127.0.0.1", 0), {"127.0.0.1": upstream})
    server.log = lines.append  # type: ignore[method-assign]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield server.server_address[1], lines
    finally:
        server.shutdown()
        server.server_close()


def _raw(port: int, payload: bytes, *, then: bytes = b"") -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(payload)
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = s.recv(4096)
            if not chunk:
                return head
            head += chunk
        if then:
            s.sendall(then)
            body = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                body += chunk
                if b"model-endpoint-ok" in body:
                    break
            return head + body
        return head


def test_proxy_tunnels_only_to_the_allowlist(proxy: tuple[int, list[str]], upstream: int) -> None:
    port, lines = proxy
    ok = _raw(
        port,
        f"CONNECT 127.0.0.1:{upstream} HTTP/1.1\r\nHost: 127.0.0.1:{upstream}\r\n\r\n".encode(),
        then=b"GET / HTTP/1.0\r\nHost: x\r\n\r\n",
    )
    assert ok.startswith(b"HTTP/1.1 200") and b"model-endpoint-ok" in ok
    denied = _raw(port, b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
    assert denied.startswith(b"HTTP/1.1 403")
    wrong_port = _raw(port, b"CONNECT 127.0.0.1:1 HTTP/1.1\r\n\r\n")
    assert wrong_port.startswith(b"HTTP/1.1 403")
    plain = _raw(port, b"GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n")
    assert plain.startswith(b"HTTP/1.1 405")
    bad = _raw(port, b"CONNECT nonsense HTTP/1.1\r\n\r\n")
    assert bad.startswith(b"HTTP/1.1 403")
    assert f"allow 127.0.0.1:{upstream}" in lines
    assert "deny example.com:443" in lines and "deny 127.0.0.1:1" in lines
    assert "deny method=GET" in lines


def test_proxy_allowlist_parsing() -> None:
    assert egress_proxy.parse_allow(["api.anthropic.com", "Mock.Local.:8443"]) == {
        "api.anthropic.com": 443,
        "mock.local": 8443,
    }
    for bad in ("", "a b", "*.x.com", "host:99999", "h/p"):
        with pytest.raises(ValueError):
            egress_proxy.parse_allow([bad])
    allow = {"api.anthropic.com": 443}
    assert egress_proxy.decide(allow, "API.ANTHROPIC.COM.:443") == (True, "api.anthropic.com", 443)
    assert egress_proxy.decide(allow, "api.anthropic.com:80")[0] is False
    assert egress_proxy.decide(allow, "evil.anthropic.com:443")[0] is False
    assert egress_proxy.decide(allow, "[::1]:443")[0] is False


def test_proxy_main_requires_an_allowlist() -> None:
    with pytest.raises(SystemExit):
        egress_proxy.main(["--listen", "127.0.0.1:0"])


# ---------------------------------------------------------------------------
# The adapter's sealed path with a fake session
# ---------------------------------------------------------------------------


class SealedFakeBuilder:
    """Registered as ``fake``; writes the feat source into whatever workspace it gets
    and records what that workspace could see."""

    name = "fake"
    seen: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, *, model: str, provider: str = "", **cfg: Any) -> None:
        self.model = model
        self.provider = provider
        self.cfg = cfg

    def describe(self) -> dict[str, Any]:
        return {"builder": self.name, "model": self.model}

    def build(
        self,
        workspace: Workspace,
        brief: BuildBrief,
        budget: Budget,
        *,
        on_event: EventFn | None = None,
    ) -> BuildOutcome:
        gold = workspace.repo.run("cat-file", "-e", self.cfg["gold_sha"], cwd=workspace.root)
        SealedFakeBuilder.seen.append(
            {"root": workspace.root, "gold_reachable": gold.ok, "cfg": dict(self.cfg)}
        )
        (workspace.root / pr.SRC).write_text(pr.SRC_FEAT)
        return BuildOutcome(
            builder=self.name,
            model=self.model,
            provider=self.provider,
            mode=brief.mode,
            done=True,
            stop_reason=STOP_DONE,
            budget=budget,
        )


class FakeSession:
    """Stands in for :class:`ContainerSession`: no daemon, records the lifecycle."""

    calls: ClassVar[list[str]] = []
    fail: ClassVar[bool] = False

    def __init__(
        self, settings: BuilderContainerSettings, checkout: SealedCheckout, **kw: Any
    ) -> None:
        self.settings = settings
        self.checkout = checkout
        self.kw = kw

    def __enter__(self) -> FakeSession:
        FakeSession.calls.append("enter")
        if FakeSession.fail:
            raise SandboxUnavailable("egress proxy unhealthy (fake)")
        return self

    def __exit__(self, *exc: object) -> None:
        FakeSession.calls.append("exit")

    def overrides_for(self, builder: str) -> dict[str, Any]:
        return {"session_marker": self.checkout.commit}


@pytest.fixture
def sealed_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    """Register ``SealedFakeBuilder`` as ``fake``, mark it sealable, and reset the fake session's
    recorded lifecycle.
    """
    monkeypatch.setitem(builders_pkg._REGISTRY, "fake", SealedFakeBuilder)
    monkeypatch.setattr(adapter, "SEALABLE_BUILDERS", frozenset({"fake"}))
    SealedFakeBuilder.seen = []
    FakeSession.calls = []
    FakeSession.fail = False


def _spec(
    pyrepo: pr.PyRepo, tmp_path: Path, ladder: EscalationLadder
) -> tuple[RunSpec, JsonlLedger]:
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")
    spec = RunSpec(
        run_id="run-sealed",
        config=pyrepo.config,
        runner=PytestRunner(pyrepo.config),
        executor=LocalExecutor(),
        scratch=tmp_path / "scratch",
        ledger=ledger,
        evidence_dir=tmp_path / "evidence",
        ladder=adapter.ladder_labels(ladder),
    )
    return spec, ledger


def test_adapter_sealed_path_grades_clean_on_the_real_worktree(
    pyrepo: pr.PyRepo, tmp_path: Path, sealed_fake: None
) -> None:
    ladder = EscalationLadder((Rung("fake", "m1", config={"gold_sha": pyrepo.feat_sha}),))
    spec, ledger = _spec(pyrepo, tmp_path, ladder)
    events: list[tuple[str, dict[str, Any]]] = []
    fn = adapter.build_fn_for(
        ladder,
        budget=Budget(),
        runner=spec.runner,
        executor=spec.executor,
        config=pyrepo.config,
        on_event=lambda a, p: events.append((a, dict(p))),
        container=BuilderContainerSettings(image="crb-builder:test"),
        session_factory=FakeSession,
    )
    summary = run(spec, pyrepo.repo, [pyrepo.feat_task()], fn)
    assert (summary.tasks, summary.clean, summary.rows) == (1, 1, 1)
    (row,) = ledger.rows()
    assert row.clean and row.error == "" and verify_chain([row]) == 1
    (seen,) = SealedFakeBuilder.seen
    assert seen["root"].name.endswith("-sealed") and seen["gold_reachable"] is False
    assert seen["cfg"]["session_marker"]  # the session's overrides reached the builder
    assert FakeSession.calls == ["enter", "exit"]
    actions = [a for a, _ in events]
    assert "builder.sealed" in actions and "builder.copy_back" in actions
    copy = next(p for a, p in events if a == "builder.copy_back")
    assert copy["copied"] == [pr.SRC] and copy["refused"] == []
    assert not seen["root"].exists()  # the sealed checkout is removed after the attempt


def test_adapter_sealed_path_fails_closed(
    pyrepo: pr.PyRepo, tmp_path: Path, sealed_fake: None
) -> None:
    FakeSession.fail = True
    ladder = EscalationLadder((Rung("fake", "m1", config={"gold_sha": pyrepo.feat_sha}),))
    spec, ledger = _spec(pyrepo, tmp_path, ladder)
    fn = adapter.build_fn_for(
        ladder,
        budget=Budget(),
        runner=spec.runner,
        executor=spec.executor,
        config=pyrepo.config,
        container=BuilderContainerSettings(image="crb-builder:test"),
        session_factory=FakeSession,
    )
    summary = run(spec, pyrepo.repo, [pyrepo.feat_task()], fn)
    # the orchestrator stops the run (ADR-0005) — no attempt, no verdict of either kind
    assert summary.stopped_reason.startswith("sandbox unavailable: egress proxy unhealthy")
    assert summary.rows == 0 and list(ledger.rows()) == []
    assert SealedFakeBuilder.seen == []  # the builder never ran on the host
    # and the build_fn itself raises rather than recording a host-side attempt
    ws = pyrepo.trial(tmp_path / "direct")
    try:
        with pytest.raises(SandboxUnavailable, match="egress proxy"):
            fn(ws, pyrepo.feat_task(), "sighted", "fake:m1")
    finally:
        ws.remove()


def test_adapter_unsealable_builder_keeps_the_real_worktree(
    pyrepo: pr.PyRepo, tmp_path: Path, sealed_fake: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(adapter, "SEALABLE_BUILDERS", frozenset())
    ladder = EscalationLadder((Rung("fake", "m1", config={"gold_sha": pyrepo.feat_sha}),))
    spec, _ledger = _spec(pyrepo, tmp_path, ladder)
    fn = adapter.build_fn_for(
        ladder,
        budget=Budget(),
        runner=spec.runner,
        executor=spec.executor,
        config=pyrepo.config,
        container=BuilderContainerSettings(image="crb-builder:test"),
        session_factory=FakeSession,
    )
    run(spec, pyrepo.repo, [pyrepo.feat_task()], fn)
    (seen,) = SealedFakeBuilder.seen
    assert seen["gold_reachable"] is True and FakeSession.calls == []


def test_container_settings_from_env_is_the_worker_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CRB_BUILDER__EXECUTOR", raising=False)
    assert adapter.container_settings_from_env() is None
    monkeypatch.setenv("CRB_BUILDER__EXECUTOR", "docker")
    monkeypatch.setenv("CRB_BUILDER__IMAGE", "crb-builder:local")
    s = adapter.container_settings_from_env()
    assert s is not None and s.image == "crb-builder:local"
