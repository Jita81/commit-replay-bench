"""One owner per database write lock: each PostgreSQL advisory lock id is taken in one function.

Navigation
----------
What it is:   The ratchet that keeps every table's write lock in one helper, so two parallel
              changes cannot each add their own copy of the same lock (P-224).
What it does: Walks every module under src/crb, finds each ``pg_advisory_xact_lock(<id>)``
              literal and the function that holds it, and fails when an id is taken in more
              than one function, or when the events lock is taken anywhere but
              ``crb.store.events.lock_event_writes``; a synthetic tree with two helpers for one
              id must fail, so the walker cannot pass by finding nothing.
How:          ``ast`` over the source files: a string constant carrying the lock call is
              attributed to its innermost enclosing function; the ids are grouped by owner.
Layer:        tests — docs/ARCHITECTURE.md#72-observability
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md
Works with:   src/crb/store/events.py (``lock_event_writes``, the events lock every ``seq``
              writer takes), src/crb/store/ledger.py and src/crb/store/jobs.py (the grades,
              reviews and runs locks), src/crb/server/auth.py and
              src/crb/server/routes/signoffs.py (the users and signoffs locks),
              docs/PREVENTION.md (P-224, the class this stops), docs/DECISION-LOG.md (DL-085,
              the rule)
Tested by:    tests/test_advisory_lock_owners.py
Touch when:   never for a new repository; a table gains its own write lock (give it a new id,
              in one helper every writer calls — never a second helper for an id in use).
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "crb"
_LOCK = re.compile(r"pg_advisory_xact_lock\((\d+)\)")


def _owners(src: Path = SRC) -> dict[str, set[str]]:
    """Map each advisory lock id to the ``module:function`` names that take it."""
    owners: dict[str, set[str]] = defaultdict(set)
    for path in sorted(src.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module = ".".join(path.relative_to(src.parent).with_suffix("").parts)

        def visit(node: ast.AST, scope: str, module: str = module) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    visit(child, f"{scope}.{child.name}" if scope else child.name)
                    continue
                if isinstance(child, ast.Constant) and isinstance(child.value, str):
                    for lock_id in _LOCK.findall(child.value):
                        owners[lock_id].add(f"{module}:{scope or '<module>'}")
                visit(child, scope)

        visit(tree, "")
    return owners


def _shared(owners: dict[str, set[str]]) -> dict[str, list[str]]:
    return {lock_id: sorted(names) for lock_id, names in owners.items() if len(names) > 1}


def test_every_advisory_lock_id_is_taken_in_one_function() -> None:
    """P-224: streams A and C of the security review each added the ``events`` write lock
    (id 7332) under its own name, and the merge found two helpers for one lock. A second
    helper for an id already in use fails here, naming both."""
    owners = _owners()
    assert len(owners) >= 5, f"too few advisory locks found under src/crb: {sorted(owners)}"
    assert not _shared(owners), (
        f"an advisory lock id is taken in more than one function: {_shared(owners)}"
    )


def test_the_events_lock_lives_in_lock_event_writes() -> None:
    """Every writer that allocates an ``events`` ``seq`` calls this one helper (DL-085)."""
    assert _owners()["7332"] == {"crb.store.events:lock_event_writes"}


def test_two_helpers_for_one_lock_are_caught(tmp_path: Path) -> None:
    """The walker is not vacuous: the shape the merge found — two functions, one id — fails."""
    pkg = tmp_path / "crb"
    (pkg / "store").mkdir(parents=True)
    (pkg / "store" / "events.py").write_text(
        "def lock_event_writes(s):\n"
        '    s.execute(text("SELECT pg_advisory_xact_lock(7332)"))\n'
        "\n\n"
        "def lock_event_seq(s):\n"
        '    s.execute(text("SELECT pg_advisory_xact_lock(7332)"))\n',
        encoding="utf-8",
    )
    assert _shared(_owners(pkg)) == {
        "7332": ["crb.store.events:lock_event_seq", "crb.store.events:lock_event_writes"]
    }
