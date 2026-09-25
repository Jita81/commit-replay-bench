"""Every CI job's check-run name is under 100 characters — a longer one can never go green.

GitHub truncates a check-run name at 100 characters, and branch protection matches the FULL
name of a required context, so a job whose rendered name is 100 characters or more can never
satisfy a required status check: the pull request waits forever for a context that no run
will ever report. It bit us on 2026-09-22/23 (PR #48; docs/PREVENTION.md P-001). Before this
test the only guard was a comment in ci.yml asking the next author to count.

Navigation
----------
What it is:   The gate that keeps every job name in .github/workflows/*.yml under 100
              characters, as GitHub renders it (matrix expressions expanded to their longest
              value).
What it does: Reads each workflow's ``jobs:`` block line by line (no YAML dependency: PyYAML
              is not a declared dependency), takes each job's ``name:`` or, without one, its
              id, expands ``${{ matrix.<key> }}`` to the longest value the job's matrix lists,
              and fails naming every job at 100 characters or more. It also refuses to pass
              vacuously: the parser must find the jobs we know exist, and a synthetic
              workflow with a long name must fail.
How:          ``job_names(text)`` → ``{job_id: rendered_name}``; ``too_long(names)``; the
              repository's workflows are read from disk.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   .github/workflows/ci.yml (the required contexts), .github/workflows/release.yml
              (read the same way), docs/PREVENTION.md (P-001 — the bug this closes),
              docs/dod/STANDARD.md (the rule that a defect is closed only by an artefact that
              fails)
Tested by:    (this is a test file)
Touch when:   a workflow file is added (it is found by the glob); GitHub changes the limit.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
#: GitHub truncates a check-run name at this many characters; a required context is matched
#: on the full name, so the rendered name must be strictly shorter.
LIMIT = 100

_JOB_KEY = re.compile(r"^  ([A-Za-z0-9_-]+):\s*(?:#.*)?$")
_JOB_NAME = re.compile(r"^    name:\s*(.+?)\s*$")
_MATRIX_LIST = re.compile(r"^\s+([A-Za-z0-9_-]+):\s*\[(.*)\]\s*$")
_MATRIX_EXPR = re.compile(r"\$\{\{\s*matrix\.([A-Za-z0-9_-]+)\s*\}\}")
#: What a matrix expression renders as when the job lists no values for its key — long
#: enough that a name near the limit is caught rather than waved through.
_UNKNOWN_MATRIX_VALUE = "x" * 16


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def job_names(text: str) -> dict[str, str]:
    """``{job_id: the name GitHub renders}`` for one workflow's ``jobs:`` block."""
    lines = text.split("\n")
    try:
        start = next(i for i, line in enumerate(lines) if line.rstrip() == "jobs:")
    except StopIteration:
        return {}
    blocks: dict[str, list[str]] = {}
    current = ""
    for line in lines[start + 1 :]:
        if line and not line.startswith(" ") and not line.startswith("#"):
            break  # the next top-level key ends the jobs block
        m = _JOB_KEY.match(line)
        if m:
            current = m.group(1)
            blocks[current] = []
        elif current:
            blocks[current].append(line)
    out: dict[str, str] = {}
    for job, body in blocks.items():
        name = job
        for line in body:
            nm = _JOB_NAME.match(line)
            if nm:
                name = _unquote(nm.group(1))
                break
        matrix: dict[str, str] = {}
        for line in body:
            ml = _MATRIX_LIST.match(line)
            if ml:
                values = [_unquote(v) for v in ml.group(2).split(",") if v.strip()]
                if values:
                    matrix[ml.group(1)] = max(values, key=len)
        out[job] = _MATRIX_EXPR.sub(
            lambda m, mx=matrix: mx.get(m.group(1), _UNKNOWN_MATRIX_VALUE), name
        )
    return out


def too_long(names: dict[str, str]) -> list[str]:
    """Every job whose rendered name GitHub would truncate, with its length."""
    return [
        f"{job}: {len(name)} chars — {name!r}" for job, name in names.items() if len(name) >= LIMIT
    ]


def test_every_ci_job_name_is_under_100_characters() -> None:
    files = sorted(WORKFLOWS.glob("*.yml"))
    assert files, "no workflow files found"
    offenders: list[str] = []
    for path in files:
        offenders += [f"{path.name}: {o}" for o in too_long(job_names(path.read_text("utf-8")))]
    assert not offenders, (
        "GitHub truncates a check-run name at 100 characters and branch protection matches the "
        "full name, so these jobs can never satisfy a required check — shorten them:\n"
        + "\n".join(offenders)
    )


def test_the_parser_finds_the_jobs_we_know_exist() -> None:
    """The gate must not pass because it read nothing."""
    names = job_names((WORKFLOWS / "ci.yml").read_text("utf-8"))
    assert {"lint", "types", "dod", "test", "ui-unit", "container"} <= set(names)
    assert names["test"].startswith("test (py3.1")  # the matrix expression was expanded
    assert "${{" not in "".join(names.values())


def test_a_long_name_and_a_long_matrix_value_are_caught() -> None:
    long_name = "x" * 100
    text = (
        "name: ci\non:\n  push:\njobs:\n"
        f"  short:\n    name: short\n    runs-on: ubuntu-latest\n"
        f"  long:\n    name: {long_name}\n    runs-on: ubuntu-latest\n"
        '  matrixed:\n    name: "test (py${{ matrix.python }})"\n'
        "    strategy:\n      matrix:\n"
        f'        python: ["3.12", "{"9" * 95}"]\n'
        "  unnamed-job-uses-its-id:\n    runs-on: ubuntu-latest\n"
    )
    names = job_names(text)
    assert names["unnamed-job-uses-its-id"] == "unnamed-job-uses-its-id"
    bad = too_long(names)
    assert [b.split(":")[0] for b in bad] == ["long", "matrixed"]
