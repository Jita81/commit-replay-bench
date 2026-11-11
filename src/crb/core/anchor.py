"""Ledger anchors — a small file, kept off the machine, that a later ledger must still extend.

A hash chain shows that no row was edited or removed from the middle. It cannot show that
rows were cut from its end, or that the whole ledger was rebuilt from a new genesis: a
rebuilt chain verifies too. An anchor closes that, under one condition. It records, for
each chain, the row count and the ``row_hash`` of the row at that count. Later, the row at
that count must still carry that hash. If the anchor left the machine before the ledger was
rewritten, and the person who can rewrite the ledger cannot also rewrite the anchor, the
rewrite is caught (docs/LEDGER-ANCHORS.md says who holds anchors and where).

File format (``crb.ledger-anchor/v1``, sorted keys, two-space indent, one trailing newline)::

    {
      "schema": "crb.ledger-anchor/v1",
      "created_at": "2026-11-11T12:00:00Z",
      "crb_version": "...", "apparatus": "2.5",
      "source": "jsonl" | "sqlite" | "postgresql",     # never a URL: it can hold a password
      "chains": {"grades": {"rows": 3, "head_row_hash": "..."},
                 "events": {"rows": 5, "head_row_hash": "..."}},  # events: store only
      "previous_anchor": {"file": "anchor-....json", "sha256": "..."} | null,
      "signed": false,
      "note": "..."
    }

Invariants
----------
* **Read-only.** Nothing here writes a ledger, a row or a hash input; an anchor is derived
  from heads the caller has already read.
* **An anchor attests something.** Its chains are exactly its source's (``grades`` for
  JSONL; ``grades`` and ``events`` for a store) and at least one has a row; the writer and
  the reader apply the same rule (:func:`check_chains`).
* **No overwrite.** :func:`write_anchor` creates a file under a name derived from the chain
  state, through a hard link that fails if the name exists. The same state again is a no-op;
  a different state under an existing name is refused.
* **Anchors chain.** Each new anchor names the previous anchor in its directory and the
  sha256 of that file's bytes, so a deleted or edited anchor that has a successor is visible
  in the directory. The newest anchor has none: only the directory's own custody (a
  repository held off the machine) protects it.
* **No network, no git.** A transparency-log signature (Sigstore / Rekor) is the seam
  ``signed`` leaves open; it is not built and is off by default.

Navigation
----------
What it is:   The anchor format and its checks — ``build_anchor``, ``anchor_name``,
              ``check_chains`` (the chains a source's anchor must record, one with a row),
              ``check_anchor`` (does today's ledger still extend this anchor?),
              ``check_anchor_links`` (is the directory's anchor chain whole?),
              ``previous_link`` (the one validated read of a predecessor link), the loaders
              and the no-overwrite ``write_anchor``.
What it does: Builds a self-describing, deterministic JSON anchor from chain heads; names it
              from its row counts and heads; refuses to overwrite one; finds the row at an
              anchored count through a caller-supplied reader and names the first chain that
              no longer holds; checks each anchor in a directory names its predecessor.
How:          Pure functions over dicts plus small file helpers (``os.link`` for create-only);
              the CLI supplies the ``hash_at(chain, n)`` reader for the JSONL file or store.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md,
              docs/adr/0029-the-audit-trail-is-hash-chained.md
Works with:   src/crb/cli/commands/ledger.py (``crb ledger anchor`` and ``verify --anchor``),
              src/crb/core/ledger.py (``JsonlLedger`` / ``verify_chain`` — the chain anchored),
              src/crb/store/events.py (``verify_events`` — the audit chain's head),
              docs/LEDGER-ANCHORS.md (custody: who holds anchors and where)
Tested by:    tests/test_anchor.py, tests/test_cli_ledger_anchor.py
Touch when:   never for a new repository; the anchor format changes (bump ``ANCHOR_SCHEMA``
              and keep reading v1); a transparency-log signature is approved by the operator.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ANCHOR_SCHEMA = "crb.ledger-anchor/v1"
ANCHOR_PREFIX = "anchor-"
ANCHOR_SUFFIX = ".json"

#: What an anchor is and is not, written into every file so it explains itself.
ANCHOR_NOTE = (
    "Unsigned. Proves the ledger was not rewritten after this file left the machine, and only "
    "while the file is held where whoever can write the ledger cannot change it. It proves "
    "nothing about the ledger before this anchor was taken, and nothing about whether a row "
    "is true. See docs/LEDGER-ANCHORS.md."
)

#: ``hash_at(chain, n)`` → the ``row_hash`` of the n-th row (1-based) of ``chain``, or
#: ``None`` when the chain has fewer than ``n`` rows.
HashAt = Callable[[str, int], str | None]


class AnchorError(ValueError):
    """An anchor that cannot be read, or an anchor operation that is refused."""


@dataclass(frozen=True)
class ChainHead:
    """One chain's state: its row count and the ``row_hash`` of its last row."""

    rows: int
    head_row_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {"rows": self.rows, "head_row_hash": self.head_row_hash}


def build_anchor(
    *,
    source: str,
    chains: Mapping[str, ChainHead],
    apparatus: str,
    crb_version: str,
    created_at: str,
    previous: tuple[str, str] | None = None,
) -> dict[str, Any]:
    """The anchor dict. ``previous`` is ``(file name, sha256 of its bytes)`` of the anchor
    this one follows in its directory. ``created_at`` is passed in: nothing here reads a
    clock."""
    check_chains(source, chains, "anchor")
    return {
        "schema": ANCHOR_SCHEMA,
        "created_at": created_at,
        "crb_version": crb_version,
        "apparatus": apparatus,
        "source": source,
        "chains": {name: chains[name].to_dict() for name in sorted(chains)},
        "previous_anchor": (
            None if previous is None else {"file": previous[0], "sha256": previous[1]}
        ),
        "signed": False,
        "note": ANCHOR_NOTE,
    }


def anchor_bytes(anchor: Mapping[str, Any]) -> bytes:
    """The file's bytes: sorted keys, two-space indent, one trailing newline."""
    return (json.dumps(anchor, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


def anchor_name(chains: Mapping[str, Any]) -> str:
    """A deterministic file name from each chain's row count and head, chains in name order:
    ``anchor-g00000003-<16 hex>[-e00000005-<16 hex>].json`` (grades first)."""
    parts = []
    for name in sorted(chains, key=lambda c: (c != "grades", c)):
        head = _head(chains[name])
        parts.append(f"{name[0]}{head.rows:08d}-{head.head_row_hash[:16] or 'empty'}")
    return ANCHOR_PREFIX + "-".join(parts) + ANCHOR_SUFFIX


SOURCES = ("jsonl", "sqlite", "postgresql")
"""The ledgers an anchor can be of: the JSONL file, or a store on one of its two backends."""


def expected_chains(source: str) -> frozenset[str]:
    """The chains an anchor of ``source`` records: a JSONL ledger has only ``grades``; a
    store (``sqlite``, ``postgresql``) has ``grades`` and ``events``."""
    return frozenset({"grades"}) if source == "jsonl" else frozenset({"grades", "events"})


def check_chains(source: str, chains: Mapping[str, ChainHead], where: str) -> None:
    """:class:`AnchorError` naming ``where`` unless ``source`` is one of :data:`SOURCES`,
    ``chains`` are exactly its chains, each head is consistent (rows > 0 exactly when it has
    a head) and at least one chain has a row: an anchor that attests nothing would check as
    holding. The one
    rule, shared by :func:`build_anchor` and :func:`parse_anchor`, so the writer never
    produces a file the reader refuses."""
    if source not in SOURCES:
        raise AnchorError(f"{where}: source {source!r} is not one of {list(SOURCES)}")
    want = expected_chains(source)
    if set(chains) != want:
        raise AnchorError(
            f"{where}: a {source} anchor records the chains {sorted(want)}, not {sorted(chains)}"
        )
    for name, head in chains.items():
        if head.rows < 0 or (head.rows > 0) != bool(head.head_row_hash):
            raise AnchorError(
                f"{where}: chain {name!r}: {head.rows} rows with head {head.head_row_hash!r}"
            )
    if not any(head.rows > 0 for head in chains.values()):
        raise AnchorError(f"{where}: every chain has 0 rows; the anchor attests nothing")


def _head(value: Any) -> ChainHead:
    if isinstance(value, ChainHead):
        return value
    return ChainHead(int(value["rows"]), str(value["head_row_hash"]))


def parse_anchor(data: bytes, where: str) -> dict[str, Any]:
    """The anchor in ``data``; :class:`AnchorError` naming ``where`` when it is not one."""
    try:
        d = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise AnchorError(f"{where}: not a JSON anchor ({e})") from e
    if not isinstance(d, dict) or d.get("schema") != ANCHOR_SCHEMA:
        raise AnchorError(f"{where}: schema is not {ANCHOR_SCHEMA}")
    chains = d.get("chains")
    if not isinstance(chains, dict) or not chains:
        raise AnchorError(f"{where}: no chains")
    for name, head in chains.items():
        if (
            not isinstance(head, dict)
            or not isinstance(head.get("rows"), int)
            or isinstance(head["rows"], bool)  # JSON true is not a row count
            or head["rows"] < 0
            or not isinstance(head.get("head_row_hash"), str)
        ):
            raise AnchorError(f"{where}: chain {name!r} is not {{rows, head_row_hash}}")
    if not isinstance(d.get("source"), str):
        raise AnchorError(f"{where}: no source")
    check_chains(d["source"], {name: _head(head) for name, head in chains.items()}, where)
    return d


def same_state(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """Two anchors record the same ledger state (source and every chain's count and head);
    their creation times may differ."""
    return a.get("source") == b.get("source") and a.get("chains") == b.get("chains")


def check_anchor(anchor: Mapping[str, Any], *, source: str, hash_at: HashAt) -> list[str]:
    """Why today's ledger does not extend ``anchor`` — one line per chain that no longer
    holds; empty when every anchored row is still there with its anchored hash."""
    if anchor.get("source") != source:
        return [
            f"the anchor was taken of a {anchor.get('source')} ledger and is checked against "
            f"a {source} ledger"
        ]
    faults: list[str] = []
    for name in sorted(anchor["chains"]):
        head = _head(anchor["chains"][name])
        if head.rows == 0:
            continue
        found = hash_at(name, head.rows)
        if found is None:
            faults.append(
                f"{name}: the ledger has fewer than {head.rows} rows — rows were cut from its "
                "end, or it was replaced"
            )
        elif found != head.head_row_hash:
            faults.append(
                f"{name}: row {head.rows} has row_hash {found}, the anchor recorded "
                f"{head.head_row_hash} — the history up to that row was rewritten"
            )
    return faults


@dataclass(frozen=True)
class LoadedAnchor:
    """An anchor file as read: its path, its exact bytes and the parsed anchor."""

    path: Path
    data: bytes
    anchor: dict[str, Any]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    def order_key(self) -> tuple[Any, ...]:
        chains = self.anchor["chains"]
        return (
            tuple(int(chains[c]["rows"]) for c in sorted(chains)),
            str(self.anchor.get("created_at", "")),
            self.path.name,
        )


def load_anchor(path: Path) -> LoadedAnchor:
    """Read one anchor file."""
    try:
        data = path.read_bytes()
    except OSError as e:
        raise AnchorError(f"{path}: cannot be read ({e.strerror or e})") from e
    return LoadedAnchor(path, data, parse_anchor(data, str(path)))


def load_anchor_dir(directory: Path) -> list[LoadedAnchor]:
    """Every ``anchor-*.json`` in ``directory``, oldest first (by row counts, then creation
    time). An unreadable anchor file raises: it is never skipped silently."""
    if not directory.is_dir():
        return []
    paths = sorted(directory.glob(f"{ANCHOR_PREFIX}*{ANCHOR_SUFFIX}"))
    return sorted((load_anchor(p) for p in paths), key=LoadedAnchor.order_key)


def previous_link(anchor: Mapping[str, Any]) -> tuple[str, str] | None:
    """The ``(file, sha256)`` this anchor names as its predecessor, or ``None`` when it names
    none. :class:`AnchorError` when ``previous_anchor`` is neither null nor
    ``{"file": str, "sha256": str}``: the one place the link is read, so no malformed value
    reaches attribute access."""
    prev = anchor.get("previous_anchor")
    if prev is None:
        return None
    if (
        not isinstance(prev, dict)
        or not isinstance(prev.get("file"), str)
        or not isinstance(prev.get("sha256"), str)
    ):
        raise AnchorError(f"previous_anchor is not {{file, sha256}} or null: {prev!r}")
    return prev["file"], prev["sha256"]


def check_anchor_links(anchors: Sequence[LoadedAnchor]) -> list[str]:
    """Faults in a directory's anchor chain (``anchors`` oldest first): each anchor after the
    first must name the one before it and that file's sha256; the first must name none. A
    malformed ``previous_anchor`` is a damaged link, reported like any other."""
    faults: list[str] = []
    for i, la in enumerate(anchors):
        try:
            link = previous_link(la.anchor)
        except AnchorError as e:
            faults.append(f"{la.path.name}: {e}")
            continue
        if i == 0:
            if link is not None:
                faults.append(f"{la.path.name} follows {link[0]}, which is not in the directory")
            continue
        before = anchors[i - 1]
        if link is None or link[0] != before.path.name:
            named = None if link is None else link[0]
            faults.append(
                f"{la.path.name} follows {named}, but the anchor before it is {before.path.name}"
            )
        elif link[1] != before.sha256:
            faults.append(
                f"{before.path.name} was changed after {la.path.name} recorded its sha256"
            )
    return faults


def write_anchor(directory: Path, anchor: Mapping[str, Any]) -> tuple[Path, bool]:
    """Create ``directory/anchor_name(...)`` holding ``anchor``; never overwrite. Returns
    ``(path, written)``: ``written`` is ``False`` when a file of the same ledger state is
    already there. A different state under an existing name raises :class:`AnchorError`."""
    path = directory / anchor_name(anchor["chains"])
    if path.exists():
        if same_state(load_anchor(path).anchor, anchor):
            return path, False
        raise AnchorError(f"{path} exists and records a different ledger state; not overwritten")
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".anchor-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(anchor_bytes(anchor))
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(tmp, path)  # create-only: fails if the name appeared meanwhile
        except FileExistsError as e:
            raise AnchorError(f"{path} appeared while writing; not overwritten") from e
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
    return path, True


def is_inside(path: Path, parent: Path) -> bool:
    """``path`` is ``parent`` or below it, after resolving symlinks and ``..``."""
    p, d = path.expanduser().resolve(), parent.expanduser().resolve()
    return p == d or p.is_relative_to(d)


__all__ = [
    "ANCHOR_NOTE",
    "ANCHOR_SCHEMA",
    "SOURCES",
    "AnchorError",
    "ChainHead",
    "HashAt",
    "LoadedAnchor",
    "anchor_bytes",
    "anchor_name",
    "build_anchor",
    "check_anchor",
    "check_anchor_links",
    "check_chains",
    "expected_chains",
    "is_inside",
    "load_anchor",
    "load_anchor_dir",
    "parse_anchor",
    "previous_link",
    "same_state",
    "write_anchor",
]
