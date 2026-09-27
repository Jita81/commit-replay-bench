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
setting that is not strict (a branch may merge while behind ``main``); and a job name of 100
characters or more (GitHub cuts a check name at 100, so no run can satisfy it).

Navigation
----------
What it is:   The comparator between branch protection's required checks and ci.yml's jobs
              (stdlib only; ``gh`` reads the setting).
What it does: Expands ci.yml's jobs into the check names GitHub reports (a matrix job once per
              value), reads ``required_status_checks`` through ``gh api`` (or from a saved
              JSON reading), and prints every difference; exits non-zero on any.
How:          Line-scan the workflow's ``jobs:`` block (job key, ``name:``, a one-key list
              matrix) → expand ``${{ matrix.<key> }}`` → set comparison with the reading.
Layer:        deploy — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   .github/workflows/ci.yml (the jobs it expands), .github/workflows/
              branch-protection.yml (the scheduled run with a token that may read the
              setting), tests/fixtures/branch_protection_main.json (the last saved reading),
              docs/DEPLOYMENT.md §3.4 (the administrator's guide to the setting),
              docs/dod/product.md (product.evidence.6 and gap G-930)
Tested by:    tests/test_check_branch_protection.py
Touch when:   ci.yml gains a job shape this scan does not read (a multi-key matrix, a job-level
              ``if:`` that keeps a job off pull requests) — teach ``job_contexts`` and add the
              fixture case in the same change.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CI = ROOT / ".github" / "workflows" / "ci.yml"
#: GitHub cuts a check-run name at this length (docs/DEPLOYMENT.md §3.4).
NAME_LIMIT = 100

_JOB = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")
_NAME = re.compile(r"^    name:\s*(.+?)\s*$")
_MATRIX_LIST = re.compile(r"^        ([A-Za-z0-9_-]+):\s*\[(.*)\]\s*$")
_MATRIX_REF = re.compile(r"\$\{\{\s*matrix\.([A-Za-z0-9_-]+)\s*\}\}")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def job_contexts(ci_text: str) -> list[str]:
    """The check names ci.yml's jobs report, in file order: ``name:`` (or the job key), with
    ``${{ matrix.<key> }}`` expanded once per value of a one-key list matrix."""
    jobs: list[tuple[str, str | None, dict[str, list[str]]]] = []
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
            jobs.append((m.group(1), None, {}))
            in_matrix = False
            continue
        if not jobs:
            continue
        key, name, matrix = jobs[-1]
        m = _NAME.match(line)
        if m and name is None:
            jobs[-1] = (key, _unquote(m.group(1)), matrix)
            continue
        if line.strip() == "matrix:":
            in_matrix = True
            continue
        if in_matrix:
            m = _MATRIX_LIST.match(line)
            if m:
                matrix[m.group(1)] = [_unquote(v) for v in m.group(2).split(",") if v.strip()]
            elif not line.startswith("        "):
                in_matrix = False
    out: list[str] = []
    for key, name, matrix in jobs:
        label = name or key
        refs = _MATRIX_REF.findall(label)
        if not refs:
            if matrix and name is None:
                (values,) = matrix.values()
                out += [f"{key} ({v})" for v in values]
            else:
                out.append(label)
            continue
        (ref,) = set(refs)
        out += [_MATRIX_REF.sub(v, label) for v in matrix.get(ref, [])]
    return out


def compare(jobs: list[str], required: list[str], strict: bool) -> list[str]:
    """Every way the setting and the workflow disagree, as sentences; empty when they agree."""
    errors: list[str] = []
    for ctx in required:
        if ctx not in jobs:
            errors.append(
                f"branch protection requires {ctx!r}, which no job in ci.yml reports: "
                "every pull request waits on it for ever"
            )
    for ctx in jobs:
        if len(ctx) >= NAME_LIMIT:
            errors.append(
                f"job name {ctx!r} is {NAME_LIMIT} characters or more: GitHub cuts a check "
                f"name at {NAME_LIMIT}, so no run can ever satisfy it"
            )
        elif ctx not in required:
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
    jobs = job_contexts(args.ci.read_text(encoding="utf-8"))
    errors = compare(jobs, required, strict)
    for e in errors:
        print(e)
    if errors:
        print(f"{len(errors)} difference(s)")
        return 1
    print(f"branch protection: {len(required)} required checks match the jobs in {args.ci.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
