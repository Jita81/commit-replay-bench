"""Where an event's keys are served (P-817): a key the emitter lifts to the envelope is never
documented as a payload key.

The wave-4 primary read looked for the task in ``payload["task"]`` because docs/API.md said it
was there, and its fixtures copied the documented shape. The served event carries it in the
top-level ``task_id``: ``Emitter.on_event`` pops ``task`` (or ``sha``) and ``error`` from the
payload and passes envelope-named keys to the envelope. This suite emits real events through
the real emitter and the worker's callback, reads them back through the real
``GET /runs/{run_id}/events/log`` route, and checks docs/API.md's event table against the
emitter itself, so the doc and a fixture built from it cannot describe a shape the product
does not serve.

Navigation
----------
What it is:   The served-shape contract for StepEvents and the doc check that keeps
              docs/API.md#event-vocabulary in step with it.
What it does: Emits ``builder.author_test.*`` through ``builders.base.emit`` →
              ``RunContext.on_event`` → ``Emitter`` → ``DbEventSink`` and reads them back
              through the events-log route: the task is the top-level ``task_id``, the error
              is ``error_message``, neither is in ``payload``. Parses the event table and fails
              when a payload cell names, as a payload key, a key the real emitter lifts; every
              "… on the envelope" key must be a served envelope field; pins that
              ``oracle.mutation.excluded`` passes ``outcome``, not the refused ``status``. Scans
              every emit call under src/crb and fails on a keyword its emitter refuses.
How:          A seeded app (``fixtures.server_seed.make_env``) and its TestClient, no network;
              the lifted and refused sets are probed on live emitters over a ``MemorySink``,
              the names read with ``inspect``; the emit calls are read with ``ast``; the table
              is split on unescaped pipes, parentheses and the prose after " — " dropped.
Layer:        tests — docs/ARCHITECTURE.md#72-observability
ADRs:         none
Works with:   src/crb/observability/events.py (``Emitter.on_event``, the lift),
              src/crb/server/routes/runs.py (``EVENT_KEYS``, the served shape),
              src/crb/server/worker.py (``RunContext.on_event``, the stage routing),
              src/crb/builders/adapter.py (``author_s1``, the author events),
              src/crb/factory/loop.py (``FactoryLoop._emit``, a refused set it probes),
              docs/API.md (the table this checks),
              tests/test_event_vocabulary.py (the action-name ratchet beside this one)
Tested by:    tests/test_event_served_shape.py
Touch when:   never for a new repository; the emitter's lift or the served envelope changes,
              an event is written outside ``Emitter.on_event`` with an envelope-named payload
              key (add an exemption with its reason), or a new emit call shape is added.
"""

from __future__ import annotations

import ast
import inspect
import os
import re
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from crb.builders.base import emit
from crb.factory.loop import FactoryLoop
from crb.observability.events import Emitter, MemorySink
from crb.server.routes.runs import EVENT_KEYS
from crb.server.worker import RunContext
from crb.store.events import DbEventSink
from fixtures.server_seed import Env, make_env

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "API.md"
ADAPTER = ROOT / "src" / "crb" / "builders" / "adapter.py"
MUTATION = ROOT / "src" / "crb" / "core" / "oracle" / "mutation.py"

ENVELOPE = " on the envelope"

#: Rows written with an explicit ``payload`` dict, never through ``Emitter.on_event``: these
#: keys really are served in ``payload``. Key: a code span in the row's action cell.
EXEMPT: dict[str, tuple[set[str], str]] = {
    "`builder.login.verified`": (
        {"status", "cost_usd"},
        "append_event(payload=…) with the LoginCheck's own dict",
    ),
    "`run.reclaimed`": ({"status"}, "store/jobs.py append_event(payload=…)"),
    "`legacy.tasks`": ({"task"}, "the CLI's own callback; never the Emitter, never stored"),
}

#: Code spans in a payload cell that are values, not keys (``by`` ∈ ``admin`` | ``self``).
VALUES = {"self"}


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-placeholder-not-a-key")
    monkeypatch.setenv("CEREBRAS_API_KEY", "csk-test-placeholder-not-a-key")


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    with make_env(tmp_path) as e:
        yield e


# ---------------------------------------------------------------------------
# The served shape, end to end
# ---------------------------------------------------------------------------


def _served(env: Env, action: str) -> list[dict[str, Any]]:
    run_id = env.info.run_ids["succeeded"]
    r = env.get(f"/runs/{run_id}/events/log?limit=500")
    assert r.status_code == 200, r.text
    return [e for e in r.json()["items"] if e["action"] == action]


def _worker_callback(env: Env) -> Any:
    """The callback a run's builder receives: ``RunContext.on_event`` over a real emitter."""
    emitter = Emitter(DbEventSink(env.factory), trace_id=env.info.run_ids["succeeded"])
    ctx = SimpleNamespace(emitter=emitter)
    return lambda action, payload: RunContext.on_event(ctx, action, payload)  # type: ignore[arg-type]


def test_author_test_start_serves_the_task_on_the_envelope(env: Env) -> None:
    emit(_worker_callback(env), "builder.author_test.start", task="T-author-1", commit="c0ffee")
    [ev] = _served(env, "builder.author_test.start")
    assert ev["task_id"] == "T-author-1"
    assert ev["stage"] == "build" and ev["status"] == "ok"
    assert ev["payload"] == {"commit": "c0ffee"}
    assert "task" not in ev["payload"]


def test_author_test_failed_serves_task_and_error_on_the_envelope(env: Env) -> None:
    emit(_worker_callback(env), "builder.author_test.failed", task="T-author-2", error="no red")
    [ev] = _served(env, "builder.author_test.failed")
    assert ev["task_id"] == "T-author-2" and ev["error_message"] == "no red"
    assert ev["payload"] == {}
    # ``.failed`` is not an ``.error`` suffix: the emitter serves it as ``ok``
    assert ev["status"] == "ok"


def test_author_test_removed_carries_no_task(env: Env) -> None:
    emit(_worker_callback(env), "builder.author_test.removed", path="tests/test_x.py")
    [ev] = _served(env, "builder.author_test.removed")
    assert ev["task_id"] == "" and ev["payload"] == {"path": "tests/test_x.py"}


def _emit_keywords(path: Path, action_suffix: str) -> set[str]:
    """The keyword names of every emit call in ``path`` whose action ends ``action_suffix``."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", getattr(node.func, "attr", ""))
        spans = [n.value for a in node.args for n in ast.walk(a) if isinstance(n, ast.Constant)]
        if name in {"emit", "_emit"} and any(
            isinstance(s, str) and s.endswith(action_suffix) for s in spans
        ):
            found |= {k.arg for k in node.keywords if k.arg}
    return found


def test_the_adapter_still_emits_the_author_keys_this_suite_serves() -> None:
    assert _emit_keywords(ADAPTER, "author_test.start") == {"task", "commit"}
    assert _emit_keywords(ADAPTER, "author_test.failed") == {"task", "error"}
    assert _emit_keywords(ADAPTER, "author_test.removed") == {"path"}


# ---------------------------------------------------------------------------
# The doc against the emitter
# ---------------------------------------------------------------------------


def _probe(key: str) -> str:
    """``kept`` / ``lifted`` / ``refused``: what ``Emitter.on_event`` does with ``key``."""
    sink = MemorySink()
    try:
        Emitter(sink, trace_id="t").on_event("system")("probe.x", {key: "v"})
    except TypeError:
        return "refused"
    [ev] = sink._events
    return "kept" if key in ev.payload else "lifted"


def _rows() -> list[list[str]]:
    text = DOC.read_text(encoding="utf-8")
    section = text.split("## Event vocabulary", 1)[1].split("\n## ", 1)[0]
    rows, inside = [], False
    for line in section.splitlines():
        if line.startswith("| stage | action |"):
            inside = True
            continue
        if not inside or line.startswith("|---"):
            continue
        if not line.startswith("|"):
            break
        rows.append([c.strip() for c in re.split(r"(?<!\\)\|", line)[1:-1]])
    return rows


def _keys(cell: str) -> list[tuple[str, bool]]:
    """``(key, on_envelope)`` for each code span in a payload cell, prose and asides dropped."""
    head = cell.split(" — ", 1)[0]
    while True:
        bare = re.sub(r"\([^()]*\)", "", head)
        if bare == head:
            break
        head = bare
    out = []
    for m in re.finditer(r"`([^`]+)`(" + ENVELOPE + ")?", head):
        if re.fullmatch(r"[a-z_][a-z0-9_]*", m.group(1)) and m.group(1) not in VALUES:
            out.append((m.group(1), bool(m.group(2))))
    return out


def test_the_table_parses() -> None:
    rows = _rows()
    assert len(rows) > 50 and all(len(r) == 6 for r in rows)


def test_no_documented_payload_key_is_one_the_emitter_lifts() -> None:
    wrong, used = [], set()
    for stage, action, _status, payload, by, _consumed in _rows():
        exempt: set[str] = set()
        for span, (keys, _why) in EXEMPT.items():
            if span in action:
                exempt |= keys
                used.add(span)
        for key, on_env in _keys(payload):
            if on_env or key in exempt:
                continue
            if _probe(key) != "kept":
                wrong.append(f"{stage} {action[:60]}: `{key}` — {_fix(by, key)}")
    assert not wrong, "a documented payload key the emitter lifts:\n" + "\n".join(wrong)
    assert used == set(EXEMPT), f"stale exemptions: {set(EXEMPT) - used}"


def _fix(by: str, key: str) -> str:
    """What the author of a failing row should do, read from its "emitted by" cell."""
    if "append_event" in by or "append_system_event" in by:
        return (
            f"this row is written with an explicit payload (append_event / append_system_event), "
            f"which keeps `{key}` as given: add the row to EXEMPT with the reason"
        )
    return (
        f'Emitter.on_event serves `{key}` on the envelope: write it as "`<field>` on the '
        f'envelope"; if the row is written with append_event / append_system_event instead, '
        f"add it to EXEMPT with the reason"
    )


def test_every_envelope_key_is_a_served_envelope_field() -> None:
    marked = {k for r in _rows() for k, on_env in _keys(r[3]) if on_env}
    assert marked and marked <= set(EVENT_KEYS), marked - set(EVENT_KEYS)


def test_the_exempt_keys_really_are_lifted_by_the_emitter() -> None:
    # an exemption is only needed, and only honest, for a key the emitter would not keep
    for keys, _why in EXEMPT.values():
        assert all(_probe(k) != "kept" for k in keys), keys


def test_the_excluded_mutant_row_matches_the_emit() -> None:
    # oracle.mutation.excluded passed ``status``, which the emitter's own argument refuses, so
    # the row raised before it was written (P-817); it now passes ``outcome``, and the doc says so
    assert _probe("status") == "refused"
    keys = _emit_keywords(MUTATION, "oracle.mutation.excluded")
    assert "outcome" in keys and "status" not in keys
    [row] = [r for r in _rows() if "`oracle.mutation.excluded`" in r[1]]
    assert "`outcome`" in row[3] and "raises" not in row[3]


# ---------------------------------------------------------------------------
# No emit call passes a keyword its emitter refuses
# ---------------------------------------------------------------------------
#
# A keyword that is also a named argument of the emitter (``status``, ``task_id``, ``stage``)
# raises ``TypeError: got multiple values`` when the call runs — on a rare branch, that is a
# crash no other test sees (the ``excluded`` row, P-817). The refused names are found by
# calling the real emitters with each argument name ``inspect`` reads from their signatures;
# none is written here by hand. The call shapes this scan covers:
#
# * ``callback`` — a module-level helper ``f(on_event, action, **payload)`` that hands the
#   payload to ``on_event`` (``builders.base.emit`` and every core / factory ``_emit``),
#   called by name where it is defined or imported;
# * ``callback`` — ``on_event(action, {…})`` / ``x.on_event(action, {…})`` with a dict literal;
# * ``emit`` — ``x.emit(stage, action, …)`` (``Emitter.emit``, ``RunContext.emit``);
# * ``error`` — ``<…emitter>.error(stage, action, exc, …)`` (``Emitter.error``);
# * ``method`` — ``self._emit(…)`` inside a class whose own ``_emit`` it is (``FactoryLoop``).
#
# Not covered: a ``**mapping`` splat (its keys are not in the source) and ``Emitter.timed``.

SRC = ROOT / "src" / "crb"


def _refused_by(call: Any, names: set[str]) -> frozenset[str]:
    """The names in ``names`` that ``call(**{name: …})`` refuses as given twice."""
    out = set()
    for name in names:
        try:
            call(**{name: "v"})
        except TypeError as exc:
            if "multiple values" in str(exc):
                out.add(name)
        except Exception:  # a bad value is not a collision
            continue
    return frozenset(out)


def _named(*fns: Any) -> set[str]:
    """Every named (non-``**``) parameter of ``fns``, read with ``inspect``."""
    return {
        p.name
        for fn in fns
        for p in inspect.signature(fn).parameters.values()
        if p.kind is not inspect.Parameter.VAR_KEYWORD and p.name != "self"
    }


def _refused() -> dict[str, frozenset[str]]:
    """Per call shape, the keywords its emitter refuses — probed on the real code."""
    names = _named(
        Emitter.emit, Emitter.error, Emitter.on_event, RunContext.emit, FactoryLoop._emit
    )
    names |= {"task", "sha", "action", "payload", "on_event"}

    def em() -> Emitter:
        return Emitter(MemorySink(), trace_id="t")

    def ctx() -> Any:
        return SimpleNamespace(emitter=em())

    return {
        "callback": _refused_by(lambda **kw: em().on_event("system")("probe.x", kw), names),
        "emit": _refused_by(lambda **kw: em().emit("system", "probe.x", **kw), names)
        | _refused_by(lambda **kw: RunContext.emit(ctx(), "system", "probe.x", **kw), names),
        "error": _refused_by(
            lambda **kw: em().error("system", "probe.x", ValueError(), **kw), names
        ),
        "method": _refused_by(lambda **kw: FactoryLoop._emit(ctx(), "probe.x", "i", **kw), names),
    }


def _is_callback_helper(fn: ast.FunctionDef) -> bool:
    """``def f(on_event, action, **payload)`` — a helper that forwards ``payload``."""
    a = fn.args
    return [x.arg for x in a.args][:2] == ["on_event", "action"] and a.kwarg is not None


def _helpers() -> set[tuple[str, str]]:
    """``(module, name)`` of every module-level callback helper under src/crb."""
    out = set()
    for path in SRC.rglob("*.py"):
        mod = ".".join(path.relative_to(SRC.parent).with_suffix("").parts)
        mod = mod.removesuffix(".__init__")
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.FunctionDef) and _is_callback_helper(node):
                out.add((mod, node.name))
    return out


def _shape(node: ast.Call, local: set[str], methods: set[str]) -> str:
    """Which covered shape ``node`` is, or ``""``."""
    f = node.func
    if isinstance(f, ast.Name) and f.id in local and len(node.args) >= 2:
        return "callback"
    name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
    if name == "on_event" and len(node.args) == 2 and isinstance(node.args[1], ast.Dict):
        return "callback"
    if not isinstance(f, ast.Attribute):
        return ""
    if f.attr == "emit" and len(node.args) >= 2:
        return "emit"
    if f.attr == "error" and ast.unparse(f.value).endswith("emitter"):
        return "error"
    if f.attr in methods and isinstance(f.value, ast.Name) and f.value.id == "self":
        return "method"
    return ""


def _passed(node: ast.Call) -> set[str]:
    """The literal keyword names ``node`` passes (a dict literal's keys for ``on_event``)."""
    keys = {k.arg for k in node.keywords if k.arg}
    if len(node.args) == 2 and isinstance(node.args[1], ast.Dict):
        keys |= {k.value for k in node.args[1].keys if isinstance(k, ast.Constant)}
    return keys


def collisions(
    source: str, where: str, helpers: set[tuple[str, str]], refused: dict[str, frozenset[str]]
) -> list[str]:
    """Each covered emit call in ``source`` that passes a keyword its emitter refuses."""
    tree = ast.parse(source)
    local = {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and _is_callback_helper(n)}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            local |= {a.asname or a.name for a in n.names if (n.module, a.name) in helpers}
    found = []
    for cls in [tree, *[c for c in ast.walk(tree) if isinstance(c, ast.ClassDef)]]:
        methods = (
            {m.name for m in cls.body if isinstance(m, ast.FunctionDef) and m.name == "_emit"}
            if isinstance(cls, ast.ClassDef)
            else set()
        )
        for node in ast.walk(cls):
            if not isinstance(node, ast.Call):
                continue
            shape = _shape(node, local, methods)
            if shape == "method" or (shape and not isinstance(cls, ast.ClassDef)):
                bad = sorted(_passed(node) & refused[shape])
                if bad:
                    found.append(f"{where}:{node.lineno} ({shape}) passes {bad}")
    return found


def test_the_refused_sets_are_read_from_the_real_emitters() -> None:
    refused = _refused()
    assert "status" in refused["callback"] and "task_id" in refused["callback"]
    assert {"stage", "action"} <= refused["emit"] and "status" not in refused["emit"]
    assert "task_id" in refused["method"] and "status" not in refused["method"]
    assert "error" in refused["error"]


def test_no_emit_call_passes_a_keyword_its_emitter_refuses() -> None:
    helpers, refused = _helpers(), _refused()
    assert ("crb.builders.base", "emit") in helpers
    assert ("crb.core.oracle.mutation", "_emit") in helpers
    wrong = []
    for path in sorted(SRC.rglob("*.py")):
        where = str(path.relative_to(ROOT))
        wrong += collisions(path.read_text(encoding="utf-8"), where, helpers, refused)
    assert not wrong, "an emit call passes a keyword its emitter refuses:\n" + "\n".join(wrong)


def test_the_scan_catches_the_excluded_call_as_it_stood() -> None:
    # the call P-817 found, as it was before the fix: the scan must name it
    old = (
        "def _emit(on_event, action, **payload):\n"
        "    on_event(action, payload)\n"
        "def score(on_event, task, m, outcomes):\n"
        "    _emit(on_event, 'oracle.mutation.excluded', task=task.task_id,\n"
        "          mutant=m.mutant_id, status=outcomes[-1].status)\n"
    )
    [hit] = collisions(old, "mutation.py", set(), _refused())
    assert "(callback)" in hit and "['status']" in hit
