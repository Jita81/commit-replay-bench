"""``crb deps ls | verify | gc`` — the sealed dependency sets on this worker (ADR-0019).

* ``ls`` lists every sealed set: language, key, size, digest, when it was sealed and what
  it holds.
* ``verify`` re-hashes every set (or the keys named) against the digest sealed into its
  ``bundle.json``; a mismatch or a set someone made writable is ``BUNDLE_INTEGRITY`` —
  exit 1, with the fix: delete that set's directory from the store and the next run
  fetches and seals it again (verify itself removes nothing).
* ``gc`` removes the oldest sets until the store is under ``--max-gb`` (default
  ``CRB_PROVISION__MAX_TOTAL_GB``), never a key named with ``--keep``.

The store is ``--store``, else ``CRB_PROVISION__STORE``, else ``<CRB_HOME>/deps``. Nothing
here fetches.

Navigation
----------
What it is:   The operator's view of the bundle store: list, verify and collect the sealed
              dependency sets.
What it does: Prints the sets (text or ``--json``); re-proves each digest and exits 1 on a
              ``BUNDLE_INTEGRITY`` with the fix; removes the oldest sets beyond a size cap,
              never a kept key. Never fetches.
How:          ``ProvisionConfig.from_env`` (or ``--store``) → ``BundleStore`` → ``sets`` /
              ``verify`` / ``gc``.
Layer:        cli — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/provision/store.py (the store), src/crb/provision/config.py (where it is),
              src/crb/cli/main.py (registers the verb), docs/OPERATOR.md#21-environment-setup--the-only-network-phase
              (when to run it)
Tested by:    tests/test_cli_deps.py
Touch when:   never for a new repository; a new store operation gets a subcommand here.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from crb.cli.commands import EXIT_NEGATIVE, EXIT_OK, print_json, print_lines
from crb.core.deps import ProvisionRefused
from crb.provision.config import ProvisionConfig
from crb.provision.store import BundleStore


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``crb deps ls | verify | gc``."""
    p = sub.add_parser("deps", help="the sealed dependency sets (list, verify, collect)")
    ds = p.add_subparsers(dest="deps_cmd", metavar="<subcommand>")
    for name, helptext, func in (
        ("ls", "list every sealed set", cmd_ls),
        ("verify", "re-hash sealed sets against their digests", cmd_verify),
        ("gc", "remove the oldest sets beyond a size cap", cmd_gc),
    ):
        sp = ds.add_parser(name, help=helptext)
        sp.add_argument("--store", default=None, help="the store (default: CRB_PROVISION__STORE)")
        sp.add_argument("--json", action="store_true", help="machine-readable output")
        if name == "verify":
            sp.add_argument("keys", nargs="*", help="keys to verify (default: every set)")
        if name == "gc":
            sp.add_argument("--keep", action="append", default=[], help="a key never removed")
            sp.add_argument("--max-gb", type=float, default=None, help="the size cap in GB")
        sp.set_defaults(func=func)
    p.set_defaults(func=lambda args: _usage(p))


def _usage(p: argparse.ArgumentParser) -> int:
    p.print_help()
    return 2


def _store(args: argparse.Namespace) -> tuple[BundleStore, ProvisionConfig]:
    cfg = ProvisionConfig.from_env()
    root = Path(args.store).expanduser() if args.store else cfg.store
    return BundleStore(root), cfg


def cmd_ls(args: argparse.Namespace) -> int:
    store, _ = _store(args)
    rows: list[dict[str, Any]] = [
        {
            "lang": s.lang,
            "key": s.key,
            "bytes": s.bytes,
            "digest": s.digest,
            "created": s.manifest.get("created", ""),
            "recipe": s.manifest.get("recipe", ""),
            "holds": len(s.manifest.get("modules") or s.manifest.get("packages") or {}),
        }
        for s in store.sets()
    ]
    if args.json:
        print_json({"store": str(store.root), "sets": rows})
        return EXIT_OK
    lines = [f"store {store.root} · {len(rows)} sealed set(s)"]
    for r in rows:
        lines.append(
            f"{r['lang']:<7} {r['key'][:20]}…  {r['bytes'] / 2**20:8.1f} MB  "
            f"{r['holds']:>4} held  {r['recipe']:<16} {r['created']}"
        )
    print_lines(lines)
    return EXIT_OK


def cmd_verify(args: argparse.Namespace) -> int:
    store, _ = _store(args)
    keys = list(args.keys) or [s.key for s in store.sets()]
    results: list[dict[str, str]] = []
    for key in keys:
        try:
            s = store.verify(key)
            results.append({"key": key, "status": "ok", "digest": s.digest})
        except ProvisionRefused as exc:
            results.append({"key": key, "status": exc.code, "message": exc.message, "fix": exc.fix})
    bad = [r for r in results if r["status"] != "ok"]
    if args.json:
        print_json({"store": str(store.root), "results": results})
    else:
        lines = [f"verified {len(results) - len(bad)} of {len(results)} set(s) in {store.root}"]
        for r in bad:
            lines.append(f"FAIL {r['key']}: {r['status']}: {r['message']} — {r['fix']}")
        print_lines(lines)
    return EXIT_NEGATIVE if bad else EXIT_OK


def cmd_gc(args: argparse.Namespace) -> int:
    store, cfg = _store(args)
    cap = args.max_gb if args.max_gb is not None else cfg.max_total_gb
    removed = store.gc(keep=set(args.keep), max_total_gb=cap)
    if args.json:
        print_json({"store": str(store.root), "removed": removed, "max_gb": cap})
    else:
        print_lines([f"removed {len(removed)} set(s) to stay under {cap} GB", *removed])
    return EXIT_OK


__all__ = ["cmd_gc", "cmd_ls", "cmd_verify", "register"]
