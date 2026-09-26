# ADR-0027 — Automatic sign-in for a development stack, on loopback only

**Status:** Accepted (operator request 2026-09-26; decision DL-054, which may be renumbered at merge)
**Date:** 2026-09-26 (amended the same day after a security review: points 2, 3, 5 and 7)
**Apparatus impact:** none — this changes who is signed in on a development stack, never
what a belt means, how a cell is keyed or how a route is decided.

## Context

Before the open beta, the person running the product is usually its only user, on their
own computer. The operator asked, on 2026-09-26, why they still have to type a password to
use their own local stack. Every visit to a fresh browser, every session that ends after
`CRB_SESSION_TTL`, and every agent that drives the UI on their behalf meets the sign-in form.

Removing the sign-in is not an option: the same code runs in production, where the session
is what carries the role ladder, the CSRF defence, the audit actor and the two-person rule
(ADR-0016). A switch that turns sign-in off would be one environment variable away from an
unauthenticated production deployment.

## Decision

1. **One setting, off by default.** `CRB_AUTH__DEV_AUTOLOGIN=<username>` names one local
   account (`crb.server.settings.AuthSettings`). Empty means off.
2. **Refused where it may not run, with no override.** `Settings` refuses to construct with
   it set unless `CRB_ENV=dev` and `CRB_BIND_HOST` is a loopback address
   (`dev_autologin_refusal_for`). `crb.server.main.serve` checks the address it is about to
   bind again, because `crb serve --host` never passes through the settings. `prod`, and any
   other value of `CRB_ENV`, refuses. The container entrypoint refuses to run any role with the
   variable set: a container is never a development stack on one machine. A process manager
   that runs `uvicorn --factory` itself binds an address `crb` never sees; there the start-up
   check cannot run, and only the per-request checks in point 3 apply.
3. **Admitted per request only when the request is plainly local**
   (`crb.server.auth.dev_autologin_refusal`): the TCP peer is loopback; the connection
   arrived on a loopback address (the ASGI `server` address, which covers a bind `crb` could
   not check); no forwarding header (`Forwarded`, `X-Forwarded-*`, `X-Real-IP`, `Via` and the
   client-address headers proxies, CDNs and tunnels add, listed in `FORWARDING_HEADERS`); the
   `Host` header names this machine; an `Origin`, when sent, is a loopback origin; the browser
   did not mark it `cross-site`. Anything else gets the same 404 `dev_autologin_off` as "off",
   and `/health` and `/version` tell it `off` too (point 5), so a request from another machine
   cannot tell a stack with it on from one without. The reason goes to the log.
4. **An ordinary session through the existing machinery.** `POST /auth/dev-autologin` looks
   the account up with `find_local_user`, refuses a missing or disabled one (403
   `dev_autologin_unavailable`, the log says which), and then sets the same cookies as
   `POST /auth/login` (`set_session_cookie` bound to the credential version,
   `set_csrf_cookie`). Nothing downstream knows how the session began, so CSRF, roles,
   sign-out and a password change behave as they do after a typed password. The route is
   not exempt from the CSRF check.
5. **Recorded and visible.** Every sign-in appends `auth.dev_autologin` on the account's
   trace (actor = the account, `payload.client` = the peer) and logs one warning line.
   Start-up logs a warning. `GET /health` and `GET /version` carry `dev_autologin`, which
   reads `on` only for a caller that point 3 would sign in and `off` for everyone else;
   `crb doctor` reads the settings directly and has a `dev_autologin` line that warns while it
   is on; the UI shows a hinted banner on every page, the sign-in page included.
6. **The UI asks, the server decides.** `useMe` asks for an automatic sign-in only when
   `/auth/me` says there is no session and `/version` says it is on. After Sign out it does
   not ask again in the same page load, so signing out lands on the form; a reload asks
   again under the same conditions.
7. **The project's own proxy marks what it forwards.** The Vite dev server and
   `vite preview` forward `/api` from `127.0.0.1` and pass on the client's `Host`, so on their
   own they would make a request from another machine (the dev server started with `--host`)
   look local. `ui/vite.config.ts` adds `X-Forwarded-For` to every request whose client is not
   loopback, or is unknown (`ui/src/dev/apiProxy.ts`), before the proxy copies the headers,
   and point 3 refuses it. A browser on the same machine is not marked and is signed in.

## Consequences

- The operator's local stack opens signed in, and an agent driving a browser on the same
  machine needs no password.
- A production deployment cannot enable it: `prod` refuses to start, `crb serve` refuses a
  non-loopback bind, and the published image refuses to run any role with it set.
- `uvicorn --factory` run by a process manager is not checked at start-up; the local-address
  and peer checks still refuse every request that arrives on a network interface.
- Every local user and process on the machine can use it, not only the person who switched
  it on. It is for a personal development machine; `docs/SECURITY.md` §3.8 says so.
- A reverse proxy or tunnel on the same machine that strips or never sets forwarding headers
  would expose it. We must never document one in front of a stack with it on, and the one
  proxy the project ships (Vite's) must keep marking off-machine requests
  (`ui/src/dev/apiProxy.test.ts` fails if it stops).
- We must never add an override flag, a non-loopback exception or a path that issues a
  session without `set_session_cookie`.

## Alternatives considered

- **A flag that turns authentication off in dev.** Rejected: every route would need a
  second code path, the audit actor would be empty and the role ladder untested on it.
- **Sign in inside the `current_user` dependency.** Rejected: an unsafe request with no
  session cookie skips the CSRF check (there is no ambient credential to abuse), so signing
  it in inside the dependency would let a cross-site `POST` act as the account. A separate
  route issues the session first; every later request is CSRF-checked as usual.
- **Trust `X-Forwarded-For` from `CRB_TRUSTED_PROXIES`.** Rejected: the point is that a
  proxied request is never local, whatever the proxy says. Any forwarding header refuses.
- **Refuse it whenever `CRB_TRUSTED_PROXIES` is set.** Not adopted: the header check already
  refuses every proxied request, and a trusted-proxy list is not evidence that a proxy is
  in front of this particular stack.
