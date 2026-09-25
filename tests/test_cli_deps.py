"""``crb deps ls | verify | gc`` over a real bundle store (ADR-0019).

Navigation
----------
What it is:   The suite for the ``crb deps`` verb.
What it does: Pins that ``ls`` lists the sealed sets (text and ``--json``), that ``verify`` exits 0
              on intact sets and 1 with ``BUNDLE_INTEGRITY`` and the fix on a changed byte, and
              that ``gc`` never removes a ``--keep`` key.
How:          A store under ``tmp_path`` sealed by hand → ``crb.cli.main.main([...])``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/cli/commands/deps.py (under test), src/crb/provision/store.py (the store)
Tested by:    tests/test_cli_deps.py
Touch when:   a ``crb deps`` subcommand is added or its output changes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crb.cli.main import main
from crb.provision.store import BundleStore

K1, K2 = "dep_" + "a" * 64, "dep_" + "b" * 64


def _store(root: Path) -> BundleStore:
    store = BundleStore(root)
    for key, data in ((K1, b"one"), (K2, b"two" * 1000)):
        st = store.stage()
        (st / "out" / "gomod").mkdir()
        (st / "out" / "gomod" / "f").write_bytes(data)
        store.seal(
            st, {"lang": "go", "key": key, "recipe": "go.modcache.v1", "modules": {"m@v1": ""}}
        )
    return store


def test_ls_verify_and_gc(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = _store(tmp_path / "deps")
    assert main(["deps", "ls", "--store", str(store.root)]) == 0
    out = capsys.readouterr().out
    assert "2 sealed set(s)" in out and "go.modcache.v1" in out
    assert main(["deps", "ls", "--store", str(store.root), "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert {s["key"] for s in body["sets"]} == {K1, K2} and body["sets"][0]["holds"] == 1
    assert main(["deps", "verify", "--store", str(store.root)]) == 0
    assert "verified 2 of 2" in capsys.readouterr().out
    target = store.root / "go" / K2 / "gomod" / "f"
    target.chmod(0o644)
    target.write_bytes(b"tampered")
    target.chmod(0o444)
    assert main(["deps", "verify", "--store", str(store.root)]) == 1
    out = capsys.readouterr().out
    assert f"FAIL {K2}: BUNDLE_INTEGRITY" in out and "revoked" in out
    assert main(["deps", "gc", "--store", str(store.root), "--max-gb", "0", "--keep", K2]) == 0
    assert "removed 1 set(s)" in capsys.readouterr().out
    assert [s.key for s in store.sets()] == [K2]
