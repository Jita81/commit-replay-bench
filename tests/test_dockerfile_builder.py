"""The builder image builds on the Go sandbox image, and CI proves it every run (P-791).

deploy/README.md §9.1 documents the Go builder as ``deploy/Dockerfile.builder`` built with
``--build-arg BASE_IMAGE=<the Go sandbox image>``. The shipped Go sandbox image ends as
``USER 65534:65534`` (deploy/sandbox/Dockerfile.go), a stage inherits its base's user, and the
builder stage ran ``apt-get`` and ``chmod`` with no ``USER`` of its own, so the documented
build failed ("List directory /var/lib/apt/lists/partial is missing ... Permission denied").
Nothing built that combination: the ``sandbox-images`` job built the sandbox images, and the
sealed-builder suites ran on the python one.

Navigation
----------
What it is:   The check that the builder stage switches to root before it installs anything and
              still ends non-root, and that CI lints the builder Dockerfile and builds and runs
              its Go variant on the Go sandbox image the same job just built.
What it does: Reads ``deploy/Dockerfile.builder`` stage by stage: in the ``builder`` stage the
              first ``USER`` is root and comes before the first ``RUN``, and the last ``USER``
              is ``65534:65534``. Reads ``.github/workflows/ci.yml``'s ``sandbox-images`` job:
              a hadolint step on the builder Dockerfile at the pin the sandbox Dockerfiles use;
              after the Go sandbox build, a step that builds the builder on
              ``crb-sandbox-go:ci`` and runs it, asserting uid 65534 and the CLI version the
              Dockerfile pins.
How:          ``stage_instructions(text, stage)`` → ``[(instruction, argument)]`` with line
              continuations joined; ``ci.yml`` is parsed with PyYAML (a dev dependency); no
              docker command runs here (the CI step is the build).
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         docs/adr/0012-builder-in-a-sealed-container.md
Works with:   deploy/Dockerfile.builder (the image), deploy/sandbox/Dockerfile.go (the base that
              ends non-root), .github/workflows/ci.yml (the sandbox-images job),
              deploy/README.md (§9.1, the documented build), docs/PREVENTION.md (P-791)
Tested by:    (this is a test file)
Touch when:   never for a new repository; the builder Dockerfile's stages or users change; the
              sandbox-images job is restructured or renamed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
BUILDER = ROOT / "deploy" / "Dockerfile.builder"
GO_SANDBOX = ROOT / "deploy" / "sandbox" / "Dockerfile.go"
CI = ROOT / ".github" / "workflows" / "ci.yml"

_FROM = re.compile(r"^FROM\s+\S+(?:\s+AS\s+(\S+))?\s*$", re.IGNORECASE)
_ROOT_USERS = {"root", "0", "0:0", "root:root"}


def instructions(text: str) -> list[tuple[str, str]]:
    """Every instruction of a Dockerfile as ``(KEYWORD, argument)``: comments and blank lines
    dropped, backslash continuations joined."""
    out: list[tuple[str, str]] = []
    pending = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not pending and (not line or line.startswith("#")):
            continue
        if pending and line.startswith("#"):
            continue
        if line.endswith("\\"):
            pending += line[:-1].rstrip() + " "
            continue
        full = (pending + line).strip()
        pending = ""
        keyword, _, arg = full.partition(" ")
        out.append((keyword.upper(), arg.strip()))
    return out


def stage_instructions(text: str, stage: str) -> list[tuple[str, str]]:
    """The instructions of the stage named ``stage``, from its ``FROM`` to the next one."""
    out: list[tuple[str, str]] = []
    inside = False
    for keyword, arg in instructions(text):
        if keyword == "FROM":
            m = _FROM.match(f"FROM {arg}")
            inside = bool(m and m.group(1) == stage)
        if inside:
            out.append((keyword, arg))
    return out


def _sandbox_steps() -> list[dict[str, Any]]:
    workflow = yaml.safe_load(CI.read_text(encoding="utf-8"))
    steps: list[dict[str, Any]] = workflow["jobs"]["sandbox-images"]["steps"]
    return steps


def _go_sandbox_build_index(steps: list[dict[str, Any]]) -> int:
    for i, step in enumerate(steps):
        with_ = step.get("with") or {}
        if (
            with_.get("file") == "deploy/sandbox/Dockerfile.go"
            and with_.get("tags") == "crb-sandbox-go:ci"
        ):
            return i
    raise AssertionError("the sandbox-images job no longer builds crb-sandbox-go:ci")


def test_builder_stage_switches_to_root_before_apt_and_ends_as_65534() -> None:
    # The premise: the Go sandbox image a deployment builds on ends non-root.
    go_users = [arg for kw, arg in instructions(GO_SANDBOX.read_text("utf-8")) if kw == "USER"]
    assert go_users[-1] == "65534:65534"

    stage = stage_instructions(BUILDER.read_text("utf-8"), "builder")
    assert stage, "deploy/Dockerfile.builder has no stage named builder"
    keywords = [kw for kw, _ in stage]
    users = [(i, arg) for i, (kw, arg) in enumerate(stage) if kw == "USER"]
    first_run = keywords.index("RUN")
    assert "apt-get" in stage[first_run][1], "the first RUN of the stage is the apt install"
    assert users, "the builder stage sets no USER, so it runs as whatever its base ends as"
    first_user_at, first_user = users[0]
    assert first_user_at < first_run, "the stage must switch user before its first RUN"
    assert first_user in _ROOT_USERS, f"the install steps must run as root, not {first_user}"
    assert users[-1][1] == "65534:65534", "the image must still end non-root"
    # no RUN after the last USER switch runs as root
    assert all(kw != "RUN" for kw, _ in stage[users[-1][0] :])


def test_the_builder_dockerfile_is_linted_in_ci() -> None:
    steps = _sandbox_steps()
    pins = {
        (step.get("with") or {}).get("dockerfile"): step.get("uses")
        for step in steps
        if str(step.get("uses", "")).startswith("hadolint/hadolint-action@")
    }
    assert "deploy/Dockerfile.builder" in pins
    assert pins["deploy/Dockerfile.builder"] == pins["deploy/sandbox/Dockerfile.go"]


def test_sandbox_images_builds_and_smokes_the_go_builder_on_the_go_sandbox() -> None:
    steps = _sandbox_steps()
    go_at = _go_sandbox_build_index(steps)
    builds = [
        i
        for i, step in enumerate(steps)
        if "-f deploy/Dockerfile.builder" in str(step.get("run", ""))
    ]
    assert builds, "no step builds deploy/Dockerfile.builder"
    at = builds[0]
    assert at > go_at, "the builder must be built after the Go sandbox image it builds on"
    run = " ".join(str(steps[at]["run"]).split())
    assert "--build-arg BASE_IMAGE=crb-sandbox-go:ci" in run
    # the daemon's own builder: the docker-container builder cannot see a loaded image
    assert "--builder default" in run and "--load" in run
    assert "set -euo pipefail" in run
    # it runs as uid 65534, and answers with the CLI version the Dockerfile pins
    assert re.search(r'crb-builder-go:ci id -u\)" = "65534"', run)
    assert "s/^ARG CLAUDE_CODE_VERSION=//p' deploy/Dockerfile.builder" in run
    assert 'grep -F "$want"' in run
    pinned = re.search(r"^ARG CLAUDE_CODE_VERSION=(\S+)$", BUILDER.read_text("utf-8"), re.M)
    assert pinned and pinned.group(1)


def test_the_instruction_reader_joins_continuations_and_finds_a_stage() -> None:
    """The reader cannot pass vacuously: a stage with no USER is seen as one."""
    text = (
        "FROM a AS one\nUSER 0:0\n\nFROM ${B} AS builder\n# c\n"
        "RUN set -eu; \\\n    apt-get update\nUSER 65534:65534\n"
    )
    assert stage_instructions(text, "builder") == [
        ("FROM", "${B} AS builder"),
        ("RUN", "set -eu; apt-get update"),
        ("USER", "65534:65534"),
    ]
    assert stage_instructions(text, "missing") == []
