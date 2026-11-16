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
              counted and its reasons stamped; ``gold_view`` over a real two-commit repo; that
              ``novel_tokens`` agrees with ``parent_has`` on a word held only inside a longer
              match, and keeps a word held only in a binary file novel; and that ``product``
              needs the word in parent product code.
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
    novel_tokens,
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
        "parent_has": lambda tok: tok in PARENT_TREE,
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


def test_a_whole_statement_disclose_declares_nothing() -> None:
    """Review case B: one broad disclose must not cover the novel token inside it, nor set
    the provenance below the novel token's own (``tests_only`` here)."""
    only_tests = gold(src_after="def validate(name):\n    pass\n")
    broad = StatedItem("i01", "error_text", ITEM.statement, "nowhere", (ITEM.statement,))
    why = guard(broad, view=only_tests)
    assert stated.REASON_DISCLOSE in why
    assert stated.REASON_UNDECLARED_NOVEL in why
    assert stated.REASON_PROVENANCE in why


def test_a_superstring_disclose_does_not_declare_the_token_inside_it() -> None:
    """Review case C: ``text `name required``` contains the novel token but is not it."""
    only_tests = gold(src_after="def validate(name):\n    pass\n")
    sup = StatedItem("i01", "error_text", ITEM.statement, "nowhere", ("text `name required",))
    why = guard(sup, view=only_tests)
    assert {stated.REASON_DISCLOSE, stated.REASON_UNDECLARED_NOVEL} <= set(why)
    assert stated.REASON_PROVENANCE in why


def test_provenance_ignores_a_hit_that_is_only_a_substring() -> None:
    """A tests-only literal the source post-image holds only inside a longer word is still
    tests_only: every side is read whole-word and case-sensitively, as ``novel_tokens``
    reads the parent (the parent's own matcher is pinned on a real repository below)."""
    only_tests = gold(src_after="def validate(name):\n    hint = 'name requiredness'\n")
    tests_only = StatedItem("i01", "error_text", ITEM.statement, "tests_only", ("name required",))
    assert guard(tests_only, view=only_tests) == []
    product = StatedItem("i01", "error_text", ITEM.statement, "product", ("name required",))
    assert stated.REASON_PROVENANCE in guard(product, view=only_tests)


def test_filler_words_do_not_break_a_copied_span() -> None:
    """Review case E: a non-stopword filler between copied test tokens."""
    filler = StatedItem(
        "i01",
        "rule",
        "Use pytest next raises next ValueError next match next name required next "
        "validate next assert",
        "change_detail",
        ("name required",),
    )
    assert stated.REASON_TEST_SPAN in guard(filler)


def test_filler_from_the_gold_vocabulary_does_not_break_a_copied_span() -> None:
    """Review 4580636569: ``name`` is a gold token, so the vocabulary filter keeps it; the
    copied run must still be found with it inserted between the copied tokens."""
    filler = StatedItem(
        "i01",
        "rule",
        "pytest name raises name ValueError name match name name required name "
        "validate name assert",
        "change_detail",
        ("name required",),
    )
    assert stated.REASON_TEST_SPAN in guard(filler)
    # seven copied tokens in order are not a run, however they are spaced
    short = StatedItem(
        "i01",
        "rule",
        "pytest name raises name ValueError name match name name required name validate",
        "change_detail",
        ("name required",),
    )
    assert stated.REASON_TEST_SPAN not in guard(short)


def test_prose_reusing_short_gold_tokens_is_not_a_copied_span() -> None:
    """A gapped run counts only with copies of ONE token inserted inside it: prose that
    reuses short common tokens (``func``, ``t``, ``int``, ``function``) of the gold in a
    different order, with several distinct tokens between them, is not a copy. A contiguous
    run is always one, and one repeated filler still is."""
    test_lines = (
        "\t// a less function func(T, T) bool",
        '\t{"less", func(x, y int) bool { return x < y }},',
        "\t// a compare function func(T, T) int returning int",
        '\t{"compare", func(x, y int) int { return x - y }},',
        '\tt.Run("function returning int with two parameters", func(t *testing.T) {',
    )
    view = gold(novel=frozenset(), test_added=test_lines, test_paths=("sort_test.go",))
    prose = StatedItem(
        "i01",
        "rule",
        "SortSlices accepts a compare function of the form func(T, T) int as well as the "
        "existing less function of the form func(T, T) bool; a function returning int with "
        "two parameters no longer panics",
        "nowhere",
    )
    assert stated.REASON_TEST_SPAN not in guard(prose, view=view)
    contiguous = StatedItem(
        "i01", "rule", "a compare function func(T, T) int returning int compare", "nowhere"
    )
    assert stated.REASON_TEST_SPAN in guard(contiguous, view=view)
    one_filler = StatedItem(
        "i01",
        "rule",
        "compare t function t func t t t t int t returning t int t compare",
        "nowhere",
    )
    assert stated.REASON_TEST_SPAN in guard(one_filler, view=view)


def test_a_copied_span_split_across_items_is_refused() -> None:
    """Review case F: the run is read over the whole entry, items in order."""
    first = StatedItem("i01", "rule", "Use pytest raises ValueError match", "nowhere")
    second = StatedItem(
        "i02", "rule", "name required then validate, assert", "change_detail", ("name required",)
    )
    assert stated.REASON_TEST_SPAN not in guard(first)
    assert stated.REASON_TEST_SPAN in guard(first, second)
    assert stated.REASON_TEST_SPAN in guard(first, second, structure="checklist")


def test_a_test_helper_or_fixture_name_is_refused() -> None:
    """Review case G: a name a test file defines, not only a test's own definition."""
    test_after = (
        "@pytest.fixture\n"
        "def make_sample_widget_payload():\n"
        "    return {'name': ''}\n"
        "const DEFAULT_WIDGET_LIMIT = 10\n" + TEST_AFTER
    )
    view = gold(test_after=test_after, test_added=tuple(test_after.splitlines()))
    for name in ("make_sample_widget_payload", "DEFAULT_WIDGET_LIMIT"):
        item = StatedItem("i01", "rule", f"Build inputs with {name}", "nowhere")
        assert stated.REASON_TEST_NAME in guard(item, view=view), name
    # a helper the source also holds is the product's own name
    shared = gold(test_after="def validate_all():\n    pass\n", src_after="validate_all = 1\n")
    item = StatedItem("i01", "rule", "Keep validate_all", "nowhere")
    assert stated.REASON_TEST_NAME not in guard(item, view=shared)


def test_a_python_test_constant_is_a_held_out_name() -> None:
    """Review 4580636570: a plain or annotated Python assignment in a test file defines a
    held-out name, even disclosed with a correct ``tests_only`` provenance."""
    test_after = "DEFAULT_WIDGET_LIMIT = 10\nWIDGET_CEILING: int = 99\n" + TEST_AFTER
    view = gold(
        novel=gold().novel | {"DEFAULT_WIDGET_LIMIT", "WIDGET_CEILING"},
        test_after=test_after,
        test_added=tuple(test_after.splitlines()),
    )
    for name in ("DEFAULT_WIDGET_LIMIT", "WIDGET_CEILING"):
        item = StatedItem("i01", "value", f"Cap at {name}", "tests_only", (name,))
        assert stated.REASON_TEST_NAME in guard(item, view=view), name
    # every target of a tuple, chained or attribute assignment is bound too
    test_after = "WIDGET_A, WIDGET_B = 1, 2\nWIDGET_P = WIDGET_Q = 3\n    self.WIDGET_MAX = 5\n"
    names = ("WIDGET_A", "WIDGET_B", "WIDGET_P", "WIDGET_Q", "WIDGET_MAX")
    view = gold(
        novel=gold().novel | set(names),
        test_after=test_after + TEST_AFTER,
        test_added=tuple((test_after + TEST_AFTER).splitlines()),
    )
    for name in names:
        item = StatedItem("i01", "value", f"Cap at {name}", "tests_only", (name,))
        assert stated.REASON_TEST_NAME in guard(item, view=view), name
    # a comparison is not a definition
    compared = gold(test_after="    assert widget_total == 3\n")
    item = StatedItem("i01", "rule", "Keep widget_total", "nowhere")
    assert stated.REASON_TEST_NAME not in guard(item, view=compared)


def test_the_python_assignment_rule_reads_only_python_test_files() -> None:
    """A Go short declaration (``pathValue := r.PathValue("id")``) is not a Python
    annotated assignment: naming the standard library's ``PathValue`` is no held-out name.
    The same file read as Python still binds the name, and a Go test file's own definitions
    stay held out."""
    go_test = (
        "func TestRouteParam(t *testing.T) {\n"
        '\tpathValue := r.PathValue("id")\n'
        "}\n"
        "func newRouterFixture() *Mux { return nil }\n"
    )
    item = StatedItem("i01", "rule", "Read the parameter with PathValue", "nowhere")
    for view in (
        gold(test_after=go_test, test_paths=("mux_test.go",), test_added=()),
        gold(
            test_after=go_test + TEST_AFTER,
            test_paths=("mux_test.go", "tests/test_validate_names.py"),
            test_after_by_path=(
                ("mux_test.go", go_test),
                ("tests/test_validate_names.py", TEST_AFTER),
            ),
            test_added=(),
        ),
    ):
        assert stated.REASON_TEST_NAME not in guard(item, view=view)
        fixture = StatedItem("i01", "rule", "Build it with newRouterFixture", "nowhere")
        assert stated.REASON_TEST_NAME in guard(fixture, view=view)
    as_python = gold(test_after=go_test, test_paths=("tests/test_mux.py",), test_added=())
    assert stated.REASON_TEST_NAME in guard(item, view=as_python)


def test_an_annotated_jvm_or_dotnet_test_method_is_a_held_out_name() -> None:
    """Review 4580935910: a method declared on the line after ``@Test`` (or a C#
    ``[Fact]``), a same-line ``@Test void x()`` and a Kotlin ``fun x()`` define held-out
    names, even disclosed with a correct ``tests_only`` provenance."""
    cases = {
        "src/test/java/WidgetTest.java": (
            "class WidgetTest {\n"
            "    @Test\n"
            "    void rejectsEmptyWidget() {\n"
            '        assertThrows(IllegalArgumentException.class, () -> make(""));\n'
            "    }\n"
            "    @ParameterizedTest\n"
            '    @ValueSource(strings = {"a b", "c"})\n'
            "    public void acceptsShortWidgets(String s) {}\n"
            "    @Test public static void inlineAnnotatedWidgetCase() {}\n"
            "}\n",
            ("rejectsEmptyWidget", "acceptsShortWidgets", "inlineAnnotatedWidgetCase"),
        ),
        "src/test/kotlin/WidgetTest.kt": (
            "class WidgetTest {\n    @Test\n    fun rejectsBlankWidgetName() {}\n}\n",
            ("rejectsBlankWidgetName",),
        ),
        "tests/WidgetTests.cs": (
            "public class WidgetTests {\n"
            "    [Fact]\n"
            "    public async Task RejectsNullWidgetInput() {}\n"
            "}\n",
            ("RejectsNullWidgetInput",),
        ),
    }
    for path, (test_after, names) in cases.items():
        view = gold(
            novel=gold().novel | set(names),
            test_after=test_after,
            test_paths=(path,),
            test_added=tuple(test_after.splitlines()),
        )
        for name in names:
            item = StatedItem("i01", "rule", f"Cover {name}", "tests_only", (name,))
            assert stated.REASON_TEST_NAME in guard(item, view=view), (path, name)
    # a call or a return inside a JVM test body defines nothing
    body = "    @Test\n    void ok() {\n        return buildWidgetSample();\n    }\n"
    view = gold(test_after=body, test_paths=("WidgetTest.java",), test_added=())
    item = StatedItem("i01", "rule", "Keep buildWidgetSample", "nowhere")
    assert stated.REASON_TEST_NAME not in guard(item, view=view)


@pytest.mark.parametrize(
    ("path", "line", "name"),
    [
        (
            "WidgetTest.java",
            "    public <T extends Comparable<T>> void boundedWidget(T t) {",
            "boundedWidget",
        ),
        (
            "WidgetTest.java",
            '    @DisplayName("a (b) c") void parenArgWidget() {',
            "parenArgWidget",
        ),
        (
            "WidgetTest.java",
            "    /** doc */ public native void commentedWidget();",
            "commentedWidget",
        ),
        (
            "WidgetTest.java",
            "    @Nested public static class WhenWidgetIsEmpty {",
            "WhenWidgetIsEmpty",
        ),
        ("WidgetTests.cs", "    public void GenericWidget<T>() {", "GenericWidget"),
        (
            "WidgetTests.cs",
            '    [InlineData("a]b")] public void BracketWidget(string s) {',
            "BracketWidget",
        ),
        ("WidgetSpec.scala", "  private[this] def scalaWidget[T](t: T): Unit = {", "scalaWidget"),
        ("WidgetTest.kt", "    fun List<String>.extensionWidget(): String {", "extensionWidget"),
        ("WidgetTest.kt", "    fun `rejects blank widget names`() {", "rejects blank widget names"),
        ("WidgetSpec.groovy", '    def "rejects a blank widget"() {', "rejects a blank widget"),
    ],
)
def test_jvm_and_dotnet_declaration_forms_are_held_out_names(
    path: str, line: str, name: str
) -> None:
    """Review 4580935910 (verify round): the declaration forms around the annotated method —
    a bounded generic, an annotation argument holding ``)``, a block comment, a nested class,
    a C# generic method, a Scala type parameter, a Kotlin extension, a Kotlin backtick or a
    Spock string name — each define a held-out name."""
    view = gold(
        test_after=f"class X {{\n    @Test\n{line}\n}}\n", test_paths=(path,), test_added=()
    )
    item = StatedItem("i01", "rule", f"Cover {name}", "nowhere")
    assert stated.REASON_TEST_NAME in guard(item, view=view), (path, name)


@pytest.mark.parametrize(
    "line",
    [
        "public record class HiddenWidgetSeed(int Value);",
        "public readonly record struct HiddenWidgetSeed(int Value);",
    ],
)
def test_a_csharp_record_class_or_struct_names_its_type_not_the_keyword(line: str) -> None:
    """Outside review: ``record class X`` and ``record struct X`` declare ``X``; reading the
    ``class`` or ``struct`` keyword as the name let a type declared only in the held-out test
    be disclosed with a ``tests_only`` provenance."""
    test_after = f"{line}\npublic class WidgetTests {{}}\n"
    view = gold(
        novel=gold().novel | {"HiddenWidgetSeed"},
        test_after=test_after,
        test_paths=("tests/WidgetTests.cs",),
        test_added=tuple(test_after.splitlines()),
    )
    item = StatedItem("i01", "rule", "Cover HiddenWidgetSeed", "tests_only", ("HiddenWidgetSeed",))
    assert stated.REASON_TEST_NAME in guard(item, view=view)


def test_a_jvm_statement_line_defines_no_name_and_a_long_line_stays_linear() -> None:
    """A Groovy command call or an infix assertion is a statement, not a declaration; a line
    of thousands of block comments or annotations is read in linear time."""
    body = (
        "    @Test\n    void ok() {\n        println makeWidget(x)\n        r shouldBe(y)\n    }\n"
    )
    view = gold(test_after=body, test_paths=("WidgetTest.groovy",), test_added=())
    for word in ("makeWidget", "shouldBe"):
        item = StatedItem("i01", "rule", f"Keep {word}", "nowhere")
        assert stated.REASON_TEST_NAME not in guard(item, view=view), word
    long_line = "/* a */ " * 5000 + "@a " * 5000 + "void x"
    view = gold(test_after=long_line, test_paths=("WidgetTest.java",), test_added=())
    assert stated.REASON_TEST_NAME not in guard(
        StatedItem("i01", "rule", "Keep it", "nowhere"), view=view
    )


def test_a_disclosure_masks_only_whole_tokens() -> None:
    """Review 4580636571: a disclosed ``load`` (the parent's) must not mask ``load`` inside
    the distinct novel token ``payload``, nor a literal ``10`` inside ``1000``."""
    src = "def validate(name):\n    payload = name\n    return 1000\n"
    view = gold(
        novel=gold().novel | {"payload", "1000"},
        src_after=src,
        parent_has=lambda tok: tok in PARENT_TREE | {"10"},
    )
    item = StatedItem("i01", "name", "Introduce payload", "product", ("load",))
    why = guard(item, view=view)
    assert {stated.REASON_UNDECLARED_NOVEL, stated.REASON_PROVENANCE} <= set(why)
    literal = StatedItem("i01", "value", "Return 1000 on success", "nowhere", ("10",))
    assert stated.REASON_UNDECLARED_NOVEL in guard(literal, view=view)
    # the declared token itself, and a novel word inside its own text, stay covered
    assert guard(ITEM, PLAIN) == []


def test_a_disclosure_never_names_fewer_tokens_than_a_substring_mask() -> None:
    """The whole-token mask must not refuse less than masking the declared text as a plain
    substring did: ``load`` spent inside ``loadwidget`` leaves the novel ``widget`` named,
    and a provenance either reading contradicts is refused."""
    view = gold(novel=frozenset({"widget"}), parent_has=lambda tok: tok == "load")
    item = StatedItem("i01", "name", "Keep loadwidget", "product", ("load",))
    assert stated.REASON_UNDECLARED_NOVEL in guard(item, view=view)
    src = 'MSG = "Name Required"\n'
    tests = "def test_x():\n    assert f() == 'name required'\n"
    view = gold(novel=frozenset({"name required"}), src_after=src, test_after=tests)
    for prov in ("change_detail", "tests_only"):
        item = StatedItem("i01", "error_text", "Raise aName Required", prov, ("Name Required",))
        assert stated.REASON_PROVENANCE in guard(item, view=view), prov


def test_a_signature_header_does_not_exempt_a_copied_python_body() -> None:
    """Review case H: only the header is exempt from the source-span rule."""
    src = (
        "def normalise(name):\n"
        "    cleaned = name.strip().lower().replace(' ', '_')\n"
        "    prefix = cleaned.split('_')[0]\n"
        "    suffix = cleaned.split('_')[-1]\n"
    )
    view = gold(src_after=src, src_added=tuple(src.splitlines()), novel=frozenset())
    body = StatedItem(
        "i01",
        "signature",
        "normalise(name): cleaned = name.strip().lower().replace(' ', '_') "
        "prefix = cleaned.split('_')[0]",
        "nowhere",
    )
    assert stated.REASON_TEST_SPAN in guard(body, view=view)
    header_only = StatedItem("i01", "signature", "normalise(name) -> str: keeps it", "nowhere")
    assert guard(header_only, view=view) == []


def test_a_signature_may_restate_source_tokens_but_never_a_body() -> None:
    sig = StatedItem("i01", "signature", "validate(name) keeps its signature", "nowhere")
    assert guard(sig) == []
    for body in ("validate(name) { return 1 }", "validate(name) => x", "validate(name) return x"):
        assert stated.REASON_SIGNATURE in guard(StatedItem("i01", "signature", body, "nowhere"))


def test_a_signature_carrying_a_short_python_statement_is_refused() -> None:
    """Review 4580636573: a short Python body past the header carries none of the brace,
    ``;``, ``=>`` or ``return`` markers and is too short for the span rule."""
    for body in (
        "validate(name): raise ValueError(name)",
        "validate(name): raise ValueError",
        "validate(name): name = name.strip()",
        "validate(name): pass",
        "validate(name): assert name",
        "validate(name): if not name: raise",
        "validate(name) -> str: yield name",
        # the code before the first parenthesis is not a header either
        "raise ValueError(name)",
        "if not name: raise ValueError(name)",
        "name = name.strip()",
        # an expression body
        "area(radius) -> float: pi * radius ** 2",
        "scale(x, k): x * k",
    ):
        item = StatedItem("i01", "signature", body, "nowhere")
        assert stated.REASON_SIGNATURE in guard(item), body
    for prose in (
        "validate(name) -> str: raises ValueError on an empty name",
        "validate(name): keeps its signature and passes for any other name",
    ):
        assert guard(StatedItem("i01", "signature", prose, "nowhere")) == [], prose


def test_a_go_method_signature_is_a_header_not_a_body() -> None:
    """The receiver group is not the whole header: a Go method's name, parameters and one
    result are header too; anything else between receiver and parameters, or code past the
    result, is still a body."""
    view = gold(novel=frozenset())
    for sig in (
        "func (he *HTTPError) Is(target error) bool",
        "func (x *Context) Clone() *Context",
        "func (pe ParseError) Unwrap() error",
        "func (s *Set) Pair() (int, error)",
        "func (s *Set) Keys() []string",
        "func (s *Set) Index() map[string]int",
    ):
        assert guard(StatedItem("i01", "signature", sig, "nowhere"), view=view) == [], sig
    for body in (
        "func (x) raise ValueError(name)",
        "func (s *Set) Keys() names = f()",
        "func (s *Set) Keys() f(x)",
        "func (s *Set) Keys() a + b",
        "func (s *Set) Keys() bool { return x }",
    ):
        item = StatedItem("i01", "signature", body, "nowhere")
        assert stated.REASON_SIGNATURE in guard(item, view=view), body


#: A held-out Go assertion on a panic message (the review's flush-panic case).
PANIC_TEST = (
    "func TestResponse_FlushPanics(t *testing.T) {",
    '\tassert.PanicsWithError(t, "echo: response writer *echo.testResponseWriter does not '
    'support flushing (http.Flusher interface)", func() {',
)
PANIC_ITEMS = (
    "The panic value is an error. Its text is echo: response writer, a space, the writer's Go "
    "type as printed by fmt, a space, then does not support flushing (http.Flusher interface).",
    "Flush panics with echo: Response Writer %T DOES NOT support   flushing.",
)


def _panic_view(**kw: Any) -> GoldView:
    return gold(novel=frozenset(), test_added=PANIC_TEST, test_paths=("response_test.go",), **kw)


def test_a_statement_repeating_an_asserted_literal_is_refused() -> None:
    """Four words in a row of a literal the held-out test asserts, held neither by the request
    nor by the parent, are refused whatever the case, spacing, punctuation or format verb."""
    for statement in PANIC_ITEMS:
        item = StatedItem("i01", "error_text", statement, "change_detail")
        assert stated.REASON_ASSERTED_LITERAL in guard(item, view=_panic_view()), statement
    own_words = StatedItem(
        "i01", "error_text", "Flush panics with an error naming the writer's type", "nowhere"
    )
    assert guard(own_words, view=_panic_view()) == []


def test_an_asserted_literal_the_request_states_is_not_refused() -> None:
    item = StatedItem("i01", "error_text", PANIC_ITEMS[0], "change_detail")
    e = entry(item)
    request = (
        "Restore the flush panic: echo: response writer %T does not support flushing "
        "(http.Flusher interface)"
    )
    assert stated.REASON_ASSERTED_LITERAL not in req_guard(
        e.text, e.items, e.structure, _panic_view(), request=request
    )
    # compose reads the request from the ticket the builder is given
    refused = _compose(REQ_ARM, (e,), gold=_panic_view(), novel=frozenset())
    assert refused.labels[LABEL_CTX_REQ_REFUSED] == stated.REASON_ASSERTED_LITERAL
    ticket = Ticket("fix: restore the flush panic", request)
    delivered = compose(
        REQ_ARM,
        ticket,
        repo="gorepo",
        language="go",
        mode="blind",
        library=(e,),
        novel=frozenset(),
        gold=_panic_view(),
    )
    assert delivered.labels[LABEL_CTX_DELIVERED] == "1"


def test_an_asserted_literal_the_parent_tree_holds_is_not_refused(tmp_path: Path) -> None:
    item = StatedItem("i01", "error_text", PANIC_ITEMS[0], "change_detail")
    held = _panic_view(parent_has_run=lambda run: run == ("does", "not", "support", "flushing"))
    assert stated.REASON_ASSERTED_LITERAL in guard(item, view=held)  # other runs stay novel
    every = _panic_view(parent_has_run=lambda run: True)
    assert stated.REASON_ASSERTED_LITERAL not in guard(item, view=every)
    # gold_view's own lookup over a real parent tree: case and punctuation between words aside
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "config", "user.name", "fixture")
    (root / "response.go").write_text("package echo\n")
    (root / "response_test.go").write_text("package echo\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "parent")
    bare = _git(root, "rev-parse", "HEAD")
    (root / "legacy.go").write_text(
        'var msg = "ECHO: Response-Writer %T does not support flushing (http.Flusher interface)"\n'
    )
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "parent with the message")
    holding = _git(root, "rev-parse", "HEAD")
    (root / "response_test.go").write_text("package echo\n" + "\n".join(PANIC_TEST) + "\n")
    _git(root, "add", "response_test.go")
    _git(root, "commit", "-q", "-m", "change")
    commit = _git(root, "rev-parse", "HEAD")
    repo = GitRepo(root)
    tests = ("response_test.go",)
    view = gold_view(repo, parent=holding, commit=commit, src_paths=(), test_paths=tests)
    assert view is not None
    assert stated.REASON_ASSERTED_LITERAL not in guard(item, view=view)
    _git(root, "checkout", "-q", "-b", "without", bare)
    (root / "response_test.go").write_text("package echo\n" + "\n".join(PANIC_TEST) + "\n")
    _git(root, "add", "response_test.go")
    _git(root, "commit", "-q", "-m", "change without the message")
    commit = _git(root, "rev-parse", "HEAD")
    view = gold_view(repo, parent=bare, commit=commit, src_paths=(), test_paths=tests)
    assert view is not None
    assert stated.REASON_ASSERTED_LITERAL in guard(item, view=view)


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
    assert view.parent_has("validate") and not view.parent_has("name required")
    # the matcher novel_tokens uses: whole word, case-sensitive (never a substring)
    assert not view.parent_has("VALIDATE") and not view.parent_has("valid")
    assert view.test_paths == ("tests/test_calc.py",)
    assert req_guard(entry(ITEM).text, (ITEM,), "prose", view) == []


def test_gold_view_is_none_when_a_present_blob_cannot_be_read(
    two_commits: tuple[GitRepo, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review 4580636567: a failed read is no gold view (the entry is withheld as
    ``req_no_gold``), never an empty post-image; only a path the commit lacks reads empty."""
    repo, parent, commit = two_commits
    real = GitRepo.show_file

    def failing(self: GitRepo, sha: str, path: str) -> str | None:
        if sha == commit and path == "tests/test_calc.py":
            return None
        return real(self, sha, path)

    monkeypatch.setattr(GitRepo, "show_file", failing)
    kw: dict[str, Any] = {"parent": parent, "commit": commit, "src_paths": ("calc.py",)}
    tests = ("tests/test_calc.py",)
    assert gold_view(repo, test_paths=tests, **kw) is None
    assert gold_view(repo, test_paths=tests, novel=frozenset({"name required"}), **kw) is None
    e = entry(ITEM)
    composed = _compose(REQ_ARM, (e,), gold=gold_view(repo, test_paths=tests, **kw))
    assert composed.labels[LABEL_CTX_REQ_REFUSED] == stated.REASON_NO_GOLD

    def raising(self: GitRepo, sha: str, path: str) -> str | None:
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setattr(GitRepo, "show_file", raising)
    assert gold_view(repo, test_paths=tests, **kw) is None


def test_gold_view_reads_an_absent_or_binary_path_as_empty(tmp_path: Path) -> None:
    """A path added, deleted or binary is read as git holds it: absent is empty, a blob with
    a NUL byte has no text. Neither is a failed read."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "config", "user.name", "fixture")
    (root / "old.py").write_text("def validate(name):\n    return name\n")
    (root / "logo.bin").write_bytes(b"\x89PNG\x00\xff\xfe")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "parent")
    parent = _git(root, "rev-parse", "HEAD")
    _git(root, "rm", "-q", "old.py")
    (root / "new.py").write_text(SRC_AFTER)
    (root / "logo.bin").write_bytes(b"\x89PNG\x00\xff\xfd")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "change")
    commit = _git(root, "rev-parse", "HEAD")
    view = gold_view(
        GitRepo(root),
        parent=parent,
        commit=commit,
        src_paths=("old.py", "new.py", "logo.bin"),
        test_paths=(),
    )
    assert view is not None
    assert "name required" in view.novel and view.src_after.count("def validate") == 1


def test_gold_view_never_trusts_a_short_novel_set(
    two_commits: tuple[GitRepo, str, str],
) -> None:
    """A ``novel`` set computed earlier from a read that failed silently is completed from
    the view's own reads: the union, never the smaller set."""
    repo, parent, commit = two_commits
    view = gold_view(
        repo,
        parent=parent,
        commit=commit,
        src_paths=("calc.py",),
        test_paths=("tests/test_calc.py",),
        novel=frozenset({"extra_token_only_passed"}),
    )
    assert view is not None
    assert {"name required", "extra_token_only_passed"} <= view.novel
    assert "validate" not in view.novel


# -- the parent-tree read: one rule for novel_tokens and parent_has ----------------------------


@pytest.fixture
def shadowed(tmp_path: Path) -> tuple[GitRepo, str, str]:
    """The parent holds "Service" and "Unavailable" only inside the phrase "Service
    Unavailable", in a file the change does not touch; the change adds that phrase as a
    string literal, so the literal and both words are candidates."""
    root = tmp_path / "shadow"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "config", "user.name", "fixture")
    (root / "timeout.py").write_text("# returns 503 Service Unavailable to the client\n")
    (root / "calc.py").write_text("def validate(name):\n    return name\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "parent")
    parent = _git(root, "rev-parse", "HEAD")
    (root / "calc.py").write_text(
        'def validate(name):\n    if not name:\n        raise ValueError("Service Unavailable")\n'
        "    return name\n"
    )
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "change")
    return GitRepo(root), parent, _git(root, "rev-parse", "HEAD")


def _shadow_view(shadowed: tuple[GitRepo, str, str]) -> GoldView:
    repo, parent, commit = shadowed
    view = gold_view(repo, parent=parent, commit=commit, src_paths=("calc.py",), test_paths=())
    assert view is not None
    return view


def test_novel_tokens_sees_a_word_inside_a_longer_parent_match(
    shadowed: tuple[GitRepo, str, str],
) -> None:
    repo, parent, commit = shadowed
    novel = novel_tokens(repo, parent=parent, commit=commit, paths=("calc.py",))
    view = _shadow_view(shadowed)
    assert view.parent_has("Service") and view.parent_has("Unavailable")
    assert "Service" not in novel and "Unavailable" not in novel
    assert "Service" not in view.novel and "Unavailable" not in view.novel


def test_novel_tokens_agrees_with_parent_has_on_every_candidate(
    shadowed: tuple[GitRepo, str, str],
) -> None:
    """Both ways: a held word is not novel, and a word the parent lacks (``ValueError``)
    stays novel — the extra passes never drop an absent token."""
    repo, parent, commit = shadowed
    novel = novel_tokens(repo, parent=parent, commit=commit, paths=("calc.py",))
    view = _shadow_view(shadowed)
    assert "ValueError" in novel
    for tok in ("Service", "Unavailable", "Service Unavailable", "ValueError"):
        assert (tok in novel) == (not view.parent_has(tok)), tok


def test_a_statement_naming_a_parent_word_is_not_refused_as_undeclared(
    shadowed: tuple[GitRepo, str, str],
) -> None:
    view = _shadow_view(shadowed)
    item = StatedItem(
        "i01",
        "error_text",
        "An empty name raises ValueError reporting that the Service is Unavailable",
        "change_detail",
        ("ValueError",),
    )
    assert req_guard(entry(item).text, (item,), "prose", view) == []


def test_a_word_held_only_in_a_parent_binary_file_stays_novel(tmp_path: Path) -> None:
    """The batched read skips binary files (``-I``), so such a word stays novel although
    ``parent_has`` finds it: the one place the two differ, and on the refusing side."""
    root = tmp_path / "bin"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "config", "user.name", "fixture")
    (root / "blob.bin").write_bytes(b"\x00Secretword\x00")
    (root / "calc.py").write_text("def validate(name):\n    return name\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "parent")
    parent = _git(root, "rev-parse", "HEAD")
    (root / "calc.py").write_text("def validate(name):\n    return Secretword(name)\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "change")
    repo, commit = GitRepo(root), _git(root, "rev-parse", "HEAD")
    novel = novel_tokens(repo, parent=parent, commit=commit, paths=("calc.py",))
    view = gold_view(repo, parent=parent, commit=commit, src_paths=("calc.py",), test_paths=())
    assert view is not None
    assert view.parent_has("Secretword")
    assert "Secretword" in novel and "Secretword" in view.novel


# -- provenance: product means the parent's product code ---------------------------------------


def test_provenance_product_needs_the_token_in_parent_product_code() -> None:
    """A word the parent holds only in a comment or a test file is not ``product``: it ranks
    by the change's post-images (here the source: ``change_detail``)."""
    item = StatedItem("i01", "name", "Add validate", "product", ("validate",))
    weak = gold(product_has=lambda tok: False)
    assert stated.REASON_PROVENANCE in req_guard(entry(item).text, (item,), "prose", weak)
    relabelled = StatedItem("i01", "name", "Add validate", "change_detail", ("validate",))
    assert req_guard(entry(relabelled).text, (relabelled,), "prose", weak) == []


def test_provenance_never_drops_below_product_for_a_parent_word() -> None:
    """A parent word neither post-image holds stays ``product``, never ``nowhere``, however
    the parent holds it."""
    item = StatedItem("i01", "rule", "Keep the Config loader", "product", ("Config",))
    view = gold(product_has=lambda tok: False)
    assert req_guard(entry(item).text, (item,), "prose", view) == []


@pytest.fixture
def comment_and_test_only(tmp_path: Path) -> tuple[GitRepo, str, str]:
    root = tmp_path / "prov"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "config", "user.name", "fixture")
    (root / "encode.py").write_text(
        "# Marshal is the counterpart of Unmarshal\ndef Unmarshal(b):\n    return b\n"
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_header.py").write_text("def test_h():\n    h = Clone()\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "parent")
    parent = _git(root, "rev-parse", "HEAD")
    (root / "encode.py").write_text(
        "# Marshal is the counterpart of Unmarshal\ndef Unmarshal(b):\n    return b\n"
        "def Marshal(v):\n    return Clone(v)\n"
    )
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "change")
    return GitRepo(root), parent, _git(root, "rev-parse", "HEAD")


def test_gold_view_product_has_skips_comments_and_test_files(
    comment_and_test_only: tuple[GitRepo, str, str],
) -> None:
    repo, parent, commit = comment_and_test_only
    view = gold_view(repo, parent=parent, commit=commit, src_paths=("encode.py",), test_paths=())
    assert view is not None
    assert view.parent_has("Marshal") and view.parent_has("Clone")
    assert view.product_has is not None
    assert not view.product_has("Marshal") and not view.product_has("Clone")
    assert view.product_has("Unmarshal")
    for tok in ("Marshal", "Clone"):
        item = StatedItem("i01", "name", f"Add {tok}", "product", (tok,))
        assert stated.REASON_PROVENANCE in req_guard(entry(item).text, (item,), "prose", view)
        moved = StatedItem("i01", "name", f"Add {tok}", "change_detail", (tok,))
        assert req_guard(entry(moved).text, (moved,), "prose", view) == []
