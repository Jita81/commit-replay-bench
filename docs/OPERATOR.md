# Operator guide (skeleton)

*For the person who installs, configures and runs `crb` inside an organisation's tenant.*
This is a skeleton for phases P1–P2; the full runbook (deployment, DPIA support, air-gap
guidance, incident procedures) lands in P7. Where a command or screen is not yet built, it
is marked with the phase that delivers it.

Read alongside: [README](../README.md) · [ARCHITECTURE](ARCHITECTURE.md) ·
[EVIDENCE-AND-CLAIMS](EVIDENCE-AND-CLAIMS.md) · [ADR-0005 (sandbox)](adr/0005-fail-closed-docker-sandbox.md).

Contents: [1 Install](#1-install) · [2 Configure a repository](#2-configure-a-repository) ·
[3 Run a sweep](#3-run-a-sweep) · [4 Read the capability map](#4-read-the-capability-map) ·
[5 Sign off](#5-sign-off-p4) · [6 Export the ledger](#6-export-and-verify-the-ledger) ·
[7 When the sandbox is unavailable](#7-when-the-sandbox-is-unavailable) · [8 Stop conditions](#8-stop-conditions)

---

## 1. Install

Requirements: Python ≥ 3.12, `git`, a Docker daemon reachable by the user running `crb`
(for the sandboxed executor — the default), and network access **only** to the model
endpoint you configure.

```bash
uv venv .venv --python 3.12
uv pip install -e '.[dev]' --python .venv/bin/python        # CLI + core
# builder extras as needed: '.[openai]' (Azure OpenAI / Cerebras / local), '.[claude]'
```

Model credentials are read from the environment (or the vault integration in P4); they are
never written to configuration files, evidence packs or logs. `crb` redacts common secret
shapes from every stored string as defence in depth, but do not put live secrets in
repositories under measurement.

Server, worker and UI (`crb serve`, `crb worker`) land in P4–P5.

## 2. Configure a repository

A repository is described by a `RepoConfig` (see `crb.core.spec`): language, runner,
source/test layout, regression belt scope, a known-green probe scope, runner options, the
sandbox image, and mining limits.

```bash
crb repo add myrepo \
  --path /srv/repos/myrepo \
  --language python --runner pytest \
  --src-prefix src/ --test-prefix tests/ \
  --belt-scope AFFECTED_DIRS \
  --probe tests/test_smoke.py \
  --sandbox-image ghcr.io/example/myrepo-toolchain:2026-09
crb repo probe myrepo
```

`crb repo probe` runs the probe scope inside the sandbox and must be green before mining;
it proves the image has the toolchain and the dependencies. Belt scope options:

| `belt_scope` | Regression belt runs… |
|---|---|
| `TARGET_ONLY` | only the target tests (weakest; use for very large suites while calibrating) |
| `AFFECTED_DIRS` | every test in the target tests' directories |
| `BARE` | the runner's default discovery (whole suite) |
| explicit list | the named runner scopes |

The census `configs.json` shape is accepted unchanged by `RepoConfig.from_dict`.

**Sandbox images** are yours to build: one image per repository (or per toolchain) with
the language runtime, the test runner and the repository's dependencies pre-installed,
runnable as user `65534` with a read-only root. P7 ships reference images.

## 3. Run a sweep

```bash
crb mine  myrepo --pool standard --target 25       # RED-check, baseline, gold-check; writes tasks
crb grade myrepo --builder editblock --mode sighted --budget-usd 5   # P2: editblock; P3: openai_agent, claude_code
crb ledger stats --repo myrepo
```

What you will see (events; UI live progress in P5): `mine.candidate` → `mine.red` /
`mine.skip` → `mine.gold` → `build.*` → `grade.belt` (four per task) → `ledger.append`.
Skips are normal: a commit whose target is already green at the parent, or times out, is
not a valid oracle and is excluded, not counted.

Every graded task produces an **evidence pack** (redacted; no raw diff, no transcript by
default) and a **ledger row** that carries the pack's hash. A row cannot be `clean` without
a pack.

## 4. Read the capability map

`crb ledger stats` (CLI) and the Capability Map screen (P5) show, per cell
`(class × size × language × builder × model × provider)`:

| Column | Read it as |
|---|---|
| `n` | eligible graded trials — the claim's denominator; `disqualified` and `errors` shown beside it |
| `point` | clean / n |
| `ci_low – ci_high` | Wilson 95% interval — **the** number to quote |
| `false_q1` | must be **0**; anything else is a stop condition (§8) |
| `oracle_strength_mean` | hygiene-adjusted mutant kill-rate (P2) or **not measured** |
| `cost_usd_mean`, `latency_s_mean` | economics per trial |
| `apparatus_versions` | if more than one, the rows are from different instruments and are shown separately |
| `route` + reason | `deliver` / `calibrate` / `granularize` / `human` / `do_not_ship` — see [ADR-0003](adr/0003-one-routing-rule.md) |

Rules of reading: a cell at `n < 10` is `calibrate` whatever its point estimate; a
`deliver` route means "high-confidence candidate under the published bar", not "safe to
automate" — see [EVIDENCE-AND-CLAIMS §6](EVIDENCE-AND-CLAIMS.md#6-permitted-claim-shapes-by-maturity).
Never quote a point without its interval and its `n`.

## 5. Sign off (P4)

An **approver** signs off a cell for a route in the Sign-off screen (or `POST /api/v1/signoffs`).
The server re-derives the cell's statistics and applies the routing rule:

- any false-Q1 row in the cell → **409 Conflict**, nothing written, event logged;
- requested route stricter than or equal to the rule's decision → **201**, an append-only
  `signoffs` row with actor and timestamp;
- requested route more permissive than the rule → **409** with the rule's reason.

Sign-offs are revoked by a new row, never by deleting one.

## 6. Export and verify the ledger

```bash
crb ledger verify                          # walks the hash chain; exit 1 and the row number on any break
crb ledger export --repo myrepo -o myrepo.jsonl   # P2; chain preserved; legacy rows keep belt_set=v3-legacy
```

For an audit: export, run `crb ledger verify` on the export, and record the last
`row_hash` out of band (for example in the audit report). Anyone with the file can re-run
the verification.

## 7. When the sandbox is unavailable

**Fail closed means the run STOPS.** If Docker is missing, the daemon is unreachable, the
image is not set, the configured user is root, a forbidden mount is requested, or
`docker run` fails to launch (exit 125), `crb` raises `SandboxUnavailable` and the run's
status becomes `blocked`. **No test is run on the host as a fallback**, and no verdict is
recorded for the affected tasks.

What to do:

1. `docker info` as the `crb` user — the daemon must answer.
2. `crb repo probe <repo>` — proves the image and the toolchain.
3. Check the run's status message; it names the cause (`docker binary not found`,
   `daemon not reachable`, `refusing to run untrusted tests as root`, `refusing to mount …`).
4. Fix the cause and **re-run**; the worker (P4) resumes blocked runs. Tasks that were
   never graded have no rows — nothing needs correcting in the ledger.

Do **not** switch the executor to `local` for a repository you do not fully trust; the
local executor exists for development and fixture repositories and is visible on every
verdict's apparatus stamp.

## 8. Stop conditions

Stop delivery and investigate before any further sign-off if you observe any of:

- `false_q1 > 0` anywhere (`crb_false_q1_total` metric non-zero);
- `crb ledger verify` fails;
- a secret in an evidence pack, log or export;
- a sandbox escape or unexpected network egress from a test container;
- a builder repeatedly disqualified for test tampering (shows as a rising `disqualified` count).

Resume only after root cause, correction, a targeted regression run and re-qualification
of the affected cells.
