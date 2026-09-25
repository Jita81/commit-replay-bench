# ADR-0023 — Production refuses the unsealed posture unless an evented override says so

**Status:** Proposed
**Date:** 2026-09-25
**Apparatus impact:** none (no belt, size, class, route or threshold changes meaning; a run
produced under the override is marked on its apparatus as `unsealed_prod_override`, so it is
always distinguishable from a sealed run). Amends ADR-0005 and ADR-0012: the sealed posture
stops being opt-in in production.

## Context

The assessment of 2026-09-25 (item B2) found that in `CRB_ENV=prod` the builder defaulted to
the host (`CRB_BUILDER__EXECUTOR=host`, `crb.server.settings.BuilderSettings`) and that the
host builder or a `local` test executor produced only a log warning. In host mode
`claude -p` runs with Bash, `--permission-mode dontAsk`, the API key in its environment and
the gold commit reachable through the shared object store, as the worker user. The worker
itself did not read `CRB_ENV` at all, and its test executor defaulted to `local`
(`crb.server.worker_main`). [measured — reproduced against `main` at `8ab88ad` by
`tests/test_settings_posture.py` before the change: `Settings(env="prod",
sandbox={"executor": "local"})` and `builder={"executor": "host"}` constructed; the builder
default read `host`; `crb worker` accepted both]

Every ledger row to date is `executor: local` (CHANGELOG, "Evidence caveat for this
release"). A deployment could therefore run in production on a posture whose numbers the
product's own policy calls a development reading, and nothing on the record would say so
unless someone read the apparatus stamp's executor field.

## Decision

1. **One rule, both processes.** `crb.server.settings.unsealed_prod_refusal(env,
   sandbox_executor, builder_executor, allow=)` returns why a posture may not run. In `prod`
   a test executor or a builder executor that is not `docker` is refused unless
   `allow` (`CRB_ALLOW_UNSEALED_PROD=1`). `Settings` (the API) raises on it at construction;
   `crb.server.worker_main.settings_from_args` (the worker) raises on it before the worker
   starts. `dev` is never refused.
2. **The sealed posture is the production default.** Unset `CRB_BUILDER__EXECUTOR` resolves to
   `docker` in `prod` and `host` in `dev` (`default_builder_executor`); the worker's test
   executor defaults to `docker` in `prod` and `local` in `dev`. An EXPLICIT
   `CRB_BUILDER__EXECUTOR=docker` still needs `CRB_BUILDER__IMAGE` at start-up (a typo fails
   early); the defaulted one does not, and the worker fails each build closed without it
   (`SandboxUnavailable`, never a host attempt). `deploy/docker-compose.yml` and the Helm
   chart (`worker.builder.executor: docker`) set the sealed builder on the worker.
3. **The override is evented and visible.** With `CRB_ALLOW_UNSEALED_PROD=1` and an unsealed
   posture, the API logs a warning and `Settings.posture()` reports
   `unsealed_prod_override: true` on `/health` (`crb.server.routes.system.collect_health`),
   on `/settings`, and on the Posture page to every viewer. The worker stamps
   `unsealed_prod_override` (env, both executors, the variable's name, this ADR) into every
   run's apparatus (`Worker._override_stamp`) — for a replay, into `RunSpec.extra` and so into
   every evidence pack. An override that is set but not needed is not reported as in force.
4. **A run cannot ask its way round it.** A `prod` worker without the override refuses a run
   whose own parameters ask for the `local` executor (`Worker._executor` raises
   `SandboxUnavailable`; the run fails with the reason). The builder executor was already a
   deployment posture, never a run parameter (ADR-0012).

## Consequences

- A production deployment that has not provisioned Docker for the worker now fails closed:
  runs end `sandbox unavailable` instead of producing host-posture rows. That is the intent.
- An operator who wants a production evaluation on the host posture must say so, once, with
  a variable whose name states what it does; every row it produces carries the statement.
- `crb worker` with `CRB_ENV` unset now reads `prod` (as the API always did) and defaults to
  `docker`. A developer running the worker by hand sets `CRB_ENV=dev`.
- We must never add a per-run way back to the host builder, nor treat a row stamped
  `unsealed_prod_override` as evidence for routing or sign-off.
- The refusal proves a setting, not a measurement: no row has yet been produced on the sealed
  posture (assessment item B3 remains open). [gap]

## Alternatives considered

- **Keep the warning.** Rejected: a log line is not on the record, and the assessment found
  the posture unstated wherever it mattered.
- **Refuse with no override.** Rejected: a throwaway evaluation on a server without Docker is
  a legitimate operator choice; the rule is that it is visible and stamped, not impossible.
- **Enforce only in the API's `Settings`.** Rejected: the worker is the process that runs
  builds, reads its own environment and, until now, did not know `CRB_ENV`; enforcing in one
  process would repeat the 2026-09-21 drift where `/settings` said `docker` while the worker
  ran `local`.
- **Bump the apparatus.** Rejected: no verdict changes meaning; the executor was already on
  the stamp, and the override is an additional, explicit field.
