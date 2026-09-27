"""Shared plumbing for the ``crb`` subcommands: the workdir layout, output helpers,
exit codes, the executor factory and the dependency provider. Every command module
imports from here, from :mod:`crb.core` and (for the provider) :mod:`crb.provision`.

Workdir layout (``./.crb`` by default; ``CRB_HOME`` or ``--workdir`` override)::

    <workdir>/
      repos/<name>.json        RepoConfig.to_dict() + {"path": <clone>}
      tasks/<name>.jsonl       one TaskSpec per line (append-only, idempotent by task_id)
      qualifications/<name>.jsonl  each task's qualification per posture (append-only)
      ledger.jsonl             the hash-chained GradeRow ledger
      evidence/<pack_hash>.json  evidence packs (measured and imported)
      aggregates.jsonl         imported AggregateRows (reference only, never graded)
      scratch/                 disposable mining worktrees

Navigation
----------
What it is:   The shared plumbing of the ``crb`` subcommands — the file workdir, the executor
              factory, output helpers, the exit codes and ``CliError``.
What it does: ``Workdir`` owns the on-disk layout the CLI uses without a server (repo
              configs, task files, the JSONL ledger, evidence packs, scratch) and its
              read / append rules (tasks append-only and idempotent by id, packs written
              once); ``build_executor`` fails closed when docker is asked for without an
              image; ``parse_kv`` decodes ``KEY=VALUE`` with JSON values.
How:          Pure helpers over ``pathlib`` and ``json``; nothing here computes a verdict.
Layer:        cli — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/core/spec.py (``RepoConfig`` / ``TaskSpec`` — what the files hold),
              src/crb/core/execution.py (``LocalExecutor``, ``DockerSettings``,
              ``make_executor``), src/crb/provision/__init__.py (``make_deps_provider`` —
              the same provider the worker uses), src/crb/cli/commands/repo.py (``save_repo`` /
              ``require_clone`` callers), src/crb/cli/commands/mine.py (``append_tasks``),
              src/crb/cli/commands/grade.py (``write_pack``, ``ledger_path``),
              src/crb/cli/main.py (maps ``CliError`` to exit 2)
Tested by:    tests/test_cli.py, tests/test_cli_repo_setup.py, tests/test_cli_tasks.py
Touch when:   never for a new repository (``crb repo add`` writes the files); when the
              workdir layout gains a file or directory (update the docstring table,
              ``describe`` and docs/OPERATOR.md together).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from crb.core.deps import DepsProvider
from crb.core.execution import (
    TREE_COPY,
    DockerExecutor,
    DockerSettings,
    Executor,
    LocalExecutor,
    make_executor,
)
from crb.core.spec import RepoConfig, TaskSpec
from crb.provision import make_deps_provider
from crb.provision.config import ProvisionConfig

EXIT_OK = 0
EXIT_NEGATIVE = 1
EXIT_ERROR = 2

DEFAULT_WORKDIR = ".crb"
WORKDIR_ENV = "CRB_HOME"
EXECUTOR_KINDS: tuple[str, ...] = ("local", "docker")
DEFAULT_EXECUTOR = "local"


class CliError(Exception):
    """A usage or harness error. Reported on stderr; the process exits ``2``."""


# ---------------------------------------------------------------------------
# Workdir
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Workdir:
    """The CLI's state directory (the layout in the module docstring) and the reads and
    writes the verbs are allowed to make on it."""

    root: Path

    @classmethod
    def resolve(cls, explicit: str | os.PathLike[str] | None = None) -> Workdir:
        """``--workdir`` > ``$CRB_HOME`` > ``./.crb``. Never creates anything."""
        chosen = explicit or os.environ.get(WORKDIR_ENV) or DEFAULT_WORKDIR
        return cls(Path(chosen).expanduser().resolve())

    # --- paths -----------------------------------------------------------------
    @property
    def repos_dir(self) -> Path:
        return self.root / "repos"

    @property
    def tasks_dir(self) -> Path:
        return self.root / "tasks"

    @property
    def evidence_dir(self) -> Path:
        return self.root / "evidence"

    @property
    def scratch_dir(self) -> Path:
        return self.root / "scratch"

    @property
    def ledger_path(self) -> Path:
        return self.root / "ledger.jsonl"

    @property
    def aggregates_path(self) -> Path:
        return self.root / "aggregates.jsonl"

    def repo_file(self, name: str) -> Path:
        """``repos/<name>.json``."""
        return self.repos_dir / f"{name}.json"

    def task_file(self, name: str) -> Path:
        """``tasks/<name>.jsonl``."""
        return self.tasks_dir / f"{name}.jsonl"

    def qualification_file(self, name: str) -> Path:
        """``qualifications/<name>.jsonl`` — each task's qualification per posture
        (ADR-0019), append-only; the latest row for a task and posture is in force."""
        return self.root / "qualifications" / f"{name}.jsonl"

    def describe(self) -> dict[str, Any]:
        """The layout as ``crb config show`` prints it."""
        return {
            "workdir": str(self.root),
            "exists": self.root.is_dir(),
            "repos_dir": str(self.repos_dir),
            "tasks_dir": str(self.tasks_dir),
            "evidence_dir": str(self.evidence_dir),
            "scratch_dir": str(self.scratch_dir),
            "ledger": str(self.ledger_path),
            "aggregates": str(self.aggregates_path),
        }

    # --- repos -----------------------------------------------------------------
    def save_repo(self, config: RepoConfig, path: Path | None, *, force: bool = False) -> Path:
        """Persist a config (+ its clone path). Refuses to overwrite unless ``force``."""
        f = self.repo_file(config.name)
        if f.exists() and not force:
            raise CliError(f"repo {config.name!r} already exists at {f} (use --force to replace)")
        self.repos_dir.mkdir(parents=True, exist_ok=True)
        payload = config.to_dict()
        payload["path"] = str(path) if path else ""
        f.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return f

    def load_repo(self, name: str) -> tuple[RepoConfig, Path | None]:
        """``(config, clone_path)``; ``clone_path`` is ``None`` for config-only repos."""
        f = self.repo_file(name)
        if not f.is_file():
            raise CliError(f"unknown repo {name!r} (no {f}); run `crb repo add` first")
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise CliError(f"{f}: not valid JSON: {e}") from e
        config = RepoConfig.from_dict(name, d)
        raw_path = str(d.get("path") or "")
        return config, (Path(raw_path) if raw_path else None)

    def require_clone(self, name: str) -> tuple[RepoConfig, Path]:
        """``load_repo`` for a verb that needs the clone on disk (mine, prep, grade, probe)."""
        config, path = self.load_repo(name)
        if path is None:
            raise CliError(
                f"repo {name!r} has no clone path; re-add it with `crb repo add {name} --path <clone> …`"
            )
        if not path.is_dir():
            raise CliError(f"repo {name!r}: clone path {path} is not a directory")
        return config, path

    def repo_names(self) -> list[str]:
        """Registered repo names, sorted."""
        if not self.repos_dir.is_dir():
            return []
        return sorted(p.stem for p in self.repos_dir.glob("*.json"))

    # --- tasks -----------------------------------------------------------------
    def load_tasks(self, name: str) -> list[TaskSpec]:
        """Every task on file for ``name`` (empty when never mined)."""
        f = self.task_file(name)
        if not f.is_file():
            return []
        out: list[TaskSpec] = []
        with f.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    out.append(TaskSpec.from_dict(json.loads(line)))
        return out

    def known_task_ids(self, name: str) -> frozenset[str]:
        """The ids ``crb mine`` must not re-mine."""
        return frozenset(t.task_id for t in self.load_tasks(name))

    def append_tasks(self, name: str, tasks: Iterable[TaskSpec]) -> int:
        """Append tasks not already on file (idempotent by ``task_id``). Returns the count."""
        known = set(self.known_task_ids(name))
        f = self.task_file(name)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        n = 0
        with f.open("a", encoding="utf-8") as fh:
            for t in tasks:
                if t.task_id in known:
                    continue
                fh.write(json.dumps(t.to_dict(), sort_keys=True, ensure_ascii=False) + "\n")
                known.add(t.task_id)
                n += 1
            fh.flush()
            os.fsync(fh.fileno())  # a proved task must survive a crash right after it is found
        return n

    def find_task(self, name: str, task_id: str) -> TaskSpec:
        """Resolve a full sha or a unique prefix (≥7 chars) to the task on file."""
        if len(task_id) < 7:
            raise CliError("task id must be a git sha or a prefix of at least 7 characters")
        matches = [t for t in self.load_tasks(name) if t.task_id.startswith(task_id)]
        if not matches:
            raise CliError(f"no task {task_id!r} for repo {name!r} in {self.task_file(name)}")
        if len(matches) > 1:
            raise CliError(f"task prefix {task_id!r} is ambiguous ({len(matches)} matches)")
        return matches[0]

    # --- evidence --------------------------------------------------------------
    def write_pack(self, pack_hash: str, pack: Mapping[str, Any]) -> Path:
        """Write a pack under its hash. Idempotent: an existing pack is left untouched."""
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        p = self.evidence_dir / f"{pack_hash}.json"
        if not p.exists():
            p.write_text(
                json.dumps(pack, sort_keys=True, indent=1, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        return p


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------


def build_executor(kind: str, config: RepoConfig) -> Executor:
    """``local`` or ``docker``. Docker needs ``sandbox_image`` on the config and fails
    closed (:class:`~crb.core.execution.SandboxUnavailable`) otherwise."""
    k = (kind or DEFAULT_EXECUTOR).strip().lower()
    if k == "local":
        return LocalExecutor()
    if k == "docker":
        # ADR-0019 §7: the repository may choose how the tree is presented; the default is
        # the throwaway copy, as the worker's (CRB_SANDBOX__TREE / __WORK_SIZE)
        tree = (config.sandbox_tree or os.environ.get("CRB_SANDBOX__TREE") or TREE_COPY).strip()
        work_size = (os.environ.get("CRB_SANDBOX__WORK_SIZE") or "1g").strip()
        docker = (
            DockerSettings(image=config.sandbox_image, tree=tree.lower(), work_size=work_size)
            if config.sandbox_image
            else None
        )
        return make_executor("docker", docker=docker)
    raise CliError(f"unknown executor {kind!r}; expected one of {EXECUTOR_KINDS}")


def deps_provider(executor: Executor) -> DepsProvider:
    """The dependency provider the worker would use for ``executor`` (ADR-0019), read from
    ``CRB_PROVISION__*``: off → the host's environment locally and ``PROVISION_DISABLED``
    for a repository with dependencies in the sandbox; on → fetched, sealed and bound per
    task. A production refusal (a public registry, an unpinned fetch image, a store the
    daemon cannot see) raises before anything is qualified."""
    probe_image = executor.settings.image if isinstance(executor, DockerExecutor) else ""
    return make_deps_provider(
        ProvisionConfig.from_env(), executor_kind=executor.name, probe_image=probe_image
    )


def executor_defaults() -> dict[str, Any]:
    """The executor kinds and the docker sandbox's default limits, for ``crb config``."""
    dummy = DockerSettings(image="<sandbox_image>")
    return {
        "default": DEFAULT_EXECUTOR,
        "kinds": list(EXECUTOR_KINDS),
        "docker": {
            "memory": dummy.memory,
            "cpus": dummy.cpus,
            "pids_limit": dummy.pids_limit,
            "user": dummy.user,
            "network": "none",
            "read_only": True,
        },
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def print_json(obj: Any, stream: IO[str] | None = None) -> None:
    """Pretty, sorted-keys JSON to stdout (``--json`` output)."""
    out = stream or sys.stdout
    out.write(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    out.flush()


def print_lines(lines: Iterable[str], stream: IO[str] | None = None) -> None:
    """Plain lines to stdout (the human output)."""
    out = stream or sys.stdout
    for line in lines:
        out.write(line + "\n")
    out.flush()


def event_printer(stream: IO[str] | None = None) -> Any:
    """An ``on_event`` callback that streams ``{"event": …, …}`` JSON lines."""
    out = stream or sys.stderr

    def on_event(action: str, payload: Mapping[str, Any]) -> None:
        out.write(json.dumps({"event": action, **payload}, sort_keys=True, default=str) + "\n")
        out.flush()

    return on_event


def table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> Iterator[str]:
    """A plain fixed-width text table (no colour, no third-party deps)."""
    cells = [[str(h) for h in headers]] + [[str(c) for c in r] for r in rows]
    widths = [max(len(row[i]) for row in cells) for i in range(len(headers))]
    yield "  ".join(cells[0][i].ljust(widths[i]) for i in range(len(headers))).rstrip()
    yield "  ".join("-" * w for w in widths)
    for r in cells[1:]:
        yield "  ".join(r[i].ljust(widths[i]) for i in range(len(headers))).rstrip()


# ---------------------------------------------------------------------------
# argparse helpers
# ---------------------------------------------------------------------------


def add_common(parser: argparse.ArgumentParser) -> None:
    """``--workdir`` and ``--json`` — on every verb."""
    parser.add_argument(
        "--workdir",
        default=None,
        help=f"state directory (default: ${WORKDIR_ENV} or ./{DEFAULT_WORKDIR})",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable JSON output")


def add_executor(parser: argparse.ArgumentParser) -> None:
    """``--executor`` and ``--timeout`` — on every verb that runs repository tests."""
    parser.add_argument(
        "--executor",
        choices=EXECUTOR_KINDS,
        default=DEFAULT_EXECUTOR,
        help="where repository tests run (docker needs sandbox_image; fails closed)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=0,
        help="per test-run wall clock in seconds (0 = runner default)",
    )


def workdir_of(args: argparse.Namespace) -> Workdir:
    """The ``Workdir`` a parsed command line resolves to."""
    return Workdir.resolve(getattr(args, "workdir", None))


def parse_kv(items: Sequence[str] | None) -> dict[str, Any]:
    """``KEY=VALUE`` pairs. A value that is valid JSON (a list, object, number or
    boolean — e.g. ``pip='["click","pytest"]'``) is decoded; anything else stays a
    string, so ``pythonpath_suffix=/src`` is untouched."""
    out: dict[str, Any] = {}
    for item in items or ():
        if "=" not in item:
            raise CliError(f"expected KEY=VALUE, got {item!r}")
        k, v = item.split("=", 1)
        value: Any = v
        stripped = v.strip()
        if (
            stripped[:1] in "[{"
            or stripped in {"true", "false", "null"}
            or _looks_numeric(stripped)
        ):
            try:
                value = json.loads(stripped)
            except ValueError:
                value = v
        out[k.strip()] = value
    return out


def _looks_numeric(s: str) -> bool:
    """Whether ``s`` parses as a float (so ``parse_kv`` decodes it as JSON)."""
    try:
        float(s)
    except ValueError:
        return False
    return True


__all__ = [
    "DEFAULT_EXECUTOR",
    "DEFAULT_WORKDIR",
    "EXECUTOR_KINDS",
    "EXIT_ERROR",
    "EXIT_NEGATIVE",
    "EXIT_OK",
    "WORKDIR_ENV",
    "CliError",
    "Workdir",
    "add_common",
    "add_executor",
    "build_executor",
    "event_printer",
    "executor_defaults",
    "parse_kv",
    "print_json",
    "print_lines",
    "table",
    "workdir_of",
]
