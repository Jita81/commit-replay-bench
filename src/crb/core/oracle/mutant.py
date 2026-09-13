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
