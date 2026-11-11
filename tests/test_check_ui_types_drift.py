"""scripts/check_ui_types_drift.py — the UI-types drift check, on fixtures and on this tree.

Navigation
----------
What it is:   Unit tests for the drift check between ui/src/api/types.ts and the API's
              OpenAPI schema.
What it does: Pins that the parser reads each exported interface's own depth-1 fields (not a
              nested object's, not a commented-out one, not cut short by a brace in a string
              literal), its optional marks and what it ``extends``; that a shape maps to ``X``,
              ``XOut``, ``X-Output`` or ``X-Input``
              but never to a free-form component with no properties; that an unknown field and
              a missing required field are each a finding and an inherited field is not
              missing; that ``--check`` fails on new drift, on a stale allowlist entry and on
              an entry with no reason, and passes when the list matches; that it fails when a
              committed mapping is lost (a server rename) or a new one is not recorded; and
              that this tree's types.ts and schema pass ``--check`` against the committed
              allowlist and mapped list, and CI's fresh-clone gates run it.
How:          Calls the parser and ``compare`` on small inline sources and schemas; drives
              ``main`` with injected text; one test builds the real schema from the app.
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   scripts/check_ui_types_drift.py (the code under test),
              scripts/ui_types_drift_allowlist.txt (the reviewed drift),
              scripts/ui_types_mapped.txt (the committed coverage),
              ui/src/api/types.ts (the real types the tree-level test parses),
              .github/workflows/ci.yml (the ``fresh-clone-gates`` line that runs ``--check``)
Tested by:    (this is a test file)
Touch when:   never for a new repository; the check learns a new mapping rule or finding kind
              (add its case here in the same change).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load() -> ModuleType:
    """Import the script as a module, by path, since `scripts/` is not a package."""
    spec = importlib.util.spec_from_file_location(
        "check_ui_types_drift", ROOT / "scripts" / "check_ui_types_drift.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


m = _load()

TS = """
/** A doc comment with a fake: field */
export interface Base {
  id: string
}

export interface Thing extends Base {
  name: string
  // gone: number
  /* also_gone: number */
  url?: 'https://example.invalid' | null
  nested: { inner: number; deeper: { x: string } }
  readonly 'quoted': boolean
}

export type Literal = {
  a: number; b?: string
}

export type Alias = 'x' | 'y'

export interface Page<T> {
  items: T[]
}
"""


def _schema(props: list[str], required: list[str] | None = None) -> dict[str, Any]:
    """A minimal OpenAPI component with the given property names and required list."""
    return {"properties": {p: {} for p in props}, "required": required or []}


def test_the_parser_reads_own_depth_one_fields_and_extends() -> None:
    shapes = m.parse_ts(TS)
    assert set(shapes) == {"Base", "Thing", "Literal", "Page"}
    thing = shapes["Thing"]
    assert dict(thing.fields) == {"name": False, "url": True, "nested": False, "quoted": False}
    assert thing.extends == ("Base",)
    assert dict(shapes["Literal"].fields) == {"a": False, "b": True}
    assert dict(shapes["Page"].fields) == {"items": False}
    assert set(m.all_fields(thing, shapes)) == {"id", "name", "url", "nested", "quoted"}


@pytest.mark.parametrize("literal", ["'}'", '"}"', "`}`", "'\\'}'", '"{"'])
def test_a_brace_inside_a_string_literal_does_not_end_the_body(literal: str) -> None:
    """A ``}`` in a string literal type is not the interface's end: later fields are read."""
    shapes = m.parse_ts(f"export interface Thing {{ tag: {literal}; removed?: string }}\n")
    assert dict(shapes["Thing"].fields) == {"tag": False, "removed": True}
    findings, _ = m.compare(shapes, {"Thing": _schema(["tag"], ["tag"])})
    assert [f.line for f in findings] == ["Thing.removed unknown-field"]


@pytest.mark.parametrize(
    "line",
    ["tag: 'a // b'", "tag: 'a /* b'", "tag: string // it's a { tag", "tag: string /* it's } */"],
)
def test_comment_markers_in_strings_and_quotes_in_comments_stay_local(line: str) -> None:
    """A ``//`` in a string is not a comment, a quote in a comment opens no string."""
    shapes = m.parse_ts(f"export interface A {{\n  {line}\n  y?: number\n}}\n" + TS)
    assert dict(shapes["A"].fields) == {"tag": False, "y": True}
    assert dict(shapes["Base"].fields) == {"id": False}


def test_a_shape_maps_to_a_component_that_declares_properties() -> None:
    schemas = {
        "A": _schema(["x"]),
        "BOut": _schema(["x"]),
        "C-Output": {"type": "object", "additionalProperties": True},
        "C-Input": _schema(["x"]),
        "D-Output": {"type": "object", "additionalProperties": True},
        "ErrorEnvelope": _schema(["error"]),
    }
    assert m.component_for("A", schemas) == "A"
    assert m.component_for("B", schemas) == "BOut"
    assert m.component_for("C", schemas) == "C-Input"
    assert m.component_for("D", schemas) is None  # a free-form dict says nothing
    assert m.component_for("ApiErrorEnvelope", schemas) == "ErrorEnvelope"
    assert m.component_for("Nope", schemas) is None


def test_compare_finds_unknown_and_missing_required_but_not_inherited() -> None:
    shapes = m.parse_ts(TS)
    schemas = {
        "Thing": _schema(["id", "name", "url", "nested", "quoted", "extra"], ["id", "extra"]),
        "Base": _schema(["id"], ["id"]),
        "Literal": _schema(["a"], ["a"]),
    }
    findings, unmapped = m.compare(shapes, schemas)
    assert [f.line for f in findings] == [
        "Literal.b unknown-field",
        "Thing.extra missing-required",
    ]
    assert unmapped == ["Page"]


def test_an_inherited_field_the_component_dropped_is_an_unknown_field() -> None:
    """The derived component lacks a field the base interface (and base component) still has."""
    shapes = m.parse_ts(
        "export interface Base { id: string; gone: string }\n"
        "export interface Kid extends Base { own: string }\n"
    )
    schemas = {
        "Base": _schema(["id", "gone"], ["id"]),
        "Kid": _schema(["id", "own"], ["id"]),
    }
    findings, _ = m.compare(shapes, schemas)
    assert [f.line for f in findings] == ["Kid.gone unknown-field"]


def _run(allowlist: str, schemas: dict[str, Any], mapped: str = "Literal Literal\n") -> int:
    """Run the check against in-memory inputs and return its exit status."""
    return int(
        m.main(
            ["--check"],
            schemas=schemas,
            types_text=TS,
            allowlist_text=allowlist,
            mapped_text=mapped,
        )
    )


SCHEMAS = {"Literal": _schema(["a"], ["a", "c"])}  # b unknown, c missing


def test_check_fails_on_new_drift_and_passes_when_listed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _run("", SCHEMAS) == 1
    out = capsys.readouterr().out
    assert "new drift: Literal.b unknown-field" in out
    assert "new drift: Literal.c missing-required" in out
    listed = "Literal.b unknown-field  # r\nLiteral.c missing-required  # r\n"
    assert _run(listed, SCHEMAS) == 0


def test_check_fails_on_a_stale_entry(capsys: pytest.CaptureFixture[str]) -> None:
    listed = (
        "Literal.b unknown-field  # r\nLiteral.c missing-required  # r\n"
        "Literal.a missing-required  # fixed long ago\n"
    )
    assert _run(listed, SCHEMAS) == 1
    assert "stale allowlist entry: Literal.a missing-required" in capsys.readouterr().out


@pytest.mark.parametrize(
    "line",
    ["Literal.b unknown-field\n", "Literal.b unknown-field  #   \n", "Literal.b typo  # r\n"],
)
def test_an_entry_without_a_reason_or_kind_is_refused(line: str) -> None:
    with pytest.raises(ValueError):
        m.read_allowlist(line)
    assert _run(line, SCHEMAS) == 1


def test_this_tree_passes_against_the_committed_allowlist(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The real schema, built offline from the app: today's drift is exactly the list."""
    assert m.main(["--check"]) == 0, capsys.readouterr().out


def test_ci_runs_the_check_in_the_fresh_clone_gates() -> None:
    import yaml

    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    cmd = ".venv/bin/python scripts/check_ui_types_drift.py --check"
    fresh = [str(s.get("run", "")) for s in ci["jobs"]["fresh-clone-gates"]["steps"]]
    assert any(cmd in r for r in fresh)


LISTED = "Literal.b unknown-field  # r\nLiteral.c missing-required  # r\n"


def test_check_fails_when_a_mapped_shape_stops_mapping(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A server-side rename of a response model must not drop its interface in silence."""
    assert _run(LISTED, SCHEMAS) == 0
    renamed = {"LiteralRenamed": SCHEMAS["Literal"]}
    assert _run("", renamed) == 1
    assert "coverage lost: Literal no longer maps to Literal (now unmapped)" in (
        capsys.readouterr().out
    )
    assert _run(LISTED, {"LiteralOut": SCHEMAS["Literal"]}) == 1  # mapped elsewhere: also lost
    assert "now LiteralOut" in capsys.readouterr().out


def test_check_fails_on_a_mapping_the_list_does_not_record(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _run(LISTED, SCHEMAS, mapped="") == 1
    assert "new mapping: Literal -> Literal" in capsys.readouterr().out
    with pytest.raises(ValueError):
        m.read_mapped("Literal\n")


def test_the_committed_mapped_list_is_the_coverage() -> None:
    committed = m.read_mapped(m.MAPPED.read_text("utf-8"))
    assert committed["ApiErrorEnvelope"] == "ErrorEnvelope"
    assert set(m.ALIASES) <= set(committed)  # every reviewed alias is compared
