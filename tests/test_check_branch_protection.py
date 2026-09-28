"""Branch protection requires exactly the jobs the workflow runs — compared, not assumed.

Navigation
----------
What it is:   The tests for scripts/check_branch_protection.py.
What it does: Pins that the workflow's jobs expand to the check names branch protection must
              require (a matrix job once per combination, an aggregator's parts set aside);
              that the comparison names a required check no job reports, a job nobody
              requires, a required part of an aggregator, a non-strict setting and a job name
              GitHub would cut at 100 characters; that the last reading of the setting
              (tests/fixtures/branch_protection_main.json) still matches ci.yml, so renaming or
              adding a job fails here until the setting is read again — or until the reading
              names the job under ``awaiting_protection`` with the administrator's step and
              an open gap in docs/dod that names the job, an entry that is itself refused once
              stale or once no open gap holds it (DL-101, P-269); and that the scheduled
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
Touch when:   never for a new repository (it pins this repository's own workflow and setting);
              a job is added to or renamed in ci.yml (read the setting again after the
              administrator updates it, and save the reading in the fixture; until then name
              the job under ``awaiting_protection`` with the step that remains).
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


SPLIT_CI_TEXT = """name: ci
jobs:
  test-shard:
    name: test shard (py${{ matrix.python }}, ${{ matrix.shard }} of 2)
    strategy:
      matrix:
        python: ["3.12", "3.13"]
        shard: [1, 2]
  test:
    name: test (py${{ matrix.python }})
    needs: [test-shard]
    if: always()
    strategy:
      matrix:
        python: ["3.12", "3.13"]
  story:
    name: walkthrough story
  walkthrough:
    name: walkthrough
    needs: [story]
    if: always()
  build:
    name: build
  deploy:
    name: deploy
    needs: build
"""


def test_a_multi_key_matrix_is_one_check_per_combination_and_an_aggregator_stands_for_its_parts() -> (
    None
):
    mod = _load()
    assert mod.job_contexts(SPLIT_CI_TEXT) == [
        "test shard (py3.12, 1 of 2)",
        "test shard (py3.12, 2 of 2)",
        "test shard (py3.13, 1 of 2)",
        "test shard (py3.13, 2 of 2)",
        "test (py3.12)",
        "test (py3.13)",
        "walkthrough story",
        "walkthrough",
        "build",
        "deploy",
    ]
    parts = mod.aggregated_parts(SPLIT_CI_TEXT)
    assert parts == {
        "test shard (py3.12, 1 of 2)": "test",
        "test shard (py3.12, 2 of 2)": "test",
        "test shard (py3.13, 1 of 2)": "test",
        "test shard (py3.13, 2 of 2)": "test",
        "walkthrough story": "walkthrough",
    }
    # `deploy` needs `build` without `if: always()`: a failed build SKIPS deploy, and a
    # skipped required check does not block a merge — so `build` gates in its own name.
    assert mod.gating_contexts(SPLIT_CI_TEXT) == [
        "test (py3.12)",
        "test (py3.13)",
        "walkthrough",
        "build",
        "deploy",
    ]


def test_a_part_of_an_aggregator_is_never_required_in_its_own_name() -> None:
    mod = _load()
    gating = mod.gating_contexts(SPLIT_CI_TEXT)
    parts = mod.aggregated_parts(SPLIT_CI_TEXT)
    assert mod.compare(gating, list(gating), strict=True, parts=parts) == []
    with_part = mod.compare(gating, [*gating, "walkthrough story"], strict=True, parts=parts)
    assert with_part == [
        "branch protection requires 'walkthrough story', a part of the aggregator job "
        "'walkthrough': require the aggregator, never a part — a part's name changes whenever "
        "the work is split differently"
    ]
    no_aggregator = mod.compare(
        gating, [c for c in gating if c != "walkthrough"], strict=True, parts=parts
    )
    assert no_aggregator == [
        "job 'walkthrough' runs on every pull request but branch protection does not require "
        "it: it can fail and the change still merges"
    ]


UNREAD_MATRIX_CI_TEXT = """name: ci
jobs:
  lint:
    name: lint
  test:
    name: test (py${{ matrix.python }})
    strategy:
      matrix:
        include:
          - python: "3.12"
"""

EMPTY_LIST_CI_TEXT = """name: ci
jobs:
  lint:
    name: lint
  test:
    strategy:
      matrix:
        python: []
"""


@pytest.mark.parametrize(
    "ci_text", [UNREAD_MATRIX_CI_TEXT, EMPTY_LIST_CI_TEXT], ids=["include-matrix", "empty-list"]
)
def test_a_matrix_the_scan_cannot_read_fails_closed_never_drops_the_job(ci_text: str) -> None:
    """A job whose ``name:`` names a matrix key the scan did not read (an ``include:`` matrix,
    a multi-line list), or whose matrix list is empty, used to expand to no check names at
    all: it dropped out of the comparison, and a setting that did not require it passed."""
    mod = _load()
    with pytest.raises(SystemExit, match="could not read"):
        mod.gating_contexts(ci_text)


def test_the_real_workflow_requires_its_aggregators_and_none_of_their_parts() -> None:
    """Main's CI splits the suite into shards, the walkthrough into a story and screens
    shards, and the fresh-clone check into its gates and the suite's shards (P-743); the
    contexts to require stay on the `test`, `walkthrough` and `fresh-clone` aggregators."""
    mod = _load()
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    parts = mod.aggregated_parts(ci)
    assert set(parts.values()) == {"test", "walkthrough", "fresh-clone"}
    assert sum(1 for c in parts if c.startswith("test shard (py")) == 12
    assert "walkthrough story (browser, live stack, tier 1)" in parts
    assert sum(1 for c in parts if c.startswith("walkthrough screens (")) == 4
    assert "fresh-clone gates (from uv.lock, as root, no docker daemon)" in parts
    assert sum(1 for c in parts if c.startswith("fresh-clone shard (")) == 6
    gating = mod.gating_contexts(ci)
    assert {
        "test (py3.12)",
        "test (py3.13)",
        "walkthrough (browser, live stack, tier 1)",
        "fresh-clone (every gate from uv.lock, as root, no docker daemon)",
    } <= set(gating)
    assert not set(gating) & set(parts)


def test_the_last_reading_of_the_setting_still_matches_the_workflow() -> None:
    """A job renamed or added in ci.yml breaks the required-check list silently — the renamed
    check is never reported, and every pull request waits for ever. This fails first: read the
    setting again once the administrator has updated it, and save it in the fixture."""
    mod = _load()
    reading = json.loads(READING.read_text(encoding="utf-8"))
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    errors, awaiting = mod.compare_reading(
        mod.gating_contexts(ci), reading, mod.open_gaps(), mod.aggregated_parts(ci)
    )
    assert errors == []
    assert len(reading["contexts"]) == 16
    # a job the administrator has not yet required is named, with its step, never silent
    fresh = "fresh-clone (every gate from uv.lock, as root, no docker daemon)"
    step = reading["awaiting_protection"][fresh]
    assert awaiting == [f"job {fresh!r} awaits the administrator: {step}"]


def test_a_job_awaiting_protection_is_held_to_the_setting_and_the_workflow() -> None:
    """The saved reading's ``awaiting_protection`` entry is honest only while the setting
    lacks the job, a job reports it and it names the step; each lapse is a difference. A
    reading without the entry — every live reading — still refuses the unrequired job."""
    mod = _load()
    jobs = mod.job_contexts(CI_TEXT)
    gaps = {"G-930": "an administrator adds `bare` to the required checks · deploy"}
    base = {"strict": True, "contexts": ["lint (ruff)", "test (py3.12)", "test (py3.13)"]}
    assert mod.compare_reading(jobs, base, gaps)[0] == [
        "job 'bare' runs on every pull request but branch protection does not require it: "
        "it can fail and the change still merges"
    ]
    step = "an administrator requires it (G-930)"
    waiting = {**base, "awaiting_protection": {"bare": step}}
    assert mod.compare_reading(jobs, waiting, gaps) == (
        [],
        [f"job 'bare' awaits the administrator: {step}"],
    )
    now_required = {**waiting, "contexts": [*base["contexts"], "bare"]}
    assert mod.compare_reading(jobs, now_required, gaps)[0] == [
        "branch protection now requires 'bare': save the reading again without it under "
        "awaiting_protection"
    ]
    ghost = {**waiting, "awaiting_protection": {"bare": step, "gone": "an administrator"}}
    assert mod.compare_reading(jobs, ghost, gaps)[0] == [
        "'gone' awaits branch protection, but no job in ci.yml reports it"
    ]
    silent = {**base, "awaiting_protection": {"bare": " "}}
    assert mod.compare_reading(jobs, silent, gaps)[0] == [
        "'bare' awaits branch protection with no step named"
    ]


def test_a_job_awaits_protection_only_under_an_open_gap_that_names_it() -> None:
    """The entry is bounded by the record, not by review (DL-101, P-269): its step names a
    gap id, the gap is open in docs/dod (it blocks a criterion that is not met), and the
    gap's own text names the job. A job parked under the key with no gap, under a closed
    gap, or under a gap about something else — say one dropped from the required list —
    fails, so the saved-reading test cannot be kept green by moving a job there."""
    mod = _load()
    jobs = mod.job_contexts(CI_TEXT)
    base = {"strict": True, "contexts": ["lint (ruff)", "test (py3.12)", "test (py3.13)"]}
    gaps = {
        "G-930": "an administrator adds `bare` to the required checks · deploy",
        "G-111": "something else entirely · deploy",
    }
    no_gap = {**base, "awaiting_protection": {"bare": "an administrator requires it"}}
    assert mod.compare_reading(jobs, no_gap, gaps)[0] == [
        "'bare' awaits branch protection under no gap: name the open gap (G-nnn) whose "
        "text names the job"
    ]
    closed = {**base, "awaiting_protection": {"bare": "an administrator requires it (G-930)"}}
    assert mod.compare_reading(jobs, closed, {})[0] == [
        "'bare' awaits branch protection under G-930, which is not an open gap in docs/dod "
        "that names the job"
    ]
    elsewhere = {**base, "awaiting_protection": {"bare": "parked (G-111)"}}
    assert mod.compare_reading(jobs, elsewhere, gaps)[0] == [
        "'bare' awaits branch protection under G-111, which is not an open gap in docs/dod "
        "that names the job"
    ]
    # the real record: the fixture's entry names G-930, which is open and names the job
    reading = json.loads(READING.read_text(encoding="utf-8"))
    (fresh,) = reading["awaiting_protection"]
    live = mod.open_gaps()
    assert "G-930" in reading["awaiting_protection"][fresh] and fresh in live["G-930"]


def test_main_compares_a_saved_reading_and_fails_on_any_difference(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = _load()
    assert mod.main(["--from-json", str(READING)]) == 0
    said = capsys.readouterr().out
    assert "branch protection: 16 required checks match" in said
    assert "awaits the administrator" in said
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
