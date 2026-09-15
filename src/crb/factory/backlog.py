"""The pre-registered, frozen, hashed backlog — the integrity anchor of forward mode.

The T9 pilot charter moves the integrity load of a self-created pilot off the
repositories and onto the *issue stream*: every item is authored from the
product's needs **before** any factory attempt, the file is frozen, and its hash
is recorded. From then on:

* **The frozen record never mutates.** :meth:`Backlog.freeze` computes
  ``backlog_hash`` — SHA-256 of the canonical JSON of the items — and stamps
  ``frozen_at``. :meth:`Backlog.verify` recomputes it. Any operation that would
  change a frozen item raises :class:`BacklogFrozen`.
* **Change goes through the front door.** A later change is a *registered
  evolution*: a NEW item (new id) appended with ``supersedes=<old id>`` — or with
  no ``supersedes`` for a pure amendment. The original stays in the record and
  still counts (the charter's all-comers rule); the evolution hangs off it.
  :meth:`Backlog.active_items` is the effective backlog (superseded items
  replaced by their latest evolution).
* **Every item carries its kind and level.** ``kind`` is ``code`` (the factory
  builds), ``infra`` (the factory writes, the operator applies) or ``operator``
  (money / accounts / legal / recruiting — never delegable); ``level`` is the
  horizon it belongs to (L1 MVP → L2 MMP → L3 GA, nested supersets).

Everything here is a frozen dataclass or a pure function; persistence is the
caller's (see :mod:`crb.factory.evidence`).

Navigation
----------
What it is:   The frozen, hashed backlog — the integrity anchor of forward mode.
What it does: Validates items (id shape, kind, level, size, no self-dependency), freezes the
              record under a SHA-256 of its canonical JSON, refuses any mutation of a
              frozen item (``BacklogFrozen``), admits change only as a new item chained
              onto the frozen hash (``evolve``), and orders the active items by dependency
              (cycles raise). Pure dataclasses and functions; the caller persists.
How:          ``BacklogItem.__post_init__`` checks the shape; ``Backlog.freeze`` stamps
              ``backlog_hash``; ``evolve`` extends ``evolutions_hash``; ``verify`` recomputes
              both; ``ordered`` is a stable topological sort with supersession resolved.
Layer:        factory — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md (the same hash discipline)
Works with:   src/crb/factory/readiness.py (reads ``structural_facts`` and ``kind``),
              src/crb/factory/loop.py (``run_backlog`` requires a frozen, verifying record),
              src/crb/factory/evidence.py (``record_freeze`` / ``record_evolution``),
              src/crb/core/evidence.py (``canonical_json`` / ``sha256_text``),
              src/crb/cli/commands/learn.py (emits items in this shape),
              src/crb/server/routes/factory.py (the HTTP surface — a 501 stub until P6)
Tested by:    tests/test_factory_backlog.py, tests/test_factory_loop.py
Touch when:   never for a new repository; adding an item field changes the frozen hash of
              every future record — bump ``BACKLOG_SCHEMA`` and note it in
              docs/EVIDENCE-AND-CLAIMS.md; adding a kind or level extends the tuples and
              the loop's routing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from crb.core.evidence import canonical_json, sha256_text, utc_now_iso
from crb.core.spec import SIZE_TIER_NAMES, UNCLASSIFIED

BACKLOG_SCHEMA = "crb.backlog.v1"

KIND_CODE = "code"
KIND_INFRA = "infra"
KIND_OPERATOR = "operator"
KINDS: tuple[str, ...] = (KIND_CODE, KIND_INFRA, KIND_OPERATOR)

LEVEL_L1 = "L1"
LEVEL_L2 = "L2"
LEVEL_L3 = "L3"
LEVELS: tuple[str, ...] = (LEVEL_L1, LEVEL_L2, LEVEL_L3)

_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


class BacklogError(ValueError):
    """A backlog or item is malformed (duplicate id, dangling dependency, bad kind…)."""


class BacklogFrozen(BacklogError):
    """An operation would mutate a frozen record. Register an evolution instead."""


@dataclass(frozen=True)
class BacklogItem:
    """One registered issue. Immutable once its backlog is frozen.

    ``structural_facts`` are the API-shaped facts a builder can act on (a route's
    method + path, a field's name + type + nullability, a component's props). They
    are ``slot: text`` lines — see :mod:`crb.factory.readiness` for which slots a
    class requires. They are never a diff and never a file list.
    """

    id: str
    title: str
    kind: str
    description: str = ""
    acceptance_criteria: tuple[str, ...] = ()
    capability_class: str = UNCLASSIFIED
    size_estimate: str = "S"
    structural_facts: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    level: str = LEVEL_L1
    supersedes: str = ""
    registered: str = field(default_factory=utc_now_iso)
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _ID_RE.fullmatch(self.id):
            raise BacklogError(f"item id {self.id!r} must match [A-Za-z0-9][A-Za-z0-9._-]{{0,63}}")
        if not self.title.strip():
            raise BacklogError(f"item {self.id}: title is required")
        if self.kind not in KINDS:
            raise BacklogError(f"item {self.id}: kind must be one of {KINDS}, got {self.kind!r}")
        if self.level not in LEVELS:
            raise BacklogError(f"item {self.id}: level must be one of {LEVELS}, got {self.level!r}")
        if self.size_estimate not in SIZE_TIER_NAMES:
            raise BacklogError(
                f"item {self.id}: size_estimate must be one of {SIZE_TIER_NAMES}, got {self.size_estimate!r}"
            )
        if self.supersedes == self.id:
            raise BacklogError(f"item {self.id} cannot supersede itself")
        for attr in ("acceptance_criteria", "structural_facts", "depends_on"):
            object.__setattr__(self, attr, tuple(str(x) for x in getattr(self, attr)))
        if self.id in self.depends_on:
            raise BacklogError(f"item {self.id} cannot depend on itself")
        object.__setattr__(self, "labels", {str(k): str(v) for k, v in self.labels.items()})

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "kind": self.kind,
            "description": self.description,
            "acceptance_criteria": list(self.acceptance_criteria),
            "capability_class": self.capability_class,
            "size_estimate": self.size_estimate,
            "structural_facts": list(self.structural_facts),
            "depends_on": list(self.depends_on),
            "level": self.level,
            "supersedes": self.supersedes,
            "registered": self.registered,
            "labels": dict(self.labels),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> BacklogItem:
        return cls(
            id=str(d["id"]),
            title=str(d.get("title", "")),
            kind=str(d.get("kind", KIND_CODE)),
            description=str(d.get("description", "")),
            acceptance_criteria=tuple(d.get("acceptance_criteria", ())),
            capability_class=str(d.get("capability_class") or UNCLASSIFIED),
            size_estimate=str(d.get("size_estimate", "S")),
            structural_facts=tuple(d.get("structural_facts", ())),
            depends_on=tuple(d.get("depends_on", ())),
            level=str(d.get("level", LEVEL_L1)),
            supersedes=str(d.get("supersedes", "")),
            registered=str(d.get("registered") or utc_now_iso()),
            labels=dict(d.get("labels") or {}),
        )


def backlog_hash(items: Iterable[BacklogItem]) -> str:
    """SHA-256 of the canonical JSON of the items, in registration order."""
    return sha256_text(canonical_json([i.to_dict() for i in items]))


def _check_items(items: Sequence[BacklogItem], *, known: Iterable[str] = ()) -> None:
    """Unique ids, and every ``depends_on`` / ``supersedes`` target known (``known`` = ids
    registered before this batch)."""
    seen: set[str] = set(known)
    for it in items:
        if it.id in seen:
            raise BacklogError(f"duplicate item id {it.id!r}")
        seen.add(it.id)
    for it in items:
        for dep in it.depends_on:
            if dep not in seen:
                raise BacklogError(f"item {it.id} depends on unknown item {dep!r}")
        if it.supersedes and it.supersedes not in seen:
            raise BacklogError(f"item {it.id} supersedes unknown item {it.supersedes!r}")


@dataclass(frozen=True)
class Backlog:
    """A registered backlog: ``items`` (frozen and hashed) plus ``evolutions``
    (registered after the freeze, each hashed on top of the frozen hash).

    ``backlog_hash`` covers the frozen items only and never changes;
    ``evolutions_hash`` chains each evolution onto it so the whole record is
    still verifiable (:meth:`verify`).
    """

    items: tuple[BacklogItem, ...]
    repo: str = ""
    frozen_at: str = ""
    backlog_hash: str = ""
    evolutions: tuple[BacklogItem, ...] = ()
    evolutions_hash: str = ""
    schema: str = BACKLOG_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        object.__setattr__(self, "evolutions", tuple(self.evolutions))
        _check_items(self.items)
        _check_items(self.evolutions, known=[i.id for i in self.items])
        if self.evolutions and not self.frozen:
            raise BacklogError("evolutions can only be registered against a frozen backlog")

    # --- freeze / verify ---------------------------------------------------------
    @property
    def frozen(self) -> bool:
        """Whether ``freeze`` has stamped a hash (the record is then immutable)."""
        return bool(self.backlog_hash)

    def freeze(self, *, at: str = "") -> Backlog:
        """Compute the hash and stamp the freeze time. Idempotent on a frozen record
        (returns ``self``); a frozen record cannot be re-frozen with different items."""
        if self.frozen:
            if self.backlog_hash != backlog_hash(self.items):
                raise BacklogFrozen("frozen items do not match backlog_hash — record tampered")
            return self
        if not self.items:
            raise BacklogError("cannot freeze an empty backlog")
        return replace(self, frozen_at=at or utc_now_iso(), backlog_hash=backlog_hash(self.items))

    def verify(self, expected_hash: str = "") -> bool:
        """Recompute the frozen hash (and the evolutions chain) and compare.

        ``expected_hash`` is the hash the registration ledger recorded; when given
        it must equal the record's own hash too.
        """
        if not self.frozen:
            return False
        if backlog_hash(self.items) != self.backlog_hash:
            return False
        if expected_hash and expected_hash != self.backlog_hash:
            return False
        return self._evolutions_chain() == self.evolutions_hash

    def _evolutions_chain(self) -> str:
        """Fold every evolution onto the frozen hash; empty when there are none."""
        h = self.backlog_hash
        for ev in self.evolutions:
            h = sha256_text(h + canonical_json(ev.to_dict()))
        return h if self.evolutions else ""

    # --- evolution (the only way a frozen backlog changes) -------------------------
    def evolve(self, item: BacklogItem) -> Backlog:
        """Register an evolution: a NEW item, optionally superseding an existing one.

        The frozen record is untouched; the new item is appended to
        ``evolutions`` and the evolutions chain hash is extended. Superseding an
        item that is already superseded is refused (supersede the latest).
        """
        if not self.frozen:
            raise BacklogError("freeze the backlog before registering evolutions")
        if self.get(item.id) is not None:
            raise BacklogFrozen(
                f"item {item.id!r} already exists — a frozen record never mutates; register a new id"
            )
        if item.supersedes:
            old = self.get(item.supersedes)
            if old is None:
                raise BacklogError(f"cannot supersede unknown item {item.supersedes!r}")
            if any(e.supersedes == old.id for e in self.evolutions):
                raise BacklogFrozen(
                    f"item {old.id!r} is already superseded — supersede its latest evolution"
                )
        new = replace(self, evolutions=(*self.evolutions, item))
        object.__setattr__(new, "evolutions_hash", new._evolutions_chain())
        return new

    # --- queries ---------------------------------------------------------------
    def all_items(self) -> tuple[BacklogItem, ...]:
        """Frozen items then evolutions, in registration order (superseded ones included)."""
        return (*self.items, *self.evolutions)

    def get(self, item_id: str) -> BacklogItem | None:
        """The item (frozen or evolution) with ``item_id``, or ``None``."""
        for it in self.all_items():
            if it.id == item_id:
                return it
        return None

    def superseded_ids(self) -> frozenset[str]:
        """Ids that a later evolution replaced."""
        return frozenset(e.supersedes for e in self.evolutions if e.supersedes)

    def active_items(self) -> tuple[BacklogItem, ...]:
        """The effective backlog: every item not superseded, in registration order."""
        gone = self.superseded_ids()
        return tuple(i for i in self.all_items() if i.id not in gone)

    def ordered(self) -> tuple[BacklogItem, ...]:
        """Active items in dependency order (stable topological sort). A dependency
        on a superseded item resolves to its latest evolution. Cycles raise."""
        active = self.active_items()
        by_id = {i.id: i for i in active}
        # ``latest`` maps a superseded id to the END of its supersession chain, so a
        # dependency on an old id follows the chain to whatever replaced it last.
        latest: dict[str, str] = {}
        for e in self.evolutions:
            if e.supersedes:
                root = e.supersedes
                while root in latest:
                    root = latest[root]
                latest[e.supersedes] = e.id
        for k in list(latest):
            v = latest[k]
            while v in latest:
                v = latest[v]
            latest[k] = v

        def deps(i: BacklogItem) -> list[str]:
            out = []
            for d in i.depends_on:
                d2 = latest.get(d, d)
                if d2 in by_id:
                    out.append(d2)
            return out

        done: list[BacklogItem] = []
        seen: set[str] = set()
        visiting: set[str] = set()

        def visit(i: BacklogItem) -> None:
            if i.id in seen:
                return
            if i.id in visiting:
                raise BacklogError(f"dependency cycle through {i.id!r}")
            visiting.add(i.id)
            for d in deps(i):
                visit(by_id[d])
            visiting.discard(i.id)
            seen.add(i.id)
            done.append(i)

        for i in active:
            visit(i)
        return tuple(done)

    # --- serialisation -----------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """The on-disk shape (what the evidence ledger's freeze event also records)."""
        return {
            "schema": self.schema,
            "repo": self.repo,
            "frozen_at": self.frozen_at,
            "backlog_hash": self.backlog_hash,
            "items": [i.to_dict() for i in self.items],
            "evolutions": [e.to_dict() for e in self.evolutions],
            "evolutions_hash": self.evolutions_hash,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Backlog:
        """Inverse of :meth:`to_dict`; the stored hashes are kept and checked by ``verify``."""
        return cls(
            items=tuple(BacklogItem.from_dict(i) for i in d.get("items", ())),
            repo=str(d.get("repo", "")),
            frozen_at=str(d.get("frozen_at", "")),
            backlog_hash=str(d.get("backlog_hash", "")),
            evolutions=tuple(BacklogItem.from_dict(e) for e in d.get("evolutions", ())),
            evolutions_hash=str(d.get("evolutions_hash", "")),
            schema=str(d.get("schema", BACKLOG_SCHEMA)),
        )


__all__ = [
    "BACKLOG_SCHEMA",
    "KINDS",
    "KIND_CODE",
    "KIND_INFRA",
    "KIND_OPERATOR",
    "LEVELS",
    "LEVEL_L1",
    "LEVEL_L2",
    "LEVEL_L3",
    "Backlog",
    "BacklogError",
    "BacklogFrozen",
    "BacklogItem",
    "backlog_hash",
]
