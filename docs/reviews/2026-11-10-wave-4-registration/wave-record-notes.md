# Wave 4 record notes (to be folded into the wave record; nothing here changes a registered number)

## 2026-11-11 23:0xZ — stop (b) reading, decided by Paul before any cobra run

Stop (b): four or more of the first 40 wave builds ending on an outage, a provider error, a
container failure or a refused allowed command, counted from row fields.
**[hypothesis — a record of the sessions of 2026-11-11 and 2026-11-12; the rows and the transcripts are not in this repository]**

First 40 wave builds = click batches 1 and 2 (runs 7f3ee062, 3f17a9b8, c0147446, 688a8a4f,
5a6bd92c, b49c2e6a, a2373f88, c98ee5ba). Row `error` fields read from
`GET /api/v1/runs/<id>/tasks` on 2026-11-11 ~22:50Z. Nine builds ended in an error:
**[hypothesis — a record of the sessions of 2026-11-11 and 2026-11-12; the rows and the transcripts are not in this repository]**

- 5 × "authoring: the authored test ... is not RED at the parent" (3f17a9b8 ×2, c0147446,
  b49c2e6a, a2373f88)
- 2 × "protocol violation: archaeology: 'git stash' is not allowed" (7f3ee062, b49c2e6a)
- 1 × "'git log' is not allowed (no history/other revisions)" (688a8a4f)
- 1 × "'git show' is not allowed (no history/other revisions)" (c98ee5ba)

No outage, provider error or container failure.

Count under each reading of "a refused allowed command":
- strict (the guard forbids all three commands by design, so none is an allowed command): 0
  **[hypothesis — a record of the sessions of 2026-11-11 and 2026-11-12; the rows and the transcripts are not in this repository]**
- `git stash` only (Amendment 2 called the pilot's refused `git stash list` "an allowed
  command refused in spirit"): 2
- every refused read-only git command: 4 (the stop would have fired)

The team's methodologist raised the ambiguity on 2026-11-11 from pooled figures. Claude Code
had applied the strict reading during the click runs and had reported the count to Paul as 0
without stating the other readings. Paul was shown all three counts and Claude Code's
recommendation (strict reading, recorded with all three counts) and answered: "Happy to
proceed with the [recommendations]". The wave continues under the strict reading. This is a
reading decided after 110 pooled click builds were seen (no arm comparison was made); a
reader who holds the widest reading should treat the wave as one that passed its stop (b) on
the operator's decision.
**[hypothesis — a record of the sessions of 2026-11-11 and 2026-11-12; the rows and the transcripts are not in this repository]**

## Refile rule — kept as registered

Paul offered to relax it; the product owner, methodologist and architect personas each
recommended keeping part 2's row rule unchanged for cobra. Applied mechanically on run status
and row count. Click: all runs filed so far ended `succeeded` with 5 of 5 rows; batch 3 was
refiled once (run 98fe708c failed its gold control before any build; no row was read).
**[hypothesis — a record of the sessions of 2026-11-11 and 2026-11-12; the rows and the transcripts are not in this repository]**

## Other things the wave record must state
- runs from click-3/1 onward were filed by the `svc-claude` operator account;
- a poster crash / login-verify timeout before batch 3 (no run lost);
- both pilot gates failed and waived (Amendment 2).

## 2026-11-11 23:27:59Z — second stack restart (cobra builder image), granted once by Paul

- `~/crb-stack/env.sh` line 22 changed from `export CRB_BUILDER__IMAGE=crb-builder:local` to
  `export CRB_BUILDER__IMAGE=crb-builder-go:local` (image Id 77b43c312c7a, built 2026-10-11);
  backup beside it: `env.sh.bak-20261111T232545Z`. Lines 20 and 23 unchanged.
- Preconditions met: every click batch filed (24 succeeded runs + 1 refiled gold-control failure,
  120 rows), no active run, worker idle.
  **[hypothesis — a record of the sessions of 2026-11-11 and 2026-11-12; the rows and the transcripts are not in this repository]**
- `CRB_SKIP_UI_BUILD=1 ~/crb-stack/restart.sh` finished 2026-11-11T23:27:59Z: api pid 25906,
  worker pid 25907, apparatus 2.5, served commit 7bb03d6c (unchanged), database at 0018.
- After restart: cobra posture id `pst_a308788d88899137d5fae9c7` (unchanged, not stale, class
  docker/copy/sealed, sandbox image crb-sandbox-go:main-8ab88ad, 74 of 86 qualified); no
  re-qualify needed. Each run checks its own gold control before any build.
- Campaign before the first cobra run: spent $28.848331 of $95, left $66.151669.
- Cobra poster started ~23:30Z, same svc-claude account.
