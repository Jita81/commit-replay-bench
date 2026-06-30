"""``commit-replay`` CLI — measure a model on a real repo's own tests.

    commit-replay /path/to/repo --model gpt-4o-mini --commits 10
    commit-replay /path/to/repo --model gpt-oss-120b \
        --base-url https://api.cerebras.ai/v1 --api-key-env CEREBRAS_API_KEY

It mines feasible commits (source change + test change), replays each — checkout
parent, overlay the commit's tests, regenerate the source with the model, require
GREEN with no regression — and prints the ai_can / needs_human / fails scorecard.

v1 targets Python repos with a ``pytest`` suite. Other stacks: implement the
:class:`commit_replay_bench.core.RepoHarness` Protocol and call
``replay_commit`` directly.
"""

from __future__ import annotations

import argparse
import sys

from .core import CommitSpec, LiveGitHarness, aggregate, replay_commit
from .generate import openai_generate
from .mine import mine_feasible_commits


def _spread(items: list, k: int) -> list:
    """Evenly sample k items across the list (a complexity/recency spread)."""
    if k >= len(items):
        return items
    idx = sorted({int(i * (len(items) - 1) / (k - 1)) for i in range(k)}) if k > 1 else [0]
    return [items[i] for i in idx]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="commit-replay", description=__doc__.splitlines()[0])
    p.add_argument("repo", help="path to a git checkout of the target repo")
    p.add_argument("--model", required=True, help="model id (e.g. gpt-4o-mini, gpt-oss-120b)")
    p.add_argument("--base-url", default=None, help="OpenAI-compatible base URL (default: OpenAI)")
    p.add_argument("--api-key-env", default="OPENAI_API_KEY", help="env var holding the API key")
    p.add_argument("--python", default=sys.executable, help="python interpreter that runs the repo's tests")
    p.add_argument("--base-ref", default="main", help="branch/ref to reset to between commits (default: main)")
    p.add_argument("--commits", type=int, default=10, help="how many feasible commits to replay")
    p.add_argument("--scan", type=int, default=400, help="how many recent commits to scan when mining")
    p.add_argument("--max-attempts", type=int, default=2, help="regeneration attempts before 'fails'")
    p.add_argument("--max-tokens", type=int, default=8000, help="model max output tokens")
    p.add_argument("--fold-system", action="store_true", help="fold system prompt into the user message")
    args = p.parse_args(argv)

    candidates = mine_feasible_commits(args.repo, limit=args.scan)
    if not candidates:
        print("No feasible commits found (need a source change paired with a test change).", file=sys.stderr)
        return 2
    picked = _spread(candidates, args.commits)
    print(f"mined {len(candidates)} feasible commits; replaying {len(picked)} with {args.model}\n")

    generate = openai_generate(
        model=args.model,
        base_url=args.base_url,
        api_key_env=args.api_key_env,
        max_tokens=args.max_tokens,
        fold_system_into_user=args.fold_system,
    )
    harness = LiveGitHarness(args.repo, args.python, base_ref=args.base_ref)

    results = []
    try:
        for c in picked:
            spec = CommitSpec(c.commit, c.subject, c.src_path, c.test_paths)
            r = replay_commit(harness, spec, generate, max_attempts=args.max_attempts)
            results.append(r)
            print(f"  {c.commit[:8]}  {r.verdict:11s}  {c.subject[:54]}")
    finally:
        harness.reset()

    agg = aggregate(results)
    c = agg["counts"]
    n = agg["n"] or 1
    print(
        f"\n{args.model}: ai_can={c['ai_can']} needs_human={c['needs_human']} fails={c['fails']} "
        f"(graded {agg['n']}, skipped {agg['skipped']})  →  ai_can rate {100 * c['ai_can'] / n:.0f}%"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
