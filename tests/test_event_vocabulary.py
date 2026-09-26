"""The event vocabulary ratchet (J-TEL-12): every action a ``StepEvent`` can carry is in
docs/API.md's "Event vocabulary" table, so a renamed or added action cannot break a log
shipper, a dashboard or a test silently.

The events table is the audit trail and the SSE stream is the UI's contract; an
undocumented contract is not one. This suite walks every ``emit`` call site in
``src/crb`` with the AST — every way the code names an action — and asserts each literal
appears in the table. A new action fails here until its row is written.

Navigation
----------
What it is:   The documentation ratchet for event action names.
What it does: Extracts every action literal from the emit call sites in ``src/crb`` (emitter
              ``emit`` / ``error`` / ``timed``, the core's ``_emit(on_event, "…")`` helpers,
              plain ``on_event("…", …)`` callbacks, ``append_event(action=…)``, the factory
              loop's ``self._emit("…", item_id)``, and the builders' ``builder.``-prefixed
              forms) and asserts each is a code span in docs/API.md#event-vocabulary; also
              asserts the table names no action the code no longer emits, and that every
              documented action has its plain sentence in the UI's ``ACTION_HELP``
              (ui/src/lib/verdict.ts) — so the Python half alone fails when a row is added
              without the sentence the live log shows.
How:          ``ast`` over ``src/crb/**/*.py``; a regex over the vocabulary section of the doc.
Layer:        tests — docs/ARCHITECTURE.md#72-observability
ADRs:         none
Works with:   docs/API.md (the table), src/crb/observability/events.py (the envelope and the
              ``timed`` suffixes), src/crb/builders/adapter.py (``BUILDER_EVENT_PREFIX``),
              src/crb/server/worker.py and src/crb/factory/loop.py (the largest emitters)
Tested by:    tests/test_event_vocabulary.py
Touch when:   an action is added or renamed — write its row in docs/API.md first.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "crb"
DOC = ROOT / "docs" / "API.md"

#: Functions whose string argument names an action.
EMITTERS = {
    "emit",
    "_emit",
    "error",
    "timed",
    "on_event",
    "cb",
    "append_event",
    "append_system_event",
}
#: ``builder_on_event`` (src/crb/builders/adapter.py) prefixes every builder-level action.
BUILDER_PREFIX = "builder."
#: ``Emitter.timed`` emits these suffixes.
TIMED_SUFFIXES = (".start", ".done", ".error")


def _literals(node: ast.AST) -> list[str]:
    """The string(s) an action expression can evaluate to (a constant, a prefixed constant,
    or either branch of ``"a" if x else "b"``)."""
    if isinstance(node, ast.IfExp):
        return _literals(node.body) + _literals(node.orelse)
    lit = _literal(node)
    return [lit] if lit is not None else []


def _literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    # BUILDER_EVENT_PREFIX + "discard"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = node.left, node.right
        if (
            isinstance(left, ast.Name)
            and left.id == "BUILDER_EVENT_PREFIX"
            and isinstance(right, ast.Constant)
            and isinstance(right.value, str)
        ):
            return BUILDER_PREFIX + right.value
    return None


def _actions_in(path: Path) -> set[str]:
    """Every action literal an emit call in ``path`` can produce."""
    out: set[str] = set()
    in_builders = path.parent == SRC / "builders" and path.name != "adapter.py"
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = (
            fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ""
        )
        if name not in EMITTERS:
            continue
        candidates: list[ast.AST] = [k.value for k in node.keywords if k.arg == "action"]
        args = node.args
        if name in {"emit", "error", "timed"} and isinstance(fn, ast.Attribute) and len(args) >= 2:
            candidates.append(args[1])  # emitter.emit(stage, action, …)
        if name in {"_emit", "emit"} and len(args) >= 2 and isinstance(args[0], ast.Name):
            candidates.append(args[1])  # _emit(on_event, action, …)
        if name in {"_emit", "on_event", "cb"} and args:
            candidates.append(args[0])  # self._emit(action, item_id) / on_event(action, payload)
        for lit in (x for c in candidates for x in _literals(c)):
            if "." not in lit:
                continue
            if name == "timed":
                out.update(lit + s for s in TIMED_SUFFIXES)
            elif in_builders and lit.startswith("build."):
                # a builder's own events reach a replay trace through builder_on_event
                # (prefixed) and a factory trace through the raw callback (unprefixed)
                out.update({lit, BUILDER_PREFIX + lit})
            else:
                out.add(lit)
    return out


def emitted_actions() -> dict[str, set[str]]:
    """action → the files that emit it, over all of ``src/crb``."""
    found: dict[str, set[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        for action in _actions_in(path):
            found.setdefault(action, set()).add(str(path.relative_to(ROOT)))
    return found


def documented_actions() -> set[str]:
    """Every action named in the table's ``action`` column (the second cell of each row)."""
    text = DOC.read_text(encoding="utf-8")
    m = re.search(r"^## Event vocabulary\n(.*?)(?=^## )", text, re.M | re.S)
    assert m, "docs/API.md has no '## Event vocabulary' section"
    out: set[str] = set()
    for line in m.group(1).splitlines():
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        if len(cells) == 6 and cells[0] not in {"stage", "---"}:
            out.update(re.findall(r"`([a-z_]+(?:\.[a-z_]+)+)`", cells[1]))
    return out


def test_every_emitted_action_is_in_the_vocabulary_table() -> None:
    emitted = emitted_actions()
    assert len(emitted) > 60, sorted(emitted)  # the walker found the real call sites
    documented = documented_actions()
    missing = {a: sorted(f) for a, f in emitted.items() if a not in documented}
    assert not missing, f"emitted but not in docs/API.md#event-vocabulary: {missing}"


def test_the_vocabulary_table_names_no_ghost_action() -> None:
    """A row for an action nothing emits is a consumer waiting for an event that never
    comes — allowed only for the families the table documents by pattern."""
    emitted = set(emitted_actions())
    ghosts = {
        a
        for a in documented_actions()
        if a not in emitted and not a.startswith(("builder.build.", "oracle.mutation."))
    }
    assert not ghosts, f"documented but never emitted: {sorted(ghosts)}"


def test_the_walker_sees_every_emit_shape() -> None:
    """The shapes the code uses, one example each, so a refactor of an emit helper that the
    walker no longer recognises fails here rather than silently shrinking the ratchet."""
    emitted = emitted_actions()
    assert "run.claimed" in emitted  # emitter.emit("system", "run.claimed", …)
    assert "run.error" in emitted  # emitter.error("system", "run.error", exc)
    assert "mine.candidate" in emitted  # _emit(on_event, "mine.candidate", …)
    assert "item.start" in emitted  # FactoryLoop: self._emit("item.start", item.id, …)
    assert "run.cancel_requested" in emitted  # append_event(action="run.cancel_requested")
    assert {"run.reclaimed", "run.abandoned"} <= set(emitted)  # action="a" if x else "b"
    assert "signoff.revoked" in emitted  # append_system_event(action="signoff.revoked")
    assert "builder.discard" in emitted  # emit(on_event, BUILDER_EVENT_PREFIX + "discard")
    assert "builder.build.turn" in emitted and "build.turn" in emitted  # a builder's own
    assert "grade.belt" in emitted  # core/grade.py on_event / _emit


#: The UI's one plain sentence per action (the live log's explanation).
VERDICT_TS = ROOT / "ui" / "src" / "lib" / "verdict.ts"


def test_every_documented_action_has_its_ui_sentence() -> None:
    """The UI's own check (ui/src/lib/verdict.test.ts) runs only in the UI suite; a vocabulary
    row added with a Python change and no ``ACTION_HELP`` sentence passed every Python gate
    and broke the UI suite (2026-09-25, value wave stream L). Mirrored here so either half
    catches it."""
    text = VERDICT_TS.read_text(encoding="utf-8")
    m = re.search(
        r"export const ACTION_HELP: Record<string, string> = \{(.*?)^\}", text, re.M | re.S
    )
    assert m, "ui/src/lib/verdict.ts has no ACTION_HELP table"
    keys = set(re.findall(r"^\s*'([a-z_]+(?:\.[a-z_]+)+)':", m.group(1), re.M))
    assert len(keys) > 60, sorted(keys)
    missing = sorted(
        a
        for a in documented_actions()
        if a not in keys and not (a.startswith("builder.build.") and a[len("builder.") :] in keys)
    )
    assert not missing, (
        f"documented in docs/API.md but no ACTION_HELP sentence in verdict.ts: {missing}"
    )
