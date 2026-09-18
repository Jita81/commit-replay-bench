# ADR-0016 — The desktop app is a launcher, not a second front end; and what it launches cannot produce evidence

**Status:** Proposed (operator decision DL-044)
**Date:** 2026-09-18
**Apparatus impact:** none — deliberately. Packaging cannot move a verdict. No belt, no grader, no
routing threshold, no ledger row and no sign-off clause changes here. The apparatus stays 2.2 and
`signoff-policy.v2` is untouched. What changes is how the *same* server is started on one operator's
machine, and what that machine is then permitted to claim.

## Context

The front end is a single-page application served by the API process itself: `crb serve` mounts the
built SPA at `/` when `CRB_UI_DIST` names a directory containing `index.html`
(`src/crb/server/app.py`, `mount_ui`). Running the product today therefore means a terminal, a
Python 3.12 environment, the `[server]` extra, a migration and two environment variables. That is a
reasonable bar for a platform team and an unreasonable one for the tech lead in persona P3, who is
evaluating whether the instrument is worth an afternoon
(`docs/reviews/2026-09-17-enterprise-front-end.md` §2), and for the NHS/Kainos reviewer who wants to
see the screens before reading the architecture.

Three facts about the product make a desktop wrapper unusually cheap:

- the core engine imports nothing outside the standard library (ADR-0008), so the dependency surface
  to vendor is only the `[server]` extra;
- the store is SQLite by default (`sqlite:///{CRB_HOME}/crb.db`, `src/crb/store/db.py`), so there is
  no database to install;
- the API already serves the UI, so there is no second artefact to host.

One fact makes it dangerous. A MacBook Air has no Docker daemon unless the operator installed one.
The sandbox executor defaults to `docker` and fails closed (ADR-0005); the builder likewise
(ADR-0012). An app that "just works" on such a machine can only do so by relaxing the executor to
`local`, and a local executor means **test runs are not isolated**. The product's entire claim is
that a number is only evidence because of the conditions under which it was produced
(`docs/EVIDENCE-AND-CLAIMS.md` §4). A convenient laptop build that quietly produced numbers
indistinguishable from sealed ones would be the most damaging thing we could ship. [hypothesis]

## Decision

**1. The app is a launcher around the existing server, not a new front end.** `src/crb/desktop/` is
a standard-library-only package that prepares state, spawns `crb serve` as a child process, waits for
readiness and opens the operator's browser. It renders nothing. There is no second implementation of
any screen, and no code path that reaches the store or the core directly — enforced by the
import-linter contract, which places `crb.desktop` above `crb.cli` and forbids it the inner layers.

**2. It waits on `GET /api/v1/health/live`, never `/health`.** The SPA is mounted at `/` with an
`index.html` fallback for deep links, so *any* unmatched path answers 200 with HTML. A launcher that
polled `/health` would read a false ready signal from the static-file mount before the API existed.
`readiness_url` in `src/crb/desktop/server.py` names the versioned liveness route, and
`tests/test_desktop_launcher.py` pins it.

**3. The runtime is embedded, and the bundle is self-contained.** `macos/build_app.sh` vendors a
standalone CPython into `crb.app/Contents/Resources/python`, installs `commit-replay-bench[server]`
into it, and copies the built SPA to `Contents/Resources/ui`. Nothing is required on the target Mac
except macOS 12 and, for anything beyond browsing, `git`. The app does not create a virtual
environment, does not reach PyPI at run time and does not touch the operator's own Python.

**4. A desktop run is a development reading, and the app says so before it is believed.** The
launcher sets `CRB_SANDBOX__EXECUTOR=local` and `CRB_ROLE=api`. The first is what makes a
Docker-less Mac usable at all; the second stops the deep health check reporting `down` for a sandbox
this process was never going to own. Both are *stated*, not hidden:
`src/crb/desktop/preflight.py` reports the executor and the absence of `git` or Docker in the
first-run output, in the vocabulary the health probe already uses (`local executor — test runs are
NOT isolated (dev only)`, `src/crb/server/routes/system.py`).

This ADR does not add a new enforcement mechanism, and it must not be read as one. The existing
posture stamp on every row is what an approver reads; a sign-off made against host-posture rows is
refused or marked by the rules that already exist, not by anything in `crb.desktop`. What this ADR
commits to is that the desktop packaging never *weakens* those rules to make the app feel better,
and never presents a local-executor run as anything else.

**5. Signing is a distribution concern, and the two cases are kept apart.** An app built on the
machine that runs it carries no `com.apple.quarantine` attribute, so it opens on a double-click with
no Gatekeeper prompt and no Apple Developer account. A *downloaded* copy carries the attribute and
is refused until the bundle is signed with a Developer ID and notarised.
`.github/workflows/macos-app.yml` builds and smoke-tests unconditionally, and signs and notarises
only when the Apple secrets are present — so the workflow is green today and becomes a distribution
pipeline the day an account exists, with no edit.

**6. There is no unauthenticated mode, and the app does not invent one.** The server seeds a local
admin from `CRB_BOOTSTRAP_ADMIN__*` only while the users table is empty
(`bootstrap_admin_if_empty`, `src/crb/server/auth.py`). The launcher generates that password once,
stores it at `$CRB_HOME/first-run-credentials.txt` with mode 0600 and prints it on first run. It
does not add a token-login route, does not disable authentication and does not ship a default
password. The session signing key is likewise generated once and persisted, because an ephemeral key
would invalidate every session on every launch.

## Consequences

**Easier.** A reviewer can see the twelve screens on real data without a toolchain. The trial in
persona P3 starts at a double-click. The same bundle is the basis of a signed distribution later.

**Harder.** The macOS bundle can only be built and tested on macOS: `macos/build_app.sh` cannot run
in the Linux CI that gates every other job, so its proof is a separate workflow on a `macos-14`
runner, and a change to the launcher is not exercised by the main suite beyond
`tests/test_desktop_launcher.py`. The bundle embeds a Python runtime and therefore carries its own
CVE surface, refreshed only when the app is rebuilt; `pip-audit` in `ci.yml` covers the resolved
requirements, not the vendored interpreter.

**What we now must never do.** Never let the desktop path relax a belt, a threshold, a routing rule
or a sign-off clause to make the app work on a laptop — the executor is relaxed, nothing else, and
the relaxation is visible in the health payload and the first-run output. Never present a
host-posture or local-executor run as evidence. Never add an authentication bypass "just for
desktop". Never let `macos/` import from `crb.core`, `crb.store` or `crb.server`.

## Alternatives considered

**Electron or Tauri with a bundled front end.** Rejected: both add a second runtime (Node or Rust)
and a second copy of the UI build, to draw a window around a page the API already serves. Tauri
additionally cannot be cross-compiled, which buys nothing over a `.app` whose executable is a shell
script. The wrapper would be larger than the thing it wraps.

**A virtual environment created on first run from the user's Python.** Rejected: macOS ships no
usable Python, so the first run would fail on a clean machine with an error about a missing
interpreter — the worst possible first impression, and one that cannot be fixed from inside the app.
It also makes the app's behaviour depend on a runtime we do not control.

**Shipping with `CRB_SANDBOX__EXECUTOR=docker` and requiring Docker Desktop.** Rejected for the
trial case: it moves the install burden from "one double-click" to "install Docker Desktop first",
which is the bar we are trying to remove. The app detects a reachable daemon and reports it; an
operator who has one gets the sealed posture, and the routing and sign-off rules read the stamp
either way.

**A dedicated desktop login token.** Rejected as scope: it is a new authentication path on the
server, with its own security review, added to make a password prompt disappear once per machine.
The first-run credentials file is honest and costs the operator one paste.
