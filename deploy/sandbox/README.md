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
[3 Select an image](#3-select-an-image) · [4 Dependencies](#4-dependencies-are-provisioned-per-task-adr-0019) ·
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
(`tests/test_sandbox_images_docker.py`): the image's own default user and the executor's
user are uid 65534; `/usr` and the worktree — read-only at `/src` — refuse a write
(`Read-only file system`), while `/work`, the throwaway copy of the tree every command runs
in (ADR-0019 §7), and `/tmp` accept one, and the host tree is byte-identical afterwards; the
image carries `/bin/sh` and GNU `tar`, which make that copy; no setuid/setgid file is in the
image; `/tmp` is `noexec` for every command but the Go runner's (`/proc/mounts` says so and a
script written there is refused / runs accordingly); a test that asserts `example.com:443` is
reachable **fails** through that language's runner, attributed to exactly that test id; an
image absent from the daemon's store is `SandboxUnavailable` rather than a pull (the daemon's
`No such image`, not its `pull access denied`); the language's fixture repository qualifies
(RED at the parent, gold clean) and grades clean with the same baseline reading the host
runner suite pins, leaving the host worktree untouched; the OCI labels and `USER` are set; and
a Go test that writes into its own package directory reads the same on the host and in the
copy (the D5 regression) **[measured — n = 42 tests passed, 0 skipped, across
`tests/test_sandbox_images_docker.py` (3 images) and `tests/test_sandbox_docker.py`; method: a
local run on colima, Docker 29.5.2, 2026-09-25; apparatus 2.2]**. Before ADR-0019 the same
module had ten tests per language and pinned the read-only `/work` instead **[measured — 47
passed / 0 skipped locally (colima, Docker 29.5.2, 2026-09-22) and 44 passed / 0 skipped in CI
on PR #44 run 35678358686, head 4a64fe3; apparatus 2.2]**. The sandbox suite and the
sealed-builder suite (`tests/test_sandbox_docker.py`, `tests/test_builders_container_docker.py`)
also run on the python image in that job, so the kill path, the sidecar and the copy-back
are proven on the shipped bytes too, and the dependency-provisioning suites
(`tests/test_provision_{fetch,go,python,node}.py`) fetch from an offline mirror into a sealed
set and run each language's fixture offline on its image.

**The fetch images.** Dependency provisioning (§4) runs its fetch in the full toolchain
image each sandbox image is built from — pinned by the same digests — because the slim
runtimes have no CA certificates. Pre-pull them next to the sandbox images when provisioning
is on:

| Fetch image (`CRB_PROVISION__*_IMAGE`) | For |
|---|---|
| `golang:1.26.8-bookworm@sha256:a688600ca24f8a4d3ca77f95b0dd40704a9fc787c826660eb7ba0b641b8b175d` | Go modules (`go mod download`) |
| `python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7` | Python wheels (`pip download`, then the offline `pip install`) |
| `node:22.19.0-bookworm-slim@sha256:4a4884e8a44826194dff92ba316264f392056cbe243dcc9fd3551e71cea02b90` | Node modules (`npm ci --ignore-scripts`) |

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

**The worker never pulls.** Each image — the sandbox images, and with provisioning on the
three fetch images in §1 and the proxy image — must already be in the store of the daemon
the worker talks to:

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

## 4. Dependencies are provisioned per task (ADR-0019)

The reference images carry the toolchain and the test runner and **nothing else**, and a
repository's dependencies are never baked into an image. They belong to the task: one
commit's `go.sum` is not its parent's (the gold commit of a replay routinely bumps a module),
so an image that holds one commit's dependencies serves one commit
([ADR-0019](../../docs/adr/0005-fail-closed-docker-sandbox.md#amendment-2026-09-25--adr-0019-a-throwaway-tree-read-only-dependency-sets-and-no-network-for-any-command)
records the finding, defects D1–D5). Instead, with provisioning switched on
(`CRB_PROVISION__ENABLED=true`, [DEPLOYMENT.md §3.4](../../docs/DEPLOYMENT.md#34-the-workers-sandbox--choose-deliberately)):

1. the lockfiles at the parent and at the gold are read from the repository's **git
   objects** — never a worktree, so nothing a builder writes can change what is fetched;
   `.npmrc`, `pip.conf` and `go.env` are never read;
2. a **fetch container** — the fetch image above, as the worker's non-root uid, read-only,
   no capabilities — fetches them. Its only network is an `--internal` bridge whose only
   way out is the allowlisting proxy to the configured registry hosts; a `file://` mirror
   runs it with no network at all. It sees the lockfiles and its output directory, never the
   source, a secret or `CRB_HOME`, and runs no repository code;
3. the result is **sealed** under `$CRB_HOME/deps` (`CRB_PROVISION__STORE`): content-addressed
   by the recipe, the fetch image's ID and the lockfile hashes, digested, made read-only and
   shared by every task with the same inputs (`crb deps ls | verify | gc`);
4. the test container **keeps `--network=none`** and mounts the set read-only:

| Language | Lockfile (at the commit) | Set | Mounted at | Test-time environment |
|---|---|---|---|---|
| Go | `go.mod` + `go.sum` (a `vendor/` tree needs no fetch) | ONE module cache for the parent's and the gold's modules | `/deps/gomod` | `GOMODCACHE=/deps/gomod GOPROXY=off GOSUMDB=off GOVCS=*:off GOTOOLCHAIN=local` |
| Python | `requirements*.txt` with `name==version` lines (hashes optional), or `runner_opts.deps_lock` | wheels only, installed with no network; one set per lock | `/deps/site` | `PYTHONPATH=/work:/deps/site`, `PYTHONNOUSERSITE=1` |
| Node | `package-lock.json` / `npm-shrinkwrap.json`, lockfileVersion 2+ | `npm ci --ignore-scripts`; the packages named in `runner_opts.deps_build_scripts` rebuilt with no network; one set per lock | `/work/node_modules` | `NODE_PATH=/work/node_modules`, `.bin` on `PATH` |

A trial is graded with the set its own manifests select — the parent's or the gold's; one
that selects anything outside that closure is disqualified, never graded. Refused, each with
its code and fix: a URL, VCS, path or foreign-registry source; an unpinned version; `go.work`;
`yarn`, `pnpm`, `poetry`, `uv` and `pylock` locks; a Python package published only as a
source distribution; an install script the repository did not name; JVM and Rust. Those stay
measurable in the local posture, on a stamp that says so. With provisioning **off**, a
repository that declares dependencies is refused `PROVISION_DISABLED` under docker before any
spend.

### 4.1 Extending an image for a toolchain (never for dependencies)

A derived image is for something the **toolchain** lacks: cgo's compiler, the linter belt 5
runs (`ruff` at the version the repository pins), another language's runtime. It is a
different posture — the image's ID is part of what a qualification records — so a repository
moved onto it is qualified again. Build it multi-stage: fetch in the full toolchain image by
digest (it has CA certificates; the slim sandbox images have none, so a `RUN` that downloads
inside them fails with `x509: certificate signed by unknown authority` — the D3 finding), then
copy the result onto the sandbox image:

```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7 AS fetch
COPY ruff-requirements.txt /r.txt          # ruff==<the repository's pin> --hash=sha256:…
RUN pip download --only-binary=:all: --no-deps --require-hashes -r /r.txt -d /wheels

FROM <acr>.azurecr.io/crb-sandbox/python@sha256:<digest>
COPY --from=fetch /wheels /opt/wheels
COPY ruff-requirements.txt /opt/wheels/r.txt
USER 0
RUN pip install --no-index --find-links /opt/wheels --require-hashes --root-user-action=ignore \
      -r /opt/wheels/r.txt
USER 65534:65534
```

Belt 5 runs the image's `ruff` under docker and fails closed (a visible harness error, never a
silent skip) when it is absent. For cgo: a stage that installs `gcc libc6-dev` from the Debian
release the image is built on, copied or installed onto the Go sandbox image, and
`runner_opts.cgo: "1"`. The Go runner sets `Command.exec_tmp` — the `/tmp` tmpfs is `exec` for
Go alone, because `go test` compiles each test binary there and runs it; `nosuid,nodev` hold.

**Another toolchain** (JVM, Rust) — copy the shape: a digest-pinned base, the toolchain and
the runner only, caches under `/tmp`, `/bin/sh` and GNU `tar` (the throwaway tree needs
them), `USER 65534:65534`, the labels; then add the language to
`tests/conftest_langs.py::SHIPPED_SANDBOX_LANGS`, its fixture, net probe and expected baseline
to `tests/test_sandbox_images_docker.py`, and a hadolint + build step to the `sandbox-images`
job in `.github/workflows/ci.yml`. The suite refuses a language with no image and an image
with no suite (`assert tuple(_LANGS) == SHIPPED_SANDBOX_LANGS`).

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
