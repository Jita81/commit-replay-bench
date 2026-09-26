# Commit Replay Bench — a two-page summary

*For an NHS engineering or assurance reader deciding whether to put it on a repository.
Written 2026-09-25 against `main` (version 2.0.0a1, apparatus 2.2). Every figure carries its
tag ([Evidence and claims §1](EVIDENCE-AND-CLAIMS.md#1-claim-tags)); where this page and
the ledger disagree, the ledger is right.*

## What it is

Commit Replay Bench (`crb`) finds out which kinds of change an AI coding tool can make on
**your** repository, judged by **your** repository's own tests. It replays real commits
from the repository's history: it starts from the commit's parent, lets a builder (a model
driven by an agent such as Claude Code) attempt the change, and grades the result
mechanically. No model judges another model's work. This section and the next describe the
design **[aspiration — as ADR-0001, ADR-0003, ADR-0005 and ADR-0006 record it; what it has
shown so far is under *What the current evidence licenses*, and what it has not is under
*Open gaps*]**.

- **Where it runs.** Inside your own tenant, with your own model keys. The tests can run in
  a container with no network (the sealed posture), but every number published so far ran
  on the host (see Open gaps). Raw diffs and builder transcripts are not kept by default.
- **What it decides.** For each class and size of change it gives one route: `deliver`,
  `calibrate`, `granularize` or `human` ([ADR-0003](adr/0003-one-routing-rule.md)).
- **What it does with that.** For a class that routes `deliver`, its factory may open a
  branch and a pull request on your repository. It never merges; a person does.
- **What it learns.** It proposes; a named person acts. It lists the refusals worth a guard,
  with what each one cost; the tests worth strengthening, without a price; and the
  re-measurements that are due, with an estimate of their cost. A person decides
  ([Learning loop](LEARNING-LOOP.md)).
- **Licence.** Apache 2.0, so you can read and re-run the grader that judged your evidence.

## What it measures

What each check is, by design **[aspiration — ADR-0001 (the belts), ADR-0003 (the routing
rule), ADR-0009 (the mutation oracle), ADR-0010 (the negative controls) and ADR-0011 (the
linter belt); their results so far are under *What the current evidence licenses*]**:

| It measures | How |
|---|---|
| Whether one attempt is `clean` | Five belts: the target tests were not edited, they now pass, nothing else broke, source code changed, and the repository's own linter accepts the change. One failed belt means not clean. The linter belt runs only when the repository has a linter configured or detected; with none, or with the belt switched off, it is not evaluated and does not count against the attempt. |
| How often, per class and size of change | `n` attempts, the number clean, a Wilson 95% interval and the apparatus version, on every cell of the map. |
| How good your tests are as a judge | Oracle strength: the share of small faults planted on the changed lines that the target tests catch. |
| Whether the grader can be fooled | Negative controls: deliberate cheats (do nothing, stub the code, edit the test, and others) that must never grade clean. |
| What it costs | Mean cost and time per attempt, shown beside the rate. |

The published bar is meant to route a cell `deliver` only when `n` ≥ 10, the rate ≥ 0.90,
the interval's lower bound ≥ 0.80, there are no false passes, oracle strength ≥ 0.80 and the
controls passed. On `main` an unmeasured oracle strength does not block `deliver`; nor does
a controls verdict that was never evaluated when `crb route` reads a ledger file (the
server's map treats missing controls as `calibrate`); and `n` counts attempts, not tasks.
See Open gaps. A "false
pass" (false-Q1) is a row recorded clean that its own belts contradict; the product refuses
to write one ([ADR-0001](adr/0001-four-belts-and-false-q1-at-write.md)).

## What it refuses to claim

- That a passing test suite proves a change is correct. `clean` means the belts held.
- That `deliver` means safe to merge or deploy. It means a candidate a person reviews.
- Any throughput headline, such as changes per hour.
- That a sighted, historical rate is what the tool would do blind, or on future work.
- That a rate from one repository, model, budget or apparatus version carries to another.
- Anything about work that is not a source change with a test: architecture, migrations,
  security design, user research, clinical or financial risk.

The full list is [Evidence and claims §7](EVIDENCE-AND-CLAIMS.md#7-what-must-never-be-said).

## What it costs to onboard a repository

| Item | Cost |
|---|---|
| Developer time | About a working day, most of it describing the repository's layout and toolchain **[hypothesis — the onboarding guide's estimate from the repositories onboarded so far; not timed]** |
| Model spend | Roughly £0.20 to £0.60 per attempt with Claude Sonnet, and under £20 for a first useful picture of about 30 attempts **[hypothesis — the onboarding guide's band; a deployment's own mean cost per attempt, with its n, replaces it once measured]** |
| Platform | Docker for the test sandbox, PostgreSQL for the ledger, your identity provider (OIDC) for sign-in ([Deployment](DEPLOYMENT.md)) |

Nothing spends money until an operator queues a run that can be seen and cancelled. The
steps are in [Onboarding a repository](ONBOARDING-A-REPO.md).

## What the current evidence licenses

Everything in this section is **[measured — graded ledger rows re-derivable with `crb`,
sighted replay unless stated, `claude_code` with Claude Sonnet 5, on the host executor
posture, apparatus 2.2; the census rows (apparatus 1.0-census) are never pooled with them]**,
from the [NHS measurement](reviews/2026-09-14-nhs-public-repos.md) and the
[critical-friend review](reviews/2026-09-13-critical-friend.md):

- **The grader held.** Across n = 7 repositories — four public libraries and three NHS
  repositories — no row was recorded clean against its own belts, and the negative controls
  passed with 0 escapes wherever they were run.
- **One cell routes `deliver`.** cobra `bug.fix` XS: 22 of 22 attempts clean over 9
  distinct tasks. Nobody has signed it off.
- **NHS, sighted:** 15 of 18 gold-clean tasks clean, counting the linter pre-flight arm.
- **NHS, blind** (the builder saw only the commit message): 2 of 14 clean, against 12 of
  14 sighted on the same tasks. From a description alone the builder could not reconstruct
  what the maintainers' tests check.

That licenses one kind of sentence: "under apparatus 2.2, this builder reproduced X of n
historical changes in this cell of this repository, graded by the repository's own tests,
with no false pass recorded". It does not license a rate on the sealed posture, on another
repository, or on future work.

## Open gaps

Each of these is **[gap]** — named so that nobody assumes it is closed. None is closed on
`main`. The last five were found by an external assessment on 2026-09-25.

- **No row has been measured on the sealed posture.** Every number above was produced on
  the host posture. The sealed builder and the Docker executor are built and tested, but no
  ledger row on the sealed posture has been published.
- **No independent human review of the core.** The grader, ledger, controls and guards
  have been read by an AI reviewer only ([DL-053](DECISION-LOG.md), critical-friend
  action #8).
- **`deliver` without a measured oracle strength.** The routing rule on `main` can route a
  cell `deliver` without a measured oracle strength, and `crb route` without a controls
  verdict, although the published bar requires both. Until that is fixed, treat any
  `deliver` route whose oracle reads "not scored" as `calibrate`.
- **The route counts attempts, not tasks.** Repeated attempts on one task each add to `n`,
  so a cell can clear `n` ≥ 10 on fewer than ten distinct tasks. The map shows `n_tasks`
  beside `n`; read both.
- **Belt 5 switched off reads the same as no linter.** The ledger records both as "not
  evaluated", so a reader cannot tell an operator's choice from a missing toolchain, and
  neither blocks `deliver`.
- **The factory can open a pull request before its review.** In forward mode the pull
  request is opened before the test-strength check runs.
- **Production does not refuse the unsealed posture.** A production deployment warns, but
  does not stop, when the builder runs on the host.

Closing the first three of the assessment's gaps changes what a verdict means, so it needs
an ADR, an apparatus bump and a routing-policy version bump. What would close each gap, and
who owns it: the [definition-of-done gap analysis](dod/GAP-ANALYSIS.md) and the
[decision log](DECISION-LOG.md).
