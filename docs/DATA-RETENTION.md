# Data, retention and privacy

_Support material for a Data Protection Impact Assessment (DPIA) or an information-governance
review. It describes exactly what crb stores, for how long, and who can see it. Nothing here
is legal advice._

## 1. What crb processes

crb is pointed at **source-code repositories** and at **AI model endpoints**. It does not
process patient data, service-user data or any special-category data by design. Personal data
it may touch:

| Data | Source | Why | Where it lands |
|---|---|---|---|
| Commit metadata: author date, subject, message | the repository's git history | The commit message is the builder's task description (blind mode) and the task's label | `tasks.spec_json` (subject, authored date); the full message is passed to the builder at run time and **not stored** |
| Author names / e-mails | git history | **Not used.** crb reads `%aI` (date) and `%s`/`%B` (subject/body) only; author identity fields are never read | — |
| Operator identity: display name, e-mail, OIDC subject, role | the identity provider or a local account | Authentication, audit (`actor` on every ledger row and event) | `users`; `grades.actor`; `events.actor`; `signoffs.verifier` |
| Repository file paths and test identifiers | the repository | Verdict evidence: which files changed, which tests failed | `grades`, `evidence`, `events` |
| Source code | the repository | Read by builders and test runners in a **throwaway worktree** | Worktrees are deleted after grading. Code is **not** stored in the database. Diffs are stored as a hash + counts (see §2) |
| Model prompts and responses | builder runs | Needed only for debugging | **Not retained by default** (see §2) |

## 2. Retention defaults ("zero raw retention")

| Artefact | Default | Configurable |
|---|---|---|
| Grade rows (verdicts, belts, cost, latency, hashes) | **Kept indefinitely, append-only.** This is the evidence; deleting it would invalidate every number derived from it | No deletion path exists by design; export + archive the whole ledger instead |
| Evidence packs | Kept indefinitely (content-addressed). Contain: the task spec (paths, sha, subject), belt values, **redacted and capped** test-output tails (≤ 8 KB), diff **hash + file list + line counts** (never the diff text), builder cost/turn metrics, the apparatus stamp | — |
| Events (StepEvents) | Kept, append-only; payloads are redacted at construction | — |
| Builder transcripts (raw model I/O) | **Off.** `BuildOutcome.transcript` is discarded unless `keep_transcript` is enabled per builder | When enabled: stored under `CRB_HOME/transcripts/` with a `retention.transcripts_days` sweep (default 30); referenced from the pack by `transcript_ref` only |
| Throwaway worktrees | Deleted immediately after grading (`RunSpec.keep_worktrees=false`) | `keep_worktrees` for debugging only |
| Repository clones | Kept on the worker host under `CRB_HOME/repos/` for as long as the repository is configured | Remove the repository to delete |
| Access logs | JSON to stdout/stderr, redacted; retention is the host's log policy | — |
| Session cookies | `session_ttl` (default 12 h), signed, `HttpOnly` | `CRB_SESSION_TTL` |

## 3. Redaction

Every string that leaves an execution sandbox — test output, event payloads, log lines,
transcripts when enabled — is passed through `crb.core.redact` before storage. Patterns
cover bearer/basic authorisation headers, well-known API-key prefixes (OpenAI/Anthropic,
GitHub, Slack, AWS, Google), JWTs, `key=value` secrets, URL userinfo and private-key blocks.
Redaction is defence in depth: the executors already strip the worker's environment before
running repository code. [measured — `tests/test_redact.py`, `tests/test_execution.py`]

## 4. Access

| Role | Can see | Cannot |
|---|---|---|
| viewer | every verdict, pack, event, capability map, ledger export | create runs, sign off |
| operator | + create/cancel runs, add repositories, abstract export | sign off, manage users |
| approver | + sign off cells (human attestation) | manage users |
| admin | + users, settings (secrets shown only as configured yes/no), ledger import | — |

There is no per-repository visibility control in v2.0: a viewer sees every configured
repository's evidence. Deploy one instance per trust domain if that is not acceptable.

## 5. Cross-organisation sharing

crb can **export** abstract capability cells — `(process step, change class, size,
language, builder, model, provider) → n, clean, false-Q1, point, Wilson interval, mean cost,
mean latency` — with no repository name, task id, path, timestamp or free text, and only for
cohorts of at least *k* contributors. The export is **opt-in** and **manual**
(`crb ledger export --abstract`, `GET /ledger/export/abstract`, operator role). Nothing is
transmitted automatically, and the product does not consume shared priors (that boundary is
designed, not implemented — see ADR-0007).

## 6. Deletion and data-subject requests

- **Operator accounts**: deactivate (`active=false`); the `actor` field on historical rows
  remains because it is part of the audit chain. Replace the display name/e-mail on the
  `users` row if pseudonymisation is required — ledger rows reference the user's opaque id.
- **A repository**: delete its configuration and clone; its rows remain in the ledger
  (they contain paths and shas, not code). If the rows themselves must go, export the
  ledger, remove the repository's rows from the export, and re-import into a **new** ledger —
  the hash chain makes in-place deletion impossible by design, and the new chain will not
  verify against the old export. Record this as a registered evolution.
- **Transcripts** (if enabled): deleted by the retention sweep or by removing the file; the
  pack's `transcript_ref` then dangles, which the UI shows honestly.

## 7. Where data lives (self-hosted)

All of it is inside the customer's tenant: the database (SQLite file or PostgreSQL), the
`CRB_HOME` directory (evidence packs, events, optional transcripts, clones) and the worker
host. The only outbound traffic is to the configured model endpoint; for an NHS deployment
that is expected to be Azure OpenAI in the same tenant, or a local model.
