# Releasing

*For the person who cuts a version: what changes, in what order, what the pipeline then
does on its own, and what to check before telling anyone the release exists.* Deploying
what a release produces is the [Deployment guide](DEPLOYMENT.md); the branch and pull
request rules are [CONTRIBUTING](../CONTRIBUTING.md).

A release is **a tag `v<package-version>` on `main`** — `v` + the exact PEP 440 version in
`pyproject.toml`, pre-release suffix included (`v2.0.0b1`, `v2.0.0`); `X.Y.Z` below stands
for that version. Pushing the tag runs
[`.github/workflows/release.yml`](../.github/workflows/release.yml), which builds the
package and the container image, smokes both, writes an SBOM, pushes the image to GHCR and
signs it keyless. Nothing is published to PyPI; the Helm chart is installed from the git
tag. The package version is one number in three files, pinned equal by
`tests/test_version_consistency.py` (which also pins the chart's own `version` to the
SemVer form of that number), and the CHANGELOG must carry a dated header for it — so a
bump that misses one is a failing test, never a refused tag.

Contents: [1 Numbers](#1-the-numbers-and-where-they-live) ·
[2 Cut a release](#2-cut-a-release) · [3 What the pipeline does](#3-what-the-pipeline-does) ·
[4 Check it on GHCR](#4-check-it-on-ghcr) · [5 After the tag](#5-after-the-tag) ·
[Checklist](#checklist)

---

## 1. The numbers and where they live

| What | Where | Example for the next cut |
|---|---|---|
| Package version (PEP 440) | `pyproject.toml` `[project] version`; `src/crb/core/version.py` `__version__`; `deploy/helm/crb/Chart.yaml` `appVersion` | `2.0.0b1` |
| Git tag | `v` + the package version, on `main` | `v2.0.0b1` |
| Image tags | the package version, and `sha-<7-char sha>`; never `latest` | `ghcr.io/jita81/commit-replay-bench:2.0.0b1` |
| Chart version (SemVer 2) | `deploy/helm/crb/Chart.yaml` `version` — tracks the package version; a PEP 440 pre-release takes SemVer's hyphen | `2.0.0-b1` |
| CHANGELOG header | `## [X.Y.Z] — YYYY-MM-DD …` plus the compare link `[X.Y.Z]: https://github.com/Jita81/commit-replay-bench/compare/v<previous>...vX.Y.Z` | `## [2.0.0b1] — 2026-09-2x` |
| Apparatus version | `crb.core.version.APPARATUS_VERSION` — **not** a release number; it moves only when the meaning of a verdict changes, with an ADR | stays `2.2` |

`scripts/check_release_tag.py` is the rule `release.yml` runs first, before anything is
built: on a tag push the tag must be exactly `v` + the `pyproject.toml` version, **and the
tagged commit must be reachable from `main`** (the workflow's full-history checkout carries
`origin/main` — it never fetches, since the checkout keeps no token — and it runs
`git merge-base --is-ancestor` through the script's `--require-on origin/main`), or the job stops with an `::error::` annotation naming the
tag, the commit and the ref, and nothing is built, pushed or signed. The `main` half is
the release contract enforced, not described: without it a `v*` tag on an unmerged
branch commit would have built, pushed to GHCR and keylessly signed an image nobody
reviewed (CodeRabbit on PR #43, 2026-09-21). `tests/test_release_tag.py` proves both
outcomes on a throwaway repository and that the workflow runs the step before `uv build`.

The workflow check is the floor; **who may create a `v*` tag** is the repository's setting,
not the pipeline's — and that setting does not exist: **this repository has no ruleset at
all, so anyone who can push may create, move or delete a `v*` tag** [gap] **[measured
2026-09-22 — the repository's rules read once from the setting itself (`gh api
…/rules/branches/main`), which returned an empty list, n = 1 reading; apparatus n/a: a
repository setting, not a graded number]**. The way to close it is a **tag-protection
ruleset** (*Settings → Rules → Rulesets → New tag ruleset*, target `v*`, *Restrict creations*
with maintainers as the bypass list, and *Restrict deletions* / *Block force pushes* so a tag
never moves), which only an administrator of the repository can add. Even then the ruleset
governs **who** may create, delete or move a `v*` tag — it does not check what the tag points
at, and a maintainer on the bypass list can still tag an unmerged commit; main ancestry is
enforced by the workflow alone, on every tag, whoever pushed it, which is why the workflow's
refusal is the floor either way. (CodeRabbit's ruleset query on PR #43, 2026-09-21, also
found none — the gap has been open since at least then.)

## 2. Cut a release

Work on a branch (`chore/release-X.Y.Z`) and land it through a pull request like any other
change; the tag is pushed **after** the merge, on the merge commit.

1. **Bump the four numbers together**: `pyproject.toml`, `src/crb/core/version.py`,
   `deploy/helm/crb/Chart.yaml` `appVersion` (quoted), and the chart's own `version` — the
   SemVer form of the same number (`2.0.0b1` → `2.0.0-b1`; a final release is the same
   string). `pytest tests/test_version_consistency.py` is the check:
   `test_package_version_is_one_number_in_three_places` pins the first three equal, and
   `test_chart_version_is_the_semver_form_of_the_package_version` pins the chart `version`
   to `semver_of(__version__)` — the rule lives in that test file.
2. **Cut the CHANGELOG**: rename the `## [Unreleased]` block to `## [X.Y.Z] — YYYY-MM-DD —
   <one line>`, keep its dated sub-sections as they are, open a new empty `## [Unreleased]`
   above it, and add the compare link at the foot of the file (and repoint the `[Unreleased]`
   link at `vX.Y.Z...main`). The same test refuses a header without a date and a body that
   still says `tag pending`.
3. **A line in the decision log** (`docs/DECISION-LOG.md`) saying what the release is for
   and what evidence it rests on — every claim in the CHANGELOG section carries its
   `[measured — …]` bracket already; the log entry points at them.
4. **Update what names the version**: the README status line, the `deploy/verify-image.sh`
   / `cosign triangulate` examples in [DEPLOYMENT §2.2](DEPLOYMENT.md#22-the-released-image-name-signature-sbom)
   and the compose `CRB_IMAGE` example.
5. **Every gate green locally** — the same commands CI runs: `ruff check`, `ruff format
   --check`, `mypy src`, `scripts/code_map.py --check`, `lint-imports`, the full `pytest`,
   `cd ui && npm run typecheck && npx vitest run`, `helm lint deploy/helm/crb --strict`.
6. **Dry-run the pipeline** from the branch: *Actions → release → Run workflow*
   (`workflow_dispatch`). On a branch it builds and smokes the wheel and the image exactly
   as the tag will, and **never pushes or signs**; read its summary.
7. **Merge the pull request**, then run the adversarial verify pass CONTRIBUTING asks for
   before a release tag: the full suite on the merged tree, fresh checkout.
8. **Tag the merge commit and push the tag** — the merge commit, on `main`: the workflow
   refuses a tag whose commit `main` does not contain (§1), so a tag pushed from the
   branch before the merge is a red `build` job, not a release:

   ```bash
   git switch main && git pull --ff-only
   git tag -a vX.Y.Z -m "crb X.Y.Z — <the CHANGELOG header line>"
   git push origin vX.Y.Z
   ```

## 3. What the pipeline does

`release.yml` on a `v*` tag, three jobs in order:

| Job | Does | Stops when |
|---|---|---|
| `build` | `scripts/check_release_tag.py --require-on origin/main` on the full-history checkout (the tag is `v<pyproject version>` and its commit is reachable from `main` — nothing is built otherwise); `uv build` (sdist + wheel); installs the wheel into a clean venv and imports `crb.core`; records `SHA256SUMS`; uploads `crb-dist-<tag>` | the tag is not `v<pyproject version>`; the tagged commit is not on `main`; the wheel does not import |
| `image` | builds `deploy/Dockerfile` for `linux/amd64` (UI bundle + the wheel, installed non-editable); smokes the candidate — non-root uid 10001, read-only root, `migrate upgrade` on SQLite, UI and tools present; writes an SPDX 2.3 SBOM with syft and uploads it as `crb-image-sbom-<tag>` (365-day retention); **pushes to GHCR only for a tag of `Jita81/commit-replay-bench`** (a fork or a dispatch builds and smokes but never publishes); smokes the **pushed** digest again | any smoke fails |
| `sign` | `cosign sign` the pushed digest **keyless** (the workflow's GitHub OIDC token → a Fulcio certificate, recorded in Rekor) and `cosign attest --type spdxjson` the SBOM; then verifies its own signature | the signature does not verify |

There is no signing key to hold or rotate. The identity a verifier accepts is the release
workflow on a `v*` tag of the canonical repository, issuer
`https://token.actions.githubusercontent.com` — `deploy/verify-image.sh --print` shows the
exact `cosign` invocation, and `tests/test_release_verify_image.py` holds the script, the
workflow and the Helm values to the same identity.

The Helm chart is **not** packaged or pushed by the workflow: an operator installs it from
the tag (`git checkout vX.Y.Z && helm upgrade --install crb deploy/helm/crb …`,
[DEPLOYMENT §3](DEPLOYMENT.md#3-kubernetes-helm)). Publishing the chart as an OCI artifact
(`helm package deploy/helm/crb && helm push crb-<version>.tgz oci://ghcr.io/jita81/charts`,
signed the same keyless way) is a follow-up; until it lands, the chart `version` in the
tag is the chart an operator gets.

## 4. Check it on GHCR

Before the release is announced, from any machine with `docker login ghcr.io`
(`read:packages`), `cosign ≥ 2` and `jq`:

```bash
deploy/verify-image.sh X.Y.Z --sbom sbom.spdx.json       # signature identity + SBOM attestation
cosign triangulate --type digest ghcr.io/jita81/commit-replay-bench:X.Y.Z   # the digest to pin
docker run --rm ghcr.io/jita81/commit-replay-bench:X.Y.Z python -c 'import crb.core.version as v; print(v.__version__)'   # prints X.Y.Z
```

And on GitHub: the *release* workflow run for the tag shows every job green and the
`crb-dist-<tag>` / `crb-image-sbom-<tag>` artifacts; the package page
(*Packages → commit-replay-bench*) lists the tags `X.Y.Z` and `sha-<sha>` **and no
`latest`**; the digest the package page shows is the one `cosign triangulate` printed.
If any of these differ, the release is not done — do not move the tag; fix on `main` and
cut the next number.

## 5. After the tag

- Create the GitHub release for the tag with the CHANGELOG section as its notes (the
  compare link is already in the CHANGELOG).
- Tell the deployments: [DEPLOYMENT §6](DEPLOYMENT.md#6-upgrade) is the upgrade procedure
  (verify, triangulate, `helm upgrade --set image.digest=…`); a schema change is listed in
  the CHANGELOG section under its revision number.
- Open the follow-ups the release found (a `Deferred` line in the decision log is enough).

## Checklist

Copy into the release pull request.

- [ ] `pyproject.toml`, `src/crb/core/version.py`, `Chart.yaml` `appVersion` = `X.Y.Z`;
      `Chart.yaml` `version` = the SemVer form — `pytest tests/test_version_consistency.py`
      (`test_package_version_is_one_number_in_three_places` +
      `test_chart_version_is_the_semver_form_of_the_package_version`)
- [ ] CHANGELOG: `## [Unreleased]` → `## [X.Y.Z] — YYYY-MM-DD — …`; new empty
      `## [Unreleased]`; compare link `[X.Y.Z]: …/compare/v<previous>...vX.Y.Z`; `[Unreleased]`
      link repointed; no `tag pending` left in the section
- [ ] decision-log line; README status line; DEPLOYMENT §2.2 examples
- [ ] every local gate green; `workflow_dispatch` dry run green (built and smoked, not pushed)
- [ ] pull request merged; adversarial verify pass on the merged tree
- [ ] `git tag -a vX.Y.Z` on the merge commit (`git merge-base --is-ancestor vX.Y.Z origin/main`
      answers 0 — the check the workflow repeats); `git push origin vX.Y.Z`
- [ ] release workflow: `build`, `image`, `sign` green; artifacts present
- [ ] GHCR: tags `X.Y.Z` + `sha-…`, no `latest`; `deploy/verify-image.sh X.Y.Z --sbom` passes;
      digest recorded
- [ ] GitHub release created from the CHANGELOG section
