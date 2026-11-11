"""The anchor format and its checks — pure, no ledger, no database.

Navigation
----------
What it is:   Unit tests for ``crb.core.anchor``.
What it does: Pins the file's shape and its determinism, the deterministic name, the check
              that passes on growth and fails on a rewritten or shortened chain, the
              directory's anchor chain (a deleted or edited anchor is named, a malformed
              predecessor link is a fault, not an exception), and the create-only write
              that never overwrites; an anchor without its source's chains or any row is
              refused on read and never built.
How:          Dict-built anchors, a ``hash_at`` over plain lists, ``tmp_path`` for the files.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0029-the-audit-trail-is-hash-chained.md
Works with:   src/crb/core/anchor.py (under test), tests/test_cli_ledger_anchor.py (the same
              checks through the CLI), docs/LEDGER-ANCHORS.md (what the checks are for)
Tested by:    tests/test_anchor.py
Touch when:   never for a new repository; the anchor format or a check changes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crb.core.anchor import (
    ANCHOR_SCHEMA,
    AnchorError,
    ChainHead,
    anchor_bytes,
    anchor_name,
    build_anchor,
    check_anchor,
    check_anchor_links,
    is_inside,
    load_anchor,
    load_anchor_dir,
    parse_anchor,
    write_anchor,
)

H = [f"{i:064x}" for i in range(1, 10)]


def _anchor(rows: int, *, previous: tuple[str, str] | None = None, at: str = "T") -> dict:
    return build_anchor(
        source="jsonl",
        chains={"grades": ChainHead(rows, H[rows - 1])},
        apparatus="2.5",
        crb_version="x",
        created_at=at,
        previous=previous,
    )


def _hash_at(hashes: list[str]):  # type: ignore[no-untyped-def]
    return lambda chain, n: hashes[n - 1] if chain == "grades" and n <= len(hashes) else None


def test_the_file_is_self_describing_and_deterministic() -> None:
    a = _anchor(3)
    assert a["schema"] == ANCHOR_SCHEMA and a["signed"] is False and a["previous_anchor"] is None
    assert a["chains"] == {"grades": {"rows": 3, "head_row_hash": H[2]}}
    assert "Unsigned" in a["note"] and "LEDGER-ANCHORS" in a["note"]
    assert anchor_bytes(a) == anchor_bytes(_anchor(3)) and anchor_bytes(a).endswith(b"}\n")
    assert parse_anchor(anchor_bytes(a), "x") == a


def test_the_name_comes_from_counts_and_heads_grades_first() -> None:
    chains = {"events": ChainHead(5, H[4]), "grades": ChainHead(3, H[2])}
    assert anchor_name(chains) == f"anchor-g00000003-{H[2][:16]}-e00000005-{H[4][:16]}.json"


def test_a_chain_with_rows_needs_a_head() -> None:
    with pytest.raises(AnchorError):
        build_anchor(
            source="jsonl",
            chains={"grades": ChainHead(2, "")},
            apparatus="2.5",
            crb_version="x",
            created_at="T",
        )


def test_the_check_passes_on_growth_and_fails_on_rewrite_or_truncation() -> None:
    a = _anchor(3)
    assert check_anchor(a, source="jsonl", hash_at=_hash_at(H[:3])) == []
    assert check_anchor(a, source="jsonl", hash_at=_hash_at(H[:6])) == []
    rewritten = ["f" * 64, "e" * 64, "d" * 64, H[3]]
    [fault] = check_anchor(a, source="jsonl", hash_at=_hash_at(rewritten))
    assert "row 3" in fault and "rewritten" in fault and H[2] in fault
    [fault] = check_anchor(a, source="jsonl", hash_at=_hash_at(H[:2]))
    assert "fewer than 3 rows" in fault
    [fault] = check_anchor(a, source="sqlite", hash_at=_hash_at(H))
    assert "jsonl" in fault and "sqlite" in fault


def test_unreadable_anchors_are_refused() -> None:
    for data in (b"not json", b'{"schema": "other"}', json.dumps({"schema": ANCHOR_SCHEMA})):
        with pytest.raises(AnchorError):
            parse_anchor(data if isinstance(data, bytes) else data.encode(), "f")


def _file(source: str, chains: dict) -> bytes:  # type: ignore[type-arg]
    a = _anchor(3)
    a.update(source=source, chains=chains)
    return anchor_bytes(a)


ATTESTS_NOTHING = (
    ("jsonl", {"events": {"rows": 0, "head_row_hash": ""}}),  # not the JSONL chain
    ("jsonl", {"grades": {"rows": 0, "head_row_hash": ""}}),  # no row
    (
        "jsonl",
        {"grades": {"rows": 3, "head_row_hash": H[2]}, "events": {"rows": 0, "head_row_hash": ""}},
    ),
    ("sqlite", {"grades": {"rows": 3, "head_row_hash": H[2]}}),  # a store anchor lacks events
    (
        "sqlite",
        {"grades": {"rows": 0, "head_row_hash": ""}, "events": {"rows": 0, "head_row_hash": ""}},
    ),
    ("jsonl", {"grades": {"rows": 3, "head_row_hash": ""}}),  # rows without a head
    ("jsonl", {"grades": {"rows": 0, "head_row_hash": H[0]}}),  # a head without rows
)


@pytest.mark.parametrize(("source", "chains"), ATTESTS_NOTHING)
def test_an_anchor_without_its_sources_chains_or_any_row_is_refused(
    source: str,
    chains: dict,  # type: ignore[type-arg]
) -> None:
    """A file whose chains are not its source's, or whose every chain is empty, would check
    as holding while attesting nothing: refused on read, and never built."""
    with pytest.raises(AnchorError):
        parse_anchor(_file(source, chains), "f")
    heads = {k: ChainHead(v["rows"], v["head_row_hash"]) for k, v in chains.items()}
    with pytest.raises(AnchorError):
        build_anchor(source=source, chains=heads, apparatus="2.5", crb_version="x", created_at="T")


def test_a_store_anchor_of_events_only_is_a_real_anchor() -> None:
    """A store with no grade yet but an audit trail anchors its events: accepted both ways."""
    a = build_anchor(
        source="sqlite",
        chains={"grades": ChainHead(0, ""), "events": ChainHead(5, H[4])},
        apparatus="2.5",
        crb_version="x",
        created_at="T",
    )
    assert parse_anchor(anchor_bytes(a), "x") == a


def test_write_never_overwrites_and_a_same_state_rewrite_is_a_no_op(tmp_path: Path) -> None:
    path, written = write_anchor(tmp_path, _anchor(3, at="first"))
    assert written and path.name == anchor_name(_anchor(3)["chains"])
    before = path.read_bytes()
    again, written = write_anchor(tmp_path, _anchor(3, at="second"))
    assert again == path and not written and path.read_bytes() == before
    forged = _anchor(3)
    forged["source"] = "sqlite"
    with pytest.raises(AnchorError, match="not overwritten"):
        write_anchor(tmp_path, forged)
    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == [path.name]  # no temp file left


def test_the_directory_chain_names_a_deleted_or_edited_anchor(tmp_path: Path) -> None:
    p1, _ = write_anchor(tmp_path, _anchor(2))
    first = load_anchor(p1)
    p2, _ = write_anchor(tmp_path, _anchor(4, previous=(p1.name, first.sha256)))
    loaded = load_anchor_dir(tmp_path)
    assert [la.path for la in loaded] == [p1, p2] and check_anchor_links(loaded) == []
    p1.write_bytes(p1.read_bytes().replace(b'"T"', b'"T2"'))  # an edited anchor
    [fault] = check_anchor_links(load_anchor_dir(tmp_path))
    assert p1.name in fault and "changed" in fault
    p1.unlink()  # a deleted anchor
    [fault] = check_anchor_links(load_anchor_dir(tmp_path))
    assert p1.name in fault and "not in the directory" in fault


def test_is_inside_resolves_dot_dot(tmp_path: Path) -> None:
    data = tmp_path / "data"
    assert is_inside(data / "anchors", data) and is_inside(data, data)
    assert not is_inside(data / ".." / "anchors", data)


MALFORMED_LINKS = (
    "damaged",
    7,
    ["anchor-x.json", "0" * 64],
    {},
    {"sha256": "0" * 64},
    {"file": "anchor-x.json"},
    {"file": 3, "sha256": "0" * 64},
    {"file": "anchor-x.json", "sha256": None},
)


@pytest.mark.parametrize("link", MALFORMED_LINKS)
def test_a_malformed_predecessor_link_is_an_anchor_chain_fault(
    tmp_path: Path, link: object
) -> None:
    """A ``previous_anchor`` that is not ``{file: str, sha256: str}`` (or null) is a damaged
    link in the directory's anchor chain, reported as a fault — on the first anchor and on a
    later one — never an exception."""
    first = _anchor(2)
    first["previous_anchor"] = link
    p1 = tmp_path / anchor_name(first["chains"])
    p1.write_bytes(anchor_bytes(first))
    [fault] = check_anchor_links(load_anchor_dir(tmp_path))
    assert p1.name in fault and "previous_anchor" in fault
    p1.write_bytes(anchor_bytes(_anchor(2)))
    second = _anchor(4)
    second["previous_anchor"] = link
    p2 = tmp_path / anchor_name(second["chains"])
    p2.write_bytes(anchor_bytes(second))
    [fault] = check_anchor_links(load_anchor_dir(tmp_path))
    assert p2.name in fault and "previous_anchor" in fault
