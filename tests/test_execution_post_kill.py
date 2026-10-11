"""After a kill, every runner waits for the killed command's output a BOUNDED time (P-774).

The fault this pins: a group kill (``killpg``) does not end every process holding the
client's stdout and stderr. One that called ``setsid`` is outside the group; on macOS one
forked as the ``killpg`` is sent survives it INSIDE the group (measured, P-774). A reader
that waits for EOF waits for either. Each fake client here starts such a process: a
grandchild that keeps the pipes open for 30 s — silent, or writing every 10 ms, or still in
the group past the first kill. Before the fix every kill path below waited the whole 30 s
for the first; the stream readers waited for a writer however long it wrote; and nothing
killed the group again, so a survivor in it held the pipes until the bound gave up.

Navigation
----------
What it is:   The deterministic, no-load suite for the post-kill bound: each kill path is
              driven against a client whose grandchild survives the group kill and holds the
              output pipes open.
What it does: Asserts that ``DockerExecutor.run`` (cancel and wall clock),
              ``LocalExecutor.run`` (cancel and wall clock), ``DockerStream.lines`` (cancel and
              wall clock), the claude CLI ``SubprocessHandle`` and the provision fetch each
              return within ``POST_KILL_DRAIN_S`` (shortened to 0.5 s) plus a margin of the
              kill — with the right return code, ``cancelled`` / ``timed_out`` /
              ``kill_confirmed``, the output written before the kill, a warning that names the
              container or command, and the killed client reaped (no zombie) while the escaped
              holder still runs. And that the path with no kill reads exactly what it read
              before: ``LocalExecutor`` output equals ``subprocess.run(text=True)`` and
              ``DockerStream`` lines equal iterating a ``TextIOWrapper`` over the same bytes
              (CRLF, a lone CR, multibyte characters split across reads, invalid bytes).
              Then, on all five paths: a holder that keeps WRITING is bounded the same (the
              stream readers check the bound before every read, not only on a silent pipe);
              a holder still IN the group after the first kill (the macOS race, reproduced by
              a ``killpg`` whose first call per group reaches only the leader) is killed by
              the second group kill at the bound, with a warning, and the output reaches EOF;
              and an abandoned ``OutputDrain`` has stopped and closed both pipes when
              ``finish_after_kill`` returns.
How:          A ``/bin/sh`` client writes its pid, starts ``holder.py`` in the background
              (``setsid`` — or not, for the in-group holder — writes its pid, sleeps or writes
              until released or 30 s), waits for it, prints ``hello`` / ``oops`` and a
              ``ready`` file, then ``exec``-s a sleep. The cancel token fires on ``ready``.
              Teardown releases every holder and SIGKILLs one still alive (checked to be the
              session it started, or a member of the client's group), so no sleeper outlives
              a test.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/core/execution.py (under test: ``OutputDrain``, ``read_lines``,
              ``reap_after_kill``), src/crb/builders/claude_code.py (``SubprocessHandle``),
              src/crb/provision/fetch.py (the fetch runner), tests/test_execution.py (the kill
              and confirmation contract), tests/test_post_kill_wait_ratchet.py (the static
              half: no unbounded wait in a module that kills)
Tested by:    tests/test_execution_post_kill.py
Touch when:   never for a new repository; a runner gains a kill path (add its case here — the
              ratchet already scans it); ``POST_KILL_DRAIN_S`` or the drain's stop interval
              changes (the margins below).
"""

from __future__ import annotations

import contextlib
import io
import os
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from crb.builders.claude_code import SubprocessHandle
from crb.core import execution as ex
from crb.core.deps import ProvisionRefused
from crb.core.execution import Command, DockerExecutor, DockerSettings, LocalExecutor
from crb.provision import fetch as fetch_mod
from crb.provision.config import ProvisionConfig
from crb.provision.fetch import FetchPlan

PY = sys.executable
#: The shortened post-kill bound every test runs under.
BOUND_S = 0.5
#: What a return may take past the bound: the drain's stop (1 s), the kill itself (a fake
#: ``docker kill`` and ``inspect``), one poll, and room for a loaded machine — 10 s in all,
#: above tests/test_wall_clock_bounds.py's floor (P-014). The holder sleeps 30 s, so the
#: bound still tells bounded (about 1 s here) from unbounded (27–30 s before the fix).
MARGIN_S = 9.5
#: The holder: leave the client's process group and session, keep the inherited stdout and
#: stderr open, and sleep until teardown releases it (30 s at most).
HOLDER = (
    "import os, sys, time\n"
    "os.setsid()\n"
    "with open(sys.argv[1], 'w') as f:\n"
    "    f.write(str(os.getpid()))\n"
    "end = time.monotonic() + 30\n"
    "while time.monotonic() < end and not os.path.exists(sys.argv[2]):\n"
    "    time.sleep(0.05)\n"
)
#: The writer: escape like the holder, then — once the client is ready (``argv[3]``) — write
#: a line to the inherited stdout and stderr every 10 ms until released (30 s at most).
WRITER = (
    "import os, sys, time\n"
    "os.setsid()\n"
    "with open(sys.argv[1], 'w') as f:\n"
    "    f.write(str(os.getpid()))\n"
    "end = time.monotonic() + 30\n"
    "while time.monotonic() < end and not os.path.exists(sys.argv[3]):\n"
    "    time.sleep(0.01)\n"
    "while time.monotonic() < end and not os.path.exists(sys.argv[2]):\n"
    "    for fd in (1, 2):\n"
    "        try:\n"
    "            os.write(fd, b'w\\n')\n"
    "        except OSError:\n"
    "            pass\n"
    "    time.sleep(0.01)\n"
)
#: The holder that stays IN the client's process group: the survivor macOS leaves when it
#: forks as the ``killpg`` is sent.
IN_GROUP = HOLDER.replace("os.setsid()\n", "")


@dataclass
class Escaping:
    """One escaping client and the files it reports through."""

    script: Path
    client_pid: Path
    holder_pid: Path
    ready: Path
    release: Path

    def pid(self, which: str) -> int:
        return int((self.client_pid if which == "client" else self.holder_pid).read_text())

    def cancel_on_ready(self, fired: dict[str, float]) -> Callable[[], bool]:
        """A cancel token that fires once the client has written its output; it records
        when it first fired."""

        def cancel() -> bool:
            if self.ready.exists():
                fired.setdefault("at", time.monotonic())
                return True
            return False

        return cancel


@pytest.fixture
def escaping(tmp_path: Path) -> Iterator[Callable[..., Escaping]]:
    """Make escaping clients; release (and if need be kill) every holder afterwards."""
    made: list[Escaping] = []

    def make(name: str = "client", extra: str = "", holder_py: str = HOLDER) -> Escaping:
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        holder = d / "holder.py"
        holder.write_text(holder_py)
        e = Escaping(d / name, d / "client.pid", d / "holder.pid", d / "ready", d / "release")
        e.script.write_text(
            "#!/bin/sh\n"
            'case "$1" in\n'
            "  kill) exit 0 ;;\n"
            '  inspect) echo "Error: No such container: $4" >&2; exit 1 ;;\n'
            "esac\n"
            f'echo $$ > "{e.client_pid}"\n'
            f'"{PY}" "{holder}" "{e.holder_pid}" "{e.release}" "{e.ready}" &\n'
            f'while [ ! -s "{e.holder_pid}" ]; do /bin/sleep 0.02; done\n'
            "echo hello\n"
            "echo oops >&2\n"
            f"{extra}\n"
            f': > "{e.ready}"\n'
            "exec /bin/sleep 30\n"
        )
        e.script.chmod(e.script.stat().st_mode | stat.S_IEXEC)
        made.append(e)
        return e

    yield make
    for e in made:
        e.release.write_text("")
    for e in made:
        if not e.holder_pid.exists():
            continue
        pid = e.pid("holder")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and _alive(pid):
            time.sleep(0.05)
        with contextlib.suppress(OSError):
            # still our holder: its own session, or a member of the client's group
            ours = os.getsid(pid) == pid or os.getpgid(pid) == e.pid("client")
            if _alive(pid) and ours:
                os.kill(pid, signal.SIGKILL)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _assert_bounded_and_clean(
    e: Escaping, waited: float, caplog: pytest.LogCaptureFixture, what: str
) -> None:
    """The return came within the bound, the killed client was reaped, the escaped holder
    is still running (so the bound, not its exit, ended the wait) and a warning named
    ``what``."""
    assert waited < BOUND_S + MARGIN_S, f"waited {waited:.1f}s after the kill"
    with pytest.raises(ChildProcessError):  # reaped: not a zombie child of this process
        os.waitpid(e.pid("client"), os.WNOHANG)
    assert _alive(e.pid("holder")), "the holder exited: the escape was not exercised"
    held = [r.getMessage() for r in caplog.records if "still open" in r.getMessage()]
    assert any(what in m for m in held), [r.getMessage() for r in caplog.records]


def _docker(script: Path, cancel: Callable[[], bool] | None) -> DockerExecutor:
    return DockerExecutor(
        DockerSettings(image="img", docker_binary=str(script)), verify_daemon=False, cancel=cancel
    )


@pytest.fixture
def fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """Poll quickly and bound the post-kill wait at :data:`BOUND_S` on every kill path."""
    monkeypatch.setattr(ex, "_CANCEL_POLL_S", 0.05)
    for cls in (LocalExecutor, DockerExecutor, ex.DockerStream, SubprocessHandle):
        monkeypatch.setattr(cls, "POST_KILL_DRAIN_S", BOUND_S, raising=False)
        monkeypatch.setattr(cls, "KILL_CONFIRM_STEP_S", 0.02, raising=False)
    monkeypatch.setattr(fetch_mod, "_POLL_S", 0.05)
    monkeypatch.setattr(fetch_mod, "POST_KILL_DRAIN_S", BOUND_S, raising=False)


# ---------------------------------------------------------------------------
# DockerExecutor.run — the defect I-09 reproduced (cancel) and its wall-clock twin
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("fast")
def test_docker_run_cancel_returns_within_the_bound_when_a_process_holds_the_pipes(
    tmp_path: Path, escaping: Callable[..., Escaping], caplog: pytest.LogCaptureFixture
) -> None:
    e = escaping()
    fired: dict[str, float] = {}
    with caplog.at_level("WARNING", logger="crb.core.execution"):
        r = _docker(e.script, e.cancel_on_ready(fired)).run(
            Command(("sleep", "60"), tmp_path, timeout=60)
        )
    waited = time.monotonic() - fired["at"]
    assert r.cancelled and not r.timed_out and r.returncode == 130
    assert r.kill_confirmed is True and r.container.startswith("crb-")
    assert "hello" in r.stdout and "oops" in r.stderr  # what came before the kill is kept
    _assert_bounded_and_clean(e, waited, caplog, f"docker container {r.container}")


@pytest.mark.usefixtures("fast")
def test_docker_run_wall_clock_returns_within_the_bound_when_a_process_holds_the_pipes(
    tmp_path: Path, escaping: Callable[..., Escaping], caplog: pytest.LogCaptureFixture
) -> None:
    e = escaping()
    t0 = time.monotonic()
    with caplog.at_level("WARNING", logger="crb.core.execution"):
        r = _docker(e.script, None).run(Command(("sleep", "60"), tmp_path, timeout=3))
    assert e.ready.exists(), "the client never got its holder going inside the wall clock"
    assert r.timed_out and not r.cancelled and r.returncode == 124
    assert r.kill_confirmed is True and "hello" in r.stdout
    _assert_bounded_and_clean(
        e, time.monotonic() - t0 - 3, caplog, f"docker container {r.container}"
    )


# ---------------------------------------------------------------------------
# LocalExecutor.run
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("fast")
def test_local_run_cancel_returns_within_the_bound_when_a_process_holds_the_pipes(
    tmp_path: Path, escaping: Callable[..., Escaping], caplog: pytest.LogCaptureFixture
) -> None:
    e = escaping()
    fired: dict[str, float] = {}
    with caplog.at_level("WARNING", logger="crb.core.execution"):
        r = LocalExecutor(cancel=e.cancel_on_ready(fired)).run(
            Command((str(e.script),), tmp_path, timeout=60)
        )
    waited = time.monotonic() - fired["at"]
    assert r.cancelled and not r.timed_out and r.returncode == 130
    assert r.stdout == "hello\n" and r.stderr == "oops\n"
    _assert_bounded_and_clean(e, waited, caplog, f"command {e.script}")


@pytest.mark.usefixtures("fast")
def test_local_run_wall_clock_returns_within_the_bound_when_a_process_holds_the_pipes(
    tmp_path: Path, escaping: Callable[..., Escaping], caplog: pytest.LogCaptureFixture
) -> None:
    e = escaping()
    t0 = time.monotonic()
    with caplog.at_level("WARNING", logger="crb.core.execution"):
        r = LocalExecutor().run(Command((str(e.script),), tmp_path, timeout=3))
    assert e.ready.exists(), "the client never got its holder going inside the wall clock"
    assert r.timed_out and not r.cancelled and r.returncode == 124
    assert r.stdout == "hello\n"
    _assert_bounded_and_clean(e, time.monotonic() - t0 - 3, caplog, f"command {e.script}")


# ---------------------------------------------------------------------------
# DockerStream.lines
# ---------------------------------------------------------------------------


def _stream(e: Escaping, *, timeout_s: int, cancel: Callable[[], bool] | None) -> ex.DockerStream:
    return ex.DockerStream(
        [str(e.script), "run", "--rm", "--name", "crb-post-kill"],
        docker=str(e.script),
        name="crb-post-kill",
        env={"PATH": os.environ.get("PATH", "")},
        timeout_s=timeout_s,
        cancel=cancel,
    )


@pytest.mark.usefixtures("fast")
def test_docker_stream_cancel_ends_the_lines_within_the_bound(
    escaping: Callable[..., Escaping], caplog: pytest.LogCaptureFixture
) -> None:
    e = escaping()
    fired: dict[str, float] = {}
    with caplog.at_level("WARNING", logger="crb.core.execution"):
        h = _stream(e, timeout_s=60, cancel=e.cancel_on_ready(fired))
        lines = list(h.lines())
    waited = time.monotonic() - fired["at"]
    assert lines == ["hello"]
    assert h.cancelled and not h.timed_out and h.kill_confirmed is True
    assert h.returncode == -signal.SIGKILL and "oops" in h.stderr_tail
    _assert_bounded_and_clean(e, waited, caplog, "docker container crb-post-kill")


@pytest.mark.usefixtures("fast")
def test_docker_stream_wall_clock_ends_the_lines_within_the_bound(
    escaping: Callable[..., Escaping], caplog: pytest.LogCaptureFixture
) -> None:
    e = escaping()
    t0 = time.monotonic()
    with caplog.at_level("WARNING", logger="crb.core.execution"):
        h = _stream(e, timeout_s=3, cancel=None)
        lines = list(h.lines())
    assert e.ready.exists(), "the client never got its holder going inside the wall clock"
    assert lines == ["hello"]
    assert h.timed_out and not h.cancelled and h.kill_confirmed is True
    _assert_bounded_and_clean(
        e, time.monotonic() - t0 - 3, caplog, "docker container crb-post-kill"
    )


# ---------------------------------------------------------------------------
# The claude CLI transport and the provision fetch — the same class of wait
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("fast")
def test_claude_cli_handle_kill_ends_the_lines_within_the_bound(
    tmp_path: Path, escaping: Callable[..., Escaping], caplog: pytest.LogCaptureFixture
) -> None:
    e = escaping()
    h = SubprocessHandle([str(e.script)], {"PATH": os.environ.get("PATH", "")}, tmp_path, 60)
    with caplog.at_level("WARNING", logger="crb.core.execution"):
        it = h.lines()
        assert next(it) == "hello"
        deadline = time.monotonic() + 30
        while not e.ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        h.kill()  # what the watchdog and a cancelling builder call
        killed = time.monotonic()
        rest = list(it)
    assert rest == []
    assert h.returncode == -signal.SIGKILL and "oops" in h.stderr_tail
    pid = e.pid("client")
    _assert_bounded_and_clean(e, time.monotonic() - killed, caplog, f"claude CLI (pid {pid})")


def _fetch_breach(
    make: Callable[..., Escaping], tmp_path: Path, holder_py: str
) -> tuple[Escaping, float]:
    """Run a fetch whose client writes 2 MB against a 1 MB cap, so it is killed at once;
    return the client and the seconds from the breach to the refusal."""
    stage = tmp_path / "stage"
    (stage / "out").mkdir(parents=True)
    blob = stage / "out" / "blob"
    e = make(
        extra=f'/bin/dd if=/dev/zero of="{blob}" bs=1048576 count=2 2>/dev/null',
        holder_py=holder_py,
    )
    plan = FetchPlan(
        recipe="go.modcache.v1", lang="go", key="dep_" + "c" * 64, image="img", argv=("true",)
    )
    cfg = ProvisionConfig(enabled=True, env="dev", max_bundle_mb=1, fetch_timeout_s=60)
    with pytest.raises(ProvisionRefused) as refused:
        fetch_mod._execute(
            plan,
            [str(e.script)],
            stage=stage,
            name="crb-fetch-post-kill",
            docker=str(e.script),
            config=cfg,
            sidecar=None,
            on_event=None,
        )
    assert refused.value.code == "PROVISION_TOO_LARGE"
    # the breach is seen within one poll of the blob landing
    return e, time.time() - blob.stat().st_mtime


@pytest.mark.usefixtures("fast")
def test_fetch_breach_kill_returns_within_the_bound(
    tmp_path: Path, escaping: Callable[..., Escaping], caplog: pytest.LogCaptureFixture
) -> None:
    """An oversized fetch is killed at once; the refusal comes within the bound although a
    process the kill missed still holds the client's pipes."""
    with caplog.at_level("WARNING", logger="crb.core.execution"):
        e, waited = _fetch_breach(escaping, tmp_path, HOLDER)
    _assert_bounded_and_clean(e, waited, caplog, "fetch container crb-fetch-post-kill")


# ---------------------------------------------------------------------------
# Every kill path: a holder that keeps writing, a survivor still in the group, and the
# drain an abandon leaves behind
# ---------------------------------------------------------------------------

KILL_PATHS = ("docker_run", "local_run", "docker_stream", "claude_cli", "fetch")


def _wait_for(path: Path) -> None:
    deadline = time.monotonic() + 30
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert path.exists(), f"{path} never appeared"


def _drive(
    path: str, make: Callable[..., Escaping], tmp_path: Path, holder_py: str
) -> tuple[Escaping, float, str]:
    """Run a client with ``holder_py`` down kill path ``path`` and kill it once it is ready;
    return the client, the seconds from the kill to the return, and the name the path's
    warnings give it. Each path still delivers the output written before the kill."""
    if path == "fetch":
        e, waited = _fetch_breach(make, tmp_path, holder_py)
        return e, waited, "fetch container crb-fetch-post-kill"
    e = make(holder_py=holder_py)
    fired: dict[str, float] = {}
    cancel = e.cancel_on_ready(fired)
    if path == "docker_run":
        r = _docker(e.script, cancel).run(Command(("sleep", "60"), tmp_path, timeout=60))
        assert r.cancelled and r.returncode == 130 and r.stdout.startswith("hello\n")
        what = f"docker container {r.container}"
    elif path == "local_run":
        r = LocalExecutor(cancel=cancel).run(Command((str(e.script),), tmp_path, timeout=60))
        assert r.cancelled and r.returncode == 130 and r.stdout.startswith("hello\n")
        what = f"command {e.script}"
    elif path == "docker_stream":
        h = _stream(e, timeout_s=60, cancel=cancel)
        lines = list(h.lines())
        assert h.cancelled and h.returncode == -signal.SIGKILL and lines[0] == "hello"
        what = "docker container crb-post-kill"
    else:
        handle = SubprocessHandle(
            [str(e.script)], {"PATH": os.environ.get("PATH", "")}, tmp_path, 60
        )
        it = handle.lines()
        assert next(it) == "hello"
        _wait_for(e.ready)
        handle.kill()
        fired["at"] = time.monotonic()
        for _ in it:
            pass
        assert handle.returncode == -signal.SIGKILL
        what = f"claude CLI (pid {e.pid('client')})"
    return e, time.monotonic() - fired["at"], what


@pytest.mark.usefixtures("fast")
@pytest.mark.parametrize("path", KILL_PATHS)
def test_a_holder_that_keeps_writing_is_bounded_the_same(
    path: str,
    tmp_path: Path,
    escaping: Callable[..., Escaping],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The bound is checked before every read: a process the kill missed that writes every
    10 ms ends the wait at the bound just as a silent one does (before, the stream readers
    bounded only a silent pipe, and read this writer for its whole 30 s)."""
    with caplog.at_level("WARNING", logger="crb.core.execution"):
        e, waited, what = _drive(path, escaping, tmp_path, WRITER)
    _assert_bounded_and_clean(e, waited, caplog, what)


@pytest.fixture
def first_killpg_misses_the_group(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The macOS race, made deterministic: the first ``killpg`` sent to a group reaches only
    its leader — as a member forked while the signal is sent survives it — and every later
    one is the real ``killpg``. Returns the groups signalled, in order."""
    real = os.killpg
    sent: list[int] = []

    def killpg(pgid: int, sig: int) -> None:
        first = pgid not in sent
        sent.append(pgid)
        if first:
            os.kill(pgid, sig)
        else:
            real(pgid, sig)

    monkeypatch.setattr(os, "killpg", killpg)
    return sent


@pytest.mark.usefixtures("fast")
@pytest.mark.parametrize("path", KILL_PATHS)
def test_a_survivor_still_in_the_group_is_killed_by_the_second_group_kill(
    path: str,
    tmp_path: Path,
    escaping: Callable[..., Escaping],
    caplog: pytest.LogCaptureFixture,
    first_killpg_misses_the_group: list[int],
) -> None:
    """At the bound the group is killed again: the member the first kill missed dies, the
    pipes reach EOF, and a warning says the group was killed again — instead of giving up on
    pipes a process in the group still holds (before, nothing killed it again)."""
    with caplog.at_level("WARNING", logger="crb.core.execution"):
        e, waited, what = _drive(path, escaping, tmp_path, IN_GROUP)
    assert waited < BOUND_S + MARGIN_S, f"waited {waited:.1f}s after the kill"
    client, holder = e.pid("client"), e.pid("holder")
    assert first_killpg_misses_the_group.count(client) >= 2, first_killpg_misses_the_group
    with pytest.raises(ChildProcessError):  # reaped: not a zombie child of this process
        os.waitpid(client, os.WNOHANG)
    deadline = time.monotonic() + 2
    while _alive(holder) and time.monotonic() < deadline:  # launchd / init reaps it
        time.sleep(0.02)
    assert not _alive(holder), "the survivor in the group outlived the second group kill"
    messages = [r.getMessage() for r in caplog.records]
    assert any("process group again" in m and what in m for m in messages), messages
    assert not any("outside its process group" in m for m in messages), messages


def test_an_abandoned_drain_has_stopped_and_closed_its_pipes(
    escaping: Callable[..., Escaping], caplog: pytest.LogCaptureFixture
) -> None:
    """``finish_after_kill`` returning ``False`` promises the drain is stopped: its thread
    ends and both pipes are closed, so nothing keeps reading for a process outside the group.
    A drain whose select has no wake-up (``sel.select()``) never sees the stop."""
    e = escaping()
    proc = subprocess.Popen(
        [str(e.script)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        drain = ex.OutputDrain(proc, leads_group=True)
        _wait_for(e.ready)
        os.killpg(proc.pid, signal.SIGKILL)
        with caplog.at_level("WARNING", logger="crb.core.execution"):
            assert drain.finish_after_kill(BOUND_S, "the drained client") is False
        assert drain.abandoned
        assert drain.join(MARGIN_S), "the abandoned drain still runs: it never saw the stop"
        assert proc.stdout is not None and proc.stdout.closed
        assert proc.stderr is not None and proc.stderr.closed
        assert proc.returncode == -signal.SIGKILL
        assert drain.text() == ("hello\n", "oops\n")
        assert _alive(e.pid("holder")), "the holder exited: the escape was not exercised"
    finally:
        if proc.returncode is None:
            with contextlib.suppress(OSError):
                os.killpg(proc.pid, signal.SIGKILL)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# No kill: the output is read exactly as it was before the bound existed
# ---------------------------------------------------------------------------

#: CRLF, a lone CR, a CR before a 32 KiB boundary, two-byte characters the emitter's odd-sized
#: writes split across reads, and a last line with no newline.
TRICKY = (
    "a\r\nb\rc\n"
    + "x" * 32767
    + "é€\n"
    + "y" * 32766
    + "\r"
    + "\n"
    + ("ü" * 20000 + "\r\n") * 3
    + "z"
).encode()


def _emitter(tmp_path: Path, out: bytes, err: bytes) -> list[str]:
    (tmp_path / "out.bin").write_bytes(out)
    (tmp_path / "err.bin").write_bytes(err)
    code = (
        "import sys\n"
        "for name, stream in (('out.bin', sys.stdout), ('err.bin', sys.stderr)):\n"
        "    data = open(sys.argv[1] + '/' + name, 'rb').read()\n"
        "    for i in range(0, len(data), 7001):\n"
        "        stream.buffer.write(data[i:i + 7001]); stream.buffer.flush()\n"
    )
    (tmp_path / "emit.py").write_text(code)
    return [PY, str(tmp_path / "emit.py"), str(tmp_path)]


def test_local_run_without_a_kill_reads_what_subprocess_run_reads(tmp_path: Path) -> None:
    argv = _emitter(tmp_path, TRICKY, TRICKY[::-1].decode("latin-1").encode())
    want = subprocess.run(argv, capture_output=True, text=True, check=False)
    got = LocalExecutor().run(Command(tuple(argv), tmp_path, timeout=60))
    assert got.returncode == 0 and not got.cancelled and not got.timed_out
    assert got.stdout == want.stdout and got.stderr == want.stderr


def test_docker_stream_without_a_kill_yields_what_iterating_the_pipe_yields(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    data = TRICKY + b"\n\xff\xfe bad bytes\r\n\n\nend \xe2\x82"  # invalid and truncated
    payload = tmp_path / "payload.bin"
    payload.write_bytes(data)
    script = tmp_path / "docker"
    script.write_text(f'#!/bin/sh\ncase "$1" in run) /bin/cat "{payload}" ;; esac\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    want = [
        line.rstrip("\n")
        for line in io.TextIOWrapper(io.BytesIO(data), encoding="utf-8", errors="replace")
    ]
    with caplog.at_level("WARNING", logger="crb.core.execution"):
        h = ex.DockerStream(
            [str(script), "run"],
            docker=str(script),
            name="crb-plain",
            env={"PATH": os.environ.get("PATH", "")},
            timeout_s=60,
        )
        got = list(h.lines())
    assert got == want and h.returncode == 0 and h.kill_confirmed is None
    assert not [r for r in caplog.records if "still open" in r.getMessage()]
