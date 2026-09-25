"""The bundle store: sealed, read-only, content-addressed, and the only maker of a mount (D2).

Navigation
----------
What it is:   The suite for ``crb.provision.store.BundleStore``.
What it does: Pins that a seal is atomic and leaves nothing writable; that one changed byte is
              ``BUNDLE_INTEGRITY``; that garbage collection never removes a cited key; that a
              mount outside a registered store or without a ``dep_`` key is refused at
              construction and again by ``validate_mount``; and that two concurrent seals of
              one key keep exactly one set.
How:          A store under ``tmp_path``; stages filled by hand; threads for the race.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/provision/store.py (under test), src/crb/core/deps.py (``BundleMount``,
              ``validate_mount``), tests/test_provision.py (the keys a store is addressed by)
Tested by:    tests/test_provision_store.py
Touch when:   the store's layout, manifest schema or sealing rule changes.
"""

from __future__ import annotations

import json
import os
import stat
import threading
from pathlib import Path

import pytest

from crb.core.deps import BundleMount, ProvisionRefused, validate_mount
from crb.provision.store import MANIFEST, BundleStore, output_digest

KEY = "dep_" + "1" * 64
KEY2 = "dep_" + "2" * 64


def _fill(store: BundleStore, files: dict[str, bytes]) -> Path:
    st = store.stage()
    for rel, data in files.items():
        p = st / "out" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return st


def _writable(p: Path) -> bool:
    return bool(p.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def test_seal_is_atomic_and_read_only(tmp_path: Path) -> None:
    store = BundleStore(tmp_path / "deps")
    st = _fill(store, {"gomod/a/b.txt": b"b", "gomod/c.txt": b"c"})
    assert oct(st.stat().st_mode & 0o777) == "0o700"
    sealed = store.seal(st, {"lang": "go", "key": KEY, "recipe": "go.modcache.v1"})
    assert not st.exists(), "the stage must be gone once sealed"
    assert sealed.path == store.root / "go" / KEY
    manifest = json.loads((sealed.path / MANIFEST).read_text())
    assert manifest["schema"] == "crb.bundle/1" and manifest["key"] == KEY
    assert manifest["digest"] == output_digest(sealed.path)[0] and manifest["bytes"] == 2
    for dirpath, dirnames, filenames in os.walk(sealed.path):
        for name in [*dirnames, *filenames]:
            assert not _writable(Path(dirpath) / name), Path(dirpath) / name
    assert not _writable(sealed.path)
    with pytest.raises(PermissionError):
        (sealed.path / "gomod" / "c.txt").write_bytes(b"tampered")
    # the store hands out a read-only mount that validates at use
    m = store.mount(KEY, "go", "gomod", "/deps/gomod")
    validate_mount(m)
    assert store.verify(KEY).digest == manifest["digest"]


def test_a_changed_byte_is_bundle_integrity(tmp_path: Path) -> None:
    store = BundleStore(tmp_path / "deps")
    sealed = store.seal(_fill(store, {"site/x.py": b"x = 1\n"}), {"lang": "python", "key": KEY})
    target = sealed.path / "site" / "x.py"
    target.chmod(0o644)
    target.write_bytes(b"x = 2\n")
    target.chmod(0o444)
    with pytest.raises(ProvisionRefused) as ei:
        store.verify(KEY)
    assert ei.value.code == "BUNDLE_INTEGRITY" and ei.value.scope == "run"
    assert "does not match" in ei.value.message
    # a set made writable again is not sealed either
    sealed2 = store.seal(_fill(store, {"site/y.py": b"y\n"}), {"lang": "python", "key": KEY2})
    (sealed2.path / "site").chmod(0o755)
    with pytest.raises(ProvisionRefused, match="writable"):
        store.verify(KEY2)


def test_gc_keeps_every_cited_key(tmp_path: Path) -> None:
    store = BundleStore(tmp_path / "deps")
    keys = [f"dep_{str(i) * 64}" for i in range(3, 7)]
    for k in keys:
        store.seal(_fill(store, {"f": b"x" * 1024}), {"lang": "go", "key": k})
    store.stage()  # a stale stage from a crashed fetch
    removed = store.gc(keep={keys[0], keys[2]}, max_total_gb=0)
    assert set(removed) == {keys[1], keys[3]}
    assert {s.key for s in store.sets()} == {keys[0], keys[2]}
    assert not any((store.root / ".staging").iterdir())
    assert store.gc(keep=set(), max_total_gb=1) == []


def test_a_mount_outside_the_store_or_without_a_key_name_is_refused(tmp_path: Path) -> None:
    store = BundleStore(tmp_path / "deps")
    sealed = store.seal(_fill(store, {"gomod/x": b"x"}), {"lang": "go", "key": KEY})
    outside = tmp_path / "elsewhere" / "go" / KEY / "gomod"
    outside.mkdir(parents=True)
    with pytest.raises(ValueError, match="registered bundle store"):
        BundleMount(outside, "/deps/gomod", KEY)
    with pytest.raises(ValueError, match="not a dep_"):
        BundleMount(sealed.path / "gomod", "/deps/gomod", "dep_notahash")
    with pytest.raises(ValueError, match="directory of key"):
        BundleMount(sealed.path / "gomod", "/deps/gomod", KEY2)
    with pytest.raises(ValueError, match="container path"):
        BundleMount(sealed.path / "gomod", "/etc", KEY)
    with pytest.raises(ProvisionRefused):
        store.mount(KEY2, "go", "gomod", "/deps/gomod")  # not sealed here
    # a forged mount (construction bypassed) is still refused at use
    forged = object.__new__(BundleMount)
    object.__setattr__(forged, "host_path", outside)
    object.__setattr__(forged, "container_path", "/deps/gomod")
    object.__setattr__(forged, "key", KEY)
    with pytest.raises(ValueError, match="registered bundle store"):
        validate_mount(forged)
    # and a sealed set somebody made writable is refused at use
    ok = store.mount(KEY, "go", "gomod", "/deps/gomod")
    (sealed.path / "gomod").chmod(0o755)
    with pytest.raises(ValueError, match="not sealed"):
        validate_mount(ok)


def test_a_concurrent_seal_keeps_one(tmp_path: Path) -> None:
    store = BundleStore(tmp_path / "deps")
    stages = [_fill(store, {"gomod/f": f"writer {i}".encode()}) for i in range(4)]
    results = []
    barrier = threading.Barrier(len(stages))

    def seal(st: Path) -> None:
        barrier.wait()
        results.append(store.seal(st, {"lang": "go", "key": KEY}))

    threads = [threading.Thread(target=seal, args=(st,)) for st in stages]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 4
    assert len({r.digest for r in results}) == 1, "every caller sees the one winner"
    assert [s.key for s in store.sets()] == [KEY]
    assert not any((store.root / ".staging").iterdir()), "losers discard their stage"
    store.verify(KEY)
