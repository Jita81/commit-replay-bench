#!/usr/bin/env python3
"""Branch protection requires exactly the pull-request workflows' jobs — compared, not assumed.

A job blocks a merge only while its check name is on the branch's required-status-checks
list, and that list is a repository setting, not a file. A job renamed in a workflow, or
added to one, therefore stops gating without any file saying so; an administrator who drops
a check from the setting does the same. This script reads the setting and compares it, both
ways, with the jobs of every workflow under ``.github/workflows`` whose top-level ``on:``
names ``pull_request`` — found by reading each file, never from a list kept by hand, so a
new workflow's job (``commit-subjects.yml``'s, say) is held to the setting the day it lands.

    python scripts/check_branch_protection.py --repo Jita81/commit-replay-bench
    python scripts/check_branch_protection.py --from-json reading.json   # offline
    python scripts/check_branch_protection.py --workflow .github/workflows/ci.yml  # one file

It fails on: a required check that no job of a pull-request workflow reports (every pull
request waits on it for ever); such a job that no required check names (it can fail and the
change still merges); a required check that is a part of an aggregator (its name changes
whenever the work is split differently); a setting that is not strict (a branch may merge
while behind ``main``); and a job name of 100 characters or more (GitHub cuts a check name
at 100, so no run can satisfy it). An aggregator is a job that ``needs`` others and runs
``if: always()`` — the ``test`` job over the suite's shards and ``walkthrough`` over the
story and the screens shards: it is required, and the parts it stands for are not. A saved
reading may list a job added before the administrator could require it, under
``awaiting_protection`` with the step that remains and the open gap in docs/dod that names
the job; the live setting never does (DL-101, P-269).

Navigation
----------
What it is:   The comparator between branch protection's required checks and the jobs of
              every pull-request workflow (stdlib only; ``gh`` reads the setting).
What it does: Finds the workflows under .github/workflows that run on ``pull_request`` (or
              takes them from ``--workflow``), expands their jobs into the check names GitHub
              reports (a matrix job once per combination), sets aside the parts an
              aggregator stands for, reads ``required_status_checks`` through ``gh api`` (or
              from a saved JSON reading, which may name jobs awaiting the administrator, each
              under an open gap in docs/dod that names it), and prints every difference,
              naming the workflow file; exits non-zero on any.
How:          Line-scan each workflow's top-level ``on:`` (a scalar, a ``[list]`` or a block
              of events; any other shape fails closed) and its ``jobs:`` block (job key,
              ``name:``, list matrices, ``needs:``, the job-level ``if:``) → expand
              ``${{ matrix.<key> }}`` → the aggregators' parts → set comparison with the
              reading; the open gaps come from scripts/dod_check.py's own parser.
Layer:        deploy — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   .github/workflows/ci.yml and .github/workflows/commit-subjects.yml (the
              pull-request workflows whose jobs it expands), .github/workflows/
              branch-protection.yml (the scheduled run with a token that may read the
              setting), tests/fixtures/branch_protection_main.json (the last saved reading),
              data/branch-protection-2026-10-07/ (the reading README cites),
              docs/DEPLOYMENT.md §3.4 (the administrator's guide to the setting),
              docs/dod/product.md (product.evidence.6 and gap G-930), scripts/dod_check.py
              (``open_gaps`` reads the record through its parser)
Tested by:    tests/test_check_branch_protection.py
Touch when:   never for a new repository (it compares this repository's own workflows with its
              own branch setting); a pull-request workflow gains a shape this scan does not
              read (an ``include:`` matrix, an ``on:`` written as a ``{…}`` mapping, a
              job-level ``if:`` or a ``paths:`` filter that keeps a job off some pull
              requests) — teach ``triggers`` or ``parse_jobs`` and add the fixture case in the
              same change.
"""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
#: Every workflow here whose top-level ``on:`` names :data:`PR_EVENT` has its jobs required.
WORKFLOWS = ROOT / ".github" / "workflows"
#: The event whose runs a merge waits on: a workflow that does not run on it gates nothing.
PR_EVENT = "pull_request"
#: GitHub cuts a check-run name at this length (docs/DEPLOYMENT.md §3.4).
NAME_LIMIT = 100

#: A saved reading's record of jobs that await the administrator: ``{check name: the step}``.
AWAITING_KEY = "awaiting_protection"

_JOB = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")
_NAME = re.compile(r"^    name:\s*(.+?)\s*$")
_NEEDS = re.compile(r"^    needs:\s*(.+?)\s*$")
_IF = re.compile(r"^    if:\s*(.+?)\s*$")
_MATRIX_LIST = re.compile(r"^        ([A-Za-z0-9_-]+):\s*\[(.*)\]\s*$")
_MATRIX_REF = re.compile(r"\$\{\{\s*matrix\.([A-Za-z0-9_-]+)\s*\}\}")
#: The top-level trigger key, bare or quoted (``"on"`` keeps YAML 1.1 from reading ``true``).
_ON = re.compile(r"""^(?:on|"on"|'on')\s*:(.*)$""")
#: One event under a block ``on:``: a key (``pull_request:``, ``"pull_request":``) in a block
#: of keys, or a list item (``- push``, ``- "push"``) in a block of items, each bare or quoted.
_EVENT_KEY = re.compile(r"""^(["']?)([A-Za-z_]+)\1\s*:(?:\s|$)""")
_EVENT_ITEM = re.compile(r"""^-\s+(["']?)([A-Za-z_]+)\1$""")
_COMMENT = re.compile(r"\s+#.*$|^#.*$")
#: The one job-level condition that makes a job an aggregator: it runs, and so fails, when a
#: part failed, was cancelled or was skipped. Without it a failed part SKIPS the job, and a
#: skipped required check does not block a merge — so a job without it is no aggregator and
#: every job it needs must be required in its own name.
_ALWAYS = "always()"


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _fill(label: str, values: dict[str, str]) -> str:
    """``label`` with each ``${{ matrix.<key> }}`` replaced by its value."""
    return _MATRIX_REF.sub(lambda m: values[m.group(1)], label)


def _block_events(lines: list[str]) -> list[str] | None:
    """The events of a block ``on:`` whose lines follow it, or None when any line at the
    events' indent is one the scan cannot read: a block read in part would drop the events it
    missed, and with them, maybe, every job of a pull-request workflow. The first line sets
    the block's kind: keys (``push:``, each with its filters below it) or list items
    (``- push``). In a block of keys, a ``- …`` line at the keys' indent is the value of the
    key above it (``schedule:`` then ``- cron: …``), never an event."""
    events: list[str] = []
    indent: int | None = None
    items = False
    for child in lines:
        if not child.strip() or child.lstrip().startswith("#"):
            continue
        if not child.startswith(" "):
            break
        width = len(child) - len(child.lstrip(" "))
        line = _COMMENT.sub("", child).strip()
        if indent is None:
            indent, items = width, line.startswith("-")
        if width != indent:
            continue
        if items:
            e = _EVENT_ITEM.match(line)
        elif line.startswith("-") and events:
            continue
        else:
            e = _EVENT_KEY.match(line)
        if not e:
            return None
        events.append(e.group(2))
    return events or None


def triggers(text: str) -> list[str]:
    """The events a workflow's top-level ``on:`` names, in file order: ``on: push``,
    ``on: [push, pull_request]``, or a block of events (keys, with their filters, or list
    items), each bare or quoted. A workflow with no top-level ``on:``, a ``{…}`` mapping, or a
    block with no event or with any event line the scan cannot read fails closed: a workflow
    read as running on nothing, or on only some of its events, could drop its jobs out of the
    comparison, and a setting that did not require them would pass."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        m = _ON.match(line)
        if not m:
            continue
        value = _COMMENT.sub("", m.group(1)).strip()
        if value.startswith("{"):
            break
        if value.startswith("["):
            return [_unquote(v) for v in value.strip("[]").split(",") if v.strip()]
        if value:
            return [_unquote(value)]
        events = _block_events(lines[i + 1 :])
        if events:
            return events
        break
    raise SystemExit(
        "check_branch_protection: could not read the workflow's top-level on: (missing, a "
        "{…} mapping, a block with no event, or an event line it cannot read) — teach "
        "triggers this shape"
    )


def runs_on_pull_request(text: str) -> bool:
    """True when the workflow's top-level ``on:`` names :data:`PR_EVENT`."""
    return PR_EVENT in triggers(text)


@dataclass
class Job:
    """One job of a workflow as the scan reads it."""

    key: str
    name: str | None = None
    matrix: dict[str, list[str]] = field(default_factory=dict)
    needs: list[str] = field(default_factory=list)
    condition: str = ""

    def contexts(self) -> list[str]:
        """The check names this job reports: ``name:`` (or the key) once per combination of
        the matrix values it names; a job with a matrix and no ``name:`` reports
        ``key (v1, v2, …)``, as GitHub renders it. A matrix key the name uses (or, with no
        ``name:``, any matrix list) that the scan read no values for fails closed: expanding
        it would report no check at all, and a job with no check drops out of the comparison
        and passes."""
        refs = list(dict.fromkeys(_MATRIX_REF.findall(self.name or "")))
        named = refs if self.name is not None else list(self.matrix)
        unread = [r for r in named if not self.matrix.get(r)]
        if unread:
            raise SystemExit(
                f"check_branch_protection: could not read the matrix value(s) {unread} of job "
                f"{self.key!r} (an include: matrix or a multi-line list?) — teach parse_jobs "
                "this matrix shape"
            )
        if self.name is None:
            if not self.matrix:
                return [self.key]
            combos = itertools.product(*self.matrix.values())
            return [f"{self.key} ({', '.join(c)})" for c in combos]
        if not refs:
            return [self.name]
        out: list[str] = []
        for combo in itertools.product(*(self.matrix[r] for r in refs)):
            label = _fill(self.name, dict(zip(refs, combo, strict=True)))
            if label not in out:
                out.append(label)
        return out

    @property
    def aggregates(self) -> bool:
        """True for an aggregator: it needs other jobs and runs ``if: always()``."""
        return bool(self.needs) and self.condition.replace(" ", "") == _ALWAYS


def parse_jobs(ci_text: str) -> list[Job]:
    """A workflow's jobs in file order: key, ``name:``, list matrix (any number of keys),
    ``needs:`` and the job-level ``if:``."""
    jobs: list[Job] = []
    in_jobs = False
    in_matrix = False
    for line in ci_text.split("\n"):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            in_jobs = line.rstrip() == "jobs:"
            continue
        if not in_jobs:
            continue
        m = _JOB.match(line)
        if m:
            jobs.append(Job(m.group(1)))
            in_matrix = False
            continue
        if not jobs:
            continue
        job = jobs[-1]
        m = _NAME.match(line)
        if m and job.name is None:
            job.name = _unquote(m.group(1))
            continue
        m = _NEEDS.match(line)
        if m:
            raw = m.group(1).strip()
            items = raw[1:-1].split(",") if raw.startswith("[") else [raw]
            job.needs = [_unquote(v) for v in items if v.strip()]
            continue
        m = _IF.match(line)
        if m:
            job.condition = _unquote(m.group(1))
            continue
        if line.strip() == "matrix:":
            in_matrix = True
            continue
        if in_matrix:
            m = _MATRIX_LIST.match(line)
            if m:
                job.matrix[m.group(1)] = [_unquote(v) for v in m.group(2).split(",") if v.strip()]
            elif not line.startswith("        "):
                in_matrix = False
    return jobs


def job_contexts(ci_text: str) -> list[str]:
    """Every check name a workflow's jobs report, in file order, parts of an aggregator
    included."""
    return [ctx for job in parse_jobs(ci_text) for ctx in job.contexts()]


def aggregated_parts(ci_text: str) -> dict[str, str]:
    """Each check name that an aggregator stands for, mapped to the aggregator's job key. A
    part is never required in its own name: its name changes whenever the work is split
    differently, and the aggregator's does not (docs/DEPLOYMENT.md §3.4)."""
    jobs = parse_jobs(ci_text)
    by_key = {job.key: job for job in jobs}
    parts: dict[str, str] = {}
    for job in jobs:
        if not job.aggregates:
            continue
        for need in job.needs:
            if need in by_key:
                for ctx in by_key[need].contexts():
                    parts[ctx] = job.key
    return parts


def gating_contexts(ci_text: str) -> list[str]:
    """The check names that must be required: every job's, less the parts an aggregator
    stands for."""
    parts = aggregated_parts(ci_text)
    return [ctx for ctx in job_contexts(ci_text) if ctx not in parts]


def pull_request_contexts(texts: Mapping[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """``(gating, parts)`` over the workflows in ``texts`` (``{file name: text}``) that run on
    :data:`PR_EVENT`: each check name that must be required, mapped to the file that reports
    it, and each part of an aggregator, mapped to the aggregator's job key. A workflow that
    does not run on pull requests contributes neither: no merge waits on its jobs. One check
    name reported by two files fails closed: a required name cannot say which of the two
    jobs it waits on."""
    gating: dict[str, str] = {}
    parts: dict[str, str] = {}
    for name, text in texts.items():
        if not runs_on_pull_request(text):
            continue
        for ctx in gating_contexts(text):
            if ctx in gating:
                raise SystemExit(
                    f"check_branch_protection: {ctx!r} is reported by both {gating[ctx]} and "
                    f"{name}: give each job its own name"
                )
            gating[ctx] = name
        parts.update(aggregated_parts(text))
    return gating, parts


def _files(files: Iterable[str], conjunction: str = "or") -> str:
    """``ci.yml or commit-subjects.yml`` — the workflow files a sentence names, or "a
    pull-request workflow" when the caller gave check names without their files."""
    named = sorted(set(files))
    if not named:
        return "a pull-request workflow"
    return f" {conjunction} ".join([", ".join(named[:-1]), named[-1]] if named[:-1] else named)


def compare(
    jobs: Sequence[str] | Mapping[str, str],
    required: list[str],
    strict: bool,
    parts: Mapping[str, str] | None = None,
) -> list[str]:
    """Every way the setting and the workflows disagree, as sentences; empty when they agree.
    ``jobs`` are the check names that must be required — a mapping names the workflow file
    that reports each, and the sentences name it too; ``parts`` the check names an aggregator
    stands for, which must not be."""
    parts = parts or {}
    files = dict(jobs) if isinstance(jobs, Mapping) else {}
    errors: list[str] = []
    for ctx in required:
        if ctx in parts:
            errors.append(
                f"branch protection requires {ctx!r}, a part of the aggregator job "
                f"{parts[ctx]!r}: require the aggregator, never a part — a part's name changes "
                "whenever the work is split differently"
            )
        elif ctx not in jobs:
            errors.append(
                f"branch protection requires {ctx!r}, which no job in "
                f"{_files(files.values())} reports: every pull request waits on it for ever"
            )
    for ctx in [*jobs, *parts]:
        if len(ctx) >= NAME_LIMIT:
            errors.append(
                f"job name {ctx!r} is {NAME_LIMIT} characters or more: GitHub cuts a check "
                f"name at {NAME_LIMIT}, so no run can ever satisfy it"
            )
        elif ctx in jobs and ctx not in required:
            where = f" in {files[ctx]}" if ctx in files else ""
            errors.append(
                f"job {ctx!r}{where} runs on every pull request but branch protection does "
                "not require it: it can fail and the change still merges"
            )
    if not strict:
        errors.append(
            "branch protection is not strict: a branch may merge without being up to date with main"
        )
    return errors


_GAP_ID = re.compile(r"\bG-\d{3}\b")


def open_gaps() -> dict[str, str]:
    """``{gap id: its text}`` for every gap in docs/dod that blocks a criterion not yet met,
    read through scripts/dod_check.py's own parser (one reading of the record, never two)."""
    name = "_check_branch_protection_dod"
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "dod_check.py")
    assert spec and spec.loader
    dod = importlib.util.module_from_spec(spec)
    sys.modules[name] = dod  # its dataclasses look their module up while it executes
    spec.loader.exec_module(dod)
    out: dict[str, str] = {}
    for path in dod.artefact_files():
        art, _errors = dod.parse_artefact(path)
        blocking = {c.gap for c in art.criteria if c.state in ("partial", "unmet")}
        out.update({g: text for g, text in art.gaps.items() if g in blocking})
    return out


def compare_reading(
    jobs: Sequence[str] | Mapping[str, str],
    reading: dict[str, Any],
    gaps: Mapping[str, str] | None = None,
    parts: Mapping[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    """``(errors, notes)`` for one reading; ``jobs`` as :func:`compare` takes them. A SAVED
    reading may name, under :data:`AWAITING_KEY`, a job added to a pull-request workflow
    before an administrator could require it, with
    the step that remains: it is not an error while the setting lacks it, and it is listed as a
    note. The entry is an error once the setting requires the job (read it again and drop the
    entry), when no job reports it, when it names no step, and unless its step names a gap
    that is open in docs/dod (``gaps``: :func:`open_gaps`, read only when an entry needs it)
    and whose text names the job; ``parts`` are the aggregators' parts, as :func:`compare`
    takes them — so a job cannot be parked there by review alone (P-269).
    The live setting never carries the key, so the scheduled comparison stays red until the
    administrator acts (DL-101)."""
    required = [str(c) for c in reading.get("contexts", [])]
    awaiting = {str(k): str(v) for k, v in dict(reading.get(AWAITING_KEY) or {}).items()}
    errors = compare(
        jobs, required + [c for c in awaiting if c in jobs], bool(reading.get("strict")), parts
    )
    notes: list[str] = []
    for ctx, step in awaiting.items():
        if ctx in required:
            errors.append(
                f"branch protection now requires {ctx!r}: save the reading again without it "
                f"under {AWAITING_KEY}"
            )
        elif ctx not in jobs:
            where = _files(jobs.values() if isinstance(jobs, Mapping) else ())
            errors.append(f"{ctx!r} awaits branch protection, but no job in {where} reports it")
        elif not step.strip():
            errors.append(f"{ctx!r} awaits branch protection with no step named")
        else:
            named = _GAP_ID.findall(step)
            if not named:
                errors.append(
                    f"{ctx!r} awaits branch protection under no gap: name the open gap "
                    "(G-nnn) whose text names the job"
                )
                continue
            if gaps is None:
                gaps = open_gaps()
            if not any(ctx in gaps.get(g, "") for g in named):
                errors.append(
                    f"{ctx!r} awaits branch protection under {', '.join(named)}, which is not "
                    "an open gap in docs/dod that names the job"
                )
                continue
            notes.append(f"job {ctx!r} awaits the administrator: {step}")
    return errors, notes


def read_live(repo: str, branch: str) -> dict[str, Any]:
    """``required_status_checks`` for ``repo``'s ``branch``, read with ``gh`` (its token must
    be allowed to read the setting: Administration: read)."""
    done = subprocess.run(
        ["gh", "api", f"repos/{repo}/branches/{branch}/protection/required_status_checks"],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise SystemExit(
            f"check_branch_protection: could not read the setting for {repo}@{branch}: "
            f"{done.stderr.strip() or done.stdout.strip()}"
        )
    data: dict[str, Any] = json.loads(done.stdout)
    return data


def default_workflows(directory: Path = WORKFLOWS) -> list[Path]:
    """Every workflow file in ``directory``, by name; :func:`pull_request_contexts` keeps the
    ones that run on pull requests."""
    return sorted(p for p in directory.iterdir() if p.suffix in (".yml", ".yaml") and p.is_file())


def read_workflows(paths: Iterable[Path]) -> dict[str, str]:
    """``{file name: text}`` for each path. Two paths with one file name fail closed: they
    would share one key, the second would replace the first unread, and a job only the first
    runs would never be compared."""
    texts: dict[str, str] = {}
    seen: dict[str, Path] = {}
    for p in paths:
        if p.name in seen:
            raise SystemExit(
                f"check_branch_protection: two workflows are named {p.name} ({seen[p.name]} and "
                f"{p}): name each file once"
            )
        seen[p.name] = p
        texts[p.name] = p.read_text(encoding="utf-8")
    return texts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--repo", default="Jita81/commit-replay-bench")
    ap.add_argument("--branch", default="main")
    ap.add_argument(
        "--workflow",
        "--ci",
        dest="workflows",
        action="append",
        type=Path,
        metavar="PATH",
        help="a workflow whose jobs must be required (repeatable; it must run on pull_request); "
        "default: every workflow under .github/workflows that runs on pull_request. --ci is "
        "the old name",
    )
    ap.add_argument(
        "--from-json",
        type=Path,
        help="a saved required_status_checks reading, instead of reading the setting live",
    )
    args = ap.parse_args(argv)
    reading: dict[str, Any]
    if args.from_json:
        reading = json.loads(args.from_json.read_text(encoding="utf-8"))
    else:
        reading = read_live(args.repo, args.branch)
    required = [str(c) for c in reading.get("contexts", [])]
    texts = read_workflows(args.workflows or default_workflows())
    if args.workflows:
        off = [name for name, text in texts.items() if not runs_on_pull_request(text)]
        if off:
            raise SystemExit(
                f"check_branch_protection: {', '.join(off)} does not run on {PR_EVENT}: no "
                "merge waits on its jobs, so none of them can be required"
            )
    gating, parts = pull_request_contexts(texts)
    errors, notes = compare_reading(gating, reading, parts=parts)
    for e in errors:
        print(e)
    if errors:
        print(f"{len(errors)} difference(s)")
        return 1
    for n in notes:
        print(n)
    print(
        f"branch protection: {len(required)} required checks match the jobs of "
        f"{_files(gating.values(), 'and')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
