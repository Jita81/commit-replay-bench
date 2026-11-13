"""docs/API.md's event table against the payload keys the emit sites pass (the P-817 follow-on).

``test_event_served_shape.py`` proves the table never names a lifted key as a payload key, and
``test_event_vocabulary.py`` proves every emitted action has a row. Neither proves that a
documented payload key is one the code passes, or that a key the code passes is documented: a
renamed key (``item_ref`` in the table, ``item`` in the call) passed both, and a reader written
from the table looks for a key nobody sends.

Navigation
----------
What it is:   The doc-versus-emit-site payload-key contract for StepEvents, with a baseline
              that may only shrink.
What it does: Walks every emit call under src/crb, works out the payload keys the event is
              served with (for a callback event, the real emitter's lift is applied: a key
              ``_probe`` does not find kept is not a payload key), and compares them per table
              row with the row's documented keys. ``A <action> <key>``: a top-level documented
              key that no site of the row passes. ``B <action> <key>``: a key a site passes
              that the row never names. A call with a ``**`` splat or a non-literal payload is
              "open" and is never read as proof that a documented key is absent. Gaps present
              when this suite was written are listed in tests/fixtures/event_key_gaps.txt.
How:          ``ast`` over src/crb with test_event_vocabulary's scope-aware action reader; the
              row parser and the lift probe are test_event_served_shape's; the named parameters
              of ``Emitter.emit`` / ``error`` / ``timed`` and ``FactoryLoop._emit`` are read
              with ``inspect``.
Layer:        tests — docs/ARCHITECTURE.md#72-observability
ADRs:         none
Works with:   docs/API.md (the table), src/crb/observability/events.py (the emitter and its
              lift), src/crb/factory/loop.py (``FactoryLoop._emit``),
              tests/test_event_served_shape.py (the rows, the lift probe),
              tests/test_event_vocabulary.py (the action reader),
              tests/fixtures/event_key_gaps.txt (the baseline)
Tested by:    tests/test_event_key_contract.py
Touch when:   never for a new repository; a payload key is added, renamed or dropped at an
              emit call (change its table row in the same commit), or a new emit shape is
              added (teach ``served_keys`` its shape).
"""

from __future__ import annotations

import ast
import functools
import hashlib
import inspect
import re
from dataclasses import dataclass
from typing import Any

from crb.factory.loop import FactoryLoop
from crb.observability.events import Emitter
from test_event_served_shape import ENVELOPE, NOT_KEYS, _probe, _rows
from test_event_vocabulary import _SCOPES, SRC, _bindings, _call_actions, _own_nodes

ROOT = SRC.parents[1]
BASELINE = ROOT / "tests" / "fixtures" / "event_key_gaps.txt"

#: Writers that keep ``payload={...}`` as given; their other keywords are envelope fields.
EXPLICIT = {"append_event", "append_system_event"}
#: Helper callbacks ``f(on_event, action, **payload)`` hand the payload to ``on_event``.
CALLBACK_HELPERS = {"emit", "_emit"}


def _named(fn: Any) -> frozenset[str]:
    """Named (non-``**``) parameters of ``fn``: on the emitter these are envelope fields."""
    return frozenset(
        p.name
        for p in inspect.signature(fn).parameters.values()
        if p.kind is not inspect.Parameter.VAR_KEYWORD and p.name != "self"
    )


NAMED = {
    "emit": _named(Emitter.emit),
    "error": _named(Emitter.error),
    "timed": _named(Emitter.timed),
    "_emit": _named(FactoryLoop._emit) | _named(Emitter.emit),
}


@functools.cache
def _kept(key: str) -> bool:
    """``True`` when the real ``Emitter.on_event`` keeps ``key`` in ``payload``."""
    return _probe(key) == "kept"


@dataclass(frozen=True)
class Site:
    """One emit call: the action, where, the payload keys it is served with, and whether its
    key set is unknowable from the source (a ``**`` splat, a non-literal mapping)."""

    action: str
    where: str
    payload: frozenset[str]
    open: bool


def _dict_keys(node: ast.AST | None) -> set[str] | None:
    """The keys of a dict literal whose keys are all string constants, else ``None``."""
    if isinstance(node, ast.Dict) and all(
        isinstance(k, ast.Constant) and isinstance(k.value, str) for k in node.keys
    ):
        return {str(k.value) for k in node.keys if isinstance(k, ast.Constant)}
    return None


def _lift(keys: set[str]) -> set[str]:
    """What ``Emitter.on_event`` leaves in ``payload``, probed on the real emitter."""
    return {k for k in keys if _kept(k)}


def _is_helper_call(node: ast.Call) -> bool:
    """``_emit(on_event, action, …)`` / ``emit(on_event, …)`` / ``base.emit(on_event, …)``:
    the first argument is a callback, so the payload goes through ``on_event``."""
    fn = node.func
    name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
    if name not in CALLBACK_HELPERS or len(node.args) < 2:
        return False
    first = node.args[0]
    if isinstance(fn, ast.Name):
        return isinstance(first, ast.Name | ast.Attribute | ast.Call)
    text = ast.unparse(first)
    return "on_event" in text or text.endswith(("cb", "_cb", "callback"))


def served_keys(node: ast.Call) -> tuple[set[str], bool]:
    """``(payload keys the call is served with, open)`` for one emit call."""
    fn = node.func
    name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
    given = {k.arg for k in node.keywords if k.arg}
    splat = any(k.arg is None for k in node.keywords)
    if name in EXPLICIT:
        arg = next((k.value for k in node.keywords if k.arg == "payload"), None)
        if arg is None:
            return set(), splat
        keys = _dict_keys(arg)
        return (keys or set()), keys is None
    if name in {"on_event", "cb"}:
        keys = _dict_keys(node.args[1]) if len(node.args) == 2 else None
        return _lift(keys or set()), keys is None
    if _is_helper_call(node):
        return _lift(given), splat
    if isinstance(fn, ast.Attribute) and name in NAMED:
        return given - NAMED[name], splat  # Emitter.emit keeps these in payload as given
    return set(), True  # any other writer: not read


def sites_of(source: str, where: str, in_builders: bool = False) -> list[Site]:
    """Every emit site in ``source``, each name read in the scope of the call that uses it."""
    out: list[Site] = []

    def walk(scope: ast.AST, outer: dict[str, str | None]) -> None:
        consts = {**outer, **_bindings(scope)}
        for node in _own_nodes(scope):
            if isinstance(node, _SCOPES):
                walk(node, outer if isinstance(scope, ast.ClassDef) else consts)
            elif isinstance(node, ast.Call):
                actions = _call_actions(node, consts, in_builders)
                if actions:
                    keys, opened = served_keys(node)
                    at = f"{where}:{node.lineno}"
                    out.extend(Site(a, at, frozenset(keys), opened) for a in sorted(actions))

    walk(ast.parse(source), {})
    return out


@functools.cache
def all_sites() -> dict[str, list[Site]]:
    by_action: dict[str, list[Site]] = {}
    for path in sorted(SRC.rglob("*.py")):
        in_builders = path.parent == SRC / "builders" and path.name != "adapter.py"
        rel = str(path.relative_to(ROOT))
        for s in sites_of(path.read_text(encoding="utf-8"), rel, in_builders):
            by_action.setdefault(s.action, []).append(s)
    return by_action


def top_keys(cell: str) -> set[str]:
    """Identifier code spans at parenthesis depth 0, before the first " — ", not marked "on
    the envelope": the keys a row names as its own. A value or a nested key sits in
    parentheses or after the dash."""
    head = cell.split(" — ", 1)[0]
    out: set[str] = set()
    depth = i = 0
    while i < len(head):
        c = head[i]
        if c == "`":
            j = head.find("`", i + 1)
            if j < 0:
                break
            span = head[i + 1 : j]
            if (
                depth == 0
                and re.fullmatch(r"[a-z_][a-z0-9_]*", span)
                and not head[j + 1 :].startswith(" on the envelope")
            ):
                out.add(span)
            i = j + 1
            continue
        depth = depth + 1 if c == "(" else max(0, depth - 1) if c == ")" else depth
        i += 1
    return out


#: A code span that names a key and says more about it: ``new[]``, ``refusals[{code, n}]``,
#: ``status_at_request ∈ queued|running``, ``reason: ""``.
#: A plain key span is the same pattern with no annotation.
_ANNOTATED = re.compile(r"([a-z_][a-z0-9_]*)(?:\[.*\]|\s*[∈=:].*)?")


def documented_keys(cell: str) -> set[tuple[str, bool]]:
    """``(key, on_envelope)`` for every key a payload cell names anywhere, an annotated span
    normalised to its key and the " on the envelope" after the span kept as its placement.
    The one reader of a cell for every check that asks "does the table document this key"."""
    return {
        (k.group(1), bool(m.group(2)))
        for m in re.finditer(r"`([^`]+)`(" + ENVELOPE + ")?", cell)
        if (k := _ANNOTATED.fullmatch(m.group(1)))
    }


def named_keys(cell: str) -> set[str]:
    """Every key a payload cell names anywhere (the B direction reads the cell leniently)."""
    return {k for k, _on_env in documented_keys(cell)}


def _actions(action_cell: str) -> list[str]:
    return re.findall(r"`([a-z_]+(?:\.[a-z_]+)+)`", action_cell)


def row_gaps(
    action_cell: str,
    payload_cell: str,
    sites: dict[str, list[Site]],
    also_named: dict[str, set[str]] | None = None,
) -> set[str]:
    """``"A <action> <key>"`` / ``"B <action> <key>"`` lines for one table row.
    ``also_named``: per action, the keys other rows of the table name for it (an action with
    a row per emitter, ``build.start`` in core/run.py and factory/build.py)."""
    actions = _actions(action_cell)
    row_sites = [s for a in actions for s in sites.get(a, [])]
    named = named_keys(payload_cell)
    found: set[str] = set()
    for s in row_sites:  # B: the code passes a key no row of the action names
        known = named | (also_named or {}).get(s.action, set())
        found |= {f"B {s.action} {k}" for k in s.payload if k not in known}
    if row_sites and not any(s.open for s in row_sites):  # A: a key nobody passes
        passed = set().union(*(s.payload for s in row_sites))
        skip = {k for span, k in NOT_KEYS if span in action_cell}
        for k in top_keys(payload_cell) - passed - skip:
            if _kept(k):  # a lifted key is test_event_served_shape's finding
                found.add(f"A {actions[0]} {k}")
    return found


@functools.cache
def gaps() -> frozenset[str]:
    sites = all_sites()
    rows = _rows()
    by_action: dict[str, set[str]] = {}
    for row in rows:
        for a in _actions(row[1]):
            by_action.setdefault(a, set()).update(named_keys(row[3]))
    found: set[str] = set()
    for _stage, action_cell, _status, payload_cell, _by, _consumed in rows:
        found |= row_gaps(action_cell, payload_cell, sites, by_action)
    return frozenset(found)


def baseline() -> set[str]:
    lines = (ln.split("#", 1)[0].strip() for ln in BASELINE.read_text("utf-8").splitlines())
    return {ln for ln in lines if ln}


def test_the_walker_reads_the_emit_sites() -> None:
    sites = all_sites()
    closed = [a for a, ss in sites.items() if any(not s.open for s in ss)]
    assert len(sites) > 100 and len(closed) > 50, (len(sites), len(closed))


def test_the_known_author_test_sites_are_served_as_the_emitter_serves_them() -> None:
    # tests/test_event_served_shape.py reads these back through the real route
    sites = all_sites()
    start = [s for s in sites["builder.author_test.start"] if not s.open]
    assert start and all(s.payload == {"commit"} for s in start), start
    failed = [s for s in sites["builder.author_test.failed"] if not s.open]
    assert failed and all(s.payload == set() for s in failed), failed


def test_no_new_gap_between_the_table_and_the_emit_sites() -> None:
    new = sorted(gaps() - baseline())
    assert not new, (
        "docs/API.md and the emit sites disagree on a payload key. A <action> <key>: the row "
        "names a key no call passes (rename the cell or the call). B <action> <key>: a call "
        "passes a key the row never names (document it). Fix the row or the call; never add "
        "to tests/fixtures/event_key_gaps.txt:\n" + "\n".join(new)
    )


def test_the_gap_baseline_only_shrinks() -> None:
    stale = sorted(baseline() - gaps())
    assert not stale, (
        "no longer a gap, delete from tests/fixtures/event_key_gaps.txt:\n" + "\n".join(stale)
    )


#: How many lines tests/fixtures/event_key_gaps.txt holds. The two tests above only force
#: the file to equal today's gaps, so a commit that adds a gap AND its line would pass them;
#: this count and ``INITIAL_GAPS`` below are the ratchet. Lower it with every deleted line;
#: never raise it.
BASELINE_SIZE = 79

#: The baseline as this suite first found it (2026-11-13), copied here so a commit that
#: fixes one gap and adds another cannot swap the two lines in the fixture: every line of
#: tests/fixtures/event_key_gaps.txt must be one of these. Never add to it; its digest is
#: pinned below.
INITIAL_GAPS: frozenset[str] = frozenset(
    line.strip()
    for line in """
A connect.stage.chained auto_stages
B author.attempt cost_known
B author.attempt item
B author.attempt provider
B author.done item
B author.start item
B author.start route
B build.attempt builder
B build.attempt fixture
B build.done files
B build.done fixture
B build.start auth
B build.start files
B build.tool fixture
B builder.build.attempt builder
B builder.build.attempt fixture
B builder.build.done builder
B builder.build.done fixture
B builder.build.start auth
B builder.build.start builder
B builder.build.start mode
B builder.build.start model
B builder.build.tool fixture
B builder.sealed network
B controls.done passed
B controls.done repo
B delivery.override cell
B grade.belt rc
B grade.belt timed_out
B grade.tamper detail
B grade.tamper violations
B label.task capability_class
B label.task taxonomy
B ledger.append clean
B ledger.append disqualified
B ledger.append item
B ledger.append pack
B ledger.append row_hash
B ledger.append trial
B legacy.grade clean
B mine.candidate repo
B mine.done repo
B mine.red baseline_failing
B mine.red cls
B mine.red size
B oracle.mutation.scored oracle_strength
B red.proved item
B red.refused item
B red.start item
B repo.created config
B repo.created github
B review.corrected grade_row_hash
B review.corrected review_id
B review.corrected row_hash
B review.created findings
B review.created grade_row_hash
B review.created mergeable
B review.created minutes
B review.created patch_sha256_reviewed
B review.created review_id
B review.created row_hash
B review.created verdict
B review.probe detail
B review.probe item
B review.refused code
B review.refused envelope_code
B review.refused grade_row_hash
B review.start item
B review.verdict item
B route.decided cell_route
B setup.auto reason
B setup.start path
B signoff.created controls_run_id
B signoff.created controls_verdict
B signoff.created oracle_scored
B signoff.created oracle_strength
B signoff.created oracle_tasks
B signoff.created reviewed_row_hash
B signoff.created route_reason_code
""".splitlines()
    if line.strip()
)
INITIAL_GAPS_SHA256 = "dc44adf2b50d96933388e13e4fe11e177a749f0621950f8365bae97f6687019e"


#: Every gap fixed since ``INITIAL_GAPS`` was written. Fixing a gap moves its line here in
#: the commit that deletes it from the fixture; never remove a line. The fixture must hold
#: exactly ``INITIAL_GAPS - FIXED_GAPS``, so a fixed gap cannot be swapped back in for a
#: later fix even once ``BASELINE_SIZE`` has gone down.
FIXED_GAPS: frozenset[str] = frozenset()


def baseline_problems(
    entries: set[str], fixed: frozenset[str] = FIXED_GAPS, size: int = BASELINE_SIZE
) -> list[str]:
    """Why ``entries`` is not a baseline that only shrank: a line that was never in
    ``INITIAL_GAPS`` (a new gap), a line in ``fixed`` (a fixed gap come back), a line gone
    from the baseline but not recorded in ``fixed``, or a size other than ``size``."""
    problems = [
        f"{e!r} was not a gap when the baseline was written: fix the row or the call"
        for e in sorted(entries - INITIAL_GAPS)
    ]
    problems += [
        f"{e!r} was fixed (it is in FIXED_GAPS) and is a gap again: fix the row or the call"
        for e in sorted(entries & fixed)
    ]
    problems += [
        f"{e!r} is no longer in the baseline: add it to FIXED_GAPS in the same commit"
        for e in sorted(INITIAL_GAPS - fixed - entries)
    ]
    problems += [
        f"{e!r} is in FIXED_GAPS but never was a gap" for e in sorted(fixed - INITIAL_GAPS)
    ]
    if size != len(INITIAL_GAPS - fixed):
        problems.append(
            f"BASELINE_SIZE is {size} but INITIAL_GAPS less FIXED_GAPS holds "
            f"{len(INITIAL_GAPS - fixed)}: they move together"
        )
    n = len(entries)
    if n > size:
        problems.append(
            f"tests/fixtures/event_key_gaps.txt grew to {n} lines (pinned at {size}): "
            "a new gap is fixed in the row or the call, never added to the baseline"
        )
    elif n < size:
        problems.append(
            f"the baseline shrank to {n}: lower BASELINE_SIZE to {n} in the same commit"
        )
    return problems


def test_the_initial_allow_list_is_the_one_first_written() -> None:
    digest = hashlib.sha256("\n".join(sorted(INITIAL_GAPS)).encode()).hexdigest()
    assert digest == INITIAL_GAPS_SHA256, "INITIAL_GAPS is never edited; it may not grow"
    assert len(INITIAL_GAPS) == 79


def test_the_gap_baseline_size_is_pinned_and_only_goes_down() -> None:
    assert baseline_problems(baseline()) == []


def test_a_new_gap_swapped_for_a_fixed_one_is_refused() -> None:
    """A commit that fixes one gap and adds another keeps the size; membership stops it."""
    fixed = sorted(baseline())[0]
    swapped = (baseline() - {fixed}) | {"B build.start brand_new_key"}
    assert len(swapped) == BASELINE_SIZE
    assert baseline_problems(swapped) == [
        "'B build.start brand_new_key' was not a gap when the baseline was written: fix the "
        "row or the call",
        f"{fixed!r} is no longer in the baseline: add it to FIXED_GAPS in the same commit",
    ]
    assert baseline_problems(baseline() - {fixed}) == [
        f"{fixed!r} is no longer in the baseline: add it to FIXED_GAPS in the same commit",
        f"the baseline shrank to {BASELINE_SIZE - 1}: lower BASELINE_SIZE to "
        f"{BASELINE_SIZE - 1} in the same commit",
    ]


def test_a_fixed_gap_cannot_come_back_in_place_of_a_later_fix() -> None:
    """Fix X (record it, lower the size), then fix Y and swap X back: the size matches, every
    line is an initial gap, and X is still refused because it was recorded fixed."""
    x, y = sorted(INITIAL_GAPS)[:2]
    after_x = frozenset({x})
    assert baseline_problems(set(INITIAL_GAPS - after_x), after_x, len(INITIAL_GAPS) - 1) == []
    swapped = set(INITIAL_GAPS - {y})
    assert baseline_problems(swapped, after_x, len(INITIAL_GAPS) - 1) == [
        f"{x!r} was fixed (it is in FIXED_GAPS) and is a gap again: fix the row or the call",
        f"{y!r} is no longer in the baseline: add it to FIXED_GAPS in the same commit",
    ]
    after_y = after_x | {y}
    assert baseline_problems(swapped, after_y, len(INITIAL_GAPS) - 2) == [
        f"{x!r} was fixed (it is in FIXED_GAPS) and is a gap again: fix the row or the call",
        f"tests/fixtures/event_key_gaps.txt grew to {len(INITIAL_GAPS) - 1} lines (pinned at "
        f"{len(INITIAL_GAPS) - 2}): a new gap is fixed in the row or the call, never added to "
        "the baseline",
    ]


def test_the_size_and_the_fixed_list_move_together() -> None:
    assert baseline_problems(set(INITIAL_GAPS), size=len(INITIAL_GAPS) - 1) == [
        f"BASELINE_SIZE is {len(INITIAL_GAPS) - 1} but INITIAL_GAPS less FIXED_GAPS holds "
        f"{len(INITIAL_GAPS)}: they move together",
        f"tests/fixtures/event_key_gaps.txt grew to {len(INITIAL_GAPS)} lines (pinned at "
        f"{len(INITIAL_GAPS) - 1}): a new gap is fixed in the row or the call, never added to "
        "the baseline",
    ]


# -- the walker on planted code and planted rows ------------------------------------------


def _sites(src: str) -> dict[str, list[Site]]:
    out: dict[str, list[Site]] = {}
    for s in sites_of(src, "planted.py"):
        out.setdefault(s.action, []).append(s)
    return out


HELPER = "def _emit(on_event, action, **payload):\n    on_event(action, payload)\n"


def test_a_helper_call_is_served_with_the_lift_applied() -> None:
    src = HELPER + "def f(on_event, t):\n    _emit(on_event, 'x.y', task=t, error='e', foo=1)\n"
    [s] = _sites(src)["x.y"]
    assert s.payload == {"foo"} and not s.open


def test_a_key_named_like_an_envelope_field_the_emitter_keeps_stays_in_payload() -> None:
    # ``repo`` is an envelope name but not an argument of Emitter.emit: on_event keeps it
    src = HELPER + "def f(on_event):\n    _emit(on_event, 'x.y', repo='r', duration_ms=3)\n"
    [s] = _sites(src)["x.y"]
    assert s.payload == {"repo"}


def test_an_emitter_call_keeps_task_in_payload() -> None:
    # Emitter.emit does not lift: ``task=`` there is a payload key
    src = "def f(emitter):\n    emitter.emit('system', 'x.y', task='t', task_id='t', a=1)\n"
    [s] = _sites(src)["x.y"]
    assert s.payload == {"task", "a"}


def test_a_splat_makes_the_site_open() -> None:
    src = HELPER + "def f(on_event, r):\n    _emit(on_event, 'x.y', **r)\n"
    assert _sites(src)["x.y"][0].open


def test_an_explicit_payload_keeps_every_key_as_given() -> None:
    src = (
        "def f(s):\n    append_event(s, action='x.y', status='e', payload={'status': 1, 'a': 2})\n"
    )
    [s] = _sites(src)["x.y"]
    assert s.payload == {"status", "a"}


def test_a_renamed_key_is_reported_both_ways() -> None:
    src = HELPER + "def f(on_event):\n    _emit(on_event, 'x.y', item='i')\n"
    got = row_gaps("`x.y`", "`item_ref`", _sites(src))
    assert got == {"A x.y item_ref", "B x.y item"}


def test_an_open_site_never_proves_a_documented_key_a_ghost() -> None:
    src = HELPER + "def f(on_event, r):\n    _emit(on_event, 'x.y', **r)\n"
    assert row_gaps("`x.y`", "`item_ref`", _sites(src)) == set()


def test_a_value_or_nested_key_in_parentheses_is_not_a_key() -> None:
    assert top_keys("`a`, `b` (`ok` / `bad`) — the `c`") == {"a", "b"}
    assert top_keys("`task_id` on the envelope, `d`") == {"d"}
