# What an adequate oracle costs — the `cobra-2154` test, strengthened five times — 2026-09-21

**Question asked:** after the first real factory run showed the reviewer right about a weak
oracle (docs/reviews/2026-09-19-b1b-first-factory-pull-request.md, finding 3), how much work
does it take to make one small item's test strong enough that only a real fix passes it — and
what is left over when you stop?

**Claims in this record.** Every count below — failing ids, attack outcomes, churn — is
**[measured — pristine clones of `Jita81/cobra` at `9c0edca` (the fork's `main` after PR #2
merged), Go 1.26.4, `go test -json -count=1 ./...` (the root package, where the authored file lives, plus `./doc`, which only adds its own passing tests — `./` alone yields the same authored ids), `gofmt -l`, `go vet ./`;
each attack applied on a reset tree; n = 1 item, 5 revisions, 10 wrong builds; the proof notes
and the attack patches' failing ids are in [2026-09-21-oracle-2154-v2/proof-notes.md](2026-09-21-oracle-2154-v2/proof-notes.md)]**.
The statements about *why* a family of wrong builds survives are **[hypothesis]** — reasoning
from the code, not a census. No model was involved: the authors, the adversaries and the
throwaway correct fix are all hand work.

## What happened

The first factory run (B-1b) delivered PR #1 on the fork against an oracle that pinned the
issue's stated inputs but not two neighbouring paths: `DisableFlagParsing`, and a flag passed
through the built-in `help` command. The independent review said *accept with edit —
weak oracle*; the rework then produced a build that dropped an untested guard, and only a
failed push kept it off the pull request. Rule (3) of DL-045 now stops that rebuild; this
record is the other half — the strengthened oracle that the superseding item carries.

The oracle went through five revisions. Each revision was written by one agent, then attacked
by a second whose brief was to pass the test with a *wrong* fix while keeping the package
green (what the four belts would accept). Each round's survivors became the next round's
pins.

| Rev | Added | RED ids at base | Wrong builds rejected | What still passed |
|---|---|---|---|---|
| frozen v1 (B-1b) | the issue's inputs | 14 | — | build 1 (raw args through `help`); the rework (guard dropped) |
| 2 | `DisableFlagParsing`; flags through `help sub …`; `--`; shorthands; `help -h` | 28 | build 1 (8 ids), rework (12), 3 attacks | a name-switch on the help command's first token (B) |
| 3 | grouped shorthands `-vc 3`; `help -- …` | 32 | + attack B by assertion | two ~28-line first-token switches (B′, B″) |
| 4 | root persistent flags before the topic (`-V -h`, `-Vh`, `--vroot --help`, `--help=1`, `--config x sub`) | 39 | + B′ (8 ids), B″ (5) | a 35-line hand-rolled token walker (D) |
| 5 (frozen) | `help -- sub`; `help --config= sub`; `help --config` and `help -x` as guards | 39 + 5 guards | + D (2 by assertion, 2 by panic); every earlier attack re-run and still rejected | see *Residue* |

The correct fix stayed the same size throughout: 13 insertions, 3 deletions in `command.go`
(**S**), green on all 44 authored tests and on `go test ./...` for the package and `./doc`.
Build 1's fix was 7+3 lines; the rework's 4+3; the wrong builds that survived longest were
24–35 lines — the same size band as the right answer.

## What is left, and why we stopped

Revision 5's residue, written into the proof notes before stopping:

1. A faithful hand-rolled re-implementation of `pflag` on the help command. Walker D at 35
   lines was rejected on four `pflag` corner cases **[measured — one build, 4 ids]**; that
   the next iteration which handles them lands at ≥ 45 source lines — **M** under
   `SIZE_TIERS`, which the route gate for an S item does not license — is **[hypothesis]**
   (no such build was written). Every row added only pushes this family's line count up; the size gate, not
   the oracle, is the instrument that catches it.
2. Builds correct on the fixture's int / bool / string flags but wrong on kinds the fixture
   does not declare (slice, count, `-c=3`, values that look like flags). Also a parser; also
   ≥ M.
3. Mechanically different but observably equivalent builds (re-parsing on a written-back copy
   of the helped command's flag set). Not wrong builds; acceptable deliveries if small.
4. A hand-rolled filter *after* the topic that also sets the stripped flag values. Rejected
   today only by one pin (`--count` reads 7 inside the help function); a filter that sets the
   values is a parser again — size-caught.

So the honest statement of what the oracle licenses is: *a change under 40 source lines that
passes these 44 tests is the fix, or an equivalent of it*. Above 40 lines the oracle alone
does not say, and the size gate says no.

## What this means for the product

The four points below are **[hypothesis]** — conclusions drawn from one item's record, not a census; the last three each name a backlog row that is **[aspiration]** until built.

- **An adequate oracle for one XS/S bug cost ~45 test rows and five author–adversary rounds.**
  That is the price of "false-Q1 = 0" on a forward-mode item, and it is the reason the loop's
  rule (3) refuses to rebuild against an unchanged oracle: the builder will find the gap
  before the reviewer does.
- **The adversary is the mechanism, not the author.** Every round's improvement came from a
  wrong build that passed; none from re-reading the issue. That argues for a *review probe
  that attacks the oracle before the build* — the mutation probe does this for the delivered
  change; a pre-build variant would do it for the authored test (backlog: F48).
- **The size gate is part of the oracle.** Route decisions already key on `size_estimate`;
  this record shows why the delivered change's measured churn must be compared to the item's
  estimate at the gate, not only recorded (backlog: F49 — refuse delivery when measured size
  exceeds the licensed cell).
- **Process exits and panics hide ids.** Four of the ten wrong builds (the rework, attack 1,
  attack B and walker D) `os.Exit` or panic inside the test binary **[measured — the
  proof notes' per-build runs, same method and apparatus as above]**, so a whole-package run reports only the failures before the exit. The RED
  proof and the reviewer read attributable ids from one run; a build that exits should be
  classified as *harness error → not clean*, never as "fewer failures" (backlog: F50 — the
  grader treats a test-binary exit as a failed belt with the exit recorded).

## The artefacts

- [2026-09-21-oracle-2154-v2/item.json](2026-09-21-oracle-2154-v2/item.json) — the
  superseding item `cobra-2154-v2` (labels carry `supersedes: cobra-2154`; recording
  supersession on the chain needs an evolutions route the API does not have yet —
  **[aspiration]**, backlog F32), API-valid against `BacklogRegisterIn`.
- [2026-09-21-oracle-2154-v2/help_func_args_issue2154_test.go](2026-09-21-oracle-2154-v2/help_func_args_issue2154_test.go)
  — sha256 `e3821bc1213ded3ace50b88dc260db53c0015970b7c8f238922be81542139f71`, 44 tests
  (39 RED at `9c0edca`, 5 guards green at base).
- [2026-09-21-oracle-2154-v2/proof-notes.md](2026-09-21-oracle-2154-v2/proof-notes.md) — every
  run, every attack's failing ids, the churn numbers, the residue. The throwaway correct fix is
  deliberately absent: the factory must earn it.

## How to repeat it

```bash
git clone https://github.com/Jita81/cobra.git && cd cobra && git checkout 9c0edca
cp <this dir>/help_func_args_issue2154_test.go . && gofmt -l . && go vet ./
go test -json -count=1 ./... > red.json; status=$?          # exit 1 is the expected RED
python3 -c 'import json;print(sum(1 for l in open("red.json") for e in [json.loads(l)] if e.get("Action")=="fail" and e.get("Test")))'   # 39 (leaf + parent ids; the package-level fail event has no Test field and is not counted)
exit $status
```
