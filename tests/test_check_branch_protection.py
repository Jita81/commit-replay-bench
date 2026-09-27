"""Branch protection requires exactly the jobs the workflow runs — compared, not assumed.

Navigation
----------
What it is:   The tests for scripts/check_branch_protection.py.
What it does: Pins that the workflow's jobs expand to the check names branch protection must
              require (a matrix job once per value); that the comparison names a required
              check no job reports, a job nobody requires, a non-strict setting and a job name
              GitHub would cut at 100 characters; that the last reading of the setting
              (tests/fixtures/branch_protection_main.json) still matches ci.yml, so renaming or
              adding a job fails here until the setting is read again; and that the scheduled
              workflow runs the live comparison and fails, never passes, without its token.
How:          Calls the module's functions on fixture text and on the real ci.yml, runs
              ``main`` against the saved reading, and reads the workflow file.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   scripts/check_branch_protection.py (under test), .github/workflows/ci.yml (the
              jobs), .github/workflows/branch-protection.yml (the scheduled live run),
              tests/fixtures/branch_protection_main.json (the last reading),
              docs/dod/product.md (product.evidence.6 cites these tests)
Tested by:    (this is a test file)
Touch when:   a job is added to or renamed in ci.yml (read the setting again after the
              administrator updates it, and save the reading in the fixture).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
READING = ROOT / "tests" / "fixtures" / "branch_protection_main.json"
WORKFLOW = ROOT / ".github" / "workflows" / "branch-protection.yml"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_branch_protection", ROOT / "scripts" / "check_branch_protection.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_branch_protection"] = mod
    spec.loader.exec_module(mod)
    return mod


CI_TEXT = """name: ci
on:
  pull_request:
jobs:
  lint:
    name: lint (ruff)
    runs-on: ubuntu-latest
    steps:
      - run: ruff
  test:
    name: test (py${{ matrix.python }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python: ["3.12", "3.13"]
    steps:
      - uses: actions/setup-python@v7
        with:
          python-version: ${{ matrix.python }}
  bare:
    runs-on: ubuntu-latest
    steps:
      - run: true
"""


def test_each_job_is_one_check_and_a_matrix_job_one_per_value() -> None:
    mod = _load()
    assert mod.job_contexts(CI_TEXT) == [
        "lint (ruff)",
        "test (py3.12)",
        "test (py3.13)",
        "bare",
    ]


def test_the_comparison_names_every_way_the_setting_and_the_workflow_disagree() -> None:
    mod = _load()
    jobs = mod.job_contexts(CI_TEXT)
    assert mod.compare(jobs, list(jobs), strict=True) == []
    missing = mod.compare(jobs, ["lint (ruff)", "test (py3.12)", "test (py3.13)"], strict=True)
    assert missing == [
        "job 'bare' runs on every pull request but branch protection does not require it: "
        "it can fail and the change still merges"
    ]
    ghost = mod.compare(jobs, [*jobs, "types (mypy --strict)"], strict=True)
    assert ghost == [
        "branch protection requires 'types (mypy --strict)', which no job in ci.yml reports: "
        "every pull request waits on it for ever"
    ]
    loose = mod.compare(jobs, list(jobs), strict=False)
    assert loose == [
        "branch protection is not strict: a branch may merge without being up to date with main"
    ]
    long_name = "x" * 100
    cut = mod.compare([long_name], [long_name], strict=True)
    assert cut == [
        f"job name {long_name!r} is 100 characters or more: GitHub cuts a check name at 100, "
        "so no run can ever satisfy it"
    ]


def test_the_last_reading_of_the_setting_still_matches_the_workflow() -> None:
    """A job renamed or added in ci.yml breaks the required-check list silently — the renamed
    check is never reported, and every pull request waits for ever. This fails first: read the
    setting again once the administrator has updated it, and save it in the fixture."""
    mod = _load()
    reading = json.loads(READING.read_text(encoding="utf-8"))
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert mod.compare(mod.job_contexts(ci), reading["contexts"], reading["strict"]) == []
    assert len(reading["contexts"]) == 16


def test_main_compares_a_saved_reading_and_fails_on_any_difference(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = _load()
    assert mod.main(["--from-json", str(READING)]) == 0
    assert "branch protection: 16 required checks match" in capsys.readouterr().out
    reading = json.loads(READING.read_text(encoding="utf-8"))
    reading["contexts"].remove(
        "dod (every route, journey and stream has its definition of done; evidence resolves)"
    )
    edited = tmp_path / "reading.json"
    edited.write_text(json.dumps(reading), encoding="utf-8")
    assert mod.main(["--from-json", str(edited)]) == 1
    out = capsys.readouterr().out
    assert (
        "job 'dod (every route, journey and stream has its definition of done; evidence resolves)' runs on every pull request"
        in out
    )
    assert "1 difference(s)" in out


def test_the_scheduled_workflow_runs_the_live_comparison_and_fails_without_its_token() -> None:
    """The setting can only be read with a token allowed to read it (Administration: read),
    which the workflow's own GITHUB_TOKEN can never be granted. Without it the run is red —
    a comparison that silently passes would be the fabricated default this gate replaces."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "schedule:" in text and "workflow_dispatch:" in text
    assert "GH_TOKEN: ${{ secrets.BRANCH_PROTECTION_TOKEN }}" in text
    assert 'test -n "$GH_TOKEN"' in text
    assert "python scripts/check_branch_protection.py --repo" in text
    assert "continue-on-error" not in text
