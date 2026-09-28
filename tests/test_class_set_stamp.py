"""The class-set stamp (ADR-0026 item 9): one version per reading, a label table, never pooled.

Navigation
----------
What it is:   Tests for the class-set version every row of apparatus 2.4 stamps
              (``labels.taxonomy``), ``ClassSetsPooled`` and the (task, version) label table.
What it does: Pins the ``<owner>/classes@v<N>`` grammar and the global version; shows
              ``cell_stats`` refusing rows of two versions; shows a relabel recorded in the
              label table while the stored row keeps its class, version and hash; pins the
              taxonomy module's new *Touch when*, word for word from the ADR.
How:          Rows from ``tests.fixtures.posture.posture_row`` at 2.4; the label run's event
              payloads folded by ``ClassLabelTable.from_events``.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0026-the-context-standard.md (item 9's stamp)
Works with:   src/crb/core/taxonomy.py (the grammar, ``ClassSetsPooled``, the label table),
              src/crb/core/ledger.py (the stamp on every 2.4 row, the refusal in ``cell_stats``),
              docs/adr/0026-the-context-standard.md (item 9's *Touch when*, quoted verbatim)
Tested by:    this file
Touch when:   never for a new repository; the class-set grammar or the label table changes (an ADR
              first).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from crb.core.ledger import GradeRow, cell_stats, verify_chain
from crb.core.taxonomy import (
    GLOBAL_CLASS_SET,
    ClassLabelTable,
    ClassSetsPooled,
    is_class_set_version,
    parse_class_set,
    rows_for_taxonomy,
)
from fixtures.posture import posture_row

ROOT = Path(__file__).resolve().parents[1]


def _row(task: str, **kw: Any) -> GradeRow:
    return posture_row(
        repo="r",
        task_id=task,
        clean=True,
        tests_unmodified=True,
        target_green=True,
        no_new_failures=True,
        source_changed=True,
        repo_lint_clean=None,
        capability_class="bug.fix",
        size="S",
        language="python",
        builder="b",
        model="m",
        provider="p",
        evidence_pack_hash="h" * 64,
        apparatus_version="2.4",
        **kw,
    )


def test_the_global_vocabulary_is_version_one_of_the_class_set_grammar() -> None:
    assert GLOBAL_CLASS_SET == "global/classes@v1"
    assert parse_class_set(GLOBAL_CLASS_SET) == ("global", 1)
    assert parse_class_set("acme/classes@v12") == ("acme", 12)
    for bad in ("", "global", "global/classes@v0", "Acme/classes@v1", "global/classes@1"):
        assert not is_class_set_version(bad)


def test_every_24_row_stamps_the_global_class_set_unless_another_is_named() -> None:
    assert _row("a").taxonomy == GLOBAL_CLASS_SET
    assert _row("b", labels={"taxonomy": "acme/classes@v2"}).taxonomy == "acme/classes@v2"


def test_rows_of_two_class_set_versions_never_pool() -> None:
    v1 = [_row(f"g{i}") for i in range(3)]
    v2 = [_row(f"o{i}", labels={"taxonomy": "acme/classes@v1"}) for i in range(3)]
    with pytest.raises(ClassSetsPooled, match="class-set version"):
        cell_stats([*v1, *v2])
    assert cell_stats(rows_for_taxonomy([*v1, *v2], GLOBAL_CLASS_SET)).taxonomy == GLOBAL_CLASS_SET
    with pytest.raises(ValueError):
        rows_for_taxonomy(v1, "all")


def test_a_relabel_is_recorded_per_task_and_version_and_never_rewrites_a_stored_row() -> None:
    task = "c" * 40
    stored = _row(task).chained("0" * 64)
    table = ClassLabelTable.from_events(
        [
            {"task_id": task, "capability_class": "bug.fix"},
            {"task_id": task, "capability_class": "feature.add", "previous_class": "bug.fix"},
            {"task_id": task, "capability_class": "perf", "taxonomy": "acme/classes@v1"},
        ]
    )
    assert table.class_of(task) == "feature.add"
    assert table.class_of(task, "acme/classes@v1") == "perf"
    assert table.class_of("d" * 40) is None
    # the row keeps the class and the version it was graded under, and still verifies
    assert stored.capability_class == "bug.fix" and stored.taxonomy == GLOBAL_CLASS_SET
    assert verify_chain([stored]) == 1


def test_the_taxonomy_modules_touch_when_is_adr_0026_item_9s_word_for_word() -> None:
    adr = (ROOT / "docs/adr/0026-the-context-standard.md").read_text(encoding="utf-8")
    quoted = adr.split("The new *Touch when* of `src/crb/core/taxonomy.py`:**", 1)[1]
    want = " ".join(quoted.split('"', 2)[1].split())
    src = (ROOT / "src/crb/core/taxonomy.py").read_text(encoding="utf-8")
    block = src.split("Touch when:", 1)[1].split('"""', 1)[0]
    assert " ".join(block.split()) == want
