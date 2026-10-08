"""``crb deps ls | verify | gc`` — the sealed dependency sets on this worker (ADR-0019).

* ``ls`` lists every sealed set: language, key, size, digest, when it was sealed and what
  it holds.
* ``verify`` re-hashes every set (or the keys named) against the digest sealed into its
  ``bundle.json``; a mismatch or a set someone made writable is ``BUNDLE_INTEGRITY`` —
  exit 1, naming the set. With ``--quarantine`` it also does what a run does on its own
  (G-966): moves each damaged set to the store's ``.quarantine`` directory, with a record of
  why, and revokes every qualification in the database that cites it; the next run that
  needs the set fetches and seals it afresh. Nothing is ever deleted by hand.
* ``gc`` removes the oldest sets until the store is under ``--max-gb`` (default
  ``CRB_PROVISION__MAX_TOTAL_GB``), never a key named with ``--keep``.

The store is ``--store``, else ``CRB_PROVISION__STORE``, else ``<CRB_HOME>/deps``. Nothing
here fetches.

Navigation
----------
What it is:   The operator's view of the bundle store: list, verify and collect the sealed
              dependency sets.
What it does: Prints the sets (text or ``--json``); re-proves each digest and exits 1 on a
              ``BUNDLE_INTEGRITY`` with the fix, and with ``--quarantine`` moves a damaged
              set aside and revokes the qualifications that cite it; removes the oldest
              sets beyond a size cap, never a kept key. Never fetches.
How:          ``ProvisionConfig.from_env`` (or ``--store``) → ``BundleStore`` → ``sets`` /
              ``verify`` (``quarantine`` + ``crb.store.qualifications.revoke_citing``) /
              ``gc``.
Layer:        cli — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/provision/store.py (the store), src/crb/provision/config.py (where it is),
              src/crb/store/qualifications.py (``revoke_citing``), src/crb/cli/commands/users.py
              (``_open`` — the database ``crb serve`` reads),
              src/crb/cli/main.py (registers the verb),
              docs/OPERATOR.md#21-environment-setup--the-only-network-phase
              (when to run it)
Tested by:    tests/test_cli_deps.py, tests/test_provision_quarantine.py
Touch when:   never for a new repository; a new store operation gets a subcommand here.
"""

from __future__ import annotations

import argparse
import getpass
from pathlib import Path
from typing import Any

from crb.cli.commands import EXIT_NEGATIVE, EXIT_OK, CliError, print_json, print_lines
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
            sp.add_argument(
                "--quarantine",
                action="store_true",
                help="move each damaged set aside and revoke the qualifications that cite it",
            )
            sp.add_argument(
                "--database-url",
                default=None,
                help="the database whose qualifications are revoked (default: CRB_DATABASE_URL)",
            )
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


def _revoke(database_url: str | None, keys: list[str], reason: str) -> str:
    """Revoke every qualification citing ``keys`` in the database ``crb serve`` reads, and
    say what happened; a database that cannot be opened is said, never a failure — the next
    run revokes them itself when it finds the set gone (``BUNDLE_INTEGRITY``)."""
    from crb.cli.commands import users  # noqa: PLC0415 — the optional store layer, lazily

    try:
        from crb.core.deps import BUNDLE_INTEGRITY  # noqa: PLC0415
        from crb.store import qualifications as store_q  # noqa: PLC0415

        factory, where = users._open(database_url)
    except (CliError, ImportError) as exc:
        return f"qualifications not revoked here ({exc}); the next run revokes them itself"
    actor = f"cli:{getpass.getuser()}"
    with factory() as s:
        revoked = store_q.revoke_citing(s, keys, BUNDLE_INTEGRITY, actor, reason)
    return f"revoked {len(revoked)} qualification(s) in {where}"


def cmd_verify(args: argparse.Namespace) -> int:
    store, _ = _store(args)
    keys = list(args.keys) or [s.key for s in store.sets()]
    results: list[dict[str, str]] = []
    for key in keys:
        try:
            s = store.verify(key)
            results.append({"key": key, "status": "ok", "digest": s.digest})
        except ProvisionRefused as exc:
            row = {"key": key, "status": exc.code, "message": exc.message, "fix": exc.fix}
            if args.quarantine and store.find(key) is not None:
                row["quarantine"] = str(store.quarantine(key, exc.message))
            results.append(row)
    bad = [r for r in results if r["status"] != "ok"]
    moved = [r["key"] for r in bad if r.get("quarantine")]
    revoked = (
        _revoke(args.database_url, moved, "the sealed set failed its digest (crb deps verify)")
        if moved
        else ""
    )
    if args.json:
        print_json({"store": str(store.root), "results": results, "revoked": revoked})
    else:
        lines = [f"verified {len(results) - len(bad)} of {len(results)} set(s) in {store.root}"]
        for r in bad:
            lines.append(f"FAIL {r['key']}: {r['status']}: {r['message']} — {r['fix']}")
            if r.get("quarantine"):
                lines.append(f"  moved to {r['quarantine']}; it is never mounted again")
        if revoked:
            lines.append(revoked)
        elif bad and not args.quarantine:
            lines.append(
                "run crb deps verify --quarantine to move the damaged set(s) aside and revoke "
                "what cites them now; a run does the same when it meets one"
            )
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
