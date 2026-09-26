# ADR-0019 — Qualification is posture-relative: a task is proven in the posture that grades it, its dependencies are provisioned per task outside the test container, and the model is blamed only with a witness from that posture

**Status:** Accepted (F42 part 2 finding, 2026-09-25; built in two streams on one seam, `crb.core.deps`: stream Q, posture-relative qualification, and stream D, dependency provisioning)
**Date:** 2026-09-25
**Apparatus impact:** bumps `APPARATUS_VERSION` to **2.3**. The meaning of a verdict changes in three ways:

- belt 3 subtracts the baseline measured in the posture that graded the trial;
- a `builder_red` or `lint` row needs a witness from that posture;
- in a provisioned posture, belt 1b also covers the task's dependency closure.

Every row carries its posture as hashed labels. The cell key does not change (`CELL_FIELDS`, ADR-0007). Posture is a stamp and a read filter, as `mode` and the apparatus version already are.

This ADR amends ADR-0005: tests run in a throwaway copy of a read-only tree, dependency sets are mounted read-only, and `Command.network=True` is refused under docker. It amends ADR-0012: a sealed builder may read the parent's dependency set, never the gold's.

## Context

**What happened.** On 2026-09-25 we ran the first replay in the docker posture. It was run `0c44ff24189d4879b1254be6181ef54c`: cobra, `bug.fix` × XS, image `crb-sandbox-go:main-8ab88ad` (Go 1.26.8, uid 65534, read-only root, no network), `claude_code / claude-sonnet-5`, with the tasks qualified earlier on the host. The replay graded every attempt `builder_red` with the target red **[measured — n = 3 or 4 rows, each `builder_red` with `target_green: false`, builder-reported cost $0.147, $0.180 and $0.137 for the 3 observed rows, and $0.111 for a fourth in stream D's reading; method: the run's grade rows as read on 2026-09-25; apparatus 2.2. The count is disputed: the finding's own note counted 3 when the run was cancelled, and stream D read 4 from the deployment's ledger export, which is not committed — [gap] F42, settled only by the stack's ledger]**.

The same cell on the host posture reads 22 of 22 clean on 9 distinct tasks **[measured — n = 22 attempts on 9 tasks, sighted replay under the local executor, belts 1–5, as the README's *What has been measured (2026-09-15)* section records it; apparatus 2.2]**. The model had not changed. The instrument had.

We reproduced the failure by hand. The instrument failed in five separate ways **[measured — n = 1 reproduction of each, method: commands run by hand against a fresh clone of `Jita81/cobra` inside the shipped Go sandbox image with `--network none`, 2026-09-25; apparatus 2.2]**:

- **D1: no dependencies in the sealed container.** With an empty module cache and no network, `go test` cannot load the module graph (`dial tcp: lookup proxy.golang.org … network is unreachable`). Every target therefore fails to build.
- **D2: the model is blamed for the environment's failure.** `crb.core.ledger.derive_failure_kind` names a row `harness` only when the grader recorded an error (rule 4b). A target that fails to build is a red target with no error, so it falls through to `builder_red` (rule 7). The run did not stop, and it paid for every task.
- **D3: the documented recipe fails.** `deploy/sandbox/README.md` §4 says to bake the module cache into a derived image. Inside the slim image that fails at build time (`x509: certificate signed by unknown authority`). A multi-stage build works: fetch in `golang:1.26.8-bookworm@sha256:a688…`, then copy the cache onto the sandbox image. With it, `cobra/doc` passes offline **[measured — n = 1 package, method: the multi-stage probe image run with `--network none` and `GOPROXY=off`, 2026-09-25; apparatus 2.2]**.
- **D4: one image serves one commit.** With that image, the gold commit `746ef07` fails `[setup failed]`, because its `go.mod` and `go.sum` differ from its parent's.
- **D5: the sandbox changes the baseline.** At the parent, `TestDeadcodeElimination` passes on the host (Go 1.26.4) and fails in the sandbox (Go 1.26.8). The test writes into its package directory, and the sandbox mounts the worktree read-only. Measured against a host baseline, belt 3 charges that failure to the builder as a "new failure".

**Why.** One fact sits behind D2 and D5: **qualification is not posture-relative.**

- `crb.core.mine.qualify` measures RED, the baseline failing set and the gold on whatever executor the mine ran with, and stamps none of them.
- Every later replay then trusts `TaskSpec.baseline_failing` and `gold_clean`, under any executor.
- Belt 3 in `crb.core.grade.grade` therefore subtracts a baseline that a different instrument measured.

A **posture** is everything outside the patch that can change a test's outcome: the executor, the bytes of the image, the toolchain, how the tree behaves, the network, the dependency set, the limits and the runner's command environment.

**Why it matters now.** A production deployment that follows the guide measures in the docker posture:

- docker is the deployment's default executor (`CRB_SANDBOX__EXECUTOR`);
- DEPLOYMENT §3.4 tells a cluster to run it;
- the go-live checklist proves the probe inside the sandbox.

The finding says production settings refuse `local`. They do not: `Settings._secrets_fail_closed` logs "test runs are NOT isolated" and carries on. The conclusion still holds for every deployment that follows the guide.

As shipped, such a deployment would read close to 0% for every Go repository with a third-party dependency, and would say the model failed **[hypothesis — one repository measured; the mechanism of D1 and D2 applies to any repository whose tests import a module the image does not carry]**.

The same flaw cuts the other way for the negative controls. An environment that cannot build makes every control look caught, and that overstates how strong the oracle is.

**Constraints.**

- The test container never has a network (ADR-0005).
- The builder must not be able to influence what is fetched.
- Nothing that holds a secret may reach a registry.
- The ledger is append-only (ADR-0002).
- A platform team must be able to run Go, Python and Node repositories without building an image by hand for each one.
- Every stop must say what to do.
- Qualification must cost no model money.

## Decision

1. **A posture is an identity, stamped and hashed.**
   - `crb.core.posture.Posture` holds:
     - the executor;
     - the image ID (`docker image inspect --format {{.Id}}`, never the tag). Once the posture has resolved it, every container the executor starts names that ID, not the tag, so a tag rebuilt during a run cannot grade a trial on bytes the posture does not name;
     - the toolchain version, probed inside the posture;
     - the runner, and a hash of its fixed command environment;
     - the tree mode, the network, the dependency mode and the limits;
     - the apparatus version.
   - `posture_id` is `pst_` followed by a SHA-256 over all of these except the image reference.
   - `posture_class` is what statistics pool on. It is `executor/tree/dependency mode`, for example `docker/copy/sealed`.
   - The posture is on the run's apparatus stamp, on every evidence pack and on every row (`labels.posture_id`, `labels.posture_class`).

2. **Qualification is a record per task and posture, measured in that posture, for no model money.** `crb.core.qualify.qualify_task` runs inside the posture, with the task's dependencies bound, in this order:
   - **Environment probe at the parent.** For Go this is `go list -deps -test ./...` offline. It proves the posture can load the parent's dependencies.
   - **RED, once, with the tests overlaid.** A RED that is a build failure counts only when the probe passed, so "nothing builds" can never produce a task.
   - **Baseline, twice.** The union of the two failing sets is the baseline. The tests that differ between the runs are recorded as flaky.
   - **The gold's target twice and its belt scope once, at half the wall clock.** A trial that later runs out the full clock has therefore taken more than twice as long as the gold.
   - **Belt 5 on the gold.**

   The result is a `Qualification`. It holds the state and any refusal code, the dependency keys and digests, the kind of RED, the baseline, the facts about the gold, a fingerprint of the facts that matter to the oracle, and how it differs from the task's qualifications in other postures.

   It is appended to `task_qualifications`. The latest row for a repository, task and posture is the one in force. A revocation is a new row.

   The run kind `qualify` (`crb repo qualify`, `POST /runs {kind: qualify}`) never constructs a builder. `crb.core.mine.mine` writes a qualification for its own posture in the same pass.

   `TaskSpec.baseline_failing`, `red_checked` and `gold_clean` stay as discovery values. The grader never reads them again.

3. **Nothing is built for a task that is not qualified in the run's posture.**
   - The worker (`crb.server.worker`) resolves the posture live and keeps only tasks with a `qualified` row for that `posture_id`.
   - With `qualify_first` (on by default), the worker qualifies the other tasks first.
   - If no task qualifies, the run fails with `POSTURE_UNQUALIFIED` before any builder call, and counts the refusals by code.
   - With `qualify_first` switched off, `POST /runs` refuses the run with `409 posture_unqualified` and the fix.
   - If the live posture differs from the one a qualification recorded, the run stops with `POSTURE_DRIFT`.
   - Before the first build, a **canary** grades the first task's own gold patch through the real path. If it is not clean, the run fails with `POSTURE_CANARY_FAILED`.
   - `crb.core.run.run_task` asks for the task's grade context before it calls the builder, so a task that is not qualified never reaches the builder.

4. **Belt 3 subtracts the in-posture baseline.**
   - `Qualification.project(task)` returns the spec the replay path uses. Its baseline and gold fields are the qualification's.
   - It also carries `posture_id` and `qualification_ref`. Both are written only when set, so existing specs and packs stay byte-identical.
   - `grade()` takes a required `GradeContext`, which holds the posture, the qualification, the dependencies and the witness.
   - When the spec, the context and the executor disagree, `grade()` raises `PostureMismatch`. That stops the run and writes nothing.

5. **The model is blamed only with a witness from the same posture.** Whenever a verdict would be `builder_red` or `lint`, `grade()` asks for a control. The control runs now, in the same posture, on a tree the builder never touched:
   - **for a replay task:** the gold tree (the parent, the tests and the commit's own sources, with the gold's dependencies) runs the scope the trial failed. That is the target for belt 2, or the belt scope for belt 3;
   - **for a factory item, which has no gold:** the environment probe runs on a fresh base tree;
   - **for a failure of belt 5 only:** the witness is that the gold passed belt 5 at qualification;
   - **for no source change:** this is a fact about the diff and needs no control.

   **If the control is green,** the row is `builder_red` or `lint`, and `labels.blame_control` names the witness.

   **If the control is red,** the trial's error becomes `environment: …`. The unchanged rule reads that as `harness`, which is counted against autonomy in the fail-closed rate and never against the model. The task's qualification is revoked and its ladder stops. Two such rows in a row stop the run (`env_stop`, event `run.environment_stop`), as `outage_stop` does for outages.

   **If the trial's own tree could not be given its ground** (the throwaway copy failed, `env_error: tree_copy_failed`), whose fault it was is a blame decision too, so the same control runs first. A green control means the posture holds the gold's tree and the trial's own tree did not fit (its size, or a path the worker could not make readable to the sandbox's user): the trial is disqualified (`dq_reason: trial tree: …`), never charged, never an `environment:` row, and nothing is revoked. A red control makes it an `environment:` row as above. Only a row whose control ran red (`env_code: GOLD_CONTROL_RED`) revokes a qualification; an unwitnessed grade's environment row (`TEST_RUN_ENVIRONMENT`) stops the ladder and revokes nothing.

   `MisattributionViolation` sits beside `FalseQ1Violation`. It makes 2 things impossible to construct:
   - a blamed `GradeResult` without a witness;
   - a measured row of apparatus 2.3 or later, in a model-failure kind, without its posture labels and its witness.

   Error text never decides how a failure is classified. A runner's error signature only names the fault on a row that the witness has already made `environment`.

6. **Dependencies belong to the task.** They are read from git objects, fetched outside the test container, sealed and mounted read-only. The seam between qualification and provisioning is `crb.core.deps`: `DepsProvider.resolve` returns a `TaskDeps` holding three bindings (the parent's, the gold's and the builder's) and a closure selector. `crb.provision` produces it. The qualifier, the grader and the worker consume it.

   **Inputs.**
   - The inputs are the lockfiles at the parent and at the gold, read from the repository's object store (`git show <sha>:<path>`) before any builder exists for the task.
   - No fetch path accepts a worktree, and grading never fetches.

   **The fetch container.**
   - It uses a digest-pinned toolchain image, which has CA certificates. That closes D3.
   - It runs as the worker's non-root user, so the worker can seal what it wrote.
   - Its only network is an `--internal` network. The only way out is the existing CONNECT-only allowlisting proxy (`crb/builders/egress_proxy.py`), to the configured registry hosts.
   - It sees `/in` (the lockfiles, read-only) and `/out`. It never sees a worktree, the repository's source, a secret or `CRB_HOME`.
   - It runs no repository code:
     - Go uses `go mod download` with `GOVCS=*:off` and never `direct`;
     - npm uses `ci --ignore-scripts`;
     - pip fetches wheels only.
   - Anything that must be installed or built runs in a second container with `--network=none`. That covers a Python install and the install script of a Node package the repository has named.

   **Checks.**
   - Every artifact is checked against the committed hash: `go.sum` and the checksum database, npm `integrity`, and pip hashes wherever the lock carries them. Where a pip lock carries no hash, the fetched hash is recorded in the bundle's manifest.
   - Before any container starts, the worker pre-parses the lockfiles. It refuses:
     - a URL, VCS, path or foreign-registry source;
     - an unpinned version;
     - `go.work`.
   - The repository's `.npmrc`, `pip.conf` and `go.env` are never read.

   **The store.**
   - The store is addressed by content: a key built from the recipe, the fetch image ID and the lockfile blob hashes.
   - A set is built in a staging directory, sealed with a digest, made read-only and renamed into place.
   - The host never follows what a container wrote. An install or rebuild step runs package code with `/out` writable, so before the seal a symlink that leaves the set, or anything but a regular file at the manifest's name, is refused `PROVISION_UNSAFE_OUTPUT` and the stage is discarded. The manifest is written as a new file that refuses a link, removal never changes permissions through a link, and a link to a directory inside the set is part of its digest.
   - Every task with the same inputs shares it.
   - Only the store can construct a `BundleMount`, and the executor checks every mount again.

   **Go, Python and Node.**
   - **Go** keeps one module cache for the parent's and the gold's modules together. That closes D4.
   - **Python and Node** keep one set per lockfile. A trial is graded with the set its own manifests select.
   - A trial whose manifests select anything outside the task's closure is **disqualified** under belt 1b. In a provisioned posture, the closure is part of the ground the oracle stands on. The selector reads the builder's tree, so it reads nothing outside it: a manifest that is a link, or a local `replace` that leaves the tree, is itself a violation.

   **At test time.**
   - The set is mounted read-only with the offline flags: `GOMODCACHE=/deps/gomod GOPROXY=off GOSUMDB=off` for Go, `/deps/site` on `PYTHONPATH` for Python, and `/work/node_modules` with `NODE_PATH` for Node.
   - The test container keeps `--network=none`.
   - `Command.network=True` is refused under docker.

   **Switching it on.**
   - Provisioning is off until an operator switches it on (`CRB_PROVISION__ENABLED`). While it is off, a repository that declares dependencies is refused with `PROVISION_DISABLED` before any spend.
   - In production:
     - a public registry is refused unless it is explicitly allowed; a mirror inside the tenant is the documented shape;
     - fetch images must be pinned by digest;
     - a `file://` mirror runs the fetch with no network at all.
   - `crb doctor` and `/health` report whether provisioning is on, and whether the daemon can see the store.

7. **Tests work in a throwaway copy of the tree.** This closes D5.
   - `DockerExecutor` mounts the worktree read-only at `/src`.
   - It copies the tree into a size-capped tmpfs at `/work` (`rw,exec,nosuid,nodev`), and only then runs the command. The copy is `exec` because the tree has always been executable to its own tests.
   - The copy dies with the container.
   - Declared output paths are still bound from the worktree.
   - The whole tree reaches the tests, whatever its host modes. The container's user owns nothing on the host, so before a container starts the executor adds read (and search, on a directory) for its owner and for others on every path the worker owns. It never adds a write bit, never changes the owner's execute bit (git's mode) and never follows a link. A path it cannot make readable fails the copy (`tree_copy_failed`), and the copy never leaves a path out: GNU tar's "removed before we read it" is fatal, although tar exits 1 for it (PR #56).
   - A repository whose tree is too large to copy can choose `sandbox_tree: readonly`. That is a different posture and is qualified separately.
   - In every posture, belts 4 and 5 read the builder's changes as they stood before the first test ran. A file a test writes is therefore never counted as the builder's.

8. **Posture is a filter, never a blend.**
   - By default, the capability map, the factory's route gate and the sign-off overlay read the deployment's posture class (`crb.server.routes.capability.rows_for_posture`).
   - `posture=all` pools two classes only over tasks whose qualification fingerprints match in both. It counts the rest as `excluded_posture_divergent`.
   - A cell lists its `posture_ids`, as it lists its apparatus versions.

9. **Every stop is a code with a fix.** There is one closed vocabulary, served as `{code, message, fix, doc}`. A code with run scope stops the run; a code with task scope skips the task.

| Code | Scope | What to do |
|---|---|---|
| `POSTURE_UNQUALIFIED` | run | qualify the repository in this posture (`crb repo qualify`, or leave `qualify_first` on); this costs no model money |
| `POSTURE_DRIFT` | run | the image, toolchain, limits or runner environment changed after qualification: qualify again |
| `POSTURE_CANARY_FAILED` | run | the gold did not grade clean here: read the canary's tail (the cause is usually provisioning or the image) |
| `QUAL_ENV_UNLOADABLE` | task | the parent cannot load its dependencies offline: switch provisioning on if it is off; if it is on, run `crb deps verify` and delete any set it names (the next run fetches it again); otherwise fix the module named |
| `QUAL_NOT_RED`, `QUAL_RED_TIMEOUT`, `QUAL_BASELINE_TIMEOUT`, `QUAL_BASELINE_UNATTRIBUTED` | task | the oracle cannot be proven in this posture; the Tasks screen shows how it differs from other postures |
| `QUAL_GOLD_NOT_GREEN`, `QUAL_GOLD_NEW_FAILURES`, `QUAL_GOLD_LINT` | task | the humans' own patch does not pass here; the task is excluded, as a task with a dirty gold always was |
| `QUAL_TARGET_FLAKY` | task | the gold's 2 target runs disagreed: the oracle is not deterministic in this posture |
| `QUAL_HEADROOM` | task | the gold needed more than half the wall clock: raise the repository's timeout |
| `QUAL_TREE_COPY_FAILED` | task | the tree did not fit the copy: raise `work_size`, or choose `sandbox_tree: readonly` |
| `PROVISION_DISABLED`, `PROVISION_PUBLIC_REGISTRY`, `PROVISION_FETCH_IMAGE_UNPINNED`, `PROVISION_STORE_NOT_VISIBLE`, `PROVISION_UNSUPPORTED_LANGUAGE` | run | a deployment setting; each fix names the setting (DEPLOYMENT §3.4) |
| `PROVISION_NO_LOCK`, `PROVISION_UNPINNED`, `PROVISION_SOURCE_REFUSED`, `PROVISION_BUILD_REQUIRED`, `PROVISION_LOCK_UNSUPPORTED`, `PROVISION_PRIVATE_MODULE`, `PROVISION_TOOLCHAIN_TOO_OLD`, `PROVISION_FETCH_FAILED`, `PROVISION_TOO_LARGE`, `PROVISION_UNSAFE_OUTPUT` | task | a fact about that commit's lockfiles or about the registry; each fix names the file, the host or the setting |
| `BUNDLE_INTEGRITY` | run | a sealed set no longer matches its digest: the run stops before any builder is called; `crb deps verify` names the set, and deleting it from the store makes the next run fetch and seal it again. Revoking every qualification that cites the set is decided but not built **[gap]** (G-966) |

10. **Migration.** Nothing is rewritten.
    - **Grade rows** keep their stamps, and 2.2 stays readable. A row stamped before 2.3 by the docker executor (read from its run's apparatus stamp) was graded against a baseline measured somewhere else. It is excluded from every rate and counted beside the cell as `unqualified_posture`. That covers run `0c44ff24…` without editing it.
    - **Task specs** keep their shape, and the new fields are written only when set.
    - **A store migration** adds `task_qualifications`, which is append-only like `grades`. It back-fills 1 `legacy` row per task, for the record.
    - **A legacy row** never satisfies the gate. Every repository therefore qualifies once, for no model money, before its next replay. With `qualify_first` on, the replay does this itself.
    - **Sign-offs** made on 2.2 cells go stale at 2.3 (ADR-0015).

## Consequences

**What becomes easier.**
- A sealed deployment can grade real Go, Python and Node repositories without an image per repository. The platform team switches provisioning on, points it at the organisation's mirror and presses *Qualify* once for each repository.
- The capability map can no longer say the model failed when the instrument did. Every row that blames the model names the witness that makes the blame true, and every rate names the posture that produced it.
- A run that cannot measure anything stops before it spends. The rows of run `0c44ff24…` (3 or 4: the count is disputed, [gap] F42) would instead have been a `409`, or a failure that cost $0, with the fix.

**What becomes harder.**
- Every repository must be qualified in each posture it is graded in. It must be qualified again when the posture changes: a monthly image re-pin, a toolchain upgrade or a changed limit. Qualification costs no model money, but it takes machine time **[measured — n = 1 cobra task (`746ef07`), 62 s (61.982 s) for the whole qualification with a cold Go build cache, in `docker/copy/sealed`; method: the `qualify.task` event of `docs/reviews/2026-09-25-sealed-posture/mine-events.jsonl`, reproduced at 60.6 s by the adversarial review; apparatus 2.3. One task is not a figure to plan on: other repositories and warm caches will differ — [hypothesis]]**.
- A trial that is not clean costs one more scoped test run, on the gold.
- The apparatus moves to 2.3, so the current map starts empty. Every cell must be measured again to be current, and that costs model money **[measured — about $0.14 to $0.15 per attempt with `claude_code / claude-sonnet-5` on cobra: the mean of the 3 observed builder-reported costs from run `0c44ff24…` is $0.155, and of the 4 in stream D's reading $0.144; apparatus 2.2; so few, so no interval, and the count itself is disputed — [gap] F42]**. Where ADR-0018's signed-cell licence is in force (ADR-0018 is pending in wave 2 and not yet on this branch), delivery pauses until a person re-signs a cell on 2.3 rows.
- In this version, the following are refused a sealed posture, each with its code. They stay measurable in the local posture, on a stamp that says so:
  - Python repositories without a pinned requirements lock;
  - Node repositories without `package-lock.json`;
  - Python packages published only as source distributions;
  - `yarn`, `pnpm`, `poetry` and `uv` locks;
  - JVM and Rust repositories.
- The throwaway copy counts against the container's memory. A very large tree needs `work_size` raised, or the `readonly` tree.
- The factory cannot deliver a change that needs a dependency the base does not already provision. Such an attempt is disqualified, and the item stops for a person **[aspiration — the extension point is a dependency request that a person approves before the build, fetched as a trusted input]**.

**What we must never do.**
- Give a test container a network.
- Put a package registry on the builder's allowlist.
- Fetch at grade time, or fetch anything a worktree names.
- Mount the gold's dependency set anywhere a builder can read it.
- Accept a qualification from another posture, or a legacy one.
- Classify a failure from its error text alone.
- Pool two posture classes over a task whose oracle differs between them.
- Rewrite a row to correct its posture.

**What is still open.** **[gap]**
- A negative control that is "caught" is not witnessed control by control. The canary covers only the start of a controls run.
- A mirror that needs a credential has no way yet to pass a secret into the fetch container.
- Nobody has yet qualified cobra live on the operator's stack. This work never touches that stack.
- We have not measured whether `proxy.golang.org` serves module zips from another host. If it does, the exact-match allowlist would refuse them.

## Alternatives considered

- **Give the test container a network, even through an allowlist.** Rejected. Untrusted tests with a route out would re-open SECURITY T1. A verdict would depend on what a registry served that day. It would also break the go-live line "an egress test from a worker pod fails". The cost of rejecting it is a separate fetch phase, a store and a sidecar to run.
- **A derived image per repository.** This covers README §4, and also the multi-stage probe that works. Rejected as the mechanism. The recipe as written fails (D3). Even when the image builds, it serves one commit (D4), so replaying n commits needs up to n images. Each would be a new posture that the platform team must build, push and pre-pull. The recipe is kept only as the escape hatch for a toolchain extension (cgo, or a linter), in its corrected multi-stage shape.
- **One module cache per repository, holding every version ever needed.** Rejected. A task could build against versions from its own future, and a trial that stepped outside its closure would pass without anyone knowing. The cost of rejecting it is one set per distinct lockfile, shared while the lockfiles do not change.
- **Install dependencies inside the sandbox, in a network phase (`Command.network=True`).** Rejected. Install scripts and source builds are untrusted code with a network. Under docker this is now refused outright.
- **Recognise environment failures by their error text** (`dial tcp`, `GOPROXY=off`, `ModuleNotFoundError`). Rejected as the guarantee. Toolchains change their wording. One signature also cuts in the model's favour: a patch that imports a module without requiring it prints `module lookup disabled by GOPROXY=off` too. The witness decides instead.
- **Qualification plus a canary at the start of the run, with no witness per trial** (the security-first and operator-first designs). Rejected. Drift after qualification would still write `builder_red` until a breaker tripped: a set removed from the store, a daemon starved of resources, or a flaky target. The cost of the witness is one scoped run on the gold for each trial that is not clean, and nothing for a clean one.
- **A new failure kind `environment`, outside n** (the correctness-first design). Rejected. The builder ran and was paid for. `harness` already means "the instrument failed: counted against autonomy, never against the model", and the failure split's partition stays as it is. `outage` sits outside n only because the call never happened.
- **Charge a trial outside its dependency closure as `builder_red`, or exclude it with a new kind.** Rejected in favour of a disqualification. Charging it blames the model for something the instrument cannot observe. A new kind would give a failing builder a way to leave n. A disqualification is the existing record of a builder that moved the oracle's ground: it is counted with its reason, and it is never credited or blamed.
- **Keep the qualifications inside `TaskSpec`.** Rejected. It would rewrite every stored spec and the task block of every pack. It would also lose the history of revocations that an append-only table keeps.
- **Accept host-measured qualifications for the local posture in development.** Rejected. A 2.3 row would then carry a witness nobody measured, and qualifying costs no model money anyway.
- **Add posture to `CELL_FIELDS`.** Rejected. It would re-identify every cell and change the federated export (ADR-0007). A hashed label and a filter do the job, as they already do for `mode`.
- **Keep apparatus 2.2 and treat posture as a stamp only.** Rejected. `builder_red` now means "witnessed", belt 3's baseline comes from a different source, and belt 1b covers new ground. A verdict means something different. The cost is stated above: stale sign-offs, an empty current map, and model money to measure again.
- **A writable copy on the host, bind-mounted read-write** (the operator-first design). Rejected as the default. The container would write to the worker's disk with no size cap. Under colima or `dind`, the worker cannot always remove files the container creates as uid 65534. The tmpfs copy dies with the container.
- **Mount the parent's and the gold's dependencies in the sealed builder** (the correctness-first design). Rejected. The gold's module list is part of the answer.
