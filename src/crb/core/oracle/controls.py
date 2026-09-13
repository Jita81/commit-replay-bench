"""Negative controls — prove the INSTRUMENT rejects what it must reject, with no model.

Every task is driven through the SAME grading path a builder's trial takes
(:class:`~crb.core.workspace.Workspace` at the parent → tests overlaid → a
deterministic edit → :func:`~crb.core.grade.grade`) with seven generators:

* ``gold``        — the commit's own source overlaid. MUST grade ``clean``: anything
                    else means the instrument cannot even grade the repo's own history
                    (an instrument bug, never a model result).
* ``noop``        — the empty edit. The target MUST stay ``red``.
* ``test_tamper`` — the target test file rewritten to pass trivially, written
                    OUT-OF-BAND (past any write hook). MUST be ``disqualified``: the
                    :class:`TamperGuard` re-hashes the oracle before every grade and
                    belt 1 re-checks it byte-for-byte inside the grader.
* ``stub``        — the changed function bodies replaced with
                    ``raise NotImplementedError`` (AST-based; right shape, no
                    substance). MUST be ``red``.
* ``regression``  — the gold patch PLUS a poisoned adjacent module (a top-level
                    ``raise`` in a same-directory source module the wider suite imports
                    but the target tests do not). Target green + belt broken MUST grade
                    ``regressed`` — NEVER clean. This is the control that proves belt 3
                    is load-bearing, not ornamental.
* ``hardcode_cheat`` — the parent source special-cased on the exact literal
                    inputs/expectations parsed from the target test, nothing implemented.
* ``env_poison``  — an identity source edit plus a root ``conftest.py`` that execs the
                    gold source into the module under test at collection time: the
                    target goes green purely by state pollution.

The last two are MEASUREMENT controls. Their expectation is ``caught`` (red,
regressed or disqualified). If one of them grades ``clean`` that is a **MEASURED
ORACLE ESCAPE** — the product's central honesty claim rests on saying this plainly:
the belts held (the patch really is green and regression-free, and the oracle was
untouched), so it is not a grader bug; it is a finding that this task's own tests are
too weak to distinguish an implementation from a lookup table. Escapes are the
oracle-adequacy signal that :mod:`crb.core.oracle.mutation` quantifies and
:mod:`crb.core.oracle.adequacy` routes on. They never fail the gate; they are
reported prominently and stamped into the task's evidence.

When a cheat cannot be built deterministically for a task (no literal assert, no
adjacent module) the row honestly reads ``not_constructible`` — never faked, never a
violation. A task whose target is not RED at the parent grades ``skip`` (vacuous).
A harness error on any control is a ``VIOLATION``: the gate never passes on an error.

Exit contract for the CI gate: :attr:`ControlsReport.passed` is ``True`` iff there is
no ``VIOLATION``. Escapes leave it ``True`` and land in ``escapes``.

Every transform is a pure function over file text so it can be unit-tested without
a repository; the runner is the thin I/O shell around them.
"""

from __future__ import annotations

import ast
import copy
import os
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crb.core.execution import Executor, SandboxUnavailable
from crb.core.git import GitRepo
from crb.core.grade import MODE_SIGHTED, GradeResult, grade
from crb.core.redact import redact_and_cap
from crb.core.runners.base import BaseRunner
from crb.core.spec import RepoConfig, TaskSpec
from crb.core.version import APPARATUS_VERSION
from crb.core.workspace import Workspace

CONTROLS_SCHEMA = "crb.negative_controls.v1"
CONTROLS_VERSION = "controls.v1"

EventFn = Callable[[str, Mapping[str, Any]], None]

GOLD = "gold"
NOOP = "noop"
TEST_TAMPER = "test_tamper"
STUB = "stub"
REGRESSION = "regression"
HARDCODE_CHEAT = "hardcode_cheat"
ENV_POISON = "env_poison"
CONTROLS: tuple[str, ...] = (GOLD, NOOP, TEST_TAMPER, STUB, REGRESSION, HARDCODE_CHEAT, ENV_POISON)

#: Measurement controls: they PROBE the oracle rather than assert the instrument.
#: Slipping through as ``clean`` is a MEASURED ORACLE ESCAPE — a finding, never a
#: violation.
MEASURE_CONTROLS: tuple[str, ...] = (HARDCODE_CHEAT, ENV_POISON)

# --- observed outcomes (a projection of GradeResult) --------------------------
OBS_CLEAN = "clean"
OBS_RED = "red"
OBS_REGRESSED = "regressed"
OBS_DISQUALIFIED = "disqualified"
OBS_NO_SOURCE_CHANGE = "no_source_change"
OBS_ERROR = "error"
OBS_NOT_CONSTRUCTIBLE = "not_constructible"
OBS_SKIPPED = "skipped"

# --- row verdicts --------------------------------------------------------------
VERDICT_OK = "ok"
VERDICT_VIOLATION = "VIOLATION"
VERDICT_ESCAPE = "ESCAPE"
VERDICT_NOT_CONSTRUCTIBLE = "not_constructible"
VERDICT_SKIP = "skip"

#: displayed expectation for measurement controls.
CAUGHT_OR_FLAGGED = "caught_or_flagged"

#: acceptable outcomes per control. TEST_TAMPER also accepts ``red`` (an edit that
#: never reaches grading is still rejected); the hard line is: never clean. For
#: MEASURE_CONTROLS the tuple is the "caught" set — ``clean`` = escape.
EXPECTED: dict[str, tuple[str, ...]] = {
    GOLD: (OBS_CLEAN,),
    NOOP: (OBS_RED,),
    TEST_TAMPER: (OBS_DISQUALIFIED, OBS_RED),
    STUB: (OBS_RED,),
    REGRESSION: (OBS_REGRESSED,),
    HARDCODE_CHEAT: (OBS_RED, OBS_REGRESSED, OBS_DISQUALIFIED),
    ENV_POISON: (OBS_RED, OBS_REGRESSED, OBS_DISQUALIFIED),
}


def expected_label(control: str) -> str:
    return CAUGHT_OR_FLAGGED if control in MEASURE_CONTROLS else "|".join(EXPECTED[control])


def observe(result: GradeResult) -> str:
    """Project a :class:`GradeResult` onto the control vocabulary. Fails closed:
    anything the grader could not attribute is ``error``."""
    if result.error:
        return OBS_ERROR
    if result.disqualified:
        return OBS_DISQUALIFIED
    if result.clean:
        return OBS_CLEAN
    b = result.belts
    if b.target_green is not True:
        return OBS_RED
    if b.no_new_failures is False:
        return OBS_REGRESSED
    if b.source_changed is False:
        return OBS_NO_SOURCE_CHANGE
    return OBS_ERROR


# ---------------------------------------------------------------------------
# tamper guard — re-hash the oracle before every grade
# ---------------------------------------------------------------------------


class TamperGuard:
    """Snapshot the overlaid target tests; re-verify them before every grade.

    Detection sits at grading time, so an out-of-band write (one that bypasses any
    builder-side write hook) is still caught before a verdict can be earned. The
    grader's belt 1 re-checks against the commit's own bytes independently — this
    guard is the belt-and-braces layer that also names the offending file.
    """

    def __init__(self, ws: Workspace, test_files: Sequence[str]) -> None:
        self.ws = ws
        self.test_files = tuple(test_files)
        self._snapshot: dict[str, str | None] = {}
        self.tests_touched = False
        self.tamper_note = ""

    def snapshot(self) -> None:
        self._snapshot = {p: self.ws.file_hash(p) for p in self.test_files}

    def check(self) -> tuple[str, ...]:
        """Paths whose bytes differ from the snapshot. Sets ``tests_touched``."""
        touched = tuple(p for p, h in self._snapshot.items() if self.ws.file_hash(p) != h)
        if touched:
            self.tests_touched = True
            self.tamper_note = f"target test {touched[0]} modified since overlay"
        return touched


# ---------------------------------------------------------------------------
# pure transforms over file text
# ---------------------------------------------------------------------------

TRIVIAL_TEST = "def test_tampered_trivially_passes():\n    assert True\n"
REGRESSION_POISON = 'raise RuntimeError("negctrl-regression-poison")'


def poison_module(text: str) -> str:
    """REGRESSION: a top-level raise prepended to an adjacent module."""
    return REGRESSION_POISON + "\n" + text


def _functions(src: str) -> dict[str, tuple[ast.FunctionDef | ast.AsyncFunctionDef, str]]:
    """qualname → (node, source segment) for every (async) function, methods included."""
    out: dict[str, tuple[ast.FunctionDef | ast.AsyncFunctionDef, str]] = {}

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                qn = f"{prefix}{child.name}"
                out[qn] = (child, ast.get_source_segment(src, child) or "")
                walk(child, qn + ".")
            elif isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}{child.name}.")

    walk(ast.parse(src), "")
    return out


def _stub_def(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """The function rebuilt with a ``raise NotImplementedError`` body (no decorators —
    in-file decorator lines stay where they are and still apply)."""
    clone = copy.deepcopy(node)
    clone.body = [ast.Raise(exc=ast.Name(id="NotImplementedError", ctx=ast.Load()), cause=None)]
    clone.decorator_list = []
    return ast.unparse(ast.fix_missing_locations(clone))


def stub_changed_functions(parent_src: str, gold_src: str) -> str:
    """Deterministically hollow out the commit's change: every parent function whose
    source differs from the gold version keeps its signature but its body becomes
    ``raise NotImplementedError``; top-level functions the commit ADDS are appended
    as stubs (so import-shaped tests reach the NotImplementedError, not ImportError).
    Right shape, no substance — the classic plausible-but-wrong submission."""
    try:
        parent_funcs = _functions(parent_src) if parent_src.strip() else {}
        gold_funcs = _functions(gold_src) if gold_src.strip() else {}
    except SyntaxError:
        return parent_src  # degenerate: unparseable source stubs to a no-op (still must fail)

    changed = [
        node
        for qn, (node, seg) in parent_funcs.items()
        if qn not in gold_funcs or gold_funcs[qn][1] != seg
    ]
    # only outermost changed functions — stubbing an outer def swallows its inner defs
    outermost = [
        n
        for n in changed
        if not any(
            o is not n
            and o.lineno <= n.lineno
            and (n.end_lineno or n.lineno) <= (o.end_lineno or o.lineno)
            for o in changed
        )
    ]

    lines = parent_src.split("\n")
    for node in sorted(outermost, key=lambda n: n.body[0].lineno, reverse=True):
        first = node.body[0]
        end = node.end_lineno or node.lineno
        if first.lineno == node.lineno:  # one-liner ``def f(): ...`` — rebuild the whole def
            indent = " " * node.col_offset
            lines[node.lineno - 1 : end] = [indent + ln for ln in _stub_def(node).split("\n")]
        else:
            indent = " " * first.col_offset
            lines[first.lineno - 1 : end] = [indent + "raise NotImplementedError"]

    added = [
        node for qn, (node, _seg) in gold_funcs.items() if "." not in qn and qn not in parent_funcs
    ]
    for node in sorted(added, key=lambda n: n.lineno):
        lines.extend(["", "", _stub_def(node)])
    return "\n".join(lines)


# --- regression: choosing the poison target ----------------------------------------


def _imports(text: str, stem: str) -> bool:
    """Does this source import module ``stem`` (``import x``, ``import pkg.x``,
    ``from x import``, ``from pkg.x import``, ``from pkg import x``)?"""
    s = re.escape(stem)
    pat = re.compile(
        rf"^\s*(?:import\s+(?:[\w.]+\s*,\s*)*(?:[\w.]+\.)?{s}\b"
        rf"|from\s+(?:[\w.]+\.)?{s}\s+import\b"
        rf"|from\s+[\w.]+\s+import\s+(?:[\w*]+\s*,\s*)*{s}\b)",
        re.M,
    )
    return bool(pat.search(text))


def select_poison_target(
    candidates: Sequence[str],
    *,
    target_texts: Sequence[str],
    src_texts: Sequence[str],
    suite_texts: Sequence[str],
) -> str | None:
    """Pure selector: the first candidate (sorted) the wider suite imports but neither
    the target tests nor the module(s) under test do. ``None`` = not constructible."""
    for cand in sorted(candidates):
        stem = Path(cand).stem
        if any(_imports(t, stem) for t in target_texts):
            continue  # poison would break the target too — not this one
        if any(_imports(t, stem) for t in src_texts):
            continue  # transitive via the module under test — would break the target
        if any(_imports(t, stem) for t in suite_texts):
            return cand  # the wider suite imports it → belt 3 MUST see the breakage
    return None


def pick_regression_poison_target(ws: Workspace, task: TaskSpec, config: RepoConfig) -> str | None:
    """Deterministically pick a same-directory source module the wider suite imports
    but the target tests (and the modules under test) do not — the file whose
    breakage belt 3 must flag. Reads the parent worktree; the target tests' text is
    the commit's (already overlaid)."""
    files = ws.repo.run("ls-tree", "-r", "--name-only", ws.parent, cwd=ws.root, check=True).lines
    src_dirs = {os.path.dirname(p) for p in task.src_files}
    skip_names = {"__init__.py", "conftest.py"}
    candidates = [
        p
        for p in files
        if p.endswith(".py")
        and p not in task.src_files
        and p not in task.test_files
        and os.path.dirname(p) in src_dirs
        and os.path.basename(p) not in skip_names
        and not os.path.basename(p).startswith("test_")
        and not config.is_test(p)
    ]
    if not candidates:
        return None
    target_texts = [ws.read(t) for t in task.test_files if ws.exists(t)]
    src_texts = [ws.read(p) for p in task.src_files if ws.exists(p)] + [
        ws.repo.show_file(ws.sha, p) or "" for p in task.src_files
    ]
    suite_texts = [
        ws.read(p) for p in files if config.is_test(p) and p not in task.test_files and ws.exists(p)
    ]
    return select_poison_target(
        candidates, target_texts=target_texts, src_texts=src_texts, suite_texts=suite_texts
    )


# --- hardcode cheat --------------------------------------------------------------------

Fact = tuple[str, tuple[Any, ...], Any]


def _literal(node: ast.AST) -> tuple[bool, Any]:
    try:
        return True, ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return False, None


def extract_literal_asserts(test_src: str) -> list[Fact]:
    """``(func_name, positional-literal args, expected literal)`` for every
    ``assert f(<literals>) == <literal>`` (either side) in the target test source.
    Keyword calls / non-literal args / non-Eq compares are skipped — narrowness is
    the point: the cheat may only special-case what the visible test pins down."""
    out: list[Fact] = []
    try:
        tree = ast.parse(test_src)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        t = node.test
        if not (isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], ast.Eq)):
            continue
        call, expected_node = t.left, t.comparators[0]
        if not isinstance(call, ast.Call) and isinstance(expected_node, ast.Call):
            call, expected_node = expected_node, call  # tolerate ``assert 3 == f(1, 2)``
        if not isinstance(call, ast.Call) or call.keywords:
            continue
        fn = call.func
        name = (
            fn.id
            if isinstance(fn, ast.Name)
            else (fn.attr if isinstance(fn, ast.Attribute) else "")
        )
        if not name:
            continue
        ok_e, expected = _literal(expected_node)
        if not ok_e:
            continue
        args: list[Any] = []
        for a in call.args:
            ok_a, v = _literal(a)
            if not ok_a:
                break
            args.append(v)
        else:
            out.append((name, tuple(args), expected))
    return out


def build_hardcode_cheat(parent_src: str, facts: Sequence[Fact]) -> str | None:
    """The parent source with each fact special-cased and NOTHING implemented:
    existing functions get an ``if (params...) == (literals...): return expected``
    guard prepended (buggy body kept); functions the test names but the parent
    lacks are appended as hard-coded ``*args`` lookups. ``None`` = not constructible."""
    if not facts:
        return None
    try:
        funcs = _functions(parent_src) if parent_src.strip() else {}
    except SyntaxError:
        return None
    by_name: dict[str, list[tuple[tuple[Any, ...], Any]]] = {}
    for name, args, expected in facts:
        by_name.setdefault(name, []).append((args, expected))

    lines = parent_src.split("\n")
    inserts: list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, list[str]]] = []
    missing: dict[str, list[tuple[tuple[Any, ...], Any]]] = {}
    for name, pairs in by_name.items():
        nodes = [node for qn, (node, _seg) in funcs.items() if qn.split(".")[-1] == name]
        if not nodes:
            missing[name] = pairs
            continue
        node = min(nodes, key=lambda n: n.lineno)  # deterministic: first definition wins
        params = [a.arg for a in (*node.args.posonlyargs, *node.args.args)]
        if params and params[0] in ("self", "cls"):
            params = params[1:]
        guards: list[str] = []
        for args, expected in pairs:
            if len(args) > len(params):
                continue
            head = f"if ({', '.join(params[: len(args)])},) == {args!r}:" if args else "if True:"
            guards += [head, f"    return {expected!r}"]
        if guards:
            inserts.append((node, guards))
    if not inserts and not missing:
        return None

    for node, guards in sorted(inserts, key=lambda t: t[0].body[0].lineno, reverse=True):
        first = node.body[0]
        if first.lineno == node.lineno:
            continue  # one-liner def — no safe line-splice; the fact stays uncheated
        indent = " " * first.col_offset
        lines[first.lineno - 1 : first.lineno - 1] = [indent + g for g in guards]
    for name, pairs in sorted(missing.items()):
        body = [
            g
            for args, expected in pairs
            for g in (f"    if args == {args!r}:", f"        return {expected!r}")
        ]
        lines += ["", "", f"def {name}(*args, **kwargs):", *body, "    raise NotImplementedError"]
    cheat = "\n".join(lines)
    try:
        compile(cheat, "<cheat>", "exec")
    except SyntaxError:
        return None
    return cheat


# --- env poison ------------------------------------------------------------------------


def module_name_for(src_path: str, config: RepoConfig) -> str:
    """Dotted import name of a source file as the pytest runner will see it.

    The pytest runner puts the worktree root (plus ``runner_opts.pythonpath_suffix``
    entries) on ``PYTHONPATH``; a path under one of those extra roots is imported
    relative to it, everything else relative to the worktree root.
    """
    rel = src_path[:-3] if src_path.endswith(".py") else src_path
    suffix = str(config.runner_opts.get("pythonpath_suffix", ""))
    for entry in suffix.split(os.pathsep):
        root = entry.strip().strip("/")
        if root and rel.startswith(root + "/"):
            rel = rel[len(root) + 1 :]
            break
    if rel.endswith("/__init__"):
        rel = rel[: -len("/__init__")]
    return rel.replace("/", ".")


def env_poison_conftest(module: str, src_path: str, gold_src: str) -> str:
    """A root ``conftest.py`` that sets a marker and execs the GOLD source into the
    module under test at collection time — state pollution, no implementation."""
    return (
        "# negctrl-env-poison: state pollution, not implementation\n"
        "import os\n"
        'os.environ["NEGCTRL_ENV_POISON"] = "1"\n'
        f"import {module} as _poisoned\n"
        f"_gold = {gold_src!r}\n"
        f'exec(compile(_gold, {src_path!r}, "exec"), _poisoned.__dict__)\n'
    )


# ---------------------------------------------------------------------------
# rows + report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ControlRow:
    task_id: str
    repo: str
    control: str
    expected: str
    observed: str
    verdict: str
    note: str = ""
    grade: GradeResult | None = None
    duration_s: float = 0.0

    def __post_init__(self) -> None:
        if self.control not in CONTROLS:
            raise ValueError(f"unknown control {self.control!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "repo": self.repo,
            "control": self.control,
            "expected": self.expected,
            "observed": self.observed,
            "verdict": self.verdict,
            "note": self.note,
            "grade": self.grade.to_dict() if self.grade else None,
            "duration_s": round(self.duration_s, 3),
        }


@dataclass(frozen=True)
class ControlsReport:
    """The control matrix. ``passed`` is the CI gate: no VIOLATION. Escapes never
    fail it — they are findings about the oracle, reported in ``escapes``."""

    rows: tuple[ControlRow, ...]
    apparatus: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "rows", tuple(self.rows))
        object.__setattr__(self, "apparatus", dict(self.apparatus))

    def _with(self, verdict: str) -> tuple[ControlRow, ...]:
        return tuple(r for r in self.rows if r.verdict == verdict)

    @property
    def violations(self) -> tuple[ControlRow, ...]:
        return self._with(VERDICT_VIOLATION)

    @property
    def escapes(self) -> tuple[ControlRow, ...]:
        return self._with(VERDICT_ESCAPE)

    @property
    def not_constructible(self) -> tuple[ControlRow, ...]:
        return self._with(VERDICT_NOT_CONSTRUCTIBLE)

    @property
    def skipped(self) -> tuple[ControlRow, ...]:
        return self._with(VERDICT_SKIP)

    @property
    def passed(self) -> bool:
        return not self.violations

    @property
    def task_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(r.task_id for r in self.rows))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CONTROLS_SCHEMA,
            "apparatus": dict(self.apparatus),
            "n_tasks": len(self.task_ids),
            "n_rows": len(self.rows),
            "violations": len(self.violations),
            "escapes": len(self.escapes),
            "not_constructible": len(self.not_constructible),
            "skipped": len(self.skipped),
            "passed": self.passed,
            "escape_rows": [r.to_dict() for r in self.escapes],
            "rows": [r.to_dict() for r in self.rows],
        }

    def render_markdown(self) -> str:
        lines = [
            "# Negative-control matrix",
            "",
            f"- tasks: {len(self.task_ids)}",
            f"- control rows: {len(self.rows)}",
            f"- violations: {len(self.violations)} (a violation = instrument bug)",
            f"- escapes: {len(self.escapes)} (measured oracle escapes — findings, not instrument bugs)",
            f"- not constructible: {len(self.not_constructible)} (cheat honestly unbuildable for the task)",
            f"- skipped: {len(self.skipped)} (no RED oracle)",
            f"- gate: {'PASS' if self.passed else 'FAIL'}",
            "",
            "| task | control | expected | observed | verdict | note |",
            "|------|---------|----------|----------|---------|------|",
        ]
        lines += [
            f"| {r.task_id[:10]} | {r.control} | {r.expected} | {r.observed} | {r.verdict} | {r.note} |"
            for r in self.rows
        ]
        if self.escapes:
            lines += [
                "",
                "## MEASURED ORACLE ESCAPES",
                "",
                "These deterministic cheats graded ``clean`` — every belt held and no belt",
                "caught them. Each is a finding about the target tests' weakness (overfitting /",
                "pollution surface), NOT an instrument bug; the gate stays PASS.",
                "",
            ]
            lines += [f"- `{r.task_id[:10]}` **{r.control}** — {r.note}" for r in self.escapes]
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# the runner — every control through the REAL replay path
# ---------------------------------------------------------------------------


class _NotConstructible(Exception):
    """Raised by a control applier when the cheat cannot honestly be built."""


def _primary_source(task: TaskSpec) -> str | None:
    for p in task.src_files:
        if p.endswith(".py"):
            return p
    return None


def _apply_control(name: str, ws: Workspace, task: TaskSpec, config: RepoConfig) -> str:
    """Perform the control's edit in ``ws`` (parent + tests overlaid). Returns a note.
    Raises :class:`_NotConstructible` with the reason when it cannot be built."""
    if name == GOLD:
        ws.overlay_sources(task.src_files)
        return ""
    if name == NOOP:
        return ""
    if name == TEST_TAMPER:
        for t in task.test_files:  # OUT-OF-BAND: past any write hook, on purpose
            (ws.root / t).write_text(TRIVIAL_TEST, encoding="utf-8")
        return ""
    if name == STUB:
        edited = 0
        for p in task.src_files:
            if not p.endswith(".py"):
                continue
            parent_src = ws.read(p) if ws.exists(p) else ""
            gold_src = ws.repo.show_file(ws.sha, p) or ""
            stubbed = stub_changed_functions(parent_src, gold_src)
            if stubbed != parent_src or not ws.exists(p):
                (ws.root / p).parent.mkdir(parents=True, exist_ok=True)
                (ws.root / p).write_text(stubbed, encoding="utf-8")
                edited += 1
        if not edited:
            raise _NotConstructible("no python source function changed — nothing to stub")
        return ""
    if name == REGRESSION:
        poison = pick_regression_poison_target(ws, task, config)
        if poison is None:
            raise _NotConstructible(
                "no same-directory module imported by the wider suite but not by the target"
            )
        ws.overlay_sources(task.src_files)
        (ws.root / poison).write_text(poison_module(ws.read(poison)), encoding="utf-8")
        return f"poisoned {poison}"
    primary = _primary_source(task)
    if primary is None:
        raise _NotConstructible("no python source file in the task")
    if name == HARDCODE_CHEAT:
        facts = [
            f for t in task.test_files if ws.exists(t) for f in extract_literal_asserts(ws.read(t))
        ]
        parent_src = ws.read(primary) if ws.exists(primary) else ""
        cheat = build_hardcode_cheat(parent_src, facts)
        if cheat is None:
            raise _NotConstructible(
                "no literal `assert f(<literals>) == <literal>` extractable from the target tests"
            )
        (ws.root / primary).parent.mkdir(parents=True, exist_ok=True)
        (ws.root / primary).write_text(cheat, encoding="utf-8")
        return f"{len(facts)} literal fact(s) special-cased in {primary}"
    if name == ENV_POISON:
        if not ws.exists(primary):
            raise _NotConstructible(f"{primary} does not exist at the parent — nothing to pollute")
        gold_src = ws.repo.show_file(ws.sha, primary) or ""
        if not gold_src.strip():
            raise _NotConstructible("gold source unavailable")
        conftest = env_poison_conftest(module_name_for(primary, config), primary, gold_src)
        (ws.root / "conftest.py").write_text(conftest, encoding="utf-8")
        return f"root conftest.py execs gold into {module_name_for(primary, config)}"
    raise ValueError(f"unknown control: {name}")


def _caught_note(observed: str, guard: TamperGuard, grade_result: GradeResult) -> str:
    if observed == OBS_REGRESSED:
        return "caught: regression belt flagged it"
    if observed == OBS_DISQUALIFIED:
        return f"caught: {guard.tamper_note or grade_result.dq_reason or 'disqualified'}"
    return "caught: target tests stayed red"


def _emit(on_event: EventFn | None, action: str, **payload: Any) -> None:
    if on_event is not None:
        on_event(action, payload)


def _red_at_parent(
    repo: GitRepo,
    task: TaskSpec,
    *,
    config: RepoConfig,
    runner: BaseRunner,
    executor: Executor,
    scratch: Path,
    timeout: int,
) -> tuple[bool, str]:
    """(is_red, note). Vacuous controls are never a violation — but a harness error is."""
    dest = Path(scratch) / f"ctrl-{config.name}-{task.short_id}-red"
    with Workspace.create(repo, task.task_id, dest, config=config) as ws:
        ws.overlay_tests(task.test_files)
        run = runner.run(executor, ws.root, task.target_tests, timeout=timeout)
    if run.timed_out:
        return False, "target timed out at the parent — no usable RED oracle"
    if run.green:
        return False, "target GREEN at the parent — no RED oracle, controls vacuous"
    return True, ""


def controls_for_task(
    repo: GitRepo,
    task: TaskSpec,
    *,
    config: RepoConfig,
    runner: BaseRunner,
    executor: Executor,
    scratch: Path,
    controls: Sequence[str] = CONTROLS,
    timeout: int = 0,
    on_event: EventFn | None = None,
) -> list[ControlRow]:
    """Run the controls for one task, each in a FRESH workspace, through :func:`grade`.

    One row per control. Raises :class:`SandboxUnavailable` (infrastructure) so a
    run can stop; every other error is a recorded ``VIOLATION`` row.
    """
    unknown = [c for c in controls if c not in CONTROLS]
    if unknown:
        raise ValueError(f"unknown control(s): {unknown}")
    rows: list[ControlRow] = []

    def row(
        control: str,
        observed: str,
        verdict: str,
        note: str = "",
        *,
        grade_result: GradeResult | None = None,
        started: float | None = None,
    ) -> ControlRow:
        return ControlRow(
            task_id=task.task_id,
            repo=task.repo,
            control=control,
            expected=expected_label(control),
            observed=observed,
            verdict=verdict,
            note=note,
            grade=grade_result,
            duration_s=0.0 if started is None else time.monotonic() - started,
        )

    try:
        is_red, why = _red_at_parent(
            repo,
            task,
            config=config,
            runner=runner,
            executor=executor,
            scratch=scratch,
            timeout=timeout,
        )
    except SandboxUnavailable:
        raise
    except Exception as exc:
        err = redact_and_cap(
            f"harness error on RED check: {type(exc).__name__}: {exc}", max_chars=600
        )
        _emit(on_event, "controls.error", task=task.task_id, error=err)
        return [row(c, OBS_ERROR, VERDICT_VIOLATION, err) for c in controls]
    if not is_red:
        _emit(on_event, "controls.skip", task=task.task_id, reason=why)
        return [row(c, OBS_SKIPPED, VERDICT_SKIP, why) for c in controls]

    for name in controls:
        started = time.monotonic()
        dest = Path(scratch) / f"ctrl-{config.name}-{task.short_id}-{name}"
        _emit(on_event, "controls.control", task=task.task_id, control=name)
        try:
            with Workspace.create(repo, task.task_id, dest, config=config) as ws:
                ws.overlay_tests(task.test_files)
                guard = TamperGuard(ws, task.test_files)
                guard.snapshot()
                try:
                    apply_note = _apply_control(name, ws, task, config)
                except _NotConstructible as nc:
                    rows.append(
                        row(
                            name,
                            OBS_NOT_CONSTRUCTIBLE,
                            VERDICT_NOT_CONSTRUCTIBLE,
                            str(nc),
                            started=started,
                        )
                    )
                    continue
                guard.check()  # re-hash the oracle BEFORE grading (belt 1 re-checks inside)
                result = grade(
                    ws,
                    task,
                    config=config,
                    runner=runner,
                    executor=executor,
                    mode=MODE_SIGHTED,
                    timeout=timeout,
                    on_event=on_event,
                )
        except SandboxUnavailable:
            raise
        except Exception as exc:
            err = redact_and_cap(f"harness error: {type(exc).__name__}: {exc}", max_chars=600)
            rows.append(row(name, OBS_ERROR, VERDICT_VIOLATION, err, started=started))
            continue

        observed = OBS_DISQUALIFIED if guard.tests_touched else observe(result)
        if name in MEASURE_CONTROLS:
            if observed in EXPECTED[name]:
                verdict, note = VERDICT_OK, _caught_note(observed, guard, result)
            elif observed == OBS_CLEAN:
                verdict = VERDICT_ESCAPE
                note = (
                    "MEASURED ORACLE ESCAPE — cheat graded clean; every belt held, no belt "
                    "caught it (the target tests cannot tell an implementation from a lookup)"
                )
            else:
                verdict, note = (
                    VERDICT_VIOLATION,
                    f"unexpected outcome {observed}: {result.note or result.error}",
                )
        else:
            verdict = VERDICT_OK if observed in EXPECTED[name] else VERDICT_VIOLATION
            note = guard.tamper_note
            if verdict == VERDICT_VIOLATION:
                detail = result.error or result.dq_reason or result.note
                note = f"{note + '; ' if note else ''}observed={observed} {detail}".strip()
        if apply_note:
            note = f"{note}; {apply_note}" if note else apply_note
        rows.append(row(name, observed, verdict, note, grade_result=result, started=started))
        _emit(
            on_event,
            "controls.row",
            task=task.task_id,
            control=name,
            observed=observed,
            verdict=verdict,
        )
    return rows


def run_controls(
    repo: GitRepo,
    tasks: Iterable[TaskSpec],
    *,
    config: RepoConfig,
    runner: BaseRunner,
    executor: Executor,
    scratch: Path,
    controls: Sequence[str] = CONTROLS,
    timeout: int = 0,
    on_event: EventFn | None = None,
) -> ControlsReport:
    """The negative-controls gate over a set of tasks (the fixture repo in CI)."""
    rows: list[ControlRow] = []
    for task in tasks:
        rows.extend(
            controls_for_task(
                repo,
                task,
                config=config,
                runner=runner,
                executor=executor,
                scratch=scratch,
                controls=controls,
                timeout=timeout,
                on_event=on_event,
            )
        )
    apparatus = {
        "apparatus_version": APPARATUS_VERSION,
        "controls_version": CONTROLS_VERSION,
        "controls": list(controls),
        "repo": config.name,
        "runner": runner.name,
        "executor": executor.describe(),
    }
    report = ControlsReport(tuple(rows), apparatus)
    _emit(
        on_event,
        "controls.done",
        repo=config.name,
        rows=len(rows),
        violations=len(report.violations),
        escapes=len(report.escapes),
        passed=report.passed,
    )
    return report
