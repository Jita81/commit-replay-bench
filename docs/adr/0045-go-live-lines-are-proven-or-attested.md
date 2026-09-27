# ADR-0045 — Each go-live line is proven by the product or attested by a named admin, and the sealed posture runs without a hand in the store

**Status:** Proposed (DL-124, DL-125, DL-126; north-star Wave 4, stream P — G-317 and the
lines it unifies, G-950, G-951, G-966). Amends ADR-0019 on three points (§4 to §6).
**Date:** 2026-09-27
**Apparatus impact:** none. No belt, size, class, route or threshold changes meaning. The
go-live reading writes only system events on its own trace. Reading `uv.lock`, `poetry.lock`
and `pylock.toml` admits Python repositories that were refused before; each is read into the
same pinned, hashed set a requirements lock gives, fetched by the same recipe
(`py.site.v1`), so a set sealed from one reads the same as a set sealed from the other.
Quarantine changes what happens to a damaged set after `BUNDLE_INTEGRITY`, not when that
refusal fires.

## Context

DEPLOYMENT §8, the go-live checklist, was a list of boxes to tick. The Deployment page
(`/posture`) said nothing about any of its lines. A review board could not tell which lines
held, which had been checked and by whom, or which nobody had looked at (G-317, G-584). Five
of the fourteen lines are facts the product already reads: the health check, the ledger
verification, how people sign in, whether each repository qualifies in the sealed posture,
and whether tests and the builder run sealed. The other nine are acts only the operator can
do on their own infrastructure, such as an egress test from a worker pod, a rehearsed restore
or a penetration test. The product cannot see them.

Three operating gaps kept the sealed posture from going live without a person's hand:

- a registry mirror that needs a credential had no way to pass one into the fetch container
  (G-950);
- Python repositories locked with uv, poetry or PEP 751 were refused
  `PROVISION_LOCK_UNSUPPORTED` (G-951);
- a sealed set that failed its digest stopped the run, and then the operator had to delete
  its directory from the store by hand. The qualifications that cited it stayed in force
  **[measured — n = 1 damaged set; method: the module cache of cobra 746ef07's set emptied,
  `crb deps verify` reported it and left it in place; apparatus 2.3;
  docs/reviews/2026-09-25-sealed-posture.md]** (G-966).

## Decision

1. **Every go-live line has exactly one state.** `crb.server.golive.LINES` holds the lines
   of DEPLOYMENT §8 in the guide's order. Each line says who proves it (`product` or
   `operator`), where its state comes from, and which part of the guide it is. `GET /golive`
   (any signed-in role) reads each line as one of three states:
   - **proven**: a product line whose check passed when this request ran it;
   - **attested**: an operator line with an admin's record in force;
   - **unproven**: anything else, with the reason.

   A test fails when a line in the guide and a line in the code disagree on either its id
   or its kind.
2. **The product's checks are its own reads, never a setting's say-so.** Each check reads
   live data:
   - `health-green` reads every probe of `/health` (each `ok` or `skipped`);
   - `ledger-verified` reads `/ledger/verify` (chain intact, false-Q1 = 0);
   - `sign-in` needs all four of these: an account from the identity provider has signed
     in, which is the live proof that OIDC works; local sign-in is off; no bootstrap admin
     is configured; and every active local admin has had a password set since it was
     created;
   - `repos-qualified` needs every connected repository to have a task qualified in a
     docker posture, and the `provision` probe not to be `down`;
   - `sealed-posture` reads `/health`'s posture.

   A failed read is the line's reason, never a 500.
3. **An attestation is an operator act recorded through the product, and it cannot stand in
   for a check.** `PUT /settings/attestations/{line}` (admin) takes what was done (1 to 500
   characters) and the day it was done (never in the future). It writes one
   `golive.attested` event on the `golive` system trace, naming the admin as its actor.
   `DELETE` writes `golive.withdrawn`, and the line reads unproven again. Events are
   append-only, so an attestation is never edited. The product refuses:
   - a product line: `409 proven_by_product`. A person's word cannot replace a check the
     product runs;
   - an unknown line: `404 unknown_line`;
   - a withdrawal with nothing in force: `409 not_attested`.

   Nothing writes an attestation except that route. A line reads `attested` only when a
   person recorded it.
4. **A private mirror's credential reaches the fetch container, and only it** (amends
   ADR-0019 §6; DL-126). `CRB_PROVISION__MIRROR_CREDENTIAL_ENV` holds the name of a worker
   variable, never the credential itself. Only a networked `fetch` step to a registry that
   is not public carries it. It is passed by name (`--env CRB_MIRROR_CREDENTIAL`), so the
   value is on no command line. A shell prelude writes it to the owner-only `.netrc` or
   `.npmrc` the toolchain reads, then unsets it. Any output that is kept is scrubbed of it.
   An install or rebuild step, a test container, a builder and every other docker call build
   their environment from an allowlist that cannot name it.
5. **uv, poetry and pylock locks are read** (amends ADR-0019 §6 and its list of refusals; DL-125).
   Each is read from git objects into the same `PyPin` set a requirements lock gives: exact
   versions, `sha256` hashes, and markers joined from the dependency edges. The project and
   its workspace members are the repository's own code and are never fetched. A git, URL,
   file or outside-path source is `PROVISION_SOURCE_REFUSED`, and a pylock with
   `lock-version` other than `1.x` is `PROVISION_LOCK_UNSUPPORTED`. A pinned requirements
   file still wins when both are committed. `Pipfile.lock` stays refused.
6. **A damaged set is quarantined, not reused, and what cites it is revoked** (amends
   ADR-0019 §9's `BUNDLE_INTEGRITY` row; DL-126). When the provider's `verify` finds a set
   that fails its digest, it moves the set to `<store>/.quarantine/<lang>/<key>.<time>` with
   a record of why (`provision.quarantined`), and names the key on the refusal. The posture
   gate then revokes every qualification in force whose `deps.keys` cites it: one new
   `revoked` row each, coded `BUNDLE_INTEGRITY` (`provision.revoked`). The key is then a
   miss, so the next run that needs it fetches and seals it afresh. The damaged bytes are
   kept for whoever investigates and are never mounted again. Between runs,
   `crb deps verify --quarantine` does the same. Nothing is deleted by hand.

## Consequences

**What becomes easier.**
- A review board reads the go-live state on the page it already reads (`/posture`), and can
  print it. Each line shows its state, the reason and its source, and each attested line
  shows who recorded it, the day of the act and the admin's words.
- The run-the-platform stream counts its own go-live lines from the same reading: `/flow`'s
  `golive_*` counts replace a "not captured" entry.
- Organisations whose mirror needs a login, and Python repositories on uv, poetry or
  pylock, can run sealed.
- A damaged set no longer needs someone with shell access to the store.

**What becomes harder.**
- Adding a line to DEPLOYMENT §8 now means adding it to `LINES` in the same change. The
  guide-and-code test makes this impossible to forget.
- An attestation is a claim by a named person, not a verification. The page says so in the
  pill's hint and in the Claims line of `golive.py`, and a board must read it as such.
- A structured lock's markers are joined from its edges. A lock that uses a construct the
  reader does not model is refused with its path; it is never guessed.

**What we must never do.**
- Let an attestation stand in for a line the product proves, or write one on anyone's behalf.
- Edit or delete an attestation event; withdraw it with a new event instead.
- Put a mirror credential's value on a command line, in a setting, in a view or in a log,
  or give it to a test container or a builder.
- Mount a set that failed its digest, or leave a qualification in force that cites one.

## Alternatives considered

- **A checkbox per line in the UI, stored as a setting.** Rejected: a setting has no author
  and no date, and can be flipped by anyone who can write settings. An event on its own trace
  names who did it and when, and cannot be edited.
- **Let an admin attest a product line when the check is flaky.** Rejected: that is ticking
  by belief. A flaky check is a defect to fix in the check.
- **Pass the mirror credential as `--env NAME=value` or in a mounted file.** Rejected: the
  value would be visible in the process list or would need a file on the worker's disk. Passing
  it by name to the one client process keeps it in memory, and only for as long as the fetch
  runs.
- **Delete the damaged set.** Rejected: that destroys the evidence of what went wrong.
  Quarantine keeps it, and the store's key space treats it exactly as a deletion would.
