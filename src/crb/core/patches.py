"""Keep what the product makes: every graded attempt's patch, redacted, content-addressed.

Until 2026-09-25 the only copy of a builder's patch was the throwaway worktree, which is
deleted after grading unless the run asked ``retain.worktrees``. The operator's export of
that day held 190 clean rows and **0** retrievable patches [measured — n = 618 rows,
method: every clean row's retention reason over the export, apparatus 2.0–2.2]: nothing
the product made could be read, reviewed, re-graded under a stronger belt or learned from.

So every graded attempt now keeps its patch, independent of ``retain.worktrees``:

* **The bytes are the grader's.** :meth:`crb.core.workspace.Workspace.patch_text` is the
  one procedure :meth:`~crb.core.workspace.Workspace.diff_stats` hashes, so a kept patch is
  by construction the text behind the pack's ``grade.diff.diff_sha256`` (when the grade got
  that far; a red attempt's pack has no diff anchor and the kept patch is anchored by the
  pack's ``notes.patch`` alone). :func:`keep_patch` records whether the two hashes agree
  (``anchored``) rather than assuming it.
* **Redacted, then capped, then stored.** The full text is hashed first (``sha256`` — what a
  review attests to), then passed through :func:`crb.core.redact.redact`, then cut to
  :data:`PATCH_STORE_MAX_BYTES` (1 MiB). The note says whether either changed the bytes.
* **Content-addressed.** The stored file is named by the SHA-256 of its own bytes
  (``stored_sha256``), under ``<evidence>/patches/<aa>/<sha>.diff``: a file whose content no
  longer hashes to its name is refused on read (:meth:`PatchStore.get`), and identical
  patches are stored once.
* **Anchored by the pack.** The note (``notes.patch`` of the evidence pack) carries both
  hashes, so the pack's own hash — which the ledger row cites — commits to the kept bytes.
* **Never a verdict, never a failure.** Keeping a patch cannot change a grade; a store that
  cannot write records ``{"error": …}`` in the note and the attempt is graded as before.

Retention: a kept patch belongs to its row's retention class — evidence, kept for as long
as the row (docs/DATA-RETENTION.md §2). A deployment that must keep no code switches the
store off (``CRB_RETENTION__PATCHES=false``); rows written then carry no ``notes.patch``.

Navigation
----------
What it is:   The patch store — every graded attempt's unified diff, redacted, capped,
              content-addressed, and the note the evidence pack carries about it.
What it does: Hashes the grader's own patch text, redacts and caps it, writes it once under
              the SHA-256 of the stored bytes, and returns the pack note (both hashes, sizes,
              redacted / truncated / anchored); reads a kept patch back only when its bytes
              still hash to its name.
How:          ``keep_patch(ws, store, diff_sha256=…)`` → ``Workspace.patch_text`` →
              ``sha256`` → ``redact`` → cap → ``PatchStore.put`` (temp file + rename) →
              ``KeptPatch.to_note``; readers: ``kept_patch_note(pack)`` →
              ``PatchStore.get(stored_sha256)``.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0006-zero-raw-retention-and-evidence-packs.md (the 2026-09-25
              amendment: patches are evidence)
Works with:   src/crb/core/workspace.py (``patch_text`` — the procedure the grader hashes),
              src/crb/core/run.py (keeps every replay attempt's patch before its pack is
              written), src/crb/factory/build.py (the same for a factory build),
              src/crb/core/redact.py (the redaction pass), src/crb/server/routes/grades.py
              (``GET /grades/{row_hash}/patch`` serves the kept bytes first),
              src/crb/core/review.py (a review attests to ``sha256`` — the pack's diff anchor)
Tested by:    tests/test_patches.py, tests/test_run.py, tests/test_server_routes_grades.py
Touch when:   ``Workspace.diff_stats`` changes what it hashes (``patch_text`` is the shared
              procedure — change it there, never here); the cap changes (docs/API.md and
              docs/DATA-RETENTION.md say 1 MiB).
Claims:       ``anchored: true`` means the kept text hashes to the grade's diff anchor — not
              that the patch is correct (the belts say that) or mergeable (a review does).
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from crb.core.redact import redact

if TYPE_CHECKING:  # the workspace imports git; the store itself needs neither
    from crb.core.workspace import Workspace

#: A kept patch is capped here (the hash is computed over the FULL text first).
PATCH_STORE_MAX_BYTES = 1024 * 1024
#: The store's directory under the deployment's evidence directory.
PATCHES_DIRNAME = "patches"
#: The evidence pack ``notes`` key that carries :meth:`KeptPatch.to_note`.
NOTE_KEY = "patch"

_HEX = frozenset("0123456789abcdef")


def sha256_hex(data: bytes) -> str:
    """The lowercase hex SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def is_sha256(value: str) -> bool:
    """A 64-character lowercase hex digest — the only name a kept patch may have."""
    return len(value) == 64 and all(ch in _HEX for ch in value)


@dataclass(frozen=True)
class KeptPatch:
    """What :func:`keep_patch` stored, as the pack's ``notes.patch`` records it.

    ``sha256`` is the hash of the FULL, unredacted text (what the grader hashed and a
    review attests to); ``stored_sha256`` names the stored bytes (redacted, capped).
    ``anchored`` is ``True`` when ``sha256`` equals the grade's diff anchor, ``False``
    when they differ, ``None`` when the grade recorded no anchor (a red attempt)."""

    sha256: str
    stored_sha256: str
    bytes: int
    stored_bytes: int
    redacted: bool
    truncated: bool
    anchored: bool | None

    def to_note(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "stored_sha256": self.stored_sha256,
            "bytes": self.bytes,
            "stored_bytes": self.stored_bytes,
            "redacted": self.redacted,
            "truncated": self.truncated,
            "anchored": self.anchored,
        }


def prepare(text: str, *, cap: int = PATCH_STORE_MAX_BYTES) -> tuple[str, bytes, bool, bool]:
    """``(full_sha256, stored_bytes, redacted, truncated)`` — hash, redact, cap, in that
    order: the hash must be of the full text so it can equal the grader's."""
    full = text.encode("utf-8")
    full_sha = sha256_hex(full)
    body = redact(text)
    redacted = body != text
    raw = body.encode("utf-8")
    truncated = len(raw) > cap
    if truncated:
        raw = raw[:cap].decode("utf-8", errors="ignore").encode("utf-8")
    return full_sha, raw, redacted, truncated


class PatchStore:
    """Content-addressed files ``<root>/<sha[:2]>/<sha>.diff`` where ``sha`` is the
    SHA-256 of the file's own bytes. Written once (temp file + rename); read back only
    when the bytes still hash to the name."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @classmethod
    def under(cls, evidence_dir: str | Path) -> PatchStore:
        """The store of a deployment whose evidence packs live in ``evidence_dir``."""
        return cls(Path(evidence_dir) / PATCHES_DIRNAME)

    def path_for(self, stored_sha256: str) -> Path:
        if not is_sha256(stored_sha256):
            raise ValueError("a kept patch is named by a 64-character lowercase sha256")
        return self.root / stored_sha256[:2] / f"{stored_sha256}.diff"

    def put_bytes(self, data: bytes) -> str:
        """Store ``data`` under its own hash (idempotent); return the hash."""
        sha = sha256_hex(data)
        path = self.path_for(sha)
        if path.is_file():
            return sha
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        return sha

    def put(
        self, text: str, *, cap: int = PATCH_STORE_MAX_BYTES, diff_sha256: str = ""
    ) -> KeptPatch:
        """Hash, redact, cap and store ``text``; ``diff_sha256`` is the grade's anchor
        (``""`` when it recorded none)."""
        full_sha, raw, redacted, truncated = prepare(text, cap=cap)
        stored = self.put_bytes(raw)
        return KeptPatch(
            sha256=full_sha,
            stored_sha256=stored,
            bytes=len(text.encode("utf-8")),
            stored_bytes=len(raw),
            redacted=redacted,
            truncated=truncated,
            anchored=(full_sha == diff_sha256) if diff_sha256 else None,
        )

    def get(self, stored_sha256: str) -> bytes | None:
        """The stored bytes, or ``None`` when absent or when they no longer hash to their
        name (a tampered or damaged file is never served as evidence)."""
        try:
            path = self.path_for(stored_sha256)
        except ValueError:
            return None
        if not path.is_file():
            return None
        data = path.read_bytes()
        return data if sha256_hex(data) == stored_sha256 else None


def keep_patch(ws: Workspace, store: PatchStore, *, diff_sha256: str = "") -> dict[str, Any]:
    """Keep ``ws``'s patch (the grader's own text) in ``store``; return the pack note.

    Never raises: keeping a patch is evidence, not a verdict, so a failure is recorded as
    ``{"error": …}`` and the attempt is graded exactly as before."""
    try:
        return store.put(ws.patch_text(), diff_sha256=diff_sha256).to_note()
    except Exception as exc:  # the grade must not depend on the store
        return {"error": redact(f"{type(exc).__name__}: {exc}")[:300]}


def kept_patch_note(pack: Mapping[str, Any] | None) -> dict[str, Any]:
    """The pack's ``notes.patch`` (``{}`` when the pack kept none)."""
    if not pack:
        return {}
    notes = pack.get("notes")
    note = notes.get(NOTE_KEY) if isinstance(notes, Mapping) else None
    return dict(note) if isinstance(note, Mapping) else {}


__all__ = [
    "NOTE_KEY",
    "PATCHES_DIRNAME",
    "PATCH_STORE_MAX_BYTES",
    "KeptPatch",
    "PatchStore",
    "is_sha256",
    "keep_patch",
    "kept_patch_note",
    "prepare",
    "sha256_hex",
]
