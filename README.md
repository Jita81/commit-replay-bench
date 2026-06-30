# commit-replay-bench

**Grade an AI coding agent against a repo's _own_ tests — the honest, overfit-proof coding eval.**

Most coding evals are curated exercises (easy to overfit) or leaderboards (easy to game). `commit-replay-bench` does something harder to fake: it replays a repository's **real commits** and grades each AI-produced change against that repo's **own held-out test suite**.

For each commit it:

1. checks out the **parent** (the state before the fix),
2. overlays the commit's **tests** — which now **fail** on the parent (a genuine RED oracle),
3. asks your model to **regenerate the source change**,
4. requires the tests to pass **GREEN** with **no regressions** in the rest of the suite.

Then it grades into three honest buckets:

| Verdict | Meaning |
|---|---|
| `ai_can` | Green on the first try, no regressions — the agent reproduces the change unaided. |
| `needs_human` | Green only after a retry, **or** green but it broke other tests — a human must reconcile. |
| `fails` | Never green. |

Because the oracle is the repo's *real* tests and the ground truth is the *real* commit, you can't overfit it the way you can a fixed exercise set.

## Why this exists

The agentic-coding ecosystem ships a lot of context tricks — `CLAUDE.md`, repo rules, prompt scaffolds, "loop engineering" — and **almost nobody measures whether they actually help.** This is the eval that closes that loop: point it at a real repo and a real model and get an honest `ai_can` rate. A/B your context, your model, your harness — against ground truth.

## Install

```bash
pip install commit-replay-bench[openai]
```

(The core engine is **standard-library only**; the `openai` extra is just for the bundled OpenAI-compatible model adapter.)

## Use (CLI)

v1 targets **Python repos with a `pytest` suite**. Clone the target repo, set up a venv that can run its tests, then:

```bash
# OpenAI
commit-replay /path/to/repo --model gpt-4o-mini --commits 10 --python /path/to/repo/.venv/bin/python

# any OpenAI-compatible endpoint (Cerebras, Together, local vLLM, Ollama, …)
commit-replay /path/to/repo --model gpt-oss-120b \
  --base-url https://api.cerebras.ai/v1 --api-key-env CEREBRAS_API_KEY
commit-replay /path/to/repo --model llama3.1 --base-url http://localhost:11434/v1   # Ollama
```

Output:

```
mined 56 feasible commits; replaying 10 with gpt-4o-mini

  a1b2c3d4  ai_can       fix: handle empty input to merge_intervals
  e5f6a7b8  fails        Optimise the scheduler hot path
  ...
gpt-4o-mini: ai_can=4 needs_human=1 fails=5 (graded 10, skipped 0)  →  ai_can rate 40%
```

## Use (library)

```python
from commit_replay_bench import mine_feasible_commits, LiveGitHarness, CommitSpec, replay_commit, aggregate
from commit_replay_bench.generate import openai_generate

gen = openai_generate(model="gpt-4o-mini")
harness = LiveGitHarness("/path/to/repo", "/path/to/repo/.venv/bin/python", base_ref="main")

results = []
for c in mine_feasible_commits("/path/to/repo")[:10]:
    results.append(replay_commit(harness, CommitSpec(c.commit, c.subject, c.src_path, c.test_paths), gen))

print(aggregate(results)["counts"])
```

## Plug in your own model or stack

- **Any model:** write a `generate(*, subject, src_path, src, tests, prior_failure) -> list[tuple[str, str]]` callable (return parsed SEARCH/REPLACE blocks — see `parse_edit_blocks`). The bundled `openai_generate` is just one implementation.
- **Non-Python / non-pytest repos:** implement the `RepoHarness` Protocol (git checkout + your test runner) and call `replay_commit` directly. `LiveGitHarness` is the reference Python/pytest implementation.

## Design notes (hard-won)

- **SEARCH/REPLACE, not unified diffs** — models reliably mis-form unified diffs against large files; SEARCH/REPLACE with a tolerant parser + fuzzy (indentation-insensitive) apply lands far more edits.
- **`py_compile` gate** — a mis-spliced edit that breaks syntax becomes a retryable attempt, never a whole-suite crash.
- **Test timeout** — a generated edit that blocks on tty/stdin is a failed attempt, never an infinite wait.
- **Honest `SKIP`** — if the commit's test already passes on the parent, it isn't a valid oracle and the commit is skipped (not counted).

## Limitations

- Grades **behavioural correctness** (does it pass the real tests), not style/maintainability — though "passes the repo's own tests with no regressions" is a high bar.
- v1 is Python/pytest (the harness Protocol generalises; runners for other stacks welcome).
- A repo's difficulty bounds the absolute rate; the **relative** comparison (model A vs B, context on vs off) is the robust signal.

## License

MIT.
