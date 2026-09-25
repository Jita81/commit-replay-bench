"""The bundle store: content-addressed, sealed, read-only dependency sets (ADR-0019).

Layout under the root (``CRB_PROVISION__STORE``, default ``<CRB_HOME>/deps``)::

    .staging/<uuid>/in    the lockfiles a fetch reads (mode 0700 while it is built)
    .staging/<uuid>/out   what the fetch wrote — the set, before it is sealed
    <lang>/dep_<sha256>/  a sealed set: read-only, with bundle.json beside the payload

Invariants:

* **Sealed is final.** :meth:`BundleStore.seal` hashes every file into an output digest,
  writes ``bundle.json`` (schema ``crb.bundle/1``), removes every write bit and renames
  the directory into place with ``os.replace``. A set is never edited after that; a
  concurrent seal of the same key keeps the first and discards its own stage.
* **Only the store makes a mount.** :meth:`mount` is the only place a real
  :class:`~crb.core.deps.BundleMount` is constructed: the path must be inside the root
  and the key must match ``^dep_[0-9a-f]{64}$``. The executor checks it again at use.
* **Integrity is re-provable.** :meth:`verify` re-hashes a set; a mismatch is
  ``BUNDLE_INTEGRITY`` (run scope). ``crb deps verify`` runs it over every set.
* **The daemon must see it.** :meth:`visible_to_daemon` writes a marker and reads it back
  through a throwaway container — under colima or dind a path the worker can write is not
  always one the daemon can mount (``PROVISION_STORE_NOT_VISIBLE``).

Navigation
----------
What it is:   The content-addressed store of sealed dependency sets and the only maker of a
              real ``BundleMount``.
What it does: Stages a fetch (0700), seals it (digest over every file, ``bundle.json``,
              ``a-w``, atomic rename; a lost race keeps the winner), hands out read-only
              mounts, re-verifies a set, collects garbage without ever removing a cited key,
              and proves the docker daemon can see the root.
How:          ``stage`` → the fetch writes ``out`` → ``seal`` (walk → sha256 lines → digest →
              manifest → chmod → ``os.replace``) → ``mount`` / ``binding_env`` → ``verify`` /
              ``gc`` / ``visible_to_daemon``.
Layer:        provision — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0005-fail-closed-docker-sandbox.md
Works with:   src/crb/core/deps.py (``BundleMount``, ``register_store_root``, the refusals),
              src/crb/provision/fetch.py (fills a stage), src/crb/provision/__init__.py (the
              provider that seals and binds), src/crb/core/execution.py (re-validates each
              mount), src/crb/cli/commands/deps.py (``crb deps ls | verify | gc``)
Tested by:    tests/test_provision_store.py
Touch when:   never for a new repository; the manifest schema changes only with a new
              ``crb.bundle/N`` and a reader for the old one.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import json
import os
import shutil
import stat
import subprocess
import uuid
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crb.core.deps import KEY_RE, BundleMount, ProvisionRefused, register_store_root

SCHEMA = "crb.bundle/1"
MANIFEST = "bundle.json"
STAGING = ".staging"


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")


def _walk(root: Path) -> Iterator[Path]:
    """Every regular file and symlink under ``root``, sorted, excluding the manifest."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if p.parent == root and name == MANIFEST:
                continue
            yield p


def output_digest(root: Path) -> tuple[str, int]:
    """``sha256:`` over the sorted ``relpath\\0size\\0sha256`` lines of every file under
    ``root`` (a symlink contributes its target text), and the total size in bytes."""
    lines: list[str] = []
    total = 0
    for p in _walk(root):
        rel = p.relative_to(root).as_posix()
        if p.is_symlink():
            data = os.readlink(p).encode()
            lines.append(f"{rel}\0L{len(data)}\0{hashlib.sha256(data).hexdigest()}")
            continue
        h = hashlib.sha256()
        size = 0
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
                size += len(chunk)
        total += size
        lines.append(f"{rel}\0{size}\0{h.hexdigest()}")
    lines.sort()
    return "sha256:" + hashlib.sha256("\n".join(lines).encode()).hexdigest(), total


def _make_read_only(root: Path) -> None:
    """``chmod -R a+rX,a-w`` — every write bit off, read (and search on directories) on."""
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        for name in filenames:
            p = Path(dirpath) / name
            if p.is_symlink():
                continue
            mode = p.stat().st_mode
            exe = 0o111 if mode & 0o111 else 0
            p.chmod(0o444 | exe)
        for name in dirnames:
            p = Path(dirpath) / name
            if not p.is_symlink():
                p.chmod(0o555)


def _make_writable(root: Path) -> None:
    """Give the worker back write permission so it can remove a set it owns."""
    if not root.exists():
        return
    with contextlib.suppress(OSError):
        root.chmod(0o755)
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames:
            with contextlib.suppress(OSError):
                (Path(dirpath) / name).chmod(0o755)
        for name in filenames:
            p = Path(dirpath) / name
            if not p.is_symlink():
                with contextlib.suppress(OSError):
                    p.chmod(0o644)


def remove_tree(root: Path) -> None:
    """Remove a (possibly sealed, read-only) tree the worker owns."""
    _make_writable(root)
    shutil.rmtree(root, ignore_errors=True)


@dataclass(frozen=True)
class Sealed:
    """A sealed set: where it is and what its manifest says."""

    lang: str
    key: str
    path: Path
    manifest: Mapping[str, Any]

    @property
    def digest(self) -> str:
        return str(self.manifest.get("digest", ""))

    @property
    def bytes(self) -> int:
        return int(self.manifest.get("bytes", 0))


class BundleStore:
    """The store at ``root``. Registers the root with :mod:`crb.core.deps` so mounts under
    it are admitted."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self.root = register_store_root(self.root)

    # --- staging and sealing -----------------------------------------------------
    def stage(self) -> Path:
        """A fresh ``.staging/<uuid>`` (mode 0700) with empty ``in`` and ``out``."""
        base = self.root / STAGING
        base.mkdir(parents=True, exist_ok=True)
        st = base / uuid.uuid4().hex
        st.mkdir(mode=0o700)
        (st / "in").mkdir(mode=0o700)
        (st / "out").mkdir(mode=0o777)
        # the fetch container runs as the worker's uid, but a restrictive umask must not
        # stop it writing into /out
        (st / "out").chmod(0o700)
        return st

    def path_of(self, lang: str, key: str) -> Path:
        if not KEY_RE.fullmatch(key):
            raise ValueError(f"not a bundle key: {key!r}")
        if not lang.isidentifier():
            raise ValueError(f"not a language: {lang!r}")
        return self.root / lang / key

    def seal(self, stage: Path, manifest: Mapping[str, Any]) -> Sealed:
        """Seal ``stage/out`` as ``manifest["key"]`` under ``manifest["lang"]``.

        The digest covers every file; ``bundle.json`` records it with the manifest;
        every write bit goes; ``os.replace`` moves the set into place. If another seal of
        the same key got there first, this stage is discarded and the winner returned."""
        lang, key = str(manifest["lang"]), str(manifest["key"])
        final = self.path_of(lang, key)
        out = Path(stage) / "out"
        digest, size = output_digest(out)
        record = {
            "schema": SCHEMA,
            **dict(manifest),
            "digest": digest,
            "bytes": size,
            "created": _now(),
        }
        (out / MANIFEST).write_text(json.dumps(record, indent=1, sort_keys=True), encoding="utf-8")
        _make_read_only(out)
        (out / MANIFEST).chmod(0o444)
        final.parent.mkdir(parents=True, exist_ok=True)
        try:
            if final.exists():
                raise FileExistsError(str(final))
            # a directory moves into place while it is still writable (renaming a directory
            # across parents updates its "..": POSIX needs write permission on it)
            os.replace(out, final)
        except OSError:
            remove_tree(Path(stage))
            winner = self.get(lang, key)
            if winner is None:  # pragma: no cover - the rename failed for another reason
                raise
            return winner
        final.chmod(0o555)
        remove_tree(Path(stage))
        return Sealed(lang, key, final, record)

    def discard(self, stage: Path) -> None:
        """Remove an unsealed stage (a failed or refused fetch)."""
        remove_tree(Path(stage))

    # --- reading -----------------------------------------------------------------
    def get(self, lang: str, key: str) -> Sealed | None:
        """The sealed set, or ``None`` (a miss)."""
        path = self.path_of(lang, key)
        try:
            manifest = json.loads((path / MANIFEST).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return Sealed(lang, key, path, manifest)

    def sets(self) -> list[Sealed]:
        """Every sealed set, oldest first."""
        out: list[Sealed] = []
        for lang_dir in sorted(p for p in self.root.iterdir() if p.is_dir()):
            if lang_dir.name == STAGING:
                continue
            for d in sorted(lang_dir.iterdir()):
                if KEY_RE.fullmatch(d.name):
                    s = self.get(lang_dir.name, d.name)
                    if s is not None:
                        out.append(s)
        out.sort(key=lambda s: str(s.manifest.get("created", "")))
        return out

    def find(self, key: str) -> Sealed | None:
        """The sealed set for ``key`` in any language."""
        return next((s for s in self.sets() if s.key == key), None)

    def mount(self, key: str, lang: str, sub: str, inside: str) -> BundleMount:
        """THE constructor of a real mount: ``<root>/<lang>/<key>/<sub>`` at ``inside``.
        Refuses a key that is not sealed here."""
        sealed = self.get(lang, key)
        if sealed is None:
            raise ProvisionRefused("BUNDLE_INTEGRITY", f"{lang}/{key} is not sealed in the store")
        host = sealed.path / sub if sub else sealed.path
        return BundleMount(host_path=host, container_path=inside, key=key)

    # --- integrity and housekeeping -----------------------------------------------
    def verify(self, key: str, lang: str = "") -> Sealed:
        """Re-hash ``key``; ``BUNDLE_INTEGRITY`` (run scope) unless the digest matches and
        nothing in the set is writable."""
        sealed = self.get(lang, key) if lang else self.find(key)
        if sealed is None:
            raise ProvisionRefused("BUNDLE_INTEGRITY", f"{key} is not in the store")
        digest, _ = output_digest(sealed.path)
        if digest != sealed.digest:
            raise ProvisionRefused(
                "BUNDLE_INTEGRITY",
                f"{sealed.lang}/{key}: digest {digest} does not match the sealed {sealed.digest}",
            )
        dirs = [Path(d) for d, _, _ in os.walk(sealed.path)]
        for p in [*dirs, *_walk(sealed.path)]:
            if not p.is_symlink() and p.stat().st_mode & (
                stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
            ):
                raise ProvisionRefused(
                    "BUNDLE_INTEGRITY", f"{sealed.lang}/{key}: {p.name} is writable (unsealed)"
                )
        return sealed

    def gc(self, keep: Iterable[str], max_total_gb: float) -> list[str]:
        """Remove the oldest sets until the store is under ``max_total_gb``, never one whose
        key is in ``keep`` (a key a qualification cites). Stale stages go first. Returns
        the removed keys."""
        cited = set(keep)
        staging = self.root / STAGING
        if staging.is_dir():
            for st in staging.iterdir():
                remove_tree(st)
        sets = self.sets()
        cap = int(max_total_gb * (1 << 30))
        total = sum(s.bytes for s in sets)
        removed: list[str] = []
        for s in sets:
            if total <= cap:
                break
            if s.key in cited:
                continue
            remove_tree(s.path)
            total -= s.bytes
            removed.append(s.key)
        return removed

    def visible_to_daemon(self, docker: str, image: str, *, timeout: int = 60) -> None:
        """Write a marker under the root and read it back through a throwaway container
        (``--network=none``, read-only). Any difference is ``PROVISION_STORE_NOT_VISIBLE``."""
        token = uuid.uuid4().hex
        marker = self.root / f".probe-{token}"
        marker.write_text(token, encoding="utf-8")
        marker.chmod(0o644)
        try:
            r = subprocess.run(
                [
                    docker,
                    "run",
                    "--rm",
                    "--pull=never",
                    "--network=none",
                    "--read-only",
                    "--cap-drop=ALL",
                    "--user=65534:65534",
                    "--mount",
                    f"type=bind,src={self.root},dst=/store,readonly",
                    image,
                    "cat",
                    f"/store/{marker.name}",
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            seen = (r.stdout or "").strip()
            detail = (r.stderr or "").strip()[:300]
        except (OSError, subprocess.SubprocessError) as exc:
            seen, detail = "", f"{type(exc).__name__}: {exc}"
        finally:
            marker.unlink(missing_ok=True)
        if seen != token:
            raise ProvisionRefused(
                "PROVISION_STORE_NOT_VISIBLE",
                f"the docker daemon cannot read {self.root} ({detail or 'marker not seen'})",
            )


__all__ = ["MANIFEST", "SCHEMA", "BundleStore", "Sealed", "output_digest", "remove_tree"]
