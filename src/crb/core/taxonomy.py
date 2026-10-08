"""The closed change-class vocabulary, as data.

Two axes describe *what kind of change* a commit is:

* **Path classes** (:data:`ALL_CLASSES`) — what :func:`crb.core.spec.classify_path`
  can derive from *where* a change lands (routes, models, migrations, tests, docs,
  CI, IaC …). Deterministic, free, and blind to intent: any other code file falls
  through to ``bug.fix``, which on a library repository is every task.
* **Intent classes** (:data:`INTENT_CLASSES`) — the census's labelled vocabulary
  (``data/census-*/class_labels.json``) for the change *kinds* a path cannot
  express: a feature, a behaviour change, a refactor, a performance change. The
  quality-floor essay's per-class numbers were measured on these labels, so a
  product claim "per class" must be made on the same vocabulary.

:data:`CLASS_VOCABULARY` is the union and it is **closed**: an intent label must
name one of its members or :data:`UNCLASSIFIED` (:func:`normalise_class`). Adding a
GLOBAL class here changes the instrument (see ``docs/ARCHITECTURE.md`` §7.4).

This module is pure data so that :mod:`crb.core.classify` (labels) and
:mod:`crb.core.spec` (task spec) can both import it without a cycle.

Navigation
----------
What it is:   The change-class vocabulary — the path classes, the intent classes, their
              closed union, one definition per class, and the alias table a labeller's
              answer is folded through.
What it does: Fixes the ``capability_class`` axis of every cell key as data; maps any
              labeller answer onto a member or ``(unclassified)`` and never invents a
              class; supplies the definitions shown verbatim to a model or a human; names
              the class-set version every row of apparatus 2.4 stamps (``labels.taxonomy``,
              the global vocabulary is ``global/classes@v1``), refuses a cell that pools two
              versions (``ClassSetsPooled``) and keeps a (task, version) label table so a
              relabel never rewrites a stored row.
How:          Tuples and mappings; ``normalise_class`` lower-cases, strips quotes, then
              exact member → alias → ``(unclassified)``; ``parse_class_set`` checks the
              ``<owner>/classes@v<N>`` grammar; ``ClassLabelTable`` folds the label run's
              ``label.task`` events (latest per task and version wins).
Layer:        core — docs/ARCHITECTURE.md#75-change-class-two-axes-one-resolved-value
ADRs:         docs/adr/0026-the-context-standard.md (item 9's stamp)
Works with:   src/crb/core/spec.py (``classify_path`` returns members of ALL_CLASSES),
              src/crb/core/classify.py (labels are normalised through here; the prompt
              lists CLASS_DEFINITIONS), src/crb/builders/labeller.py (the transports that
              ask a model), src/crb/core/ledger.py (the cell key's class field),
              data/census-2026-07-08/class_labels.json (the vocabulary the census numbers
              were measured on)
Tested by:    tests/test_classify.py, tests/test_spec.py, tests/test_class_set_stamp.py
Touch when:   never for a new repository or organisation — an organisation's classes are a
              class-set version (ADR-0026 item 9), stamped `labels.taxonomy` and read on
              their own axis; adding, removing or redefining a GLOBAL class still changes the
              instrument: bump `src/crb/core/version.py`, add the definition
              (`tests/test_classify.py` enforces one per member) and record it in
              `docs/adr/README.md`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

UNCLASSIFIED = "(unclassified)"

#: The path taxonomy: everything :func:`crb.core.spec.classify_path` can return
#: (other than :data:`UNCLASSIFIED`). A capability map reports 0-count classes
#: honestly from this list.
ALL_CLASSES: tuple[str, ...] = (
    "backend.migration.add",
    "backend.model.edit",
    "backend.route.add",
    "backend.route.edit",
    "bug.fix",
    "ci.workflow.edit",
    "docs.update",
    "frontend.component.add",
    "frontend.component.edit",
    "frontend.route.add",
    "infra.helm.edit",
    "infra.terraform.edit",
    "test.add",
    "test.fix",
)

#: The census intent vocabulary not expressible by path. ``bug.fix`` is shared with
#: the path taxonomy; the census's ``other`` maps to :data:`UNCLASSIFIED`.
INTENT_CLASSES: tuple[str, ...] = (
    "behavior.change",
    "feature.add",
    "perf",
    "refactor",
)

#: The closed vocabulary a label must come from (sorted, deduplicated).
CLASS_VOCABULARY: tuple[str, ...] = tuple(sorted(set(ALL_CLASSES) | set(INTENT_CLASSES)))

#: One-line definitions, shown verbatim to a labeller (model or human). Every member
#: of :data:`CLASS_VOCABULARY` has one; a test enforces it.
CLASS_DEFINITIONS: Mapping[str, str] = {
    "backend.migration.add": "Adds or alters a database schema migration.",
    "backend.model.edit": "Changes a persistence model / entity / domain object definition.",
    "backend.route.add": "Adds a new HTTP route, endpoint, handler or controller action.",
    "backend.route.edit": "Changes an existing HTTP route's request/response shape or semantics.",
    "behavior.change": (
        "Deliberately changes existing observable behaviour or a default (not a defect "
        "repair, not a new capability): outputs, defaults, edge-case handling, contracts."
    ),
    "bug.fix": ("Repairs a defect: the code did not do what it was documented or expected to do."),
    "ci.workflow.edit": "Changes CI/CD pipeline or workflow definitions.",
    "docs.update": "Changes documentation only (no runtime behaviour).",
    "feature.add": (
        "Adds a new capability: a new public function, option, field, command, format or "
        "protocol support that did not exist before."
    ),
    "frontend.component.add": "Adds a new UI component.",
    "frontend.component.edit": "Changes an existing UI component's props, states or rendering.",
    "frontend.route.add": "Adds a new UI page / view / client route.",
    "infra.helm.edit": "Changes Helm chart values or templates.",
    "infra.terraform.edit": "Changes Terraform / IaC definitions.",
    "perf": "Improves performance (speed, memory, allocations) without changing behaviour.",
    "refactor": (
        "Restructures code without changing observable behaviour (rename, extract, move, "
        "simplify, type tightening)."
    ),
    "test.add": "Adds tests only; no production behaviour changes.",
    "test.fix": "Repairs or adjusts existing tests only.",
}

#: The ways a labeller may *explicitly* say "none of these" (an honest answer, as
#: opposed to an invented class, which is also unclassified but a parse failure).
UNCLASSIFIED_SPELLINGS: frozenset[str] = frozenset(
    {UNCLASSIFIED, "unclassified", "other", "none", "unknown"}
)

#: Spellings a labeller may produce that map onto the closed vocabulary. Anything
#: not in the vocabulary and not here is :data:`UNCLASSIFIED`.
CLASS_ALIASES: Mapping[str, str] = {
    **dict.fromkeys(UNCLASSIFIED_SPELLINGS, UNCLASSIFIED),
    "behaviour.change": "behavior.change",
    "behavior_change": "behavior.change",
    "behaviour_change": "behavior.change",
    "bugfix": "bug.fix",
    "bug_fix": "bug.fix",
    "fix": "bug.fix",
    "feature": "feature.add",
    "feature_add": "feature.add",
    "feat": "feature.add",
    "performance": "perf",
    "refactoring": "refactor",
    "docs": "docs.update",
    "test": "test.add",
    "tests": "test.add",
}


def normalise_class(raw: object) -> str:
    """Map a labeller's answer onto the closed vocabulary.

    Exact members pass through; :data:`CLASS_ALIASES` fold the obvious spellings;
    everything else — including ``None``, blanks and invented classes — is
    :data:`UNCLASSIFIED`. Deterministic and total: never raises.
    """
    if raw is None:
        return UNCLASSIFIED
    text = str(raw).strip().strip("\"'`").lower()
    if not text:
        return UNCLASSIFIED
    if text in UNCLASSIFIED_SPELLINGS:
        return UNCLASSIFIED
    if text in CLASS_VOCABULARY:
        return text
    return CLASS_ALIASES.get(text, UNCLASSIFIED)


def is_explicit_unclassified(raw: object) -> bool:
    """``True`` when a labeller *said* none-of-these (``other``, ``unclassified`` …)."""
    return str(raw).strip().strip("\"'`").lower() in UNCLASSIFIED_SPELLINGS


def is_known_class(name: str) -> bool:
    """``True`` for a vocabulary member or :data:`UNCLASSIFIED` (the only two things a
    label may carry)."""
    return name == UNCLASSIFIED or name in CLASS_VOCABULARY


# ---------------------------------------------------------------------------
# Class-set versions (ADR-0026 item 9's stamp)
# ---------------------------------------------------------------------------

#: The hashed row label that carries the class-set version (apparatus 2.4 or later).
LABEL_TAXONOMY = "taxonomy"
#: The global vocabulary above, as a class-set version. An organisation's set is
#: ``<org>/classes@vN`` (Wave 4); ``capability_class`` in the cell key stays the global parent.
GLOBAL_CLASS_SET = "global/classes@v1"
_CLASS_SET_RE = re.compile(r"^(?P<owner>[a-z0-9][a-z0-9._-]*)/classes@v(?P<n>[1-9][0-9]*)$")
#: The event the label run writes for each task it labels (``crb.server.worker``).
LABEL_EVENT_ACTION = "label.task"


class ClassSetsPooled(ValueError):
    """Rows classified under two class-set versions reached one cell (ADR-0026 item 9): a
    class means what its version's rule says, so a reader chooses one version
    (:func:`rows_for_taxonomy`) before it reduces a cell."""


def parse_class_set(version: str) -> tuple[str, int]:
    """``"global/classes@v1"`` → ``("global", 1)``; refuses anything outside the grammar."""
    m = _CLASS_SET_RE.match((version or "").strip())
    if not m:
        raise ValueError(
            f"class-set version {version!r} is outside the grammar <owner>/classes@v<N> "
            f"(the global vocabulary is {GLOBAL_CLASS_SET!r})"
        )
    return m.group("owner"), int(m.group("n"))


def is_class_set_version(version: str) -> bool:
    """``True`` for a string inside the ``<owner>/classes@v<N>`` grammar."""
    return bool(_CLASS_SET_RE.match((version or "").strip()))


class _HasTaxonomy(Protocol):
    @property
    def taxonomy(self) -> str: ...


def rows_for_taxonomy[R: _HasTaxonomy](rows: Iterable[R], version: str) -> list[R]:
    """The rows classified under ONE class-set version — there is no pooled view."""
    parse_class_set(version)
    return [r for r in rows if r.taxonomy == version]


@dataclass(frozen=True)
class ClassLabel:
    """One task's class under one class-set version, as a label run recorded it."""

    task_id: str
    taxonomy: str
    capability_class: str
    previous_class: str = ""
    labeller: str = ""


@dataclass(frozen=True)
class ClassLabelTable:
    """The (task, version) → class table (ADR-0026 item 9). A relabel adds an entry; it never
    rewrites a stored ledger row, which keeps the class and version it was graded under."""

    entries: Mapping[tuple[str, str], ClassLabel] = field(default_factory=dict)

    def with_label(self, label: ClassLabel) -> ClassLabelTable:
        """A new table with ``label`` recorded (the latest label of a task and version wins)."""
        parse_class_set(label.taxonomy)
        return ClassLabelTable({**self.entries, (label.task_id, label.taxonomy): label})

    def class_of(self, task_id: str, taxonomy: str = GLOBAL_CLASS_SET) -> str | None:
        """The task's class under ``taxonomy``, or ``None`` when no label run has named it."""
        hit = self.entries.get((task_id, taxonomy))
        return hit.capability_class if hit is not None else None

    @classmethod
    def from_events(cls, payloads: Iterable[Mapping[str, Any]]) -> ClassLabelTable:
        """Fold the label run's ``label.task`` event payloads, in order. A payload with no
        ``taxonomy`` was written under the global vocabulary, the only version before 2.4."""
        table = cls()
        for p in payloads:
            task_id = str(p.get("task_id") or "")
            klass = str(p.get("capability_class") or "")
            if not task_id or not klass:
                continue
            table = table.with_label(
                ClassLabel(
                    task_id=task_id,
                    taxonomy=str(p.get("taxonomy") or GLOBAL_CLASS_SET),
                    capability_class=klass,
                    previous_class=str(p.get("previous_class") or ""),
                    labeller=str(p.get("labeller") or ""),
                )
            )
        return table


__all__ = [
    "ALL_CLASSES",
    "CLASS_ALIASES",
    "CLASS_DEFINITIONS",
    "CLASS_VOCABULARY",
    "GLOBAL_CLASS_SET",
    "INTENT_CLASSES",
    "LABEL_TAXONOMY",
    "UNCLASSIFIED",
    "UNCLASSIFIED_SPELLINGS",
    "ClassLabel",
    "ClassLabelTable",
    "ClassSetsPooled",
    "is_class_set_version",
    "is_explicit_unclassified",
    "is_known_class",
    "normalise_class",
    "parse_class_set",
    "rows_for_taxonomy",
]
