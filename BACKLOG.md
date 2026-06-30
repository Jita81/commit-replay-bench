# Assessment & Backlog — `commit-replay-bench`

_Assessment date: 2026-06-30. Scope: the staged OSS carve-out at HEAD (`8bc18b1`)._

## 1. What this is, and where it stands

`commit-replay-bench` replays a repository's **real commits** and grades an AI
coding model against that repo's **own held-out test suite** — an eval that is
hard to overfit because the oracle (the tests) and the ground truth (the commit)
both come from the target repo, not a curated set.

The carve-out is genuinely clean:

- **Engine is dependency-injected and stdlib-only.** `replay_commit` takes a
  `RepoHarness` Protocol and a `generate` callable; the pure pieces
  (`parse_edit_blocks`, `apply_edit_blocks`, `grade`, `aggregate`) have no IO.
- **The robustness is hard-won and documented** — tolerant SEARCH/REPLACE
  parser, fuzzy (indentation-insensitive) apply, `py_compile` gate, test
  timeout, honest `SKIP` when there is no RED oracle.
- **Tests are hermetic and green** (12 passing, ruff clean across 3.10–3.13 CI).

So the foundation is strong. What it is **not yet** is a tool a stranger can
point at their repo and trust: there are correctness/safety sharp edges, the
output isn't machine-consumable, half the shipped surface (`repo_assess.py`) is
orphaned and partly broken, and the "credibility flywheel" the project's own
notes call out (a public leaderboard, a second-language runner) doesn't exist.

This backlog is what closes that gap, ordered by leverage.

---

## 2. P0 — correctness & safety (do before anyone runs this on a real repo)

### P0-1. `reset()` can destroy uncommitted work in the target repo
`LiveGitHarness.reset()` runs `git checkout -f <base_ref>` then `git clean -fdq`.
Pointed at a repo with uncommitted changes or untracked files, the **first
replay wipes them silently**. There is no pre-flight clean-tree check and no
warning in the docs.
- **Fix:** refuse to run on a dirty tree unless `--force`; document that the
  tool mutates the working copy and recommend a throwaway clone; consider
  operating on a dedicated worktree (`git worktree add`) so the user's checkout
  is never touched.
- **Acceptance:** running against a repo with a staged/untracked file aborts
  with a clear message instead of deleting it; a test covers the dirty-tree guard.

### P0-2. Test timeout orphans the process group
`run_tests` launches pytest with `start_new_session=True` but on
`TimeoutExpired` only `subprocess.run` is unwound, which SIGKILLs the immediate
child — **not** the new session group. A hung test that spawned children leaks
them, and they can hold the venv/ports across the rest of the run.
- **Fix:** capture the `Popen`, and on timeout `os.killpg(os.getpgid(p.pid), SIGKILL)`.
- **Acceptance:** a test that forks a long-lived child and hangs is fully reaped
  on timeout (no surviving PIDs in the session group).

### P0-3. `assess_repo(with_change_profile=True)` silently returns `None`
The optional `repo_change_profile` add-on is not bundled in the OSS package, so
the `except Exception: return None` path **always** fires when the flag is set —
discarding a perfectly good assessment and returning `None`. The docstring even
claims the path is "PURELY ADDITIVE." Confirmed: `assess_repo('.', with_change_profile=True)` → `None`.
- **Fix:** drop the dead optional-coupling branch from the OSS surface (return
  `m` regardless, or remove the flag), or make it degrade to `m` instead of
  `None`. See also P1-4 (orphaned module).
- **Acceptance:** no public function can return `None` where a
  `RepoManufacturability` is the contract; a regression test asserts it.

### P0-4. `full_test_target="tests"` is hardcoded and unexposed
Regression detection runs the whole suite as `pytest tests`. Repos that keep
tests in `test/`, `src/.../tests`, or alongside sources will run **zero** tests
for the regression check, so `regressed` is always `False` and `needs_human` is
under-reported. The CLI doesn't expose `full_test_target` at all.
- **Fix:** auto-detect the test root (or default to the repo root / `pytest`'s
  own discovery), and add a `--full-test-target` flag.
- **Acceptance:** a repo with tests under `test/` reports regressions correctly.

### P0-5. `--base-ref` defaults to `main` with no detection
Many target repos use `master` or a different default branch; the run fails
opaquely at the first `reset()`. 
- **Fix:** detect the default branch (`git symbolic-ref refs/remotes/origin/HEAD`,
  fallback to current branch) when `--base-ref` is omitted.
- **Acceptance:** a `master`-default repo runs without passing `--base-ref`.

---

## 3. P1 — make it a tool people adopt

### P1-1. Machine-readable output (`--json` / results schema)
An eval that only prints human text can't feed CI gates, A/B comparisons, or a
leaderboard — which is the project's stated reason to exist. Emit a versioned
JSON document (per-commit verdicts + aggregate + run metadata: model, base_url,
repo SHA, timestamp, tool version).
- **Acceptance:** `commit-replay ... --json out.json` writes a documented schema;
  a golden test pins the shape.

### P1-2. Cost & token accounting
Comparing models/contexts honestly means reporting **cost**, not just `ai_can`
rate. Capture prompt/completion tokens from the API response and surface
per-run totals (and per-verdict).
- **Acceptance:** scorecard includes tokens and (when a price table is supplied)
  estimated USD.

### P1-3. API robustness in `openai_generate`
A single transient 429/5xx aborts an entire multi-commit run. Add bounded
retries with exponential backoff and a per-request timeout; treat a final
failure as a failed attempt, not a crash.
- **Acceptance:** an injected transient error is retried; a persistent one
  degrades the commit to `fails` and the run completes.

### P1-4. Decide the fate of `repo_assess.py` (orphaned)
`repo_assess.py` is not exported from `__init__.py`, not wired into any CLI, and
carries the broken `with_change_profile` branch (P0-3) plus a second, divergent
copy of "is this a test file" logic. It's dead weight that also leaks moat
vocabulary (see P1-5).
- **Options:** (a) wire it in as a `commit-replay assess` subcommand with its own
  console entry and tests, or (b) remove it from the package. Pick one; don't
  ship it half-attached.
- **Acceptance:** every shipped module is reachable from the public API or the
  CLI and has test coverage.

### P1-5. Remove `CARVE-OUT-SCOPE.md` and proprietary references before publish
The repo ships an internal staging doc describing the proprietary "AthenaClaude
factory," its "moat," Cerebras specifics, and the redaction list. The doc's own
checklist says "Drop `CARVE-OUT-SCOPE.md` before publishing." Docstrings in
`core.py`/`repo_assess.py` also reference factory-internal concepts ("the
factory," "Q1-fix-loop lever," "(class × complexity) operating model") that mean
nothing to an OSS reader.
- **Acceptance:** no `AthenaClaude`/factory/Cerebras vocabulary in shipped files;
  staging doc removed (this BACKLOG can carry forward the still-relevant items).

### P1-6. Packaging completeness
Ship the things adopters expect: `CONTRIBUTING.md`, a `CHANGELOG.md`, README
badges (CI, PyPI, license), a `py.typed` marker (the code is fully typed but
downstreams can't consume the types without it), and an explicit
`Programming Language :: Python :: 3.10/.../3.13` classifier set.
- **Acceptance:** `pip install` exposes types to mypy; PyPI page renders badges.

### P1-7. Unify the "is this a test file?" logic
Three modules classify paths independently: `mine._is_test`/`_TEST_RE`,
`repo_assess.file_kind`, with subtly different rules (suffix lists, `__init__`
handling). Divergence means mining and assessment can disagree about the same
commit.
- **Acceptance:** one shared `paths.py` classifier; mine + assess import it;
  tests cover the tricky cases (`tests/`, `*_test.py`, `*.spec.ts`, `__init__`).

---

## 4. P2 — coverage & credibility (the flywheel)

### P2-1. A second-language runner (prove the Protocol generalizes)
The headline claim is "the harness Protocol generalises." Ship one non-Python
reference runner — JS/`jest` or Go/`go test` — to prove it and to widen the
addressable repo set. `mine.py` already recognizes JS/TS test suffixes, so the
miner is half-ready.
- **Acceptance:** `replay_commit` grades a real commit in a JS repo end-to-end.

### P2-2. Multi-file commits
`max_src_files=1` excludes the large class of real fixes that touch >1 source
file, biasing the sample toward easy changes. Support N-file regeneration
(edit blocks keyed by path).
- **Acceptance:** a two-file fix can be replayed and graded.

### P2-3. Response cache
Replays are expensive and re-run often during harness/context A/B work. Cache
model responses keyed by `(model, prompt hash)` so re-runs are free and
deterministic.
- **Acceptance:** a second run with an unchanged prompt makes zero API calls.

### P2-4. Public leaderboard + self-demo
The project's own notes name a leaderboard as the credibility flywheel aider
proved. Ship (a) a runnable demo that replays this repo against its **own**
history with a mock/local model (no API key, runs in CI), and (b) a small
results table (model × a few well-known OSS repos) generated from the P1-1 JSON.
- **Acceptance:** `make demo` (or a CI job) produces a scorecard with no secrets.

### P2-5. Parallel replays + progress
Replays are fully sequential. Independent commits can run concurrently (separate
worktrees), and a long run needs progress output. Add `--jobs` and a live
counter.
- **Acceptance:** N commits replay across `--jobs` workers with isolated checkouts.

### P2-6. Sampling honesty
`_spread` is documented as a "complexity/recency spread" but only samples evenly
by list index. Either make it genuinely stratify by complexity tier (the
`Candidate.churn`/assessment is available) or fix the docstring. Silent sampling
choices should be logged so a 10-of-400 run doesn't read as "all 400."
- **Acceptance:** the sampling strategy is accurate to its description and logged.

---

## 5. Quality gates to add to CI (cheap, high signal)

- `mypy --strict src` (the code is already typed — lock it in).
- `python -m build` + `twine check dist/*` (catch packaging breakage early).
- A CLI smoke test (`commit-replay --help`, and the P2-4 no-API self-demo).
- Coverage reporting with a floor.

---

## 6. Suggested sequencing

1. **P0-1, P0-2, P0-3** — stop it from destroying data, leaking processes, or
   returning `None`. These are trust-killers.
2. **P1-5 + P1-4** — clean the publishable surface (drop the staging doc, resolve
   the orphaned module). Required before any public release.
3. **P1-1 + P1-2** — JSON output + cost. Unlocks every downstream use (CI gates,
   A/B, leaderboard).
4. **P0-4, P0-5, P1-3, P1-6, P1-7** — robustness + adoption polish.
5. **P2-*** — the flywheel: second runner, multi-file, cache, leaderboard.

Each P0 item is a few hours; the P0+P1 block is the path to a credible first
public release; the P2 block is what turns "a clean tool" into "the eval people
cite."
