"""The container reaper: an enforced ``docker kill`` the daemon never confirmed is not
forgotten — it is recorded, retried from the worker loop, and reported either way.

``DockerStream.kill()`` (src/crb/core/execution.py) waits at most ``KILL_CONFIRM_S`` for the
daemon to report the container not running. When that bound is hit the stream ends with
``kill_confirmed: False`` and the container MAY STILL BE RUNNING. The run still ends
``cancelled`` / timed out — it did stop building — but the container is handed here.

Invariants:

* **Durable.** The queue is a JSON file under ``CRB_HOME`` (``<home>/unconfirmed-containers.json``,
  written atomically) so a worker restart continues reaping; an unreadable file is treated as
  empty with a warning and repaired by the next write — never a crash in the loop.
* **Bounded.** Every worker poll makes one pass: ``docker inspect`` (the strict question —
  :func:`crb.core.execution.container_stopped`), then ``docker rm -f`` (kills and removes;
  idempotent), then ``inspect`` again. Gone or not running = ``reaped``. Otherwise the attempt
  counts, and at :attr:`ContainerReaper.max_attempts` the entry is reported ``failed`` once and
  DROPPED: the run's trace carries ``run.kill_reap_failed`` and the run's error already told
  the operator ``docker rm -f <name>`` — the loop does not retry forever.
* **Budgeted in time.** A pass takes ``budget_s`` (the worker passes ``heartbeat_s / 2``):
  every docker call is capped to the time left in the pass, an entry the budget runs out on
  counts as an attempt with the reason (``pass budget exhausted``), and the entries the pass
  never reached are left untouched for the next poll. A daemon that answers nothing therefore
  costs the idle loop at most the budget per poll — the worker's check-in that follows is
  never later than its own liveness bound (``3 × heartbeat_s``).
* **Visible.** :meth:`ContainerReaper.pending_count` is what the worker stamps on its
  ``workers`` row (``unconfirmed_containers``) so the ``/health`` worker probe reports it and
  reads ``degraded`` while it is above zero.

Navigation
----------
What it is:   ``ContainerReaper`` — the durable queue of containers whose enforced kill was
              not confirmed, and the one bounded reap pass the worker loop runs every poll.
What it does: Persists ``(container, run_id, task_id, attempts)`` under ``CRB_HOME``; per
              pass asks the daemon, force-removes, re-asks and reports ``reaped`` or, at the
              bound, ``failed`` (then drops the entry); counts what is pending for the health
              probe. Never raises into the loop; never decides anything about a run's status.
How:          ``add`` → JSON file (tmp + rename) → ``reap_once(budget_s)``: per entry, while
              the pass has time left, ``container_stopped`` → ``docker rm -f`` →
              ``container_stopped`` (each call capped to the remainder) → ``ReapResult`` per
              entry that ended.
Layer:        server — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0012-builder-in-a-sealed-container.md,
              docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/server/worker.py (queues on ``run.kill_unconfirmed``, runs a pass every
              poll and writes ``run.kill_reaped`` / ``run.kill_reap_failed`` on the run's
              trace; stamps ``pending_count`` on its check-in row),
              src/crb/core/execution.py (``container_stopped`` — the strict inspect question;
              ``DockerStream.kill_confirmed`` — the signal that queues an entry),
              src/crb/builders/adapter.py (``on_kill_unconfirmed`` — how the signal reaches
              the worker), src/crb/server/routes/system.py (the probe that reports
              ``unconfirmed_containers``)
Tested by:    tests/test_server_reaper.py, tests/test_worker.py
Touch when:   the reap sequence or the bound changes (docs/API.md's cancel row and ADR-0012
              state them); never for a new repository.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from crb.core.evidence import utc_now_iso
from crb.core.execution import INSPECT_TIMEOUT_S, container_stopped

_LOG = logging.getLogger(__name__)

#: The file under ``CRB_HOME`` that holds the queue.
STATE_FILENAME = "unconfirmed-containers.json"
#: Reap passes (one per worker poll) before an entry is reported failed and dropped.
MAX_ATTEMPTS = 20
#: ``docker rm -f`` may have to kill first; give it longer than one inspect.
RM_TIMEOUT_S = 30.0
#: The reason an entry carries when the pass's time budget ran out on it.
BUDGET_EXHAUSTED = "pass budget exhausted"


@dataclass(frozen=True)
class Unconfirmed:
    """One queued container: where it came from and how many passes it has survived."""

    container: str
    run_id: str
    task_id: str
    attempts: int = 0
    added: str = ""
    last_error: str = ""


@dataclass(frozen=True)
class ReapResult:
    """An entry that LEFT the queue this pass: ``reaped`` (the daemon reports it gone or not
    running) or not (the bound was hit — ``detail`` carries the by-hand command)."""

    entry: Unconfirmed
    reaped: bool
    attempts: int
    detail: str = ""


def by_hand(container: str) -> str:
    """The command the operator runs when the reaper cannot."""
    return f"docker rm -f {container}"


class ContainerReaper:
    def __init__(
        self,
        path: Path,
        *,
        docker: str = "docker",
        max_attempts: int = MAX_ATTEMPTS,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.path = Path(path)
        self.docker = docker
        self.max_attempts = max(1, int(max_attempts))
        self._runner = runner
        self._lock = threading.Lock()

    # --- state ---------------------------------------------------------------------
    def pending(self) -> list[Unconfirmed]:
        """The queue as stored; an unreadable file is empty (warned once per read)."""
        with self._lock:
            return self._read()

    def pending_count(self) -> int:
        return len(self.pending())

    def add(self, container: str, *, run_id: str, task_id: str) -> None:
        """Queue ``container`` (idempotent per name — a re-add keeps the first record)."""
        with self._lock:
            entries = self._read()
            if any(e.container == container for e in entries):
                return
            entries.append(
                Unconfirmed(
                    container=container, run_id=run_id, task_id=task_id, added=utc_now_iso()
                )
            )
            self._write(entries)

    def _read(self) -> list[Unconfirmed]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError as exc:
            _LOG.warning("reaper state %s unreadable (%s): treating as empty", self.path, exc)
            return []
        try:
            data = json.loads(raw) if raw.strip() else {}
            items = data.get("containers", []) if isinstance(data, dict) else []
            return [self._entry(i) for i in items if isinstance(i, dict) and i.get("container")]
        except (ValueError, TypeError) as exc:
            _LOG.warning("reaper state %s unreadable (%s): treating as empty", self.path, exc)
            return []

    @staticmethod
    def _entry(item: dict[str, Any]) -> Unconfirmed:
        return Unconfirmed(
            container=str(item.get("container", "")),
            run_id=str(item.get("run_id", "")),
            task_id=str(item.get("task_id", "")),
            attempts=int(item.get("attempts", 0) or 0),
            added=str(item.get("added", "")),
            last_error=str(item.get("last_error", "")),
        )

    def _write(self, entries: list[Unconfirmed]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"containers": [asdict(e) for e in entries]}, indent=1) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    # --- the pass --------------------------------------------------------------------
    def reap_once(self, *, budget_s: float | None = None) -> list[ReapResult]:
        """One bounded pass over the queue, within ``budget_s`` seconds (``None`` =
        unbudgeted; the worker passes ``heartbeat_s / 2``). Returns the entries that
        ended this pass — reaped, or failed at the bound — so the caller can put each on
        its run's trace. Entries still pending stay in the file with ``attempts``
        incremented; entries the budget never reached stay untouched."""
        deadline = None if budget_s is None else time.monotonic() + max(0.0, float(budget_s))
        with self._lock:
            entries = self._read()
            if not entries:
                return []
            keep: list[Unconfirmed] = []
            ended: list[ReapResult] = []
            for i, entry in enumerate(entries):
                if deadline is not None and time.monotonic() >= deadline:
                    left = entries[i:]
                    _LOG.info(
                        "reaper: pass budget (%.1fs) exhausted with %d entr%s waiting",
                        budget_s or 0.0,
                        len(left),
                        "y" if len(left) == 1 else "ies",
                    )
                    keep.extend(left)
                    break
                attempts = entry.attempts + 1
                error = self._reap(entry.container, deadline=deadline)
                if error is None:
                    ended.append(ReapResult(entry, True, attempts))
                    _LOG.info("reaped container %s (run %s)", entry.container, entry.run_id[:8])
                    continue
                if attempts >= self.max_attempts:
                    detail = (
                        f"{error}; gave up after {attempts} attempt(s) — "
                        f"`{by_hand(entry.container)}` reaps it by hand"
                    )
                    ended.append(ReapResult(entry, False, attempts, detail))
                    _LOG.error("container %s not reaped: %s", entry.container, detail)
                    continue
                keep.append(replace(entry, attempts=attempts, last_error=error))
            if keep != entries:
                self._write(keep)
            return ended

    def _reap(self, container: str, *, deadline: float | None = None) -> str | None:
        """``None`` when the daemon reports the container gone or not running (after a
        ``docker rm -f`` — always issued, so a stopped container is removed too); else
        why not, in one line. Every docker call is capped to the time left before
        ``deadline`` (a monotonic instant; ``None`` = uncapped), and a step the budget
        does not reach is reported as :data:`BUDGET_EXHAUSTED` rather than attempted."""
        left = _left(deadline, INSPECT_TIMEOUT_S)
        if left is None:
            return f"container state unknown ({BUDGET_EXHAUSTED})"
        before = container_stopped(self.docker, container, timeout_s=left)
        left = _left(deadline, RM_TIMEOUT_S)
        if left is None:
            state = "not running" if before is True else "state unknown"
            return f"container {state}; docker rm -f not attempted ({BUDGET_EXHAUSTED})"
        rm_error = self._rm(container, timeout_s=left)
        if before is True and rm_error is None:
            return None
        left = _left(deadline, INSPECT_TIMEOUT_S)
        if left is None:
            return f"container state unknown ({BUDGET_EXHAUSTED})" + (
                f"; {rm_error}" if rm_error else ""
            )
        after = container_stopped(self.docker, container, timeout_s=left)
        if after is True:
            return None
        state = "still running" if after is False else "state unknown (daemon not answering)"
        return f"container {state}" + (f"; {rm_error}" if rm_error else "")

    def _rm(self, container: str, *, timeout_s: float = RM_TIMEOUT_S) -> str | None:
        try:
            r = self._runner(
                [self.docker, "rm", "-f", container],
                capture_output=True,
                check=False,
                timeout=timeout_s,
                text=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return f"docker rm -f failed: {type(exc).__name__}"
        if r.returncode == 0 or "no such" in (r.stderr or "").lower():
            return None
        return f"docker rm -f failed (rc={r.returncode}): {(r.stderr or '').strip()[-200:]}"


def _left(deadline: float | None, cap: float) -> float | None:
    """How long the next docker call may take: ``cap`` when the pass is unbudgeted, else
    the smaller of ``cap`` and the time to ``deadline`` — ``None`` once that is gone."""
    if deadline is None:
        return cap
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    return min(cap, remaining)


__all__ = [
    "BUDGET_EXHAUSTED",
    "MAX_ATTEMPTS",
    "STATE_FILENAME",
    "ContainerReaper",
    "ReapResult",
    "Unconfirmed",
    "by_hand",
]
