# Reference sandbox images

The images the worker runs a repository's tests in — one hardened container per test
command, driven by `crb.core.execution.DockerExecutor` (`--network=none --read-only
--cap-drop=ALL --user 65534:65534`, [ADR-0005](../../docs/adr/0005-fail-closed-docker-sandbox.md),
[SECURITY.md §3.1](../../docs/SECURITY.md#31-sandboxed-test-execution--crbcoreexecutiondockerexecutor)).
Until 2026-09-21 the honest answer to "what do I run?" was "build one yourself"; this
directory is the answer now: three Dockerfiles, built and proven on every pull request by
CI's `sandbox-images` job, which runs each language's fixture repository through the real
executor on the image it just built (`tests/test_sandbox_images_docker.py`).

Contents: [1 What ships](#1-what-ships) · [2 Build, tag, push](#2-build-tag-and-push-to-a-private-registry) ·
[3 Select an image](#3-select-an-image) · [4 Extend an image](#4-extend-an-image-a-repositorys-dependencies-another-toolchain) ·
[5 Rebuild cadence and the digest rule](#5-rebuild-cadence-and-the-digest-pinning-rule) · [6 Not shipped](#6-what-is-not-shipped-and-why)

## 1. What ships

| Image | Dockerfile | Base (pinned by digest) | Contains | Runners it serves | Size (compressed / on disk) |
|---|---|---|---|---|---|
| `crb-sandbox-python` | [`Dockerfile.python`](Dockerfile.python) | `python:3.12.11-slim-bookworm` | CPython 3.12; `pytest` 9.1.1 and its four dependencies at exact versions with sha256 hashes ([`python-requirements.txt`](python-requirements.txt), `pip install --require-hashes`) | `pytest` | 49 MB / 231 MB |
| `crb-sandbox-node` | [`Dockerfile.node`](Dockerfile.node) | `node:22.19.0-bookworm-slim` | Node.js 22.19.0 (`node --test`, the JUnit reporter) and the base's npm; npm's cache, update check, fund and audit pointed at `/tmp` or off | `node`; `vitest` / `jest` / `mocha` when the repository's `node_modules` is visible (§4) | 79 MB / 344 MB |
| `crb-sandbox-go` | [`Dockerfile.go`](Dockerfile.go) | `golang:1.26.8-bookworm` (toolchain stage) onto `debian:bookworm-slim` | Go 1.26.8 (`go`, `gofmt`) copied onto a slim base of the same Debian release — no gcc, no git (the official `golang` image is 1.2 GB on disk; `go test` with `CGO_ENABLED=0`, the runner's default, needs none of it) | `go` | 92 MB / 477 MB |

Every image, in the same shape ([`Dockerfile.builder`](../Dockerfile.builder) is the house
style): `FROM <image>:<tag>@sha256:<digest>` — the **multi-arch index** digest, so the
same line resolves the same bytes on `linux/amd64` (CI, AKS) and `linux/arm64` (a developer
on colima); `USER 65534:65534` (nobody) as the default, and `DockerSettings` refuses root
at construction regardless; `/work` present for the worktree mount; `HOME=/tmp` and every
toolchain cache under `/tmp` — the tmpfs the executor provides — so the image runs with a
read-only root; `org.opencontainers.image.{title,description,vendor,licenses,source,documentation}`
labels; `ENTRYPOINT []` and a `CMD` that prints the toolchain's version; nothing that
listens, nothing secret, no package manager invoked after the one pinned install; no
setuid/setgid file — the Debian bases ship `su`, `mount`, `passwd`, `gpasswd`, `chsh`,
`chfn`, `newgrp`, `chage`, `expiry`, `umount` and `unix_chkpwd` with the bits set, and each
Dockerfile's `RUN` strips them (`find / -xdev -perm /6000 -type f -exec chmod a-s`) — inert
under the executor anyway (`--cap-drop=ALL`, `no-new-privileges`, uid 65534), stripped so the
image depends on neither flag **[measured — 11 files per image before, 0 after, read from
inside as uid 65534, 3/3 images, 2026-09-22]**; hadolint
clean (CI runs `hadolint/hadolint-action` on each file, as it does on `deploy/Dockerfile`).

What CI proves on each image, from inside, on every pull request
(`tests/test_sandbox_images_docker.py`, ten tests per language): the image's own default
user and the executor's user are uid 65534; `/usr` and the worktree at `/work` refuse a write
(`Read-only file system`) and nothing reaches the host, while `/tmp` accepts one; no
setuid/setgid file is in the image; `/tmp` is `noexec` for every command but the Go runner's
(`/proc/mounts` says so and a script written there is refused / runs accordingly); a test that
asserts `example.com:443` is reachable **fails** through that language's runner, attributed
to exactly that test id; an image absent from the daemon's store is `SandboxUnavailable`
rather than a pull (the daemon's `No such image`, not its `pull access denied`); the language's fixture repository qualifies (RED at the parent, gold
clean) and grades clean with the same baseline reading the host runner suite pins, leaving
the host worktree untouched; the OCI labels and `USER` are set **[measured — 10 tests × 3
images in `tests/test_sandbox_images_docker.py`, run as the CI `sandbox-images` job's smoke
step on images built from the tree: 47 passed / 0 skipped locally (colima, Docker 29.5.2,
2026-09-22) and 44 passed / 0 skipped in CI on PR #44 run 35678358686, head 4a64fe3;
apparatus 2.2]**. The sandbox suite and the
sealed-builder suite (`tests/test_sandbox_docker.py`, `tests/test_builders_container_docker.py`)
also run on the python image in that job, so the kill path, the sidecar and the copy-back
are proven on the shipped bytes too.

## 2. Build, tag and push to a private registry

Build from `deploy/sandbox` (the context holds only the requirements file); the digest
pins mean a build on any machine with the same Dockerfile produces the same base layers:

```bash
cd commit-replay-bench
for lang in python node go; do
  docker build -f "deploy/sandbox/Dockerfile.${lang}" -t "crb-sandbox-${lang}:local" deploy/sandbox
done
docker run --rm crb-sandbox-python:local            # pytest 9.1.1, as uid 65534
```

For a cluster or a fleet of workers, push to **your** private registry under a date tag
and record the **digest** — that is what `CRB_SANDBOX__IMAGE` / `sandbox_image` should
name in production, exactly as `image.digest` pins the product image:

```bash
REG=<acr>.azurecr.io/crb-sandbox     # or ghcr.io/<org>/crb-sandbox, a Harbor project, …
TAG=$(date +%Y-%m)                   # 2026-09: the month the bases were re-pinned
for lang in python node go; do
  docker buildx build --platform linux/amd64 \
    -f "deploy/sandbox/Dockerfile.${lang}" -t "${REG}/${lang}:${TAG}" --push deploy/sandbox
  docker buildx imagetools inspect "${REG}/${lang}:${TAG}" --format '{{.Manifest.Digest}}'
done
```

`--platform linux/amd64` builds the worker node's architecture from an arm64 laptop (the
index digests resolve it). Sign them with cosign if your registry policy asks for it — the
worker does not verify signatures itself; the registry admission policy or the node's
runtime does. Multi-arch (`--platform linux/amd64,linux/arm64`) works unchanged.

**The worker never pulls.** Each image must already be in the store of the daemon the
worker talks to:

* compose / a single host: `docker pull <ref>` on the host (or `docker save | docker load`
  on an air-gapped one — compare `docker image inspect --format '{{.Id}}'` before and after,
  the image ID survives a save/load, the registry digest does not);
* Helm `worker.sandbox.mode: dind`: the sidecar's store is an emptyDir — pre-pull with an
  init step or let the first `crb repo probe` fail closed, pull, and probe again; allow the
  registry in `networkPolicy.extraEgress` ([DEPLOYMENT.md §3.1](../../docs/DEPLOYMENT.md#31-install));
* `hostSocket`: the node's store — pull on the node.

`crb repo probe <repo>` (or *Probe* on the Repos screen) is the proof: it runs the
repository's probe scope inside the image. An absent image is `sandbox unavailable` with
the daemon's reason (`docker run --pull=never` → exit 125, `No such image`) — the run stops;
nothing is pulled and nothing runs on the host ([OPERATOR.md §7](../../docs/OPERATOR.md#7-when-the-sandbox-is-unavailable)).

## 3. Select an image

Two settings, one rule — **the repository's own image wins; the deployment's is the
default for a repository that names none** (`crb.server.worker.docker_settings_for`):

| Where | Key | Meaning |
|---|---|---|
| per repository | `sandbox_image` on the `RepoConfig` — `crb repo add … --sandbox-image <ref>`, the *Sandbox image* field on the Repos screen, `PUT /repos/{name}` | the image THIS repository's tests run in; choose the reference image of its toolchain, or your extension of it (§4) |
| per deployment | `CRB_SANDBOX__IMAGE` — `deploy/.env` (compose), `config.CRB_SANDBOX__IMAGE` in Helm values, or the worker flag `crb worker --image` | the default when a repository config has none; **one toolchain only** — a Go repository left on a python default fails its probe (`go: not found` in the tail), never silently passes |
| per deployment | `CRB_SANDBOX__EXECUTOR` — `docker` (default, fail-closed) or `local` (development) | read by the API (`/settings`, `/health`) **and by the worker** (`crb worker`; also `--executor`). Until 2026-09-21 the worker read only its short form `CRB_EXECUTOR` and a compose / Helm worker ran `local` while `/settings` reported `docker` — fixed with this directory; the short forms still work when the deployment keys are absent |
| per run | `image` in the run's params (`POST /runs`) | an explicit override for one run (a canary of a re-pinned image) |

Helm values, naming the shipped python image pushed to a private ACR:

```yaml
config:
  CRB_SANDBOX__EXECUTOR: docker
  CRB_SANDBOX__IMAGE: <acr>.azurecr.io/crb-sandbox/python@sha256:<digest from §2>
worker:
  sandbox: { mode: dind }
```

and a Go repository on the same worker names its own:

```bash
crb repo add cobra --url https://github.com/<org>/cobra.git --language go --runner go \
  --sandbox-image <acr>.azurecr.io/crb-sandbox/go@sha256:<digest>
crb repo probe cobra
```

## 4. Extend an image: a repository's dependencies, another toolchain

The reference images carry the toolchain and the test runner and **nothing else**. Under
the docker executor `crb repo setup` does not run — setup is a host phase; the sandbox has
no network — so a repository whose tests need more than the runner needs an image that
already contains it ([OPERATOR.md §2.1](../../docs/OPERATOR.md#21-environment-setup--the-only-network-phase)).
Extend the reference image; never loosen it:

**Python** — the repository's test dependencies, hash-pinned like the base's pytest
(the worktree is on `PYTHONPATH` at `/work`, so the repository itself is never installed):

```dockerfile
# syntax=docker/dockerfile:1.7
FROM <acr>.azurecr.io/crb-sandbox/python@sha256:<digest>
USER 0
COPY requirements-test.txt /opt/crb/requirements-test.txt      # uv pip compile --generate-hashes …
RUN pip install --no-cache-dir --require-hashes --root-user-action=ignore -r /opt/crb/requirements-test.txt
USER 65534:65534
```

Add `ruff==<the version the repository pins>` there when the repository configures ruff:
belt 5 runs the image's `ruff` under docker and fails closed (a visible harness error, never
a silent skip) when it is absent.

**Node** — `vitest` / `jest` / `mocha` and the repository's devDependencies resolve from
`node_modules` (`NODE_PATH=/work/node_modules`; the tool binary from `PATH` under docker).
A trial worktree's `node_modules` is a symlink to the host clone's (`crb repo setup` runs
`npm ci` there), which the container cannot follow — the probe runs in the clone itself and
sees a real directory, a grade does not — so bake it: `COPY package.json
package-lock.json /opt/app/` + `npm ci --ignore-scripts --prefix /opt/app` in a derived
image, `ENV PATH=/opt/app/node_modules/.bin:$PATH`, and `runner_opts.env:
{NODE_PATH: /opt/app/node_modules}` on the repository (it overrides the runner's default).
Native modules need their build dependencies in the image at `npm ci` time only.
`DockerSettings.extra_ro_mounts` can expose a host directory read-only instead, but no
deployment key sets it for the test sandbox yet — programmatic use only.

**Go** — modules: `go mod download` into a directory the image keeps (`/opt/gomod`, or a
host directory exposed through `extra_ro_mounts`) and set `runner_opts.gomodcache:
/opt/gomod`; the runner passes it as `GOMODCACHE`. Commit a complete `go.sum` — the
worktree is read-only, so a module the sum file does not cover fails the build, attributed
to the trial. cgo: `apt-get install gcc libc6-dev` in the derived image and
`runner_opts.cgo: "1"`. Note the runner sets
`Command.exec_tmp` — the sandbox's tmpfs is mounted `exec` for Go alone (every other
command's is `noexec`), because `go test` compiles each test binary under `/tmp` and runs
it; `nosuid,nodev` still hold.

**Another toolchain** (JVM, Rust) — copy the shape: a digest-pinned base, the toolchain and
the runner only, caches under `/tmp`, `USER 65534:65534`, the labels; then add the
language to `tests/conftest_langs.py::SHIPPED_SANDBOX_LANGS`, its fixture, net probe and
expected baseline to `tests/test_sandbox_images_docker.py`, and a hadolint + build step to
the `sandbox-images` job in `.github/workflows/ci.yml`. The suite refuses a language with no
image and an image with no suite (`assert tuple(_LANGS) == SHIPPED_SANDBOX_LANGS`).

## 5. Rebuild cadence and the digest-pinning rule

* **Every `FROM` is `<image>:<tag>@sha256:<index digest>`.** The tag is for humans, the
  digest is what builds; a rebuild without editing the line reproduces the same base. Take
  the digest from `docker buildx imagetools inspect <image>:<tag>` (the `Digest:` of the
  index, not of one platform's manifest) and pin the two stages of `Dockerfile.go` to the
  same Debian release (`cat /etc/debian_version` in both).
* **Re-pin monthly, and on any CVE in the base that the image exposes** — the Debian
  security tracker for the base, the toolchain's own advisories (Python, Node, Go
  point releases). A re-pin is a pull request: edit the `FROM` line(s), regenerate
  `python-requirements.txt` when pytest moves (the header of the file has the command),
  let the `sandbox-images` job prove the walls and the fixtures, push under the new date
  tag, then change `CRB_SANDBOX__IMAGE` / the repositories' `sandbox_image` to the new
  digest. Keep the previous image loaded until every repository has probed green on the new
  one — a `params.image` on one run (§3) is the canary.
* **Never `latest`, never a bare tag, never `pip install` without hashes**, and no
  `apt-get upgrade` in a derived image: a layer that differs by the day it was built is a
  verdict whose apparatus cannot be reproduced.
* The apparatus stamp on every verdict records the image reference the executor used
  (`DockerExecutor.describe()`), so which image graded a row is always visible.

## 6. What is not shipped, and why

* **JVM (Maven).** The `maven` runner's docker branch points Maven's local repository at
  `/tmp/m2` — the tmpfs that is empty in every container — and grades offline (`-o`), so
  a JVM run under the docker executor cannot resolve a single plugin today whatever the
  image contains; a reference image would be a false promise. The fix is in the runner
  (a warm repository the image keeps, read through `runner_opts.maven_opts` /
  `extra_ro_mounts`), and the image follows it. Until then a JVM repository runs under the
  local executor on a host with a warm `~/.m2`, visibly on every verdict's apparatus stamp.
* **Rust (Cargo).** Not asked for yet; the runner's docker branch (`CARGO_HOME=/tmp/cargo`,
  `target/` as a writable path) is expected to work with a registry cache baked into the
  image, but that has not been measured, and this directory ships nothing unmeasured.
* **A live re-measurement under the docker posture** (rows stamped `executor: docker`) is
  part 2 of F42 and is done on the stack, not in CI.
