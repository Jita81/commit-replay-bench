"""A ``file://`` GOPROXY tree built with :mod:`zipfile`, and the ``go.sum`` lines that pin it.

The module ``example.com/dep`` at ``v1.0.0`` (``Greeting``) and ``v1.1.0`` (adds
``Farewell``) is laid out exactly as the Go module proxy protocol serves it::

    <root>/example.com/dep/@v/list
    <root>/example.com/dep/@v/v1.0.0.info | .mod | .zip
    <root>/example.com/dep/@v/v1.1.0.info | .mod | .zip

so ``GOPROXY=file://<root>`` resolves it with no network. :func:`go_sum` computes the
``h1:`` hashes Go's ``dirhash.Hash1`` computes — sha256 over the sorted
``"<sha256>  <name>\\n"`` lines of the zip's files (and of ``go.mod`` alone for the
``/go.mod`` line) — so a fixture module's committed ``go.sum`` verifies against this
mirror exactly as a real one verifies against ``proxy.golang.org``.

Navigation
----------
What it is:   The Go module mirror fixture: two versions of ``example.com/dep`` as a
              ``file://`` GOPROXY tree, plus their ``go.sum`` lines.
What it does: Writes deterministic module zips (fixed timestamps), ``.info``/``.mod``/``list``
              files, and the ``h1:`` hashes Go verifies, so the Go fetch recipe can be proven
              offline — the air-gapped mode CI uses.
How:          ``zipfile`` with fixed ``ZipInfo`` dates → ``build(root)``; ``go_sum(versions)``
              re-derives Go's ``dirhash.Hash1`` in Python.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         none
Works with:   tests/fixtures/langs/gorepo_deps.py (the module that requires this one),
              tests/test_provision_go.py (fetches from it), src/crb/provision/go.py (the recipe
              that reads it), tests/test_provision.py (the go.sum lines)
Tested by:    tests/test_provision_go.py
Touch when:   a test needs another module or version in the mirror (add it to ``VERSIONS``).
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import Path

MODULE = "example.com/dep"
GO_MOD = f"module {MODULE}\n\ngo 1.22\n"

VERSIONS: Mapping[str, Mapping[str, str]] = {
    "v1.0.0": {
        "go.mod": GO_MOD,
        "dep.go": 'package dep\n\n// Greeting says hello.\nfunc Greeting() string { return "hello" }\n',
    },
    "v1.1.0": {
        "go.mod": GO_MOD,
        "dep.go": (
            "package dep\n\n"
            '// Greeting says hello.\nfunc Greeting() string { return "hello" }\n\n'
            '// Farewell says goodbye.\nfunc Farewell() string { return "goodbye" }\n'
        ),
    },
}

_DATE = (2026, 1, 1, 0, 0, 0)


def _hash1(files: Mapping[str, bytes]) -> str:
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n".encode())
    return "h1:" + base64.b64encode(h.digest()).decode()


def zip_files(version: str) -> dict[str, bytes]:
    """The zip's entries: ``<module>@<version>/<file>`` → bytes."""
    return {f"{MODULE}@{version}/{n}": c.encode() for n, c in VERSIONS[version].items()}


def module_zip(version: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(zip_files(version).items()):
            info = zipfile.ZipInfo(name, date_time=_DATE)
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
    return buf.getvalue()


def go_sum(versions: Iterable[str]) -> str:
    """The ``go.sum`` lines for ``versions`` of :data:`MODULE` (zip hash and go.mod hash)."""
    lines = []
    for v in sorted(versions):
        lines.append(f"{MODULE} {v} {_hash1(zip_files(v))}")
        lines.append(f"{MODULE} {v}/go.mod {_hash1({'go.mod': GO_MOD.encode()})}")
    return "\n".join(lines) + "\n"


def build(root: Path, versions: Iterable[str] = tuple(VERSIONS)) -> Path:
    """Write the proxy tree under ``root`` and return it (``GOPROXY=file://<root>``)."""
    at = Path(root) / MODULE / "@v"
    at.mkdir(parents=True, exist_ok=True)
    vs = sorted(versions)
    (at / "list").write_text("\n".join(vs) + "\n", encoding="utf-8")
    for v in vs:
        (at / f"{v}.info").write_text(
            json.dumps({"Version": v, "Time": "2026-01-01T00:00:00Z"}), encoding="utf-8"
        )
        (at / f"{v}.mod").write_text(GO_MOD, encoding="utf-8")
        (at / f"{v}.zip").write_bytes(module_zip(v))
    return Path(root)


__all__ = ["GO_MOD", "MODULE", "VERSIONS", "build", "go_sum", "module_zip", "zip_files"]
