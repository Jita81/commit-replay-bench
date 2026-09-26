"""The leakage probe: does any fragment of the held-out commit's sha reach the builder?

A replay task is the future commit; its sha is the answer key's address. On the host
posture ``git worktree add`` shares the object store, so a builder that learns even a
short prefix of the sha can ``git show`` the answer. Seven hex characters is git's own
default abbreviation, so the probe checks every substring of that length: a text that
contains none of them contains no usable prefix, suffix or middle of the sha either.

``RecordingSpawn`` stands in for the ``claude -p`` process (it is the builder's
``SpawnFn``): it records the argv (the prompt), the environment and the working
directory the builder was started with, RUNS the given shell commands for real in that
directory (``pwd``, ``basename "$PWD"`` …), and replays a stream-json session in which
the "model" repeats each command's output in its own words — so what the builder saw
reaches the transcript the adapter writes, exactly as it would in a real session.

Navigation
----------
What it is:   A test helper — the sha-fragment scan and a recording, command-running stand-in
              for the Claude Code CLI process.
What it does: ``sha_fragments`` lists every 7-character substring of a sha; ``leaks`` returns
              the fragments found in any of the given texts. ``RecordingSpawn`` records the
              builder's argv, environment and cwd, runs real shell commands in that cwd and
              emits a stream-json session (init, one Bash tool use per command, the outputs
              echoed as assistant text, a successful result).
How:          A sliding window over the sha; ``subprocess.run`` with ``shell=True`` in the cwd
              for each command; JSON lines in the shape ``claude -p --output-format
              stream-json`` emits.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md,
              docs/adr/0012-builder-in-a-sealed-container.md
Works with:   src/crb/core/workspace.py (``opaque_dest`` — the names under test),
              src/crb/core/run.py (the trial worktree), src/crb/builders/claude_code.py (the
              builder whose spawn this replaces), src/crb/builders/adapter.py (the brief and
              the transcript file)
Tested by:    tests/test_run.py, tests/test_builders_guard_corpus.py, tests/test_mine.py,
              tests/test_oracle_controls.py
Touch when:   a new place a builder can read (a new environment variable, a prompt field, a
              mounted path) is added — add it to the texts the tests scan.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

#: git's default abbreviation length: the shortest prefix ``git show`` resolves in practice.
FRAGMENT = 7


def sha_fragments(sha: str, n: int = FRAGMENT) -> list[str]:
    """Every substring of ``sha`` of length ``n`` (lower-cased)."""
    s = sha.lower()
    return [s[i : i + n] for i in range(len(s) - n + 1)]


def leaks(sha: str, *texts: str) -> list[str]:
    """The sha fragments that appear in any of ``texts`` (case-insensitive); empty = clean."""
    frags = sha_fragments(sha)
    low = [t.lower() for t in texts]
    return sorted({f for f in frags for t in low if f in t})


class _Handle:
    """What the builder reads from a spawned process: lines, then an exit status."""

    def __init__(self, lines: Sequence[str]) -> None:
        self._lines = list(lines)
        self.returncode: int | None = 0
        self.timed_out = False
        self.stderr_tail = ""

    def lines(self) -> Iterator[str]:
        yield from self._lines

    def kill(self) -> None:
        self._lines = []


class RecordingSpawn:
    """A ``SpawnFn`` that records the invocation and runs ``commands`` in the cwd."""

    def __init__(self, commands: Sequence[str] = ()) -> None:
        self.commands = tuple(commands)
        self.argv: list[str] = []
        self.env: dict[str, str] = {}
        self.cwd: Path | None = None
        #: The ``.git`` file of the worktree as the builder could ``cat`` it.
        self.git_file = ""
        #: ``command -> stdout`` as the builder saw it.
        self.outputs: dict[str, str] = {}

    def __call__(
        self, argv: list[str], env: Mapping[str, str], cwd: Path, timeout_s: int
    ) -> _Handle:
        del timeout_s
        self.argv, self.env, self.cwd = list(argv), dict(env), Path(cwd)
        dotgit = Path(cwd) / ".git"
        self.git_file = dotgit.read_text(encoding="utf-8") if dotgit.is_file() else ""
        blocks: list[str] = [_line({"type": "system", "subtype": "init", "session_id": "s"})]
        for i, cmd in enumerate(self.commands):
            out = subprocess.run(
                cmd, shell=True, cwd=cwd, capture_output=True, text=True, check=False
            ).stdout
            self.outputs[cmd] = out
            tool = {"type": "tool_use", "id": f"tu{i}", "name": "Bash", "input": {"command": cmd}}
            blocks.append(_assistant(tool))
            blocks.append(
                _line(
                    {
                        "type": "user",
                        "message": {
                            "role": "user",
                            "content": [
                                {"type": "tool_result", "tool_use_id": f"tu{i}", "content": out}
                            ],
                        },
                    }
                )
            )
            # the model reads the output and repeats it — what it saw reaches the transcript
            blocks.append(_assistant({"type": "text", "text": f"`{cmd}` printed: {out}"}))
        blocks.append(
            _line(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "num_turns": len(self.commands) + 1,
                    "result": "",
                    "session_id": "s",
                    "total_cost_usd": 0.0,
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                    "structured_output": {"done": False, "summary": "looked around"},
                }
            )
        )
        return _Handle(blocks)

    def seen(self) -> list[str]:
        """Everything the builder was handed or could read: argv, env values, cwd, the
        ``.git`` pointer and the commands' outputs."""
        return [
            *self.argv,
            *(f"{k}={v}" for k, v in self.env.items()),
            str(self.cwd or ""),
            self.git_file,
            *self.outputs.values(),
        ]


def _assistant(block: Mapping[str, Any]) -> str:
    return _line(
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [dict(block)],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
            "session_id": "s",
        }
    )


def _line(obj: Mapping[str, Any]) -> str:
    return json.dumps(dict(obj))
