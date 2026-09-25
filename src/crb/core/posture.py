"""A posture: everything outside the patch that can change a test's outcome (ADR-0019 §1).

The same commit, the same tests and the same patch can pass on the host and fail in the
sealed sandbox: another toolchain patch release, a read-only tree, no module cache, no
network. So a verdict is only meaningful next to the instrument that produced it, and a
fact measured by one instrument (a task's RED, its baseline, its gold) is only true for
that instrument. :class:`Posture` names the instrument:

* the executor, and — for the sandbox — the image by its **content id**
  (``docker image inspect --format {{.Id}}``), never the tag, which a re-push moves;
* the toolchain's exact version, probed INSIDE the posture (``go version`` in the image,
  not on the host);
* the runner and a hash of its fixed command environment (the worktree's own path
  normalised out, so two worktrees are one posture);
* how the tree is presented (``inplace``, ``readonly``, ``copy``), the network, how the
  dependencies are provided (``sealed``, ``host-env``) and the limits;
* the apparatus version.

:attr:`Posture.posture_id` is ``pst_`` + the first 24 hex digits of a SHA-256 over all of
these except ``image_ref``. :attr:`Posture.posture_class` —
``executor/tree/dependency-mode`` — is what statistics pool on: it survives a monthly
image re-pin, which changes the id and asks for a re-qualification, but not the class.

Navigation
----------
What it is:   The posture identity: the ``Posture`` record, its id and class, the resolver
              that measures one live, and ``PostureMismatch``.
What it does: Resolves the posture a run grades in from the executor's own facts, the
              toolchain version probed through that executor, and the runner's command
              environment; gives it a stable hashed id that follows the image's bytes and a
              class that statistics pool on.
How:          ``executor.posture_facts()`` + ``runner.toolchain_argv()`` run through the
              executor + a SHA-256 of ``runner.command(root, ()).env`` with the root path
              replaced by ``<root>`` → ``Posture`` → canonical JSON → SHA-256.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0019-qualification-is-posture-relative.md,
              docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/core/execution.py (``posture_facts`` — the executor's half),
              src/crb/core/runners/base.py (``toolchain_argv`` and the command environment),
              src/crb/core/qualify.py (a qualification is keyed to a posture id),
              src/crb/core/grade.py (``PostureMismatch`` when spec, context and executor
              disagree), src/crb/server/worker.py (resolves the live posture before a run),
              src/crb/core/version.py (the apparatus version a posture carries)
Tested by:    tests/test_posture.py, tests/test_grade.py, tests/test_worker.py
Touch when:   a fact that can change a test's outcome is found outside this record (add the
              field, prove the id moves with it, and say so in ADR-0019's successor).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from crb.core.execution import Command, Executor, SandboxUnavailable
from crb.core.runners.base import BaseRunner
from crb.core.version import APPARATUS_VERSION

#: The id of the back-filled legacy qualifications (a record, never a gate).
LEGACY_POSTURE_ID = "pst_legacy"

#: Wall clock for the toolchain version probe.
TOOLCHAIN_PROBE_TIMEOUT_S = 120


class PostureMismatch(SandboxUnavailable):
    """The spec, the grade context and the executor name different postures, or the live
    posture drifted from the one a qualification recorded. Nothing is graded and nothing
    is written: the run stops (a :class:`SandboxUnavailable`, so every caller that already
    stops on an unusable sandbox stops on this)."""


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Posture:
    """Where a test ran, as an identity. See the module docstring for each field."""

    executor: str
    image_ref: str = ""
    image_id: str = ""
    toolchain: str = ""
    runner: str = ""
    runner_env: str = ""
    tree: str = ""
    network: str = ""
    deps_mode: str = ""
    limits: str = ""
    apparatus_version: str = APPARATUS_VERSION

    def _hashed(self) -> dict[str, str]:
        d = asdict(self)
        d.pop("image_ref")  # a name for the bytes, never the bytes
        return d

    @property
    def posture_id(self) -> str:
        """``pst_`` + 24 hex digits of SHA-256 over every field but ``image_ref``."""
        return "pst_" + _sha256(_canonical(self._hashed()))[:24]

    @property
    def posture_class(self) -> str:
        """``executor/tree/dependency-mode`` — what statistics pool on."""
        return f"{self.executor}/{self.tree}/{self.deps_mode}"

    def to_dict(self) -> dict[str, Any]:
        """Every field plus the derived ``posture_id`` / ``posture_class`` for readers;
        :meth:`from_dict` drops the derived ones and re-derives them."""
        return {**asdict(self), "posture_id": self.posture_id, "posture_class": self.posture_class}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Posture:
        known = {k: str(d[k]) for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)


def normalised_env_hash(env: Mapping[str, str], root: Path) -> str:
    """SHA-256 of a command environment with the worktree's own path replaced by
    ``<root>`` — the path differs per worktree, the environment's meaning does not."""
    roots = {str(Path(root)), str(Path(root).resolve())}
    norm: dict[str, str] = {}
    for k, v in env.items():
        val = str(v)
        for r in sorted(roots, key=len, reverse=True):
            val = val.replace(r, "<root>")
        norm[str(k)] = val
    return _sha256(_canonical(norm))


def probe_toolchain(
    executor: Executor, runner: BaseRunner, root: Path, *, timeout: int = TOOLCHAIN_PROBE_TIMEOUT_S
) -> str:
    """The toolchain's exact version as the posture sees it (inside the image for docker).
    ``""`` when the runner names no probe; a probe that fails is
    :class:`SandboxUnavailable` — a posture that cannot name its toolchain cannot be
    qualified."""
    argv = runner.toolchain_argv(executor)
    if not argv:
        return ""
    try:
        res = executor.run(Command(tuple(argv), root, timeout=timeout))
    except OSError as exc:
        raise SandboxUnavailable(f"cannot read the toolchain version ({argv[0]}): {exc}") from exc
    text = (res.stdout or "").strip() or (res.stderr or "").strip()
    if not res.ok or not text:
        raise SandboxUnavailable(
            f"cannot read the toolchain version in this posture ({' '.join(argv)} exited "
            f"{res.returncode}): {text[:200]}"
        )
    return text.splitlines()[0].strip()


def resolve_posture(
    executor: Executor,
    runner: BaseRunner,
    *,
    deps_mode: str,
    root: Path,
    timeout: int = TOOLCHAIN_PROBE_TIMEOUT_S,
) -> Posture:
    """Measure the live posture: the executor's facts, the toolchain probed through the
    executor in ``root``, and the runner's command environment hashed with ``root``
    normalised out. Raises :class:`SandboxUnavailable` when the image is absent or the
    toolchain cannot be read."""
    facts = executor.posture_facts()
    toolchain = probe_toolchain(executor, runner, Path(root), timeout=timeout)
    cmd = runner.command(Path(root), (), executor=executor, timeout=max(1, timeout))
    limits = facts.get("limits", "")
    if facts.get("user"):
        limits = f"{limits},user={facts['user']}" if limits else f"user={facts['user']}"
    return Posture(
        executor=facts.get("executor", executor.name),
        image_ref=facts.get("image_ref", ""),
        image_id=facts.get("image_id", ""),
        toolchain=toolchain,
        runner=runner.name,
        runner_env=normalised_env_hash(cmd.env, Path(root)),
        tree=facts.get("tree", ""),
        network=facts.get("network", ""),
        deps_mode=deps_mode,
        limits=limits,
    )


__all__ = [
    "LEGACY_POSTURE_ID",
    "Posture",
    "PostureMismatch",
    "normalised_env_hash",
    "probe_toolchain",
    "resolve_posture",
]
