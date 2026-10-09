"""Every CI job that talks to a docker daemon pulls Docker Hub images through mirror.gcr.io.

On 2026-10-09 Docker Hub refused GitHub's runners: run 37989331696 lost its docker jobs on
two attempts to ``429 Too Many Requests`` (the unauthenticated pull rate limit, which a
runner's shared address spends on whoever ran there before) and to 504s and timeouts from its
token endpoint, with no incident on its status page. Nothing had routed a pull anywhere else.
These tests hold every workflow to the mirror (P-783).

Navigation
----------
What it is:   The gate on how CI reaches Docker Hub.
What it does: Fails when a job in any workflow talks to a docker daemon — a ``docker``
              command in a ``run`` step, a ``docker/setup-buildx-action`` or
              ``docker/build-push-action`` step, or ``docker`` among the tools its
              ``CRB_TEST_REQUIRE_TOOLS`` declares — without the
              ``./.github/actions/docker-hub-mirror`` step before the first of them
              (jobs that stop the daemon are exempt); when a ``docker/setup-buildx-action``
              step does not give BuildKit the docker.io mirror; and when the composite
              action stops merging into the runner's ``daemon.json``, stops restarting the
              daemon or stops proving that ``docker info`` lists the mirror. Each check is
              also run on a planted regression so it cannot pass vacuously.
How:          PyYAML reads the workflows and the composite action, tomllib reads each
              ``buildkitd-config-inline``; a step's docker use is read from its text.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   .github/actions/docker-hub-mirror/action.yml (the step),
              .github/workflows/ci.yml and .github/workflows/release.yml (its users),
              docs/PREVENTION.md (P-783)
Tested by:    (this is a test file)
Touch when:   never for a new repository — client repositories are not built here; a job
              starts using docker; the mirror moves; Docker Hub is reached another way.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
ACTION = ROOT / ".github" / "actions" / "docker-hub-mirror" / "action.yml"
MIRROR_STEP = "./.github/actions/docker-hub-mirror"
MIRROR = "mirror.gcr.io"

# a docker command, not a word in a name (`docker.io`, `docker-compose.yml`, `crb-docker`)
_DOCKER_COMMAND = re.compile(r"(?<![\w./-])docker\s+(?![.-])[a-z]")
_STOPS_DAEMON = re.compile(r"systemctl\s+stop\s+[^\n]*\bdocker\b")
_PULLING_ACTIONS = ("docker/setup-buildx-action@", "docker/build-push-action@")


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in job.get("steps") or [] if isinstance(s, dict)]


def _requires_docker(job: dict[str, Any]) -> bool:
    tools = str((job.get("env") or {}).get("CRB_TEST_REQUIRE_TOOLS", ""))
    return "docker" in tools.split()


def _uses_docker(step: dict[str, Any], *, declared: bool) -> bool:
    uses = str(step.get("uses", ""))
    run = str(step.get("run", ""))
    # login-action and metadata-action reach no registry for an image; these two pull
    if uses.startswith(_PULLING_ACTIONS):
        return True
    if _DOCKER_COMMAND.search(run):
        return True
    # a job that declares docker runs it from its tests
    return declared and "pytest" in run


def job_findings(where: str, text: str) -> list[str]:
    """The jobs of one workflow that reach a docker daemon before the mirror step."""
    findings = []
    for name, job in (yaml.safe_load(text).get("jobs") or {}).items():
        steps = _steps(job)
        if any(_STOPS_DAEMON.search(str(s.get("run", ""))) for s in steps):
            continue
        declared = _requires_docker(job)
        first = next((i for i, s in enumerate(steps) if _uses_docker(s, declared=declared)), None)
        if first is None:
            continue
        mirror = next((i for i, s in enumerate(steps) if s.get("uses") == MIRROR_STEP), None)
        if mirror is None or mirror > first:
            findings.append(f"{where}: job {name!r} uses docker without {MIRROR_STEP} before it")
    return findings


def buildx_findings(where: str, text: str) -> list[str]:
    """The ``setup-buildx-action`` steps whose BuildKit is not given the docker.io mirror."""
    findings = []
    for name, job in (yaml.safe_load(text).get("jobs") or {}).items():
        for step in _steps(job):
            if not str(step.get("uses", "")).startswith("docker/setup-buildx-action"):
                continue
            config = str((step.get("with") or {}).get("buildkitd-config-inline", ""))
            try:
                registries = tomllib.loads(config).get("registry", {})
            except tomllib.TOMLDecodeError:
                registries = {}
            if MIRROR not in registries.get("docker.io", {}).get("mirrors", []):
                findings.append(f"{where}: job {name!r} builds without BuildKit's docker.io mirror")
    return findings


def action_findings(text: str) -> list[str]:
    """What the composite action must keep doing: merge, restart, prove."""
    action = yaml.safe_load(text)
    run = "\n".join(str(s.get("run", "")) for s in action["runs"]["steps"])
    findings = []
    if "https://" + MIRROR not in run:
        findings.append("the action does not name https://mirror.gcr.io")
    if not re.search(r'sudo cat "\$cfg"', run) or "jq" not in run:
        findings.append("the action does not merge into the runner's daemon.json")
    if not re.search(r"systemctl\s+restart\s+docker", run):
        findings.append("the action does not restart the daemon")
    proves = re.search(r"docker info --format '\{\{json \.RegistryConfig\.Mirrors\}\}'", run)
    if not proves or not re.search(r"\*\)[^\n]*exit 1", run):
        findings.append("the action does not fail unless docker info lists the mirror")
    return findings


def _all(text_of: dict[str, str]) -> list[str]:
    return [
        f
        for where, text in text_of.items()
        for f in job_findings(where, text) + buildx_findings(where, text)
    ]


def _real() -> dict[str, str]:
    return {w.name: w.read_text("utf-8") for w in WORKFLOWS}


def test_every_job_that_uses_docker_pulls_through_the_mirror() -> None:
    assert _all(_real()) == []
    # vacuity guard: the jobs this exists for are found and checked
    ci = _real()["ci.yml"]
    jobs = yaml.safe_load(ci)["jobs"]
    for name in ("test-shard", "sandbox-images", "container"):
        assert any(s.get("uses") == MIRROR_STEP for s in _steps(jobs[name])), name


def test_the_composite_action_merges_restarts_and_proves() -> None:
    assert action_findings(ACTION.read_text("utf-8")) == []


def _drop_nth(text: str, line: str, nth: int) -> str:
    """``text`` without the ``nth`` occurrence of ``line``."""
    start = -1
    for _ in range(nth + 1):
        start = text.index(line, start + 1)
    return text[:start] + text[start + len(line) :]


_MIRROR_LINE = f"      - uses: {MIRROR_STEP} # Docker Hub through mirror.gcr.io (P-783)\n"
_BUILDX_CONFIG = (
    "        with:\n"
    "          # BuildKit in this builder does not read the daemon's registry-mirrors (P-783)\n"
    "          buildkitd-config-inline: |\n"
    '            [registry."docker.io"]\n'
    '              mirrors = ["mirror.gcr.io"]\n'
)


@pytest.mark.parametrize(
    ("what", "nth", "job"),
    [
        ("test shards", 0, "test-shard"),
        ("container", 1, "container"),
        ("sandbox images", 2, "sandbox-images"),
    ],
)
def test_the_check_refuses_a_job_without_the_mirror(what: str, nth: int, job: str) -> None:
    ci = _real()["ci.yml"]
    planted = _drop_nth(ci, _MIRROR_LINE, nth)
    found = job_findings("ci.yml", planted)
    assert found == [f"ci.yml: job {job!r} uses docker without {MIRROR_STEP} before it"], what


def test_the_check_refuses_the_mirror_after_the_builder_starts() -> None:
    # restarting the daemon after setup-buildx-action would stop the builder's container
    release = _real()["release.yml"]
    buildx = "      - uses: docker/setup-buildx-action@v4\n" + _BUILDX_CONFIG
    assert _MIRROR_LINE + buildx in release
    planted = release.replace(_MIRROR_LINE + buildx, buildx + _MIRROR_LINE)
    assert job_findings("release.yml", planted) == [
        f"release.yml: job 'image' uses docker without {MIRROR_STEP} before it"
    ]


@pytest.mark.parametrize("nth", [0, 1])
def test_the_check_refuses_a_builder_without_the_mirror(nth: int) -> None:
    ci = _real()["ci.yml"]
    planted = _drop_nth(ci, _BUILDX_CONFIG, nth)
    assert len(buildx_findings("ci.yml", planted)) == 1


def test_the_check_refuses_a_builder_mirroring_another_registry() -> None:
    ci = _real()["ci.yml"]
    planted = ci.replace('[registry."docker.io"]', '[registry."ghcr.io"]', 1)
    assert len(buildx_findings("ci.yml", planted)) == 1


def test_the_check_finds_a_new_job_that_pulls() -> None:
    planted = (
        "on: pull_request\n"
        "jobs:\n"
        "  probe:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v7\n"
        "      - run: docker run --rm python:3.12-slim true\n"
        "  declared:\n"
        "    runs-on: ubuntu-latest\n"
        "    env:\n"
        '      CRB_TEST_REQUIRE_TOOLS: "go docker"\n'
        "    steps:\n"
        "      - uses: actions/checkout@v7\n"
        "      - run: .venv/bin/pytest -q\n"
        "  stopped:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: sudo systemctl stop docker.socket docker.service\n"
        "      - run: if docker info; then exit 1; fi\n"
        "  named:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo docker.io docker-compose.yml crb-docker\n"
        "  signs:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: docker/login-action@v4\n"
        "      - uses: docker/metadata-action@v6\n"
        "  builds:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: docker/build-push-action@v7\n"
    )
    assert job_findings("probe.yml", planted) == [
        f"probe.yml: job 'probe' uses docker without {MIRROR_STEP} before it",
        f"probe.yml: job 'declared' uses docker without {MIRROR_STEP} before it",
        f"probe.yml: job 'builds' uses docker without {MIRROR_STEP} before it",
    ]


@pytest.mark.parametrize(
    ("what", "old", "new"),
    [
        ("a clobbered daemon.json", 'current="$(sudo cat "$cfg")"', "current='{}'"),
        ("no restart", "sudo systemctl restart docker", "true"),
        ("no proof", "exit 1 ;;", ";;"),
        (
            "another mirror",
            "https://mirror.gcr.io",
            "https://registry.example.invalid",
        ),
    ],
)
def test_the_action_check_refuses_a_weakened_action(what: str, old: str, new: str) -> None:
    text = ACTION.read_text("utf-8")
    assert old in text, what
    assert action_findings(text.replace(old, new)) != [], what
