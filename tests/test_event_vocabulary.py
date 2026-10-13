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
What it does: Extracts every action literal from the emit call sites in ``src/crb`` — a
              literal or a string constant passed in its place, assigned or imported from
              ``crb`` in the call's own scope or an enclosing one (P-174) — (emitter
              ``emit`` / ``error`` / ``timed``, the core's ``_emit(on_event, "…")`` helpers,
              plain ``on_event("…", …)`` callbacks, ``append_event(action=…)``, the factory
              loop's ``self._emit("…", item_id)``, the account trail's
              ``record_user_event(action=…)``, and the builders' ``builder.``-prefixed forms)
              and asserts each is a code span in docs/API.md#event-vocabulary; also asserts
              the table names no action the code no longer emits, that every documented
              action has its plain sentence in the UI's ``ACTION_HELP``
              (ui/src/lib/verdict.ts) — so the Python half alone fails when a row is added
              without the sentence the live log shows — and that any function forwarding an
              ``action`` parameter to an emitter is itself walked (P-151).
How:          ``ast`` over ``src/crb/**/*.py``; a regex over the vocabulary section of the doc.
Layer:        tests — docs/ARCHITECTURE.md#72-observability
ADRs:         none
Works with:   docs/API.md (the table), src/crb/observability/events.py (the envelope and the
              ``timed`` suffixes), src/crb/builders/adapter.py (``BUILDER_EVENT_PREFIX``),
              src/crb/server/worker.py and src/crb/factory/loop.py (the largest emitters)
Tested by:    tests/test_event_vocabulary.py
Touch when:   never for a new repository; an action is added or renamed — write its row in
              docs/API.md first.
"""

from __future__ import annotations

import ast
import functools
import re
from collections.abc import Iterator
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
    # the account trail's writer (src/crb/server/routes/admin.py): it forwards ``action`` to
    # ``append_system_event``, so its callers name the ``user.*`` actions (P-151)
    "record_user_event",
    # the Learn writes' one serialised step (src/crb/server/routes/learn.py): it forwards
    # ``action`` to ``append_system_event``, so its callers name the ``learn.*`` actions (P-431)
    "_learn_step",
    # the decided-under-the-lock writer (src/crb/store/events.py): its callers name the action
    # (``reading.*`` — P-792; ``campaign.*``; ``acceptance.written``), most by a constant they
    # import from the core module that owns it, so they are read like the rest
    "append_event_checked",
}
#: Functions that forward an ``action`` parameter to an emitter but are only ever handed on
#: as an ``on_event`` callback — their call sites are ``on_event("…")``, which the walker reads.
CALLBACK_ONLY = {"on_skip", "_cb"}
#: ``builder_on_event`` (src/crb/builders/adapter.py) prefixes every builder-level action.
BUILDER_PREFIX = "builder."
#: ``Emitter.timed`` emits these suffixes.
TIMED_SUFFIXES = (".start", ".done", ".error")


def _literals(node: ast.AST, consts: dict[str, str | None] | None = None) -> list[str]:
    """The string(s) an action expression can evaluate to (a constant, a prefixed constant,
    a string constant ``consts`` binds the name to, or either branch of
    ``"a" if x else "b"``)."""
    if isinstance(node, ast.IfExp):
        return _literals(node.body, consts) + _literals(node.orelse, consts)
    lit = _literal(node, consts or {})
    return [lit] if lit is not None else []


def _module_constants(tree: ast.Module) -> dict[str, str]:
    """``NAME = "a.b"`` / ``NAME: str = "a.b"`` at module level — a name an emit call may pass
    as its action (P-174: such an action escaped the ratchet while it read literals only)."""
    out: dict[str, str] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            targets, value = list(stmt.targets), stmt.value
        elif isinstance(stmt, ast.AnnAssign):
            targets, value = [stmt.target], stmt.value
        else:
            continue
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            continue
        for t in targets:
            if isinstance(t, ast.Name):
                out[t.id] = value.value
    return out


@functools.cache
def _constants_of(module: str) -> dict[str, str]:
    """The module-level string constants of ``crb.x.y`` (``src/crb/x/y.py`` or its package's
    ``__init__.py``); nothing for a module outside ``src/crb``."""
    base = SRC.parent.joinpath(*module.split("."))
    for path in (base.with_suffix(".py"), base / "__init__.py"):
        if path.is_file():
            return _module_constants(ast.parse(path.read_text(encoding="utf-8")))
    return {}


#: Comprehensions: each is a scope, whose first iterable the enclosing scope evaluates.
_COMPS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
#: The nodes that open a scope of their own: a name bound inside one is not the enclosing
#: scope's name.
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda, *_COMPS)


def _children(scope: ast.AST) -> list[ast.AST]:
    """The child nodes ``scope`` evaluates itself: a comprehension's are all but its first
    iterable."""
    if isinstance(scope, _COMPS):
        first, *rest = scope.generators
        elts = [scope.key, scope.value] if isinstance(scope, ast.DictComp) else [scope.elt]
        return [*elts, first.target, *first.ifs, *rest]
    return list(ast.iter_child_nodes(scope))


def _own_nodes(scope: ast.AST) -> Iterator[ast.AST]:
    """The nodes of ``scope`` outside every scope nested in it (a nested function, class,
    lambda or comprehension is yielded, never entered, but a comprehension's first iterable
    is ``scope``'s own)."""
    stack = _children(scope)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, _COMPS):
            stack.append(node.generators[0].iter)
        elif not isinstance(node, _SCOPES):
            stack.extend(ast.iter_child_nodes(node))


def _comp_walrus(comp: ast.AST) -> Iterator[str]:
    """The names a walrus in ``comp``, or in a comprehension nested in it, binds: they are the
    enclosing function's (PEP 572), never the comprehension's."""
    for node in _own_nodes(comp):
        if isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
            yield node.target.id
        elif isinstance(node, _COMPS):
            yield from _comp_walrus(node)


def _bindings(scope: ast.AST) -> dict[str, str | None]:
    """The names ``scope`` binds itself: a string constant (``NAME = "a.b"``,
    ``NAME: str = "a.b"``, or ``from crb.x import NAME [as ALIAS]`` where ``NAME`` is a string
    constant of ``crb.x``), else ``None`` — a name bound to anything else (an argument, an
    assignment, another import) hides an enclosing scope's constant of that name.

    A route names an action by its core module's constant (``readings.py``:
    ``action=READING_EVENT_ACTION``); while the walker resolved only the file's own constants,
    ``reading.registered`` and the ``campaign.*`` actions escaped the table. Read per scope,
    an import in one function never names the action another function binds itself."""
    out: dict[str, str | None] = {}
    consts: dict[str, str] = {}
    assigned: list[tuple[int, int, str, str]] = []  # read in source order: the last one wins
    if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
        a = scope.args
        params = [*a.posonlyargs, *a.args, *a.kwonlyargs, *filter(None, (a.vararg, a.kwarg))]
        out.update(dict.fromkeys((x.arg for x in params), None))
    walrus = set(_comp_walrus(scope)) if isinstance(scope, _COMPS) else set()
    for node in _own_nodes(scope):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            if node.id not in walrus:
                out.setdefault(node.id, None)
        elif isinstance(node, _COMPS):
            if not isinstance(scope, _COMPS):  # a comprehension's walrus binds out here
                for name in _comp_walrus(node):
                    out.setdefault(name, None)
        elif isinstance(node, _SCOPES[:3]):
            out.setdefault(node.name, None)
        elif isinstance(node, ast.Import):
            out.update(dict.fromkeys((x.asname or x.name.split(".")[0] for x in node.names), None))
        elif isinstance(node, ast.ImportFrom):
            source = (
                _constants_of(node.module)
                if node.level == 0
                and node.module
                and (node.module == "crb" or node.module.startswith("crb."))
                else {}
            )
            for alias in node.names:
                name = alias.asname or alias.name
                out.setdefault(name, None)
                if alias.name in source:
                    consts[name] = source[alias.name]
        if isinstance(node, ast.Assign | ast.AnnAssign):
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                assigned += [
                    (node.lineno, node.col_offset, x.id, value.value)
                    for x in targets
                    if isinstance(x, ast.Name)
                ]
    consts.update({name: value for *_, name, value in sorted(assigned)})
    return {**out, **consts}


def _literal(node: ast.AST, consts: dict[str, str | None]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
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
    """Every action literal an emit call in ``path`` can produce, each name read in the scope
    of the call that uses it: the call's own function, then each enclosing function, then the
    module (a class body's names are not its methods')."""
    out: set[str] = set()
    in_builders = path.parent == SRC / "builders" and path.name != "adapter.py"

    def walk(scope: ast.AST, outer: dict[str, str | None]) -> None:
        consts = {**outer, **_bindings(scope)}
        for node in _own_nodes(scope):
            if isinstance(node, _SCOPES):
                walk(node, outer if isinstance(scope, ast.ClassDef) else consts)
            elif isinstance(node, ast.Call):
                out.update(_call_actions(node, consts, in_builders))

    walk(ast.parse(path.read_text(encoding="utf-8")), {})
    return out


def _call_actions(node: ast.Call, consts: dict[str, str | None], in_builders: bool) -> set[str]:
    """The actions one call names, when it is an emit call."""
    out: set[str] = set()
    fn = node.func
    name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ""
    if name not in EMITTERS:
        return out
    candidates: list[ast.AST] = [k.value for k in node.keywords if k.arg == "action"]
    args = node.args
    if name in {"emit", "error", "timed"} and isinstance(fn, ast.Attribute) and len(args) >= 2:
        candidates.append(args[1])  # emitter.emit(stage, action, …)
    if name in {"_emit", "emit"} and len(args) >= 2 and isinstance(args[0], ast.Name):
        candidates.append(args[1])  # _emit(on_event, action, …)
    if name in {"_emit", "on_event", "cb"} and args:
        candidates.append(args[0])  # self._emit(action, item_id) / on_event(action, payload)
    for lit in (x for c in candidates for x in _literals(c, consts)):
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


def test_every_function_that_forwards_an_action_is_walked() -> None:
    """P-151: ``record_user_event(db, action=…)`` forwards its ``action`` to
    ``append_system_event``, but the walker did not know its name, so every ``user.*`` action
    was emitted with no row in the table and no test noticed. Any function that takes an
    ``action`` parameter and hands it to an emitter is itself an emitter: it must be in
    ``EMITTERS`` (or be a callback only, ``CALLBACK_ONLY``), or this fails."""
    unwalked: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        for fn in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            params = {a.arg for a in [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]}
            if "action" not in params or fn.name in EMITTERS | CALLBACK_ONLY:
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                passed = [k.value for k in node.keywords if k.arg == "action"] + node.args[:2]
                if name in EMITTERS and any(
                    isinstance(v, ast.Name) and v.id == "action" for v in passed
                ):
                    unwalked.append(f"{path.relative_to(ROOT)}::{fn.name}")
    assert not unwalked, f"add these to EMITTERS (their callers name actions): {unwalked}"


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
    assert "user.created" in emitted  # record_user_event(db, action="user.created", …)
    assert "reading.reserved" in emitted  # append_event_checked(…, action="reading.reserved")
    # append_event_checked(…, action=READING_EVENT_ACTION), imported from crb.core.reading
    assert "reading.registered" in emitted


def test_an_action_named_by_a_module_constant_is_seen(tmp_path: Path) -> None:
    """``action=SOME_CONSTANT`` is how a module names an action it also queries by; the walker
    read literals only, so such an action escaped the table entirely (found 2026-09-26 while
    adding ``repo.baseline_read``: the ratchet stayed green with no row — P-174)."""
    src = tmp_path / "mod.py"
    src.write_text(
        'READ: str = "demo.read"\n'
        'OTHER = "demo.other"\n'
        "def f(db):\n"
        "    append_system_event(db, trace_id='t', action=READ)\n"
        "    emitter.emit('system', OTHER)\n"
        "    local = 'demo.local'\n"
        "    append_system_event(db, trace_id='t', action=local)\n"
        "def g(db, local):\n"
        "    append_system_event(db, trace_id='t', action=local)\n",
        encoding="utf-8",
    )
    # the two module constants resolve, and so does f's own constant; g's argument is not f's
    assert _actions_in(src) == {"demo.read", "demo.other", "demo.local"}


def test_an_action_named_by_an_imported_constant_is_seen(tmp_path: Path) -> None:
    """A route names the action its core module owns: ``from crb.core.reading import
    READING_EVENT_ACTION``, then ``action=READING_EVENT_ACTION``. The walker resolved only the
    file's own constants, so ``reading.registered``, the ``campaign.*`` actions and
    ``acceptance.written`` were written with no row in the table and the ratchet stayed green
    (found on the review of the Wave 3 pre-run PR)."""
    src = tmp_path / "mod.py"
    src.write_text(
        "from crb.core.reading import READING_EVENT_ACTION\n"
        "from crb.core.campaign import CAMPAIGN_RELEASED as RELEASED\n"
        "def f(factory):\n"
        "    from crb.core.acceptance import EVENT_ACTION\n"
        "    append_event_checked(factory, action=READING_EVENT_ACTION)\n"
        "    append_event_checked(factory, action=RELEASED)\n"
        "    append_event_checked(factory, action=EVENT_ACTION)\n",
        encoding="utf-8",
    )
    # an import at the top or inside a function, under its own name or an alias
    assert _actions_in(src) == {"reading.registered", "campaign.released", "acceptance.written"}


def test_a_name_is_read_in_the_scope_of_the_call_that_uses_it(tmp_path: Path) -> None:
    """The imports of every function were read into one map for the file, so a function that
    binds a name itself (``EVENT_ACTION = "demo.other"``) was read as the action another
    function imports under that name, and its own action escaped the table (CodeRabbit on the
    review-only PR #91). Each name is now read in the call's own scope, then each enclosing
    function's, then the module's; a class body's names are not its methods'."""
    src = tmp_path / "mod.py"
    src.write_text(
        'EVENT_ACTION = "demo.module"\n'
        "def imports(factory):\n"
        "    from crb.core.acceptance import EVENT_ACTION\n"
        "    append_event_checked(factory, action=EVENT_ACTION)\n"
        "def assigns(factory):\n"
        '    EVENT_ACTION = "demo.other"\n'
        "    append_event_checked(factory, action=EVENT_ACTION)\n"
        "    def inner():\n"
        "        append_event_checked(factory, action=EVENT_ACTION)\n"
        "def takes(factory, EVENT_ACTION):\n"
        "    append_event_checked(factory, action=EVENT_ACTION)\n"
        "class Holder:\n"
        '    EVENT_ACTION = "demo.class"\n'
        "    def method(self, factory):\n"
        "        append_event_checked(factory, action=EVENT_ACTION)\n"
        "append_event_checked(None, action=EVENT_ACTION)\n",
        encoding="utf-8",
    )
    # the import names acceptance.written in its own function only; the assignment names
    # demo.other there and in the closure; an argument names nothing; the method and the
    # module read the module's constant, never the class body's
    assert _actions_in(src) == {"acceptance.written", "demo.other", "demo.module"}


def test_a_comprehension_is_a_scope_of_its_own(tmp_path: Path) -> None:
    """A comprehension's loop variable was read as its function's own name, so a loop variable
    named like a module constant hid that constant from every emit call after the comprehension,
    and the call's action escaped the table (CodeRabbit on the review-only PR #92). A
    comprehension is now a scope: its first iterable is read in the enclosing scope, its loop
    variables only inside it, and a walrus in it binds the enclosing function's name (PEP 572)."""
    src = tmp_path / "mod.py"
    src.write_text(
        'EVENT_ACTION = "demo.module"\n'
        'OTHER = "demo.other"\n'
        'FIRST = "demo.first"\n'
        'HIDDEN = "demo.hidden"\n'
        'WALRUS = "demo.walrus"\n'
        'DEEP = "demo.deep"\n'
        "def after(factory, rows):\n"
        "    names = [EVENT_ACTION for EVENT_ACTION in rows]\n"
        "    append_event_checked(factory, action=EVENT_ACTION)\n"
        "def reads(factory, rows):\n"
        "    return [append_event_checked(factory, action=OTHER) for r in rows]\n"
        "def first(factory):\n"
        "    return [FIRST for FIRST in append_event_checked(factory, action=FIRST)]\n"
        "def inside(factory, rows):\n"
        "    return {append_event_checked(factory, action=HIDDEN) for HIDDEN in rows}\n"
        "def walrus(factory, rows):\n"
        "    [(WALRUS := r) for r in rows]\n"
        "    append_event_checked(factory, action=WALRUS)\n"
        "def deep(factory, rows):\n"
        "    {k: [(DEEP := y) for y in v] for k, v in rows}\n"
        "    append_event_checked(factory, action=DEEP)\n",
        encoding="utf-8",
    )
    # after the comprehension and inside it, an unshadowed constant resolves; the first
    # iterable reads the enclosing scope's name; a loop variable names nothing; a walrus,
    # in the comprehension or one nested in it, hides the constant in its function
    assert _actions_in(src) == {"demo.module", "demo.other", "demo.first"}


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
