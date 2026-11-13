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
  Each function, lambda and comprehension is its own scope: a name it binds hides the
  enclosing one; a call site's events and payloads reach a lambda's parameters (one called
  where it is written or bound by ``name = lambda``) as they do a function's. The rule also
  flags what it cannot read: an event's ``action`` used other than compared with constant
  strings (or ``X.action`` of a declared ``X``); an event dict read other than by ``[]``,
  ``.get``, ``.pop`` or ``.setdefault`` (``.copy()``, ``.items()``, ``{**ev}``,
  ``__getitem__``, ``methodcaller``); an event or payload handed where it cannot follow
  what a function's parameters receive (``map(f, payloads)``, ``payloads.sort(key=f)``,
  ``*args``, a default argument, or a callee it cannot resolve: ``g = task_of``,
  ``functools.partial(f)(b)``, ``mk()(b)``, a method of a class reached other than by
  ``self.name``: ``super().g(b)``, ``type(self).g(self, b)``, ``getattr(self, "g")(b)``);
  ``Expect`` used other
  than in a direct call with constant arguments; and ``value``/``has`` handed an
  expectation that is not one such call or a name bound once to one.
* ``preflight`` applies ``check`` to the declarations and checks every raw payload read
  against the declared actions, or, when the script compares no ``action`` with a constant
  or compares one so that it may take other actions (``!=``, ``not in``, ``not``, ``or``,
  an ``else``, a jump anywhere in the ``if`` body, ``case _``), against every action present
  in the events.
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
    if events is None or isinstance(events, str | bytes | Mapping):
        raise PreflightError(f"{label}: the events are a {type(events).__name__}, not a list")
    try:
        items = list(events)
    except TypeError:
        raise PreflightError(
            f"{label}: the events are a {type(events).__name__}, not a list"
        ) from None
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
#: Getters that turn a missing key into a value with no default argument: ``get(k)`` gives
#: ``None``, ``setdefault(k)`` inserts ``None`` and gives it. ``pop(k)`` raises.
_DEFAULTING = frozenset({"get", "setdefault"})


def _unbound(holder: ast.expr) -> bool:
    """``dict`` or ``type(x)``: the getter is called unbound, the mapping is its first
    argument (``dict.get(m, k)``, ``type(m).get(m, k)``)."""
    if isinstance(holder, ast.Name):
        return holder.id == "dict"
    return isinstance(holder, ast.Call) and _name(holder.func) == "type"


def _accesses(node: ast.AST) -> list[tuple[ast.expr, ast.expr | None, bool, str]]:
    """``(holder, key, default, how)`` for each key of a mapping that ``node`` reads:
    ``m[k]``, ``k in m``, ``m.get(k)``, ``dict.get(m, k)``, ``type(m).get(m, k)``,
    ``getattr(m, "get")(k)``, ``operator.itemgetter(k)(m)`` and
    ``operator.methodcaller("get", k)(m)``."""
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
        if _unbound(f.value):
            if len(args) < 2:
                return []
            default = f.attr in _DEFAULTING or len(args) > 2 or bool(node.keywords)
            return [(args[0], args[1], default, f"dict.{f.attr}")]
        if not args:
            return []
        default = f.attr in _DEFAULTING or len(args) > 1 or bool(node.keywords)
        return [(f.value, args[0], default, f".{f.attr}")]
    if isinstance(f, ast.Call) and args:
        if _name(f.func) == "itemgetter":
            return [(args[0], k, False, "itemgetter") for k in f.args]
        if _name(f.func) == "getattr" and len(f.args) >= 2 and _const(f.args[1]) in _GETS:
            attr = _const(f.args[1])
            default = attr in _DEFAULTING or len(args) > 1 or bool(node.keywords)
            return [(f.args[0], args[0], default, f"getattr .{attr}")]
        if _name(f.func) == "methodcaller" and len(f.args) >= 2 and _const(f.args[0]) in _GETS:
            attr = _const(f.args[0])
            default = attr in _DEFAULTING or len(f.args) > 2 or bool(f.keywords)
            return [(args[0], f.args[1], default, f"methodcaller .{attr}")]
    return []


#: Names that are an event, a payload or a list of events wherever they are bound.
NAMED = {"payload": "payload", "ev": "envelope", "evt": "envelope", "event": "envelope"}
NAMED |= {"events": "events", "evs": "events"}
_ELEMENT = {"events": "envelope", "payloads": "payload"}
_COLLECTION = {"envelope": "events", "payload": "payloads"}
_RANK = {"payload": 3, "envelope": 2, "events": 1, "payloads": 1}
#: Handlers that turn a missing key inside ``try`` (or ``suppress``) into a value.
CATCHES = frozenset({"KeyError", "LookupError", "Exception", "BaseException"})
#: Calls whose result holds what their first argument holds (a copy, a view, a wrapper).
_SAME_KIND = frozenset(
    {"dict", "list", "tuple", "sorted", "reversed", "copy", "deepcopy", "OrderedDict"}
    | {"ChainMap", "MappingProxyType", "UserDict"}
)


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
        local = {k: v for k, v in env.items() if k not in _scope_locals(node)}
        for gen in node.generators:
            _bind_iter(gen.target, gen.iter, local)
        return _COLLECTION.get(_kind(node.elt, local) or "")
    if isinstance(node, ast.Call) and node.args and _name(node.func) in _SAME_KIND:
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
#: What a call of this module may reach: a function, or a lambda (called where it is written
#: or through the name it is bound to).
_Callee = ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda


def _params(fn: ast.AST) -> list[str]:
    if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
        return []
    a = fn.args
    return [p.arg for p in (*a.posonlyargs, *a.args, *a.kwonlyargs)]


_NEW_SCOPE = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.Lambda,
    ast.ClassDef,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


_Comp = ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp
#: The nodes the static rule reads as scopes of their own (a class body is not one: its
#: names are its enclosing scope's, as far as an event read goes).
_SCOPE = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


def _arg_names(a: ast.arguments) -> set[str]:
    params = (*a.posonlyargs, *a.args, *a.kwonlyargs, *(p for p in (a.vararg, a.kwarg) if p))
    return {p.arg for p in params}


def _scope_locals(s: ast.AST) -> set[str]:
    """The names scope ``s`` binds itself, which hide an enclosing name of the same name: a
    function's locals, a lambda's parameters, a comprehension's targets."""
    if isinstance(s, ast.FunctionDef | ast.AsyncFunctionDef):
        return _locals(s)
    if isinstance(s, ast.Lambda):
        return _arg_names(s.args)
    if isinstance(s, _Comp):
        return {n.id for g in s.generators for n in ast.walk(g.target) if isinstance(n, ast.Name)}
    return set()


def _locals(fn: _Fn) -> set[str]:
    """The names local to ``fn``, which hide a module name of the same name: every
    parameter (``*args`` and ``**kwargs`` too) and every name the body binds (assignment,
    ``for`` / ``with`` / ``except`` / ``match`` / ``import`` targets, a nested ``def`` or
    ``class``), less the names it declares ``global`` or ``nonlocal``."""
    bound = _arg_names(fn.args)
    shared: set[str] = set()
    todo: list[ast.AST] = list(fn.body)
    while todo:
        n = todo.pop()
        if isinstance(n, ast.Global | ast.Nonlocal):
            shared |= set(n.names)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store | ast.Del):
            bound.add(n.id)
        elif isinstance(n, ast.ExceptHandler | ast.MatchAs | ast.MatchStar) and n.name:
            bound.add(n.name)
        elif isinstance(n, ast.MatchMapping) and n.rest:
            bound.add(n.rest)
        elif isinstance(n, ast.Import | ast.ImportFrom):
            bound |= {(al.asname or al.name).split(".")[0] for al in n.names if al.name != "*"}
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            bound.add(n.name)
        if not isinstance(n, _NEW_SCOPE):
            todo.extend(ast.iter_child_nodes(n))
    return bound - shared


def _positional(fn: _Callee, method: bool) -> list[str]:
    names = [p.arg for p in (*fn.args.posonlyargs, *fn.args.args)]
    return names[1:] if method else names


def _named(fn: _Callee) -> list[str]:
    """The parameters of ``fn`` a keyword argument can reach."""
    return [p.arg for p in (*fn.args.args, *fn.args.kwonlyargs)]


def _callees(
    call: ast.Call, funcs: Mapping[str, list[_Callee]], methods: set[int]
) -> list[tuple[_Callee, bool]]:
    """The functions of this module ``call`` may call: a lambda called where it is written,
    a bare name for a function (or a lambda bound to that name), and ``self.name`` /
    ``cls.name`` for a method (whose first parameter is then skipped)."""
    f = call.func
    if isinstance(f, ast.Lambda):
        return [(f, False)]
    if isinstance(f, ast.Name):
        return [(g, False) for g in funcs.get(f.id, []) if id(g) not in methods]
    if (
        isinstance(f, ast.Attribute)
        and isinstance(f.value, ast.Name)
        and f.value.id in {"self", "cls"}
    ):
        return [(g, True) for g in funcs.get(f.attr, []) if id(g) in methods]
    return []


def _parts(s: ast.AST) -> tuple[list[ast.AST], list[ast.AST], list[ast.AST]]:
    """``(inside, bare, outside)`` of a scope node: the nodes walked in it, its own nodes
    taken without their children (a comprehension's ``for`` clauses), and the nodes its
    enclosing scope evaluates (decorators, defaults, a comprehension's first iterable)."""
    if isinstance(s, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
        outer = [*s.args.defaults, *(d for d in s.args.kw_defaults if d)]
        if isinstance(s, ast.Lambda):
            return [s.body], [], outer
        return list(s.body), [], [*s.decorator_list, *outer]
    if isinstance(s, _Comp):
        gens = s.generators
        elts = [s.key, s.value] if isinstance(s, ast.DictComp) else [s.elt]
        inside = [*elts, *(g.target for g in gens), *(i for g in gens for i in g.ifs)]
        return [*inside, *(g.iter for g in gens[1:])], list(gens), [gens[0].iter]
    return list(ast.iter_child_nodes(s)), [], []


def _scopes(tree: ast.Module) -> list[tuple[ast.AST, list[ast.AST], ast.AST | None]]:
    """``(scope, nodes, enclosing scope)`` for the module, then every function, lambda and
    comprehension (each after the scope that encloses it). A scope's nodes stop at a nested
    scope: a name the nested scope binds is its own, never the enclosing one's."""
    out: list[tuple[ast.AST, list[ast.AST], ast.AST | None]] = []

    def visit(s: ast.AST, parent: ast.AST | None) -> None:
        inside, nodes, _outside = _parts(s)
        nested: list[ast.AST] = []
        todo = list(inside)
        while todo:
            n = todo.pop()
            nodes.append(n)
            if isinstance(n, _SCOPE):
                nested.append(n)
                todo.extend(_parts(n)[2])
            else:
                todo.extend(ast.iter_child_nodes(n))
        out.append((s, nodes, parent))
        for n in reversed(nested):
            visit(n, s)

    visit(tree, None)
    return out


@dataclass
class _Analysis:
    scopes: list[tuple[ast.AST, list[ast.AST], ast.AST | None]]
    envs: dict[int, dict[str, str]]
    funcs: dict[str, list[_Callee]]
    methods: set[int]
    #: Names a call cannot be resolved through: bound other than only by ``def``, by
    #: ``name = lambda`` or by an import (a parameter, ``g = task_of``, ``g: T = lambda``,
    #: ``g, h = ...``, ``(g := ...)``, a class).
    unresolved: set[str]
    #: Names bound to a value that may hold a function of this module (``functools.partial
    #: (task_of)``, ``{"f": lambda b: ...}``), and the functions that may return one.
    fnish: set[str]
    returns_fn: set[int]

    def fnref(self, node: ast.AST) -> bool:
        return _fnref(node, self.funcs, self.methods, self.fnish, self.returns_fn)


def _binding_kinds(tree: ast.Module) -> dict[str, set[str]]:
    """How each name is bound anywhere in the module: ``def``, ``lambda`` (a plain ``name =
    lambda`` assignment), ``import`` or ``other`` (any other binding, parameters included)."""
    plain = {
        id(t)
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Lambda)
        for t in n.targets
        if isinstance(t, ast.Name)
    }
    kinds: dict[str, set[str]] = {}

    def add(name: str, kind: str) -> None:
        kinds.setdefault(name, set()).add(kind)

    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef):
            add(n.name, "def")
        elif isinstance(n, ast.ClassDef):
            add(n.name, "other")
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store | ast.Del):
            add(n.id, "lambda" if id(n) in plain else "other")
        elif isinstance(n, ast.arg):
            add(n.arg, "other")
        elif isinstance(n, ast.Import | ast.ImportFrom):
            for al in n.names:
                if al.name != "*":
                    add((al.asname or al.name).split(".")[0], "import")
        elif isinstance(n, ast.ExceptHandler | ast.MatchAs | ast.MatchStar) and n.name:
            add(n.name, "other")
        elif isinstance(n, ast.MatchMapping) and n.rest:
            add(n.rest, "other")
    return kinds


#: Builtins whose result is never a function, and builtins whose result holds only the
#: elements of their positional arguments (a function handed as ``key=`` is not kept).
_SCALAR_BUILTINS = frozenset({"len", "sum", "any", "all", "str", "repr", "print", "bool", "int"})
_ELEMENT_BUILTINS = frozenset(
    {"sorted", "list", "set", "frozenset", "tuple", "map", "filter", "min", "max", "next"}
    | {"enumerate", "zip", "reversed", "iter"}
)


def _classish(recv: ast.AST) -> bool:
    """Whether ``recv`` is an instance or a class of this module by its form: ``self``,
    ``cls``, ``super()``, ``type(x)``, ``cls()`` or ``x.__class__``."""
    if isinstance(recv, ast.Name):
        return recv.id in {"self", "cls"}
    if isinstance(recv, ast.Call) and isinstance(recv.func, ast.Name):
        return recv.func.id in {"super", "type", "cls"}
    return isinstance(recv, ast.Attribute) and recv.attr == "__class__"


def _attr_fn(attr: str, funcs: Mapping[str, list[_Callee]], fnish: set[str]) -> bool:
    """Whether an attribute of this name, on an instance or a class of this module
    (``_classish``), may be a function of this module: a ``def`` or ``name = lambda`` of
    that name, followed or not (kept in ``fnish`` as ``.g``), a name bound to a value that
    holds one (a class body's ``f = staticmethod(lambda b: ...)``), or an attribute a
    function was assigned to (``self.h = task_of``; kept in ``fnish`` as ``.h``). The
    receiver decides first: ``tasks.add(x)`` beside a ``def add`` is the set's method."""
    return attr in funcs or attr in fnish or f".{attr}" in fnish


def _fnref(
    node: ast.AST,
    funcs: Mapping[str, list[_Callee]],
    methods: set[int],
    fnish: set[str],
    returns_fn: set[int],
) -> bool:
    """Whether ``node`` may evaluate to, or hold, a function of this module: a lambda, a
    function's name taken as a value, a name bound to one, an attribute of an instance or a
    class that may be one (``self.g``, ``cls.g``, ``super().g``, ``self.__class__.g``,
    ``type(self).g``; see ``_attr_fn``), a ``getattr`` of one, or a call that may return
    one."""

    def ref(n: ast.AST) -> bool:
        if isinstance(n, ast.Lambda):
            return True
        if isinstance(n, ast.Name):
            return isinstance(n.ctx, ast.Load) and (n.id in funcs or n.id in fnish)
        if isinstance(n, ast.Attribute) and _classish(n.value):
            return _attr_fn(n.attr, funcs, fnish)
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Lambda):
                return ref(f.body)
            if not isinstance(f, ast.Name | ast.Attribute):
                return ref(f)
            if callees := _callees(n, funcs, methods):
                return any(id(g) in returns_fn for g, _m in callees)
            if isinstance(f, ast.Name) and f.id == "getattr" and "getattr" not in funcs:
                # ``getattr(self, "g")``: a function when the name may be one (a name the
                # rule cannot read may be any); ``getattr(args, "label")`` is data.
                if not n.args or not (_classish(n.args[0]) or ref(n.args[0])):
                    return False
                name = n.args[1] if len(n.args) > 1 else None
                if isinstance(name, ast.Constant) and isinstance(name.value, str):
                    return _attr_fn(name.value, funcs, fnish)
                return True
            if (
                isinstance(f, ast.Attribute)
                and _classish(f.value)
                and _attr_fn(f.attr, funcs, fnish)
            ):
                # ``super().g(x)``, ``type(self).g(self, x)``: what the function of that
                # name may return (one the rule does not follow may return anything).
                named = funcs.get(f.attr, [])
                return not named or any(id(g) in returns_fn for g in named)
            if ref(f.value if isinstance(f, ast.Attribute) else f):
                return True  # a call of something that holds a function (a class, a partial)
            if isinstance(f, ast.Name) and f.id in _SCALAR_BUILTINS and f.id not in funcs:
                return False
            if isinstance(f, ast.Name) and f.id in _ELEMENT_BUILTINS and f.id not in funcs:
                # The result holds the elements of its positional arguments (a ``key=`` is
                # not kept), or for ``map`` what its function returns.
                elems = [*n.args, *(k.value for k in n.keywords if k.arg != "key")]
                if f.id in {"map", "filter"} and n.args:
                    g = elems.pop(0)
                    if f.id == "map" and isinstance(g, ast.Lambda) and ref(g.body):
                        return True
                    if f.id == "map" and isinstance(g, ast.Name):
                        if any(id(c) in returns_fn for c in funcs.get(g.id, [])):
                            return True
                        if g.id not in funcs and ref(g):
                            return True
                return any(ref(a) for a in elems)
            # A callee defined elsewhere that is handed a function may return one
            # (``functools.partial(task_of)``).
            return any(ref(a) for a in (*n.args, *(k.value for k in n.keywords)))
        return any(ref(c) for c in ast.iter_child_nodes(n))

    return ref(node)


def _function_values(
    tree: ast.Module, funcs: Mapping[str, list[_Callee]], methods: set[int]
) -> tuple[set[str], set[int]]:
    """``(fnish, returns_fn)`` to a fixpoint (see ``_Analysis``); a class of this module that
    defines a function holds one, and so does an instance of it."""
    fnish = {
        c.name
        for c in ast.walk(tree)
        if isinstance(c, ast.ClassDef)
        and any(
            isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) for m in ast.walk(c)
        )
    }
    returns_fn: set[int] = set()
    callees = [g for gs in funcs.values() for g in gs]
    callees += [n for n in ast.walk(tree) if isinstance(n, ast.Lambda)]

    def ref(n: ast.AST) -> bool:
        return _fnref(n, funcs, methods, fnish, returns_fn)

    while True:
        before = (len(fnish), len(returns_fn))
        for n in ast.walk(tree):
            pairs: list[tuple[list[ast.AST], ast.AST | None]] = []
            if isinstance(n, ast.Assign):
                pairs.append((list(n.targets), n.value))
            elif isinstance(n, ast.AnnAssign | ast.NamedExpr | ast.AugAssign):
                pairs.append(([n.target], n.value))
            elif isinstance(n, ast.For | ast.AsyncFor | ast.comprehension):
                pairs.append(([n.target], n.iter))
            elif isinstance(n, ast.With | ast.AsyncWith):
                pairs += [([i.optional_vars], i.context_expr) for i in n.items if i.optional_vars]
            for targets, value in pairs:
                if value is not None and ref(value):
                    fnish |= {
                        m.id
                        for t in targets
                        for m in ast.walk(t)
                        if isinstance(m, ast.Name) and m.id not in {"self", "cls"}
                    }
                    # ``self.h = task_of``: the attribute name (``_attr_fn``).
                    fnish |= {
                        f".{m.attr}"
                        for t in targets
                        for m in ast.walk(t)
                        if isinstance(m, ast.Attribute)
                    }
        for g in callees:
            if isinstance(g, ast.Lambda):
                out = [g.body]
            else:
                out = [r.value for r in ast.walk(g) if isinstance(r, ast.Return) and r.value]
            if any(ref(v) for v in out):
                returns_fn.add(id(g))
        if (len(fnish), len(returns_fn)) == before:
            return fnish, returns_fn


def _analyse(tree: ast.Module) -> _Analysis:
    """Every scope's names, to a fixpoint: a scope sees its enclosing scope's names less the
    ones it binds itself (a parameter, a local, a lambda parameter or a comprehension target
    of that name is its own); what a scope learns about a name it does not bind holds in the
    enclosing scope too (a ``payload`` lookup inside a comprehension marks the event it is
    made on); and the kinds a call site hands a function's or a lambda's parameters are
    propagated (``task_of(item["payload"])`` makes ``task_of``'s parameter a payload, as does
    ``(lambda body: ...)(item["payload"])`` the lambda's)."""
    rp = _rp_imports(tree)
    scopes = _scopes(tree)
    own = {id(s): _scope_locals(s) for s, _nodes, _parent in scopes}
    funcs: dict[str, list[_Callee]] = {}
    for fn, _nodes, _parent in scopes:
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            funcs.setdefault(fn.name, []).append(fn)
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Lambda):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    funcs.setdefault(t.id, []).append(n.value)
    # A name bound any other way as well is not followed: a call through it is refused when
    # it hands an event value (see ``_unfollowed``).
    kinds = _binding_kinds(tree)
    unresolved = {k for k, v in kinds.items() if not v <= {"def", "lambda"} and not v <= {"import"}}
    methods = {
        id(f)
        for c in ast.walk(tree)
        if isinstance(c, ast.ClassDef)
        for f in c.body
        if isinstance(f, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    every_def = set(funcs)
    funcs = {k: v for k, v in funcs.items() if kinds.get(k, set()) <= {"def", "lambda"}}
    fnish, returns_fn = _function_values(tree, funcs, methods)
    # A method whose name is also bound another way (``for g in ...``) is still a method:
    # ``super().g(b)`` reaches it, so the attribute name stays a function (``_attr_fn``).
    fnish |= {f".{k}" for k in every_def}
    handed: dict[int, dict[str, str]] = {id(s): {} for s, _nodes, _parent in scopes}
    while True:
        envs: dict[int, dict[str, str]] = {}
        for s, nodes, parent in scopes:
            start = {} if parent is None else dict(envs[id(parent)])
            start = {k: v for k, v in start.items() if k not in own[id(s)]}
            for k, v in handed[id(s)].items():
                _set(start, k, v)
            envs[id(s)] = _infer(nodes, start, rp)
        changed = False
        for s, _nodes, parent in scopes:
            if parent is not None:
                for k, v in envs[id(s)].items():
                    if k not in own[id(s)]:
                        changed |= _set(handed[id(parent)], k, v)
        for scope, nodes, _parent in scopes:
            env = envs[id(scope)]
            for n in nodes:
                if not isinstance(n, ast.Call):
                    continue
                for g, method in _callees(n, funcs, methods):
                    pos = _positional(g, method)
                    for name, arg in zip(pos, n.args, strict=False):
                        changed |= _set(handed[id(g)], name, _kind(arg, env))
                    for kw in n.keywords:
                        if kw.arg in _named(g):
                            changed |= _set(handed[id(g)], kw.arg, _kind(kw.value, env))
        if not changed:
            return _Analysis(scopes, envs, funcs, methods, unresolved, fnish, returns_fn)


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


def _action_literals(node: ast.AST, by_name: Mapping[str, Expect]) -> list[str] | None:
    """The actions ``node`` names when it is a constant string, a tuple / list / set of
    them, or ``X.action`` of a declared ``X``; ``None`` for anything else."""
    if (s := _const(node)) is not None:
        return [s]
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        parts = [_action_literals(e, by_name) for e in node.elts]
        return None if any(p is None for p in parts) else [s for p in parts if p for s in p]
    if (
        isinstance(node, ast.Attribute)
        and node.attr == "action"
        and isinstance(node.value, ast.Name)
        and node.value.id in by_name
    ):
        return [by_name[node.value.id].action]
    return None


def _case_actions(p: ast.pattern, by_name: Mapping[str, Expect]) -> list[str] | None:
    """The actions a ``case`` names, or ``None`` when it binds or tests the action other
    than against constants (``case a:`` hands the action to a name)."""
    if isinstance(p, ast.MatchValue):
        return _action_literals(p.value, by_name)
    if isinstance(p, ast.MatchSingleton):
        return []
    if isinstance(p, ast.MatchOr):
        parts = [_case_actions(q, by_name) for q in p.patterns]
        return None if any(q is None for q in parts) else [s for q in parts if q for s in q]
    if isinstance(p, ast.MatchAs):
        if p.pattern is None:
            return [] if p.name is None else None
        return _case_actions(p.pattern, by_name)
    return None


def _literal_use(n: ast.AST, parent: ast.AST | None, by_name: Mapping[str, Expect]) -> bool:
    """Whether the action lookup ``n`` is only compared (``==``, ``!=``, ``in``, ``not
    in``) with constant actions, or is the subject of a ``match`` whose cases name them."""
    if isinstance(parent, ast.Compare) and all(
        isinstance(op, ast.Eq | ast.NotEq | ast.In | ast.NotIn) for op in parent.ops
    ):
        ops = [parent.left, *parent.comparators]
        return all(_action_literals(o, by_name) is not None for o in ops if o is not n)
    if isinstance(parent, ast.Match) and parent.subject is n:
        return all(_case_actions(c.pattern, by_name) is not None for c in parent.cases)
    return False


#: Getter names that are read as a lookup (``.get(k)`` etc.); any other attribute of an
#: event dict or payload hides a key read from the rule.
_LOOKUP_ATTRS = _GETS


_EVENTISH = frozenset({"envelope", "payload", "events", "payloads"})
_JUMPS = (ast.Continue, ast.Break, ast.Return, ast.Raise)


def _eventish(a: ast.AST, env: Mapping[str, str]) -> str | None:
    """The kind of the first event value in ``a``, if it holds one."""
    return next((k for m in ast.walk(a) if (k := _kind(m, env)) in _EVENTISH), None)


def _resolved(n: ast.Call, an: _Analysis) -> bool:
    """Whether the rule knows what call ``n`` calls: a lambda written in place, a function
    of this module (by ``def`` or ``name = lambda``) or a method of one by ``self.name``, or
    something defined elsewhere (a builtin, an import, a method of a value that holds no
    function of this module). A callee computed by an expression (``mk()(b)``,
    ``FNS["f"](b)``, ``(f if c else g)(b)``, ``(g := ...)(b)``), reached through a name
    bound any other way (``g = task_of``, a parameter), or reached as an attribute of an
    instance or a class that may be a function of this module, other than a method by
    ``self.name`` / ``cls.name`` (``super().g(b)``, ``self.__class__.g(b)``,
    ``type(self).g(self, b)``, ``self.h(b)`` after ``self.h = task_of``), is not."""
    f = n.func
    if isinstance(f, ast.Lambda):
        return True
    if isinstance(f, ast.Name):
        return f.id not in an.unresolved
    if isinstance(f, ast.Attribute):
        if isinstance(f.value, ast.Name) and f.value.id in {"self", "cls"}:
            return bool(_callees(n, an.funcs, an.methods))
        if _classish(f.value) and _attr_fn(f.attr, an.funcs, an.fnish):
            return False
        return not an.fnref(f.value)
    return False


def _unfollowed(n: ast.Call, env: Mapping[str, str], an: _Analysis) -> str | None:
    """Why the rule cannot follow what a function of this module receives at call ``n``: a
    function or lambda handed, as a value, to a call that is also handed an event value or
    is a method of one (``map(f, payloads)``, ``sorted(evs, key=lambda e: ...)``,
    ``payloads.sort(key=f)``), an event value handed to a callee the rule cannot resolve
    (see ``_resolved``), or an event value that lands on no named parameter of the function
    called (``*args``, ``**kwargs``)."""
    args = [*n.args, *(k.value for k in n.keywords)]
    recv = [n.func.value] if isinstance(n.func, ast.Attribute) else []
    handed = next((k for a in args if not an.fnref(a) and (k := _eventish(a, env))), None)
    handed = handed or next((k for r in recv if (k := _eventish(r, env))), None)
    if handed and any(an.fnref(a) for a in args):
        return f"a function is handed to a call with an event value ({handed})"
    kind = next((k for a in args if (k := _eventish(a, env))), None)
    if kind and not _resolved(n, an):
        return f"an event value ({kind}) is handed to a callee the rule cannot resolve"
    for g, method in _callees(n, an.funcs, an.methods):
        pos = _positional(g, method)
        for i, a in enumerate(n.args):
            if (isinstance(a, ast.Starred) or i >= len(pos)) and (kind := _eventish(a, env)):
                return f"an event value ({kind}) lands on no named parameter"
        for kw in n.keywords:
            if kw.arg not in _named(g) and (kind := _eventish(kw.value, env)):
                return f"an event value ({kind}) lands on no named parameter"
    return None


def _wild(p: ast.pattern) -> bool:
    """A ``case`` that takes whatever the other cases did not (``case _:``)."""
    if isinstance(p, ast.MatchAs):
        return p.pattern is None or _wild(p.pattern)
    return isinstance(p, ast.MatchOr) and any(_wild(q) for q in p.patterns)


def _selects(cmp: ast.Compare, parents: Mapping[int, ast.AST]) -> bool:
    """Whether an action comparison only lets through events of the actions it names: an
    ``==`` / ``in`` that is a comprehension's ``if`` or the test of an ``if`` with no
    ``else`` whose body holds no jump at any depth, joined to them by ``and`` alone. Anything
    else (``!=``, ``not in``, ``not``, ``or``, an ``else`` branch, a ``continue``, ``break``,
    ``return`` or ``raise`` anywhere in the body, a value kept for later) may take the
    actions it does not name."""
    if not all(isinstance(op, ast.Eq | ast.In) for op in cmp.ops):
        return False
    child: ast.AST = cmp
    parent = parents.get(id(cmp))
    while isinstance(parent, ast.BoolOp) and isinstance(parent.op, ast.And):
        child, parent = parent, parents.get(id(parent))
    if isinstance(parent, ast.comprehension):
        return any(i is child for i in parent.ifs)
    if isinstance(parent, ast.If) and parent.test is child:
        jumps = any(isinstance(m, _JUMPS) for s in parent.body for m in ast.walk(s))
        return not parent.orelse and not jumps
    return False


def _opaque(n: ast.AST, parent: ast.AST | None, env: Mapping[str, str]) -> tuple[str, str] | None:
    """``(where, how)`` when ``n`` reads an event dict or payload in a way the rule cannot
    check: a method other than ``get``/``pop``/``setdefault`` called on it
    (``p.copy().get``, ``p.__getitem__``, ``p.items()``), a getter taken without being
    called (``(f := p.get)(k)``), ``getattr`` of anything else, or ``{**p}``."""
    if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load):
        where = _kind(n.value, env)
        called = isinstance(parent, ast.Call) and parent.func is n
        if where in {"envelope", "payload"} and not (called and n.attr in _LOOKUP_ATTRS):
            return str(where), f".{n.attr}" + ("(...)" if called else " taken uncalled")
    if isinstance(n, ast.Call) and _name(n.func) == "getattr" and n.args:
        where = _kind(n.args[0], env)
        attr = _const(n.args[1]) if len(n.args) > 1 else None
        called = isinstance(parent, ast.Call) and parent.func is n
        if where in {"envelope", "payload"} and not (called and attr in _LOOKUP_ATTRS):
            return str(where), f"getattr {attr or '?'}"
    if isinstance(n, ast.Dict):
        for k, v in zip(n.keys, n.values, strict=True):
            if k is None and (where := _kind(v, env)) in {"envelope", "payload"}:
                return str(where), "{**...}"
    return None


def _scan(source: str) -> tuple[list[Lookup], list[tuple[int, str]]]:
    """The lookups on event dicts and payloads, and the action strings compared with an
    event's ``action``, in ``source``."""
    found, actions, _problems, _excluding = _scan_all(source)
    return found, actions


def _scan_all(source: str) -> tuple[list[Lookup], list[tuple[int, str]], list[str], list[int]]:
    """``_scan`` plus the reads the rule cannot check (an event dict or payload used other
    than by a lookup it reads, an event's ``action`` used other than compared with
    constants (``.startswith``, ``in WANT``, ``== act``), ``value`` / ``has`` handed an
    expectation that is not a name bound to a readable ``Expect`` call, and an event value
    handed where the rule cannot follow what a function's parameters receive), and the lines
    of each action comparison that may take actions it does not name (see ``_selects``)."""
    tree = ast.parse(source)
    an = _analyse(tree)
    caught = _caught(tree)
    d = _decls(tree)
    mods, names = _rp_imports(tree)
    parents = {id(c): p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    found: dict[tuple[int, int, str | None], Lookup] = {}
    actions: set[tuple[int, str]] = set()
    problems: dict[tuple[int, int], str] = {}
    excluding: set[int] = set()
    getters: dict[int, tuple[int, str, str]] = {}
    for fn, nodes, _parent in an.scopes:
        env = an.envs[id(fn)]
        params = _params(fn)
        for n in nodes:
            parent = parents.get(id(n))
            pos = (getattr(n, "lineno", 0), getattr(n, "col_offset", 0))
            if (opaque := _opaque(n, parent, env)) is not None:
                problems[pos] = (
                    f"line {pos[0]}: {opaque[1]} on an event dict ({opaque[0]}) is not a lookup "
                    f"the rule can check; read a key with [] or read_preflight.value"
                )
            if _action_lookup(n, env, known=True) is not None and not _literal_use(
                n, parent, d.by_name
            ):
                problems[pos] = (
                    f"line {pos[0]}: an event's action is used other than compared with "
                    f"constant action strings (or X.action of a declared X); the rule cannot "
                    f"tell which actions the read takes, so write the actions out"
                )
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
                defaults = [*n.args.defaults, *(k for k in n.args.kw_defaults if k)]
                if kind := next((k for a in defaults if (k := _eventish(a, env))), None):
                    problems[pos] = (
                        f"line {pos[0]}: a default argument hands an event value ({kind}) to "
                        f"a function; the rule cannot follow what the function's parameters "
                        f"receive, so call it directly with the value as a named parameter"
                    )
            if isinstance(n, ast.Call) and (why := _unfollowed(n, env, an)) is not None:
                problems[pos] = (
                    f"line {pos[0]}: {why}; the rule cannot follow what the function's "
                    f"parameters receive, so call it directly with the value as a named "
                    f"parameter, or read it in a comprehension"
                )
            fname = _rp_call(n, mods, names)
            if isinstance(n, ast.Call) and fname in {"value", "has"}:
                xs = n.args[1:2] or [k.value for k in n.keywords if k.arg == "x"]
                x = xs[0] if xs else None
                known = (
                    d.made.get(id(x))
                    if x is not None and id(x) in d.made
                    else d.by_name.get(x.id)
                    if isinstance(x, ast.Name)
                    else None
                )
                if known is None:
                    problems[pos] = (
                        f"line {pos[0]}: read_preflight.{fname}(...) is handed an expectation "
                        f"the rule cannot see declared; pass a name bound once to "
                        f"read_preflight.Expect(<constants>)"
                    )
                elif known.where == "envelope" and known.key == "action":
                    problems[pos] = (
                        f"line {pos[0]}: read_preflight.{fname}(...) reads the action; compare "
                        f'ev["action"] with constant action strings instead'
                    )
            if isinstance(n, ast.Compare):
                ops = [n.left, *n.comparators]
                for op in ops:
                    if _action_lookup(op, env, known=True) is not None:
                        others = [_action_literals(o, d.by_name) for o in ops if o is not op]
                        actions |= {(n.lineno, s) for o in others for s in o or []}
                        if not _selects(n, parents):
                            excluding.add(n.lineno)
            if isinstance(n, ast.Match):
                out: list[Lookup] = []
                for case in n.cases:
                    _pattern_lookups(case.pattern, _kind(n.subject, env), out)
                found |= {(lk.line, -1 - i, lk.key): lk for i, lk in enumerate(out)}
                if _action_lookup(n.subject, env, known=True) is not None:
                    actions |= {
                        (c.pattern.lineno, s)
                        for c in n.cases
                        for s in _case_actions(c.pattern, d.by_name) or []
                    }
                    excluding |= {c.pattern.lineno for c in n.cases if _wild(c.pattern)}
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
    return ordered, sorted(actions), [problems[k] for k in sorted(problems)], sorted(excluding)


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


def _literal(node: ast.expr) -> bool:
    try:
        ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False
    return True


def _not_constant(call: ast.Call) -> str | None:
    """The first argument of ``call`` that is not a constant, as written."""
    for a in call.args:
        if not _literal(a):
            return ast.unparse(a)
    for k in call.keywords:
        if k.arg is None or not _literal(k.value):
            return ast.unparse(k.value) if k.arg else f"**{ast.unparse(k.value)}"
    return None


@dataclass
class _Decls:
    expects: list[Expect]
    problems: list[str]
    #: A name every binding of which is one readable ``Expect(...)`` call -> that Expect.
    by_name: dict[str, Expect]
    #: ``id`` of each readable ``Expect(...)`` call node -> its Expect.
    made: dict[int, Expect]


def _bound_names(tree: ast.Module) -> Iterable[tuple[str, ast.AST]]:
    """``(name, node)`` for every way a module binds a name."""
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store | ast.Del):
            yield n.id, n
        elif isinstance(n, ast.arg):
            yield n.arg, n
        elif isinstance(n, ast.alias):
            yield (n.asname or n.name).split(".")[0], n
        elif isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) or (
            isinstance(n, ast.ExceptHandler | ast.MatchAs | ast.MatchStar) and n.name
        ):
            yield n.name, n
        elif isinstance(n, ast.MatchMapping) and n.rest:
            yield n.rest, n


def _decls(tree: ast.Module) -> _Decls:
    """Each call of this module's ``Expect``, however it is imported
    (``read_preflight.Expect``, ``rp.Expect``, ``Expect``, ``E`` from ``from read_preflight
    import Expect as E``), and the names bound to one. A call whose arguments are not all
    constants, a call ``Expect`` refuses, and ``Expect`` reached other than by a direct call
    (``E = read_preflight.Expect``, ``getattr(read_preflight, "Expect")``, ``partial``) are
    problems, never silent omissions: the read would otherwise pass the preflight on an
    expectation nobody checked."""
    mods, names = _rp_imports(tree)
    rp_mods = mods | {"read_preflight"}
    out = _Decls([], [], {}, {})
    parents = {id(c): p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and _rp_call(n, mods, names) == "Expect":
            at = f"line {n.lineno}: read_preflight.Expect(...)"
            if (bad := _not_constant(n)) is not None:
                out.problems.append(
                    f"{at} cannot be read without running the script ({bad} is not a "
                    f"constant); write its arguments as constants"
                )
                continue
            try:
                x = Expect(
                    *[ast.literal_eval(a) for a in n.args],
                    **{str(k.arg): ast.literal_eval(k.value) for k in n.keywords},
                )
            except (ValueError, TypeError) as exc:
                out.problems.append(f"{at} is refused: {exc}")
                continue
            out.expects.append(x)
            out.made[id(n)] = x
        ref = (
            isinstance(n, ast.Attribute)
            and n.attr == "Expect"
            and isinstance(n.value, ast.Name)
            and n.value.id in rp_mods
        ) or (
            isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and names.get(n.id) == "Expect"
        )
        parent = parents.get(id(n))
        if ref and not (isinstance(parent, ast.Call) and parent.func is n):
            out.problems.append(
                f"line {n.lineno}: read_preflight.Expect is used other than in a direct call; "
                f"the rule reads a declaration only as read_preflight.Expect(<constants>)"
            )
        if (
            isinstance(n, ast.Call)
            and _name(n.func) == "getattr"
            and n.args
            and isinstance(n.args[0], ast.Name)
            and n.args[0].id in rp_mods
        ):
            out.problems.append(
                f"line {n.lineno}: getattr on read_preflight hides what is called; call it by name"
            )
    good: dict[str, list[Expect]] = {}
    good_nodes: set[int] = set()
    for n in ast.walk(tree):
        if (
            isinstance(n, ast.Assign)
            and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name)
            and id(n.value) in out.made
        ):
            good.setdefault(n.targets[0].id, []).append(out.made[id(n.value)])
            good_nodes.add(id(n.targets[0]))
    other = {name for name, node in _bound_names(tree) if id(node) not in good_nodes}
    out.by_name = {k: v[0] for k, v in good.items() if k not in other and len(set(v)) == 1}
    return out


def _declarations(source: str) -> tuple[list[Expect], list[str]]:
    """``(expectations, problems)`` of ``source``'s ``Expect`` calls (see ``_decls``)."""
    d = _decls(ast.parse(source))
    return d.expects, d.problems


def declared(source: str) -> list[Expect]:
    """The ``Expect(...)`` calls of ``source`` that can be read and are not refused (a call
    that cannot is a problem of ``source_problems``)."""
    return _declarations(source)[0]


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


def _actions_for(decl: Iterable[Expect], key: str) -> set[str]:
    """The actions whose payload ``key`` is declared."""
    return {x.action for x in decl if x.where == "payload" and x.key == key}


def _undeclared_for(decl: Sequence[Expect], key: str) -> list[str]:
    """The actions the script reads (those it declares) that do not declare payload ``key``:
    a raw lookup of ``key`` may meet an event of any of them, so one action's declaration is
    no evidence for another's."""
    return sorted({x.action for x in decl} - _actions_for(decl, key))


def source_problems(source: str) -> list[str]:
    """The static rule for a script that reads run events (see the module docstring)."""
    decl, problems = _declarations(source)
    found, actions, unreadable, _excluding = _scan_all(source)
    problems += unreadable
    for lk in found:
        at = f"line {lk.line}"
        if lk.default:
            problems.append(
                f"{at}: {lk.how} on an event dict ({lk.where}.{lk.key or '?'}) turns a missing "
                f"key into a value; use read_preflight.value"
            )
        if lk.key is None:
            problems.append(f"{at}: a {lk.where} key that is not a constant cannot be checked")
        elif lk.where == "payload" and not _actions_for(decl, lk.key):
            problems.append(
                f"{at}: payload lookup of {lk.key!r}; the emitter serves it at the envelope "
                f"as {LIFTED[lk.key]!r}"
                if lk.key in LIFTED
                else f"{at}: payload.{lk.key} is read but no Expect declares it"
            )
        elif lk.where == "payload" and (lacking := _undeclared_for(decl, lk.key)):
            problems.append(
                f"{at}: payload.{lk.key} is read but no Expect declares it for "
                f"{', '.join(lacking)}; a raw lookup is not tied to one action, so declare the "
                f"key for every action the script reads or read it with read_preflight.value"
            )
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
    check over all events (no events at all is a problem), its declared expectations, and
    each constant key it reads (a payload key the script reads must be on at least one
    supplied event of every action it declares that has events: another action's event is
    no evidence)."""
    problems = protocol_problems(source) + source_problems(source)
    if not isinstance(events, list | tuple):
        problems.append(f"{label}: the events are a {type(events).__name__}, not a list")
        return [p.strip() for p in problems]
    decl = declared(source)
    try:
        check(events, decl, label=label, out=lambda _line: None)
    except PreflightError as exc:
        lines = str(exc).splitlines()
        problems += lines[1:] if len(lines) > 1 else lines
    evs = [e for e in events if isinstance(e, Mapping)]
    # A read that compares no event's action with a constant may take any action's events;
    # so may one with a comparison that excludes actions (``!=``, ``not in``, ``else``).
    _found, compared, _unreadable, excluding = _scan_all(source)
    filtered = bool(compared) and not excluding
    acts = (
        sorted({x.action for x in decl})
        if filtered
        else sorted({a for e in evs if isinstance(a := e.get("action"), str)})
    )
    why = (
        ""
        if filtered
        else f"; an exclusion filter (line {excluding[0]}) may take any action's events"
        if excluding
        else "; the read names no action, so every action's events count"
    )
    for where, key in sorted(reads(source)):
        hint = f"; served at envelope.{LIFTED[key]}" if key in LIFTED else ""
        if not any(key in _holder(e, where) for e in evs):
            problems.append(f"{where}.{key} is read but is on 0 of {len(evs)} events{hint}")
            continue
        for action in acts if where == "payload" else ():
            mine = [e for e in evs if e.get("action") == action]
            if mine and not any(key in _holder(e, where) for e in mine):
                problems.append(
                    f"{where}.{key} is read but is on 0 of {len(mine)} {action} events{hint}{why}"
                )
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
