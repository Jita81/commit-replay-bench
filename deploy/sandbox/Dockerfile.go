# syntax=docker/dockerfile:1.7
#
# Commit Replay Bench (crb) — reference SANDBOX image: Go (`go test -json` runner).
#
# What runs in it: a repository's tests, one `docker run` per test command, driven by
# `crb.core.execution.DockerExecutor` (the grader's probe / qualify / grade path). It is NOT
# the product image (deploy/Dockerfile) and NOT the builder image (deploy/Dockerfile.builder).
#
# What it contains — the toolchain the `go` runner invokes, nothing else: the Go
# distribution (`go`, and `gofmt` for belt 5) copied out of the pinned official image onto
# a slim Debian base of the SAME release. The official `golang` image itself is not the
# runtime: it carries gcc, git and the buildpack toolchain (~1.2 GB on disk against
# ~477 MB here), none of which `go test` needs with CGO_ENABLED=0 — the runner's default.
# The runner pins GOTOOLCHAIN=local, so a module's `go` directive can never trigger a
# toolchain download inside the sandbox. A repository's module dependencies are NOT baked
# into any image: they are provisioned per task outside the test container and mounted
# read-only at /deps/gomod with GOPROXY=off (ADR-0019; deploy/sandbox/README.md §4). A
# repository that needs cgo adds gcc in a derived image (README §4.1).
#
# Build from deploy/sandbox:
#
#     docker build -f deploy/sandbox/Dockerfile.go -t crb-sandbox-go:local deploy/sandbox
#
# then select it per repository (`sandbox_image` on the RepoConfig) or as the deployment
# default: CRB_SANDBOX__IMAGE=crb-sandbox-go:local (Helm: config.CRB_SANDBOX__IMAGE).
# The worker never pulls: the image must be present in the host daemon's store.
#
# How the worker runs it (crb.core.execution.DockerExecutor.build_argv — asserted flag by
# flag in tests/test_execution.py; proven from inside against a daemon in
# tests/test_sandbox_images_docker.py):
#
#     docker run --rm --network=none --memory=2g --cpus=2 --pids-limit=512
#       --user=65534:65534 --cap-drop=ALL --security-opt no-new-privileges --read-only
#       --tmpfs /tmp:rw,exec,nosuid,nodev,size=512m   (exec: the Go runner declares
#         Command.exec_tmp — every other command's tmpfs is noexec)
#       --mount type=bind,src=<worktree>,dst=/src,readonly
#       --tmpfs /work:rw,exec,nosuid,nodev,size=1g,uid=65534,gid=65534,mode=0700
#       --mount type=bind,src=<sealed module cache>,dst=/deps/gomod,readonly   (ADR-0019)
#       --env GOMODCACHE=/deps/gomod --env GOPROXY=off --env GOSUMDB=off …
#       --env HOME=/tmp --env CI=1 --env NO_COLOR=1 --workdir /work
#       crb-sandbox-go:local /bin/sh -c '<tar /src into /work>; cd /work/$0 && exec "$@"' . \
#         go test -json ./…   (the tests run in a throwaway copy of the tree: ADR-0019 §7)
#
# Security posture (docs/SECURITY.md §3.1):
#   * Both bases are pinned BY DIGEST (the multi-arch index, so amd64 and arm64 resolve the
#     same bytes); a rebuild without editing a FROM line reproduces the same bytes. Re-pin
#     by editing the lines together (same Debian release) — deploy/sandbox/README.md §5.
#   * Runs as uid 65534 (nobody) by default; the worker passes --user=65534:65534 as well,
#     and DockerSettings refuses root at construction.
#   * Works with a read-only root: the build cache, the module cache and GOPATH all live
#     under the tmpfs /tmp the executor provides (the runner sets GOCACHE / GOMODCACHE to
#     the same places; the ENV below makes a stray `docker run` of the image behave alike).
#   * Nothing secret is baked in; nothing listens; no package manager is invoked at all;
#     no setuid/setgid binary — the base's su, mount, passwd and friends have the bits
#     stripped (inert anyway under --cap-drop=ALL and no-new-privileges; stripped so the
#     image needs neither to hold).

FROM golang:1.26.8-bookworm@sha256:a688600ca24f8a4d3ca77f95b0dd40704a9fc787c826660eb7ba0b641b8b175d AS toolchain

FROM debian:bookworm-slim@sha256:3783cc01769c7b2b1b83a5c5ad96c815348e28ed7da68e2e3687004faa906251

LABEL org.opencontainers.image.title="Commit Replay Bench sandbox: go" \
      org.opencontainers.image.description="Reference test sandbox: Go 1.26 + go test, uid 65534, read-only-root compatible" \
      org.opencontainers.image.vendor="Automated Agile" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/Jita81/commit-replay-bench" \
      org.opencontainers.image.documentation="https://github.com/Jita81/commit-replay-bench/blob/main/deploy/sandbox/README.md"

COPY --from=toolchain /usr/local/go /usr/local/go

ENV PATH="/usr/local/go/bin:${PATH}" \
    HOME=/tmp \
    GOPATH=/tmp/go \
    GOCACHE=/tmp/gocache \
    GOMODCACHE=/tmp/gomod \
    GOTOOLCHAIN=local \
    GOFLAGS=-mod=mod \
    CGO_ENABLED=0

# /work is the worktree mount point; the toolchain's own probe proves the copy is whole.
RUN set -eu; \
    find / -xdev -perm /6000 -type f -exec chmod a-s '{}' +; \
    mkdir -p /work; chmod 0755 /work; \
    go version; command -v gofmt >/dev/null

WORKDIR /work
USER 65534:65534
ENTRYPOINT []
CMD ["go", "version"]
