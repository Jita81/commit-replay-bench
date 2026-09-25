# The sealed posture — what broke, what ADR-0019 decided, and what was proved on cobra

**Date:** 2026-09-25. **Tree:** branch `feat/posture` (stream Q and stream D merged onto `main`
at `8ab88ad`), crb 2.0.0a1, apparatus 2.3. **Spend:** £0 — no builder and no model was called;
every step used the product's own qualify, gate and run code with a fixture build function.
**Artefacts:** [`2026-09-25-sealed-posture/`](2026-09-25-sealed-posture/) (the driver, its
output, the qualification records, the mine's events, the probe and the store check).

## 1. What broke: five defects in the sealed posture as shipped

The first replay in the docker posture was run `0c44ff24189d4879b1254be6181ef54c` on the
operator's stack: cobra, bug.fix × XS, image `crb-sandbox-go:main-8ab88ad`, builder
`claude_code:claude-sonnet-5`. The operator's session cancelled it after 3 of 9 attempts, and all
three were graded `failure_kind: builder_red` with `target_green: false`, at $0.147, $0.180 and
$0.137 **[measured — n = 3 attempts, method: the run's grade rows read on the live stack on
2026-09-25, recorded in the session's findings note; apparatus 2.2]**. The same cell on the host
posture reads Sonnet 5 22 of 22 clean **[measured — n = 22 tasks, method: the README's host-posture
cell; apparatus 2.2]**. Stream D's CHANGELOG entry counts 4 `builder_red` rows for the same run;
this review could not reconcile the two counts without the stack's ledger, which the hard rules
keep out of reach **[gap]**.

The five defects were then reproduced by hand against a fresh clone of `Jita81/cobra`
**[measured — n = 1 clone, method: the commands quoted below, run on 2026-09-25; apparatus 2.2]**.
Each is quoted with its evidence.

- **D1 — no dependencies in the sealed container.** With `--network none` and an empty
  `GOMODCACHE`, `go test ./...` in the shipped image cannot load the module graph:
  `go: github.com/cpuguy83/go-md2man/v2@v2.0.6: Get "https://proxy.golang.org/...": dial tcp:
  lookup proxy.golang.org ...: network is unreachable`. Every task's target failed to build.
- **D2 — misattribution.** The product graded that environment failure `builder_red`, against
  the model. Production refuses `sandbox.executor=local`, so under this posture every Go
  repository with a third-party dependency would have measured close to nothing and routed to a
  person, and the capability map would have said the model failed. The run did not stop: it
  spent on each task.
- **D3 — the documented derived-image recipe failed as written.** Baking the module cache into a
  derived image (`deploy/sandbox/README.md` §4 at the time) failed at build time, because the
  slim base has no CA certificates: `tls: failed to verify certificate: x509: certificate signed
  by unknown authority`. A multi-stage build (fetch in `golang:1.26.8-bookworm@sha256:a688...`,
  copy `/opt/gomod` onto the sandbox image) worked.
- **D4 — one image holds one commit's dependencies.** With that derived image the gold commit
  `746ef07` failed `FAIL github.com/spf13/cobra [setup failed]` offline: its `go.mod` and
  `go.sum` differ from the ones the image was built for. An image per repository cannot serve a
  replay of many commits.
- **D5 — the sandbox changed the baseline.** At the parent, `TestDeadcodeElimination` passed on
  the host (go1.26.4, 0.894s) and failed in the sandbox: `could not write test program: open
  test_deadcode/test_deadcode_elimination.go: no such file or directory`. The test writes into
  the worktree, which the sandbox mounted read-only. Graded against a host baseline, that reads
  as a new failure charged to the builder.

## 2. What ADR-0019 decided

[ADR-0019](../adr/0019-qualification-is-posture-relative.md) makes qualification a fact about a
task **in a posture**, and makes the sealed posture able to hold a task's dependencies. In short:

1. **A posture is an identity.** It is the executor, the image by content id, the exact toolchain
   probed inside it, the runner's environment, the tree, the network, the dependency mode and
   the limits, hashed to `pst_…`. Its class (`executor/tree/deps-mode`) is what rates pool on.
2. **A task is qualified where it is graded, for no model money.** An offline environment probe
   (Go: `go list -deps -test ./...`), RED once, the baseline twice, the gold twice and belt 5 on
   the gold, in the posture. Each refusal is a code with its fix; `QUAL_ENV_UNLOADABLE` is the
   one D1 now gets. Nothing is built for an unqualified task.
3. **The model is blamed only with a witness from the same posture.** A verdict that would be
   `builder_red` or `lint` first reruns the failed scope on the gold there; a red control makes
   the row `harness` with `error: environment: …` (D2).
4. **Dependencies are provisioned per task, outside the test container** (D1, D3, D4). The
   lockfiles at the parent and the gold are read from git objects, fetched by a pinned image
   through the allowlisting proxy (or from a `file://` mirror with no network), sealed into a
   content-addressed store and mounted read-only; the test container keeps `--network=none`. Go
   keeps one module cache for the parent's and the gold's modules. Provisioning is off by
   default, and while it is off a repository with dependencies is refused `PROVISION_DISABLED`
   in the sandbox before any spend. A derived image is kept only as the escape hatch for a
   toolchain extension (cgo, a linter).
5. **Tests run in a throwaway copy of the tree** (D5): the worktree is read-only at `/src` and
   each command runs in a size-capped tmpfs copy at `/work`. The read-only tree stays available as
   a separate posture.

## 3. What was proved on cobra

**Set-up.** A fresh clone of `https://github.com/Jita81/cobra.git` (HEAD `9c0edca`), used
read-only. Task `746ef07158728502482cea9f880a6f4b21ef29a9`, parent `f2878ba` (its `~1`), gold
`746ef07`: "fix: prevent completions from mutating os.Args via append side effect (#2356)",
`completions.go` changed and `completions_test.go` added. The shipped image of the finding,
`crb-sandbox-go:main-8ab88ad` (`sha256:0e796b7e…`; this merge changes only comments in
`Dockerfile.go`). Colima 0.10.3, Docker 29.5.2. A throwaway `CRB_HOME`; the operator's stack and
`127.0.0.1:8000` were not touched. Provisioning on (`CRB_PROVISION__ENABLED=true`,
`ALLOW_PUBLIC=true`, the pinned Go fetch image and a pinned proxy image), through the wrapper
[`crbp.sh`](2026-09-25-sealed-posture/crbp.sh).

Every result below is **[measured — n = 1 real repository and 1 task; method: the product's own
code on colima as listed in each item, 2026-09-25; apparatus 2.3]**.

### (a) The task qualifies in the sealed posture, its dependencies provisioned for it

`crb mine cobra --executor docker --ref 746ef07… --max-candidates 1 --target 1` (the CLI miner,
which now takes the deployment's provider, as the worker's miner does) resolved the live posture
`pst_9108b668d829d89d832eaaad`, class `docker/copy/sealed`: image id `sha256:0e796b7e…`, toolchain
`go version go1.26.8 linux/arm64`, network `none`, limits
`mem=2g,cpus=2,pids=512,tmp=512m,work=1g,user=65534:65534`. Then, from
[`mine-events.jsonl`](2026-09-25-sealed-posture/mine-events.jsonl):

- `provision.fetch` — the Go recipe, mode `proxy`, hosts `proxy.golang.org` and
  `sum.golang.org` only, in the pinned fetch image **[measured — n = 1 fetch, method: the mine's
  events, apparatus 2.3]**;
- `provision.seal` — set `dep_a466b98b…`, digest `sha256:0338fa29…`, 1859788 bytes: the parent's
  and the gold's modules in one read-only cache **[measured — n = 1 sealed set, method: the
  mine's events, apparatus 2.3]**;
- `qualify.task` — `state: qualified`, in 61.982 s, spending nothing **[measured — n = 1
  qualification, method: the mine's events, apparatus 2.3]**.

The qualification record ([`qualifications.jsonl`](2026-09-25-sealed-posture/qualifications.jsonl),
line 1) carries the environment probe (`go list -deps -test ./...` offline: `ok: true`, 0.335 s), the
set it was proven with (`deps.mode: sealed`, the key and digest for the parent, the gold and the
builder, each mounted at `/deps/gomod`) and the gold check (`clean: true`, 2 target runs, belt 5
clean). `crb repo probe cobra --executor docker`, which now binds HEAD's set the same way, was green
over `./...` in 8.9 s ([`probe.json`](2026-09-25-sealed-posture/probe.json)) **[measured — n = 1
qualification record and 1 probe, method: the records linked, apparatus 2.3]**.

### (b) The baseline is measured in the posture

The record's baseline was measured in `docker/copy/sealed`, twice: `baseline_failing` is
`github.com/spf13/cobra::TestCompletionDoesNotMutateOsArgs` (the task's own new test, red at the
parent) and `baseline_flaky` is empty. `TestDeadcodeElimination` is not in it: in the throwaway
copy the test can write its program, so D5 no longer changes the baseline.

The same task qualified in the **read-only** tree (`CRB_SANDBOX__TREE=readonly crb repo qualify`,
a different posture, `pst_cc65f0f43e26bdb5a40ae2b0`, `docker/readonly/sealed`) reproduces D5 and
refuses the task instead of blaming anyone: `TestDeadcodeElimination` joins the baseline and the
gold's target is red there, so the record is `unqualified`, `QUAL_GOLD_NOT_GREEN` (line 3).

### (c) A broken environment is refused before any builder call, and never graded `builder_red`

[`proof.py`](2026-09-25-sealed-posture/proof.py) drives the worker's own pieces:
`PostureGate` (admission and `context_for`, which `crb.core.run` calls before a builder) and
`crb.core.run.run`. Its output is [`proof.json`](2026-09-25-sealed-posture/proof.json).

1. **Positive control.** The gate admitted the task on its recorded qualification, and the run
   replayed the gold (the `fixture_gold` overlay, a build function that calls no model) clean:
   1 row, `clean: true`, `target_green: true`, `no_new_failures: true`, labelled with the
   posture and the qualification it was graded under, in 21.2 s.
2. **The environment breaks.** The sealed module cache was emptied (257 files removed), its
   manifest left in place: the set the qualification cites is gone.
3. **The gate refuses before any builder call.** A new run on the same task stopped in
   `context_for` with `BUNDLE_INTEGRITY` (run scope): "digest `sha256:e3b0c442…` does not match the
   sealed `sha256:0338fa29…`". The build function was called 0 times and 0 rows were written.
4. **Past the gate, the grade does not blame the model.** Grading a trial that changed nothing
   with the context the gate had issued before the break, the target was red, the witness ran the
   gold in the same posture and it was red too. The row is `failure_kind: harness`, `blamed:
   false`, with `error: environment: gold control red in pst_9108b668d829d89d832eaaad: belt 2:
   target not green: go: github.com/cpuguy83/go-md2man/v2@v2.0.6: module lookup disabled by
   GOPROXY=off` — the D1 message, now attributed to the environment.
5. **Qualifying again refuses the task.** A second qualification in the broken environment is
   `unqualified`, `QUAL_ENV_UNLOADABLE`: "the parent cannot load its dependencies offline in this
   posture".
6. **Provisioning off, the shipped default.** `crb repo qualify` without
   `CRB_PROVISION__ENABLED` stops with exit 2 before anything runs: `PROVISION_DISABLED: cobra
   declares go dependencies (github.com/cpuguy83/go-md2man/v2@v2.0.6, …) and dependency
   provisioning is off — what to do: switch dependency provisioning on
   (CRB_PROVISION__ENABLED=true, DEPLOYMENT §3.4), or measure this repository in the local
   posture`.

**Recovery.** `crb deps verify` named the damaged set (`BUNDLE_INTEGRITY`) and left it in place.
After its directory was deleted, the next `crb repo qualify` fetched and sealed it again with the
same digest, `sha256:0338fa29…`, and the task qualified again (line 2);
[`deps-verify-after-refetch.json`](2026-09-25-sealed-posture/deps-verify-after-refetch.json) reads
`ok`. The refusal's fix sentence used to promise that "every qualification that cites the set is
revoked and the set is fetched again"; neither happens by itself, so the sentence now says what
the operator does. Automatic quarantine and revocation are **[gap]** G-966.

### The same proof as a test

[`tests/test_posture_e2e_docker.py`](../../tests/test_posture_e2e_docker.py) repeats (a), (b)
and (c) 1–5 on a fixture Go repository with one module, provisioned from a `file://` mirror with
no network at all, and runs in CI's sandbox-images job. It fails if the gate stops verifying the
set, if the witness is removed (the row would read `builder_red`), or if the throwaway tree
stops being the default (the test that writes into its package would join the baseline).

## 4. What is still open

- **A live qualification on the operator's stack.** This proof ran off the stack, by rule. The
  operator's hand-off is unchanged: switch provisioning on with the mirror hosts, pre-pull the
  fetch images and a proxy image, run `crb repo qualify cobra --executor docker`, then re-run
  F42 part 2 **[gap]** (F42).
- **Automatic quarantine and revocation of a damaged set** **[gap]** (G-966).
- **A timing claim for provisioning at scale.** One fetch of cobra's four modules is not a
  number to plan on **[hypothesis]**.
