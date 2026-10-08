"""Branch protection requires exactly the pull-request workflows' jobs — compared, not assumed.

Navigation
----------
What it is:   The tests for scripts/check_branch_protection.py.
What it does: Pins that every workflow whose top-level ``on:`` names ``pull_request`` — and
              no other — has its jobs held to the setting, its ``on:`` read in each form and
              refused in any other; that the jobs expand to the check names branch protection
              must require (a matrix job once per combination, an aggregator's parts set
              aside); that the comparison names a required check no pull-request workflow
              reports, a job nobody requires (with its file), a required part of an
              aggregator, a non-strict setting and a job name GitHub would cut at 100
              characters; that the last reading of the setting
              (tests/fixtures/branch_protection_main.json) still matches the workflows, so
              renaming or adding a job fails here until the setting is read again — or until
              the reading names the job under ``awaiting_protection`` with the administrator's
              step and an open gap in docs/dod that names the job, an entry that is itself
              refused once stale or once no open gap holds it (DL-101, P-269); and that the
              scheduled workflow runs the live comparison and fails, never passes, without its
              token.
How:          Calls the module's functions on fixture text and on the real workflows, runs
              ``main`` against the saved reading, and reads the workflow file.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   scripts/check_branch_protection.py (under test), .github/workflows/ci.yml and
              .github/workflows/commit-subjects.yml (the pull-request workflows' jobs),
              .github/workflows/branch-protection.yml (the scheduled live run),
              tests/fixtures/branch_protection_main.json (the last reading),
              docs/dod/product.md (product.evidence.6 cites these tests)
Tested by:    (this is a test file)
Touch when:   never for a new repository (it pins this repository's own workflow and setting);
              a job is added to or renamed in a pull-request workflow, or a workflow starts
              or stops running on pull requests (read the setting again after the
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
FRESH = "fresh-clone (every gate from uv.lock, as root, no docker daemon)"
SUBJECTS = "commit-subjects (Conventional Commits, imperative, at most 72 characters)"


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
        "branch protection requires 'types (mypy --strict)', which no job in a pull-request "
        "workflow reports: every pull request waits on it for ever"
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


SUBJECTS_TEXT = """name: commit-subjects
on:
  pull_request:
    types: [opened, synchronize, reopened, edited]
  push:
    branches: [main]
jobs:
  commit-subjects:
    name: commit-subjects (Conventional Commits, imperative, at most 72 characters)
    runs-on: ubuntu-latest
    steps:
      - name: Every commit subject on the pull request
        if: github.event_name == 'pull_request'
        run: python scripts/check_commit_subject.py --check
"""

RELEASE_TEXT = """name: release
on:
  push:
    tags: ["v*"]
  workflow_dispatch:
jobs:
  publish:
    name: publish (the tagged image)
    runs-on: ubuntu-latest
"""

WORKFLOW_TEXTS = {
    "ci.yml": CI_TEXT,
    "commit-subjects.yml": SUBJECTS_TEXT,
    "release.yml": RELEASE_TEXT,
}


def test_a_job_in_any_pull_request_workflow_gates_not_only_ci_yml() -> None:
    """The comparison once read ci.yml alone, so commit-subjects.yml's job — a pull-request
    check in its own file — could fail and the change still merge, and nothing said so."""
    mod = _load()
    gating, parts = mod.pull_request_contexts(WORKFLOW_TEXTS)
    assert gating == {
        "lint (ruff)": "ci.yml",
        "test (py3.12)": "ci.yml",
        "test (py3.13)": "ci.yml",
        "bare": "ci.yml",
        SUBJECTS: "commit-subjects.yml",
    }
    assert parts == {}
    without = [c for c in gating if c != SUBJECTS]
    assert mod.compare(gating, without, strict=True, parts=parts) == [
        f"job {SUBJECTS!r} in commit-subjects.yml runs on every pull request but branch "
        "protection does not require it: it can fail and the change still merges"
    ]
    assert mod.compare(gating, list(gating), strict=True, parts=parts) == []


def test_a_workflow_that_does_not_run_on_pull_requests_gates_nothing() -> None:
    """release.yml runs on a tag push and by hand: no merge waits on it, so requiring its job
    would hold every pull request for ever, and leaving it off the list is right."""
    mod = _load()
    assert mod.triggers(RELEASE_TEXT) == ["push", "workflow_dispatch"]
    assert not mod.runs_on_pull_request(RELEASE_TEXT)
    gating, _ = mod.pull_request_contexts(WORKFLOW_TEXTS)
    assert "publish (the tagged image)" not in gating
    assert mod.pull_request_contexts({"release.yml": RELEASE_TEXT}) == ({}, {})


def test_a_required_check_that_no_pull_request_workflow_reports_is_still_an_error() -> None:
    """A check the setting requires that no pull-request workflow reports — a renamed job, or
    the job of a workflow that does not run on pull requests — never arrives, and every pull
    request waits on it for ever. The sentence names the files it looked in."""
    mod = _load()
    gating, parts = mod.pull_request_contexts(WORKFLOW_TEXTS)
    required = [*gating, "publish (the tagged image)"]
    assert mod.compare(gating, required, strict=True, parts=parts) == [
        "branch protection requires 'publish (the tagged image)', which no job in ci.yml or "
        "commit-subjects.yml reports: every pull request waits on it for ever"
    ]


@pytest.mark.parametrize(
    ("on", "events"),
    [
        ("on: pull_request", ["pull_request"]),
        ("on: [push, pull_request]  # both", ["push", "pull_request"]),
        ('"on":\n  push:\n    branches: [main]\n  pull_request:', ["push", "pull_request"]),
        ("on:\n  # a comment\n  - push\n  - pull_request", ["push", "pull_request"]),
        (
            "on:\n    workflow_dispatch:\n    schedule:\n    - cron: '1 1 * * *'",
            ["workflow_dispatch", "schedule"],
        ),
        ("on:\n  \"push\":\n    branches: [main]\n  'pull_request':", ["push", "pull_request"]),
        ("on:\n  - \"push\"\n  - 'pull_request'  # pr", ["push", "pull_request"]),
        ("on:\n  push:\n# a column-0 comment\n  pull_request:", ["push", "pull_request"]),
        ("on: [push, pull_request,]\n---", ["push", "pull_request"]),
    ],
    ids=[
        "scalar",
        "flow-list",
        "quoted-block",
        "block-list",
        "four-space-block",
        "quoted-keys",
        "quoted-items",
        "column-0-comment",
        "trailing-comma-then-a-document-marker",
    ],
)
def test_the_trigger_scan_reads_each_form_of_on(on: str, events: list[str]) -> None:
    mod = _load()
    assert mod.triggers(f"name: x\n{on}\njobs:\n  a:\n    name: a\n") == events


@pytest.mark.parametrize(
    "on",
    [
        "",
        "on: {push: {}, pull_request: {}}",
        "on:\n",
        "on:\n  push:\n  ? pull_request\n",
        "on:\n  push:\n  <<: *triggers\n",
        "on:\n  - push\n  - pull_request: {}\n",
        "on: []",
        "on: push\n'on': pull_request",
        "on: [push,\n  pull_request]",
        "on: [push,\npull_request]",
        "on: [\n  push,\n  pull_request,\n  ]",
        "on: [push, [pull_request]]",
        "on: push\n  pull_request",
        "on:\n  push:\npull_request\n",
        "on: &t\n  push:\n  pull_request:",
        "on: &e pull_request",
        "on: *triggers",
        "on: >-\n  pull_request",
        "on: |-\n  pull_request",
        "on: !!str pull_request",
        'on: "pull_\\',
        "on: [push, &p pull_request]",
        "on: [push, !!str pull_request]",
        "on: [push, *p]",
        "on:\n  Push:",
    ],
    ids=[
        "no-on",
        "flow-mapping",
        "empty-block",
        "explicit-key",
        "merge-key",
        "mapping-item-in-a-list",
        "empty-flow-list",
        "two-ons",
        "flow-list-over-two-lines",
        "flow-list-continued-at-column-0",
        "flow-list-opened-alone",
        "nested-flow-list",
        "scalar-continued-below",
        "column-0-line-inside-a-block",
        "anchor-on-a-block",
        "anchor-on-a-scalar",
        "alias",
        "folded-scalar",
        "literal-scalar",
        "tag",
        "broken-quote",
        "anchored-item",
        "tagged-item",
        "alias-item",
        "not-an-event-name",
    ],
)
def test_an_on_the_scan_cannot_read_fails_closed_never_drops_the_workflow(on: str) -> None:
    """A workflow read as running on nothing would drop its jobs out of the comparison, and a
    setting that did not require them would pass. So would a block read in part: one event
    line the scan cannot read refuses the whole block, never the events around it."""
    mod = _load()
    with pytest.raises(SystemExit, match="could not read the workflow's top-level on:"):
        mod.pull_request_contexts({"x.yml": f"name: x\n{on}\njobs:\n  a:\n    name: a\n"})


def test_one_check_name_in_two_workflows_fails_closed() -> None:
    mod = _load()
    twin = SUBJECTS_TEXT.replace(SUBJECTS, "lint (ruff)")
    with pytest.raises(SystemExit, match=r"reported by both ci\.yml and twin\.yml"):
        mod.pull_request_contexts({"ci.yml": CI_TEXT, "twin.yml": twin})


def test_the_real_pull_request_workflows_are_found_by_reading_their_on() -> None:
    """No list kept by hand: each file under .github/workflows is read, and today ci.yml and
    commit-subjects.yml run on pull requests while the scheduled and release ones do not."""
    mod = _load()
    texts = mod.read_workflows(mod.default_workflows())
    on_pr = {name for name, text in texts.items() if mod.runs_on_pull_request(text)}
    assert on_pr == {"ci.yml", "commit-subjects.yml"}
    assert {"branch-protection.yml", "release.yml"} <= set(texts) - on_pr
    gating, _ = mod.pull_request_contexts(texts)
    assert gating[SUBJECTS] == "commit-subjects.yml" and gating[FRESH] == "ci.yml"


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
    assert sum(1 for c in parts if c.startswith("test shard (py")) == 18
    assert "walkthrough story (browser, live stack, tier 1)" in parts
    assert sum(1 for c in parts if c.startswith("walkthrough screens (")) == 4
    assert "fresh-clone gates (from uv.lock, as root, no docker daemon)" in parts
    assert sum(1 for c in parts if c.startswith("fresh-clone shard (")) == 9
    gating = mod.gating_contexts(ci)
    assert {
        "test (py3.12)",
        "test (py3.13)",
        "walkthrough (browser, live stack, tier 1)",
        FRESH,
    } <= set(gating)
    assert not set(gating) & set(parts)


def test_the_last_reading_of_the_setting_still_matches_the_workflow() -> None:
    """A job renamed or added in a pull-request workflow breaks the required-check list
    silently — the renamed check is never reported, and every pull request waits for ever.
    This fails first: read the setting again once the administrator has updated it, and save
    it in the fixture. The reading of 2026-10-07 requires all 18 — fresh-clone and
    commit-subjects included — so no job awaits the administrator."""
    mod = _load()
    reading = json.loads(READING.read_text(encoding="utf-8"))
    gating, parts = mod.pull_request_contexts(mod.read_workflows(mod.default_workflows()))
    errors, awaiting = mod.compare_reading(gating, reading, mod.open_gaps(), parts)
    assert errors == []
    assert len(reading["contexts"]) == 18
    assert {FRESH, SUBJECTS} <= set(reading["contexts"])
    assert "awaiting_protection" not in reading and awaiting == []


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
        "'gone' awaits branch protection, but no job in a pull-request workflow reports it"
    ]
    files = dict.fromkeys(jobs, "ci.yml")
    assert mod.compare_reading(files, ghost, gaps)[0] == [
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
    # the real record, read through dod_check's parser: G-930 is open (its token is not yet
    # provisioned) but its text names no job, so a job parked under it is refused
    live = mod.open_gaps()
    assert "BRANCH_PROTECTION_TOKEN" in live["G-930"]
    parked = {**base, "awaiting_protection": {"bare": "an administrator requires it (G-930)"}}
    assert mod.compare_reading(jobs, parked, live)[0] == [
        "'bare' awaits branch protection under G-930, which is not an open gap in docs/dod "
        "that names the job"
    ]


def test_main_compares_a_saved_reading_and_fails_on_any_difference(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = _load()
    assert mod.main(["--from-json", str(READING)]) == 0
    said = capsys.readouterr().out
    assert (
        "branch protection: 18 required checks match the jobs of ci.yml and commit-subjects.yml"
        in said
    )
    assert "awaits the administrator" not in said
    reading = json.loads(READING.read_text(encoding="utf-8"))
    reading["contexts"].remove(
        "dod (every route, journey and stream has its definition of done; evidence resolves)"
    )
    reading["contexts"].remove(SUBJECTS)
    edited = tmp_path / "reading.json"
    edited.write_text(json.dumps(reading), encoding="utf-8")
    assert mod.main(["--from-json", str(edited)]) == 1
    out = capsys.readouterr().out
    assert (
        "job 'dod (every route, journey and stream has its definition of done; evidence resolves)' in ci.yml runs on every pull request"
        in out
    )
    assert f"job {SUBJECTS!r} in commit-subjects.yml runs on every pull request" in out
    assert "2 difference(s)" in out


def test_main_takes_named_workflows_and_refuses_one_off_pull_requests(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--workflow`` (or its old name ``--ci``) narrows the comparison to the files named; a
    file named there that does not run on pull requests is refused, never read as gating."""
    mod = _load()
    flows = ROOT / ".github" / "workflows"
    assert mod.main(["--from-json", str(READING), "--ci", str(flows / "ci.yml")]) == 1
    assert (
        f"branch protection requires {SUBJECTS!r}, which no job in ci.yml reports"
        in capsys.readouterr().out
    )
    both = ["--workflow", str(flows / "ci.yml"), "--workflow", str(flows / "commit-subjects.yml")]
    assert mod.main(["--from-json", str(READING), *both]) == 0
    with pytest.raises(SystemExit, match=r"release\.yml does not run on pull_request"):
        mod.main(["--from-json", str(READING), "--workflow", str(flows / "release.yml")])


def test_two_named_workflows_with_one_file_name_fail_closed(tmp_path: Path) -> None:
    """Two ``--workflow`` paths with one file name would share one key, so the second would
    replace the first unread, and a job only the first runs would never be compared."""
    mod = _load()
    flows = ROOT / ".github" / "workflows"
    other = tmp_path / "ci.yml"
    other.write_text(SUBJECTS_TEXT, encoding="utf-8")
    with pytest.raises(SystemExit, match=r"two workflows are named ci\.yml") as refused:
        mod.read_workflows([flows / "ci.yml", other])
    assert str(flows / "ci.yml") in str(refused.value) and str(other) in str(refused.value)
    with pytest.raises(SystemExit, match=r"two workflows are named ci\.yml"):
        mod.main(
            ["--from-json", str(READING), "--workflow", str(flows / "ci.yml"), "--ci", str(other)]
        )


def test_the_scheduled_workflow_runs_the_live_comparison_and_fails_without_its_token() -> None:
    """The setting can only be read with a token allowed to read it (Administration: read),
    which the workflow's own GITHUB_TOKEN can never be granted. Without it the run is red —
    a comparison that silently passes would be the fabricated default this gate replaces."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "schedule:" in text and "workflow_dispatch:" in text
    # a push to main that changes any workflow re-reads the setting, not only one to ci.yml
    assert 'paths: [".github/workflows/**"]' in text
    assert "GH_TOKEN: ${{ secrets.BRANCH_PROTECTION_TOKEN }}" in text
    assert 'test -n "$GH_TOKEN"' in text
    assert "python scripts/check_branch_protection.py --repo" in text
    assert "continue-on-error" not in text
