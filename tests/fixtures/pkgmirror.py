"""Offline package mirrors for the Python and Node recipes: fixture wheels and npm tarballs.

* :func:`build_pypi` writes a PEP 503 simple index of two pure-Python wheels of ``cfxdep``
  (``1.0.0``: ``greet``; ``1.1.0`` adds ``farewell``) — ``pip download --index-url
  file:///…`` reads it with no network;
* :func:`build_npm_tarballs` writes the two npm tarballs of ``cfxdep`` and returns their
  ``integrity`` strings (``sha512-…``, as a ``package-lock.json`` records them); a test fills
  an npm cache from them with ``npm cache add`` inside the Node image, with no network.

Everything is deterministic (fixed timestamps) so the hashes a lock commits are stable.

Navigation
----------
What it is:   The offline package mirrors the Python and Node provisioning tests fetch from.
What it does: Builds two versions of a tiny package as wheels (with a simple index and valid
              ``RECORD``) and as npm tarballs (with their ``sha512`` integrity), deterministically.
How:          ``zipfile`` / ``tarfile`` with fixed dates → files under the caller's root;
              ``hashlib`` for the ``--hash`` and ``integrity`` values.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   tests/fixtures/langs/pyrepo_deps.py and tests/fixtures/langs/noderepo_deps.py (the
              repositories that pin these), tests/test_provision_python.py and
              tests/test_provision_node.py (the fetches), src/crb/provision/python.py and
              src/crb/provision/node.py (the recipes that read them)
Tested by:    tests/test_provision_python.py, tests/test_provision_node.py
Touch when:   a provisioning test needs another package or version.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import Path

NAME = "cfxdep"
VERSIONS = ("1.0.0", "1.1.0")
_DATE = (2026, 1, 1, 0, 0, 0)


def _py_source(version: str) -> str:
    src = f'VERSION = "{version}"\n\n\ndef greet():\n    return "hello"\n'
    if version != "1.0.0":
        src += '\n\ndef farewell():\n    return "goodbye"\n'
    return src


def wheel_name(version: str) -> str:
    return f"{NAME}-{version}-py3-none-any.whl"


def wheel_bytes(version: str) -> bytes:
    di = f"{NAME}-{version}.dist-info"
    files = {
        f"{NAME}/__init__.py": _py_source(version).encode(),
        f"{di}/METADATA": f"Metadata-Version: 2.1\nName: {NAME}\nVersion: {version}\n".encode(),
        f"{di}/WHEEL": b"Wheel-Version: 1.0\nGenerator: crb-fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record = []
    for name, data in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        record.append(f"{name},sha256={digest},{len(data)}")
    record.append(f"{di}/RECORD,,")
    files[f"{di}/RECORD"] = ("\n".join(record) + "\n").encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            info = zipfile.ZipInfo(name, date_time=_DATE)
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
    return buf.getvalue()


def wheel_hash(version: str) -> str:
    """``sha256:<hex>`` as a requirements lock's ``--hash`` records it."""
    return "sha256:" + hashlib.sha256(wheel_bytes(version)).hexdigest()


def build_pypi(root: Path) -> Path:
    """A simple index at ``root`` (``--index-url file://<root>``)."""
    pkg = Path(root) / NAME
    pkg.mkdir(parents=True, exist_ok=True)
    links = []
    for v in VERSIONS:
        data = wheel_bytes(v)
        (pkg / wheel_name(v)).write_bytes(data)
        links.append(
            f'<a href="{wheel_name(v)}#sha256={hashlib.sha256(data).hexdigest()}">{wheel_name(v)}</a>'
        )
    (pkg / "index.html").write_text(
        "<!DOCTYPE html><html><body>\n" + "\n".join(links) + "\n</body></html>\n", encoding="utf-8"
    )
    (Path(root) / "index.html").write_text(
        f'<!DOCTYPE html><html><body><a href="{NAME}/">{NAME}</a></body></html>\n',
        encoding="utf-8",
    )
    return Path(root)


def _js_source(version: str) -> str:
    src = 'exports.greet = () => "hello";\n'
    if version != "1.0.0":
        src += 'exports.farewell = () => "goodbye";\n'
    return src


def tarball_name(version: str) -> str:
    return f"{NAME}-{version}.tgz"


def tarball_bytes(version: str) -> bytes:
    files = {
        "package/package.json": json.dumps(
            {"name": NAME, "version": version, "main": "index.js"}, indent=2
        ).encode(),
        "package/index.js": _js_source(version).encode(),
    }
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as t:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(data), 1767225600, 0o644
            t.addfile(info, io.BytesIO(data))
    buf = io.BytesIO()
    import gzip

    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        gz.write(raw.getvalue())
    return buf.getvalue()


def integrity(version: str) -> str:
    """The ``sha512-<base64>`` a ``package-lock.json`` records for the tarball."""
    return "sha512-" + base64.b64encode(hashlib.sha512(tarball_bytes(version)).digest()).decode()


def build_npm_tarballs(root: Path) -> dict[str, str]:
    """Write both tarballs under ``root``; ``{version: integrity}``."""
    Path(root).mkdir(parents=True, exist_ok=True)
    out = {}
    for v in VERSIONS:
        (Path(root) / tarball_name(v)).write_bytes(tarball_bytes(v))
        out[v] = integrity(v)
    return out


__all__ = [
    "NAME",
    "VERSIONS",
    "build_npm_tarballs",
    "build_pypi",
    "integrity",
    "tarball_bytes",
    "tarball_name",
    "wheel_bytes",
    "wheel_hash",
    "wheel_name",
]
