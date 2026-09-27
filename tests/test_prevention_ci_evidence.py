"""A prevention row's ``ci:`` evidence names a job that runs what the row says fails (P-128).

A row of docs/PREVENTION.md lists the artefacts that fail if its class of defect returns. A
``ci:<job>`` citation says that job fails. P-122 cited ``ci:claims`` for the README
re-derivation, but the claims job runs only ``scripts/claims_check.py --check``; the
re-derivation is ``tests/test_measured_claims.py``, which runs in the ``test`` job. Both jobs
are required, so nothing merged unchecked, but the row named the wrong gate, and a reader
who went to the claims job to see the class held would not have found it.

Navigation
----------
What it is:   The check that a prevention row citing a CI job that runs one repository
              script, and no pytest, also cites a test of that script — so the job it names
              runs what the row's other evidence exercises.
What it does: Reads each job of .github/workflows/ci.yml; a job whose ``run`` steps name
              exactly one ``scripts/<x>.py`` and never run pytest is a single-script job
              (claims, dod, code-map). Every docs/PREVENTION.md row that cites ``ci:<job>``
              for such a job must cite a ``test:tests/test_<x>.py::`` evidence too. A
              synthetic row in P-122's old shape must fail, so the check cannot pass
              vacuously.
How:          ``single_script_jobs(workflow)`` → ``{job: script}``;
              ``misattributed(rows, jobs)`` → the rows that cite a job without a test of its
              script.
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   docs/PREVENTION.md (the rows it reads), .github/workflows/ci.yml (the jobs),
              scripts/dod_check.py (resolves a ``ci:`` citation to a job that exists; this
              checks the job is the right one), tests/test_measured_claims.py (P-122's real
              evidence)
Tested by:    (this is a test file)
Touch when:   a CI job starts or stops running a single script; the prevention register's
              row format changes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
PREVENTION = ROOT / "docs" / "PREVENTION.md"

_SCRIPT_RE = re.compile(r"\bscripts/([A-Za-z0-9_]+)\.py\b")
_ROW_RE = re.compile(r"^\|\s*(P-\d{3})\s*\|")
_CI_RE = re.compile(r"`ci:([A-Za-z0-9_-]+)`")


def single_script_jobs(workflow: dict[str, Any]) -> dict[str, str]:
    """``{job: script stem}`` for every job whose steps run one repository script, no pytest."""
    out: dict[str, str] = {}
    for job, spec in (workflow.get("jobs") or {}).items():
        runs = " ".join(str(step.get("run", "")) for step in spec.get("steps") or [])
        scripts = set(_SCRIPT_RE.findall(runs))
        if len(scripts) == 1 and "pytest" not in runs:
            out[job] = scripts.pop()
    return out


def misattributed(rows: list[str], jobs: dict[str, str]) -> list[tuple[str, str]]:
    """``(row id, job)`` for every row whose evidence cites a single-script job with no test
    of its script. Only the evidence cell is read: a row's prose may name a job it does not
    cite."""
    out: list[tuple[str, str]] = []
    for line in rows:
        m = _ROW_RE.match(line)
        if not m:
            continue
        evidence = line.strip().strip("|").split("|")[-4]
        for job in _CI_RE.findall(evidence):
            script = jobs.get(job)
            if script and f"`test:tests/test_{script}.py::" not in evidence:
                out.append((m.group(1), job))
    return out


def _jobs() -> dict[str, str]:
    return single_script_jobs(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")))


def test_the_single_script_jobs_are_found() -> None:
    """The check reads the jobs it must: if the claims job stopped being found, every row
    would pass for want of a job to check."""
    jobs = _jobs()
    assert jobs.get("claims") == "claims_check"
    assert jobs.get("dod") == "dod_check"
    assert "test" not in jobs


def test_every_prevention_row_names_a_ci_job_that_runs_its_evidence() -> None:
    rows = PREVENTION.read_text(encoding="utf-8").splitlines()
    assert misattributed(rows, _jobs()) == []


def test_a_row_citing_the_claims_job_for_a_test_it_does_not_run_fails() -> None:
    """P-122's old evidence: the re-derivation's tests and ``ci:claims``, which runs none."""
    row = (
        "| P-999 | a re-derivation defect | a-class | a finder | "
        "`test:tests/test_measured_claims.py::test_a_real_figure_in_the_wrong_role_fails` · "
        "`ci:claims` | gate | closed | |"
    )
    assert misattributed([row], _jobs()) == [("P-999", "claims")]
    fixed = row.replace("`ci:claims`", "`test:tests/test_claims_check.py::test_x` · `ci:claims`")
    assert misattributed([fixed], _jobs()) == []
