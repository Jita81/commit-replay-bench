# Ledger anchors: who holds them and where

_For the operator and for anyone who later has to trust the ledger. It says what an anchor is,
where it must be kept, who must hold it, and what it cannot prove._

## 1. Why an anchor exists

The grade ledger and the audit trail (`events`) are hash-chained (ADR-0002, ADR-0029). A chain
shows that no row was edited, removed from the middle or moved. It cannot show that rows were cut
from its end, or that the whole ledger was rebuilt from a new start: a rebuilt chain verifies
too.

An anchor closes that gap. It is a small JSON file (`crb.ledger-anchor/v1`) that records, for
each chain, the row count and the `row_hash` of the row at that count. Later, the row at that
count must still carry that hash. If it does not, the history up to the anchor was rewritten or
cut.

## 2. Writing and checking anchors

```bash
crb ledger anchor --store --out ~/anchors/my-store        # the database: grades + events
crb ledger verify --store --anchor ~/anchors/my-store     # every anchor in the directory
crb ledger anchor --out ~/anchors/my-jsonl                # the JSONL ledger: grades only
crb ledger verify --anchor ~/anchors/my-jsonl/anchor-g00000003-….json   # one anchor
```

`crb ledger anchor`:

- reads the ledger and verifies its chain first. A broken chain writes no anchor (exit 1). A
  line that is not a readable row (not JSON, not an object) counts as a broken chain.
- refuses an empty ledger (exit 2): an anchor with no row attests nothing. A store with an
  audit trail but no grade yet is anchored, with `grades` at 0 rows.
- writes one file named from the row counts and heads, for example
  `anchor-g00000412-1f3a…-e00009311-77c0….json`. It never overwrites a file. Running it again
  on an unchanged ledger writes nothing and says so.
- records the previous anchor in the directory and the sha256 of that file, so the anchors in a
  directory form a chain of their own. A deleted or edited anchor shows up **if a later
  anchor follows it**. Nothing in the directory records the newest anchor, so the newest one
  is protected only by where the directory is kept: the history of the repository that holds
  it, off this machine. Deleting the newest anchor and cutting the ledger back to the one
  before it passes `verify --anchor` on the directory alone.
- refuses to write when the ledger no longer extends the directory's last anchor (exit 1). An
  anchor written over a rewritten history would hide the rewrite.
- **refuses** an `--out` directory inside the ledger's own data directory: the folder that
  holds `ledger.jsonl`, or the folder that holds the SQLite file (the folder named on the command line and, when the
  file is a symlink, the folder of its target). An anchor beside the data it
  anchors proves nothing.
- **warns** when `--out` is on the same filesystem as the ledger. The anchor proves nothing
  until it is copied off the machine. For PostgreSQL the command cannot tell where the data
  lives, so it always says to copy the anchor off the machine.
- stores the database dialect (`sqlite`, `postgresql`), never the database URL: a URL can hold
  a password. The creation time is now, in UTC, unless `--created-at` gives one.
- makes no network call and runs no git command. Moving the file off the machine is the
  operator's act (§3).

`crb ledger verify --anchor <file-or-directory>` runs the normal verification and also checks
that the ledger still extends each anchor. For a directory it also checks the anchors' own chain.
Verify an anchor against the ledger it was taken of: an anchor written with `--store` is checked
with `crb ledger verify --store --anchor <dir>`. Without `--store`, `verify` reads the JSONL
ledger, and each database anchor fails with a line that says it was taken of a `sqlite` (or
`postgresql`) ledger and is checked against a `jsonl` ledger.

Either kind of failure exits 1, and each prints differently:

- **An anchor no longer holds.** One line per fault, `ANCHOR BROKEN — <file>: <fault>`, then
  `the first anchor that no longer holds: <file>`.
- **The directory's anchor chain is damaged** (an anchor is missing, was edited, or names no
  valid predecessor; or the directory holds no anchor files). One line per fault,
  `ANCHOR CHAIN BROKEN — <fault>`. When every anchor still holds, no first anchor is named and
  `first_broken` in the `--json` output is `null`.

Without `--anchor`, `verify` prints and returns exactly what it did before.

## 3. Custody: where anchors live and who holds them

An anchor proves something only when the person who can rewrite the ledger cannot also rewrite
the anchor. So:

1. **The anchor directory is a clone of a git repository hosted off the machine** that runs
   crb. Write the anchor into the clone, commit it and push it. Git history and the host's
   push timestamps then give an ordering that does not depend on the crb machine's clock.
2. **The repository is held by someone other than whoever can write the database.** Ideally a
   person or team without database credentials has the only write access to it, and the
   operator sends anchors to them. Where one person holds both, say so in the audit record
   (§4, second limit).
3. **Anchor after each campaign closes, before and after a restore or migration, and at least
   weekly while runs are live.** An anchor protects only the history before it, so the gap
   between anchors is the window in which a rewrite would not be caught.
4. **Keep one anchor directory per ledger.** The command refuses a directory that holds anchors
   of a different kind of ledger.
5. **Never edit or delete an anchor.** If the ledger legitimately loses rows (a restore from an
   older backup), `verify --anchor` fails by design. Record why, then start a new anchor
   directory. Do not edit the old one: the failure is the evidence that the restore happened.

**For this project's own deployment** the recommended home is an `anchors/` directory in the
project's private handbook repository, which is hosted off the machine that runs crb, with an
anchor committed after each campaign closes and weekly while runs are live. [gap] That
directory is not set up yet, and on this deployment the person who would commit anchors can
also write the database, so rule 2 is not met there; the second limit in §4 applies to every
anchor it holds until someone without database access holds the repository.

The worker log is a second, independent copy: every worker start writes both heads to its log
(ADR-0029 §5), and the log store is shipped off the host (DEPLOYMENT §9.4).

## 4. What an anchor does not prove

- **It proves nothing about the ledger before the anchor left the machine.** A ledger rewritten
  before it was first anchored is anchored as rewritten.
- **An operator who controls both copies can rewrite both.** The anchor repository's history and
  its host's push log make that harder to do quietly, not impossible. Separate custody (§3) is
  what makes it hard.
- **It says nothing about whether a row is true.** Hash-chained and anchored means unaltered
  since it was written and since it was anchored, not verified true.
- **It is unsigned.** The file says `"signed": false`. A public transparency log (Sigstore /
  Rekor) would give a timestamp and a record no operator controls. That is not built, and any
  later version is off by default because it sends data off the machine; the `signed` field is
  the place it would be recorded.

## 5. The file

```json
{
  "schema": "crb.ledger-anchor/v1",
  "created_at": "2026-11-11T12:00:00Z",
  "crb_version": "2.0.0a1",
  "apparatus": "2.5",
  "source": "sqlite",
  "chains": {
    "events": {"rows": 9311, "head_row_hash": "77c0…"},
    "grades": {"rows": 412, "head_row_hash": "1f3a…"}
  },
  "previous_anchor": {"file": "anchor-g00000398-….json", "sha256": "…"},
  "signed": false,
  "note": "Unsigned. Proves the ledger was not rewritten after this file left the machine, …"
}
```

The field names are a contract: a later signed attestation will reference `head_row_hash`.
A JSONL ledger has only the `grades` chain; a store anchor has both. `verify --anchor` refuses
a file (exit 2) whose chains are not those of its `source`, or whose every chain has 0 rows: it
would check as holding while attesting nothing. The code is `src/crb/core/anchor.py` and
`src/crb/cli/commands/ledger.py`.
