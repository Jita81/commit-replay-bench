"""commit-replay-bench — grade an AI coding agent against a repo's OWN tests.

The honest eval the agentic-coding ecosystem is missing: instead of curated
exercises or a leaderboard you can overfit, replay a repository's *real* commits
and grade each AI-produced change against that repo's *own* held-out test suite.

Per commit: check out the parent, overlay the commit's tests (now RED on the
parent — a valid oracle), have the model regenerate the source change, and
require the tests to pass GREEN without breaking the rest of the suite. Three
honest buckets:

  * ``ai_can``      — green first try, no regressions.
  * ``needs_human`` — green only after a retry, or green but broke other tests.
  * ``fails``       — never green.

Everything is dependency-injected: the model is a ``generate`` callable, the
git/test side is the :class:`RepoHarness` Protocol. Point it at any model
(OpenAI, Cerebras, local vLLM/Ollama) and any repo.
"""

from .core import (
    AI_CAN,
    FAILS,
    NEEDS_HUMAN,
    SKIP,
    CommitSpec,
    LiveGitHarness,
    ReplayResult,
    RepoHarness,
    TestRun,
    aggregate,
    apply_edit_blocks,
    grade,
    parse_edit_blocks,
    replay_commit,
    valid_python,
)
from .mine import Candidate, mine_feasible_commits

__all__ = [
    "AI_CAN",
    "NEEDS_HUMAN",
    "FAILS",
    "SKIP",
    "CommitSpec",
    "ReplayResult",
    "TestRun",
    "RepoHarness",
    "LiveGitHarness",
    "parse_edit_blocks",
    "apply_edit_blocks",
    "valid_python",
    "grade",
    "replay_commit",
    "aggregate",
    "Candidate",
    "mine_feasible_commits",
]
