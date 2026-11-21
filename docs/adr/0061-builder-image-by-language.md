# ADR-0061 — The builder image is chosen by language, and a missing image is refused

**Status:** Proposed (DL-429)
**Date:** 2026-11-20
**Apparatus impact:** none. APPARATUS_VERSION stays 2.6. A run that gets an image runs
exactly as before: the same container, the same fingerprint fields, the same grader. What
changes is which runs start: a run that would have been built or tested in another
language's image is now refused before anything is built, so it writes no row.
**Breaking for operators:** a deployment that sets only `CRB_BUILDER__IMAGE` has every sealed
build refused until it sets `CRB_BUILDER__IMAGE_LANGUAGES` or a `CRB_BUILDER__IMAGE_<LANG>`,
and a docker run for a repository with no `sandbox_image` is refused unless
`CRB_SANDBOX__ALLOW_DEFAULT_IMAGE=1` is set. See "Consequences".

## Context

A sealed builder (ADR-0012) runs in one image, `CRB_BUILDER__IMAGE`, and the adapter starts
the handed test command's tool in that image before any model call (`runner tool missing`).
The test sandbox has the same shape: a repository's `sandbox_image`, else the worker's
`CRB_SANDBOX__IMAGE`.

Both images hold one language's toolchain. The documentation said "one image per worker: a
worker serves one language", but nothing enforced it. The queue handed any run to any worker,
so a Go repository's run could reach a worker whose builder image was the Python variant, and
a repository that named no sandbox image ran its tests in whatever the worker's default was.
The outcome was a refused attempt, a probe that failed with `go: not found`, or a verdict
recorded in an image that was never chosen for that repository. In each case the operator
learned about the mismatch from a failure, not from the configuration.

## Decision

**1. One builder image per language, resolved per run.** The builder image is chosen from
the language of the run's repository (`RepoConfig.language`):

- `CRB_BUILDER__IMAGE_<LANG>` (`_PYTHON`, `_GO`, `_JAVASCRIPT`, `_JVM`, `_RUST`) when set;
- else `CRB_BUILDER__IMAGE`, when `CRB_BUILDER__IMAGE_LANGUAGES` (a comma list, aliases such
  as `py` and `golang` accepted) lists the language;
- else nothing. There is no third rule: an image that does not name a language is never used
  for it.

`crb.builders.container.builder_image_for` is the one resolver; the worker, `/settings` and
the docker probe read it. An unknown name in `CRB_BUILDER__IMAGE_LANGUAGES` fails the API's
start and the run, never silently drops the entry. The sidecar runs `python3` from
`CRB_BUILDER__PROXY_IMAGE`; empty, it defaults to `CRB_BUILDER__IMAGE` (the default builder
image, which carries `python3`), and only when that is empty too to the run's own builder
image. A per-language image never becomes the proxy by default: the Go and Node builder images
carry no `python3`, so a Go run beside a Python default image keeps a working sidecar, and a
deployment with no `CRB_BUILDER__IMAGE` that serves Go or Node sets
`CRB_BUILDER__PROXY_IMAGE`. The docker probe checks every served language's effective proxy
image, not only the default one.

**2. Refuse, never default.**

- A sealed builder run whose language has no image is refused before a task is qualified or
  a model is called (after a named context set is verified): `run.refused` with code
  `builder_image_missing`, the language and the variable to set, and the run's error says
  the same (`BuilderImageMissing`, a `SandboxUnavailable`, so it fails closed).
- A docker test sandbox for a repository with no `sandbox_image`, and a run request with no
  `image`, is refused: `run.refused` with code `sandbox_image_missing`, the repository, its
  language and the setting, and the run's error `sandbox unavailable: sandbox_image_missing:
  …` says what to set. It is a configuration refusal, not a sandbox outage: it is not
  counted in `crb_sandbox_unavailable_total` and does not raise `CrbSandboxFailingClosed`.
  The opt-in `CRB_SANDBOX__ALLOW_DEFAULT_IMAGE=1` (off by default; read by the worker and
  shown on `/settings`) lets such a run use `CRB_SANDBOX__IMAGE`. Every run that does records
  a `run.sandbox_default_image` event naming the image, the language and the setting, once
  its executor is built (a run whose executor cannot be built records no such event), so a
  run on the default image is visible on its own record. The worker reads the flag with the
  API's boolean parser (pydantic's), so the two never disagree on a value.
- A configuration no run could use is reported, not silently accepted: when no builder image
  serves any language, or `CRB_BUILDER__IMAGE_LANGUAGES` lists a language while
  `CRB_BUILDER__IMAGE` is empty, the API and the worker log a warning at start and the docker
  probe reports `degraded`; a worker whose `CRB_WORKER_LANGUAGES` names a language with no
  builder image logs a warning naming `CRB_BUILDER__IMAGE_<LANG>`. A warning, not a refusal:
  a worker may legitimately start before its images are configured, and every run it would
  build is refused with the variable to set.

**3. Queue language affinity.** A worker may name the languages it serves
(`CRB_WORKER_LANGUAGES` or `crb worker --languages`; empty means every language).
`JobQueue.claim_next(languages=…)` then claims only runs whose repository's
`repos.language` is in the list, inside the same locked, `SKIP LOCKED` claim, and the
cancel-finalise behaviour is unchanged (a cancel-requested queued run it would serve is
finalised, others are left for their own worker). "One worker per language" is now a
setting, not advice; one worker can also serve several languages with several images.

## Consequences

- **Breaking, deliberately.** A deployment that set only `CRB_BUILDER__IMAGE` had that image
  used for every language. It now has every sealed build refused, with the variable to set
  named in the refusal. Setting `CRB_BUILDER__IMAGE_LANGUAGES=python` (or the language its
  image is) restores the previous behaviour for that language only. A deployment whose
  repositories rely on `CRB_SANDBOX__IMAGE` sets each repository's `sandbox_image`, or opts
  in with `CRB_SANDBOX__ALLOW_DEFAULT_IMAGE=1` and accepts the recorded event.
- A run whose repository has no `repos` row has no language to match, so a worker with a
  language list never claims it; only a worker serving every language does.
- A refused run writes no ledger row and spends nothing; the refusal is an event on the run.
- `GET /repos/{name}/posture` and the run's posture gate predict what the worker will do:
  for a docker deployment and a repository with no `sandbox_image` (opt-in off) they name no
  image and no posture, and the Posture panel says the run is refused
  (`sandbox_image_missing`) and what to set, rather than reading the posture of the
  deployment's default image.
- `queue_position` on `GET /runs/{id}` stays global across languages: under
  `CRB_WORKER_LANGUAGES` it is an upper bound on a run's place, not its exact one.
- The builder container settings keep their fields (one `image`), so the posture
  fingerprint of a run that is built is unchanged.

## Alternatives considered

- **Keep one image per worker and document it.** That was the state before this change, and
  it failed silently. Rejected.
- **Fall back to `CRB_BUILDER__IMAGE` when no per-language image is set.** It is the same
  silent mismatch with one more variable. Rejected: an image serves the languages it is
  declared for.
- **Read the language from image labels.** It needs a label convention on every image the
  operator builds and a daemon call to read it. Rejected for now: an environment list is
  explicit and checkable at start-up.
- **Route by language without refusing.** Affinity alone leaves a worker that serves every
  language free to build any run in the wrong image. Rejected: the refusal is the guarantee;
  affinity is how a deployment avoids meeting it.
