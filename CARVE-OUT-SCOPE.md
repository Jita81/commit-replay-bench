# Carve-out scope: `commit-replay-bench`

Staged extraction of AthenaClaude's commit-replay benchmark into a standalone,
publishable OSS package. **This directory is a staging snapshot — nothing is
published.** Creating the public repo / PyPI release is an explicit operator
decision (see the checklist).

## Why this piece (and not the whole factory)

The benchmark is the one component that is **novel, reusable, and nearly
decoupled**. The rest of the factory (manufacture chain, the false-Q1=0 trust
model, the class×complexity operating model + capability ledger, intake/horizon,
Cerebras specifics, the UI) is either commodity or the **moat** — kept proprietary.
Precedent: aider's credibility was built on its *open benchmark*; Warp open-sourced
its factory *demo*, not its product. OSS the eval, keep the factory.

## What extracted cleanly

| Source (AthenaClaude) | → OSS module | Coupling found | Action |
|---|---|---|---|
| `apps/athena/manufacture/intake/commit_replay.py` | `core.py` | **none — stdlib only** (DI'd: `generate` callable + `RepoHarness` Protocol) | copied verbatim (light docstring genericisation) |
| `apps/athena/manufacture/intake/repo_manufacturability.py` | `repo_assess.py` | **one** optional import (`repo_change_profile.profile_repo`) | made optional (try/except → `None`); core assessment unaffected |
| `tests/test_commit_replay.py` | `tests/test_core.py` | only the import path | repointed to `commit_replay_bench.core` |

New, written for the OSS surface:
- `mine.py` — feasible-commit miner (git-metadata only; the RED-oracle check stays in `replay_commit`).
- `generate.py` — the model boundary: SEARCH/REPLACE prompt + a pluggable **OpenAI-compatible** adapter (OpenAI / Cerebras / vLLM / Ollama). **No AthenaClaude `llm_client`.**
- `cli.py` — `commit-replay <repo> --model …` → mine, replay, scorecard.
- `README.md`, `pyproject.toml`, `LICENSE` (MIT), `__init__.py`.

**Key finding:** `commit_replay.py` was already dependency-injected, so the gem is publishable nearly verbatim — the carve-out is genuinely small.

## What is REDACTED / kept proprietary (the moat)

- The **manufacture chain** (`cerebras_manufacture_backend.py`) — generation pipeline, panel review, stage policy.
- The **false-Q1=0 trust model** internals + the deterministic floor / verdict layer.
- The **(class × complexity) operating model**: `benchmark_ledger`, `benchmark_capability`, `change_router`, measured-routing, the capability-envelope SPC. *(The OSS ships the per-commit grade; it does NOT ship the capability-matrix / yield-envelope intelligence.)*
- **Cerebras specifics**, model routing, cost/cache instrumentation, the intake/horizon machinery, the proving-grounds, the UI.

## Package layout (staged)

```
commit-replay-bench/
├── LICENSE                         (MIT)
├── README.md
├── CARVE-OUT-SCOPE.md              (this file — drop before publishing)
├── pyproject.toml                  (hatchling; console_script `commit-replay`)
├── src/commit_replay_bench/
│   ├── __init__.py                 (public API)
│   ├── core.py                     (engine: parse/apply/grade/replay/aggregate)
│   ├── repo_assess.py              (repo manufacturability assessment)
│   ├── mine.py                     (feasible-commit miner)
│   ├── generate.py                 (SEARCH/REPLACE prompt + OpenAI-compatible adapter)
│   └── cli.py                      (commit-replay CLI)
└── tests/test_core.py             (hermetic regression tests)
```

## Publish checklist (operator-gated)

- [ ] **Decide: publish?** (depends on commercial intent — if the *factory* is the product, OSS the benchmark for credibility; keep the factory.)
- [ ] Confirm license (MIT staged; **Apache-2.0** is the alternative if an explicit patent grant matters for enterprise adoption — aider uses Apache-2.0).
- [ ] `git filter-repo`/fresh-init into a **new public repo** (no AthenaClaude history); set author/owner.
- [ ] Drop `CARVE-OUT-SCOPE.md`; finalise README badges + a CONTRIBUTING.md.
- [ ] CI (GitHub Actions: pytest on 3.10–3.13).
- [ ] Optional: publish to PyPI (`commit-replay-bench`).
- [ ] Optional: a small public **leaderboard** (model × a few well-known repos) — the credibility flywheel aider proved.

## Validation (this snapshot)

- `core.py` + `repo_assess.py` import with **zero `apps.athena` references**.
- `tests/test_core.py` runs green standalone (hermetic; no network).
- `commit-replay --help` works.
