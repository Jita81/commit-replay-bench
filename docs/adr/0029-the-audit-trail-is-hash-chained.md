# ADR-0029 — The audit trail is hash-chained, and both chains' heads are served to be kept outside the store

**Status:** Proposed (DL-091; north-star Wave 2, stream I — backlog F51 and G-601)
**Date:** 2026-09-27
**Apparatus impact:** none (storage and audit, not verdict semantics: no belt, size, class,
route, threshold or sign-off rule changes meaning; no row of any apparatus version is re-graded).
Amends ADR-0002 §5 and its first consequence.

## Context

ADR-0002 made the grade ledger a hash chain and left the `events` table — the audit trail
beside it — protected by `UPDATE`/`DELETE` triggers only. The audit trail is where the
product records who did what: every sign-in and refused sign-in, every account change (role,
password, deactivation), every repository change, every sign-off decision, every cancel,
and from this wave the start of a production process under the unsealed override (G-663).
A person with the database owner's role can drop a trigger, edit or delete a row and put the
trigger back, and nothing in the product could tell [measured — n = 1 table, method: by
inspection of `crb.store.models.Event` (no `prev_hash` / `row_hash`) and the pinned
`tests/test_server_admin_users.py::test_account_events_use_the_unchained_events_table` on
`origin/feat/ns2-t` at `0eac9ab`, apparatus 2.3]. `product.roles.7` asks that "a reader can
prove the audit trail was not altered"; the front-end review filed it as backlog F51.

A hash chain alone cannot see rows cut from its end or a table replaced by a new chain that
is consistent with itself: only a head recorded somewhere else can. ADR-0002's alternatives
already rely on "an operator-held final hash (published out of band)", and DEPLOYMENT §8
asked for it as a manual `SELECT` whose result nobody could read from the product
(`product.go-live.15`, G-601).

## Decision

1. **Every `events` row is chained, in id order.** Two columns, `prev_hash` (the previous
   row's `row_hash`; 64 zeros for the first) and `row_hash` (SHA-256 of the canonical JSON of
   every other column but the id, plus `prev_hash` and the schema tag
   `crb.events.chain.v1`). `crb.core.event_chain.event_body` is the one definition of the
   body; it normalises each value to what the database hands back (integers, a float cost,
   the payload as a JSON round trip) so a row hashes the same written and read.
2. **By construction, not by convention.** A `before_flush` hook on every SQLAlchemy
   `Session` (`crb.store.events._chain_new_events`, installed when `crb.store` is imported)
   gives each new `Event` its hashes under the events write lock (PostgreSQL advisory lock
   7332; SQLite `BEGIN IMMEDIATE`), in insertion order, onto the table's head — overwriting
   whatever the writer set. Every writer (the run's sink, `append_event`,
   `append_system_event`, a plain `add`) flushes, so none can skip it or choose its hashes.
   The database is the second line, for a writer that bypasses the hook (a Core `insert`,
   or the release before this one still running during the upgrade or after a rollback):
   the two chain columns have no default and a CHECK (`ck_events_chain_hashes`) requires 64
   characters in each, so such a row is refused alone; a unique index on `prev_hash` stops
   two rows chaining onto one predecessor, and one on `row_hash` refuses a duplicate. The
   hook reads genesis as the predecessor of the first row of an EMPTY table only; a head
   that is not a SHA-256 raises `EventChainHeadError` rather than starting a second chain
   (P-254 — a head of `''` once collided every later write with the first row).
   Every column of `events` is hashed: `EVENT_CHAIN_FIELDS` plus `EVENT_CHAIN_UNHASHED`
   (empty) must equal the table's columns, and a test fails until a new column is hashed
   under a new chain schema or named unhashed with its reason here (P-255).
3. **Existing rows are chained by the migration** (revision 0013): in id order from genesis, with a
   frozen copy of the rule that a test holds to the runtime one, so the same rows give the same
   hashes on every run and either dialect. The `events` update trigger is dropped for the back-fill
   and every trigger is re-installed in the same revision. After the back-fill the revision drops
   the columns' server default and adds the CHECK (item 2).

   **A recorded exception to the store rule.** The store's rule is that a migration may add
   nullable columns and indexes and may never rewrite, drop or alter rows of an append-only
   table. Revision 0013 is the one exception, recorded here (DL-350), and it is bounded:
   - *Why there is no other way.* A chain that starts after 0013 would leave every event
     written before it — every earlier sign-in, account change and sign-off decision —
     unprovable, which is the gap this ADR closes; and nullable chain columns would let a
     writer that names no chain store a row the chain cannot see (P-254). Only a back-fill
     of the rows already there chains the whole trail.
   - *What it writes.* Only the two columns this revision adds (`prev_hash`, `row_hash`) on
     rows that existed before it. Every column those rows held before 0013 — each hashed
     field and the id — is kept by how the revision writes: the back-fill's `UPDATE` sets
     only the two chain columns, SQLite's table rebuild copies each column into one of the
     same declared type, and PostgreSQL alters the table in place [hypothesis — the stored
     bytes are not compared]. What the test shows is narrower: each pre-0013 column keeps
     its declared type and reads as the same text before and after the upgrade [measured —
     n = 1 revision, 5 rows; method:
     `tests/test_store_migrate.py::test_0013_leaves_every_existing_events_field_as_it_was`
     reads every pre-0013 column's declared type and casts its value to text before and
     after the upgrade and compares, on SQLite here and on PostgreSQL in CI's `test-postgres`
     job (`CRB_TEST_POSTGRES_URL`); apparatus n/a, a property of the product's own code, not
     a graded row].
   - *The trigger.* `events_no_update` is dropped for the back-fill and re-installed, with
     every other append-only trigger, before the revision ends, inside the one migration
     transaction `crb.store.migrate.upgrade` opens on both dialects.
   - *When it runs.* With the API and the worker stopped (DEPLOYMENT §6, "Upgrading to
     revision `0013`"), so no writer races the back-fill.

   No later revision inherits this exception: a change to a written row of an append-only
   table needs its own ADR.
4. **The walk is served.** `GET /ledger/verify` walks the audit trail after the grade
   ledger and serves `events: {rows, chain_ok, broken_at, detail, head_row_hash, walk,
   full_walk_at}`; `ok` now also needs the audit trail intact. Between full walks the route
   re-hashes only the events written since its last clean walk, from that walk's head, once
   the head row still hashes to it and the count up to it is unchanged (`walk: tail`); it
   walks in full on the first read, at most five minutes after the last full walk, when that
   check fails, after a break, and on an operator's `?full=true` (P-257,
   `ledger.operations.11`). An edited event reads `row_hash mismatch` at its id; an
   event deleted from the middle, or moved, reads `prev_hash mismatch` at the event after
   the gap. `crb ledger verify --store` prints the same and exits 1 on either break.
5. **Both heads are served and logged, to be recorded outside the store** (G-601).
   `/ledger/verify` serves `head_row_hash` (the grade ledger's last `row_hash`) and
   `events.head_row_hash`; every worker start writes both, with their row counts, in one log
   line (`crb.server.worker_main.announce_start`), so the log store — which the deployment
   already ships off the host (DEPLOYMENT §9.4) — holds a copy the database cannot rewrite.
   A head recorded earlier must still be in the chain, and the chain must still verify: a
   store replaced wholesale, or cut at its end, fails that comparison.
6. **The append-only probe proves every table in the trigger's own words** (P-125, DL-092).
   `crb.store.ledger.assert_append_only` checks both triggers of every table in
   `APPEND_ONLY_TABLES` in the catalogue and, where a table holds a row, that an `UPDATE`
   and a `DELETE` of it are refused with `"<table> is append-only"`
   (`crb.store.db.append_only_error_text`, the one text both dialects raise). Any other
   error propagates; it is never read as proof.

## Consequences

- An auditor can prove, from the product, that no account change, sign-in, sign-off
  decision or override start was edited, removed from the middle or moved after it was
  written — on the API, from the command line, and from an export of the rows.
- Writes to `events` are serialised by one lock, as grade rows already are. A run's events
  wait for each other's commit; the SSE stream reads committed rows as before. A writer that
  reads a trace's last `seq` on a trace other processes write at the same moment takes the
  lock before it reads (`crb.store.events.lock_event_writes`, the one helper for that lock, which
  the chain's flush hook takes too): the override's start event does, as every process start
  writes its one trace (P-249), and so does every system event (DL-080).
- A full walk of the trail costs a re-hash of every event. The trail holds a row for every
  step of every run, many times the grade ledger, so a full walk slows as it grows
  [hypothesis — two readings of `verify_events` over 100,000 events, SQLite on developers'
  machines, 2026-09-27: 1.6 s and 2.7 s; a timing on a store of the deployment's own size
  would confirm or refute it]. A page read pays it at most once in five minutes per API
  process; between full walks it pays for the events written since (item 4). The price is
  a window: an edit underneath the triggers to an event before the last verified head that
  leaves the head row and the count unchanged is found by the next full walk, not the next
  read, and every answer says when that full walk ran. `crb ledger verify --store` always
  walks in full. DEPLOYMENT §9.5 tells an operator to size for it.
- Upgrading to this revision refuses every event the previous release writes, because it
  writes no chain: while the previous release's pods still run (the `pre-upgrade` hook
  migrates first), and after a `helm rollback` across this revision, their sign-ins answer
  500 and their run steps are dropped, each one alone. DEPLOYMENT §6 tells an operator to
  stop the API and the worker for the upgrade and never to roll back across it.
- Truncation and wholesale replacement stay invisible to the chain alone; they are caught
  only by comparing a head the operator recorded outside the store. That comparison is the
  operator's act (DEPLOYMENT §8), not the product's.
- ADR-0002 §5's "`events` … have DB triggers that forbid `UPDATE` and `DELETE`" now reads:
  and `events` is chained as well. Its first consequence ("the chain, not a database
  permission, is the evidence") now holds for the audit trail too.
- We must never add a write path to `events` that does not flush through a `Session`, never
  compute an event's hash anywhere but `event_body`, and never re-chain rows once written:
  a correction is a new event.

## Deferred

- **A signed (HMAC) anchor of the ledger's tail, and binding each clean row to its pack in
  the JSONL ledger** (ADR-0025 draft, item 11, "the tail is anchored" and "packs are
  bound"). No criterion in the definition of done names either; G-601 asks for the head to
  be served and logged, which this ADR does. They wait for a criterion of their own (for
  example, a TRUTH criterion that a truncated ledger is detected without an operator's
  record), and ADR-0025 defers them until one exists.
- **`/health` serving the last verification's state** (ADR-0025 draft item 11, "the state is
  served"): `/ledger/verify` already serves the walk on demand; a periodic verification
  waits for a criterion.

## Alternatives considered

- **Chain only the account events.** Rejected: the sign-off decisions, the override starts
  and a run's cancel are as much a part of "who did what" as the account events, and a
  second, partial chain would be one more place for a writer to go wrong.
- **One chain per trace.** Rejected: a trace can be deleted whole without breaking any
  other trace's chain; one chain over the table makes any removal visible.
- **Chain in each writer (as `DbLedger.append` does for grades).** Rejected: the table has
  a dozen writers across the store and the routes; the next one written would forget. The
  flush hook makes the chain a property of the table, not of the writer.
- **Database-side chaining (a `BEFORE INSERT` trigger computing the hash).** Rejected: two
  dialects' trigger languages would each carry a copy of the canonical JSON rule, and the
  verifier would need a third; one Python definition is testable against both databases.
- **Sign each event with `CRB_SECRET_KEY`.** Deferred with the tail anchor (above): it adds
  key rotation to the audit trail's meaning, and nothing in the definition of done asks
  for it yet.
