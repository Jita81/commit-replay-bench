"""The read preflight, its positive control, and the ratchet that every events reader uses it.

Navigation
----------
What it is:   Tests for scripts/read_preflight.py and the rules every events reader meets.
What it does: Runs the positive control: events built by the real emitter (top-level
              ``task_id``) and a read script with the Wave 4 lookup ``payload["task"]``
              planted must exit 6, as must the alias and the ``.get(key, default)``
              variants, while the correct read exits 0. Pins the mirror constants to the
              real emitter; checks the construction refusal, the check over all events, the
              signed zero waiver and the strict ``value``; flags every bypass a reviewer
              found (helper parameters, tuple / for / match targets, ``dict.get``,
              ``itemgetter``, ``try``/``except KeyError``, a misspelt action) and leaves rows
              that are not events alone; fails a script at any depth under scripts/ that
              reads run events without declaring ``EVENT_EXPECTATIONS``, calling
              ``read_preflight.check`` and ``read_preflight.nonzero`` and passing the static
              rule; checks each declared expectation against docs/API.md's event table.
How:          ``tests/served_events.py`` for fixtures; the script run as a subprocess for
              the exit code; ``ast`` over scripts/**/*.py; the table parser of
              tests/test_event_served_shape.py.
Layer:        tests — docs/ARCHITECTURE.md#72-observability
ADRs:         none
Works with:   scripts/read_preflight.py (what it tests), tests/served_events.py (the
              fixtures), docs/API.md (the event table a declaration must match),
              tests/test_event_served_shape.py (the table parser and the probe),
              scripts/wave4_primary_read.py (listed in PRE_DATES),
              src/crb/server/routes/runs.py (``EVENT_KEYS``, the mirror's source)
Tested by:    tests/test_read_preflight.py
Touch when:   never for a new repository; a script starts reading run events (it must pass
              the rules here), or an entry of PRE_DATES is fixed (delete it).
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from crb.observability.events import Emitter, MemorySink
from crb.server.routes.runs import EVENT_KEYS
from served_events import served_event, served_run
from test_event_served_shape import _keys, _probe, _rows

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
SCRIPT = SCRIPTS / "read_preflight.py"


def _load(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rp() -> ModuleType:
    return _load(SCRIPT)


#: Readers that pre-date the rule, with the reason. Each must still BREAK the rule (a fixed
#: script is deleted from here), so the list can only shrink.
PRE_DATES = {
    "scripts/wave4_primary_read.py": "registered and sha-pinned; its record is not edited",
}


def _run(n: int = 3) -> list[dict[str, Any]]:
    """Author-test start events as the code emits them: the callback gets ``task``."""
    return served_run(
        [("build", "builder.author_test.start", {"task": f"T{i}", "commit": "c"}) for i in range(n)]
    )


# -- the mirror and the fixture ------------------------------------------------------------


def test_the_mirror_constants_equal_the_product(rp: ModuleType) -> None:
    assert rp.ENVELOPE_KEYS == EVENT_KEYS
    probed = {k for k in (*EVENT_KEYS, "task", "sha", "error") if _probe(k) != "kept"}
    assert set(rp.LIFTED) == probed
    sink = MemorySink()
    Emitter(sink, trace_id="t").on_event("system")("p.x", {"task": "T", "error": "e"})
    Emitter(sink, trace_id="t").on_event("system")("p.y", {"sha": "S"})
    first, second = sink.events
    assert (first.task_id, first.error_message, second.task_id) == ("T", "e", "S")
    assert rp.LIFTED["task"] == rp.LIFTED["sha"] == "task_id"
    assert rp.LIFTED["error"] == "error_message"
    assert all(rp.LIFTED[k] == k for k in rp.LIFTED if k in EVENT_KEYS)


def test_a_fixture_dict_has_exactly_the_served_keys() -> None:
    ev = served_event("builder.author_test.start", task="T", commit="c")
    assert set(ev) == set(EVENT_KEYS) | {"payload"}
    assert ev["task_id"] == "T" and ev["payload"] == {"commit": "c"}


# -- Expect, check, value -----------------------------------------------------------------


def test_declaring_a_lifted_key_is_refused_at_construction(rp: ModuleType) -> None:
    with pytest.raises(ValueError, match="envelope as 'task_id'"):
        rp.Expect("builder.author_test.start", "task")
    for key in rp.LIFTED:
        with pytest.raises(ValueError, match="never kept in payload"):
            rp.Expect("a.b", key)
    with pytest.raises(ValueError, match="not a served envelope field"):
        rp.Expect("a.b", "task", "envelope")
    rp.Expect("mine.candidate", "repo")  # on_event keeps ``repo`` in the payload


def test_the_envelope_task_id_passes_on_real_served_events(
    rp: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    x = rp.Expect("builder.author_test.start", "task_id", "envelope", nonempty=True)
    rp.check(_run(), [x], label="t")
    out = capsys.readouterr().out
    assert "preflight ok: builder.author_test.start envelope.task_id on 3/3" in out


def test_a_payload_lookup_of_a_lifted_key_stops_with_where_it_is(rp: ModuleType) -> None:
    x = rp.Expect("builder.author_test.start", "task", explicit_payload=True)
    with pytest.raises(rp.PreflightError, match=r"payload\.task is on 0 of 3.*envelope\.task_id"):
        rp.check(_run(), [x])


def test_check_reads_every_event_not_a_sample(rp: ModuleType) -> None:
    """The break is on the LAST of 50 events: a check of one event per action passes."""
    evs = _run(49) + served_run([("build", "builder.author_test.start", {"task": "T49"})])
    with pytest.raises(rp.PreflightError, match="on 49 of 50"):
        rp.check(evs, [rp.Expect("builder.author_test.start", "commit")])
    rp.check(evs, [rp.Expect("builder.author_test.start", "commit", optional=True)], out=str)
    empty = _run(49) + served_run([("build", "builder.author_test.start", {"commit": ""})])
    x = rp.Expect("builder.author_test.start", "task_id", "envelope", nonempty=True)
    with pytest.raises(rp.PreflightError, match="is empty on 1 of 50"):
        rp.check(empty, [x])


def test_an_absent_action_stops_unless_declared_may_be_absent(rp: ModuleType) -> None:
    x = rp.Expect("builder.author_test.failed", "task_id", "envelope")
    with pytest.raises(rp.PreflightError, match="no event of this action"):
        rp.check(_run(), [x])
    may = rp.Expect(x.action, x.key, "envelope", may_be_absent=True)
    rp.check(_run(), [may], out=str)


def test_a_malformed_event_or_no_events_stops(rp: ModuleType) -> None:
    ev = _run()[0]
    del ev["task_id"]
    with pytest.raises(rp.PreflightError, match="envelope key 'task_id' is absent from 1 of 1"):
        rp.check([ev], [])
    bad = _run()[0] | {"payload": "x"}
    with pytest.raises(rp.PreflightError, match="payload is not an object on 1 of 1"):
        rp.check([bad], [])
    with pytest.raises(rp.PreflightError, match="no events"):
        rp.check([], [])


def test_value_has_no_default_and_raises_on_a_missing_key(rp: ModuleType) -> None:
    assert list(inspect.signature(rp.value).parameters) == ["event", "x"]
    ev = _run()[0]
    assert rp.value(ev, rp.Expect("builder.author_test.start", "task_id", "envelope")) == "T0"
    missing = rp.Expect("builder.author_test.start", "nope", optional=True)
    with pytest.raises(rp.PreflightError, match=r"payload\.nope is absent"):
        rp.value(ev, missing)
    assert not rp.has(ev, missing)


# -- a zero needs a signed waiver ---------------------------------------------------------


def test_an_unwaived_zero_raises_and_there_is_no_author_excuse(rp: ModuleType) -> None:
    assert "why_zero" not in inspect.signature(rp.nonzero).parameters
    with pytest.raises(rp.PreflightError, match=r"0 of 120.*signed Waiver"):
        rp.nonzero("usable tests", 0, 120)
    with pytest.raises(TypeError):
        rp.nonzero("usable tests", 0, 120, why_zero="no S1 run authored a test")
    with pytest.raises(rp.PreflightError, match="a zero is waived only by a signed Waiver"):
        rp.nonzero("usable tests", 0, 120, waiver="no S1 run authored a test")
    assert rp.nonzero("usable tests", 7, 120) == 7 and rp.nonzero("none", 0, 0) == 0
    with pytest.raises(rp.PreflightError, match="not a count"):
        rp.nonzero("usable tests", 121, 120)


def test_a_signed_waiver_names_the_count_the_signer_and_the_date(rp: ModuleType) -> None:
    w = rp.Waiver("usable tests", "no S1 run authored a test", "seat 2", "2026-11-12")
    lines: list[str] = []
    assert rp.nonzero("usable tests", 0, 120, waiver=w, out=lines.append) == 0
    assert lines == ["usable tests: 0 of 120, waived by seat 2 at 2026-11-12: " + w.reason]
    with pytest.raises(rp.PreflightError, match="covers 'usable tests', not this count"):
        rp.nonzero("authored tests", 0, 120, waiver=w)
    with pytest.raises(rp.PreflightError, match="not a zero; drop the waiver"):
        rp.nonzero("usable tests", 3, 120, waiver=w)
    for bad in (
        ("usable tests", "r", "", "2026-11-12"),
        ("usable tests", "", "seat 2", "2026-11-12"),
        ("usable tests", "r", "seat 2", "yesterday"),
        ("usable tests", "r", "seat 2", "2999-01-01"),
    ):
        with pytest.raises(ValueError, match=r"waiver needs|ISO 8601|future"):
            rp.Waiver(*bad)


# -- the positive control: the Wave 4 lookup, planted, must exit 6 -------------------------

GOOD_READ = """
import read_preflight

START = read_preflight.Expect("builder.author_test.start", "task_id", "envelope", nonempty=True)
COMMIT = read_preflight.Expect("builder.author_test.start", "commit")
EVENT_EXPECTATIONS = (START, COMMIT)


def keep(item):
    return read_preflight.value(item, START), read_preflight.value(item, COMMIT)


def started(events):
    read_preflight.check(events, EVENT_EXPECTATIONS)
    tasks = {read_preflight.value(e, START) for e in events if e["action"] == START.action}
    return read_preflight.nonzero("started tasks", len(tasks), len(events))
"""

#: The Wave 4 lookup, as it stood in scripts/wave4_primary_read.py (a getter helper).
WAVE4_HELPER = """
def _payload_get(item, key):
    payload = item.get("payload")
    if not isinstance(payload, dict) or key not in payload:
        return None
    return payload[key]


def keep(item):
    if item["action"] == "builder.author_test.start":
        return _payload_get(item, "task")
"""

PLANTED = {
    "direct": 'def keep(item):\n    return item["payload"]["task"]\n',
    "alias": ('def keep(item):\n    p = item["payload"]\n    q = p\n    return q["task"]\n'),
    "alias via or": ('def keep(item):\n    p = item["payload"] or {}\n    return p.get("task")\n'),
    "membership": 'def keep(item):\n    p = item["payload"]\n    return "task" in p\n',
    "default on payload": (
        "import read_preflight\n"
        'X = read_preflight.Expect("builder.author_test.start", "commit")\n'
        "EVENT_EXPECTATIONS = (X,)\n"
        'def keep(item):\n    p = item["payload"]\n    return p.get("commit", "")\n'
    ),
    "default on event": 'def keep(ev):\n    return ev.get("task_id", "")\n',
    "envelope typo": (
        'def keep(ev):\n    if ev["action"] == "builder.author_test.start":\n'
        '        return ev["task"]\n'
    ),
    "undeclared payload key": 'def keep(ev):\n    return ev["payload"]["commit"]\n',
    "wave 4 helper": WAVE4_HELPER,
}


def _cli(tmp_path: Path, source: str, events: Any) -> subprocess.CompletedProcess[str]:
    script, data = tmp_path / "a_read.py", tmp_path / "events.json"
    script.write_text(source, encoding="utf-8")
    data.write_text(json.dumps(events), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--script", str(script), "--events", str(data)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_positive_control_the_wave_4_lookup_exits_6(rp: ModuleType, tmp_path: Path) -> None:
    """Events as the code emits them (top-level ``task_id``) and the read with the Wave 4
    lookup planted: the preflight stops with exit 6 and says where the key is served."""
    events = _run()
    assert all(e["task_id"] and "task" not in e["payload"] for e in events)
    done = _cli(tmp_path, PLANTED["direct"], events)
    assert done.returncode == rp.EXIT_CODE == 6, done.stderr
    assert "payload lookup of 'task'; the emitter serves it at the envelope as 'task_id'" in (
        done.stderr
    )
    assert "payload.task is read but is on 0 of 3 events; served at envelope.task_id" in (
        done.stderr
    )
    ok = _cli(tmp_path, GOOD_READ, {"events": events})
    assert ok.returncode == 0, ok.stderr
    assert "preflight ok over 3 events" in ok.stdout


@pytest.mark.parametrize("variant", sorted(PLANTED))
def test_every_planted_variant_exits_6(rp: ModuleType, tmp_path: Path, variant: str) -> None:
    assert rp.main(["--script", _write(tmp_path, PLANTED[variant]), "--events", _events(tmp_path)])
    done = _cli(tmp_path, PLANTED[variant], _run())
    assert done.returncode == 6, (variant, done.stdout, done.stderr)


def _write(tmp_path: Path, source: str) -> str:
    p = tmp_path / "planted.py"
    p.write_text(source, encoding="utf-8")
    return str(p)


def _events(tmp_path: Path) -> str:
    p = tmp_path / "served.json"
    p.write_text(json.dumps(_run()), encoding="utf-8")
    return str(p)


def test_the_static_rule_names_each_fault(rp: ModuleType) -> None:
    def first(variant: str) -> str:
        return rp.source_problems(PLANTED[variant])[0]

    assert "line 4: payload lookup of 'task'" in first("alias")
    assert ".get on an event dict (payload.task)" in first("alias via or")
    assert "line 3: payload lookup of 'task'" in first("membership")
    assert ".get on an event dict (payload.commit)" in first("default on payload")
    assert ".get on an event dict (envelope.task_id)" in first("default on event")
    assert "'task' is not a served envelope field" in first("envelope typo")
    assert "payload.commit is read but no Expect declares it" in first("undeclared payload key")
    helper = rp.source_problems(WAVE4_HELPER)
    assert any("line 11: payload lookup of 'task'" in p for p in helper), helper
    assert any(".get on an event dict (envelope.payload)" in p for p in helper), helper
    assert rp.source_problems(GOOD_READ) == []


def test_the_rule_follows_a_renamed_payload_and_a_parameter_named_payload(
    rp: ModuleType,
) -> None:
    renamed = 'def keep(item):\n    body = item["payload"]\n    return body["task"]\n'
    assert rp.source_problems(renamed)
    # a parameter called ``payload`` is a payload wherever it is bound (review finding 2)
    named = 'def f(payload):\n    return payload["task"]\n'
    assert any("payload lookup of 'task'" in p for p in rp.source_problems(named))


#: Shapes a reviewer found exiting 0 (review of 2026-11-13, findings 1 and 2): each hides a
#: payload lookup of a lifted key, a default, or an action that matches nothing.
BYPASSES = {
    "helper parameter": (
        'def task_of(p):\n    return p.get("task")\n'
        'def keep(item):\n    return task_of(item["payload"])\n',
        "line 2: payload lookup of 'task'",
    ),
    "helper parameter named payload": (
        'def _task(payload):\n    return payload.get("task")\n'
        'def keep(item):\n    return _task(item["payload"])\n',
        "line 2: payload lookup of 'task'",
    ),
    "keyword argument": (
        'def task_of(*, p):\n    return p["task"]\n'
        'def keep(item):\n    return task_of(p=item["payload"])\n',
        "line 2: payload lookup of 'task'",
    ),
    "method with self": (
        "class R:\n    def task_of(self, p):\n        return p['task']\n"
        "    def keep(self, item):\n        return self.task_of(item['payload'])\n",
        "line 3: payload lookup of 'task'",
    ),
    "for target over a generator": (
        "def keep(events):\n    out = []\n    for p in (e['payload'] for e in events):\n"
        "        out.append(p['task'])\n    return out\n",
        "line 4: payload lookup of 'task'",
    ),
    "enumerate target": (
        "def keep(rows):\n    for i, ev in enumerate(rows):\n        p = ev['payload']\n"
        "        yield p['task']\n",
        "line 4: payload lookup of 'task'",
    ),
    "tuple unpack": (
        'def keep(item):\n    action, p = item["action"], item["payload"]\n    return p["task"]\n',
        "line 3: payload lookup of 'task'",
    ),
    "dict.get unbound": (
        'def keep(item):\n    return dict.get(item["payload"], "task")\n',
        "line 2: dict.get on an event dict (payload.task)",
    ),
    "a name called ev with no marker key": (
        'def keep(ev):\n    return ev.get("task")\n',
        "line 2: 'task' is not a served envelope field",
    ),
    "match mapping": (
        'def keep(item):\n    match item:\n        case {"payload": {"task": t}}:\n'
        "            return t\n    return None\n",
        "line 3: payload lookup of 'task'",
    ),
    "match capture": (
        'def keep(item):\n    match item:\n        case {"payload": p}:\n'
        '            return p["task"]\n',
        "line 4: payload lookup of 'task'",
    ),
    "itemgetter": (
        'import operator\ndef keep(item):\n    return operator.itemgetter("task")(item["payload"])\n',
        "line 3: payload lookup of 'task'",
    ),
    "getattr get": (
        'def keep(item):\n    p = item["payload"]\n    return getattr(p, "get")("task")\n',
        "line 3: getattr .get on an event dict (payload.task)",
    ),
    "module-level alias": (
        'import json\nEVENTS = json.load(open("x"))\nP = EVENTS[0]["payload"]\n'
        'def keep():\n    return P["task"]\n',
        "line 5: payload lookup of 'task'",
    ),
    "try except KeyError": (
        "import read_preflight\n"
        'X = read_preflight.Expect("builder.author_test.start", "commit", optional=True)\n'
        'EVENT_EXPECTATIONS = (X,)\ndef keep(item):\n    p = item["payload"]\n    try:\n'
        '        return p["commit"]\n    except KeyError:\n        return 0\n',
        "line 7: except KeyError on an event dict (payload.commit)",
    ),
    "suppress KeyError": (
        "from contextlib import suppress\n"
        'def keep(item, n):\n    with suppress(KeyError):\n        n += item["seq"]\n'
        '    return n if item["payload"] else 0\n',
        "line 4: except KeyError on an event dict (envelope.seq)",
    ),
    "an action that matches nothing": (
        "import read_preflight\n"
        "START = read_preflight.Expect("
        '"builder.author_test.start", "task_id", "envelope", nonempty=True)\n'
        "EVENT_EXPECTATIONS = (START,)\ndef usable(events):\n"
        "    read_preflight.check(events, EVENT_EXPECTATIONS)\n"
        "    return len({read_preflight.value(e, START) for e in events\n"
        '                if e["action"] == "builder.author_tests.start"})\n',
        "line 7: action 'builder.author_tests.start' is compared with an event's action but "
        "no Expect declares it",
    ),
    "an action in a tuple": (
        'def keep(ev):\n    return ev["action"] in ("a.b", "c.d")\n',
        "line 2: action 'a.b' is compared",
    ),
    "an action in a match": (
        'def keep(ev):\n    match ev["action"]:\n        case "a.b":\n            return 1\n',
        "line 3: action 'a.b' is compared",
    ),
}


@pytest.mark.parametrize("shape", sorted(BYPASSES))
def test_every_reviewed_bypass_is_flagged(rp: ModuleType, shape: str) -> None:
    source, expected = BYPASSES[shape]
    problems = rp.source_problems(source)
    assert any(expected in p for p in problems), (shape, problems)


#: Reads a reviewer found flagged though they look at no event (review finding 3 and 6).
NOT_EVENTS = {
    "task rows joined to events": (
        "import read_preflight\n"
        "START = read_preflight.Expect("
        '"builder.author_test.start", "task_id", "envelope", nonempty=True)\n'
        "EVENT_EXPECTATIONS = (START,)\n"
        "def usable(events, task_rows):\n"
        "    read_preflight.check(events, EVENT_EXPECTATIONS)\n"
        "    started = {read_preflight.value(e, START) for e in events}\n"
        "    n = sum(1 for row in task_rows\n"
        '            if row["task_id"] in started and row.get("verdict") == "clean")\n'
        '    return read_preflight.nonzero("clean started", n, len(task_rows))\n'
    ),
    "run rows": (
        "def arms(runs):\n    out = {}\n    for run in runs:\n"
        '        out[run["id"]] = run["params"]["arm"] if run["status"] == "done" else None\n'
        '    for r in runs:\n        print(r["action"] if "action" in r else r["kind"])\n'
        "    return out\n"
    ),
    "a getter's name on another object": (
        'def field(ev, key):\n    return ev[key]\ndef base_url(cfg):\n    return cfg.field("url")\n'
    ),
}


@pytest.mark.parametrize("shape", sorted(NOT_EVENTS))
def test_a_row_that_is_not_an_event_is_not_flagged(rp: ModuleType, shape: str) -> None:
    assert rp.source_problems(NOT_EVENTS[shape]) == []


def test_a_getter_still_counts_at_its_bare_call(rp: ModuleType) -> None:
    src = NOT_EVENTS["a getter's name on another object"] + 'def k(e):\n    return field(e, "x")\n'
    assert rp.source_problems(src) == ["line 6: 'x' is not a served envelope field"]


# -- every reader of run events uses it ---------------------------------------------------


def reader_problems(rp: ModuleType, source: str) -> list[str]:
    return rp.protocol_problems(source) + rp.source_problems(source)


#: What marks a script as a reader of run events: the events route, either import of this
#: module, or a client helper that fetches events without spelling the route.
READER = re.compile(
    r"/events\b|^\s*(?:import|from)\s+read_preflight\b|\brun_events\b|\.events\(", re.M
)


def readers() -> list[Path]:
    """Scripts at any depth under scripts/ that read run events."""
    return [
        p
        for p in sorted(SCRIPTS.rglob("*.py"))
        if p != SCRIPT and READER.search(p.read_text("utf-8"))
    ]


def test_the_reader_finder_sees_every_form() -> None:
    for text in (
        'get(f"/api/v1/runs/{rid}/events/log")',
        "import read_preflight",
        "from read_preflight import check, nonzero",
        "    from read_preflight import value",
        "rows = client.run_events(rid)",
        "rows = api.events(rid)",
    ):
        assert READER.search(text), text
    assert not READER.search("from crb.observability.events import Emitter")


def test_the_protocol_requires_check_and_nonzero_in_either_import_form(rp: ModuleType) -> None:
    assert rp.protocol_problems(GOOD_READ) == []
    from_form = GOOD_READ.replace("import read_preflight\n", "import read_preflight as rp\n")
    assert rp.protocol_problems(from_form.replace("read_preflight.", "rp.")) == []
    no_count = GOOD_READ.replace("read_preflight.nonzero(", "max(")
    assert rp.protocol_problems(no_count) == [
        "never calls read_preflight.nonzero(...); a count whose lookup matched nothing would "
        "print as a 0"
    ]
    imported = (
        "from read_preflight import Expect, check, nonzero\n"
        'X = Expect("builder.author_test.start", "task_id", "envelope")\n'
        "EVENT_EXPECTATIONS = (X,)\n"
        "def n(evs):\n    check(evs, EVENT_EXPECTATIONS)\n    return nonzero('n', len(evs), 1)\n"
    )
    assert rp.protocol_problems(imported) == []
    assert "never calls read_preflight.check(...)" in rp.protocol_problems("x = 1\n")


def test_the_cli_stops_a_read_that_never_guards_its_count(rp: ModuleType, tmp_path: Path) -> None:
    """Review finding 1: the Expect is right and ``check`` is called, but the comprehension
    filters on a misspelt action, so the figure is 0; the CLI must not say ok."""
    source, _ = BYPASSES["an action that matches nothing"]
    done = _cli(tmp_path, source, _run())
    assert done.returncode == 6, done.stdout
    assert "'builder.author_tests.start' is compared" in done.stderr
    assert "never calls read_preflight.nonzero" in done.stderr


def test_every_script_that_reads_run_events_uses_the_preflight(rp: ModuleType) -> None:
    assert readers(), "the reader finder matches nothing"
    bad = {}
    for p in readers():
        rel = str(p.relative_to(ROOT))
        if rel in PRE_DATES:
            continue
        if found := reader_problems(rp, p.read_text(encoding="utf-8")):
            bad[rel] = found
    assert not bad, f"a script reads run events without the read preflight: {bad}"


def test_the_pre_dating_readers_still_break_the_rule(rp: ModuleType) -> None:
    for rel in PRE_DATES:
        problems = rp.source_problems((ROOT / rel).read_text(encoding="utf-8"))
        assert any("payload lookup of 'task'" in p for p in problems), f"fixed: drop {rel}"


def table_problems(expects: list[Any]) -> list[str]:
    """Each expectation names a table row that documents the key where it is read."""
    rows = _rows()
    bad = []
    for x in expects:
        row = next((r for r in rows if f"`{x.action}`" in r[1]), None)
        if row is None:
            bad.append(f"{x.action} is not in the event table")
        elif (x.key, x.where == "envelope") not in set(_keys(row[3])):
            bad.append(f"table lacks {x.where}.{x.key} for {x.action}")
    return bad


def test_table_problems_reads_the_table(rp: ModuleType) -> None:
    good = rp.declared(GOOD_READ)
    assert len(good) == 2 and table_problems(good) == []
    wrong = [rp.Expect("builder.author_test.start", "nope"), rp.Expect("no.such", "x")]
    assert table_problems(wrong) == [
        "table lacks payload.nope for builder.author_test.start",
        "no.such is not in the event table",
    ]


def test_a_declared_expectation_matches_the_table(rp: ModuleType) -> None:
    bad = []
    for p in readers():
        if str(p.relative_to(ROOT)) not in PRE_DATES:
            bad += [f"{p.name}: {b}" for b in table_problems(rp.declared(p.read_text("utf-8")))]
    assert not bad, "\n".join(bad)
