#!/usr/bin/env python3
"""Branch protection requires exactly the jobs the workflow runs — compared, not assumed.

A job in ``.github/workflows/ci.yml`` blocks a merge only while its check name is on the
branch's required-status-checks list, and that list is a repository setting, not a file. A
job renamed in the workflow, or added to it, therefore stops gating without any file saying
so; an administrator who drops a check from the setting does the same. This script reads the
setting and compares it with the workflow's jobs, both ways.

    python scripts/check_branch_protection.py --repo Jita81/commit-replay-bench
    python scripts/check_branch_protection.py --from-json reading.json   # offline

It fails on: a required check that no job reports (every pull request waits on it for
ever); a job that no required check names (it can fail and the change still merges); a
required check that is a part of an aggregator (its name changes whenever the work is split
differently); a setting that is not strict (a branch may merge while behind ``main``); and a
job name of 100 characters or more (GitHub cuts a check name at 100, so no run can satisfy
it). An aggregator is a job that ``needs`` others and runs ``if: always()`` — the ``test``
job over the suite's shards and ``walkthrough`` over the story and the screens shards: it is
required, and the parts it stands for are not.

Navigation
----------
What it is:   The comparator between branch protection's required checks and ci.yml's jobs
              (stdlib only; ``gh`` reads the setting).
What it does: Expands ci.yml's jobs into the check names GitHub reports (a matrix job once per
              combination), sets aside the parts an aggregator stands for, reads
              ``required_status_checks`` through ``gh api`` (or from a saved JSON reading),
              and prints every difference; exits non-zero on any.
How:          Line-scan the workflow's ``jobs:`` block (job key, ``name:``, list matrices,
              ``needs:``, the job-level ``if:``) → expand ``${{ matrix.<key> }}`` → the
              aggregators' parts → set comparison with the reading.
Layer:        deploy — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   .github/workflows/ci.yml (the jobs it expands), .github/workflows/
              branch-protection.yml (the scheduled run with a token that may read the
              setting), tests/fixtures/branch_protection_main.json (the last saved reading),
              docs/DEPLOYMENT.md §3.4 (the administrator's guide to the setting),
              docs/dod/product.md (product.evidence.6 and gap G-930)
Tested by:    tests/test_check_branch_protection.py
Touch when:   never for a new repository (it compares this repository's own workflow with its
              own branch setting); ci.yml gains a job shape this scan does not read (an
              ``include:`` matrix, a job-level ``if:`` that keeps a job off pull requests) —
              teach ``parse_jobs`` and add the fixture case in the same change.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CI = ROOT / ".github" / "workflows" / "ci.yml"
#: GitHub cuts a check-run name at this length (docs/DEPLOYMENT.md §3.4).
NAME_LIMIT = 100

_JOB = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")
_NAME = re.compile(r"^    name:\s*(.+?)\s*$")
_NEEDS = re.compile(r"^    needs:\s*(.+?)\s*$")
_IF = re.compile(r"^    if:\s*(.+?)\s*$")
_MATRIX_LIST = re.compile(r"^        ([A-Za-z0-9_-]+):\s*\[(.*)\]\s*$")
_MATRIX_REF = re.compile(r"\$\{\{\s*matrix\.([A-Za-z0-9_-]+)\s*\}\}")
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


@dataclass
class Job:
    """One job of ci.yml as the scan reads it."""

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
    """ci.yml's jobs in file order: key, ``name:``, list matrix (any number of keys),
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
    """Every check name ci.yml's jobs report, in file order, parts of an aggregator included."""
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


def compare(
    jobs: list[str], required: list[str], strict: bool, parts: dict[str, str] | None = None
) -> list[str]:
    """Every way the setting and the workflow disagree, as sentences; empty when they agree.
    ``jobs`` are the check names that must be required; ``parts`` the check names an
    aggregator stands for, which must not be."""
    parts = parts or {}
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
                f"branch protection requires {ctx!r}, which no job in ci.yml reports: "
                "every pull request waits on it for ever"
            )
    for ctx in [*jobs, *parts]:
        if len(ctx) >= NAME_LIMIT:
            errors.append(
                f"job name {ctx!r} is {NAME_LIMIT} characters or more: GitHub cuts a check "
                f"name at {NAME_LIMIT}, so no run can ever satisfy it"
            )
        elif ctx in jobs and ctx not in required:
            errors.append(
                f"job {ctx!r} runs on every pull request but branch protection does not "
                "require it: it can fail and the change still merges"
            )
    if not strict:
        errors.append(
            "branch protection is not strict: a branch may merge without being up to date with main"
        )
    return errors


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--repo", default="Jita81/commit-replay-bench")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--ci", type=Path, default=CI, help="the workflow whose jobs must be required")
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
    strict = bool(reading.get("strict"))
    ci_text = args.ci.read_text(encoding="utf-8")
    errors = compare(gating_contexts(ci_text), required, strict, aggregated_parts(ci_text))
    for e in errors:
        print(e)
    if errors:
        print(f"{len(errors)} difference(s)")
        return 1
    print(f"branch protection: {len(required)} required checks match the jobs in {args.ci.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
