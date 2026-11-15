"""``crb ctxset`` — store, show and compare context sets through the API.

A context set (ADR-0050) lives in the server's store, written only by ``POST /ctxsets``, so
this verb is an API client, not a reader of a local workdir: ``put FILE`` stores a
``crb.ctxset.v1`` or ``crb.ctxset.v2`` document, ``show NAME`` prints its metadata (never an
entry's text) and ``compare --control RUN --treatment RUN`` prints the paired, fail-closed
comparison. A hindsight treatment's ceiling banner (or a stated set's banner) is printed
first. ``lint FILE --clone DIR`` is the one offline verb: it parses a document and runs a
stated set's entries through ``req_guard`` against a local clone's gold view (ADR-0052), so a
drafter sees what a run would withhold before storing it.

Navigation
----------
What it is:   The ``crb ctxset`` verb: ``put``, ``show`` and ``compare`` over ``/ctxsets``,
              and the offline ``lint`` of a stated-requirement document.
What it does: Reads the API location and a local account from the environment the MCP
              server reads (``CRB_API_URL``, ``CRB_MCP_USERNAME``, ``CRB_MCP_PASSWORD``),
              sends the request and prints the API's answer; a refusal is a one-line
              ``CliError`` naming the API's code.
How:          :class:`crb.mcp.client.CrbApi` (login, CSRF, the error envelope), imported on
              use so a base install's CLI still loads; ``--json`` prints the API's JSON
              as-is.
Layer:        cli — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0050-context-set-arms.md,
              docs/adr/0052-stated-requirement-arms.md
Works with:   src/crb/server/routes/ctxsets.py (the routes), src/crb/mcp/client.py (the
              transport), src/crb/cli/main.py (the registration), docs/API.md (the
              ``/ctxsets`` routes and the refusal codes this command prints),
              src/crb/builders/brief.py (``req_guard``, ``gold_view`` for ``lint``)
Tested by:    tests/test_cli_ctxset.py, tests/test_cli_ctxset_lint.py
Touch when:   never for a new repository; the ``/ctxsets`` routes change shape (mirror
              docs/API.md#context-sets).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from crb.cli.commands import EXIT_OK, CliError, add_common, print_json, print_lines

if TYPE_CHECKING:
    from crb.mcp.client import CrbApi


def api_factory() -> CrbApi:
    """Build the API client; tests swap this name for one over FastAPI's ``TestClient``.

    The client is imported here, not at module load: ``crb.mcp`` needs the ``[mcp]`` extra
    (``mcp``, ``httpx``), and ``crb.cli.main`` imports this module, so a load-time import
    would stop every CLI verb on a base install.
    """
    from crb.mcp.client import CrbApi

    return CrbApi.from_env()


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``crb ctxset put|show|compare``."""
    p = sub.add_parser(
        "ctxset",
        help="context sets (measurement-only arms): store, show, compare — via the API",
        description="Context sets are measurement-only (ADR-0050): they never certify, "
        "license or route. Reads CRB_API_URL, CRB_MCP_USERNAME and CRB_MCP_PASSWORD.",
    )
    verbs = p.add_subparsers(dest="ctxset_verb", required=True)
    put = verbs.add_parser("put", help="store a crb.ctxset.v1 or v2 document (operator)")
    put.add_argument("file", help="the set's JSON file")
    add_common(put)
    put.set_defaults(func=cmd_put)
    show = verbs.add_parser("show", help="a stored set's metadata (never an entry's text)")
    show.add_argument("name", help="ctx.<source>.<hex12>")
    add_common(show)
    show.set_defaults(func=cmd_show)
    cmp_ = verbs.add_parser("compare", help="pair a control run with a context-set run")
    cmp_.add_argument("--control", required=True, help="the control run id")
    cmp_.add_argument("--treatment", required=True, help="the context-set run id")
    add_common(cmp_)
    cmp_.set_defaults(func=cmd_compare)
    lint = verbs.add_parser(
        "lint",
        help="offline: parse a set and run a stated set's entries through the leak guard",
        description="Parses FILE and, for a stated-requirement set, runs every entry through "
        "req_guard against DIR's gold view of its commit. Paths are split into source and "
        "tests by the generic test-path heuristic; the run's guard, over the registered "
        "task's own split, stays authoritative. Exit 2 when any entry would be withheld.",
    )
    lint.add_argument("file", help="the set's JSON file")
    lint.add_argument("--clone", required=True, help="a local clone holding every commit")
    add_common(lint)
    lint.set_defaults(func=cmd_lint)


def _call(fn: Callable[[CrbApi], Any]) -> Any:
    try:
        from crb.mcp.client import CrbApiError
    except ImportError as e:
        raise CliError(f"crb ctxset needs `pip install commit-replay-bench[mcp]` ({e})") from e
    api = api_factory()
    try:
        return fn(api)
    except CrbApiError as e:
        raise CliError(f"{e.status} {e.code}: {e.message}") from e
    finally:
        api.close()


def _meta_lines(d: dict[str, Any]) -> list[str]:
    lines = [f"{d['name']}  ({d['source']}, {d['tasks']} tasks, repo {d['repo']})"]
    lines.append(f"digest {d['digest']}")
    lines.append(f"arm    {d['arm']}  (measurement-only)")
    if d.get("matched_to"):
        lines.append(f"matched_to {d['matched_to']}")
    if d.get("drafter"):
        lines.append(f"drafter    {d['drafter']}")
    if d.get("stated"):
        saw = ",".join(d.get("saw") or []) or "-"
        lines.append(f"stated     {d.get('structure')}  saw {saw}  items {d.get('items_digest')}")
    return lines


def cmd_put(args: argparse.Namespace) -> int:
    path = Path(args.file)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise CliError(f"cannot read {path.name}: {e}") from e
    out = _call(lambda api: api.post("/ctxsets", json=doc))
    if args.json:
        print_json(out)
    else:
        print_lines(["stored" if out.get("stored") else "already stored", *_meta_lines(out)])
    return EXIT_OK


def cmd_show(args: argparse.Namespace) -> int:
    out = _call(lambda api: api.get(f"/ctxsets/{args.name}"))
    if args.json:
        print_json(out)
    else:
        print_lines(_meta_lines(out))
    return EXIT_OK


def compare_lines(d: dict[str, Any]) -> list[str]:
    """The comparison as text: the banner first (hindsight ceiling, or stated requirements),
    a stated pair's provenance next, then per side, the paired test, cost and drift."""
    lines = [str(d["banner"])] if d.get("banner") else []
    if d.get("provenance"):
        lines.append("provenance " + " ".join(f"{k}={v}" for k, v in d["provenance"].items()))
    if d.get("head_to_head"):
        lines.append("head_to_head: two structures of one items digest")
    for side in ("control", "treatment"):
        s = d[side]
        lines.append(
            f"{side:<9} {d[side + '_arm']}  k/n {s['k']}/{s['n']}  "
            f"Wilson [{s['ci_low']}, {s['ci_high']}]"
        )
    lines.append(f"b={d['b']} c={d['c']} exact McNemar p={d['p']}")
    if d.get("pending"):
        lines.append(f"PENDING {len(d['pending'])} task(s): no claim until complete")
    if d.get("dose_imbalance"):
        lines.append("dose_imbalance: the two sides delivered different doses (read ITT)")
    if d.get("stated"):
        from crb.core.ctx_compare import prov_strata_lines

        lines.extend(prov_strata_lines(d.get("prov_strata") or []))
    cost = d.get("cost") or {}
    paired = cost.get("paired_cost_usd_diff") or {}
    if paired.get("n") or paired.get("n_missing"):
        unpriced = f" (unpriced {paired['n_missing']})" if paired.get("n_missing") else ""
        lines.append(f"paired cost diff (usd) median {paired['median']} n {paired['n']}{unpriced}")
    if d.get("drift"):
        lines.append("drift: the two sides ran more than a week apart")
    return lines


def cmd_compare(args: argparse.Namespace) -> int:
    out = _call(
        lambda api: api.get("/ctxsets/compare", control=args.control, treatment=args.treatment)
    )
    if args.json:
        print_json(out)
    else:
        print_lines(compare_lines(out))
    return EXIT_OK


def lint_set(doc: object, clone: Path) -> list[tuple[str, list[str]]]:
    """``(task_id, reasons)`` per entry of a stated set; reasons empty when the entry would
    reach a brief. A parse refusal is a :class:`CliError`; a non-stated set has no entries
    to guard and answers ``[]``."""
    from crb.builders.brief import gold_view, req_guard
    from crb.core import ctxset
    from crb.core.git import GitError, GitRepo
    from crb.core.spec import is_test_path

    try:
        cset = ctxset.parse(doc)
    except ctxset.CtxSetRefused as refused:
        raise CliError(f"refused {refused.reason}: {refused.detail}") from refused
    if not cset.stated:
        return []
    repo = GitRepo(clone)
    out: list[tuple[str, list[str]]] = []
    for entry in cset.entries:
        if not entry.items:
            continue
        try:
            parent = repo.parent(entry.task_id)
            changed = repo.changed_files(entry.task_id)
        except GitError as err:
            raise CliError(f"{entry.task_id[:12]} is not readable in {clone.name}: {err}") from err
        tests = [p for p in changed if is_test_path(p)]
        srcs = [p for p in changed if not is_test_path(p)]
        # the view reads every changed path itself and computes the novel set from those
        # reads; a blob the commit or its parent holds but cannot be read is no view at all
        gold = gold_view(
            repo, parent=parent, commit=entry.task_id, src_paths=srcs, test_paths=tests
        )
        if gold is None:
            raise CliError(f"{entry.task_id[:12]}: a changed file is not readable in {clone.name}")
        out.append((entry.task_id, req_guard(entry.text, entry.items, cset.structure, gold)))
    return out


def cmd_lint(args: argparse.Namespace) -> int:
    path = Path(args.file)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise CliError(f"cannot read {path.name}: {e}") from e
    results = lint_set(doc, Path(args.clone))
    withheld = [(t, r) for t, r in results if r]
    if args.json:
        print_json({"entries": [{"task_id": t, "reasons": r} for t, r in results]})
    else:
        lines = [f"{t[:12]}  {'withheld ' + ','.join(r) if r else 'ok'}" for t, r in results]
        lines.append(f"{len(results) - len(withheld)}/{len(results)} entries pass the guard")
        print_lines(lines)
    if withheld:
        raise CliError(f"{len(withheld)} entr{'y' if len(withheld) == 1 else 'ies'} withheld")
    return EXIT_OK


__all__ = ["api_factory", "compare_lines", "lint_set", "register"]
