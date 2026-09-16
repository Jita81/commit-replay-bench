# syntax=docker/dockerfile:1.7
#
# Commit Replay Bench (crb) — the BUILDER image (ADR-0012, plan P5).
#
# What runs in it: one builder attempt — `claude -p …` (the Claude Code CLI) over a
# sealed export of the task's parent tree, and the builder's own test runs. It is NOT
# the product image (deploy/Dockerfile) and NOT the grader's sandbox image: the grader
# keeps running the repository's tests in the operator's per-repository `sandbox_image`.
#
# Build from the REPOSITORY ROOT, on top of the toolchain image the repository needs:
#
#     docker build -f deploy/Dockerfile.builder -t crb-builder:local .
#     docker build -f deploy/Dockerfile.builder -t crb-builder-go:local \
#         --build-arg BASE_IMAGE=<your go sandbox image> .
#
# then point the worker at it:  CRB_BUILDER__EXECUTOR=docker  CRB_BUILDER__IMAGE=crb-builder:local
#
# The worker never pulls: the image must be present in the host daemon's store.
#
# How the worker runs it (crb.builders.container.builder_run_args — asserted flag by flag
# in tests/test_builders_container.py; proven against a daemon in
# tests/test_builders_container_docker.py):
#
#     docker run --rm --name crb-build-<task>-<id> --init
#       --network=crb-b-<task>-<id>            (an --internal bridge shared with ONE sidecar: the
#                                               CONNECT-only egress proxy; `none` when no allowlist)
#       --memory=4g --cpus=2 --pids-limit=1024
#       --user=<worker uid>:<gid>              (root refused; the checkout stays writable without chmod)
#       --cap-drop=ALL --security-opt no-new-privileges --read-only
#       --tmpfs /tmp:rw,nosuid,nodev,size=1g   (HOME=/tmp: the CLI's config and cache live here and die here)
#       --mount type=bind,src=<sealed checkout>,dst=/work      (rw — the only writable path besides /tmp)
#       [--mount type=bind,src=<host>,dst=<inside>,readonly …] (toolchain caches; harness symlink targets)
#       --env ANTHROPIC_API_KEY  --env CLAUDE_CODE_OAUTH_TOKEN (NAME only: the value comes from the
#                                               docker client's environment, never from argv)
#       --env HTTPS_PROXY=http://proxy:3128 --env HOME=/tmp --env CI=1 --env NO_COLOR=1 …
#       --workdir /work --stop-timeout=<wall clock> crb-builder:local
#       claude -p <prompt> --output-format stream-json --bare … (or the agent's tool commands)
#
# The sidecar runs `python3 /opt/crb/egress_proxy.py --allow api.anthropic.com` from
# CRB_BUILDER__PROXY_IMAGE (default: this image — it only needs python3), the script
# bind-mounted read-only from the worker's own copy so the policy code is always the
# worker's version.
#
# Security posture (docs/SECURITY.md §3.2):
#   * The CLI is the npm package's NATIVE binary (a single executable linked against glibc
#     only — libc, libm, libdl, libpthread, librt; verified on 2.1.132 linux/arm64). No Node
#     runtime is installed: the base's toolchain is untouched. BASE_IMAGE must therefore be
#     glibc-based (Debian/Ubuntu family; a musl base needs the `-musl` variant — not wired).
#   * `git` and `ca-certificates` are added when apt-get exists; a base without apt must
#     already carry them (the CLI uses git; TLS to the model endpoint needs the CAs).
#   * The Claude Code CLI is pinned by exact version (CLAUDE_CODE_VERSION) — the same version
#     the adapter's argv was verified against (src/crb/builders/claude_code.py). Re-pin here
#     AND re-run the argv tests when moving it.
#   * Nothing secret is baked in; nothing listens; no docker client. The image is inert
#     without the worker's mounts and environment.

ARG BASE_IMAGE=python:3.12.11-slim-bookworm
ARG NODE_IMAGE=node:22.19.0-bookworm-slim
ARG CLAUDE_CODE_VERSION=2.1.132

# ---------------------------------------------------------------------------
# Stage 1 — resolve the pinned CLI once. The package's postinstall replaces
# bin/claude.exe with the native binary for this platform; that file is all we keep.
# ---------------------------------------------------------------------------
FROM ${NODE_IMAGE} AS claude-cli
ARG CLAUDE_CODE_VERSION
RUN set -eu; \
    npm install -g --no-audit --no-fund "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"; \
    bin=/usr/local/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe; \
    test -x "$bin"; \
    # a real native binary is > 100 MB; the placeholder wrapper is < 1 KB
    test "$(stat -c %s "$bin")" -gt 100000000; \
    install -m 0755 "$bin" /claude

# ---------------------------------------------------------------------------
# Stage 2 — the toolchain image + git + the CLI binary
# ---------------------------------------------------------------------------
FROM ${BASE_IMAGE} AS builder
ARG CLAUDE_CODE_VERSION

# hadolint ignore=DL3008
RUN set -eu; \
    if command -v apt-get >/dev/null 2>&1; then \
        apt-get update; \
        apt-get install -y --no-install-recommends git ca-certificates; \
        rm -rf /var/lib/apt/lists/*; \
    fi; \
    command -v git >/dev/null || { echo "BASE_IMAGE must provide git" >&2; exit 1; }

COPY --from=claude-cli /claude /usr/local/bin/claude

RUN set -eu; \
    mkdir -p /work; chmod 0755 /work; \
    HOME=/tmp claude --version | grep -F "${CLAUDE_CODE_VERSION}"

# The worker overrides --user, HOME and the proxy variables per run; these are the
# inert defaults so a stray `docker run` of this image is still non-root and quiet.
ENV HOME=/tmp \
    CI=1 \
    NO_COLOR=1 \
    DISABLE_AUTOUPDATER=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

WORKDIR /work
USER 65534:65534
ENTRYPOINT []
CMD ["claude", "--version"]
