"""The secrets scan's range — every commit a pull request adds, its head included.

``gitleaks/gitleaks-action@v3`` scanned one page of the API's commit list for a pull request: on
#74, run 37854206126 at ``0b788b13`` scanned ``87f8b4db^..2cf9df77``, 15 of the 558 non-merge
commits the pull request adds, and not its head (docs/PREVENTION.md P-773).
``scripts/ci_gitleaks.py`` names the range from the event; these tests read its ranges against
real git repositories, hold the CI job to calling it, and, where a gitleaks binary is installed,
scan a planted fake credential in the head of a long pull request.

Navigation
----------
What it is:   Tests of the security job's scan range and of the CI configuration that runs it.
What it does: Pins that a pull request's range is exactly the commits its head reaches and its
              base does not (a merge from the base in the middle included, the head included),
              and that the action's one-page range misses the head of the same pull request
              (the negative control); that a push, the schedule and a manual run scan all of
              ``HEAD``; that an unknown event or a pull request with no base or head is refused
              before anything runs; that every trigger of ``ci.yml`` has a range; that the scan
              is redacted, uses ``.gitleaks.toml`` and reports leaks and failures as errors;
              that the security job installs a pinned, checksum-verified scanner, runs this
              script with the pull request's base and head, and no longer reads the API.
How:          Builds throwaway repositories with ``git`` in ``tmp_path``; calls ``main`` with a
              recording runner; reads ``ci.yml`` as text, job by job.
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   scripts/ci_gitleaks.py (the wrapper), .github/workflows/ci.yml (the security job),
              .gitleaks.toml (the config the scan reads), docs/PREVENTION.md (P-773),
              tests/test_ci_job_budget.py (the job parser this mirrors)
Tested by:    (this is a test file)
Touch when:   never for a new repository (it reads this repository's own CI); ci.yml gains a
              trigger; the scanner's version or command line changes.
"""

from __future__ import annotations

import importlib.util
import io
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"
#: The commit list page gitleaks-action read: ``GET /pulls/{n}/commits`` with no ``per_page``.
API_PAGE = 30


def _wrapper() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "ci_gitleaks", ROOT / "scripts" / "ci_gitleaks.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ci_gitleaks = _wrapper()


# --- a pull request longer than one page ------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path, name: str, text: str = "") -> str:
    (repo / name).write_text(text or f"{name}\n")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", f"add {name}")
    return _git(repo, "rev-parse", "HEAD")


class _PullRequest:
    """``main`` with three commits, a branch of 41 (a merge from ``main`` at 21), ``main`` +2."""

    def __init__(self, repo: Path, head_text: str = "") -> None:
        self.repo = repo
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "ci@example.invalid")
        _git(repo, "config", "user.name", "ci")
        _git(repo, "config", "commit.gpgsign", "false")
        self.base_commits = [_commit(repo, f"base{i}.txt") for i in range(3)]
        _git(repo, "checkout", "-q", "-b", "pr")
        self.added = [_commit(repo, f"pr{i}.txt") for i in range(20)]
        _git(repo, "checkout", "-q", "main")
        self.base_commits += [_commit(repo, f"main{i}.txt") for i in range(2)]
        _git(repo, "checkout", "-q", "pr")
        _git(repo, "merge", "-q", "--no-ff", "-m", "merge main", "main")
        self.added.append(_git(repo, "rev-parse", "HEAD"))
        self.added += [_commit(repo, f"pr{i}.txt") for i in range(20, 39)]
        self.head = _commit(repo, "settings.py", head_text)
        self.added.append(self.head)
        self.base = self.base_commits[-1]

    def commits(self, *range_args: str) -> list[str]:
        out = _git(self.repo, "rev-list", *range_args)
        return out.split("\n") if out else []

    def action_page_range(self) -> list[str]:
        """What gitleaks-action scanned: its first page, ``--no-merges --first-parent``."""
        page = self.added[:API_PAGE]  # the API lists them oldest first
        return ["--no-merges", "--first-parent", f"{page[0]}^..{page[-1]}"]


def test_a_pull_requests_range_is_every_commit_it_adds_and_its_head(tmp_path: Path) -> None:
    pr = _PullRequest(tmp_path)
    range_ = ci_gitleaks.log_opts("pull_request", pr.base, pr.head)
    scanned = pr.commits(range_)
    assert len(pr.added) > API_PAGE
    assert sorted(scanned) == sorted(pr.added)
    assert pr.head in scanned
    assert not set(scanned) & set(pr.base_commits)


def test_the_actions_one_page_range_misses_the_head_of_a_long_pull_request(
    tmp_path: Path,
) -> None:
    # The negative control: the same pull request through the range the action used.
    pr = _PullRequest(tmp_path)
    scanned = pr.commits(*pr.action_page_range())
    assert pr.head not in scanned
    assert len(scanned) < len(pr.added) - 10


def test_a_push_the_schedule_and_a_manual_run_scan_everything_head_reaches(
    tmp_path: Path,
) -> None:
    # A push to main checks out main, and the clone also holds branches main does not reach.
    pr = _PullRequest(tmp_path)
    _git(tmp_path, "checkout", "-q", "main")
    for event in ("push", "schedule", "workflow_dispatch"):
        range_ = ci_gitleaks.log_opts(event, "", "")
        assert sorted(pr.commits(range_)) == sorted(pr.base_commits)
        assert pr.head not in pr.commits(range_)


@pytest.mark.parametrize(
    ("event", "base", "head"),
    [
        ("pull_request_target", "a" * 40, "b" * 40),
        ("merge_group", "", ""),
        ("", "", ""),
        ("pull_request", "", "b" * 40),
        ("pull_request", "a" * 40, ""),
    ],
)
def test_an_event_with_no_range_or_a_pull_request_without_its_commits_is_refused(
    event: str, base: str, head: str
) -> None:
    with pytest.raises(ValueError):
        ci_gitleaks.log_opts(event, base, head)
    calls: list[list[str]] = []
    out = io.StringIO()
    env = {"EVENT_NAME": event, "BASE_SHA": base, "HEAD_SHA": head}
    assert ci_gitleaks.main(env=env, run=_recording(calls, [0, 0]), out=out) == 1
    assert calls == []
    assert out.getvalue().startswith("::error::")


def _recording(calls: list[list[str]], codes: list[int]) -> Any:
    answers = iter(codes)

    def run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, next(answers), stdout="41\n", stderr="")

    return run


@pytest.mark.parametrize(
    ("code", "error"),
    [(0, None), (2, "::error::gitleaks found secrets"), (1, "::error::gitleaks did not complete")],
)
def test_the_scan_is_redacted_reads_the_config_and_reports_its_verdict(
    code: int, error: str | None
) -> None:
    calls: list[list[str]] = []
    out = io.StringIO()
    env = {
        "EVENT_NAME": "pull_request",
        "BASE_SHA": "a" * 40,
        "HEAD_SHA": "b" * 40,
        "GITLEAKS": "/opt/gitleaks",
    }
    assert ci_gitleaks.main(env=env, run=_recording(calls, [0, code]), out=out) == code
    count, scan = calls
    assert count == ["git", "rev-list", "--count", f"{'a' * 40}..{'b' * 40}"]
    assert scan[:2] == ["/opt/gitleaks", "git"]
    assert "--redact" in scan
    assert scan[scan.index("--config") + 1] == ".gitleaks.toml"
    assert scan[scan.index("--exit-code") + 1] == str(ci_gitleaks.EXIT_LEAKS)
    assert f"--log-opts={'a' * 40}..{'b' * 40}" in scan
    assert "pull_request: scanning 41 commits" in out.getvalue()
    if error is None:
        assert "::error::" not in out.getvalue()
    else:
        assert error in out.getvalue()


@pytest.mark.toolchain("gitleaks")
def test_a_credential_in_the_head_of_a_long_pull_request_fails_the_scan(tmp_path: Path) -> None:
    # A fake credential the default rules report, outside the tests/ path the config allowlists.
    fake = 'api_key = "Q7vT2mX9pL4wR8kZ3nB6cY1hJ5dF0sGa"\n'
    pr = _PullRequest(tmp_path, head_text=fake)
    shutil.copy(ROOT / ".gitleaks.toml", tmp_path / ".gitleaks.toml")

    def in_repo(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.run(cmd, cwd=tmp_path, **kw)

    out = io.StringIO()
    env = {
        "EVENT_NAME": "pull_request",
        "BASE_SHA": pr.base,
        "HEAD_SHA": pr.head,
        "GITLEAKS": "gitleaks",
    }
    assert ci_gitleaks.main(env=env, run=in_repo, out=out) == ci_gitleaks.EXIT_LEAKS
    # The action's page range scans the same repository clean: the credential is past page one.
    missed = subprocess.run(
        ["gitleaks", "git", "--no-banner", "--config", ".gitleaks.toml", "--exit-code", "2",
         f"--log-opts={' '.join(pr.action_page_range())}", "."],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert missed.returncode == 0


# --- the CI configuration ----------------------------------------------------------------------

_JOB_KEY = re.compile(r"^  ([A-Za-z0-9_-]+):\s*(?:#.*)?$")


def _jobs(text: str) -> dict[str, str]:
    """``{job_id: its text}`` for the workflow's ``jobs:`` block."""
    lines = text.split("\n")
    out: dict[str, list[str]] = {}
    current = ""
    for line in lines[lines.index("jobs:") + 1 :]:
        if line and not line.startswith(" ") and not line.startswith("#"):
            break
        m = _JOB_KEY.match(line)
        if m:
            current = m.group(1)
            out[current] = []
        elif current:
            out[current].append(line)
    return {job: "\n".join(body) for job, body in out.items()}


def _steps(job: str) -> list[str]:
    """Each step of a job as one text block (a step starts at ``      - ``)."""
    steps: list[list[str]] = []
    for line in job.split("\n")[job.split("\n").index("    steps:") + 1 :]:
        if line.startswith("      - "):
            steps.append([line])
        elif steps:
            steps[-1].append(line)
    return ["\n".join(s) for s in steps]


def _triggers(text: str) -> set[str]:
    """The event names under the workflow's top-level ``on:``."""
    lines = text.split("\n")
    events: set[str] = set()
    for line in lines[lines.index("on:") + 1 :]:
        if line and not line.startswith(" ") and not line.startswith("#"):
            break
        m = re.match(r"^  ([a-z_]+):", line)
        if m:
            events.add(m.group(1))
    return events


def _uncovered(text: str) -> set[str]:
    return _triggers(text) - ci_gitleaks.PULL_REQUEST_EVENTS - ci_gitleaks.FULL_HISTORY_EVENTS


def test_every_trigger_of_the_ci_workflow_has_a_scan_range() -> None:
    text = CI.read_text()
    assert {"push", "pull_request", "schedule", "workflow_dispatch"} <= _triggers(text)
    assert _uncovered(text) == set()
    # The negative control: a trigger the wrapper has no range for is caught.
    assert _uncovered(text.replace("\non:\n", "\non:\n  merge_group:\n", 1)) == {"merge_group"}


def test_the_security_job_runs_a_pinned_checked_scanner_over_the_pull_requests_range() -> None:
    for workflow in WORKFLOWS.glob("*.y*ml"):
        assert "gitleaks/gitleaks-action" not in workflow.read_text(), workflow.name
    job = _jobs(CI.read_text())["security"]
    assert "pull-requests:" not in job  # the API's commit list is no longer read
    steps = _steps(job)
    checkout = next(s for s in steps if "actions/checkout@" in s)
    assert re.search(r"fetch-depth:\s*0\b", checkout)
    install = next(i for i, s in enumerate(steps) if "gitleaks.tar.gz" in s)
    scan = next(i for i, s in enumerate(steps) if "scripts/ci_gitleaks.py" in s)
    assert steps.index(checkout) < install < scan

    version = re.search(r'GITLEAKS_VERSION:\s*"([0-9.]+)"', steps[install])
    assert version is not None
    assert re.search(r'GITLEAKS_SHA256:\s*"[0-9a-f]{64}"', steps[install])
    assert "releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_" in steps[install]
    assert "sha256sum --check" in steps[install]
    min_version = re.search(
        r'^minVersion = "([0-9.]+)"', (ROOT / ".gitleaks.toml").read_text(), re.M
    )
    assert min_version is not None
    as_tuple = lambda v: tuple(int(p) for p in v.split("."))  # noqa: E731
    assert as_tuple(min_version.group(1)) <= as_tuple(version.group(1))

    assert "GITLEAKS: ${{ runner.temp }}/gitleaks" in steps[scan]
    assert "EVENT_NAME: ${{ github.event_name }}" in steps[scan]
    assert "BASE_SHA: ${{ github.event.pull_request.base.sha }}" in steps[scan]
    assert "HEAD_SHA: ${{ github.event.pull_request.head.sha }}" in steps[scan]
