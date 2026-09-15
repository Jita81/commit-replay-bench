"""``crb tasks`` — audit and label the class axes of mined tasks.

* ``crb tasks classes <repo>`` — one line per task: id · subject · path class ·
  intent class · confidence · resolved class · source · labeller. A reviewer can
  audit a sample in minutes (the review's "human-audited sample per repo").
* ``crb tasks label <repo> <task_id> --class X --by <name>`` — a **human** label:
  highest precedence, confidence 1.0, never overwritten by a model run.
* ``crb tasks label-llm <repo> --builder … --model …`` — label every task lacking
  an intent label through :func:`crb.builders.labeller.make_labeller` (the same
  path the worker's ``label`` run kind takes), without a queue or a server.

Where the tasks live: the file workdir (``<workdir>/tasks/<repo>.jsonl``, what
``crb mine`` writes) by default; the database (what the worker writes) when
``--database-url`` is given or ``CRB_DATABASE_URL`` is set. ``--file`` forces the
workdir. Either way a label rewrites the task record in place — the ledger is
untouched (a class is a property of the task, not of a verdict).

Navigation
----------
What it is:   ``crb tasks classes | label | label-llm`` — audit and label the change-class
              axes of mined tasks, over the file workdir or the database.
What it does: Prints the per-task table (path class · intent · confidence · resolved ·
              source · labeller) a reviewer audits; records a HUMAN label (highest
              precedence, never overwritten by a model); labels unlabelled tasks through
              the same labeller the worker's ``label`` run uses. A label rewrites the task
              record only — the ledger is untouched.
How:          ``store_of`` picks ``FileStore`` (atomic rewrite of the JSONL) or ``DbStore``
              (the ``tasks`` table via the worker's merge); ``commit_evidence`` +
              ``human_label`` / ``make_labeller`` from the core and builders.
Layer:        cli — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/core/classify.py (``IntentLabel``, ``human_label``, the resolution
              rule), src/crb/core/spec.py (``TaskSpec`` and ``CLASS_VOCABULARY``),
              src/crb/builders/labeller.py (``make_labeller`` for ``label-llm``),
              src/crb/store/models.py (``Task`` for ``DbStore``), src/crb/server/worker.py
              (the ``label`` run kind — the same path with a queue),
              docs/ARCHITECTURE.md#75-change-class-two-axes-one-resolved-value
Tested by:    tests/test_cli_tasks.py
Touch when:   never for a new repository; when the class vocabulary changes (that is the
              instrument — src/crb/core/taxonomy.py plus an ADR and apparatus bump);
              when a task store gains a field the table should show.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from crb.cli.commands import (
    EXIT_OK,
    CliError,
    Workdir,
    add_common,
    parse_kv,
    print_json,
    print_lines,
    table,
    workdir_of,
)
from crb.core.classify import (
    CLASS_SOURCES,
    IntentLabel,
    commit_evidence,
    human_label,
    label_summary,
)
from crb.core.git import GitRepo
from crb.core.spec import CLASS_VOCABULARY, TaskSpec

DB_URL_ENV = "CRB_DATABASE_URL"
_SERVER_HINT = "the store layer is not installed — `pip install 'commit-replay-bench[server]'`"


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------


class TaskStore(Protocol):
    """Where tasks live for this invocation: the workdir file or the database."""

    def describe(self) -> str: ...

    def load(self, repo: str) -> list[TaskSpec]: ...

    def save(self, task: TaskSpec) -> None: ...

    def clone_path(self, repo: str) -> Path | None: ...


@dataclass(frozen=True)
class FileStore:
    """``<workdir>/tasks/<repo>.jsonl`` — rewritten atomically on ``save``."""

    wd: Workdir

    def describe(self) -> str:
        return str(self.wd.tasks_dir)

    def load(self, repo: str) -> list[TaskSpec]:
        return self.wd.load_tasks(repo)

    def save(self, task: TaskSpec) -> None:
        """Replace the task's line by rewriting the whole file to a temp path and
        renaming it over — a crash mid-write leaves the original intact."""
        f = self.wd.task_file(task.repo)
        tasks = self.wd.load_tasks(task.repo)
        if task.task_id not in {t.task_id for t in tasks}:
            raise CliError(f"task {task.short_id} is not on file for repo {task.repo!r} ({f})")
        tmp = f.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for t in tasks:
                out = task if t.task_id == task.task_id else t
                fh.write(json.dumps(out.to_dict(), sort_keys=True, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, f)

    def clone_path(self, repo: str) -> Path | None:
        """The registered clone path (``None`` when the repo is unknown or config-only)."""
        try:
            _, path = self.wd.load_repo(repo)
        except CliError:
            return None
        return path


class DbStore:
    """The ``tasks`` table, through the same merge the worker uses."""

    def __init__(self, url: str) -> None:
        try:  # lazy: the store layer is an optional extra (as in service.py)
            from crb.store.db import make_engine, make_session_factory  # noqa: PLC0415
            from crb.store.models import Repo, Task  # noqa: PLC0415
        except ImportError as e:
            raise CliError(f"{_SERVER_HINT} ({e})") from e
        self._Task = Task
        self._Repo = Repo
        self._url = url
        self._factory = make_session_factory(make_engine(url))

    def describe(self) -> str:
        """The URL with any credentials removed."""
        return self._url.split("@")[-1] if "@" in self._url else self._url

    def load(self, repo: str) -> list[TaskSpec]:
        from sqlalchemy import select  # noqa: PLC0415 — optional extra, see __init__

        with self._factory() as s:
            rows = (
                s.execute(
                    select(self._Task)
                    .where(self._Task.repo == repo)
                    .order_by(self._Task.authored, self._Task.task_id)
                )
                .scalars()
                .all()
            )
        return [TaskSpec.from_dict(r.spec_json) for r in rows]

    def save(self, task: TaskSpec) -> None:
        """Merge the task row (columns + ``spec_json``) exactly as the worker's upsert does."""
        with self._factory() as s:
            if s.get(self._Task, (task.repo, task.task_id)) is None:
                raise CliError(f"task {task.short_id} is not in the database for {task.repo!r}")
            s.merge(
                self._Task(
                    repo=task.repo,
                    task_id=task.task_id,
                    pool=task.pool,
                    size=task.size,
                    capability_class=task.capability_class,
                    language=task.language,
                    authored=task.authored,
                    subject=task.subject,
                    red_checked=task.red_checked,
                    gold_clean=task.gold_clean,
                    spec_json=task.to_dict(),
                )
            )
            s.commit()

    def clone_path(self, repo: str) -> Path | None:
        with self._factory() as s:
            row = s.get(self._Repo, repo)
        if row is None:
            return None
        raw = row.clone_path or str((row.config_json or {}).get("path") or "")
        return Path(raw) if raw else None


def store_of(args: argparse.Namespace) -> TaskStore:
    """``--database-url`` / ``$CRB_DATABASE_URL`` → the database; else the workdir.
    ``--file`` always means the workdir."""
    url = (
        None if getattr(args, "file", False) else (args.database_url or os.environ.get(DB_URL_ENV))
    )
    if url:
        return DbStore(url)
    return FileStore(workdir_of(args))


def _find(tasks: Sequence[TaskSpec], task_id: str) -> TaskSpec:
    """Resolve a sha or a unique prefix (≥ 7 chars) among ``tasks``."""
    if len(task_id) < 7:
        raise CliError("task id must be a git sha or a prefix of at least 7 characters")
    matches = [t for t in tasks if t.task_id.startswith(task_id)]
    if not matches:
        raise CliError(f"no task {task_id!r}")
    if len(matches) > 1:
        raise CliError(f"task prefix {task_id!r} is ambiguous ({len(matches)} matches)")
    return matches[0]


def _git(store: TaskStore, repo: str) -> GitRepo | None:
    """The repo's clone as a ``GitRepo`` when it is present on this host (labelling
    needs the commit message and paths); ``None`` otherwise."""
    path = store.clone_path(repo)
    if path is None or not path.is_dir():
        return None
    git = GitRepo(path)
    return git if git.is_repo() else None


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``crb tasks classes | label | label-llm``."""
    p = sub.add_parser("tasks", help="audit and label the change-class axes of mined tasks")
    ts = p.add_subparsers(dest="tasks_command", metavar="<subcommand>")

    classes = ts.add_parser("classes", help="table of path / intent / resolved class per task")
    classes.add_argument("name", help="repo")
    classes.add_argument("--source", choices=CLASS_SOURCES, default=None, help="only this source")
    classes.add_argument("--class", dest="cls", default=None, help="only this resolved class")
    classes.add_argument("--unlabelled", action="store_true", help="only tasks without a label")
    _add_store(classes)
    classes.set_defaults(func=cmd_classes)

    label = ts.add_parser("label", help="record a HUMAN class label for one task")
    label.add_argument("name", help="repo")
    label.add_argument("task_id", help="task sha (or a unique prefix ≥7)")
    label.add_argument(
        "--class", dest="cls", required=True, help=f"one of {', '.join(CLASS_VOCABULARY)}"
    )
    label.add_argument("--by", required=True, help="who is labelling (recorded as human:<by>)")
    label.add_argument("--rationale", default="", help="one line: why")
    _add_store(label)
    label.set_defaults(func=cmd_label)

    llm = ts.add_parser("label-llm", help="label tasks lacking an intent label with a model")
    llm.add_argument("name", help="repo")
    llm.add_argument("--builder", required=True, help="claude_code | openai_agent | editblock")
    llm.add_argument("--model", default="", help="model id (claude_code: CRB_CLAUDE_CODE_MODEL)")
    llm.add_argument("--provider", default="", help="provider label for the labeller name")
    llm.add_argument("--limit", type=int, default=0, help="label at most N tasks (0 = all)")
    llm.add_argument("--relabel", action="store_true", help="re-label model-labelled tasks too")
    llm.add_argument(
        "--config",
        action="append",
        metavar="KEY=VALUE",
        help="builder_config entries (e.g. auth=cli, effort=low)",
    )
    _add_store(llm)
    llm.set_defaults(func=cmd_label_llm)


def _add_store(parser: argparse.ArgumentParser) -> None:
    """``--database-url`` / ``--file`` plus the common flags."""
    parser.add_argument(
        "--database-url", default=None, help=f"use the database (default: ${DB_URL_ENV})"
    )
    parser.add_argument("--file", action="store_true", help="use the workdir even if a DB is set")
    add_common(parser)


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def _row(t: TaskSpec) -> dict[str, Any]:
    """One task's class axes as the ``classes`` table shows them."""
    i = t.intent
    return {
        "task_id": t.task_id,
        "subject": t.subject,
        "path_class": t.path_class,
        "intent_class": i.intent_class if i else "",
        "confidence": i.confidence if i else None,
        "capability_class": t.capability_class,
        "class_source": t.class_source,
        "labeller": i.labeller if i else "",
        "rationale": i.rationale if i else "",
        "evidence_hash": i.evidence_hash if i else "",
        "gold_clean": t.gold_clean,
    }


def cmd_classes(args: argparse.Namespace) -> int:
    """The audit table: path class, intent, confidence, resolved class, source, labeller."""
    store = store_of(args)
    tasks = store.load(args.name)
    if not tasks:
        raise CliError(f"no tasks for repo {args.name!r} in {store.describe()}")
    rows = [_row(t) for t in tasks]
    if args.source:
        rows = [r for r in rows if r["class_source"] == args.source]
    if args.cls:
        rows = [r for r in rows if r["capability_class"] == args.cls]
    if args.unlabelled:
        rows = [r for r in rows if not r["labeller"]]
    summary = label_summary([t.intent for t in tasks])
    sources: dict[str, int] = {}
    for t in tasks:
        sources[t.class_source] = sources.get(t.class_source, 0) + 1
    if args.json:
        print_json(
            {
                "repo": args.name,
                "store": store.describe(),
                "n": len(tasks),
                "shown": len(rows),
                "sources": dict(sorted(sources.items())),
                "labels": summary,
                "tasks": rows,
            }
        )
        return EXIT_OK
    lines = list(
        table(
            ("task", "subject", "path", "intent", "conf", "resolved", "source", "labeller"),
            [
                (
                    r["task_id"][:10],
                    str(r["subject"])[:48],
                    r["path_class"],
                    r["intent_class"] or "-",
                    f"{r['confidence']:.2f}" if r["confidence"] is not None else "-",
                    r["capability_class"],
                    r["class_source"],
                    r["labeller"] or "-",
                )
                for r in rows
            ],
        )
    )
    lines.append("")
    lines.append(
        f"{args.name}: {len(tasks)} task(s), shown {len(rows)}; sources "
        + ", ".join(f"{k}={v}" for k, v in sorted(sources.items()))
        + f"; labelled {summary['labelled']}/{summary['n']}"
        + (
            f", mean confidence {summary['mean_confidence']:.2f} (n={summary['mean_confidence_n']})"
            if summary["mean_confidence"] is not None
            else ""
        )
        + f", unclassified {summary['unclassified']}, human {summary['human']}"
    )
    print_lines(lines)
    return EXIT_OK


def cmd_label(args: argparse.Namespace) -> int:
    """Record a human label (confidence 1.0, ``human:<by>``) and rewrite the task record."""
    store = store_of(args)
    tasks = store.load(args.name)
    task = _find(tasks, args.task_id)
    git = _git(store, args.name)
    digest = ""
    if git is not None:
        try:
            digest = commit_evidence(git, task.task_id, path_class=task.path_class).digest()
        except Exception:  # a label without a hash is honest; a fabricated hash is not
            digest = ""
    try:
        label = human_label(args.cls, by=args.by, rationale=args.rationale, evidence_hash=digest)
    except ValueError as e:
        raise CliError(str(e)) from e
    before = task.capability_class
    new = task.with_(intent=label)
    store.save(new)
    out = {
        "repo": args.name,
        "task_id": task.task_id,
        "before": before,
        "after": new.capability_class,
        "class_source": new.class_source,
        "label": label.to_dict(),
        "evidence_hash_known": bool(digest),
    }
    if args.json:
        print_json(out)
    else:
        print_lines(
            [
                f"{task.short_id} {task.subject[:60]}",
                f"  {before} -> {new.capability_class} ({new.class_source}, {label.labeller})"
                + ("" if digest else "  [no clone: evidence hash not recorded]"),
            ]
        )
    return EXIT_OK


def cmd_label_llm(args: argparse.Namespace) -> int:
    """Label tasks lacking an intent label with a model; a human label is never touched."""
    from crb.builders.labeller import make_labeller  # noqa: PLC0415 — SDK-bearing layer

    store = store_of(args)
    tasks = store.load(args.name)
    if not tasks:
        raise CliError(f"no tasks for repo {args.name!r} in {store.describe()}")
    git = _git(store, args.name)
    if git is None:
        raise CliError(
            f"repo {args.name!r} has no usable clone (the labeller reads commit metadata)"
        )
    try:
        labeller = make_labeller(
            args.builder,
            model=args.model,
            provider=args.provider,
            builder_config=parse_kv(args.config),
        )
    except ValueError as e:
        raise CliError(str(e)) from e
    todo = [t for t in tasks if t.intent is None or (args.relabel and not t.intent.is_human)]
    if args.limit > 0:
        todo = todo[: args.limit]
    labels: list[IntentLabel] = []
    changed = 0
    lines: list[str] = []
    for t in todo:
        ev = commit_evidence(git, t.task_id, path_class=t.path_class)
        label = labeller.label(
            subject=ev.subject,
            message=ev.message,
            diff_stats=ev.diff_stats,
            changed_paths=ev.changed_paths,
            path_class=ev.path_class,
        )
        new = t.with_(intent=label)
        store.save(new)
        labels.append(label)
        changed += new.capability_class != t.capability_class
        lines.append(
            f"  {t.short_id} {t.path_class} -> {new.capability_class} "
            f"[{label.intent_class} {label.confidence:.2f}] {label.rationale[:70]}"
        )
    out = {
        "repo": args.name,
        "store": store.describe(),
        "labeller": labeller.name,
        "candidates": len(todo),
        "labelled": len(labels),
        "changed": changed,
        "labels": label_summary(labels),
        "usage": labeller.usage.to_dict(),
    }
    if args.json:
        print_json(out)
    else:
        head = f"{args.name}: labelled {len(labels)}/{len(todo)} with {labeller.name}; "
        print_lines(
            [
                head + f"{changed} changed",
                *lines,
                f"  usage: {json.dumps(out['usage'], sort_keys=True)}",
            ]
        )
    return EXIT_OK


__all__ = ["DbStore", "FileStore", "TaskStore", "register", "store_of"]
