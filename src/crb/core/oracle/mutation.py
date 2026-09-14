"""Mutation oracle-strength scorer — attack oracle adequacy DETERMINISTICALLY (no model).

The bench trusts each repository's own tests as the held-out oracle, but roughly a
quarter of real suites are too weak to catch a wrong patch — the weak-oracle risk
that threatens false-Q1 = 0 from the *semantic* side (the belts are mechanical; they
cannot see a green-but-wrong patch). This module measures that weakness directly:
with the GOLD patch applied (target tests GREEN), it plants small deterministic
AST-level faults ("mutants") confined to the gold patch's changed lines/functions
and re-runs the task's TARGET tests only.

* a mutant the tests turn RED on is **killed** — the oracle sees that fault class;
* a mutant the tests stay GREEN on has **escaped** — a proven oracle blind spot.

``oracle_strength = killed / total`` per task, aggregated per (class × size) cell.
Every escaped mutant is reported WITH its diff — the blind-spot catalogue is the
prevention artifact (each escape names a missing assertion, deterministically).

Honesty properties (all correct-by-construction, none advisory)
---------------------------------------------------------------
* **No randomness anywhere.** Candidates are collected in AST source order and sorted
  on ``(line, col, operator-rank, description)``; two runs on the same input are
  byte-identical. ``max_mutants`` truncates a stable PREFIX.
* **Every mutant compiles — or is excluded.** A syntactically broken mutant would be
  "killed" by a collection error, dishonestly inflating strength. The Python AST
  mutator drops non-compiling candidates before they are counted; the text mutators
  cannot see types, so a mutant the TOOLCHAIN rejects (a build failure with no test
  id attributed — the runner's ``parse_error`` on a non-zero exit) is recorded as
  ``uncompilable`` and excluded from the denominator, never counted as a kill.
* **Mutants never touch the oracle.** A test file among the mutation targets is
  refused outright (mutating the oracle is self-grading), and the untouched test
  bytes are what belt 1 checks anyway.
* **A RED baseline is not scoreable.** A gold state that fails its own target tests
  yields ``oracle_strength=None`` — never averaged in as strength.
* **A harness error is neither a kill nor an escape.** An executor/runner exception
  on a mutant is recorded as an *error* outcome and excluded from the denominator;
  a sandbox failure propagates. A **timeout** IS a kill: the tests did not pass
  with the fault present (the fault was observable; CI would be red) — it is
  recorded as ``timed_out`` so a reader can recompute without it.
* **The file under mutation is restored byte-exact** — after every mutant and again
  in a ``finally`` — and the restore is verified by hash. Each version is written
  with a distinct integer mtime that is also newer than wall-clock, so neither a
  stale ``.pyc`` (equality-checked) nor an mtime-ordered build cache (Maven, cargo)
  can ever grade the wrong bytes.

Measurement-only: nothing here touches a verdict. The number it produces is what
:mod:`crb.core.oracle.adequacy` turns into a routing consequence, and what
``GradeRow.oracle_strength`` carries into the ledger.

Language support is a small protocol (:class:`~crb.core.oracle.mutant.Mutator`):
Python uses the AST mutator here (``family="ast"``); Go, JavaScript/TypeScript,
Java/Kotlin and Rust use the token-level
:class:`~crb.core.oracle.mutators_text.TextLineMutator` (``family="text"``). The
provenance stamp records the family and the operator-set hash, so a strength is
comparable only within a language and an instrument. Adding a language means adding
a mutator, not touching the scorer.
"""

from __future__ import annotations

import ast
import copy
import difflib
import os
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence, Set
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crb.core.evidence import canonical_json, sha256_text
from crb.core.execution import Executor, SandboxUnavailable
from crb.core.oracle.mutant import DEFAULT_MAX_MUTANTS, Mutant, Mutator
from crb.core.oracle.mutators_text import MUTATOR_FAMILY_TEXT, text_mutators
from crb.core.redact import redact_and_cap
from crb.core.runners.base import BaseRunner, TestRun
from crb.core.spec import RepoConfig, TaskSpec
from crb.core.version import APPARATUS_VERSION
from crb.core.workspace import Workspace, sha256_bytes

MUTATION_SCHEMA = "crb.oracle_strength.v1"
MUTATION_VERSION = "mutation.v1"
MUTATOR_FAMILY_AST = "ast"

EventFn = Callable[[str, Mapping[str, Any]], None]

# ---------------------------------------------------------------------------
# The operator set (fixed; hashed into the provenance stamp)
# ---------------------------------------------------------------------------

OP_CMP_FLIP = "cmp_flip"
OP_ARITH_FLIP = "arith_flip"
OP_BOOL_FLIP = "bool_flip"
OP_NEGATE_COND = "negate_cond"
OP_OFF_BY_ONE = "off_by_one"
OP_RETURN_NONE = "return_none"
OP_SWAP_BRANCHES = "swap_branches"

#: operator name → deterministic tie-break rank (sort is (line, col, rank, description)).
_OP_RANK: dict[str, int] = {
    OP_CMP_FLIP: 0,
    OP_ARITH_FLIP: 1,
    OP_BOOL_FLIP: 2,
    OP_NEGATE_COND: 3,
    OP_OFF_BY_ONE: 4,
    OP_RETURN_NONE: 5,
    OP_SWAP_BRANCHES: 6,
}
PYTHON_OPERATORS: tuple[str, ...] = tuple(sorted(_OP_RANK, key=_OP_RANK.__getitem__))

_CMP_FLIPS: dict[type[ast.cmpop], tuple[type[ast.cmpop], str]] = {
    ast.Eq: (ast.NotEq, "== -> !="),
    ast.NotEq: (ast.Eq, "!= -> =="),
    ast.Lt: (ast.LtE, "< -> <="),
    ast.LtE: (ast.Lt, "<= -> <"),
    ast.Gt: (ast.GtE, "> -> >="),
    ast.GtE: (ast.Gt, ">= -> >"),
}

_ARITH_FLIPS: dict[type[ast.operator], tuple[type[ast.operator], str]] = {
    ast.Add: (ast.Sub, "+ -> -"),
    ast.Sub: (ast.Add, "- -> +"),
}


# ---------------------------------------------------------------------------
# pure: byte-precise splicing (ast col offsets are UTF-8 BYTE offsets)
# ---------------------------------------------------------------------------

_Located = ast.expr | ast.stmt


def _line_starts(src_bytes: bytes) -> list[int]:
    starts = [0]
    for i, b in enumerate(src_bytes):
        if b == 0x0A:  # "\n"
            starts.append(i + 1)
    return starts


def _abs_span(starts: list[int], node: _Located) -> tuple[int, int]:
    end_line = node.end_lineno or node.lineno
    end_col = node.end_col_offset if node.end_col_offset is not None else node.col_offset
    return starts[node.lineno - 1] + node.col_offset, starts[end_line - 1] + end_col


def _splice(source: str, node: _Located, replacement: str) -> str:
    """Replace exactly ``node``'s source span with ``replacement`` (byte-precise)."""
    src_bytes = source.encode("utf-8")
    s, e = _abs_span(_line_starts(src_bytes), node)
    return (src_bytes[:s] + replacement.encode("utf-8") + src_bytes[e:]).decode("utf-8")


def _segment(source: str, node: _Located) -> str:
    src_bytes = source.encode("utf-8")
    s, e = _abs_span(_line_starts(src_bytes), node)
    return src_bytes[s:e].decode("utf-8")


# ---------------------------------------------------------------------------
# pure: eligibility — confine mutants to the gold patch's changed lines/functions
# ---------------------------------------------------------------------------


def eligible_lines(tree: ast.Module, changed_lines: Set[int]) -> set[int]:
    """The changed lines plus the FULL span of every function the patch touched.

    A patch that edits one line of a function changes that function's behaviour, so
    the whole function body is fair attack surface; everything else stays untouched.
    """
    lines = set(changed_lines)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            span = range(node.lineno, (node.end_lineno or node.lineno) + 1)
            if any(ln in changed_lines for ln in span):
                lines.update(span)
    return lines


_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def changed_lines_from_diff(diff_text: str) -> set[int]:
    """New-side line numbers from a unified diff's ``@@ -a,b +c,d @@`` hunk headers.

    Pure parse (hermetically testable); the git call lives in
    :func:`changed_lines_for`. Zero-length new sides (pure deletions) contribute
    the anchor line so a deletion still marks its neighbourhood as changed.
    """
    lines: set[int] = set()
    for raw in diff_text.splitlines():
        m = _HUNK_RE.match(raw)
        if m is None:
            continue
        start = int(m.group(1))
        count = int(m.group(2)) if m.group(2) is not None else 1
        if count == 0:
            lines.add(max(start, 1))
        else:
            lines.update(range(start, start + count))
    return lines


def changed_lines_for(ws: Workspace, path: str) -> set[int]:
    """Changed lines of ``path`` in the workspace's commit (``git diff -U0 parent sha``)."""
    out = ws.repo.run("diff", "-U0", ws.parent, ws.sha, "--", path, check=True).stdout
    return changed_lines_from_diff(out)


# ---------------------------------------------------------------------------
# the Python AST mutator (the Mutant / Mutator contract lives in crb.core.oracle.mutant)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Candidate:
    line: int
    col: int
    op: str
    description: str
    mutated_source: str

    @property
    def sort_key(self) -> tuple[int, int, int, str]:
        return (self.line, self.col, _OP_RANK[self.op], self.description)


def _collect_candidates(source: str, tree: ast.Module, lines: Set[int]) -> list[_Candidate]:
    out: list[_Candidate] = []

    def add(node: _Located, op: str, description: str, mutated: str) -> None:
        out.append(_Candidate(node.lineno, node.col_offset, op, description, mutated))

    for node in ast.walk(tree):
        if not isinstance(node, ast.expr | ast.stmt) or node.lineno not in lines:
            continue

        # operator flips: ==/!=, </<=, >/>= on single-op comparisons
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            flip = _CMP_FLIPS.get(type(node.ops[0]))
            if flip:
                new_cmp = copy.deepcopy(node)
                new_cmp.ops = [flip[0]()]
                add(node, OP_CMP_FLIP, flip[1], _splice(source, node, ast.unparse(new_cmp)))

        # operator flips: + / -
        elif isinstance(node, ast.BinOp):
            aflip = _ARITH_FLIPS.get(type(node.op))
            if aflip:
                new_bin = copy.deepcopy(node)
                new_bin.op = aflip[0]()
                add(node, OP_ARITH_FLIP, aflip[1], _splice(source, node, ast.unparse(new_bin)))

        # operator flips: and / or
        elif isinstance(node, ast.BoolOp):
            new_bool = copy.deepcopy(node)
            is_and = isinstance(node.op, ast.And)
            new_bool.op = ast.Or() if is_and else ast.And()
            desc = "and -> or" if is_and else "or -> and"
            add(node, OP_BOOL_FLIP, desc, _splice(source, node, ast.unparse(new_bool)))

        # boolean negation of a branch condition + swapped branch bodies
        elif isinstance(node, ast.If):
            test_seg = _segment(source, node.test)
            add(
                node.test,
                OP_NEGATE_COND,
                "if cond -> if not (cond)",
                _splice(source, node.test, f"not ({test_seg})"),
            )
            # swapped branch bodies — plain if/else only (an elif chain is not a clean swap)
            if node.orelse and not (len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If)):
                new_if = copy.deepcopy(node)
                new_if.body, new_if.orelse = new_if.orelse, new_if.body
                indent = " " * node.col_offset
                text = ("\n" + indent).join(ast.unparse(new_if).split("\n"))
                add(node, OP_SWAP_BRANCHES, "if/else bodies swapped", _splice(source, node, text))

        # off-by-one on integer constants (never bools; segment-check guards f-strings)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, int)
            and not isinstance(node.value, bool)
            and _segment(source, node) == str(node.value)
        ):
            add(
                node,
                OP_OFF_BY_ONE,
                f"{node.value} -> {node.value + 1}",
                _splice(source, node, str(node.value + 1)),
            )

        # early-return None
        elif (
            isinstance(node, ast.Return)
            and node.value is not None
            and not (isinstance(node.value, ast.Constant) and node.value.value is None)
        ):
            add(
                node,
                OP_RETURN_NONE,
                "return <expr> -> return None",
                _splice(source, node, "return None"),
            )

    return out


class PythonAstMutator:
    """The seven-operator Python mutator. Deterministic, bounded, compile-checked."""

    language = "python"
    family = MUTATOR_FAMILY_AST
    operators = PYTHON_OPERATORS
    suffixes: tuple[str, ...] = (".py",)

    def accepts(self, path: str) -> bool:
        return path.endswith(self.suffixes)

    def generate(
        self,
        source: str,
        changed_lines: Set[int],
        *,
        max_mutants: int = DEFAULT_MAX_MUTANTS,
        path: str = "<src>",
    ) -> list[Mutant]:
        """Deterministic, bounded AST-level mutants confined to the changed lines/functions.

        Seed-free: candidates sort on ``(line, col, operator-rank, description)`` and
        ids are assigned on the FULL filtered list before truncation, so the bounded
        list is always a PREFIX of the unbounded one. Every mutant compiles and
        differs from the original source.
        """
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            return []
        lines = eligible_lines(tree, changed_lines)
        candidates = sorted(_collect_candidates(source, tree, lines), key=lambda c: c.sort_key)

        mutants: list[Mutant] = []
        seen: set[str] = set()
        for cand in candidates:
            if cand.mutated_source == source or cand.mutated_source in seen:
                continue
            try:
                compile(cand.mutated_source, path, "exec")
            except (SyntaxError, ValueError):
                continue
            seen.add(cand.mutated_source)
            mutants.append(
                Mutant(
                    mutant_id=f"m{len(mutants) + 1:02d}_{cand.op}_L{cand.line}",
                    op=cand.op,
                    line=cand.line,
                    col=cand.col,
                    description=cand.description,
                    mutated_source=cand.mutated_source,
                    path=path,
                )
            )
        return mutants[: max(0, max_mutants)]

    def describe(self) -> dict[str, Any]:
        """What the operator set IS — hashed into the provenance stamp."""
        return {
            "language": self.language,
            "mutator": type(self).__name__,
            "family": self.family,
            "version": MUTATION_VERSION,
            "operators": [{"op": op, "rank": _OP_RANK[op]} for op in self.operators],
            "cmp_flips": sorted(desc for _, desc in _CMP_FLIPS.values()),
            "arith_flips": sorted(desc for _, desc in _ARITH_FLIPS.values()),
        }


#: language value → mutator. Python: the AST family; go / javascript / jvm / rust: the
#: text family. An unregistered language is not scoreable (never silently Python).
_MUTATORS: dict[str, Mutator] = {"python": PythonAstMutator(), **text_mutators()}
MUTATOR_FAMILIES: tuple[str, ...] = (MUTATOR_FAMILY_AST, MUTATOR_FAMILY_TEXT)


def mutator_for(language: str) -> Mutator | None:
    """The registered mutator for a language value (``"python"``, ``"go"``, …), or ``None``."""
    return _MUTATORS.get(language.strip().lower())


def mutator_family(mutator: Mutator) -> str:
    """Which family scored a row — what the mutator DECLARES in ``describe()``."""
    return str(mutator.describe().get("family", "") or "")


def operator_set_hash(mutator: Mutator) -> str:
    """Hash of everything the mutator says it is: language, family, version, operator
    table (and, for the text family, the substitution tables and language profile)."""
    return sha256_text(canonical_json(mutator.describe()))


def generate_mutants(
    source: str,
    changed_lines: Set[int],
    *,
    max_mutants: int = DEFAULT_MAX_MUTANTS,
    path: str = "<src>",
    mutator: Mutator | None = None,
) -> list[Mutant]:
    """Convenience: generate with the Python mutator (or the one given)."""
    m = mutator or _MUTATORS["python"]
    return m.generate(source, changed_lines, max_mutants=max_mutants, path=path)


# ---------------------------------------------------------------------------
# scoring: apply each mutant, run the task's TARGET tests only
# ---------------------------------------------------------------------------

OUTCOME_KILLED = "killed"
OUTCOME_ESCAPED = "escaped"
OUTCOME_ERROR = "error"
OUTCOME_UNCOMPILABLE = "uncompilable"


def compile_failure(run: TestRun) -> bool:
    """A MUTANT run the toolchain rejected before any test could observe the fault.

    The runner contract fails closed on an *unattributed* failure — a non-zero exit
    with no failing test id parsed (a compile/build error, a crashed binary, a reporter
    with nothing to report) is stamped ``parse_error``. On the GOLD baseline that is
    "not scoreable"; on a mutant it means the oracle never got to see the fault, so
    the mutant is ``uncompilable``: in neither the numerator nor the denominator. A
    timeout is never a compile failure (the tests ran and did not pass — a kill).
    """
    return not run.timed_out and run.returncode != 0 and not run.failing and bool(run.parse_error)


@dataclass(frozen=True)
class MutantOutcome:
    """One mutant's fate. ``killed`` is ``None`` when the mutant was not graded: a
    harness error (``error``) or a toolchain rejection (``uncompilable``) — both are
    excluded from the denominator and told apart by ``uncompilable``."""

    mutant_id: str
    op: str
    line: int
    description: str
    killed: bool | None
    diff: str  # unified diff original → mutant (the blind-spot evidence when escaped)
    path: str = ""
    timed_out: bool = False
    returncode: int | None = None
    tail: str = ""
    error: str = ""
    uncompilable: bool = False

    def __post_init__(self) -> None:
        if self.uncompilable and self.killed is not None:
            raise ValueError("an uncompilable mutant cannot also be killed/escaped")

    @property
    def status(self) -> str:
        if self.uncompilable:
            return OUTCOME_UNCOMPILABLE
        if self.killed is None:
            return OUTCOME_ERROR
        return OUTCOME_KILLED if self.killed else OUTCOME_ESCAPED

    def to_dict(self) -> dict[str, Any]:
        return {
            "mutant_id": self.mutant_id,
            "op": self.op,
            "line": self.line,
            "description": self.description,
            "killed": self.killed,
            "status": self.status,
            "diff": self.diff,
            "path": self.path,
            "timed_out": self.timed_out,
            "returncode": self.returncode,
            "tail": self.tail,
            "error": self.error,
            "uncompilable": self.uncompilable,
        }


@dataclass(frozen=True)
class MutationProvenance:
    """Which instrument produced the strength number. Evidence expires with it."""

    apparatus_version: str = APPARATUS_VERSION
    mutation_version: str = MUTATION_VERSION
    language: str = ""
    mutator: str = ""
    mutator_family: str = ""  # "ast" | "text" — strengths compare only within one
    operator_set_hash: str = ""
    max_mutants: int = DEFAULT_MAX_MUTANTS
    runner: str = ""
    executor: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "executor", dict(self.executor))

    def to_dict(self) -> dict[str, Any]:
        return {
            "apparatus_version": self.apparatus_version,
            "mutation_version": self.mutation_version,
            "language": self.language,
            "mutator": self.mutator,
            "mutator_family": self.mutator_family,
            "operator_set_hash": self.operator_set_hash,
            "max_mutants": self.max_mutants,
            "runner": self.runner,
            "executor": dict(self.executor),
        }


@dataclass(frozen=True)
class CommitOracleScore:
    """Mutation score of ONE task's target-test oracle.

    ``oracle_strength = killed / total`` over the mutants that ran to a verdict;
    ``None`` when not scoreable (RED baseline, no mutants, no mutator, harness error
    on the baseline). ``errors`` counts mutants excluded for harness errors and
    ``uncompilable`` those the toolchain rejected — both are in neither numerator
    nor denominator.
    """

    task_id: str
    repo: str
    src_paths: tuple[str, ...]
    capability_class: str
    size: str
    total: int
    killed: int
    oracle_strength: float | None
    outcomes: tuple[MutantOutcome, ...] = ()
    errors: int = 0
    note: str = ""
    baseline: TestRun | None = None
    provenance: MutationProvenance = field(default_factory=MutationProvenance)
    uncompilable: int = 0

    def __post_init__(self) -> None:
        if self.oracle_strength is not None and self.total == 0:
            raise ValueError("a score with no mutants cannot carry a strength")
        if self.killed > self.total:
            raise ValueError("killed cannot exceed total")

    @property
    def cell(self) -> str:
        """The (class × size) aggregation key."""
        return f"{self.capability_class}/{self.size}"

    @property
    def scoreable(self) -> bool:
        return self.total > 0

    @property
    def escaped(self) -> tuple[MutantOutcome, ...]:
        return tuple(o for o in self.outcomes if o.killed is False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_SCHEMA,
            "task_id": self.task_id,
            "repo": self.repo,
            "src_paths": list(self.src_paths),
            "capability_class": self.capability_class,
            "size": self.size,
            "cell": self.cell,
            "total": self.total,
            "killed": self.killed,
            "escaped": self.total - self.killed,
            "errors": self.errors,
            "uncompilable": self.uncompilable,
            "oracle_strength": self.oracle_strength,
            "note": self.note,
            "outcomes": [o.to_dict() for o in self.outcomes],
            "baseline": self.baseline.to_dict() if self.baseline else None,
            "provenance": self.provenance.to_dict(),
        }


class MutationRestoreError(RuntimeError):
    """The source file could not be restored byte-exact — the workspace is unusable."""


def _write_version(path: Path, content: bytes, mtime: int) -> None:
    """Write one source version with a DISTINCT, STRICTLY NEWER integer mtime.

    Two cache families must never grade the wrong bytes:

    * ``.pyc`` caches validate on (int-second mtime, size) — EQUALITY: a mutant/restore
      of the same size written within the same second could silently execute the
      PREVIOUS version's bytecode. Distinct mtimes per version make that impossible.
    * mtime-ORDERED build caches (Maven's stale-source check, cargo's fingerprints):
      a source whose mtime is OLDER than the artefact compiled from the previous
      version reads as "up to date", is not recompiled, and the tests run against the
      previous version's code — a false escape (or a false kill) vector. Every version
      is therefore stamped newer than wall-clock (:func:`_next_tick`), hence newer than
      any artefact that exists when it is written. Go keys its cache on content; node
      has none; both are unaffected.

    Correct-by-construction, not advisory: the scorer never asks a toolchain to clean.
    """
    path.write_bytes(content)
    os.utime(path, (mtime, mtime))


def _next_tick(tick: int) -> int:
    """The next version's mtime: strictly after the previous one AND strictly after
    now, so it is newer than anything a build compiled before this write."""
    return max(tick + 1, int(time.time()) + 1)


def _unified_diff(original: str, mutated: str, src_path: str) -> str:
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            mutated.splitlines(keepends=True),
            fromfile=f"a/{src_path}",
            tofile=f"b/{src_path}",
            n=2,
        )
    )


def _emit(on_event: EventFn | None, action: str, **payload: Any) -> None:
    if on_event is not None:
        on_event(action, payload)


def _refuse_test_targets(task: TaskSpec, config: RepoConfig, paths: Sequence[str]) -> None:
    bad = [p for p in paths if p in task.test_files or config.is_test(p)]
    if bad:
        raise ValueError(
            f"refusing to mutate test file(s) {bad!r} — mutants must never touch the oracle"
        )


def score_task(
    ws: Workspace,
    task: TaskSpec,
    *,
    config: RepoConfig,
    runner: BaseRunner,
    executor: Executor,
    max_mutants: int = DEFAULT_MAX_MUTANTS,
    changed_lines: Mapping[str, Set[int]] | None = None,
    mutator: Mutator | None = None,
    timeout: int = 0,
    on_event: EventFn | None = None,
) -> CommitOracleScore:
    """Mutation-score ONE task's target-test oracle.

    Precondition: ``ws`` is at the GOLD state — the commit's parent with the task's
    tests AND sources overlaid, so the target tests are GREEN. A RED baseline is
    reported not-scoreable, never averaged in. Every mutated file is restored
    byte-exact (verified by hash) even on exception. Raises ``ValueError`` if any
    source file is a test file; raises :class:`SandboxUnavailable` (infrastructure)
    so a run can stop; every other harness error is recorded, never counted.

    ``changed_lines`` overrides the git-derived changed lines per path (hermetic
    callers); by default they come from ``git diff -U0 parent sha -- path``.
    """
    mut = mutator or mutator_for(task.language or config.language.value)
    base: dict[str, Any] = {
        "task_id": task.task_id,
        "repo": task.repo,
        "capability_class": task.capability_class,
        "size": task.size,
    }
    if mut is None:
        return CommitOracleScore(
            src_paths=(),
            total=0,
            killed=0,
            oracle_strength=None,
            note=f"no mutator for language {task.language or config.language.value!r} — not scoreable",
            **base,
        )
    prov = MutationProvenance(
        language=mut.language,
        mutator=type(mut).__name__,
        mutator_family=mutator_family(mut),
        operator_set_hash=operator_set_hash(mut),
        max_mutants=max_mutants,
        runner=runner.name,
        executor=executor.describe(),
    )
    targets = [p for p in task.src_files if mut.accepts(p) and ws.exists(p)]
    _refuse_test_targets(task, config, task.src_files)
    base["src_paths"] = tuple(targets)
    base["provenance"] = prov

    # --- baseline: the gold state must be GREEN on its own target tests ----------
    try:
        baseline = runner.run_for(
            executor, ws.root, task.target_tests, timeout=timeout, authored=task.authored
        )
    except SandboxUnavailable:
        raise
    except Exception as exc:  # a harness error is never a strength number
        note = redact_and_cap(
            f"harness error on baseline: {type(exc).__name__}: {exc}", max_chars=600
        )
        _emit(on_event, "oracle.mutation.error", task=task.task_id, error=note)
        return CommitOracleScore(total=0, killed=0, oracle_strength=None, note=note, **base)
    if not baseline.green:
        why = "timed out" if baseline.timed_out else f"rc={baseline.returncode}"
        note = f"baseline RED — gold state fails its own target tests ({why}); not scoreable"
        _emit(on_event, "oracle.mutation.unscoreable", task=task.task_id, note=note)
        return CommitOracleScore(
            total=0, killed=0, oracle_strength=None, note=note, baseline=baseline, **base
        )

    # --- generate (pure) ---------------------------------------------------------
    originals: dict[str, bytes] = {}
    planned: list[Mutant] = []
    for rel in targets:
        raw = (ws.root / rel).read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        originals[rel] = raw
        lines = (
            set(changed_lines.get(rel, ()))
            if changed_lines is not None
            else changed_lines_for(ws, rel)
        )
        planned.extend(mut.generate(text, lines, max_mutants=max_mutants, path=rel))
    planned = planned[: max(0, max_mutants)]
    mutants = [
        Mutant(
            f"m{i:02d}_{m.op}_L{m.line}",
            m.op,
            m.line,
            m.col,
            m.description,
            m.mutated_source,
            m.path,
        )
        for i, m in enumerate(planned, start=1)
    ]
    if not mutants:
        note = "no mutants generated for the changed region — not scoreable"
        _emit(on_event, "oracle.mutation.unscoreable", task=task.task_id, note=note)
        return CommitOracleScore(
            total=0, killed=0, oracle_strength=None, note=note, baseline=baseline, **base
        )

    # --- run each mutant against the TARGET tests only; restore after each ------
    outcomes: list[MutantOutcome] = []
    files = {rel: ws.root / rel for rel in originals}
    tick = max(int(p.stat().st_mtime) for p in files.values())
    try:
        for m in mutants:
            original_text = originals[m.path].decode("utf-8")
            diff = _unified_diff(original_text, m.mutated_source, m.path)
            tick = _next_tick(tick)
            _write_version(files[m.path], m.mutated_source.encode("utf-8"), tick)
            try:
                run = runner.run_for(
                    executor, ws.root, task.target_tests, timeout=timeout, authored=task.authored
                )
            except SandboxUnavailable:
                raise
            except Exception as exc:
                err = redact_and_cap(f"{type(exc).__name__}: {exc}", max_chars=600)
                outcomes.append(
                    MutantOutcome(
                        m.mutant_id, m.op, m.line, m.description, None, diff, m.path, error=err
                    )
                )
                _emit(
                    on_event,
                    "oracle.mutation.error",
                    task=task.task_id,
                    mutant=m.mutant_id,
                    error=err,
                )
                continue
            finally:
                tick = _next_tick(tick)
                _write_version(files[m.path], originals[m.path], tick)
            if compile_failure(run):
                # the toolchain rejected the mutant before a test could see it:
                # excluded from the denominator, never a kill
                outcomes.append(
                    MutantOutcome(
                        m.mutant_id,
                        m.op,
                        m.line,
                        m.description,
                        None,
                        diff,
                        m.path,
                        returncode=run.returncode,
                        tail=redact_and_cap(run.tail, max_chars=600),
                        error=redact_and_cap(run.parse_error, max_chars=200),
                        uncompilable=True,
                    )
                )
                _emit(
                    on_event,
                    "oracle.mutation.uncompilable",
                    task=task.task_id,
                    mutant=m.mutant_id,
                    returncode=run.returncode,
                )
                continue
            killed = not run.green  # RED (incl. timeout) = the fault was observable
            outcomes.append(
                MutantOutcome(
                    m.mutant_id,
                    m.op,
                    m.line,
                    m.description,
                    killed,
                    diff,
                    m.path,
                    timed_out=run.timed_out,
                    returncode=run.returncode,
                    tail=redact_and_cap(run.tail, max_chars=600),
                )
            )
            _emit(
                on_event,
                "oracle.mutation.mutant",
                task=task.task_id,
                mutant=m.mutant_id,
                killed=killed,
                timed_out=run.timed_out,
            )
    finally:
        tick = _next_tick(tick)
        for rel, raw in originals.items():
            _write_version(files[rel], raw, tick)
            if sha256_bytes(files[rel].read_bytes()) != sha256_bytes(raw):
                raise MutationRestoreError(f"{rel} did not restore byte-exact after mutation")

    graded = [o for o in outcomes if o.killed is not None]
    uncompilable_n = sum(1 for o in outcomes if o.uncompilable)
    errors = len(outcomes) - len(graded) - uncompilable_n
    killed_n = sum(1 for o in graded if o.killed)
    total = len(graded)
    strength = round(killed_n / total, 4) if total else None
    note = (
        ""
        if total
        else (
            f"no mutant reached a verdict (uncompilable={uncompilable_n}, harness "
            f"errors={errors}) — not scoreable"
        )
    )
    _emit(
        on_event,
        "oracle.mutation.scored",
        task=task.task_id,
        total=total,
        killed=killed_n,
        errors=errors,
        uncompilable=uncompilable_n,
        oracle_strength=strength,
    )
    return CommitOracleScore(
        total=total,
        killed=killed_n,
        oracle_strength=strength,
        outcomes=tuple(outcomes),
        errors=errors,
        note=note,
        baseline=baseline,
        uncompilable=uncompilable_n,
        **base,
    )


# ---------------------------------------------------------------------------
# aggregation per (class × size) cell + reports
# ---------------------------------------------------------------------------


def aggregate_by_cell(scores: Iterable[CommitOracleScore]) -> dict[str, dict[str, Any]]:
    """Roll per-task scores up per ``class/size`` cell (scoreable tasks only).

    Every cell carries its denominator (``mutants``) — a strength never travels
    without its n.
    """
    cells: dict[str, dict[str, Any]] = {}
    for s in scores:
        if not s.scoreable:
            continue
        cell = cells.setdefault(
            s.cell,
            {"tasks": 0, "mutants": 0, "killed": 0, "escaped": 0, "errors": 0, "uncompilable": 0},
        )
        cell["tasks"] += 1
        cell["mutants"] += s.total
        cell["killed"] += s.killed
        cell["escaped"] += s.total - s.killed
        cell["errors"] += s.errors
        cell["uncompilable"] += s.uncompilable
    for cell in cells.values():
        cell["oracle_strength"] = round(cell["killed"] / cell["mutants"], 4)
    return dict(sorted(cells.items()))


def to_report(scores: Sequence[CommitOracleScore]) -> dict[str, Any]:
    """JSON-ready report. Deliberately timestamp-free — byte-identical across runs."""
    scoreable = [s for s in scores if s.scoreable]
    mutants = sum(s.total for s in scoreable)
    killed = sum(s.killed for s in scoreable)
    provenance = scoreable[0].provenance.to_dict() if scoreable else MutationProvenance().to_dict()
    return {
        "schema": MUTATION_SCHEMA,
        "provenance": provenance,
        "tasks": [
            {
                "task_id": s.task_id,
                "repo": s.repo,
                "src_paths": list(s.src_paths),
                "cell": s.cell,
                "total": s.total,
                "killed": s.killed,
                "escaped": s.total - s.killed,
                "errors": s.errors,
                "uncompilable": s.uncompilable,
                "oracle_strength": s.oracle_strength,
                "note": s.note,
                "escaped_mutants": [
                    {
                        "mutant_id": o.mutant_id,
                        "op": o.op,
                        "line": o.line,
                        "path": o.path,
                        "description": o.description,
                        "diff": o.diff,
                    }
                    for o in s.escaped
                ],
            }
            for s in scores
        ],
        "cells": aggregate_by_cell(scores),
        "summary": {
            "tasks": len(scores),
            "scoreable": len(scoreable),
            "unscoreable": len(scores) - len(scoreable),
            "mutants": mutants,
            "killed": killed,
            "escaped": mutants - killed,
            "errors": sum(s.errors for s in scores),
            "uncompilable": sum(s.uncompilable for s in scores),
            "oracle_strength": round(killed / mutants, 4) if mutants else None,
        },
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    """Human report: per-task table, per-cell table, and the blind-spot catalogue
    (every ESCAPED mutant with its diff — each one names a missing assertion)."""
    s = report["summary"]
    strength = "n/a" if s["oracle_strength"] is None else f"{s['oracle_strength']:.2f}"
    out: list[str] = [
        "# Oracle-strength report (mutation analysis)",
        "",
        f"Tasks: {s['tasks']} ({s['scoreable']} scoreable, {s['unscoreable']} not) — "
        f"mutants: {s['mutants']}, killed: {s['killed']}, escaped: {s['escaped']}, "
        f"errors: {s['errors']}, uncompilable: {s.get('uncompilable', 0)}, "
        f"oracle_strength: {strength}",
        "",
        "## Per task",
        "",
        "| task | cell | mutants | killed | escaped | strength | note |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in report["tasks"]:
        st = "n/a" if c["oracle_strength"] is None else f"{c['oracle_strength']:.2f}"
        out.append(
            f"| {c['task_id'][:12]} | {c['cell']} | {c['total']} | {c['killed']} | "
            f"{c['escaped']} | {st} | {c['note']} |"
        )
    out += [
        "",
        "## Per (class x size) cell",
        "",
        "| cell | tasks | mutants | killed | escaped | strength |",
        "|---|---|---|---|---|---|",
    ]
    for cell, v in report["cells"].items():
        out.append(
            f"| {cell} | {v['tasks']} | {v['mutants']} | {v['killed']} | "
            f"{v['escaped']} | {v['oracle_strength']:.2f} |"
        )
    out += ["", "## Blind-spot catalogue (escaped mutants)", ""]
    any_escape = False
    for c in report["tasks"]:
        for o in c["escaped_mutants"]:
            any_escape = True
            out += [
                f"### {c['task_id'][:12]} — {o['mutant_id']} ({o['description']}, "
                f"{o['path']}:{o['line']})",
                "",
                "```diff",
                o["diff"].rstrip("\n"),
                "```",
                "",
            ]
    if not any_escape:
        out += ["None — every generated mutant was killed.", ""]
    return "\n".join(out)


def oracle_strength_stamp(score: CommitOracleScore) -> str:
    """Compact one-line stamp for notes and logs (the ledger carries the number itself)."""
    if not score.scoreable:
        return f"oracle_strength=n/a task={score.task_id[:12]} (not scoreable)"
    return (
        f"oracle_strength={score.oracle_strength:.2f} killed={score.killed}/{score.total} "
        f"escaped={score.total - score.killed} task={score.task_id[:12]}"
    )


# The mutant contract (crb.core.oracle.mutant) is re-exported: this module stays the
# scorer's public face.
__all__ = [
    "DEFAULT_MAX_MUTANTS",
    "MUTATION_SCHEMA",
    "MUTATION_VERSION",
    "MUTATOR_FAMILIES",
    "MUTATOR_FAMILY_AST",
    "OUTCOME_ERROR",
    "OUTCOME_ESCAPED",
    "OUTCOME_KILLED",
    "OUTCOME_UNCOMPILABLE",
    "PYTHON_OPERATORS",
    "CommitOracleScore",
    "Mutant",
    "MutantOutcome",
    "MutationProvenance",
    "MutationRestoreError",
    "Mutator",
    "PythonAstMutator",
    "aggregate_by_cell",
    "changed_lines_for",
    "changed_lines_from_diff",
    "compile_failure",
    "eligible_lines",
    "generate_mutants",
    "mutator_family",
    "mutator_for",
    "operator_set_hash",
    "oracle_strength_stamp",
    "render_markdown",
    "score_task",
    "to_report",
]
