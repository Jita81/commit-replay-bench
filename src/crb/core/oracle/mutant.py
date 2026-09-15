"""The mutant contract every mutator family honours — a leaf module.

:mod:`crb.core.oracle.mutation` (the scorer + the Python AST mutator) and
:mod:`crb.core.oracle.mutators_text` (the C-family text mutator) both need
:class:`Mutant` and the :class:`Mutator` protocol; the scorer also needs the text
mutator to register it. Holding the shared types here keeps that graph acyclic
(text mutator → this; scorer → this + text mutator) without a late import.

Invariant carried by the types, not by any mutator: a :class:`Mutant` is ONE change
to ONE file whose id is stable across runs (``m01_cmp_flip_L4``), and a
:class:`Mutator` is pure — text in, mutants out, no I/O — so two runs on the same
input are byte-identical.

Navigation
----------
What it is:   The leaf module holding the ``Mutant`` record and the ``Mutator`` protocol every
              mutator family implements.
What it does: Fixes the shape of one planted fault (stable id, operator, position, the whole
              mutated source) and the pure-function contract of a generator; imports nothing
              from the rest of the oracle package so the two families and the scorer can all
              depend on it without a cycle.
How:          A frozen dataclass and a ``typing.Protocol``; ``DEFAULT_MAX_MUTANTS`` is the
              boundedness default the scorer and both mutators share.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0009-text-level-mutators.md
Works with:   src/crb/core/oracle/mutation.py (the scorer and the Python AST family),
              src/crb/core/oracle/mutators_text.py (the C-family text mutator),
              src/crb/core/oracle/__init__.py (re-exports)
Tested by:    tests/test_oracle_mutation.py, tests/test_oracle_mutation_text.py
Touch when:   never for a new repository; adding a field to ``Mutant`` changes the report
              shape in docs/API.md and every mutator's ``generate``.
"""

from __future__ import annotations

from collections.abc import Set
from dataclasses import dataclass
from typing import Any, Protocol

DEFAULT_MAX_MUTANTS = 20


@dataclass(frozen=True)
class Mutant:
    """One candidate fault. ``mutant_id`` is stable across runs (``m01_cmp_flip_L4``)."""

    mutant_id: str
    op: str
    line: int
    col: int
    description: str
    mutated_source: str
    path: str = ""

    def to_dict(self) -> dict[str, Any]:
        """The report shape — deliberately WITHOUT ``mutated_source`` (the scorer stores a
        diff for escapes instead; a whole file per mutant would bloat every pack)."""
        return {
            "mutant_id": self.mutant_id,
            "op": self.op,
            "line": self.line,
            "col": self.col,
            "description": self.description,
            "path": self.path,
        }


class Mutator(Protocol):
    """A per-language mutant generator. Pure: text in, mutants out, no I/O."""

    language: str
    operators: tuple[str, ...]

    def accepts(self, path: str) -> bool: ...

    def generate(
        self, source: str, changed_lines: Set[int], *, max_mutants: int, path: str
    ) -> list[Mutant]: ...

    def describe(self) -> dict[str, Any]: ...


__all__ = ["DEFAULT_MAX_MUTANTS", "Mutant", "Mutator"]
