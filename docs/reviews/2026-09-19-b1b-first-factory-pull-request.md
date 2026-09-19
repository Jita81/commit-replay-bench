# B-1b — the first real factory pull requests — 2026-09-19

**Question asked:** can the factory take a real backlog item on a real repository from a frozen
backlog to a branch and a pull request, under the same governance as measurement — a RED proof
before any build, the four belts and the lint belt, the route gate on the signed map, an
independent review — with every step on the evidence chain? And what does it cost?

**Claims in this record.** Everything quoted from the run — the belts, the costs, the turns,
the token counts, the durations, the route line, the ledger count — is **[measured — run
`e9acd89c…`, apparatus 2.2, `routing.v1`, `claude_code / claude-sonnet-5`, sighted, local
executor; n = 2 items, 3 builds; read from `/runs/{id}`, `/factory/cobra/evidence` and the
three evidence packs named below]**. Two items is a demonstration, not a rate: no interval is
quoted for the factory itself, and none should be read into "2 of 2". The two rules that
follow from the findings are **[hypothesis]** until the fix PRs land with their tests; the
backlog file and the two Go tests beside this record are the *registered inputs* the ledger's
hashes name — they are kept byte-for-byte and carry no claim tags because they are not claims.

**Answer:** yes, twice, for $0.69 in total, on a development posture. Two pull requests were
opened on the fork [Jita81/cobra](https://github.com/Jita81/cobra) (`main` = `adbc881`,
byte-identical to `spf13/cobra` that day) — nothing was pushed to `main`, nothing to
`spf13/cobra`. The run also found two product defects and one thing the reviewer was right
about; they are the second half of this record.

## Method

One live deployment (`crb 2.0.0a1`, apparatus 2.2, `routing.v1`, `signoff-policy.v2`, main
`0ce10fc`), **local executor — a development reading, not evidence** (the sealed rerun under
the Docker executor is B-1). The operator's account queued the run; no separation of duties
was exercised because no structural gap needed a sign-off (F7b stands).

The chain, as the product recorded it (`GET /factory/cobra/evidence`, `run e9acd89c…`):

1. **Link.** The existing `cobra` row (36 tasks, 64 rows on the current apparatus) was linked
   to the GitHub App installation `#163031176` (`Contents: write`, `Pull requests: write`)
   through *Connection → Connect from GitHub → Link to an existing repository* (PR #34): the
   row kept its name and its evidence; its URL became `https://github.com/Jita81/cobra.git`;
   the events table carries `repo.github_linked` with both URLs.
2. **Freeze.** A two-item backlog, hash `d10c527f366f1dea…`, registered through the Factory
   page's *paste JSON* route with the operator-authored oracles (the file is
   [2026-09-19-b1b/backlog.json](2026-09-19-b1b/backlog.json); the tests are beside it). Both
   items are `bug.fix × S` on a cell the map licenses: `n=26 · 96 % [81 %, 99 %] · app 2.2`,
   route *deliver* under `routing.v1`.
3. **Run.** `kind factory · claude_code / claude-sonnet-5 · sighted · auth: cli · deliver on ·
   max_rework 1 · retain worktrees + transcripts`.

The items were authored the day before from real, open `spf13/cobra` issues, each with a Go
test proven RED at `adbc881` from a pristine clone, proven satisfiable by a throwaway fix that
was then discarded, and attacked by a second agent trying to pass the test with a wrong fix —
every first draft could be gamed (a name-match instead of an identity check; a hand-rolled flag
filter) and was strengthened until only a real fix passed. That process is
[described in the session notes](../../CHANGELOG.md) and the item descriptions carry its
constraints (for `cobra-1918`: "by identity of the cobra-built command objects, not by name").

## What happened, per item

| | `cobra-2154` | `cobra-1918` |
|---|---|---|
| Issue | [spf13/cobra#2154](https://github.com/spf13/cobra/issues/2154) — help function gets raw argv, not the positionals | [spf13/cobra#1918](https://github.com/spf13/cobra/issues/1918) — `help` / `completion` refused when a persistent flag is required |
| Authored oracle | `help_func_args_issue2154_test.go`, sha256 `616342ad…` | `help_required_flags_issue1918_test.go`, sha256 `b81036cc…` |
| RED proof at `adbc881` | 14 failing ids, 2.4 s | 12 failing ids |
| Build (trial r1) | clean under all five belts; `command.go` +7/−3, `src_churn` 10 → measured **S**; 16 turns, 388k in / 3.3k out, **$0.226**, 61 s | clean under all five belts; `command.go` + `completions.go`, measured **S**; 21 turns, 577k in / 4.8k out, **$0.241**, 468 s |
| Delivery | branch `crb/cobra-2154-pass-the-helped-command-s-positional-arg` → [PR #1](https://github.com/Jita81/cobra/pull/1), base `main` | branch `crb/cobra-1918-built-in-help-and-completion-commands-fa` → [PR #2](https://github.com/Jita81/cobra/pull/2), base `main` |
| Independent review | **accept_with_edit** — one major finding, `weak_oracle`: "the oracle misses fault classes in the delivered change — strengthen the test: statement deleted" | **accept** — no findings; oracle strength on the delivered change 0.818 |
| Rework | permitted after the verdict (`edit.permitted`), RED re-proved, rebuilt clean: `src_churn` 6 → measured **XS**, 19 turns, **$0.224**, 90 s — **then the push to the PR branch was refused** (finding 1) | — |
| Outcome | `delivery_failed` (PR #1 open with build 1; the rework never reached it) | `accepted` |
| Evidence packs | `269cfd93…` (build 1), `cdcd2bbf…` (rework) | `2438fa70…` |
| Ledger rows | `3416f2fa…`, and the rework's | `b79c22ec…` |

Totals: 3 builds, 3 clean, 0 disqualified, 0 harness errors, **$0.69**, 11 min wall clock
**[measured — `/runs/e9acd89c…`, apparatus 2.2, local executor: a development reading]**.

The fixes themselves, for a reader who knows cobra: PR #1 passes `cmd.Flags().Args()` to the
help function in the `flag.ErrHelp` branch and `Find`'s remaining args from the `help` command;
PR #2 marks the help and completion literals with an unexported `skipRequiredFlagValidation`
and checks it beside `DisableFlagParsing` — the identity-based shape the item asked for, not
the name-match the adversarial pass had shown would slip through a weaker test.

## Findings

1. **Re-delivery after `accept_with_edit` cannot update the pull request** (product defect,
   `src/crb/factory/delivery.py`). The rework's push used `--force-with-lease` with no expected
   value; because delivery pushes to a URL, not a named remote, there is no remote-tracking ref
   to lease against and git answers `[rejected] … (stale info)`. So the loop did what the
   design says — reviewed, permitted the edit, re-proved RED, rebuilt clean — and then could not
   put the better build where the reviewer would see it. The item ends `delivery_failed` with a
   live PR carrying the weaker build. Fix: lease against the commit the first delivery pushed
   (`--force-with-lease=<branch>:<sha>`), and on re-delivery update the existing PR instead of
   opening a second one. Until then, one rework is one wasted build ($0.22 here).
2. **The route gate reads the map *after* the item's own row lands.** The `deliver` line in
   both PR bodies says `n=27`; the cell had `n=26` when the backlog was frozen. The build's
   ledger row is appended at `build.graded`, and the gate is evaluated at delivery, so a clean
   build nudges its own cell's point before the decision to deliver it. It changed nothing here
   (26 or 27 both route *deliver*) but it is circular at the margin: the map that licenses a
   delivery should be the map as it stood before this attempt. Fix: evaluate the route once, at
   readiness, from rows that precede the run, and stamp that decision on the item.
3. **The reviewer was right about the oracle — and the rebuild made it worse.** Our
   adversarial pass had attacked the test against the *unfixed* code; the reviewer attacked it
   against the *delivered* code and found that deleting the `if cmd.DisableFlagParsing {
   helpArgs = flags }` guard still passes — the item's own caveat ("DisableFlagParsing edge …
   not asserted") made real. A second gap, found in review of this record: `help sub --count 3
   arg1` through the built-in `help` command is not asserted either, so a fix that forwards the
   help command's remaining arguments raw (which is what build 1 does) passes. The rework then
   showed the sharper defect: this deployment has **no test-author rung**, so the loop rebuilt
   against the *same* oracle, and the builder found another way to pass it — a 6-line change
   that drops the `DisableFlagParsing` guard, a regression nothing tests. Finding 1 is the only
   reason that build is not on PR #1. Rule (in the fix PR): a `weak_oracle` verdict must never
   trigger a rebuild against an unchanged oracle — without a test author the item stops and
   routes to a human; with one, the oracle's hash must change first. PR #1 is **held**, with
   this on the PR; the strengthened oracle (both cases) goes in as a superseding item and the
   factory delivers the build that passes it. The frozen test file beside this record is not
   edited: it is what hash `616342ad…` names.
4. **"Run the factory" from the UI posted no builder** (HTTP 422) — known from the journeys
   audit (J-FAC-1); the run was queued through the product's API with the builder the Measure
   page derives. The fix is on the journeys branch.
5. **The deployment lived in `/private/tmp`**, where macOS deletes untouched files after
   about three days: it removed the stored Claude Code token, the restart script and the
   `HEAD` and `config` of every clone before the run. The stack now lives in `~/crb-stack`;
   docs/DEPLOYMENT.md should say so for any operator running a trial on a Mac.

## What is honest about the dev ledger after this

- Both pull requests target `main` on the fork from `crb/…` branches; `assert_not_default_branch`
  and the `branch:branch` refspec are the code's guards; branch protection on the fork's
  `main` is the deployment-side guard and was not yet enabled when this ran.
- Three factory rows joined the cobra ledger under the `process: factory` label. They were
  built against operator-authored oracles, not mined commits; a reader pooling the cell should
  know the map now mixes the two (finding 2 is the sharper version of this).
- 602 → 605 rows, chain intact, false-Q1 0 **[measured — `/ledger/verify` after the run]**.

## How to repeat it

```bash
# the items and oracles are in docs/reviews/2026-09-19-b1b/; register them through the Factory
# page (paste JSON) against a repository linked to a writable installation, then:
curl -s -X POST http://127.0.0.1:8000/api/v1/runs -H 'Content-Type: application/json' \
  -H "X-CSRF-Token: $CSRF" --cookie "$COOKIE" \
  -d '{"repo":"cobra","kind":"factory","mode":"sighted","builder":"claude_code","model":"claude-sonnet-5","builder_config":{"auth":"cli"},"deliver":true,"max_rework":1,"retain":{"worktrees":true,"transcripts":true}}'
```
