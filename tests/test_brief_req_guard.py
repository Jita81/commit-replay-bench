"""Tests for the stated-requirement guard and its place in the composer (ADR-0052).

Navigation
----------
What it is:   Tests for ``crb.builders.brief.req_guard`` and ``compose`` on a ``ctx.req*`` arm,
              and the pin that ``refuse_novel`` still applies to every non-req line.
What it does: Pins each guard reason on a minimal ``GoldView``; that a stated entry whose
              declared novel tokens would fail ``refuse_novel`` is delivered on a req arm
              (the ADR-0052 amendment); that the same text is refused on an oracle, mech or
              plain library arm, and that an entry without items, a fact or a learned line
              naming a novel token is refused on a req arm too; that a guard refusal is
              counted and its reasons stamped; and ``gold_view`` over a real two-commit repo.
How:          Hand-built ``GoldView`` values (``parent_has`` over a fixed set); one temporary
              git repository for ``gold_view``; no model, no docker.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0052-stated-requirement-arms.md, docs/adr/0050-context-set-arms.md
Works with:   src/crb/builders/brief.py (the module under test), src/crb/core/stated.py (the
              items and renderers), tests/test_builders_brief.py (the ADR-0050 compose tests)
Tested by:    this file
Touch when:   never for a new repository; a guard rule, a reason or the req amendment
              changes (an ADR first).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from crb.builders.brief import (
    LABEL_CTX_DELIVERED,
    LABEL_CTX_REFUSED,
    LABEL_CTX_REQ_REFUSED,
    ContextEntry,
    GoldView,
    Ticket,
    compose,
    gold_view,
    refuse_novel,
    req_guard,
)
from crb.core import stated
from crb.core.git import GitRepo
from crb.core.stated import StatedItem

REQ_ARM = "A0+library@ctx.req.0123456789ab"
REQ_PLACEBO_ARM = "A0+library@ctx.req-placebo.0123456789ab"
ORACLE_ARM = "A0+library@ctx.oracle.0123456789ab"
MECH_ARM = "A0+library@ctx.mech.0123456789ab"
PARENT = "a" * 40
TICKET = Ticket("feat: refuse empty names", "feat: refuse empty names")
PARENT_TREE = frozenset({"validate", "Config", "load"})

SRC_AFTER = (
    "def validate(name):\n"
    "    if not name:\n"
    '        raise ValueError("name required")\n'
    "    return name.strip().lower()\n"
)
TEST_AFTER = (
    "def test_validate_refuses_empty_name_quickly():\n"
    "    with pytest.raises(ValueError, match='name required'):\n"
    "        validate('')\n"
    "    assert validate('ok') == 'ok'\n"
)


def gold(**kw: Any) -> GoldView:
    base: dict[str, Any] = {
        "novel": frozenset({"name required", "test_validate_refuses_empty_name_quickly"}),
        "parent_has": lambda tok: any(tok.lower() == p.lower() for p in PARENT_TREE),
        "src_after": SRC_AFTER,
        "test_after": TEST_AFTER,
        "src_added": tuple(SRC_AFTER.splitlines()[1:]),
        "test_added": tuple(TEST_AFTER.splitlines()),
        "test_paths": ("tests/test_validate_names.py",),
    }
    base.update(kw)
    return GoldView(**base)


ITEM = StatedItem(
    "i01",
    "error_text",
    "An empty name raises ValueError with the text `name required`",
    "change_detail",
    ("name required",),
)
PLAIN = StatedItem("i02", "rule", "Existing callers of validate keep working", "nowhere")


def entry(*items: StatedItem, structure: str = "prose", text: str | None = None) -> ContextEntry:
    body = stated.render(structure, items) if text is None else text
    return ContextEntry("r-1", body, "1", "", items=tuple(items), structure=structure)


def guard(*items: StatedItem, view: GoldView | None = None, **kw: Any) -> list[str]:
    e = entry(*items, **kw)
    return req_guard(e.text, e.items, e.structure, gold() if view is None else view)


# -- req_guard, reason by reason --------------------------------------------------------------


def test_a_well_formed_entry_passes_in_both_structures() -> None:
    assert guard(ITEM, PLAIN) == []
    assert guard(ITEM, PLAIN, structure="checklist") == []


def test_free_text_that_is_not_the_rendering_is_refused() -> None:
    assert stated.REASON_RENDER in guard(ITEM, text="Do what the tests want.")
    assert stated.REASON_RENDER in guard(ITEM, structure="table", text="x")


def test_no_gold_view_fails_closed() -> None:
    e = entry(ITEM)
    assert req_guard(e.text, e.items, e.structure, None) == [stated.REASON_NO_GOLD]


def test_length_limits() -> None:
    many = [StatedItem(f"i{n:02}", "rule", "Keep it", "nowhere") for n in range(13)]
    assert stated.REASON_LENGTH in guard(*many)


def test_a_code_block_is_refused() -> None:
    fenced = StatedItem("i01", "rule", "Use ```x = 1```", "nowhere")
    assert stated.REASON_CODE_BLOCK in guard(fenced)
    indented = StatedItem("i01", "rule", "indented", "nowhere")
    hand_built = stated.HEADER + "\n    indented"
    assert stated.REASON_CODE_BLOCK in req_guard(hand_built, (indented,), "checklist", gold())


def test_an_undeclared_novel_token_is_refused_case_insensitively() -> None:
    undeclared = StatedItem("i01", "error_text", "Raise `NAME REQUIRED` on empty", "nowhere")
    assert stated.REASON_UNDECLARED_NOVEL in guard(undeclared)


def test_a_misstated_provenance_is_refused() -> None:
    understated = StatedItem("i01", "error_text", ITEM.statement, "product", ("name required",))
    assert stated.REASON_PROVENANCE in guard(understated)
    only_tests = gold(src_after="def validate(name):\n    pass\n")
    assert stated.REASON_PROVENANCE in guard(ITEM, view=only_tests)
    tests_only = StatedItem("i01", "error_text", ITEM.statement, "tests_only", ("name required",))
    assert guard(tests_only, view=only_tests) == []
    product = StatedItem("i01", "name", "The function `validate` stays", "product", ("validate",))
    assert guard(product) == []


def test_a_held_out_tests_name_is_refused() -> None:
    named = StatedItem(
        "i01",
        "name",
        "Cover test_validate_refuses_empty_name_quickly",
        "tests_only",
        ("test_validate_refuses_empty_name_quickly",),
    )
    assert stated.REASON_TEST_NAME in guard(named)


def test_a_held_out_tests_path_or_stem_is_refused() -> None:
    for statement in ("See tests/test_validate_names.py", "As test_validate_names checks"):
        item = StatedItem("i01", "rule", statement, "nowhere")
        assert stated.REASON_TEST_PATH in guard(item)
    generic = gold(test_paths=("tests/test.py",))
    assert (
        guard(StatedItem("i01", "rule", "Existing tests keep passing", "nowhere"), view=generic)
        == []
    )


def test_an_eight_token_span_copied_from_the_change_is_refused() -> None:
    copied = StatedItem(
        "i01",
        "rule",
        "with pytest raises ValueError, match name required, validate, assert",
        "change_detail",
        ("name required",),
    )
    assert stated.REASON_TEST_SPAN in guard(copied)
    from_src = StatedItem(
        "i01",
        "rule",
        "name: raise ValueError, name required, return name.strip",
        "change_detail",
        ("name required",),
    )
    assert stated.REASON_TEST_SPAN in guard(from_src)


def test_a_signature_may_restate_source_tokens_but_never_a_body() -> None:
    sig = StatedItem("i01", "signature", "validate(name) keeps its signature", "nowhere")
    assert guard(sig) == []
    for body in ("validate(name) { return 1 }", "validate(name) => x", "validate(name) return x"):
        assert stated.REASON_SIGNATURE in guard(StatedItem("i01", "signature", body, "nowhere"))


# -- compose: the amendment is req-only -------------------------------------------------------


def _compose(arm: str, library: tuple[ContextEntry, ...], **kw: Any) -> Any:
    kw.setdefault("novel", gold().novel)
    return compose(
        arm, TICKET, repo="pyrepo", language="python", mode="blind", library=library, **kw
    )


def test_a_stated_entry_with_declared_novel_tokens_is_delivered_on_a_req_arm() -> None:
    e = entry(ITEM, PLAIN)
    # the text names a novel token: refuse_novel alone would withhold it
    assert refuse_novel([e.text], gold().novel)[1] == [e.text]
    for arm in (REQ_ARM, REQ_PLACEBO_ARM):
        composed = _compose(arm, (e,), gold=gold())
        assert composed.brief.spec_facts == (e.text,)
        assert composed.labels[LABEL_CTX_DELIVERED] == "1"
        assert composed.labels[LABEL_CTX_REFUSED] == "0"
        assert LABEL_CTX_REQ_REFUSED not in composed.labels


def test_refuse_novel_still_applies_to_every_non_req_line() -> None:
    """THE pin (ADR-0052 review must-fix 1): the amendment covers stated entries on a req arm
    and nothing else. The same stated entry is refused on an oracle, mech or plain library
    arm; on a req arm an entry without items and a learned line naming a novel token are
    refused, and a bare fact is refused as on every context-set arm."""
    e = entry(ITEM, PLAIN)
    oracle = _compose(ORACLE_ARM, (e,), gold=gold())
    assert oracle.brief.spec_facts == () and oracle.refused == (e.text,)
    mech_entry = ContextEntry(
        "m-1", e.text, "1", "", True, PARENT, items=e.items, structure="prose"
    )
    mech = _compose(MECH_ARM, (mech_entry,), parent_rev=PARENT, gold=gold())
    assert mech.brief.spec_facts == ()
    plain_lib = _compose(
        "A0+library@v1",
        (ContextEntry("p-1", e.text, "1", "", True, items=e.items),),
        pool_began="2099-01-01",
        retrospective=True,
        gold=gold(),
    )
    assert plain_lib.brief.spec_facts == ()
    no_items = ContextEntry("r-2", "Raise the error text name required.", "1", "")
    learned = "Keep the message name required."
    req = _compose(REQ_ARM, (e, no_items), learned=(learned,), facts=("A fact.",), gold=gold())
    assert req.brief.spec_facts == (e.text,)
    assert req.brief.playbook == ()
    assert set(req.refused) == {no_items.text, learned, "A fact."}
    assert req.labels[LABEL_CTX_REFUSED] == "3"


def test_a_guard_refusal_is_counted_and_its_reasons_stamped() -> None:
    bad = entry(StatedItem("i01", "rule", "See tests/test_validate_names.py", "nowhere"))
    composed = _compose(REQ_ARM, (bad,), gold=gold())
    assert composed.brief.spec_facts == () and composed.refused == (bad.text,)
    assert composed.labels[LABEL_CTX_DELIVERED] == "0"
    assert composed.labels[LABEL_CTX_REFUSED] == "1"
    assert composed.labels[LABEL_CTX_REQ_REFUSED] == stated.REASON_TEST_PATH


def test_a_req_arm_without_a_gold_view_withholds_its_entry() -> None:
    composed = _compose(REQ_ARM, (entry(PLAIN),))
    assert composed.brief.spec_facts == ()
    assert composed.labels[LABEL_CTX_REQ_REFUSED] == stated.REASON_NO_GOLD


# -- gold_view over a real repository ---------------------------------------------------------


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def two_commits(tmp_path: Path) -> tuple[GitRepo, str, str]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "config", "user.name", "fixture")
    (root / "calc.py").write_text(
        "def validate(name):\n    # never raises ValueError with a message yet\n    return name\n"
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_calc.py").write_text("def test_ok():\n    assert True\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "parent")
    parent = _git(root, "rev-parse", "HEAD")
    (root / "calc.py").write_text(SRC_AFTER)
    (root / "tests" / "test_calc.py").write_text(TEST_AFTER)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "change")
    return GitRepo(root), parent, _git(root, "rev-parse", "HEAD")


def test_gold_view_reads_added_lines_and_the_parent_tree(
    two_commits: tuple[GitRepo, str, str],
) -> None:
    repo, parent, commit = two_commits
    view = gold_view(
        repo,
        parent=parent,
        commit=commit,
        src_paths=("calc.py",),
        test_paths=("tests/test_calc.py",),
    )
    assert "name required" in view.novel
    assert any("name required" in ln for ln in view.src_added)
    assert any(ln.startswith("def test_validate") for ln in view.test_added)
    assert view.parent_has("VALIDATE") and not view.parent_has("name required")
    assert view.test_paths == ("tests/test_calc.py",)
    assert req_guard(entry(ITEM).text, (ITEM,), "prose", view) == []
