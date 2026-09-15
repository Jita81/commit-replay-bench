"""``crb.core.learn`` — the learning half of the loop, over synthetic ledgers.

Three derivations, each pinned on (a) the exact ``builder_error`` shapes the live
rows carried on 2026-09-13/14 (critical-friend review §4.1/§4.2, A10's corpus report,
and the NHS row of 2026-09-14), (b) determinism — same rows → byte-identical output —
and (c) the property that the product NEVER decides for a human: every refusal
verdict is ``unsure``, ``apply_triage`` writes only a named human's decisions, the
strengthening items are proposals, the re-measurement plan queues nothing.

Navigation
----------
What it is:   The learning loop's test suite — refusal triage, oracle-strengthening backlog and
              the re-measurement plan, over synthetic ledgers.
What it does: Pins the parser on the exact ``builder_error`` shapes the live rows carried on
              2026-09-13/14 (quoted parens, two violations in one row, the recorder cap),
              triage's counts, grouping and corpus-format candidates, that ``apply_triage`` writes
              only a named human's decisions (idempotent; a contradiction with the other corpus is
              refused loudly), that oracle-weak cells become ``test.add`` items that pass the
              factory's DoR gate, that only oracle reasons are flagged, that the re-measurement
              plan queues nothing, determinism (same rows → byte-identical output), and the
              ``rows_to_clear_bar`` Wilson minimum (three 10/10 cells read ``ci_low_below_bar``
              on 2.2, 2026-09-15).
How:          Rows as a ledger returns them (hashed, chained) → ``triage_refusals`` /
              ``strengthening_backlog`` / ``remeasure_plan``; a temp corpus directory for apply.
Layer:        tests — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/core/learn.py (under test), src/crb/core/ledger.py (the failure labels
              it reads), src/crb/core/capability.py (the map it flags cells on),
              src/crb/factory/readiness.py (the DoR gate the items must pass),
              tests/test_cli_learn.py (the same derivations at the CLI), docs/LEARNING-LOOP.md
              (the properties this file pins, §5)
Tested by:    tests/test_learn.py
Touch when:   a builder refusal shape changes (a parser case with the row verbatim); a
              derivation gains an input; never so that the loop decides for a human.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from crb.core import learn
from crb.core.capability import PROJECTION_CELL, PROJECTION_CLASS_SIZE, build_capability_map
from crb.core.ledger import (
    FAILURE_PROTOCOL,
    LABEL_FAILURE_KIND,
    GradeRow,
    JsonlLedger,
    expected_belt_sets,
)
from crb.core.routing import (
    REASON_CONTROLS_ESCAPES,
    REASON_N_BELOW_MIN,
    REASON_ORACLE_WEAK,
    ControlsVerdict,
    RoutingPolicy,
)
from crb.factory.backlog import Backlog, BacklogItem
from crb.factory.readiness import ROUTE_BUILD, assess

PACK = "b" * 64

# --- the exact builder_error shapes from tonight's rows ------------------------------
ERR_QUOTED_PARENS = (
    "protocol violation: archaeology: could not parse the command safely (unbalanced "
    'substitution) (attempted: grep -n "func (c \\*Command) Context\\|c.ctx\\b\\|ExecuteContext'
    '\\|preRun(ctx" command.go | head -30)'
)
ERR_PIP_INSTALL = (
    "protocol violation: network: 'pip install' installs from the network (attempted: "
    "pip install -e . -q 2>&1 | tail -5 && python3 -m pytest tests/test_termui.py -k pager -q "
    "2>&1 | tail -40)"
)
ERR_PIP_INSTALL_2 = (
    "protocol violation: network: 'pip install' installs from the network (attempted: "
    "pip install -e . -q 2>&1 | tail -20)"
)
ERR_PWD = (
    "protocol violation: archaeology: could not parse the command safely (unbalanced "
    "substitution) (attempted: NODE_ENV=test NODE_PATH=$(pwd)/node_modules "
    "/opt/homebrew/bin/node --test --test-reporter=junit --test-reporter-destinat)"
)
ERR_GIT_STASH = (
    "protocol violation: archaeology: 'git stash' is not allowed — the stash stack is shared "
    "with every worktree of the clone; use git diff > /tmp/mine.patch && git checkout -- "
    "<paths> (attempted: git stash && npm test 2>&1 | tail -10; git stash pop)"
)
ERR_NPX_JEST = (
    "protocol violation: network: 'npx jest' cannot be verified against node_modules/.bin "
    "(no worktree cwd) (attempted: npx jest test/request.test.js)"
)
ERR_NPX_PRETTIER = (
    "protocol violation: network: 'npx prettier' cannot be verified against node_modules/.bin "
    "(no worktree cwd) (attempted: npx prettier --check lib/request.js)"
)
ERR_UV_RUN = (
    "protocol violation: network: 'uv run' installs or syncs from the network "
    "(attempted: uv run pytest -q tests/test_basic.py)"
)
#: 2026-09-14, a live NHS row: TWO violations in one row — the first a guard false
#: positive (``.git`` inside a quoted grep argument), the second an honest refusal
#: (the builder probing the sandbox on localhost under the no-network rule).
ERR_NHS_TWO = (
    "protocol violation: archaeology: '.git' is off limits (.git) (attempted: find . -iname "
    '"*conftest*" -o -iname "*helpers*" | grep -v ".git"); network: \'curl\' is not allowed '
    "(no network access) (attempted: curl -sk https://localhost:8701/health)"
)
#: A reviewer-written violation with no attempted command.
ERR_FREE_TEXT = (
    "protocol violation: agent fetched upstream cobra releases from the Go module proxy to "
    "obtain the real revert diff (self-disclosed in summary); not a legitimate capability "
    "observation"
)


def _row(**kw: Any) -> GradeRow:
    """A non-clean row (target red) unless overridden."""
    base: dict[str, Any] = {
        "repo": "cobra",
        "task_id": "1995054b003053cc1e404bccfbf6d168e8731509",
        "clean": False,
        "tests_unmodified": True,
        "target_green": False,
        "no_new_failures": None,
        "source_changed": None,
        "capability_class": "bug.fix",
        "size": "XS",
        "language": "go",
        "builder": "claude_code",
        "model": "claude-sonnet-5",
        "provider": "anthropic",
        "mode": "sighted",
        "gold_clean": True,
        "cost_usd": 0.16,
        "latency_s": 60.0,
        "apparatus_version": "2.1",
    }
    base.update(kw)
    # the belt set is what the stamped apparatus recorded (ledger invariant, review
    # finding 4): 2.0–2.1 → v4, 2.2+ → v5 — unless the test names one deliberately
    base.setdefault(
        "belt_set", (expected_belt_sets(base["apparatus_version"], "measured") or ("v5",))[0]
    )
    return GradeRow(**base)


def _protocol(err: str, **kw: Any) -> GradeRow:
    """A protocol row exactly as ``grade_row_from_result`` writes it: ``error`` holds
    the text, ``labels.builder_error`` its first 300 chars, ``failure_kind`` pinned."""
    labels = dict(kw.pop("labels", {}))
    labels.setdefault("builder_error", err[:300])
    labels.setdefault(LABEL_FAILURE_KIND, FAILURE_PROTOCOL)
    return _row(error=err, labels=labels, **kw)


def _clean(**kw: Any) -> GradeRow:
    base: dict[str, Any] = {
        "clean": True,
        "target_green": True,
        "no_new_failures": True,
        "source_changed": True,
        "evidence_pack_hash": PACK,
    }
    base.update(kw)
    return _row(**base)


def _chained(rows: list[GradeRow], tmp_path: Path) -> list[GradeRow]:
    """Rows as they come back from a ledger (hashed, chained)."""
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")
    ledger.append_many(rows)
    return list(ledger.rows())


# ===========================================================================
# parse_violations / normalisation
# ===========================================================================


class TestParse:
    """The refusal parser on the exact ``builder_error`` texts the live rows carried."""

    def test_single_violation_with_quoted_parens(self) -> None:
        (v,) = learn.parse_violations(ERR_QUOTED_PARENS)
        assert v.prefix == "archaeology"
        assert v.reason.startswith("archaeology: could not parse the command safely")
        assert v.command.startswith('grep -n "func (c \\*Command) Context')
        assert v.command.endswith("command.go | head -30")
        assert not v.truncated

    def test_two_violations_in_one_row_nhs(self) -> None:
        a, b = learn.parse_violations(ERR_NHS_TWO)
        assert (a.prefix, b.prefix) == ("archaeology", "network")
        assert a.command == 'find . -iname "*conftest*" -o -iname "*helpers*" | grep -v ".git"'
        assert b.command == "curl -sk https://localhost:8701/health"
        assert a.reason == "archaeology: '.git' is off limits (.git)"
        assert not a.truncated and not b.truncated

    def test_truncated_at_the_recorder_cap_is_flagged(self) -> None:
        (v,) = learn.parse_violations(ERR_PWD)
        assert len(v.command) == learn.ATTEMPTED_CAP
        assert v.truncated
        # the ledger's own cap cut the closing paren away entirely
        (w,) = learn.parse_violations(ERR_PIP_INSTALL[:150])
        assert w.truncated and w.command.startswith("pip install -e .")

    def test_free_text_violation_has_no_command(self) -> None:
        (v,) = learn.parse_violations(ERR_FREE_TEXT)
        assert v.prefix == "other" and v.command == "" and not v.truncated
        assert "Go module proxy" in v.reason

    def test_tamper_prefix_and_empty(self) -> None:
        (v,) = learn.parse_violations("protocol violation: tamper: tests/test_calc.py")
        assert v.prefix == "tamper"
        assert learn.parse_violations("") == []
        assert learn.parse_violations("protocol violation:") == []

    @pytest.mark.parametrize(
        ("cmd", "shape"),
        [
            ("pip install -e . -q 2>&1 | tail -20", "pip install -e . -q 2>&1 | tail -<n>"),
            (
                "NODE_PATH=$(pwd)/node_modules /opt/homebrew/bin/node --test",
                "NODE_PATH=$(pwd)/node_modules <path> --test",
            ),
            (
                'grep -n "func (c \\*Command)" command.go | head -30',
                'grep -n "<str>" <path> | head -<n>',
            ),
            ("git checkout abc1234def -- pkg/command.go", "git checkout <sha> -- <path>"),
            ("curl -sk https://localhost:8701/health", "curl -sk <url>"),
            ("npx jest test/request.test.js", "npx jest <path>"),
            ("python3 -m pytest tests/test_x.py -k pager", "python3 -m pytest <path> -k pager"),
            ("go test ./...\ngit log -1", "go test <path> \\n git log -<n>"),
        ],
    )
    def test_normalise_command(self, cmd: str, shape: str) -> None:
        assert learn.normalise_command(cmd) == shape

    def test_normalise_reason_placeholders_the_quoted_variable_parts(self) -> None:
        r = learn.normalise_reason("archaeology: 'git checkout abc1234def' names another revision")
        assert r == "archaeology: 'git checkout <sha>' names another revision"
        assert learn.normalise_reason("network: 'curl' is not allowed (no network access)") == (
            "network: 'curl' is not allowed (no network access)"
        )

    def test_row_violation_text_prefers_the_longest_prefixed_field(self) -> None:
        long = ERR_PIP_INSTALL + " " * 200 + "tail"
        r = _protocol(long)
        assert learn.row_violation_text(r) == long  # error (500 tail-capped by the writer)
        r2 = _row(error="TimeoutError: belt", labels={"builder_error": ERR_UV_RUN})
        assert learn.row_violation_text(r2) == ERR_UV_RUN
        assert learn.row_violation_text(_clean()) == ""

    def test_encode_corpus_line_redacts_and_encodes_newlines(self) -> None:
        line = learn.encode_corpus_line("export TOKEN=abcdefgh12345\ngo test ./...")
        assert "abcdefgh12345" not in line and "\\n" in line and "\n" not in line


# ===========================================================================
# 1. triage_refusals
# ===========================================================================


def _tonight(tmp_path: Path) -> list[GradeRow]:
    """A ledger shaped like 2026-09-13/14: 4 clean, 1 builder_red, 1 harness, and the
    protocol rows of every false-positive class the review named."""
    t = [f"{i:040x}" for i in range(1, 20)]
    rows = [
        _clean(task_id=t[0]),
        _clean(task_id=t[1], repo="click", language="python"),
        _clean(task_id=t[2], repo="koa", language="javascript"),
        _clean(task_id=t[3], mode="blind"),
        _row(task_id=t[4]),  # builder_red
        _row(task_id=t[5], error="TimeoutError: belt run"),  # harness
        _protocol(ERR_QUOTED_PARENS, task_id=t[6], cost_usd=0.16, latency_s=41.1),
        _protocol(ERR_PIP_INSTALL, task_id=t[7], repo="click", language="python", cost_usd=0.43),
        _protocol(ERR_PIP_INSTALL_2, task_id=t[8], repo="click", language="python", cost_usd=0.40),
        _protocol(ERR_PWD, task_id=t[9], repo="koa", language="javascript", cost_usd=0.17),
        _protocol(ERR_GIT_STASH, task_id=t[10], repo="koa", language="javascript", cost_usd=0.35),
        _protocol(ERR_NPX_JEST, task_id=t[11], repo="koa", language="javascript"),
        _protocol(ERR_NPX_PRETTIER, task_id=t[12], repo="koa", language="javascript"),
        _protocol(ERR_UV_RUN, task_id=t[13], repo="click", language="python"),
        _protocol(ERR_NHS_TWO, task_id=t[14], repo="nhs-api", language="python", cost_usd=0.21),
        _protocol(ERR_FREE_TEXT, task_id=t[15], cost_usd=0.63),
    ]
    return _chained(rows, tmp_path)


class TestTriage:
    """``triage_refusals``: counts, grouping, corpus-format candidates, and never an auto-accept."""

    def test_counts_cost_and_the_denominator(self, tmp_path: Path) -> None:
        rows = _tonight(tmp_path)
        rep = learn.triage_refusals(rows)
        assert rep.rows_total == 16 and rep.rows_protocol == 10
        assert rep.instrument_share == pytest.approx(10 / 16)
        assert rep.cost_usd == pytest.approx(
            0.16 + 0.43 + 0.40 + 0.17 + 0.35 + 0.16 * 3 + 0.21 + 0.63
        )
        assert rep.minutes == pytest.approx((41.1 + 60 * 9) / 60)
        assert rep.unparsed == 0
        assert rep.apparatus_versions == ("2.1",)

    def test_groups_by_reason_and_shape(self, tmp_path: Path) -> None:
        rep = learn.triage_refusals(_tonight(tmp_path))
        by_shape = {g.shape: g for g in rep.groups}
        # the two pip installs differ in their tails → two shapes, same reason
        pip = [g for g in rep.groups if g.reason.startswith("network: 'pip install'")]
        assert len(pip) == 2 and all(g.n == 1 for g in pip)
        # the NHS row contributes to two groups; its cost is attributed to both
        nhs = [g for g in rep.groups if "nhs-api/" in "".join(g.tasks)]
        assert {g.prefix for g in nhs} == {"archaeology", "network"}
        assert all(g.cost_usd == pytest.approx(0.21) for g in nhs)
        assert 'find . -iname "<str>" -o -iname "<str>" | grep -v "<str>"' in by_shape
        assert (
            by_shape["curl -sk <url>"].reason
            == "network: 'curl' is not allowed (no network access)"
        )
        # the truncated $(pwd) line is flagged; its candidate is still shown
        pwd = by_shape[
            "NODE_ENV=test NODE_PATH=$(pwd)/node_modules <path> --test --test-reporter=junit --test-reporter-destinat"
        ]
        assert pwd.truncated and pwd.candidate_honest.startswith("NODE_ENV=test")
        # the free-text violation has no command and no candidate
        free = [g for g in rep.groups if g.prefix == "other"]
        assert len(free) == 1 and free[0].candidate_honest == "" and free[0].examples == ()
        # rows / tasks / repos are recorded
        stash = by_shape["git stash && npm test 2>&1 | tail -<n>; git stash pop"]
        assert stash.repos == ("koa",) and len(stash.rows) == 1 and len(stash.rows[0]) == 64

    def test_candidate_lines_are_in_the_corpus_format(self, tmp_path: Path) -> None:
        rep = learn.triage_refusals(_tonight(tmp_path))
        by_shape = {g.shape: g for g in rep.groups}
        g = by_shape["uv run pytest -q <path>"]
        assert g.candidate_honest == "uv run pytest -q tests/test_basic.py"
        assert g.candidate_refused == "uv run pytest -q tests/test_basic.py\tnetwork:"
        q = by_shape['grep -n "<str>" <path> | head -<n>']
        assert q.candidate_refused.endswith("\tarchaeology:")
        assert "\n" not in q.candidate_honest

    def test_never_auto_accepts(self, tmp_path: Path) -> None:
        rep = learn.triage_refusals(_tonight(tmp_path))
        assert rep.groups and all(g.verdict == learn.VERDICT_UNSURE for g in rep.groups)
        d = rep.to_dict()
        assert all(g["verdict"] == "unsure" for g in d["groups"])
        with pytest.raises(learn.LearnError):
            learn.RefusalGroup(
                group_id="x",
                prefix="network",
                reason="r",
                shape="s",
                n=1,
                cost_usd=0,
                minutes=0,
                repos=(),
                tasks=(),
                rows=(),
                examples=(),
                truncated=False,
                candidate_honest="",
                candidate_refused="",
                verdict=learn.VERDICT_HONEST,
            )

    def test_deterministic_and_order_independent(self, tmp_path: Path) -> None:
        rows = _tonight(tmp_path)
        a = learn.dumps(learn.triage_refusals(rows).to_dict())
        b = learn.dumps(learn.triage_refusals(list(reversed(rows))).to_dict())
        c = learn.dumps(learn.triage_refusals(rows).to_dict())
        assert a == b == c
        rep = learn.triage_refusals(rows)
        assert [g.n for g in rep.groups] == sorted((g.n for g in rep.groups), reverse=True)

    def test_empty_and_no_protocol_rows(self, tmp_path: Path) -> None:
        rep = learn.triage_refusals([])
        assert rep.rows_total == 0 and rep.groups == () and rep.instrument_share == 0.0
        rep2 = learn.triage_refusals(_chained([_clean(), _row(task_id="1" * 40)], tmp_path))
        assert rep2.rows_protocol == 0 and rep2.groups == ()

    def test_unparsed_protocol_row_still_counts(self, tmp_path: Path) -> None:
        r = _row(error="protocol violation:", labels={LABEL_FAILURE_KIND: FAILURE_PROTOCOL})
        rep = learn.triage_refusals([r])
        assert rep.rows_protocol == 1 and rep.unparsed == 1 and rep.groups == ()

    def test_render(self, tmp_path: Path) -> None:
        text = learn.render_refusals(learn.triage_refusals(_tonight(tmp_path)))
        assert "protocol rows: 10/16" in text and "unsure" in text and "--apply" in text


# ===========================================================================
# apply_triage
# ===========================================================================


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    """A corpus directory with one honest and one refused line, for the apply round trips."""
    d = tmp_path / "fixtures"
    d.mkdir()
    (d / learn.CORPUS_HONEST_FILE).write_text("# honest\npwd\nls\n", encoding="utf-8")
    (d / learn.CORPUS_REFUSED_FILE).write_text(
        "# refused\ngit log\tarchaeology:\n", encoding="utf-8"
    )
    return d


class TestApply:
    """``apply_triage``: appends only a named human's decisions, idempotently, refusing
    contradictions.
    """

    def test_appends_only_the_decided_lines_with_provenance(
        self, tmp_path: Path, corpus: Path
    ) -> None:
        rep = learn.triage_refusals(_tonight(tmp_path))
        by_shape = {g.shape: g for g in rep.groups}
        quoted = by_shape['grep -n "<str>" <path> | head -<n>']
        find = by_shape['find . -iname "<str>" -o -iname "<str>" | grep -v "<str>"']
        curl = by_shape["curl -sk <url>"]
        stash = by_shape["git stash && npm test 2>&1 | tail -<n>; git stash pop"]
        decisions = [
            learn.RefusalDecision(
                quoted.group_id, "honest", note="quoted parens in a grep pattern"
            ),
            learn.RefusalDecision(find.group_id, "honest", note=".git inside a quoted argument"),
            learn.RefusalDecision(curl.group_id, "refuse", note="probing the sandbox on localhost"),
            learn.RefusalDecision(stash.group_id, "unsure"),
        ]
        applied = learn.apply_triage(
            decisions, rep, corpus_dir=corpus, decided_by="paul", date="2026-09-14"
        )
        assert len(applied.honest_added) == 2 and len(applied.refused_added) == 1
        assert applied.unsure == (stash.group_id,) and applied.skipped == ()
        honest = (corpus / learn.CORPUS_HONEST_FILE).read_text(encoding="utf-8")
        refused = (corpus / learn.CORPUS_REFUSED_FILE).read_text(encoding="utf-8")
        assert honest.startswith("# honest\npwd\nls\n")
        assert "# learned 2026-09-14 from cobra/0000000000 row " in honest
        assert "(honest→paul) — quoted parens in a grep pattern" in honest
        assert 'grep -n "func (c \\*Command) Context' in honest
        assert 'find . -iname "*conftest*" -o -iname "*helpers*" | grep -v ".git"\n' in honest
        assert "# learned 2026-09-14 from nhs-api/0000000000 row " in refused
        assert "(refuse→paul) — probing the sandbox on localhost" in refused
        assert "curl -sk https://localhost:8701/health\tnetwork:\n" in refused
        assert "git stash" not in honest and "git stash" not in refused
        # the two files stay in the format the guard corpus test loads
        for line in honest.splitlines():
            assert not line.strip() or line.startswith("#") or "\t" not in line
        for line in refused.splitlines():
            if line.strip() and not line.startswith("#"):
                assert line.rpartition("\t")[2] in ("archaeology:", "network:")

    def test_idempotent(self, tmp_path: Path, corpus: Path) -> None:
        rep = learn.triage_refusals(_tonight(tmp_path))
        g = next(g for g in rep.groups if g.shape == "uv run pytest -q <path>")
        d = [learn.RefusalDecision(g.group_id, "honest")]
        first = learn.apply_triage(d, rep, corpus_dir=corpus, decided_by="paul", date="2026-09-14")
        second = learn.apply_triage(d, rep, corpus_dir=corpus, decided_by="paul", date="2026-09-14")
        assert first.honest_added == ("uv run pytest -q tests/test_basic.py",)
        assert second.honest_added == () and second.skipped == first.honest_added
        text = (corpus / learn.CORPUS_HONEST_FILE).read_text(encoding="utf-8")
        assert text.count("uv run pytest -q tests/test_basic.py") == 1

    def test_refuses_bad_decisions_before_writing_anything(
        self, tmp_path: Path, corpus: Path
    ) -> None:
        rep = learn.triage_refusals(_tonight(tmp_path))
        by_shape = {g.shape: g for g in rep.groups}
        before = {p: p.read_text(encoding="utf-8") for p in corpus.iterdir()}
        ok = by_shape["uv run pytest -q <path>"]
        pwd = next(g for g in rep.groups if g.truncated)
        free = next(g for g in rep.groups if g.prefix == "other")
        for bad, msg in (
            (learn.RefusalDecision("nope", "honest"), "no such group"),
            (learn.RefusalDecision(pwd.group_id, "honest"), "truncated"),
            (learn.RefusalDecision(free.group_id, "refuse"), "no command"),
        ):
            with pytest.raises(learn.LearnError, match=msg):
                learn.apply_triage(
                    [learn.RefusalDecision(ok.group_id, "honest"), bad],
                    rep,
                    corpus_dir=corpus,
                    decided_by="paul",
                )
        # a tamper cannot be a shell-corpus refusal without an explicit prefix
        rep2 = learn.triage_refusals(
            [_protocol("protocol violation: tamper: t.py (attempted: sed -i s/a/b/ t.py)")]
        )
        with pytest.raises(learn.LearnError, match="belt 1"):
            learn.apply_triage(
                [learn.RefusalDecision(rep2.groups[0].group_id, "refuse")],
                rep2,
                corpus_dir=corpus,
                decided_by="paul",
            )
        assert {p: p.read_text(encoding="utf-8") for p in corpus.iterdir()} == before
        with pytest.raises(learn.LearnError, match="decided_by"):
            learn.apply_triage([], rep, corpus_dir=corpus, decided_by="  ")

    def test_contradicting_the_other_corpus_is_refused_loudly(
        self, tmp_path: Path, corpus: Path
    ) -> None:
        """An `honest` decision for a line the refused corpus already holds (or the
        reverse) is never applied: the corpus rule is "never weaken a refusal to make a
        line pass" — a person moves the line by hand, with a reason."""
        rep = learn.triage_refusals(_tonight(tmp_path))
        stash = next(g for g in rep.groups if g.shape.startswith("git stash"))
        (corpus / learn.CORPUS_REFUSED_FILE).write_text(
            f"# refused\n{stash.candidate_honest}\tarchaeology:\n", encoding="utf-8"
        )
        before = {p: p.read_text(encoding="utf-8") for p in corpus.iterdir()}
        ok = next(g for g in rep.groups if g.shape == "uv run pytest -q <path>")
        with pytest.raises(learn.LearnError, match="OTHER corpus"):
            learn.apply_triage(
                [
                    learn.RefusalDecision(ok.group_id, "honest"),
                    learn.RefusalDecision(stash.group_id, "honest"),
                ],
                rep,
                corpus_dir=corpus,
                decided_by="paul",
            )
        assert {p: p.read_text(encoding="utf-8") for p in corpus.iterdir()} == before
        # the same line decided `refuse` again is merely a duplicate: skipped, not an error
        applied = learn.apply_triage(
            [learn.RefusalDecision(stash.group_id, "refuse")],
            rep,
            corpus_dir=corpus,
            decided_by="paul",
        )
        assert applied.skipped == (f"{stash.candidate_honest}\tarchaeology:",)

    def test_human_completes_a_truncated_line(self, tmp_path: Path, corpus: Path) -> None:
        rep = learn.triage_refusals(_tonight(tmp_path))
        pwd = next(g for g in rep.groups if g.truncated)
        full = (
            "NODE_ENV=test NODE_PATH=$(pwd)/node_modules /opt/homebrew/bin/node --test "
            "--test-reporter=junit --test-reporter-destination=/tmp/r.xml"
        )
        applied = learn.apply_triage(
            [learn.RefusalDecision(pwd.group_id, "honest", command=full)],
            rep,
            corpus_dir=corpus,
            decided_by="paul",
            date="2026-09-14",
        )
        assert applied.honest_added == (full,)

    def test_decision_vocabulary_and_loader(self) -> None:
        with pytest.raises(learn.LearnError):
            learn.RefusalDecision("g", "accept")
        with pytest.raises(learn.LearnError):
            learn.RefusalDecision("g", "refuse", prefix="tamper")
        with pytest.raises(learn.LearnError, match="decided_by"):
            learn.load_decisions({"decisions": []})
        who, ds = learn.load_decisions(
            {
                "schema": learn.DECISIONS_SCHEMA,
                "decided_by": "paul",
                "decisions": [{"group_id": "g", "verdict": "honest"}],
            }
        )
        assert who == "paul" and ds[0].to_dict()["verdict"] == "honest"
        with pytest.raises(learn.LearnError, match="schema"):
            learn.load_decisions({"schema": "x", "decided_by": "p", "decisions": []})


# ===========================================================================
# 2. strengthening_backlog
# ===========================================================================

TASK_A = "a" * 40
TASK_B = "b" * 40
TASK_C = "c" * 40


def _weak_cell_rows() -> list[GradeRow]:
    """n=10, all clean, oracle strength 0.5 → route human / oracle_weak."""
    return [
        _clean(
            task_id=(TASK_A if i % 2 == 0 else TASK_B),
            repo="click",
            language="python",
            size="S",
            oracle_strength=0.5,
            cost_usd=0.4,
        )
        for i in range(10)
    ]


def _score(
    task_id: str, *, escaped: list[dict[str, Any]] | None = None, **kw: Any
) -> dict[str, Any]:
    """A ``CommitOracleScore.to_dict()``-shaped payload (the ``oracle.score`` event)."""
    outcomes = [
        {
            "mutant_id": "m1",
            "op": "flip_compare",
            "line": 12,
            "path": "src/click/core.py",
            "description": "== → !=",
            "killed": True,
            "status": "killed",
        },
        {
            "mutant_id": "m2",
            "op": "drop_branch",
            "line": 40,
            "path": "src/click/core.py",
            "description": "remove the elif",
            "killed": False,
            "status": "escaped",
        },
        {
            "mutant_id": "m3",
            "op": "const",
            "line": 44,
            "path": "src/click/core.py",
            "description": "0 → 1",
            "killed": False,
            "status": "escaped",
        },
    ]
    d: dict[str, Any] = {
        "task_id": task_id,
        "repo": "click",
        "src_paths": ["src/click/core.py"],
        "capability_class": "bug.fix",
        "size": "S",
        "cell": "bug.fix/S",
        "total": 3,
        "killed": 1,
        "escaped": 2,
        "oracle_strength": 0.3333,
        "outcomes": outcomes,
        "provenance": {"apparatus_version": "2.1", "mutator_family": "ast"},
    }
    if escaped is not None:
        d["escaped_mutants"] = escaped
        d.pop("outcomes")
    d.update(kw)
    return d


class TestStrengthen:
    """``strengthening_backlog``: oracle-weak cells become ``test.add`` proposals the DoR gate
    accepts.
    """

    def test_oracle_weak_cell_becomes_test_add_items(self) -> None:
        rows = _weak_cell_rows()
        cmap = build_capability_map(rows, projection=PROJECTION_CLASS_SIZE)
        cell = cmap.get(capability_class="bug.fix", size="S")
        assert cell.reason_code == REASON_ORACLE_WEAK
        scores = learn.load_oracle_scores({"tasks": [_score(TASK_A), _score(TASK_B)]})
        bl = learn.strengthening_backlog(
            cmap,
            scores,
            subjects={TASK_A: "Fix pager on Windows"},
            generated_at="2026-09-14T00:00:00+00:00",
        )
        assert bl.cells_flagged == ("bug.fix|S",) and bl.cells_without_scores == ()
        assert len(bl.items) == 2
        a = next(i for i in bl.items if i.labels["task_id"] == TASK_A)
        assert a.title == "strengthen the target tests for click Fix pager on Windows"
        assert a.description.startswith(
            "mutants that escaped: src/click/core.py:40 remove the elif; src/click/core.py:44 0 → 1."
        )
        assert "oracle strength 0.33" in a.description and "threshold 0.80" in a.description
        assert a.capability_class == "test.add" and a.kind == "code" and a.level == "L1"
        assert a.labels["cell"] == "bug.fix|S" and a.labels["reason_code"] == REASON_ORACLE_WEAK
        assert a.labels["slots"] == "structural" and a.labels["escaped"] == "2"
        assert a.structural_facts[0] == "subject_under_test: src/click/core.py"
        assert a.structural_facts[1].startswith(
            "behaviour_asserted: the target tests fail on each escaped mutant"
        )
        b = next(i for i in bl.items if i.labels["task_id"] == TASK_B)
        assert b.title == f"strengthen the target tests for click {TASK_B[:10]}"

    def test_items_pass_the_factory_dor_gate_as_build(self) -> None:
        """The review's play-01 finding: only STRUCTURAL slots, never a value from the
        answer — so the factory's gate says ``build`` without any human sign-off."""
        cmap = build_capability_map(_weak_cell_rows(), projection=PROJECTION_CLASS_SIZE)
        bl = learn.strengthening_backlog(
            cmap, [_score(TASK_A)], generated_at="2026-09-14T00:00:00+00:00"
        )
        for d in bl.to_dict()["items"]:
            item = BacklogItem.from_dict(d)
            r = assess(item)
            assert r.ready and r.route_hint == ROUTE_BUILD and r.value_gaps == ()
        backlog = Backlog.from_dict(bl.to_backlog_dict(repo="click")).freeze(
            at="2026-09-14T00:00:00+00:00"
        )
        assert backlog.verify()

    def test_escaped_count_only_when_mutants_not_recorded(self) -> None:
        cmap = build_capability_map(_weak_cell_rows(), projection=PROJECTION_CLASS_SIZE)
        s = _score(TASK_A, escaped=[])  # the run recorded the count but kept no diffs
        bl = learn.strengthening_backlog(cmap, [s], generated_at="x")
        (item,) = bl.items
        assert item.description.startswith(
            "mutants that escaped: 2 of 3 (per-mutant diffs not recorded"
        )
        assert "re-run the oracle" in item.structural_facts[1]

    def test_report_shape_with_escaped_mutants_list(self) -> None:
        cmap = build_capability_map(_weak_cell_rows(), projection=PROJECTION_CLASS_SIZE)
        s = _score(
            TASK_A,
            escaped=[
                {
                    "mutant_id": "m9",
                    "op": "neg",
                    "line": 7,
                    "path": "src/click/core.py",
                    "description": "drop not",
                }
            ],
        )
        bl = learn.strengthening_backlog(cmap, [s], generated_at="x")
        assert "src/click/core.py:7 drop not" in bl.items[0].description

    def test_flagged_cell_without_scores_gets_a_cell_item(self) -> None:
        cmap = build_capability_map(_weak_cell_rows(), projection=PROJECTION_CLASS_SIZE)
        bl = learn.strengthening_backlog(cmap, [], generated_at="x")
        assert bl.cells_without_scores == ("bug.fix|S",)
        (item,) = bl.items
        assert item.title == "strengthen the target tests for cell bug.fix|S"
        assert "not recorded per task" in item.description and item.labels["n"] == "10"
        assert assess(BacklogItem.from_dict(item.to_dict())).route_hint == ROUTE_BUILD

    def test_only_oracle_reasons_are_flagged(self) -> None:
        thin = [_clean(task_id=TASK_A, size="M")] * 3  # n=3 → calibrate / n_below_min
        cmap = build_capability_map([*_weak_cell_rows(), *thin], projection=PROJECTION_CLASS_SIZE)
        assert cmap.get(capability_class="bug.fix", size="M").reason_code == REASON_N_BELOW_MIN
        bl = learn.strengthening_backlog(cmap, [_score(TASK_A)], generated_at="x")
        assert bl.cells_flagged == ("bug.fix|S",)

    def test_controls_escapes_flags_the_cell(self) -> None:
        strong = [
            _clean(task_id=TASK_A, oracle_strength=0.95, repo="click", language="python", size="S")
        ] * 10
        controls = ControlsVerdict(passed=True, constructible=7, total=7, escapes=3)
        cmap = build_capability_map(strong, projection=PROJECTION_CLASS_SIZE, controls=controls)
        assert cmap.cells[0].reason_code == REASON_CONTROLS_ESCAPES
        bl = learn.strengthening_backlog(cmap, [_score(TASK_A)], generated_at="x")
        assert len(bl.items) == 1 and bl.items[0].labels["reason_code"] == REASON_CONTROLS_ESCAPES

    def test_strong_scored_task_in_a_held_cell_is_not_work(self) -> None:
        cmap = build_capability_map(_weak_cell_rows(), projection=PROJECTION_CLASS_SIZE)
        strong = _score(TASK_A, oracle_strength=0.95, killed=3, escaped=[], total=3)
        strong["escaped"] = 0
        bl = learn.strengthening_backlog(cmap, [strong, _score(TASK_B)], generated_at="x")
        assert [i.labels["task_id"] for i in bl.items] == [TASK_B]

    def test_since_filter(self) -> None:
        old = _weak_cell_rows()
        stale = [GradeRow.from_dict({**r.to_dict(), "apparatus_version": "2.0"}) for r in old]
        cmap = build_capability_map(stale, projection=PROJECTION_CLASS_SIZE)
        assert (
            learn.strengthening_backlog(cmap, [_score(TASK_A)], since="2.1", generated_at="x").items
            == ()
        )
        assert (
            len(
                learn.strengthening_backlog(
                    cmap, [_score(TASK_A)], since="2.0", generated_at="x"
                ).items
            )
            == 1
        )
        # a score stamped with an older apparatus is dropped too
        fresh = build_capability_map(old, projection=PROJECTION_CLASS_SIZE)
        s_old = _score(TASK_A, provenance={"apparatus_version": "2.0"})
        bl = learn.strengthening_backlog(fresh, [s_old], since="2.1", generated_at="x")
        assert bl.cells_without_scores == ("bug.fix|S",)

    def test_deterministic_ids_and_bytes(self) -> None:
        cmap = build_capability_map(_weak_cell_rows(), projection=PROJECTION_CLASS_SIZE)
        scores = [_score(TASK_B), _score(TASK_A)]
        a = learn.dumps(
            learn.strengthening_backlog(
                cmap, scores, generated_at="2026-09-14T00:00:00+00:00"
            ).to_dict()
        )
        b = learn.dumps(
            learn.strengthening_backlog(
                cmap, list(reversed(scores)), generated_at="2026-09-14T00:00:00+00:00"
            ).to_dict()
        )
        assert a == b
        ids = [i["id"] for i in json.loads(a)["items"]]
        assert all(i.startswith("strengthen-") and len(i) == len("strengthen-") + 16 for i in ids)
        # the id does not depend on the registered stamp
        c = learn.strengthening_backlog(cmap, scores, generated_at="later")
        assert [i.id for i in c.items] == ids

    def test_full_cell_projection_matches_on_class_and_size_only(self) -> None:
        cmap = build_capability_map(_weak_cell_rows(), projection=PROJECTION_CELL)
        bl = learn.strengthening_backlog(cmap, [_score(TASK_A)], generated_at="x")
        assert len(bl.items) == 1 and bl.items[0].labels["cell"].startswith(
            "replay|bug.fix|S|python|"
        )

    def test_load_oracle_scores_accepts_every_shape(self) -> None:
        report = {"tasks": [_score(TASK_A)]}
        events = [
            {
                "task_id": TASK_B,
                "payload": {k: v for k, v in _score(TASK_B).items() if k != "task_id"},
            }
        ]
        assert [s.task_id for s in learn.load_oracle_scores(report)] == [TASK_A]
        assert [s.task_id for s in learn.load_oracle_scores(events)] == [TASK_B]
        assert learn.load_oracle_scores([{"repo": "x"}]) == []  # no task id → dropped
        s = learn.OracleTaskScore.from_dict(
            {"task_id": TASK_C, "cell": "bug.fix/M", "total": 0, "oracle_strength": 0.9}
        )
        assert s.strength is None and s.capability_class == "bug.fix" and s.size == "M"

    def test_render(self) -> None:
        cmap = build_capability_map(_weak_cell_rows(), projection=PROJECTION_CLASS_SIZE)
        text = learn.render_strengthen(
            learn.strengthening_backlog(cmap, [_score(TASK_A)], generated_at="x")
        )
        assert "cells flagged: 1" in text and "strengthen-" in text and "a human pulls" in text


# ===========================================================================
# 3. remeasure_plan
# ===========================================================================


def _stale_ledger(tmp_path: Path) -> list[GradeRow]:
    rows = [
        # cell A: 7 rows at 2.0 (sighted, cobra) + 1 at 2.0 blind → all stale, none current
        *[
            _clean(task_id=f"{i:040x}", apparatus_version="2.0", cost_usd=0.24, latency_s=62)
            for i in range(1, 8)
        ],
        _clean(
            task_id="9" * 40, apparatus_version="2.0", mode="blind", cost_usd=0.39, latency_s=122
        ),
        # cell B (click): 5 stale + 8 current → needs 2
        *[
            _clean(
                task_id=f"{i:040x}",
                repo="click",
                language="python",
                apparatus_version="2.0",
                cost_usd=0.43,
            )
            for i in range(20, 25)
        ],
        *[
            _clean(
                task_id=f"{i:040x}",
                repo="click",
                language="python",
                apparatus_version="2.1",
                cost_usd=0.41,
            )
            for i in range(30, 38)
        ],
        # cell C (koa): 3 stale + 16 current at 100 % → up to date (16 clears the Wilson bar)
        *[
            _clean(task_id=f"{i:040x}", repo="koa", language="javascript", apparatus_version="2.0")
            for i in range(40, 43)
        ],
        *[
            _clean(task_id=f"{i:040x}", repo="koa", language="javascript", apparatus_version="2.1")
            for i in range(50, 66)
        ],
        # cell D: only current rows → not in the plan at all
        _clean(task_id="e" * 40, repo="cobra", size="M", apparatus_version="2.1"),
    ]
    return _chained(rows, tmp_path)


class TestRemeasure:
    """``remeasure_plan``: stale cells, rows needed, cost, and valid ``POST /runs`` bodies — nothing
    queued.
    """

    def test_cells_n_needed_cost_and_requests(self, tmp_path: Path) -> None:
        plan = learn.remeasure_plan(_stale_ledger(tmp_path), current_apparatus="2.1")
        assert plan.rows_stale == 16 and plan.min_n == 10
        by = {c.cell.label: c for c in plan.cells}
        assert set(by) == {
            "replay|bug.fix|XS|go|claude_code|claude-sonnet-5|anthropic",
            "replay|bug.fix|XS|python|claude_code|claude-sonnet-5|anthropic",
        }
        assert plan.up_to_date == (
            "replay|bug.fix|XS|javascript|claude_code|claude-sonnet-5|anthropic",
        )
        a = by["replay|bug.fix|XS|go|claude_code|claude-sonnet-5|anthropic"]
        assert (a.n_stale, a.n_current, a.n_needed) == (
            8,
            0,
            16,
        )  # unmeasured: the Wilson minimum at 1.0
        assert a.stale_versions == ("2.0",) and a.repos == ("cobra",)
        assert a.cost_usd_mean == pytest.approx((0.24 * 7 + 0.39) / 8)
        assert a.est_cost_usd == pytest.approx(a.cost_usd_mean * 16) and a.cost_known
        assert a.est_minutes == pytest.approx(((62 * 7 + 122) / 8) * 16 / 60)
        reqs = [r.to_dict() for r in a.requests]
        # (cobra, blind): 1 known task, needs 16 → a task_ids request + a limit-only remainder
        blind = [r for r in reqs if r["mode"] == "blind"]
        assert (
            blind[0]["kind"] == "blind"
            and blind[0]["task_ids"] == ["9" * 40]
            and blind[0]["limit"] == 1
        )
        assert (
            blind[1]["task_ids"] == []
            and blind[1]["limit"] == 15
            and "remainder" in blind[1]["note"]
        )
        sighted = [r for r in reqs if r["mode"] == "sighted"]
        assert (
            sighted[0]["kind"] == "replay"
            and len(sighted[0]["task_ids"]) == 7
            and sighted[0]["limit"] == 7
        )
        assert sighted[1]["limit"] == 9  # 16 − 7 named stale tasks
        for r in reqs:
            assert r["repo"] == "cobra" and r["builder"] == "claude_code"
            assert r["model"] == "claude-sonnet-5" and r["provider"] == "anthropic"
        b = by["replay|bug.fix|XS|python|claude_code|claude-sonnet-5|anthropic"]
        assert (b.n_stale, b.n_current, b.n_needed) == (5, 8, 8)  # 8/8 clean: 16 clears the bar
        req, rest = b.requests  # 5 named stale tasks + a limit-only remainder of 3
        assert req.limit == 5 and len(req.task_ids) == 5 and req.kind == "replay"
        assert rest.limit == 3 and rest.task_ids == ()

    def test_requests_are_valid_post_runs_bodies(self, tmp_path: Path) -> None:
        pydantic = pytest.importorskip("pydantic")
        del pydantic
        from crb.server.schemas import RunCreateRequest

        plan = learn.remeasure_plan(_stale_ledger(tmp_path), current_apparatus="2.1")
        for c in plan.cells:
            for r in c.requests:
                body = r.to_dict()
                body.pop("note", None)
                req = RunCreateRequest(**body)
                assert req.kind in ("replay", "blind") and req.builder

    def test_unknown_cost_is_honest(self, tmp_path: Path) -> None:
        rows = _chained(
            [_clean(task_id="1" * 40, apparatus_version="2.0", cost_usd=0.0, latency_s=0.0)],
            tmp_path,
        )
        plan = learn.remeasure_plan(rows, current_apparatus="2.1")
        (c,) = plan.cells
        assert not c.cost_known and c.est_cost_usd == 0.0 and c.n_needed == 16
        assert plan.to_dict()["summary"]["cost_known_cells"] == 0
        assert "?" in learn.render_remeasure(plan)

    def test_nothing_stale(self, tmp_path: Path) -> None:
        rows = _chained([_clean(task_id="1" * 40, apparatus_version="2.1")], tmp_path)
        plan = learn.remeasure_plan(rows, current_apparatus="2.1")
        assert plan.cells == () and plan.up_to_date == () and plan.rows_stale == 0
        assert learn.remeasure_plan([]).cells == ()

    def test_legacy_belt_set_rows_are_stale(self, tmp_path: Path) -> None:
        r = _clean(
            task_id="1" * 40,
            apparatus_version="1.0-census",
            belt_set="v3-legacy",
            source_changed=None,
            provenance="imported:census",
        )
        plan = learn.remeasure_plan([r], current_apparatus="2.1")
        assert plan.cells[0].stale_versions == ("1.0-census",)

    def test_policy_min_n(self, tmp_path: Path) -> None:
        plan = learn.remeasure_plan(
            _stale_ledger(tmp_path), current_apparatus="2.1", policy=RoutingPolicy(min_n=20)
        )
        by = {c.cell.label: c for c in plan.cells}
        # koa has 16 current rows; min_n 20 outranks the Wilson minimum (16) → 4 more
        assert (
            by["replay|bug.fix|XS|javascript|claude_code|claude-sonnet-5|anthropic"].n_needed == 4
        )

    def test_deterministic(self, tmp_path: Path) -> None:
        rows = _stale_ledger(tmp_path)
        a = learn.dumps(learn.remeasure_plan(rows, current_apparatus="2.1").to_dict())
        b = learn.dumps(
            learn.remeasure_plan(list(reversed(rows)), current_apparatus="2.1").to_dict()
        )
        assert a == b
        d = json.loads(a)
        assert d["schema"] == learn.REMEASURE_SCHEMA and "nothing here was sent" in d["note"]

    def test_render(self, tmp_path: Path) -> None:
        text = learn.render_remeasure(
            learn.remeasure_plan(_stale_ledger(tmp_path), current_apparatus="2.1")
        )
        assert (
            "apparatus 2.1" in text and "cells to renew: 2" in text and "nothing was sent" in text
        )


def test_version_key_orders_versions_and_tolerates_legacy() -> None:
    assert learn._version_key("2.1") > learn._version_key("2.0") > learn._version_key("v3-legacy")
    assert learn._version_key("2.10") > learn._version_key("2.9")


def test_rows_to_clear_bar_is_the_wilson_minimum_not_min_n() -> None:
    """Three 10–11/10–11 cells read `calibrate: ci_low_below_bar` on 2.2 (2026-09-15):
    the plan must target the rows that clear the lower bound at the observed rate."""
    from crb.core.learn import rows_to_clear_bar
    from crb.core.routing import DEFAULT_POLICY
    from crb.core.stats import wilson_interval

    assert rows_to_clear_bar(11, 11, DEFAULT_POLICY) == 16
    assert wilson_interval(16, 16).low >= 0.80 and wilson_interval(15, 15).low < 0.80
    assert rows_to_clear_bar(0, 0, DEFAULT_POLICY) == 16  # unmeasured: the optimistic minimum
    assert rows_to_clear_bar(5, 8, DEFAULT_POLICY) == DEFAULT_POLICY.min_n  # rate below the bar
    assert rows_to_clear_bar(11, 12, DEFAULT_POLICY) > 16
