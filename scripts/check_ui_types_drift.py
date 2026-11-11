#!/usr/bin/env python3
"""The UI-types drift check — ui/src/api/types.ts against the API's own OpenAPI schema.

``ui/src/api/types.ts`` is hand-written: every interface names the fields the server sends,
and nothing compared the two, so a field renamed or dropped on the server stayed in the UI's
types (and every fixture typed by them) until a screen showed a blank. This check builds the
OpenAPI document offline — it imports the FastAPI app and calls ``.openapi()``: no server, no
network, no database, no secret — and compares, for each exported interface in types.ts whose
name maps to a schema component, two things a reader can trust:

- ``unknown-field``: a field types.ts declares that the schema component does not have;
- ``missing-required``: a field the schema component requires that types.ts (with the
  interfaces it ``extends``) does not declare.

It does not compare field types, and it says nothing about an interface with no component of
the same name (the list of those is printed with ``--list``, so the coverage is visible). A
name maps to the reviewed entry in ``ALIASES``, else the first of ``<name>``, ``<name>Out``,
``<name>-Output`` and ``<name>-Input`` (the halves of a model Pydantic splits) that declares
properties: a component with none (a free-form ``dict``) says nothing a field can drift from.

The drift that existed when the check landed is recorded in
``scripts/ui_types_drift_allowlist.txt``, one line per finding with the reason it is
tolerated. The check fails on a finding that is not on the list, and on a list entry that no
longer drifts (so the list only shrinks, like ``scripts/code_map_onboarding_baseline.txt``).
The coverage is committed too: ``scripts/ui_types_mapped.txt`` lists every interface compared
and its component, and the check fails when a listed interface stops mapping to its component
(a response model renamed on the server would otherwise leave the comparison in silence) or
when a mapping appears that the list does not record.

    python scripts/check_ui_types_drift.py --check   # CI: exit 1 on new drift, a stale entry
                                                     # or a change in the mapped shapes
    python scripts/check_ui_types_drift.py --list    # every finding and every unmapped type

Navigation
----------
What it is:   The drift check between the UI's hand-written wire types and the API's OpenAPI
              schema (CI's ``fresh-clone`` gates run ``--check``; so does the ``test`` job,
              through its unit test).
What it does: Parses each exported interface (and object-literal type alias) of
              ui/src/api/types.ts into its field names, maps it to an OpenAPI schema component,
              reports fields the component lacks and required fields types.ts lacks, and in
              ``--check`` mode fails on a finding not in the allowlist, an allowlist entry
              that no longer drifts, or a mapping that differs from the committed list.
How:          Comments stripped, braces counted, only depth-1 ``name?:`` declarations read;
              ``create_app(Settings(env="dev")).openapi()`` for the schema (needs the server
              extra; the parser and the comparison are stdlib only).
Layer:        deploy — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   ui/src/api/types.ts (the types it reads), src/crb/server/app.py (``create_app``,
              whose ``.openapi()`` it compares against), scripts/ui_types_drift_allowlist.txt
              (the reviewed drift), scripts/ui_types_mapped.txt (the committed coverage),
              .github/workflows/ci.yml (the ``fresh-clone-gates`` line)
Tested by:    tests/test_check_ui_types_drift.py
Touch when:   never for a new repository (it compares this repository's own UI and API); a
              response model is renamed so an interface stops mapping (add it to ``ALIASES``
              and keep its line in scripts/ui_types_mapped.txt);
              a field is added to or removed from either side (fix the side that is wrong, and
              delete the allowlist line the fix retires).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crb.server.app import create_app
from crb.server.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
TYPES_TS = ROOT / "ui" / "src" / "api" / "types.ts"
ALLOWLIST = Path(__file__).resolve().parent / "ui_types_drift_allowlist.txt"
MAPPED = Path(__file__).resolve().parent / "ui_types_mapped.txt"

#: Interfaces whose component name is not mechanical (``X``, ``XOut``, ``X-Output``),
#: each read against the route that returns it. Add one only after reading that route.
ALIASES: dict[str, str] = {
    "ApiErrorEnvelope": "ErrorEnvelope",
    "CapabilityMap": "CapabilityMapWithControlsOut",  # GET /capability-map
    "FactoryBacklogItem": "BacklogItemOut",  # GET /factory/backlog items
    "FactoryRefusal": "RefusalOut",  # a factory task's refusal
    "FactoryWayForward": "WayForwardOut",  # a factory task's way forward
    "GitHubInstallation": "InstallationOut",  # POST /github/installations/sync
    "LedgerDisqualifiedBuilder": "DisqualifiedBuilderOut",  # the ledger's by_builder rows
    "RoutingPolicy": "RoutingPolicyWithControlsOut",  # the policy of /capability-map, /routes
}

KINDS = ("unknown-field", "missing-required")

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"(^|[ \t])//[^\n]*", re.MULTILINE)
_HEAD = re.compile(
    r"^export\s+(?:interface\s+(?P<iname>\w+)(?:<[^>{]*>)?(?:\s+extends\s+(?P<ext>[^{]+?))?\s*\{"
    r"|type\s+(?P<tname>\w+)(?:<[^>=]*>)?\s*=\s*\{)",
    re.MULTILINE,
)
_FIELD = re.compile(
    r"(?:^|[;,{])\s*(?:readonly\s+)?(?P<q>['\"]?)(?P<name>[A-Za-z_$][\w$]*)(?P=q)"
    r"\s*(?P<opt>\?)?\s*:",
    re.MULTILINE,
)


@dataclass(frozen=True)
class TsShape:
    """One exported object shape of types.ts: its own fields (name → optional) and the local
    names it ``extends``. Inherited fields are resolved by ``all_fields``, not stored."""

    name: str
    fields: Mapping[str, bool]
    extends: tuple[str, ...] = ()


@dataclass(frozen=True, order=True)
class Finding:
    """One drift: ``kind`` is one of ``KINDS``; ``key`` is ``Interface.field``."""

    key: str
    kind: str
    detail: str = ""

    @property
    def line(self) -> str:
        return f"{self.key} {self.kind}"


def strip_comments(text: str) -> str:
    """types.ts with every ``/* */`` and ``//`` comment blanked (a ``//`` glued to a word —
    ``'https://…'`` — is kept: it is not a comment)."""
    text = _BLOCK_COMMENT.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
    return _LINE_COMMENT.sub(lambda m: m.group(1), text)


def _body(text: str, open_at: int) -> str:
    """The text between the ``{`` at ``open_at`` and its matching ``}``, with everything at
    depth 2 or deeper blanked, so only the shape's own declarations remain. A brace inside a
    string literal (``'}'``, ``"{"``, a template literal; escapes honoured) is not counted."""
    depth = 0
    out: list[str] = []
    quote = ""  # the open string literal's quote character, "" outside one
    escaped = False
    for ch in text[open_at:]:
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = ""
        elif ch in "'\"`":
            quote = ch
        elif ch == "{":
            depth += 1
            if depth == 1:
                out.append("{")
                continue
        elif ch == "}":
            depth -= 1
            if depth == 0:
                break
        out.append(ch if depth == 1 else (" " if ch != "\n" else "\n"))
    return "".join(out)


def parse_ts(text: str) -> dict[str, TsShape]:
    """Every exported ``interface`` and ``type X = { … }`` of a types file, by name."""
    clean = strip_comments(text)
    shapes: dict[str, TsShape] = {}
    for m in _HEAD.finditer(clean):
        name = m.group("iname") or m.group("tname")
        body = _body(clean, m.end() - 1)
        fields = {f.group("name"): bool(f.group("opt")) for f in _FIELD.finditer(body)}
        ext = tuple(
            e.strip().split("<", 1)[0] for e in (m.group("ext") or "").split(",") if e.strip()
        )
        shapes[name] = TsShape(name, fields, ext)
    return shapes


def all_fields(shape: TsShape, shapes: Mapping[str, TsShape]) -> dict[str, bool]:
    """The shape's fields with every local interface it ``extends`` (transitively) merged in."""
    out: dict[str, bool] = {}
    seen: set[str] = set()
    stack = [shape]
    while stack:
        s = stack.pop()
        if s.name in seen:
            continue
        seen.add(s.name)
        for k, v in s.fields.items():
            out.setdefault(k, v)
        stack.extend(shapes[e] for e in s.extends if e in shapes)
    return out


def component_for(name: str, schemas: Mapping[str, Any]) -> str | None:
    """The schema component a types.ts name maps to, or None when it maps to none."""
    if name in ALIASES:
        return ALIASES[name] if ALIASES[name] in schemas else None
    for candidate in (name, f"{name}Out", f"{name}-Output", f"{name}-Input"):
        if (schemas.get(candidate) or {}).get("properties"):
            return candidate
    return None


def mapping(shapes: Mapping[str, TsShape], schemas: Mapping[str, Any]) -> dict[str, str]:
    """``{interface: component}`` for every shape that maps to a component (the coverage)."""
    out = {name: component_for(name, schemas) for name in sorted(shapes)}
    return {name: comp for name, comp in out.items() if comp is not None}


def read_mapped(text: str) -> dict[str, str]:
    """The committed coverage: ``{interface: component}``, one ``Interface Component`` per line."""
    out: dict[str, str] = {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            raise ValueError(f"mapped list line {n}: want 'Interface Component'")
        out[parts[0]] = parts[1]
    return out


def check_coverage(current: Mapping[str, str], committed: Mapping[str, str]) -> list[str]:
    """Each coverage error: a committed interface that no longer maps to its component (a
    server rename would otherwise drop it from the comparison in silence), and a new mapping
    the committed list does not record (so the list is the coverage, exactly)."""
    errors = [
        f"coverage lost: {name} no longer maps to {comp} "
        f"(now {current.get(name) or 'unmapped'}) — add an ALIASES entry after reading the "
        "route, or change its line in scripts/ui_types_mapped.txt"
        for name, comp in sorted(committed.items())
        if current.get(name) != comp
    ]
    errors += [
        f"new mapping: {name} -> {comp} is not in scripts/ui_types_mapped.txt — add the line"
        for name, comp in sorted(current.items())
        if name not in committed
    ]
    return errors


def compare(
    shapes: Mapping[str, TsShape], schemas: Mapping[str, Any]
) -> tuple[list[Finding], list[str]]:
    """``(findings, unmapped)``: every drift between a mapped shape and its component, and the
    names of shapes that map to no component (not compared — reported so it is visible)."""
    findings: list[Finding] = []
    unmapped: list[str] = []
    for name in sorted(shapes):
        comp = component_for(name, schemas)
        if comp is None:
            unmapped.append(name)
            continue
        schema = schemas[comp]
        props = set((schema.get("properties") or {}).keys())
        required = set(schema.get("required") or [])
        mine = all_fields(shapes[name], shapes)
        for field_name in sorted(mine):  # inherited fields too: a component can drop one
            if field_name not in props:
                findings.append(
                    Finding(f"{name}.{field_name}", "unknown-field", f"not a property of {comp}")
                )
        for field_name in sorted(required - set(mine)):
            findings.append(
                Finding(f"{name}.{field_name}", "missing-required", f"required by {comp}")
            )
    return findings, unmapped


def openapi_schemas() -> dict[str, Any]:
    """The API's schema components, built offline from the app (no server, no network, no
    database: ``create_app`` opens nothing until its lifespan runs, and ``env="dev"`` makes
    an ephemeral signing key, so no secret is read)."""
    doc = create_app(Settings(env="dev")).openapi()
    return dict(doc.get("components", {}).get("schemas", {}))


def read_allowlist(text: str) -> dict[str, str]:
    """``{"Interface.field kind": reason}``. Each entry is ``Interface.field kind  # reason``;
    an entry without a reason, or with an unknown kind, is an error — the list is reviewed."""
    out: dict[str, str] = {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        entry, sep, reason = line.partition("#")
        parts = entry.split()
        if len(parts) != 2 or parts[1] not in KINDS:
            raise ValueError(f"allowlist line {n}: want 'Interface.field <kind>  # reason'")
        if not sep or not reason.strip():
            raise ValueError(f"allowlist line {n}: {entry.strip()!r} has no reason")
        out[" ".join(parts)] = reason.strip()
    return out


def check(findings: Sequence[Finding], allowed: Mapping[str, str]) -> list[str]:
    """Each error ``--check`` reports: a finding not allowlisted, and an allowlisted entry
    that no longer drifts (delete its line — the list only shrinks)."""
    lines = {f.line for f in findings}
    errors = [
        f"new drift: {f.line} ({f.detail}) — fix types.ts or the schema, never just allowlist"
        for f in findings
        if f.line not in allowed
    ]
    errors += [
        f"stale allowlist entry: {entry} no longer drifts — delete its line"
        for entry in sorted(set(allowed) - lines)
    ]
    return errors


def main(
    argv: Sequence[str] | None = None,
    *,
    schemas: Mapping[str, Any] | None = None,
    types_text: str | None = None,
    allowlist_text: str | None = None,
    mapped_text: str | None = None,
) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="fail on new drift or a stale entry")
    mode.add_argument("--list", action="store_true", help="print every finding and unmapped type")
    args = ap.parse_args(argv)

    shapes = parse_ts(types_text if types_text is not None else TYPES_TS.read_text("utf-8"))
    schemas = schemas if schemas is not None else openapi_schemas()
    findings, unmapped = compare(shapes, schemas)
    if args.list:
        for f in findings:
            print(f"{f.line}  # {f.detail}")
        print(f"# {len(shapes) - len(unmapped)} of {len(shapes)} types.ts shapes map to a schema")
        print(f"# unmapped (not compared): {', '.join(unmapped)}")
        return 0
    try:
        allowed = read_allowlist(
            allowlist_text if allowlist_text is not None else ALLOWLIST.read_text("utf-8")
        )
        committed = read_mapped(
            mapped_text if mapped_text is not None else MAPPED.read_text("utf-8")
        )
    except ValueError as e:
        print(f"::error::{e}")
        return 1
    errors = check(findings, allowed) + check_coverage(mapping(shapes, schemas), committed)
    for err in errors:
        print(f"::error::{err}")
    print(
        f"ui types drift: {len(shapes) - len(unmapped)} of {len(shapes)} shapes compared, "
        f"{len(findings)} finding(s), {len(allowed)} allowlisted, {len(errors)} error(s)"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
