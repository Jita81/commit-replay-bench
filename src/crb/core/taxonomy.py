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
name one of its members or :data:`UNCLASSIFIED` (:func:`normalise_class`). Adding
a class here changes the instrument (see ``docs/ARCHITECTURE.md`` §7.4).

This module is pure data so that :mod:`crb.core.classify` (labels) and
:mod:`crb.core.spec` (task spec) can both import it without a cycle.
"""

from __future__ import annotations

from collections.abc import Mapping

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


__all__ = [
    "ALL_CLASSES",
    "CLASS_ALIASES",
    "CLASS_DEFINITIONS",
    "CLASS_VOCABULARY",
    "INTENT_CLASSES",
    "UNCLASSIFIED",
    "UNCLASSIFIED_SPELLINGS",
    "is_explicit_unclassified",
    "is_known_class",
    "normalise_class",
]
