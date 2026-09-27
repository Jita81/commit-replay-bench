"""The job-budget guard, and the CI jobs it guards — a job says so before it creeps to its timeout.

PR #57's required walkthrough was cancelled at its 40-minute budget twice with every spec so far
passing, and its py3.13 test job ran 58 of 60 minutes: a job that grows with the product
reaches its timeout without anyone deciding it should, and then blocks every merge
(docs/PREVENTION.md P-051). ``scripts/ci_job_budget.py`` makes the creep visible at 80 %, and
the walkthrough was split so each part finishes well inside its budget.

Navigation
----------
What it is:   Tests of the job-budget guard and of the CI configuration that runs it and the
              split tier-1 walkthrough.
What it does: Pins the guard's arithmetic, its summary and annotation, its exit codes (fail
              mode exits 1 past the threshold, warn mode 0, a missing start stamp 2 in either
              mode), and that ``ci.yml`` starts the clock as the first step of the ``test``,
              ``walkthrough`` and ``walkthrough-screens`` jobs and runs the guard last,
              ``if: always()``, with the job's OWN ``timeout-minutes`` (so a raised timeout
              cannot leave the guard measuring the old one) — failing for the walkthroughs.
              For the split: the required ``walkthrough`` job keeps its exact name and runs
              every spec except 11-screens, ``walkthrough-screens`` runs only 11-screens with a
              shard per matrix value ``k/N`` for k = 1..N, and N is at most the spec's persona
              count, so no shard is empty and together they are every persona.
How:          Calls ``main`` with a fake clock and environment; reads ``ci.yml`` as text,
              job by job (no YAML dependency), and the spec's ``PERSONAS`` list.
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   scripts/ci_job_budget.py (the guard), .github/workflows/ci.yml (the jobs),
              ui/e2e/walkthrough/11-screens.spec.ts (the shard selection it reads),
              docs/PREVENTION.md (P-051)
Tested by:    (this is a test file)
Touch when:   never for a new repository (it reads this repository's own CI); a long CI job
              is added (start its clock and add it to ``GUARDED``); the walkthrough is split
              differently.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
CI = ROOT / ".github" / "workflows" / "ci.yml"
SCREENS_SPEC = ROOT / "ui" / "e2e" / "walkthrough" / "11-screens.spec.ts"
WALKTHROUGH_DIR = ROOT / "ui" / "e2e" / "walkthrough"

#: job id → the mode its guard must run in. The walkthroughs fail; the test job warns until
#: the suite is split (G-708) — it already runs past the threshold.
GUARDED = {"test": "warn", "walkthrough": "fail", "walkthrough-screens": "fail"}
#: The required context's exact name: branch protection matches it character for character.
REQUIRED_WALKTHROUGH_NAME = "walkthrough (browser, live stack, tier 1)"


def _guard() -> ModuleType:
    if "ci_job_budget" in sys.modules:
        return sys.modules["ci_job_budget"]
    spec = importlib.util.spec_from_file_location(
        "ci_job_budget", ROOT / "scripts" / "ci_job_budget.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ci_job_budget"] = mod
    spec.loader.exec_module(mod)
    return mod


# --- the guard ------------------------------------------------------------------------------


def test_a_job_under_the_threshold_passes_and_records_its_time(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    summary = tmp_path / "summary.md"
    env = {"CRB_JOB_STARTED_AT": "1000", "GITHUB_STEP_SUMMARY": str(summary), "GITHUB_JOB": "w"}
    rc = _guard().main(["--timeout-minutes", "40", "--mode", "fail"], env, now=1000 + 12 * 60)
    assert rc == 0
    text = summary.read_text("utf-8")
    assert "12.0 of 40 min" in text
    assert "30%" in text
    assert "OVER BUDGET" not in text
    assert "::error" not in capsys.readouterr().out


def test_fail_mode_fails_a_job_past_80_percent_with_an_alarm_and_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    summary = tmp_path / "summary.md"
    env = {"CRB_JOB_STARTED_AT": "0", "GITHUB_STEP_SUMMARY": str(summary), "GITHUB_JOB": "w"}
    rc = _guard().main(["--timeout-minutes", "40", "--mode", "fail"], env, now=33 * 60)
    assert rc == 1
    text = summary.read_text("utf-8")
    assert text.startswith("## OVER BUDGET — `w`: 33.0 of 40 min (82%")
    assert "FAILS" in text
    assert "never raise `timeout-minutes`" in text
    out = capsys.readouterr().out
    assert "::error title=job budget::w used 82% of its 40-minute timeout" in out


def test_warn_mode_passes_past_the_threshold_but_says_so_unmissably(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    summary = tmp_path / "summary.md"
    env = {"CRB_JOB_STARTED_AT": "0", "GITHUB_STEP_SUMMARY": str(summary), "GITHUB_JOB": "test"}
    rc = _guard().main(["--timeout-minutes", "60", "--mode", "warn"], env, now=58 * 60)
    assert rc == 0
    assert "## OVER BUDGET — `test`: 58.0 of 60 min (97%" in summary.read_text("utf-8")
    assert "::warning title=job budget::test used 97%" in capsys.readouterr().out


def test_exactly_at_the_threshold_is_over_budget() -> None:
    budget = _guard().assess(32 * 60, 40)
    assert budget.share == pytest.approx(0.8)
    assert budget.over


@pytest.mark.parametrize("stamp", ["", "not-a-number", None])
@pytest.mark.parametrize("mode", ["fail", "warn"])
def test_a_guard_that_cannot_measure_never_reads_as_a_pass(
    stamp: str | None, mode: str, capsys: pytest.CaptureFixture[str]
) -> None:
    env = {} if stamp is None else {"CRB_JOB_STARTED_AT": stamp}
    rc = _guard().main(["--timeout-minutes", "40", "--mode", mode], env, now=100.0)
    assert rc == 2
    assert "::error title=job budget::CRB_JOB_STARTED_AT is not set" in capsys.readouterr().out


def test_a_start_stamp_in_the_future_or_a_nonsense_budget_is_refused() -> None:
    guard = _guard()
    assert (
        guard.main(
            ["--timeout-minutes", "40", "--mode", "warn"], {"CRB_JOB_STARTED_AT": "500"}, now=100.0
        )
        == 2
    )
    with pytest.raises(ValueError, match="positive"):
        guard.assess(10, 0)
    with pytest.raises(ValueError, match="threshold"):
        guard.assess(10, 40, threshold=1.5)


# --- the CI configuration ----------------------------------------------------------------------

_JOB_KEY = re.compile(r"^  ([A-Za-z0-9_-]+):\s*(?:#.*)?$")


def _jobs(text: str) -> dict[str, list[str]]:
    """``{job_id: its lines}`` for the workflow's ``jobs:`` block."""
    lines = text.split("\n")
    start = lines.index("jobs:")
    out: dict[str, list[str]] = {}
    current = ""
    for line in lines[start + 1 :]:
        if line and not line.startswith(" ") and not line.startswith("#"):
            break
        m = _JOB_KEY.match(line)
        if m:
            current = m.group(1)
            out[current] = []
        elif current:
            out[current].append(line)
    return out


def _steps(body: list[str]) -> list[str]:
    """Each step of a job as one text block (a step starts at ``      - ``)."""
    steps: list[list[str]] = []
    in_steps = False
    for line in body:
        if line.rstrip() == "    steps:":
            in_steps = True
            continue
        if not in_steps:
            continue
        if line.startswith("      - "):
            steps.append([line])
        elif steps:
            steps[-1].append(line)
    return ["\n".join(s) for s in steps]


def _timeout(body: list[str]) -> int:
    m = next(
        re.match(r"^    timeout-minutes:\s*(\d+)", ln) for ln in body if "timeout-minutes" in ln
    )
    assert m is not None
    return int(m.group(1))


def test_each_guarded_job_starts_the_clock_first_and_ends_with_the_guard_on_its_timeout() -> None:
    jobs = _jobs(CI.read_text("utf-8"))
    for job, mode in GUARDED.items():
        assert job in jobs, f"{job}: no such job in ci.yml"
        steps = _steps(jobs[job])
        assert 'echo "CRB_JOB_STARTED_AT=$(date +%s)" >> "$GITHUB_ENV"' in steps[0], (
            f"{job}: the first step must start the job-budget clock"
        )
        last = steps[-1]
        assert "scripts/ci_job_budget.py" in last, f"{job}: the last step must be the guard"
        assert re.search(r"^\s+if: always\(\)\s*$", last, re.M), (
            f"{job}: the guard must run always()"
        )
        minutes = re.search(r"--timeout-minutes (\d+)", last)
        assert minutes is not None
        assert int(minutes.group(1)) == _timeout(jobs[job]), (
            f"{job}: the guard measures {minutes.group(1)} min but the job's timeout-minutes is "
            f"{_timeout(jobs[job])} — keep them equal"
        )
        assert f"--mode {mode}" in last, f"{job}: the guard must run in {mode} mode"
        assert sum("ci_job_budget.py" in s for s in steps) == 1


def test_the_required_walkthrough_keeps_its_name_and_runs_every_spec_but_11_screens() -> None:
    jobs = _jobs(CI.read_text("utf-8"))
    body = "\n".join(jobs["walkthrough"])
    assert f"    name: {REQUIRED_WALKTHROUGH_NAME}\n" in body + "\n"
    runs = [s for s in _steps(jobs["walkthrough"]) if "scripts/walkthrough.sh" in s]
    assert len(runs) == 1
    # the only filter is the one exclusion: a spec added later runs in the required job
    assert re.search(
        r"run: scripts/walkthrough\.sh --grep-invert '11-screens\\\.spec\\\.ts'\s*$", runs[0], re.M
    )


def test_the_screens_jobs_run_only_11_screens_one_shard_each_and_together_every_persona() -> None:
    jobs = _jobs(CI.read_text("utf-8"))
    body = jobs["walkthrough-screens"]
    shards_line = next(ln for ln in body if re.match(r"^\s+shard:\s*\[", ln))
    shards = [int(v) for v in re.findall(r"\d+", shards_line)]
    runs = [s for s in _steps(body) if "scripts/walkthrough.sh" in s]
    assert len(runs) == 1
    assert re.search(
        r"run: scripts/walkthrough\.sh e2e/walkthrough/11-screens\.spec\.ts\s*$", runs[0], re.M
    )
    env = re.search(r"CRB_E2E_SCREENS_SHARD: \$\{\{ matrix\.shard \}\}/(\d+)", runs[0])
    assert env is not None, "each shard must say which of N it is"
    n = int(env.group(1))
    assert shards == list(range(1, n + 1)), f"the matrix must list every shard 1..{n}, got {shards}"
    name = next(ln for ln in body if ln.startswith("    name:"))
    assert f"of {n})" in name, "the job name must state the same shard count"
    personas = re.search(r"const PERSONAS = \[([^\]]*)\]", SCREENS_SPEC.read_text("utf-8"))
    assert personas is not None
    count = len(re.findall(r"'[a-z]+'", personas.group(1)))
    assert 1 <= n <= count, f"{n} shards over {count} personas would leave a shard with no persona"


def test_every_walkthrough_spec_runs_in_exactly_one_of_the_split_jobs() -> None:
    """The required job excludes 11-screens by file name and the screens jobs name it alone,
    so the union is the directory and the intersection is empty — whatever is added later."""
    specs = sorted(p.name for p in WALKTHROUGH_DIR.glob("*.spec.ts"))
    excluded = re.compile(r"11-screens\.spec\.ts")
    story = [s for s in specs if not excluded.search(f"e2e/walkthrough/{s}")]
    screens = [s for s in specs if s == "11-screens.spec.ts"]
    assert screens == ["11-screens.spec.ts"]
    assert sorted(story + screens) == specs
    assert not set(story) & set(screens)
