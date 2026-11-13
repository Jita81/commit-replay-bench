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
from test_event_key_contract import documented_keys
from test_event_served_shape import _probe, _rows

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
    """Each expectation's action has a table row, and one of its rows (an action can have a
    row per emitter: ``build.start``) documents the key where it is read."""
    rows = _rows()
    bad = []
    for x in expects:
        cells = [r[3] for r in rows if f"`{x.action}`" in r[1]]
        if not cells:
            bad.append(f"{x.action} is not in the event table")
        elif not any((x.key, x.where == "envelope") in documented_keys(c) for c in cells):
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


# -- review of #142, round 1 ---------------------------------------------------------------

_OPTIONAL_COMMIT = (
    "import read_preflight\n"
    'X = read_preflight.Expect("builder.author_test.start", "commit", optional=True)\n'
    "EVENT_EXPECTATIONS = (X,)\n"
)


@pytest.mark.parametrize(
    "call",
    [
        'p.setdefault("commit")',
        'dict.setdefault(p, "commit")',
        'getattr(p, "setdefault")("commit")',
    ],
)
def test_setdefault_is_a_default_in_every_call_form(rp: ModuleType, call: str) -> None:
    """``setdefault(key)`` inserts and returns ``None`` for a missing key: a default."""
    src = _OPTIONAL_COMMIT + f'def keep(item):\n    p = item["payload"]\n    return {call}\n'
    problems = rp.source_problems(src)
    assert any("(payload.commit) turns a missing key into a value" in p for p in problems), problems


def test_pop_without_a_default_stays_strict(rp: ModuleType) -> None:
    src = (
        _OPTIONAL_COMMIT + 'def keep(item):\n    p = item["payload"]\n    return p.pop("commit")\n'
    )
    assert rp.source_problems(src) == []


_MODULE_PAYLOAD = 'import json\nEVENTS = json.load(open("x"))\nbody = EVENTS[0]["payload"]\n'


@pytest.mark.parametrize(
    "fn",
    [
        'def title(body):\n    return body.get("title", "")\n',
        'def title(*body):\n    return body.get("title", "")\n',
        'def title(**body):\n    return body.get("title", "")\n',
        'def title(meta):\n    body = meta\n    return body.get("title", "")\n',
        'def title(meta):\n    for body in meta:\n        return body.get("title", "")\n',
    ],
)
def test_a_local_name_shadows_a_module_payload_of_the_same_name(rp: ModuleType, fn: str) -> None:
    """A parameter (or any name bound in the function) is not the module's payload."""
    src = _MODULE_PAYLOAD + fn + 'def keep():\n    return title({"title": "t"})\n'
    assert rp.source_problems(src) == []


def test_a_global_declaration_keeps_the_module_payload(rp: ModuleType) -> None:
    src = _MODULE_PAYLOAD + "def keep(x):\n    global body\n    if x:\n        body = {}\n"
    src += '    return body.get("task")\n'
    problems = rp.source_problems(src)
    assert any("(payload.task) turns a missing key into a value" in p for p in problems), problems


#: Reads through ``value`` only, so nothing but the declarations ties them to the events.
ALIASED = {
    "from-import alias": (
        "from read_preflight import Expect as E, check, nonzero, value\n"
        'X = E("builder.author_test.start", "commit")\n'
    ),
    "module alias": (
        "import read_preflight as R\n"
        "from read_preflight import check, nonzero, value\n"
        'X = R.Expect("builder.author_test.start", "commit")\n'
    ),
}
_VALUE_READ = (
    "EVENT_EXPECTATIONS = (X,)\n"
    "def n(evs):\n    check(evs, EVENT_EXPECTATIONS)\n"
    '    return nonzero("n", sum(1 for e in evs if value(e, X)), len(evs))\n'
)


@pytest.mark.parametrize("form", sorted(ALIASED))
def test_an_aliased_expect_is_declared_and_checked(
    rp: ModuleType, tmp_path: Path, form: str
) -> None:
    source = ALIASED[form] + _VALUE_READ
    assert rp.declared(source) == [rp.Expect("builder.author_test.start", "commit")]
    no_commit = served_run([("build", "builder.author_test.start", {"task": "T"})])
    done = _cli(tmp_path, source, no_commit)
    assert done.returncode == 6, (done.stdout, done.stderr)
    assert "payload.commit is on 0 of 1 events" in done.stderr


def test_an_expect_of_another_module_is_not_a_declaration(rp: ModuleType) -> None:
    assert rp.declared('import other\nX = other.Expect("a.b", "k")\n') == []


UNEVALUABLE = {
    "a name for the key": (
        'KEY = "commit"\nX = read_preflight.Expect("builder.author_test.start", KEY)\n',
        "line 3: read_preflight.Expect(...) cannot be read without running the script",
    ),
    "a splat": (
        'A = ("builder.author_test.start", "commit")\nX = read_preflight.Expect(*A)\n',
        "line 3: read_preflight.Expect(...) cannot be read without running the script",
    ),
    "a keyword splat": (
        'K = {"key": "commit"}\nX = read_preflight.Expect("builder.author_test.start", **K)\n',
        "line 3: read_preflight.Expect(...) cannot be read without running the script",
    ),
    "a refused declaration": (
        'X = read_preflight.Expect("builder.author_test.start", "task")\n',
        "line 2: read_preflight.Expect(...) is refused: builder.author_test.start: 'task' is "
        "never kept in payload",
    ),
}


@pytest.mark.parametrize("shape", sorted(UNEVALUABLE))
def test_a_declaration_that_cannot_be_read_is_a_problem(
    rp: ModuleType, tmp_path: Path, shape: str
) -> None:
    decl, expected = UNEVALUABLE[shape]
    source = (
        "import read_preflight\n"
        + decl
        + "EVENT_EXPECTATIONS = (X,)\n"
        + "def n(evs):\n    read_preflight.check(evs, EVENT_EXPECTATIONS)\n"
        + '    return read_preflight.nonzero("n", sum(1 for e in evs\n'
        + "        if read_preflight.value(e, X)), len(evs))\n"
    )
    problems = rp.source_problems(source)
    assert any(expected in p for p in problems), problems
    no_commit = served_run([("build", "builder.author_test.start", {"task": "T"})])
    assert _cli(tmp_path, source, no_commit).returncode == 6


#: ``commit`` is declared for the start events only; the read takes it from failed events.
CROSS_ACTION = (
    "import read_preflight\n"
    'C = read_preflight.Expect("builder.author_test.start", "commit")\n'
    'F = read_preflight.Expect("builder.author_test.failed", "task_id", "envelope")\n'
    "EVENT_EXPECTATIONS = (C, F)\n"
    "def n(events):\n    read_preflight.check(events, EVENT_EXPECTATIONS)\n"
    "    failed = [e for e in events if read_preflight.has(e, F)]\n"
    '    k = sum(1 for e in failed if e["payload"]["commit"])\n'
    '    return read_preflight.nonzero("n", k, len(failed))\n'
)


def _start_and_failed() -> list[dict[str, Any]]:
    return served_run(
        [
            ("build", "builder.author_test.start", {"task": "T", "commit": "c"}),
            ("build", "builder.author_test.failed", {"task": "T"}),
        ]
    )


def test_a_payload_read_is_checked_against_every_action_it_may_read(
    rp: ModuleType, tmp_path: Path
) -> None:
    """Another action's declaration (or event) is no evidence for this lookup."""
    problems = rp.source_problems(CROSS_ACTION)
    assert (
        "line 8: payload.commit is read but no Expect declares it for "
        "builder.author_test.failed; a raw lookup is not tied to one action, so declare the "
        "key for every action the script reads or read it with read_preflight.value"
    ) in problems, problems
    runtime = rp.preflight(CROSS_ACTION, _start_and_failed())
    lacking = "payload.commit is read but is on 0 of 1 builder.author_test.failed events"
    assert any(p.startswith(lacking) for p in runtime), runtime
    done = _cli(tmp_path, CROSS_ACTION, _start_and_failed())
    assert done.returncode == 6, done.stdout


def test_a_key_declared_for_every_action_read_passes(rp: ModuleType) -> None:
    both = CROSS_ACTION.replace(
        "EVENT_EXPECTATIONS = (C, F)\n",
        'G = read_preflight.Expect("builder.author_test.failed", "commit")\n'
        "EVENT_EXPECTATIONS = (C, F, G)\n",
    )
    assert not [p for p in rp.source_problems(both) if "payload.commit" in p]


#: A compliant reader that reads only through ``value``: ``reads(source)`` is empty.
VALUE_ONLY = (
    "import read_preflight\n"
    'START = read_preflight.Expect("builder.author_test.start", "task_id", "envelope")\n'
    "EVENT_EXPECTATIONS = (START,)\n"
    "def started(events):\n    read_preflight.check(events, EVENT_EXPECTATIONS)\n"
    "    tasks = {read_preflight.value(e, START) for e in events}\n"
    '    return read_preflight.nonzero("started", len(tasks), len(events))\n'
)


def test_no_events_is_a_problem_even_for_a_value_only_read(rp: ModuleType, tmp_path: Path) -> None:
    assert rp.reads(VALUE_ONLY) == set()
    assert rp.preflight(VALUE_ONLY, _run()) == []
    problems = rp.preflight(VALUE_ONLY, [], label="t")
    assert problems == ["t: no events to read; a read over nothing proves nothing"]
    done = _cli(tmp_path, VALUE_ONLY, [])
    assert done.returncode == 6, done.stdout
    assert "no events to read" in done.stderr


def test_every_table_row_of_an_action_counts(rp: ModuleType) -> None:
    """``build.start`` has a core row and a factory row; ``item`` is the factory row's."""
    assert table_problems([rp.Expect("build.start", "item")]) == []
    assert table_problems([rp.Expect("build.start", "trial")]) == []
    assert table_problems([rp.Expect("build.start", "nope")]) == [
        "table lacks payload.nope for build.start"
    ]


def test_an_annotated_field_name_counts_where_it_is_documented(rp: ModuleType) -> None:
    """``status_at_request ∈ queued\\|running`` documents ``status_at_request``."""
    assert table_problems([rp.Expect("run.cancel_requested", "status_at_request")]) == []
    assert table_problems([rp.Expect("run.cancel_requested", "actor", "envelope")]) == []
    assert table_problems([rp.Expect("run.cancel_requested", "actor")]) == [
        "table lacks payload.actor for run.cancel_requested"
    ]


# -- review of #142, round 2 ---------------------------------------------------------------

_COMMIT_ON_START = (
    "import read_preflight\n"
    'C = read_preflight.Expect("builder.author_test.start", "commit")\n'
    "EVENT_EXPECTATIONS = (C,)\n"
)
_COUNT = (
    "def n(events):\n    read_preflight.check(events, EVENT_EXPECTATIONS)\n"
    "{pool}"
    '    k = sum(1 for e in pool if "commit" in e["payload"])\n'
    '    return read_preflight.nonzero("n", k, len(pool))\n'
)
#: Filters that pick events by a rule the static rule cannot read: each may take
#: ``builder.author_test.failed`` events, on which ``commit`` is never served.
UNREAD_FILTERS = {
    "startswith": (
        '    pool = [e for e in events if e["action"].startswith("builder.author_test")]\n'
    ),
    "a module set": ('    pool = [e for e in events if e["action"] in WANT]\n'),
    "a helper's parameter": ('    pool = pick(events, "builder.author_test.failed")\n'),
}
_UNREAD_PRELUDE = (
    'WANT = {"builder.author_test.start", "builder.author_test.failed"}\n'
    'def pick(events, act):\n    return [e for e in events if e["action"] == act]\n'
)


@pytest.mark.parametrize("shape", sorted(UNREAD_FILTERS))
def test_an_action_filter_the_rule_cannot_read_is_refused(
    rp: ModuleType, tmp_path: Path, shape: str
) -> None:
    source = _COMMIT_ON_START + _UNREAD_PRELUDE + _COUNT.format(pool=UNREAD_FILTERS[shape])
    problems = rp.source_problems(source)
    assert any("an event's action is used other than compared with constant" in p for p in problems)
    assert rp.preflight(source, _start_and_failed())
    done = _cli(tmp_path, source, _start_and_failed())
    assert done.returncode == 6, done.stdout


def test_a_read_that_names_no_action_is_checked_against_every_action(
    rp: ModuleType, tmp_path: Path
) -> None:
    """No filter at all: the read takes every event, so a declaration for one action is no
    evidence that the failed events carry the key."""
    source = _COMMIT_ON_START + _COUNT.format(pool="    pool = events\n")
    assert rp.source_problems(source) == []
    runtime = rp.preflight(source, _start_and_failed())
    assert any(
        p.startswith("payload.commit is read but is on 0 of 1 builder.author_test.failed")
        and "the read names no action" in p
        for p in runtime
    ), runtime
    assert _cli(tmp_path, source, _start_and_failed()).returncode == 6
    filtered = _COMMIT_ON_START + _COUNT.format(
        pool='    pool = [e for e in events if e["action"] == C.action]\n'
    )
    assert rp.preflight(filtered, _start_and_failed()) == []


#: ``Expect`` reached other than by a direct call: none is a declaration the rule can read.
HIDDEN_EXPECTS = {
    "a local rebinding": (
        'E = read_preflight.Expect\nX = E("builder.author_test.start", "commit")\n'
    ),
    "getattr": ('X = getattr(read_preflight, "Expect")("builder.author_test.start", "commit")\n'),
    "functools.partial": (
        "import functools\n"
        'S = functools.partial(read_preflight.Expect, "builder.author_test.start")\n'
        'X = S("commit")\n'
    ),
    "dataclasses.replace": (
        "import dataclasses\n"
        'Y = read_preflight.Expect("builder.author_test.start", "task_id", "envelope")\n'
        'X = dataclasses.replace(Y, key="commit", where="payload")\n'
    ),
    "a second binding": (
        'X = read_preflight.Expect("builder.author_test.start", "task_id", "envelope")\n'
        'for X in [read_preflight.Expect("builder.author_test.start", "seq", "envelope")]:\n'
        "    pass\n"
    ),
}


@pytest.mark.parametrize("shape", sorted(HIDDEN_EXPECTS))
def test_an_expectation_the_rule_cannot_see_declared_is_refused(
    rp: ModuleType, tmp_path: Path, shape: str
) -> None:
    source = (
        "import read_preflight\n"
        + HIDDEN_EXPECTS[shape]
        + "EVENT_EXPECTATIONS = (X,)\n"
        + "def n(evs):\n    read_preflight.check(evs, EVENT_EXPECTATIONS)\n"
        + '    return read_preflight.nonzero("n", sum(1 for e in evs\n'
        + "        if read_preflight.value(e, X)), len(evs))\n"
    )
    problems = rp.source_problems(source)
    assert any("is handed an expectation the rule cannot see declared" in p for p in problems), (
        problems
    )
    no_commit = served_run([("build", "builder.author_test.start", {"task": "T"})])
    assert rp.preflight(source, no_commit)
    assert _cli(tmp_path, source, no_commit).returncode == 6


def test_a_rebound_expect_is_named_as_such(rp: ModuleType) -> None:
    source = "import read_preflight\nE = read_preflight.Expect\n"
    assert rp.source_problems(source) == [
        "line 2: read_preflight.Expect is used other than in a direct call; the rule reads a "
        "declaration only as read_preflight.Expect(<constants>)"
    ]


@pytest.mark.parametrize(
    "fn",
    [
        'def title(x):\n    return (lambda body: body.get("title", ""))(x)\n',
        'def title(x):\n    return [body.get("title", "") for body in x]\n',
        'def title(x):\n    def inner(body):\n        return body.get("title", "")\n'
        "    return inner(x)\n",
    ],
)
def test_a_nested_scope_name_shadows_a_module_payload(rp: ModuleType, fn: str) -> None:
    src = _MODULE_PAYLOAD + fn + 'def keep():\n    return title([{"title": "t"}])\n'
    assert rp.source_problems(src) == []


def test_a_nested_scope_still_sees_what_it_does_not_bind(rp: ModuleType) -> None:
    """A closure over an enclosing payload, and a mark made inside a comprehension, still
    count: the nested scope only hides the names it binds."""
    closure = (
        'def keep(item):\n    p = item["payload"]\n'
        '    def inner():\n        return p.get("task")\n    return inner()\n'
    )
    assert any("(payload.task) turns a missing key" in p for p in rp.source_problems(closure))
    marked = (
        "def keep(item, rows):\n"
        '    n = sum(1 for r in rows if item["action"] == "builder.author_test.start")\n'
        '    return item.get("task_id")\n'
    )
    assert any("(envelope.task_id) turns a missing key" in p for p in rp.source_problems(marked))


@pytest.mark.parametrize("events", ['{"events": null}', "null", "5", '"x"', '{"events": {}}'])
def test_events_that_are_not_a_list_exit_6(rp: ModuleType, tmp_path: Path, events: str) -> None:
    script, data = tmp_path / "a_read.py", tmp_path / "events.json"
    script.write_text(GOOD_READ, encoding="utf-8")
    data.write_text(events, encoding="utf-8")
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--script", str(script), "--events", str(data)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 6, done.stderr
    assert "not a list" in done.stderr
    loaded = json.loads(events)
    inner = loaded.get("events", loaded) if isinstance(loaded, dict) else loaded
    with pytest.raises(rp.PreflightError, match="not a list"):
        rp.check(inner, [])


def test_an_unreadable_declaration_names_its_argument_stably(rp: ModuleType) -> None:
    decl, _expected = UNEVALUABLE["a name for the key"]
    problems = rp.source_problems("import read_preflight\n" + decl)
    assert problems == [
        "line 3: read_preflight.Expect(...) cannot be read without running the script (KEY is "
        "not a constant); write its arguments as constants"
    ]
    splat, _expected = UNEVALUABLE["a keyword splat"]
    assert "(**K is not a constant)" in rp.source_problems("import read_preflight\n" + splat)[0]


#: Ways to read a key of a payload as a value that the lookup forms alone did not see.
VALUE_READS = {
    "walrus getter": "(f := p.get)('commit')",
    "a copy": "p.copy().get('commit')",
    "dict unpacking": "{**p}.get('commit')",
    "type(p).get": "type(p).get(p, 'commit')",
    "ChainMap": "collections.ChainMap(p).get('commit')",
    "methodcaller": "operator.methodcaller('get', 'commit')(p)",
    "__getitem__": "p.__getitem__('commit')",
    "items": "next((v for k, v in p.items() if k == 'commit'), None)",
    "getattr other": "getattr(p, '__getitem__')('commit')",
}


@pytest.mark.parametrize("shape", sorted(VALUE_READS))
def test_every_other_way_to_read_a_payload_is_flagged(rp: ModuleType, shape: str) -> None:
    src = (
        "import collections, operator\n"
        + _OPTIONAL_COMMIT
        + f'def keep(item):\n    p = item["payload"]\n    return {VALUE_READS[shape]}\n'
    )
    assert rp.source_problems(src), shape


# -- review of #142, round 3 ---------------------------------------------------------------

_TASK_READ = (
    "import read_preflight\n"
    'S = read_preflight.Expect("builder.author_test.start", "task_id", "envelope", nonempty=True)\n'
    "EVENT_EXPECTATIONS = (S,)\n"
    "def n(events):\n    read_preflight.check(events, EVENT_EXPECTATIONS)\n"
    "    tasks = set()\n"
    "    for e in events:\n"
    '        body = e["payload"]\n'
    "{read}"
    '    return read_preflight.nonzero("n", len(tasks), len(events))\n'
)
#: A payload handed to a lambda: each reads ``task`` with a default, so two tasks count as
#: one ``"unknown"``.
LAMBDA_READS = {
    "a shadowing parameter": (
        '        tasks.add((lambda body: body.get("task", "unknown"))(body))\n'
    ),
    "another parameter name": '        tasks.add((lambda b: b.get("task", "unknown"))(body))\n',
    "a keyword argument": (
        '        tasks.add((lambda body: body.get("task", "unknown"))(body=body))\n'
    ),
    "a lambda bound to a name": (
        '        get = lambda body: body.get("task", "unknown")\n        tasks.add(get(body))\n'
    ),
}


@pytest.mark.parametrize("shape", sorted(LAMBDA_READS))
def test_a_payload_handed_to_a_lambda_keeps_its_kind(
    rp: ModuleType, tmp_path: Path, shape: str
) -> None:
    source = _TASK_READ.format(read=LAMBDA_READS[shape])
    problems = rp.source_problems(source)
    assert any("(payload.task) turns a missing key into a value" in p for p in problems), problems
    assert any("payload lookup of 'task'" in p for p in problems), problems
    runtime = rp.preflight(source, _run())
    assert any(p.startswith("payload.task is read but is on 0 of 3 events") for p in runtime)
    done = _cli(tmp_path, source, _run())
    assert done.returncode == 6, done.stdout


#: A payload (or the events) handed, with a function, to a call the rule cannot follow: what
#: the function's parameter receives is not known, so the use is refused.
UNFOLLOWED_HANDOFFS = {
    "map with a lambda": '        tasks |= set(map(lambda b: b.get("task", "unknown"), [body]))\n',
    "a sort key": '        tasks |= set(sorted([body], key=lambda b: b.get("task", "")))\n',
    "map with a def": "        tasks |= set(map(task_of, [body]))\n",
    "a starred parameter": "        tasks.add(first(body))\n",
    # A lambda bound other than by ``name = lambda``: the name is not followed.
    "an annotated lambda": (
        '        g: object = lambda b: b.get("task", "unknown")\n        tasks.add(g(body))\n'
    ),
    "a tuple-assigned lambda": (
        '        g, h = lambda b: b.get("task", "unknown"), 0\n        tasks.add(g(body))\n'
    ),
    "a walrus called in place": (
        '        tasks.add((g := lambda b: b.get("task", "unknown"))(body))\n'
    ),
    "a walrus then a call": (
        '        (g := lambda b: b.get("task", "unknown"))\n        tasks.add(g(body))\n'
    ),
    # A payload reaching a parameter through a default.
    "a lambda default": '        tasks.add((lambda b=body: b.get("task", "unknown"))())\n',
    "a bound lambda default": (
        '        f = lambda b=body: b.get("task", "unknown")\n        tasks.add(f())\n'
    ),
    "a def default": (
        "        def f(b=body):\n"
        '            return b.get("task", "unknown")\n        tasks.add(f())\n'
    ),
    # A callee the rule cannot resolve.
    "a returned lambda": '        tasks.add((lambda: lambda y: y.get("task", "u"))()(body))\n',
    "a partial called": "        tasks.add(functools.partial(task_of)(body))\n",
    "a partial bound": "        p = functools.partial(task_of)\n        tasks.add(p(body))\n",
    "a function alias": "        g = task_of\n        tasks.add(g(body))\n",
    "a factory": "        tasks.add(mk()(body))\n",
    "a dict of lambdas": '        tasks.add({"f": lambda b: b.get("task", "u")}["f"](body))\n',
    "a list of lambdas": '        tasks.add([lambda b: b.get("task", "u")][0](body))\n',
    "a conditional callee": "        tasks.add((task_of if body else task_of)(body))\n",
    "a class attribute": "        tasks.add(Get.f(body))\n",
    "a method of an instance": "        tasks.add(Get().g(body))\n",
    "a partial as a key": (
        "        p = functools.partial(task_of)\n"
        "        tasks |= {str(x) for x in sorted([body], key=p)}\n"
    ),
    # A method taken as a value, or called, through ``self`` other than as ``self.name(...)``.
    "a method value through self": (
        "        class R(Get):\n"
        "            def run(self):\n"
        "                return set(map(self.g, [body]))\n"
        "        tasks |= R().run()\n"
    ),
    "a method value through cls": (
        "        class R(Get):\n"
        "            @classmethod\n"
        "            def run(cls):\n"
        "                return set(map(cls.f, [body]))\n"
        "        tasks |= R.run()\n"
    ),
    "a method through super": (
        "        class R(Get):\n"
        "            def run(self):\n"
        "                return super().g(body)\n"
        "        tasks.add(R().run())\n"
    ),
    "a method through the class of self": (
        "        class R(Get):\n"
        "            def run(self):\n"
        "                return self.__class__.g(self, body)\n"
        "        tasks.add(R().run())\n"
    ),
    "a method through type of self": (
        "        class R(Get):\n"
        "            def run(self):\n"
        "                return type(self).g(self, body)\n"
        "        tasks.add(R().run())\n"
    ),
    "a method through getattr": (
        "        class R(Get):\n"
        "            def run(self):\n"
        '                return set(map(getattr(self, "g"), [body]))\n'
        "        tasks |= R().run()\n"
    ),
    # The method's name bound another way as well: still the method ``super()`` reaches.
    "a method through super, its name also a loop variable": (
        "        for g in ():\n"
        "            pass\n"
        "        class R(Get):\n"
        "            def run(self):\n"
        "                return super().g(body)\n"
        "        tasks.add(R().run())\n"
    ),
    "a function kept on an attribute": (
        "        class R:\n"
        "            def run(self):\n"
        "                self.h = task_of\n"
        "                return self.h(body)\n"
        "        tasks.add(R().run())\n"
    ),
    "a function kept on an attribute, as a value": (
        "        class R:\n"
        "            def run(self):\n"
        "                self.h = task_of\n"
        "                return set(map(self.h, [body]))\n"
        "        tasks |= R().run()\n"
    ),
    # A key function handed to a method of the payload list.
    "a sort of the payloads": (
        '        bodies = [x["payload"] for x in events]\n'
        '        bodies.sort(key=lambda b: b.get("task", "unknown"))\n'
        "        tasks |= {str(b) for b in bodies}\n"
    ),
}
_HANDOFF_PRELUDE = (
    "import functools\n"
    'def task_of(b):\n    return b.get("task", "unknown")\n'
    'def first(*a):\n    return a[0].get("task", "unknown")\n'
    'def mk():\n    return lambda b: b.get("task", "unknown")\n'
    "class Get:\n"
    '    f = staticmethod(lambda b: b.get("task", "unknown"))\n'
    '    def g(self, b):\n        return b.get("task", "unknown")\n'
)
#: The same shapes over plain data: nothing to refuse.
DATA_HANDOFFS = {
    "a key over rows": (
        "        rows = sorted([2, 1], key=lambda r: -r)\n        tasks.add(len(rows))\n"
    ),
    "a map over rows": "        xs = set(map(lambda r: r + 1, [1]))\n        tasks.add(len(xs))\n",
    "an event appended": (
        "        pool = []\n        pool.append(e)\n        tasks.add(len(pool))\n"
    ),
    # An attribute that is no function of this module, handed with a payload elsewhere.
    "a data attribute beside a payload": (
        "        class Box:\n"
        "            def __init__(self):\n"
        "                self.rows = []\n"
        "            def keep(self, n):\n"
        "                self.rows.append(n)\n"
        "                return len(self.rows)\n"
        "        tasks.add(Box().keep(1))\n"
    ),
    # A set's own method, beside a function of this module with the same name: the
    # receiver decides, not the name.
    "a builtin method named like a function": (
        "        def add(a, b):\n"
        "            return a + b\n"
        "        tasks.add(read_preflight.value(e, S))\n"
    ),
    "an import's function named like a function": (
        "        def value(x):\n"
        "            return x\n"
        "        tasks.add(read_preflight.value(e, S))\n"
    ),
    "an option read by getattr beside a value": (
        '        print(getattr(tasks, "label", ""), read_preflight.value(e, S))\n'
    ),
}


@pytest.mark.parametrize("shape", sorted(DATA_HANDOFFS))
def test_a_function_over_plain_data_is_not_refused(rp: ModuleType, shape: str) -> None:
    read = "        tasks.add(read_preflight.value(e, S))\n" + DATA_HANDOFFS[shape]
    source = _TASK_READ.format(read=read) + _HANDOFF_PRELUDE
    assert rp.source_problems(source) == []
    assert rp.preflight(source, _run()) == []


@pytest.mark.parametrize("shape", sorted(UNFOLLOWED_HANDOFFS))
def test_a_payload_handed_where_the_rule_cannot_follow_is_refused(
    rp: ModuleType, tmp_path: Path, shape: str
) -> None:
    source = _TASK_READ.format(read=UNFOLLOWED_HANDOFFS[shape]) + _HANDOFF_PRELUDE
    problems = rp.source_problems(source)
    assert any("the rule cannot follow what" in p for p in problems), problems
    assert rp.preflight(source, _run())
    assert _cli(tmp_path, source, _run()).returncode == 6


#: Filters that take events by excluding an action: each selects every other action.
EXCLUSION_FILTERS = {
    "!=": '    pool = [e for e in events if e["action"] != C.action]\n',
    "not in": '    pool = [e for e in events if e["action"] not in (C.action,)]\n',
    "not ==": '    pool = [e for e in events if not e["action"] == C.action]\n',
    "or": '    pool = [e for e in events if e["action"] == C.action or e["seq"]]\n',
    "if ... continue": (
        "    pool = []\n    for e in events:\n"
        '        if e["action"] == C.action:\n            continue\n        pool.append(e)\n'
    ),
    "a continue nested in an if": (
        "    pool = []\n    for e in events:\n"
        '        if e["action"] == C.action:\n            if True:\n                continue\n'
        "        pool.append(e)\n"
    ),
    "a continue in a try": (
        "    pool = []\n    for e in events:\n"
        '        if e["action"] == C.action:\n            try:\n                continue\n'
        "            finally:\n                pass\n        pool.append(e)\n"
    ),
    "a continue in a with": (
        "    import contextlib\n    pool = []\n    for e in events:\n"
        '        if e["action"] == C.action:\n'
        "            with contextlib.nullcontext():\n                continue\n"
        "        pool.append(e)\n"
    ),
    "if ... else": (
        "    pool = []\n    for e in events:\n"
        '        if e["action"] == C.action:\n            pass\n'
        "        else:\n            pool.append(e)\n"
    ),
    "a conditional expression": (
        '    pool = [e for e in events if (False if e["action"] == C.action else True)]\n'
    ),
    "a match wildcard": (
        "    pool = []\n    for e in events:\n"
        '        match e["action"]:\n            case C.action:\n                pass\n'
        "            case _:\n                pool.append(e)\n"
    ),
}


@pytest.mark.parametrize("shape", sorted(EXCLUSION_FILTERS))
def test_a_read_under_an_exclusion_filter_is_checked_against_every_action(
    rp: ModuleType, tmp_path: Path, shape: str
) -> None:
    """``commit`` is declared for the start action only; a pool that excludes it takes the
    failed event, which lacks ``commit``: that action is checked, not the excluded one."""
    source = _COMMIT_ON_START + _COUNT.format(pool=EXCLUSION_FILTERS[shape])
    assert rp.source_problems(source) == []
    runtime = rp.preflight(source, _start_and_failed())
    assert any(
        p.startswith("payload.commit is read but is on 0 of 1 builder.author_test.failed")
        and "an exclusion filter" in p
        for p in runtime
    ), runtime
    done = _cli(tmp_path, source, _start_and_failed())
    assert done.returncode == 6, done.stdout
