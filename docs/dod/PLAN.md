# The plan — four waves, each closing named gaps

`GAP-ANALYSIS.md` is the order of work; this is the batching: which gaps travel together,
why, and what "done" looks like when the wave lands. Every wave is one pull request per
stream, merged onto one branch, attacked by adversarial verifiers, then merged to `main`
**with its definition-of-done artefacts updated in the same pull request** — a criterion
flips to `met` only when the evidence it cites resolves (`scripts/dod_check.py`).

The rule that governs this file: nothing enters a wave that is not a gap id in
`GAP-ANALYSIS.md`. If something must be built that no artefact names, the artefact is wrong
— fix the artefact first.

## Wave 0 — land what is in flight (today)

| item | state |
|---|---|
| #46 the hint layer on all 21 routes + the factory loop (fetch-before-run, outcome sync, evolutions) | in CI |
| this branch — the definition of done, the checker, the `dod` CI job | opens when #46 lands |

## Wave 1 — the work arrives, and the product answers

*Why first: the top gap of `manufacture-and-deliver` is that no work reaches the factory from
a tracker, and the one below it is that a ticket would stop at `no_oracle` anyway. Together
they are the enterprise's on-ramp: a ticket moves into a column and the product replies.*

| stream | gaps closed | what ships |
|---|---|---|
| **I — intake** | closed: G-900, G-901, G-332, G-902, G-333, G-334, G-335, G-336, G-903, G-337 · opened: G-928 (the time from column entry to pull request, and the £ per ticket, are not measured — that needs a timed pass on a real column, which costs model spend this wave deliberately did not make) | `intake` settings block + tracker secret; `src/crb/intake/{ado,jira}.py` behind one `TrackerClient` protocol; a worker poll with an idempotency key; the readiness-comment renderer (missing slots + the cell's route, n, interval); freeze-from-ticket; the outcome → ticket-state mapping; `GET /factory/{repo}/intake` and the `/factory/intake` screen, hinted and ratcheted; fake-tracker tests; `12-intake.spec.ts`; an ADR, API rows, an OPERATOR section, a SECURITY egress row |
| **T — the test author** | closed: G-904 | the served worker wires a test-author rung behind the same refusal that stops a rung authoring its own oracle, so a value-gap item no longer stops `no_oracle`; the superseding item offered pre-filled on a weak-oracle verdict |
| **E — evidence & explanation** | partly: G-910 (the four jobs run on every pull request but are not on branch protection's required list — G-930) · closed: G-906, G-921, G-918, G-287 · partly: G-905 (6 of 11 — the per-screen keyboard steps are not done), G-917 (3 of 4), G-909 (3 of 5) · opened: G-926 (the four shell screens carry no About block), G-927 (two sign-in stops still have no way forward) · measured, not fixed: G-292 | the UI gates run in CI (`tsc -b`, vitest, the ratchet, the mocked smoke spec — 7 criteria); the 11-screens keyboard pass and the 375-px `scrollWidth` check cover every route, not two (11 criteria); `/login`, `/help`, `/help/docs/:name` and `*` get a `SCREENS` entry and a `MIN_HINTS` floor, so the ratchet stops skipping four shell screens (5); the last six native `title=` tooltips are retired (6); `/` is visited by a test (4); `/login` says who resets a password and the 404 is axe-swept (4+) |
| **C — claims** | closed: G-603 · opened: G-929 | `scripts/claims_check.py` + a `claims` CI job: every quantified sentence on a covered page carries one of `[measured]` / `[hypothesis]` / `[aspiration]` / `[gap]`, and a `[measured]` one carries n, method and apparatus; the two wrong claims on `main` corrected (README's "eleven jobs"; RELEASING's `[aspiration]` ruleset). The allowlist is **two pages** — `README.md` and `docs/RELEASING.md` — not the six kinds of page this row first named: SECURITY, DEPLOYMENT, OPERATOR, ARCHITECTURE, the reviews and the book are still ungated, which is G-929 and why `product.claims.21` stays `partial` |

**Stream E rides with this wave because its gaps have the highest fan-out in the whole tree — G-910 and G-905 alone
close 18 criteria **[measured — n = 2 gaps, method: the `blocks` column of `docs/dod/GAP-ANALYSIS.md`
(7 + 11), apparatus 2.2]** for about a day's work **[hypothesis]** — and it touches no file the other three
streams own.**

**Done when:** a ticket moved into a watched column on a test project produces a gap comment
on that ticket, and a ticket with a testable acceptance criterion produces a pull request on
the customer's repository with the link posted back — walked by `12-intake.spec.ts`.

**What the wave actually proved.** The first half is walked end to end: `12-intake.spec.ts`
drives a file-backed fake tracker through column → one marked comment → edit → re-read →
registered and `crb:queued` → the item on the Factory screen, and proves a re-read of an
unchanged column writes nothing. The second half — a real pull request from a ticket — is
**not** proved here: the wave made no model or builder API call by design, so the author rung,
the delivery path and the outcome mapping are proved against fakes at the unit level and the
priced end-to-end pass is still owed. That, and the time and cost per ticket, is G-928.

## Wave 2 — the product proposes the next action

*Why second: every stream's top gap is the same — the parts exist, nothing sequences them.
This is what makes the workflow easy for an enterprise to follow.*

| stream | gaps closed | what ships |
|---|---|---|
| **S1 — connect & prove** | G-500, G-431, G-432, G-428 | the next £0 stage is queued when the previous one passes (opt-in per repository); each `gold_note` becomes a named candidate config change to accept or reject; re-qualify selected tasks from the Tasks tab; a controls escape links to the weak task's escaped mutants and a strengthening item |
| **S2 — measure** | G-565, G-564 | every under-bar cell serves "n needed and what it costs" with the run body pre-filled |
| **S3 — learn** | G-532 | the three write paths behind the same named-person decision the CLI already requires: accept a refusal line, register a strengthening item, queue a re-measurement |
| **S4 — decide & license** | G-518, G-516, G-517 | an approver invitation with a one-time link; Home task 7 reads the deployment's real two-person readiness, not the presence of an admin |

**Done when:** from Home, an operator can reach the next action of every stream in one click,
and no stream's top gap is `AUTOMATION`.

## Wave 3 — the screens for what the server already does, and the measures

| stream | gaps closed | what ships |
|---|---|---|
| **U1 — users** | F23 (UI half) | Settings → Users: active toggle with the last-admin reason, last sign-in, set password; the account's `user.*` events served and shown |
| **U2 — factory** | B-9, F32 | outcome pills with the pull-request link and synced-at; "Sync outcomes"; the evolution form; `way_forward` as a link |
| **U3 — phone** | F26 | navigation collapses under 640 px; no horizontal scroll at 375 on any route |
| **M — measures** | G-925 (one gap, five streams) | lead time and cost per certified change derived from the events already stored, shown on the stream's own screen |
| **R — roles** | G-919, G-920 | `/learn` and `/oracle` nav entries match their viewer-readable routes |

## Wave 4 — go-live truth and the release

| gaps closed | what ships |
|---|---|
| G-602, G-601 | every go-live line carries a product-side state (proven / attested with a dated operator record / unproven); a `PrometheusRule` manifest ships so the alert rules are not retyped; the ledger's last `row_hash` is anchored outside the store it protects |
| G-604, F51 | the `2.0.0b1` cut per `RELEASING.md`; the `events` table hash-chained |
| F42 part 2, F43, F46 | operator-owned: a measurement under the docker posture, OIDC against a live provider, a penetration test |

## What each wave must do to its own artefacts

1. Flip the criteria it closes to `met` with evidence that resolves — in the same pull request.
2. Add a criterion for anything it builds that no criterion covered (and say so in the PR).
3. Regenerate `GAP-ANALYSIS.md` (`python scripts/dod_check.py`) and commit it.
4. Never delete a gap without either closing it or recording why it is `n/a`.
