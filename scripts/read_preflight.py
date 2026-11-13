#!/usr/bin/env python3
"""The read preflight: a script that reads run events proves it can see its keys first.

    python scripts/read_preflight.py --script scripts/a_read.py --events events.json
    # exit 0: the script's lookups and the served events agree; exit 6: they do not

    import read_preflight
    START = read_preflight.Expect("builder.author_test.start", "task_id", "envelope")
    EVENT_EXPECTATIONS = (START,)
    read_preflight.check(events, EVENT_EXPECTATIONS, label="author tests")  # raises, or ok
    n = read_preflight.nonzero("usable tests", found, population)          # a 0 raises

Wave 4's read counted "usable tests: 0 of 120" because it looked in ``payload["task"]`` while
the served event carries a top-level ``task_id``; a missing key became a default, so the
break was a figure, not an error. Here every such break is a ``PreflightError`` (exit
``EXIT_CODE``, 6) that names the action, the key and where the key is served:

* ``Expect`` refuses, at construction, a payload key the emitter never keeps in the payload
  (``LIFTED``: ``task`` is served as ``task_id``).
* ``check`` tests every expectation on ALL the events supplied, not a sample.
* ``nonzero`` raises on a zero over a non-empty population unless it is handed a ``Waiver``
  that names the count, the reason, who signed it and when. There is no author's excuse.
* ``value`` reads a key and raises when it is absent; it takes no default.
* ``source_problems`` is the AST rule for a read script. A dict is an event when
  ``payload`` is looked up on it, its ``action`` is compared with an action string, it is
  handed to ``value``/``has``, it is an element of what ``check`` was handed, or it is
  named ``ev``/``evt``/``event``; a name called ``payload`` is a payload. ``task_id`` or
  ``action`` alone does not make a row an event. The rule follows events and payloads
  through aliases, tuple / ``for`` / comprehension / ``match`` targets, module names, the
  parameters a call site hands them to, and getter helpers (``_payload_get(item,
  "task")``), and flags a payload lookup of a lifted key, any default on an event or
  payload dict (``.get``, ``dict.get``, ``getattr(p, "get")``, a ``try`` that catches
  ``KeyError``, a ``match`` case), a key that is not a constant, an envelope lookup of a
  name that is not served, a payload key the script does not declare in an ``Expect``,
  and an action string compared with an event's ``action`` that no ``Expect`` declares.
* ``protocol_problems``: the script imports this module, declares ``EVENT_EXPECTATIONS``
  and calls both ``check`` and ``nonzero``; the CLI applies it too.

Navigation
----------
What it is:   The preflight every script that reads run events must call (stdlib only).
What it does: ``Expect`` declares one key of one action; ``check`` raises when an envelope
              key, an action, or an expected key is absent from (or empty on) any supplied
              event; ``nonzero`` stops an unwaived zero; ``value`` is the strict read;
              ``source_problems`` is the static rule; ``main`` runs both on a script and an
              events file and exits 6 on a problem.
How:          pure functions over the already-fetched event dicts and ``ast`` over the
              script's source; ``ENVELOPE_KEYS`` and ``LIFTED`` mirror src/crb
              (tests/test_read_preflight.py pins them to the real emitter).
Layer:        deploy — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   src/crb/server/routes/runs.py (``EVENT_KEYS``), src/crb/observability/events.py
              (the lift), docs/API.md (the event table), tests/test_read_preflight.py (the
              positive control and the ratchet that every reader uses this)
Tested by:    tests/test_read_preflight.py
Touch when:   never for a new repository; the served envelope or the emitter's lift changes
              (the test fails until the mirror is updated), or a script reads run events.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Mirrors ``crb.server.routes.runs.EVENT_KEYS``; a test pins the two equal.
ENVELOPE_KEYS: tuple[str, ...] = (
    "event_id",
    "seq",
    "timestamp",
    "trace_id",
    "step_id",
    "parent_step_id",
    "stage",
    "action",
    "status",
    "actor",
    "repo",
    "task_id",
    "input_ref",
    "output_ref",
    "error_code",
    "error_message",
    "duration_ms",
    "cost_usd",
)
#: What ``Emitter.on_event`` never keeps in the payload: callback key -> envelope field (a
#: refused key, such as ``status``, maps to itself). A test pins this to the real emitter.
LIFTED: dict[str, str] = {
    "task": "task_id",
    "sha": "task_id",
    "error": "error_message",
    "task_id": "task_id",
    "step_id": "step_id",
    "parent_step_id": "parent_step_id",
    "stage": "stage",
    "action": "action",
    "status": "status",
    "input_ref": "input_ref",
    "output_ref": "output_ref",
    "error_code": "error_code",
    "duration_ms": "duration_ms",
    "cost_usd": "cost_usd",
}
#: The exit code a read uses when the preflight stops it.
EXIT_CODE = 6


class PreflightError(Exception):
    """The events do not carry what the read expects; no figure may be computed."""


@dataclass(frozen=True)
class Expect:
    """One key the read looks at on one action's events.

    ``where``: ``"envelope"`` (a top-level field of the served event) or ``"payload"``.
    ``nonempty``: the value must not be ``""`` / ``None`` on any event of the action.
    ``optional``: some events of the action may lack the key (at least one must carry it).
    ``may_be_absent``: the action itself may be absent from the events.
    ``explicit_payload``: the row is written with ``append_event(payload=...)`` or
    ``Emitter.emit``, which keep a name as given; tests/test_read_preflight.py checks that
    docs/API.md documents the key as a payload key of that action."""

    action: str
    key: str
    where: str = "payload"
    nonempty: bool = False
    optional: bool = False
    may_be_absent: bool = False
    explicit_payload: bool = False

    def __post_init__(self) -> None:
        if not self.action or not self.key:
            raise ValueError("an expectation names an action and a key")
        if self.where not in {"envelope", "payload"}:
            raise ValueError(f"where must be 'envelope' or 'payload', not {self.where!r}")
        if self.where == "envelope" and self.key not in ENVELOPE_KEYS:
            raise ValueError(f"{self.key!r} is not a served envelope field: {ENVELOPE_KEYS}")
        if self.where == "payload" and self.key in LIFTED and not self.explicit_payload:
            raise ValueError(
                f"{self.action}: {self.key!r} is never kept in payload; the emitter serves "
                f"it at the envelope as {LIFTED[self.key]!r}"
            )


@dataclass(frozen=True)
class Waiver:
    """A signed statement that a zero count is the true answer, given after the data was
    seen. ``count`` is the label the waiver covers; ``signed_at`` is an ISO 8601 date or
    datetime no later than today (UTC)."""

    count: str
    reason: str
    signed_by: str
    signed_at: str

    def __post_init__(self) -> None:
        for name in ("count", "reason", "signed_by", "signed_at"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"a waiver needs a non-empty {name}")
        try:
            when = dt.datetime.fromisoformat(self.signed_at).date()
        except ValueError:
            raise ValueError(f"signed_at is not an ISO 8601 date: {self.signed_at!r}") from None
        if when > dt.datetime.now(dt.UTC).date():
            raise ValueError(f"signed_at is in the future: {self.signed_at!r}")


# -- the runtime check --------------------------------------------------------------------


def _holder(event: Mapping[str, Any], where: str) -> Mapping[str, Any]:
    if where == "envelope":
        return event
    payload = event.get("payload")
    return payload if isinstance(payload, Mapping) else {}


def _hint(mine: list[Mapping[str, Any]], x: Expect) -> str:
    other = "envelope" if x.where == "payload" else "payload"
    tries = [(other, x.key)]
    if x.key in LIFTED:
        tries.append(("envelope", LIFTED[x.key]))
    for where, key in tries:
        if any(key in _holder(e, where) for e in mine):
            return f"the key is served at {where}.{key}"
    seen = sorted({k for e in mine for k in _holder(e, x.where)})
    return f"{x.where} keys seen on this action: {', '.join(seen) or 'none'}"


def _empty(v: Any) -> bool:
    return v is None or v == ""


def check(
    events: Iterable[Any],
    expects: Iterable[Expect],
    *,
    label: str = "read",
    out: Callable[[str], None] = print,
) -> None:
    """Raise ``PreflightError`` unless every expectation holds on every supplied event;
    print one ``ok`` line per expectation otherwise."""
    items = list(events)
    if not items:
        raise PreflightError(f"{label}: no events to read; a read over nothing proves nothing")
    problems: list[str] = []
    evs = [e for e in items if isinstance(e, Mapping)]
    if len(evs) != len(items):
        problems.append(f"{len(items) - len(evs)} of {len(items)} items are not objects")
    absent = Counter(k for e in evs for k in (*ENVELOPE_KEYS, "payload") if k not in e)
    problems += [
        f"envelope key {k!r} is absent from {n} of {len(evs)} events"
        for k, n in sorted(absent.items())
    ]
    bad_payload = sum(1 for e in evs if "payload" in e and not isinstance(e["payload"], Mapping))
    if bad_payload:
        problems.append(f"payload is not an object on {bad_payload} of {len(evs)} events")
    lines: list[str] = []
    for x in expects:
        mine = [e for e in evs if e.get("action") == x.action]
        if not mine:
            if not x.may_be_absent:
                problems.append(f"{x.action}: no event of this action among {len(evs)} events")
            continue
        have = [e for e in mine if x.key in _holder(e, x.where)]
        full = [e for e in have if not _empty(_holder(e, x.where)[x.key])]
        where = f"{x.where}.{x.key}"
        if not have:
            problems.append(f"{x.action}: {where} is on 0 of {len(mine)} events; {_hint(mine, x)}")
        elif len(have) < len(mine) and not x.optional:
            problems.append(f"{x.action}: {where} is on {len(have)} of {len(mine)} events")
        elif x.nonempty and len(full) < len(have):
            problems.append(
                f"{x.action}: {where} is empty on {len(have) - len(full)} of {len(have)}"
            )
        else:
            lines.append(f"{label} preflight ok: {x.action} {where} on {len(have)}/{len(mine)}")
    if problems:
        head = f"{label} preflight FAILED, no figure computed:"
        raise PreflightError(head + "\n  " + "\n  ".join(problems))
    for line in lines:
        out(line)


def nonzero(
    label: str,
    found: int,
    population: int,
    *,
    waiver: Waiver | None = None,
    out: Callable[[str], None] = print,
) -> int:
    """``found`` unchanged. A zero over a non-empty population raises unless ``waiver`` is a
    ``Waiver`` for this count; a waiver handed to a count that is not zero raises too."""
    if not (0 <= found <= population):
        raise PreflightError(f"{label}: {found} of {population} is not a count")
    is_zero = population > 0 and found == 0
    if waiver is not None:
        if not isinstance(waiver, Waiver):
            raise PreflightError(f"{label}: a zero is waived only by a signed Waiver")
        if waiver.count != label:
            raise PreflightError(f"{label}: the waiver covers {waiver.count!r}, not this count")
        if not is_zero:
            raise PreflightError(f"{label}: {found} of {population} is not a zero; drop the waiver")
        out(
            f"{label}: 0 of {population}, waived by {waiver.signed_by} at {waiver.signed_at}: "
            f"{waiver.reason}"
        )
        return found
    if is_zero:
        raise PreflightError(
            f"{label}: 0 of {population}; a zero over a non-empty population needs a signed "
            f"Waiver (a lookup that matched nothing looks exactly like this)"
        )
    return found


def has(event: Mapping[str, Any], x: Expect) -> bool:
    """Whether the event carries the expected key (for an ``optional`` expectation)."""
    return x.key in _holder(event, x.where)


def value(event: Mapping[str, Any], x: Expect) -> Any:
    """The expected key's value; raises when it is absent. There is no default."""
    holder = _holder(event, x.where)
    if x.key not in holder:
        raise PreflightError(f"{x.action}: {x.where}.{x.key} is absent from an event being read")
    return holder[x.key]


# -- the static rule ----------------------------------------------------------------------


@dataclass(frozen=True)
class Lookup:
    """One lookup on an event dict (``where="envelope"``) or a payload (``"payload"``)."""

    line: int
    where: str
    key: str | None  # None: the key is not a constant
    default: bool  # a missing key becomes a value (or a skipped case) instead of an error
    how: str = ".get"  # what makes it a default: .get, dict.get, except KeyError, match case


def _const(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _name(node: ast.AST) -> str:
    return node.id if isinstance(node, ast.Name) else getattr(node, "attr", "")


_GETS = frozenset({"get", "pop", "setdefault"})


def _accesses(node: ast.AST) -> list[tuple[ast.expr, ast.expr | None, bool, str]]:
    """``(holder, key, default, how)`` for each key of a mapping that ``node`` reads:
    ``m[k]``, ``k in m``, ``m.get(k)``, ``dict.get(m, k)``, ``getattr(m, "get")(k)`` and
    ``operator.itemgetter(k)(m)``."""
    if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
        return [(node.value, node.slice, False, "[]")]
    if (
        isinstance(node, ast.Compare)
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.In | ast.NotIn)
    ):
        return [(node.comparators[0], node.left, False, "in")]
    if not isinstance(node, ast.Call):
        return []
    f, args = node.func, node.args
    if isinstance(f, ast.Attribute) and f.attr in _GETS:
        if isinstance(f.value, ast.Name) and f.value.id == "dict":
            if len(args) < 2:
                return []
            default = f.attr == "get" or len(args) > 2 or bool(node.keywords)
            return [(args[0], args[1], default, f"dict.{f.attr}")]
        if not args:
            return []
        return [(f.value, args[0], f.attr == "get" or len(args) > 1 or bool(node.keywords), ".get")]
    if isinstance(f, ast.Call) and args:
        if _name(f.func) == "itemgetter":
            return [(args[0], k, False, "itemgetter") for k in f.args]
        if _name(f.func) == "getattr" and len(f.args) >= 2 and _const(f.args[1]) in _GETS:
            default = _const(f.args[1]) == "get" or len(args) > 1
            return [(f.args[0], args[0], default, "getattr .get")]
    return []


#: Names that are an event, a payload or a list of events wherever they are bound.
NAMED = {"payload": "payload", "ev": "envelope", "evt": "envelope", "event": "envelope"}
NAMED |= {"events": "events", "evs": "events"}
_ELEMENT = {"events": "envelope", "payloads": "payload"}
_COLLECTION = {"envelope": "events", "payload": "payloads"}
_RANK = {"payload": 3, "envelope": 2, "events": 1, "payloads": 1}
#: Handlers that turn a missing key inside ``try`` (or ``suppress``) into a value.
CATCHES = frozenset({"KeyError", "LookupError", "Exception", "BaseException"})


def _best(kinds: Iterable[str | None]) -> str | None:
    known = [k for k in kinds if k]
    return max(known, key=_RANK.__getitem__) if known else None


def _any_of(changes: Iterable[bool]) -> bool:
    """``any`` that runs every binding (``any`` would stop at the first ``True``)."""
    return True in list(changes)


def _set(env: dict[str, str], name: str, kind: str | None) -> bool:
    new = _best((env.get(name), kind))
    if new is None or env.get(name) == new:
        return False
    env[name] = new
    return True


def _kind(node: ast.AST | None, env: Mapping[str, str]) -> str | None:
    """``"payload"`` / ``"envelope"`` / ``"events"`` / ``"payloads"`` when ``node``
    evaluates to a payload, an event, or a collection of either."""
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return env.get(node.id) or NAMED.get(node.id)
    if isinstance(node, ast.BoolOp | ast.IfExp):
        parts = node.values if isinstance(node, ast.BoolOp) else [node.body, node.orelse]
        return _best(_kind(p, env) for p in parts)
    if isinstance(node, ast.NamedExpr | ast.Starred):
        return _kind(node.value, env)
    if isinstance(node, ast.ListComp | ast.SetComp | ast.GeneratorExp):
        local = dict(env)
        for gen in node.generators:
            _bind_iter(gen.target, gen.iter, local)
        return _COLLECTION.get(_kind(node.elt, local) or "")
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.args
        and node.func.id in {"dict", "list", "tuple", "sorted", "reversed"}
    ):
        return _kind(node.args[0], env)
    if isinstance(node, ast.Subscript) and _const(node.slice) is None:
        holder = _kind(node.value, env)
        if holder in _ELEMENT:
            return holder if isinstance(node.slice, ast.Slice) else _ELEMENT[holder]
    for _holder_node, key, _default, how in _accesses(node):
        if how != "in" and _const(key) == "payload":
            return "payload"
        if how != "in" and _const(key) == "events":
            return "events"
    return None


def _bind_value(target: ast.AST, value: ast.AST | None, env: dict[str, str]) -> bool:
    if isinstance(target, ast.Tuple | ast.List) and isinstance(value, ast.Tuple | ast.List):
        if len(target.elts) == len(value.elts):
            return _any_of(
                _bind_value(t, v, env) for t, v in zip(target.elts, value.elts, strict=True)
            )
        return False
    if isinstance(target, ast.Starred):
        target = target.value
    return isinstance(target, ast.Name) and _set(env, target.id, _kind(value, env))


def _bind_iter(target: ast.AST, it: ast.AST, env: dict[str, str]) -> bool:
    """Bind a ``for`` / comprehension target to the element of what it iterates."""
    if isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and isinstance(target, ast.Tuple):
        if it.func.id == "enumerate" and it.args and len(target.elts) == 2:
            return _bind_iter(target.elts[1], it.args[0], env)
        if it.func.id == "zip" and len(it.args) == len(target.elts):
            return _any_of(_bind_iter(t, a, env) for t, a in zip(target.elts, it.args, strict=True))
    if isinstance(target, ast.Name):
        return _set(env, target.id, _ELEMENT.get(_kind(it, env) or ""))
    return False


def _rp_imports(tree: ast.Module) -> tuple[set[str], dict[str, str]]:
    """The names ``read_preflight`` is imported as, and the names imported from it."""
    mods: set[str] = set()
    names: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.asname or a.name for a in n.names if a.name == "read_preflight"}
        elif isinstance(n, ast.ImportFrom) and n.module == "read_preflight":
            names |= {a.asname or a.name: a.name for a in n.names}
    return mods, names


def _rp_call(node: ast.AST, mods: set[str], names: Mapping[str, str]) -> str | None:
    """The ``read_preflight`` function ``node`` calls, if it calls one."""
    if not isinstance(node, ast.Call):
        return None
    f = node.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        return f.attr if f.value.id in mods | {"read_preflight"} else None
    return names.get(f.id) if isinstance(f, ast.Name) else None


def _action_lookup(node: ast.AST, env: Mapping[str, str], *, known: bool) -> ast.expr | None:
    """The holder when ``node`` reads ``["action"]`` (``known``: of a known event)."""
    for holder, key, _default, how in _accesses(node):
        if (
            how != "in"
            and _const(key) == "action"
            and (not known or _kind(holder, env) == "envelope")
        ):
            return holder
    return None


def _strings(node: ast.AST) -> list[str]:
    if _const(node) is not None:
        return [str(_const(node))]
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return [s for e in node.elts for s in _strings(e)]
    return []


def _mark(node: ast.AST, env: dict[str, str], mods: set[str], names: Mapping[str, str]) -> bool:
    """Learn from how a name is used: ``x["payload"]`` or ``x["action"] == "a.b"`` makes
    ``x`` an event; ``read_preflight.check(x, ...)`` makes ``x`` the events; ``value(x, ..)``
    and ``has(x, ..)`` make ``x`` an event. ``task_id`` or ``action`` alone does not: rows
    of /tasks, /runs or the ledger carry those too."""
    changed = False
    for holder, key, _default, _how in _accesses(node):
        if (
            _const(key) == "payload"
            and isinstance(holder, ast.Name)
            and _kind(holder, env) != "payload"
        ):
            changed |= _set(env, holder.id, "envelope")
    if isinstance(node, ast.Compare):
        ops = [node.left, *node.comparators]
        for op in ops:
            act = _action_lookup(op, env, known=False)
            dotted = [s for o in ops if o is not op for s in _strings(o) if "." in s]
            if isinstance(act, ast.Name) and dotted:
                changed |= _set(env, act.id, "envelope")
    fn = _rp_call(node, mods, names)
    if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Name):
        if fn == "check":
            changed |= _set(env, node.args[0].id, "events")
        elif fn in {"value", "has"}:
            changed |= _set(env, node.args[0].id, "envelope")
    if (
        isinstance(node, ast.Match)
        and isinstance(node.subject, ast.Name)
        and any(_has_payload_key(c.pattern) for c in node.cases)
    ):
        changed |= _set(env, node.subject.id, "envelope")
    return changed


def _has_payload_key(p: ast.pattern) -> bool:
    return isinstance(p, ast.MatchMapping) and any(_const(k) == "payload" for k in p.keys)


def _bindings(node: ast.AST, env: dict[str, str]) -> bool:
    if isinstance(node, ast.Assign):
        return _any_of(_bind_value(t, node.value, env) for t in node.targets)
    if isinstance(node, ast.AnnAssign | ast.NamedExpr):
        return _bind_value(node.target, node.value, env)
    if isinstance(node, ast.For | ast.AsyncFor | ast.comprehension):
        return _bind_iter(node.target, node.iter, env)
    if isinstance(node, ast.Match):
        kind = _kind(node.subject, env)
        return _any_of(_bind_pattern(c.pattern, kind, env) for c in node.cases)
    return False


def _bind_pattern(p: ast.pattern, kind: str | None, env: dict[str, str]) -> bool:
    changed = False
    if isinstance(p, ast.MatchMapping):
        for k, sub in zip(p.keys, p.patterns, strict=True):
            inner = "payload" if kind == "envelope" and _const(k) == "payload" else None
            changed |= _bind_pattern(sub, inner, env)
    elif isinstance(p, ast.MatchAs):
        if p.name:
            changed |= _set(env, p.name, kind)
        if p.pattern is not None:
            changed |= _bind_pattern(p.pattern, kind, env)
    elif isinstance(p, ast.MatchOr):
        changed |= _any_of(_bind_pattern(q, kind, env) for q in p.patterns)
    return changed


def _infer(nodes: list[ast.AST], base: Mapping[str, str], rp: tuple[Any, Any]) -> dict[str, str]:
    """Names in a scope bound to an event, a payload or the events, to a fixpoint."""
    env = dict(base)
    while True:
        changed = False
        for n in nodes:
            changed |= _mark(n, env, *rp)
            changed |= _bindings(n, env)
        if not changed:
            return env


_Fn = ast.FunctionDef | ast.AsyncFunctionDef


def _params(fn: ast.AST) -> list[str]:
    if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
        return []
    a = fn.args
    return [p.arg for p in (*a.posonlyargs, *a.args, *a.kwonlyargs)]


def _positional(fn: _Fn, method: bool) -> list[str]:
    names = [p.arg for p in (*fn.args.posonlyargs, *fn.args.args)]
    return names[1:] if method else names


def _callees(
    call: ast.Call, funcs: Mapping[str, list[_Fn]], methods: set[int]
) -> list[tuple[_Fn, bool]]:
    """The functions of this module ``call`` may call: a bare name for a function, and
    ``self.name`` / ``cls.name`` for a method (whose first parameter is then skipped)."""
    f = call.func
    if isinstance(f, ast.Name):
        return [(g, False) for g in funcs.get(f.id, []) if id(g) not in methods]
    if (
        isinstance(f, ast.Attribute)
        and isinstance(f.value, ast.Name)
        and f.value.id in {"self", "cls"}
    ):
        return [(g, True) for g in funcs.get(f.attr, []) if id(g) in methods]
    return []


def _scopes(tree: ast.Module) -> list[tuple[ast.AST, list[ast.AST]]]:
    """The module's own nodes, then each function with every node under it."""
    funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
    inner = {id(m) for f in funcs for m in ast.walk(f)}
    own = [n for n in ast.walk(tree) if id(n) not in inner]
    return [(tree, own), *((f, list(ast.walk(f))) for f in funcs)]


@dataclass
class _Analysis:
    scopes: list[tuple[ast.AST, list[ast.AST]]]
    envs: dict[int, dict[str, str]]
    funcs: dict[str, list[_Fn]]
    methods: set[int]


def _analyse(tree: ast.Module) -> _Analysis:
    """Every scope's names, with the kinds a call site hands a function's parameters
    propagated to a fixpoint (``task_of(item["payload"])`` makes ``task_of``'s parameter a
    payload), and module names visible in every function."""
    rp = _rp_imports(tree)
    scopes = _scopes(tree)
    funcs: dict[str, list[_Fn]] = {}
    for fn, _nodes in scopes[1:]:
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            funcs.setdefault(fn.name, []).append(fn)
    methods = {
        id(f)
        for c in ast.walk(tree)
        if isinstance(c, ast.ClassDef)
        for f in c.body
        if isinstance(f, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    handed: dict[int, dict[str, str]] = {id(fn): {} for fn, _nodes in scopes[1:]}
    while True:
        module = _infer(scopes[0][1], {}, rp)
        envs = {id(tree): module}
        for fn, nodes in scopes[1:]:
            envs[id(fn)] = _infer(nodes, {**module, **handed[id(fn)]}, rp)
        changed = False
        for scope, nodes in scopes:
            env = envs[id(scope)]
            for n in nodes:
                if not isinstance(n, ast.Call):
                    continue
                for g, method in _callees(n, funcs, methods):
                    pos = _positional(g, method)
                    for name, arg in zip(pos, n.args, strict=False):
                        changed |= _set(handed[id(g)], name, _kind(arg, env))
                    for kw in n.keywords:
                        if kw.arg in _params(g):
                            changed |= _set(handed[id(g)], kw.arg, _kind(kw.value, env))
        if not changed:
            return _Analysis(scopes, envs, funcs, methods)


def _caught(tree: ast.Module) -> set[int]:
    """Nodes inside a ``try`` whose handler (or a ``suppress``) catches a missing key."""

    def catches(t: ast.expr | None) -> bool:
        if t is None:
            return True
        elts = t.elts if isinstance(t, ast.Tuple) else [t]
        return any(_name(e) in CATCHES for e in elts)

    out: set[int] = set()
    for n in ast.walk(tree):
        tried = isinstance(n, ast.Try | ast.TryStar) and any(catches(h.type) for h in n.handlers)
        suppressed = isinstance(n, ast.With | ast.AsyncWith) and any(
            isinstance(i.context_expr, ast.Call)
            and _name(i.context_expr.func) == "suppress"
            and any(catches(a) for a in i.context_expr.args)
            for i in n.items
        )
        if tried or suppressed:
            body: list[ast.stmt] = n.body  # type: ignore[attr-defined]
            out |= {id(m) for s in body for m in ast.walk(s)}
    return out


def _pattern_lookups(p: ast.pattern, kind: str | None, out: list[Lookup]) -> None:
    """A mapping pattern on an event or payload: each key is a lookup whose absence
    silently skips the case."""
    if isinstance(p, ast.MatchMapping):
        for k, sub in zip(p.keys, p.patterns, strict=True):
            key = _const(k)
            if kind in {"envelope", "payload"}:
                out.append(Lookup(k.lineno, str(kind), key, True, "a match case"))
            inner = "payload" if kind == "envelope" and key == "payload" else None
            _pattern_lookups(sub, inner, out)
    elif isinstance(p, ast.MatchAs) and p.pattern is not None:
        _pattern_lookups(p.pattern, kind, out)
    elif isinstance(p, ast.MatchOr):
        for q in p.patterns:
            _pattern_lookups(q, kind, out)


def _scan(source: str) -> tuple[list[Lookup], list[tuple[int, str]]]:
    """The lookups on event dicts and payloads, and the action strings compared with an
    event's ``action``, in ``source``."""
    tree = ast.parse(source)
    an = _analyse(tree)
    caught = _caught(tree)
    found: dict[tuple[int, int, str | None], Lookup] = {}
    actions: set[tuple[int, str]] = set()
    getters: dict[int, tuple[int, str, str]] = {}
    for fn, nodes in an.scopes:
        env = an.envs[id(fn)]
        params = _params(fn)
        for n in nodes:
            for holder, keynode, got_default, got_how in _accesses(n):
                where = _kind(holder, env)
                if where not in {"envelope", "payload"}:
                    continue
                default, how = got_default, got_how
                if id(n) in caught and not default:
                    default, how = True, "except KeyError"
                key = _const(keynode)
                line = getattr(n, "lineno", 0)
                at = (line, getattr(n, "col_offset", 0), key)
                if key == "payload" and where == "envelope":
                    if default:
                        found[at] = Lookup(line, where, key, True, how)
                    continue
                if key is None and isinstance(keynode, ast.Name) and keynode.id in params:
                    getters[id(fn)] = (params.index(keynode.id), keynode.id, where)
                    if default:
                        found[at] = Lookup(line, where, None, True, how)
                    continue
                found[at] = Lookup(line, where, key, default, how)
            if isinstance(n, ast.Compare):
                ops = [n.left, *n.comparators]
                for op in ops:
                    if _action_lookup(op, env, known=True) is not None:
                        others = (o for o in ops if o is not op)
                        actions |= {(n.lineno, s) for o in others for s in _strings(o)}
            if isinstance(n, ast.Match):
                out: list[Lookup] = []
                for case in n.cases:
                    _pattern_lookups(case.pattern, _kind(n.subject, env), out)
                found |= {(lk.line, -1 - i, lk.key): lk for i, lk in enumerate(out)}
                if _action_lookup(n.subject, env, known=True) is not None:
                    actions |= {
                        (c.pattern.lineno, s)
                        for c in n.cases
                        for m in ast.walk(c.pattern)
                        if isinstance(m, ast.MatchValue)
                        for s in _strings(m.value)
                    }
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        for g, method in _callees(n, an.funcs, an.methods):
            if id(g) not in getters:
                continue
            index, pname, where = getters[id(g)]
            index -= 1 if method else 0
            arg = n.args[index] if 0 <= index < len(n.args) else None
            arg = next((k.value for k in n.keywords if k.arg == pname), arg)
            found[(n.lineno, n.col_offset, None)] = Lookup(n.lineno, where, _const(arg), False)
    ordered = sorted(found.values(), key=lambda lk: (lk.line, lk.where, lk.key or ""))
    return ordered, sorted(actions)


def lookups(source: str) -> list[Lookup]:
    """Every lookup on an event dict or a payload in ``source``, through aliases, tuple,
    ``for``, comprehension and ``match`` targets, module names, the parameters a call site
    hands an event or payload to, and getter helpers (a function that looks up its own key
    parameter on an event or payload: each call of it with a constant key counts as that
    lookup at the call's line)."""
    return _scan(source)[0]


def compared_actions(source: str) -> list[tuple[int, str]]:
    """``(line, action)`` for each string compared with an event's ``action``."""
    return _scan(source)[1]


def declared(source: str) -> list[Expect]:
    """The ``Expect(...)`` calls written with constant arguments in ``source``."""
    out: list[Expect] = []
    for n in ast.walk(ast.parse(source)):
        if not isinstance(n, ast.Call):
            continue
        if _name(n.func) != "Expect":
            continue
        try:
            args = [ast.literal_eval(a) for a in n.args]
            kw = {k.arg: ast.literal_eval(k.value) for k in n.keywords if k.arg}
            out.append(Expect(*args, **kw))
        except (ValueError, TypeError, SyntaxError):
            continue  # a refused or non-constant declaration declares nothing
    return out


def protocol_problems(source: str) -> list[str]:
    """What a read script must do around the static rule: import this module, declare a
    module-level ``EVENT_EXPECTATIONS``, call ``check`` and call ``nonzero`` (a count whose
    lookup matched nothing is a 0 that prints like a finding)."""
    tree = ast.parse(source)
    mods, names = _rp_imports(tree)
    problems = []
    if not mods and not names:
        problems.append("does not `import read_preflight`")
    if not any(
        isinstance(n, ast.Assign | ast.AnnAssign)
        and any(
            getattr(t, "id", "") == "EVENT_EXPECTATIONS"
            for t in (n.targets if isinstance(n, ast.Assign) else [n.target])
        )
        for n in tree.body
    ):
        problems.append("declares no module-level EVENT_EXPECTATIONS")
    called = {_rp_call(n, mods, names) for n in ast.walk(tree)}
    if "check" not in called:
        problems.append("never calls read_preflight.check(...)")
    if "nonzero" not in called:
        problems.append(
            "never calls read_preflight.nonzero(...); a count whose lookup matched nothing "
            "would print as a 0"
        )
    return problems


def source_problems(source: str) -> list[str]:
    """The static rule for a script that reads run events (see the module docstring)."""
    decl = declared(source)
    payload_ok = {x.key for x in decl if x.where == "payload"}
    problems: list[str] = []
    found, actions = _scan(source)
    for lk in found:
        at = f"line {lk.line}"
        if lk.default:
            problems.append(
                f"{at}: {lk.how} on an event dict ({lk.where}.{lk.key or '?'}) turns a missing "
                f"key into a value; use read_preflight.value"
            )
        if lk.key is None:
            problems.append(f"{at}: a {lk.where} key that is not a constant cannot be checked")
        elif lk.where == "payload" and lk.key in LIFTED and lk.key not in payload_ok:
            problems.append(
                f"{at}: payload lookup of {lk.key!r}; the emitter serves it at the envelope "
                f"as {LIFTED[lk.key]!r}"
            )
        elif lk.where == "payload" and lk.key not in payload_ok:
            problems.append(f"{at}: payload.{lk.key} is read but no Expect declares it")
        elif lk.where == "envelope" and lk.key not in (*ENVELOPE_KEYS, "payload"):
            problems.append(f"{at}: {lk.key!r} is not a served envelope field")
    known = {x.action for x in decl}
    problems += [
        f"line {line}: action {action!r} is compared with an event's action but no Expect "
        f"declares it; a misspelt action matches nothing and counts 0"
        for line, action in actions
        if action not in known
    ]
    return problems


def reads(source: str) -> set[tuple[str, str]]:
    """The constant ``(where, key)`` pairs ``source`` looks up."""
    return {(lk.where, lk.key) for lk in lookups(source) if lk.key and lk.key != "payload"}


def preflight(source: str, events: Sequence[Any], *, label: str = "read") -> list[str]:
    """Every problem of ``source`` read against ``events``: the static rule, the envelope
    check over all events, its declared expectations, and each constant key it reads
    (a payload key the script reads must be on at least one supplied event)."""
    problems = protocol_problems(source) + source_problems(source)
    try:
        check(events, declared(source), label=label, out=lambda _line: None)
    except PreflightError as exc:
        problems += str(exc).splitlines()[1:]
    evs = [e for e in events if isinstance(e, Mapping)]
    for where, key in sorted(reads(source)):
        if not any(key in _holder(e, where) for e in evs):
            hint = f"; served at envelope.{LIFTED[key]}" if key in LIFTED else ""
            problems.append(f"{where}.{key} is read but is on 0 of {len(evs)} events{hint}")
    return [p.strip() for p in problems]


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--script", type=Path, required=True, help="the read script to check")
    ap.add_argument("--events", type=Path, required=True, help="served events (a JSON list)")
    args = ap.parse_args(argv)
    data = json.loads(args.events.read_text(encoding="utf-8"))
    events = data.get("events", []) if isinstance(data, dict) else data
    problems = preflight(args.script.read_text(encoding="utf-8"), events, label=args.script.name)
    if problems:
        print(f"{args.script} preflight FAILED, no figure computed:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return EXIT_CODE
    print(f"{args.script} preflight ok over {len(events)} events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
