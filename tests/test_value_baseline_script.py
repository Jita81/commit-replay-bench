"""The export reader behind the value baseline — the product's failure rule, not the export's.

Navigation
----------
What it is:   The test suite for ``scripts/value_baseline.py``, the reader that turns an exported
              ledger (pipe-separated, or the product's own JSONL) and an exported review file
              into the scorecard.
What it does: Pins that every row's failure kind is recomputed with the product's rule from the
              error class — a usage limit is an outage, a missing key or a missing runner tool is
              harness, a network or archaeology refusal is protocol — and never read from the
              export's crude column; that a budget stop and a lint-only failure survive; that a
              review whose statement the operator marked as a flag defect is corrected in the
              reader and counted as corrected; that the critical-friend cobra reviews can be
              left out; and that the JSONL export reads through ``GradeRow`` unchanged.
How:          Small export files written to ``tmp_path``; the script loaded as a module.
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   scripts/value_baseline.py (under test), src/crb/core/value.py (the report it
              feeds), src/crb/core/ledger.py (``derive_failure_kind`` — the rule it applies),
              docs/reviews/2026-09-25-value-baseline.md (the page it regenerates)
Tested by:    tests/test_value_baseline_script.py
Touch when:   the export's columns or error classes change (add the class to ``ERRCLASS`` and a
              case here), or the review export gains a column.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

from crb.core.value import default_register
from fixtures.posture import posture_row

ROOT = Path(__file__).resolve().parents[1]
HEADER = (
    "seq|created|repo|class|size|mode|step|clean|dq|failure_kind|trial|run|task|cost|latency|"
    "apparatus|gold_clean|oracle|rung|tests_unmod|target_green|no_new|lint|errclass"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "value_baseline", ROOT / "scripts" / "value_baseline.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["value_baseline"] = mod
    spec.loader.exec_module(mod)
    return mod


def _row(
    n: int,
    *,
    mode: str = "blind",
    clean: str = "0",
    kind: str = "",
    err: str = "",
    lint: str = "",
    latency: str = "60",
    cost: str = "1.0",
    dq: str = "0",
) -> str:
    return (
        f"|2026-09-14T00:{n:02d}:00+00:00|cobra|bug.fix|XS|{mode}|replay|{clean}|{dq}|{kind}|r1|run1|"
        f"task{n:08d}|{cost}|{latency}|2.2|1||r1|1|{'1' if clean == '1' or kind == 'lint' else '0'}|1|"
        f"{lint}|{err}"
    )


@pytest.fixture
def vb() -> ModuleType:
    return _load()


def test_the_failure_kind_is_the_products_rule_not_the_exports(
    vb: ModuleType, tmp_path: Path
) -> None:
    lines = [
        HEADER,
        _row(1, err="U", kind="harness"),
        _row(2, err="K", kind="harness"),
        _row(3, err="PN", kind="protocol"),
        _row(4, err="PA"),
        _row(5, err="EJ"),
        _row(6, kind="budget", latency="900"),
        _row(7, kind="budget", latency="120"),
        _row(8, kind="lint", lint="0"),
        _row(9, clean="1", lint="1"),
        _row(10),
        _row(11, dq="1"),
    ]
    p = tmp_path / "ledger.psv"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rows = vb.read_ledger(p)
    got = [(r.failure_kind, r.detail) for r in rows]
    assert got == [
        ("outage", "usage-limit"),
        ("harness", "api-key-missing"),
        ("protocol", "network"),
        ("protocol", "archaeology"),
        ("harness", "runner-tool-missing:jest"),
        ("budget", "wall_clock"),
        ("budget", "other_cap"),
        ("lint", ""),
        ("", ""),
        ("builder_red", ""),
        ("disqualified", ""),
    ]
    assert rows[8].clean and rows[8].repo_lint_clean is True and rows[0].cost_usd == 1.0


def test_an_unknown_error_class_is_refused(vb: ModuleType, tmp_path: Path) -> None:
    p = tmp_path / "ledger.psv"
    p.write_text(HEADER + "\n" + _row(1, err="ZZ") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ZZ"):
        vb.read_ledger(p)


def test_reviews_correct_the_flag_defect_and_can_drop_the_critical_friend_three(
    vb: ModuleType, tmp_path: Path
) -> None:
    p = tmp_path / "reviews.psv"
    p.write_text(
        "repo|task|grade_clean|verdict|mergeable_flag|finding_kinds|statement_head\n"
        "mesh-client|0b0457d694|true|ok|true||XS sighted. Mergeable as-is.\n"
        "nhsuk-frontend|fd45bdd8be|true|ok|false||XS sighted. Mergeable. (FLAG DEFECT: statement says mergeable, stored flag false)\n"
        "nhsuk-frontend|c11684dd28|true|style|false|style|XS sighted. Not mergeable.\n",
        encoding="utf-8",
    )
    verdicts, corrected = vb.read_reviews(p, critical_friend=False)
    assert corrected == 1
    assert [v.mergeable for v in verdicts] == [True, True, False]
    # the words decide, not an export's hand-written mark: stream K's rule corrects an
    # unmarked contradiction too, in either direction, and leaves a silent statement alone
    q = tmp_path / "unmarked.psv"
    q.write_text(
        "repo|task|grade_clean|verdict|mergeable_flag|finding_kinds|statement_head\n"
        "a|t1|true|ok|false||XS sighted. Byte-identical to the gold. Mergeable.\n"
        "a|t2|true|defect|true|defect|S blind. Not mergeable: the loop never ends.\n"
        "a|t3|true|style|false|style|L sighted. Clean, but the feature is not delivered.\n",
        encoding="utf-8",
    )
    unmarked, fixed = vb.read_reviews(q, critical_friend=False)
    assert fixed == 2 and [v.mergeable for v in unmarked] == [True, False, False]
    assert verdicts[2].finding_kinds == ("style",) and verdicts[0].grade_row_hash == ""
    with_cf, _ = vb.read_reviews(p, critical_friend=True)
    assert len(with_cf) == 6 and all(v.mergeable is False for v in with_cf[3:])


def test_a_jsonl_export_reads_through_the_grade_row(vb: ModuleType, tmp_path: Path) -> None:
    row = posture_row(
        repo="alpha",
        task_id="a" * 40,
        clean=False,
        tests_unmodified=True,
        target_green=False,
        no_new_failures=None,
        source_changed=None,
        mode="blind",
        labels={"stop_reason": "max_turns"},
    ).chained("0" * 64)
    p = tmp_path / "ledger.jsonl"
    p.write_text(json.dumps(row.to_dict()) + "\n", encoding="utf-8")
    (v,) = vb.read_ledger(p)
    assert v.failure_kind == "budget" and v.row_hash == row.row_hash and v.detail == "max_turns"


def test_the_markdown_carries_n_method_and_apparatus_on_every_figure(
    vb: ModuleType, tmp_path: Path
) -> None:
    p = tmp_path / "ledger.psv"
    p.write_text(
        "\n".join([HEADER, _row(1, clean="1", lint="1"), _row(2)]) + "\n", encoding="utf-8"
    )
    out = vb.render_markdown(vb.read_ledger(p), [], apparatus="all")
    assert "| measure |" in out and "n = 2" in out and "apparatus" in out


def test_the_baseline_page_quotes_its_own_tables_and_names_the_live_register() -> None:
    """docs/PREVENTION.md P-015: the page's prose once quoted a learning curve (16% → 54%)
    its own generated table did not show (14% → 50%), and its tables named a stub register
    after the prevention loop was wired. The prose must quote the table the script printed,
    and every register the tables name must be the one ``default_register`` returns."""
    page = (ROOT / "docs/reviews/2026-09-25-value-baseline.md").read_text(encoding="utf-8")
    head, _sep, _rest = page.partition("**The same figures pooled")
    rates = [
        float(m.group(1))
        for m in re.finditer(r"^\| \d+ \| [^|]+ \| \d+ \| \d+ \| \d+ / \d+ = ([\d.]+)%", head, re.M)
    ]
    assert len(rates) >= 2, "the apparatus 2.2 curve table is missing"
    prose = " ".join(page.split())
    said = re.search(
        r"was (\d+)% in the first window of fifty attempts and (\d+)% in the last", prose
    )
    assert said is not None, "the page no longer quotes the curve's first and last windows"
    assert (int(said.group(1)), int(said.group(2))) == (round(rates[0]), round(rates[-1]))
    named = set(re.findall(r"bug classes closed \(register: `([^`]+)`\)", page))
    assert named == {default_register().source}


def _rows_of(table: str) -> dict[str, str]:
    """``measure → value`` for one generated table (the page's first or second)."""
    out: dict[str, str] = {}
    for m in re.finditer(r"^\| ([^|]+) \| ([^|]+) \|", table, re.M):
        out[m.group(1).strip()] = m.group(2).strip()
    return out


def test_every_figure_the_prose_quotes_is_in_the_generated_tables() -> None:
    """P-015's class, beyond the curve sentence: the headline percentage, the pounds, the
    task count, the routing, the proxy, the process loss and the rungs the prose quotes must
    each be what the generated tables say (a hand-typed figure that drifts fails here)."""
    page = (ROOT / "docs/reviews/2026-09-25-value-baseline.md").read_text(encoding="utf-8")
    head, _sep, pooled = page.partition("**The same figures pooled")
    t22, tall = _rows_of(head), _rows_of(pooled.partition("**Where this differs")[0])
    prose = " ".join(page.split())

    def said(pattern: str) -> tuple[str, ...]:
        m = re.search(pattern, prose)
        assert m is not None, f"the page no longer says: {pattern}"
        return m.groups()

    working = float(
        re.match(r"([\d.]+)%", t22["**working rate, blind** (clean x precision)"]).group(1)
    )  # type: ignore[union-attr]
    assert int(said(r"About (\d+)% of blind attempts")[0]) == round(working)
    per = t22["**working changes per pound, blind**"]
    pounds, low, high = (
        float(x)
        for x in re.search(
            r"about £([\d.]+) per working change \(£([\d.]+)-£([\d.]+)\)", per
        ).groups()
    )  # type: ignore[union-attr]
    assert int(said(r"one working change for every £(\d+)")[0]) == round(pounds)
    a, b = said(r"from about £([\d.]+) to about £(\d+) per working change")
    assert (float(a), int(b)) == (low, round(high))
    n, tasks = said(r"n = (\d+) valid blind attempts on (\d+) tasks")
    assert f"n = {n} attempts on {tasks} tasks" in page
    k_c, t_c = said(r"and the (\d+) clean ones on (\d+)")
    assert f"{n} valid on {tasks} tasks ({k_c} clean on {t_c} tasks)" in head
    k, d = said(r"— (\d+) of (\d+) came out clean")
    assert t22["deliver decisions made prospectively, clean"].startswith(f"{k} / {d} =")
    assert said(r"All (\d+) were sighted")[0] == d
    assert f"by mode: sighted {d}" in t22["deliver decisions made prospectively, clean"]
    pk, pn = said(r"called (\d+) of (\d+) clean patches working under apparatus 2.2")
    assert t22["proxy: clean patches lint-clean with no API break"].startswith(f"{pk} / {pn} =")
    bp, fails, wall = said(r"refusals are (\d+) of the (\d+) valid failures, and (\d+) budget")
    kinds = {
        kv.rsplit(" ", 1)[0]: int(kv.rsplit(" ", 1)[1])
        for kv in tall["non-clean valid by kind"].split(", ")
    }
    assert int(bp) == kinds["budget"] + kinds["protocol"] and int(fails) == sum(kinds.values())
    spend = tall["spend on budget-stopped attempts"]
    assert f"; {wall} at the 900 s wall clock" in spend
    usd, all_usd = said(r"cost \$([\d.]+) of the \$([\d.]+) spent")
    assert spend.startswith(f"${usd} of ${all_usd}")
    words = {"Two": 2, "forty": 40}
    r2, r40 = said(r"(\w+) of (\w+) valid attempts on the second and third rungs")
    assert t22["escalation rungs r2 / r3, clean"] == f"{words[r2]} / {words[r40]}"


def test_a_percentage_is_rounded_once_from_the_exact_counts(vb: ModuleType) -> None:
    """155 / 259 is 59.846…%: formatting the report's 4-place point (0.5985) again printed
    59.9%. The page formats from k / n and the exact Wilson bounds (P-028)."""
    from crb.core.stats import wilson_interval

    for k, n in ((155, 259), (2, 24), (153, 155), (22, 94), (0, 17), (17, 20)):
        ci = wilson_interval(k, n)
        served = {
            "k": k,
            "n": n,
            "point": round(k / n, 4),
            "ci_low": round(ci.low, 4),
            "ci_high": round(ci.high, 4),
        }
        want = (
            f"{k} / {n} = {100 * k / n:.1f}% (Wilson 95% {100 * ci.low:.1f}%-{100 * ci.high:.1f}%)"
        )
        assert vb._rate(served) == want


def test_only_the_baseline_page_quotes_the_generated_register() -> None:
    """ADR-0020 once carried its own hand-made register table, and it drifted from the
    generated one within the day (P-015's class on a second page). The register's tables are
    printed by ``scripts/prevention_from_export.py --md`` and pasted into ONE page; any other
    page points there."""
    header = "| class | first attempts (blind / sighted) |"
    quoting = sorted(
        str(p.relative_to(ROOT))
        for p in (ROOT / "docs").rglob("*.md")
        if header in p.read_text(encoding="utf-8")
    )
    assert quoting == ["docs/reviews/2026-09-25-value-baseline.md"]
    adr = (ROOT / "docs/adr/0020-a-bug-is-closed-by-prevention.md").read_text(encoding="utf-8")
    section = adr.partition("### What the register would do today")[2].partition("\n## ")[0]
    assert "2026-09-25-value-baseline.md" in section and "\n|" not in section


def test_the_register_renderer_prints_the_pages_table_shape() -> None:
    spec = importlib.util.spec_from_file_location(
        "prevention_from_export", ROOT / "scripts" / "prevention_from_export.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    summary = {
        "repo": "cobra",
        "first_attempts": 3,
        "blind_first_attempts": 1,
        "sighted_first_attempts": 2,
        "largest_blind_class": {"signature": "harness:other", "first_attempts": 1},
        "classes": [
            {
                "signature": "harness:other",
                "first_attempts": 1,
                "first_attempts_by_mode": {"blind": 1},
                "stratum": "1 of 3 blind (apparatus 2.2)",
                "tasks": 1,
                "cost_usd": 0.44,
                "actionable": False,
                "lever": "",
                "level": "",
                "would_file": ["item:prevent-class"],
                "status": "open",
                "qualifiers": ["watch"],
            }
        ],
    }
    lines = mod.render_md([summary])
    page = (ROOT / "docs/reviews/2026-09-25-value-baseline.md").read_text(encoding="utf-8")
    assert lines[2] in page  # the header row the page carries
    assert lines[4] == (
        "| `harness:other` | 1 (1 / 0) | 1 of 3 blind (apparatus 2.2) | 1 | $0.44 | no | "
        "none the loop may apply | `item:prevent-class` | open (watch) |"
    )
