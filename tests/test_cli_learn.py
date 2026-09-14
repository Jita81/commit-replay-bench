"""``crb learn {refusals,strengthen,remeasure}`` — round trips on a temp ledger.

Every command reads the ledger the way ``crb route`` does (``--path`` or
``<workdir>/ledger.jsonl``), prints a report (text or ``--json``), and never acts:
``refusals --apply`` is the ONE write, and it appends only what a named human
decided to the corpus files under ``--corpus-dir``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from crb.cli.main import main
from crb.core.learn import CORPUS_HONEST_FILE, CORPUS_REFUSED_FILE
from crb.core.ledger import FAILURE_PROTOCOL, LABEL_FAILURE_KIND, GradeRow, JsonlLedger
from crb.core.spec import TaskSpec
from crb.factory.backlog import Backlog

Run = Callable[[Sequence[str]], tuple[int, str, str]]

PACK = "c" * 64
TASK_A = "a" * 40
TASK_B = "b" * 40
ERR_QUOTED = (
    "protocol violation: archaeology: could not parse the command safely (unbalanced "
    'substitution) (attempted: grep -n "func (c \\*Command) Context" command.go | head -30)'
)
ERR_CURL = (
    "protocol violation: network: 'curl' is not allowed (no network access) "
    "(attempted: curl -sk https://localhost:8701/health)"
)


def _row(**kw: Any) -> GradeRow:
    base: dict[str, Any] = {
        "repo": "click",
        "task_id": TASK_A,
        "clean": True,
        "tests_unmodified": True,
        "target_green": True,
        "no_new_failures": True,
        "source_changed": True,
        "capability_class": "bug.fix",
        "size": "S",
        "language": "python",
        "builder": "claude_code",
        "model": "claude-sonnet-5",
        "provider": "anthropic",
        "gold_clean": True,
        "evidence_pack_hash": PACK,
        "cost_usd": 0.4,
        "latency_s": 90.0,
        "oracle_strength": 0.5,
        "apparatus_version": "2.1",
    }
    base.update(kw)
    return GradeRow(**base)


def _protocol(err: str, **kw: Any) -> GradeRow:
    return _row(
        clean=False,
        target_green=False,
        no_new_failures=None,
        source_changed=None,
        evidence_pack_hash="",
        error=err,
        labels={"builder_error": err[:300], LABEL_FAILURE_KIND: FAILURE_PROTOCOL},
        **kw,
    )


@pytest.fixture(scope="module")
def workdir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    wd = tmp_path_factory.mktemp("crb-home") / ".crb"
    ledger = JsonlLedger(wd / "ledger.jsonl")
    rows = [
        # an oracle-weak cell at n=10 (all clean, strength 0.5), tasks A and B
        *[_row(task_id=TASK_A if i % 2 else TASK_B) for i in range(10)],
        # stale evidence in another cell
        *[_row(task_id=f"{i:040x}", size="M", apparatus_version="2.0") for i in range(1, 4)],
        # refusals
        _protocol(ERR_QUOTED, task_id="d" * 40, repo="cobra", language="go"),
        _protocol(ERR_CURL, task_id="e" * 40, repo="nhs-api"),
    ]
    ledger.append_many(rows)
    # task subjects for --repo click
    (wd / "tasks").mkdir(parents=True)
    spec = TaskSpec(
        task_id=TASK_A,
        repo="click",
        subject="Fix pager on Windows",
        authored="2026-01-01T00:00:00+00:00",
        test_files=("tests/test_termui.py",),
        src_files=("src/click/termui.py",),
        target_tests=("tests/test_termui.py",),
        belt_scope=(),
        size="S",
        capability_class="bug.fix",
        language="python",
        gold_clean=True,
    )
    (wd / "tasks" / "click.jsonl").write_text(
        json.dumps(spec.to_dict(), sort_keys=True) + "\n", encoding="utf-8"
    )
    return wd


@pytest.fixture
def run(workdir: Path, capsys: pytest.CaptureFixture[str]) -> Run:
    def _run(argv: Sequence[str]) -> tuple[int, str, str]:
        capsys.readouterr()
        code = main([*argv, "--workdir", str(workdir)])
        out = capsys.readouterr()
        return code, out.out, out.err

    return _run


def _json(run: Run, argv: Sequence[str]) -> tuple[int, dict[str, Any]]:
    code, out, err = run([*argv, "--json"])
    assert code == 0, err
    return code, json.loads(out)


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------


def test_refusals_report_text_and_json(run: Run) -> None:
    code, out, _ = run(["learn", "refusals"])
    assert code == 0
    assert "protocol rows: 2/15" in out and "unsure" in out and "--apply" in out
    _, d = _json(run, ["learn", "refusals"])
    assert d["schema"] == "crb.learn.refusals.v1"
    assert d["rows_protocol"] == 2 and len(d["groups"]) == 2
    assert all(g["verdict"] == "unsure" for g in d["groups"])
    shapes = {g["shape"] for g in d["groups"]}
    assert shapes == {'grep -n "<str>" <path> | head -<n>', "curl -sk <url>"}


def test_refusals_apply_round_trip(run: Run, tmp_path: Path) -> None:
    corpus = tmp_path / "fixtures"
    corpus.mkdir()
    (corpus / CORPUS_HONEST_FILE).write_text("# honest\npwd\n", encoding="utf-8")
    (corpus / CORPUS_REFUSED_FILE).write_text("# refused\n", encoding="utf-8")
    _, d = _json(run, ["learn", "refusals"])
    by_shape = {g["shape"]: g for g in d["groups"]}
    decisions = {
        "schema": "crb.learn.decisions.v1",
        "decided_by": "paul",
        "decisions": [
            {
                "group_id": by_shape['grep -n "<str>" <path> | head -<n>']["group_id"],
                "verdict": "honest",
                "note": "quoted parens",
            },
            {"group_id": by_shape["curl -sk <url>"]["group_id"], "verdict": "refuse"},
        ],
    }
    dec = tmp_path / "decisions.json"
    dec.write_text(json.dumps(decisions), encoding="utf-8")
    code, out, err = run(
        [
            "learn",
            "refusals",
            "--apply",
            str(dec),
            "--corpus-dir",
            str(corpus),
            "--date",
            "2026-09-14",
        ]
    )
    assert code == 0, err
    assert "honest  +1" in out and "refused +1" in out
    honest = (corpus / CORPUS_HONEST_FILE).read_text(encoding="utf-8")
    refused = (corpus / CORPUS_REFUSED_FILE).read_text(encoding="utf-8")
    assert "# learned 2026-09-14 from cobra/dddddddddd row " in honest
    assert (
        '(honest→paul) — quoted parens\ngrep -n "func (c \\*Command) Context" command.go | head -30\n'
        in honest
    )
    assert "curl -sk https://localhost:8701/health\tnetwork:\n" in refused
    # idempotent: a second apply writes nothing new
    _, d2 = _json(
        run,
        [
            "learn",
            "refusals",
            "--apply",
            str(dec),
            "--corpus-dir",
            str(corpus),
            "--date",
            "2026-09-14",
        ],
    )
    assert d2["applied"]["honest_added"] == [] and len(d2["applied"]["skipped"]) == 2
    assert honest == (corpus / CORPUS_HONEST_FILE).read_text(encoding="utf-8")


def test_refusals_apply_refuses_unnamed_or_unknown(run: Run, tmp_path: Path) -> None:
    dec = tmp_path / "bad.json"
    dec.write_text(json.dumps({"decisions": [{"group_id": "x", "verdict": "honest"}]}))
    code, _, err = run(["learn", "refusals", "--apply", str(dec), "--corpus-dir", str(tmp_path)])
    assert code == 2 and "decided_by" in err
    dec.write_text(
        json.dumps({"decided_by": "p", "decisions": [{"group_id": "nope", "verdict": "honest"}]})
    )
    code, _, err = run(["learn", "refusals", "--apply", str(dec), "--corpus-dir", str(tmp_path)])
    assert code == 2 and "no such group" in err
    assert not (tmp_path / CORPUS_HONEST_FILE).exists()


def test_refusals_out_file(run: Run, tmp_path: Path) -> None:
    out = tmp_path / "refusals.json"
    code, _, _ = run(["learn", "refusals", "--out", str(out)])
    assert code == 0 and json.loads(out.read_text())["rows_protocol"] == 2


# ---------------------------------------------------------------------------
# strengthen
# ---------------------------------------------------------------------------


def _oracle_report(tmp_path: Path) -> Path:
    report = {
        "schema": "crb.oracle_strength.v1",
        "tasks": [
            {
                "task_id": TASK_A,
                "repo": "click",
                "src_paths": ["src/click/termui.py"],
                "cell": "bug.fix/S",
                "total": 4,
                "killed": 2,
                "escaped": 2,
                "oracle_strength": 0.5,
                "escaped_mutants": [
                    {
                        "mutant_id": "m1",
                        "op": "flip",
                        "line": 10,
                        "path": "src/click/termui.py",
                        "description": "== → !=",
                    },
                    {
                        "mutant_id": "m2",
                        "op": "const",
                        "line": 22,
                        "path": "src/click/termui.py",
                        "description": "80 → 81",
                    },
                ],
            }
        ],
    }
    p = tmp_path / "oracle.json"
    p.write_text(json.dumps(report), encoding="utf-8")
    return p


def test_strengthen_text_json_and_out(run: Run, tmp_path: Path) -> None:
    oracle = _oracle_report(tmp_path)
    code, out, err = run(["learn", "strengthen", "--oracle", str(oracle), "--repo", "click"])
    assert code == 0, err
    assert (
        "cells flagged: 1" in out
        and "strengthen the target tests for click Fix pager on Windows" in out
    )
    backlog_path = tmp_path / "backlog.json"
    _, d = _json(
        run,
        [
            "learn",
            "strengthen",
            "--oracle",
            str(oracle),
            "--repo",
            "click",
            "--registered",
            "2026-09-14T00:00:00+00:00",
            "--out",
            str(backlog_path),
        ],
    )
    assert d["schema"] == "crb.learn.strengthen.v1" and d["cells_flagged"] == ["bug.fix|S"]
    (item,) = d["items"]
    assert item["capability_class"] == "test.add" and item["labels"]["slots"] == "structural"
    assert "src/click/termui.py:10 == → !=" in item["description"]
    # the --out file is a Backlog the factory can load and freeze
    bl = Backlog.from_dict(json.loads(backlog_path.read_text(encoding="utf-8")))
    assert bl.repo == "click" and not bl.frozen
    frozen = bl.freeze(at="2026-09-14T00:00:00+00:00")
    assert frozen.verify() and frozen.items[0].id == item["id"]


def test_strengthen_without_oracle_emits_cell_item(run: Run) -> None:
    _, d = _json(run, ["learn", "strengthen"])
    assert d["cells_without_scores"] == ["bug.fix|S"]
    assert d["items"][0]["title"] == "strengthen the target tests for cell bug.fix|S"


def test_strengthen_since_and_policy(run: Run, tmp_path: Path) -> None:
    _, d = _json(run, ["learn", "strengthen", "--since", "3.0"])
    assert d["items"] == [] and d["since"] == "3.0"
    # a policy with a lower oracle floor: nothing is oracle-held any more
    _, d2 = _json(run, ["learn", "strengthen", "--policy-json", '{"min_oracle_strength": 0.4}'])
    assert d2["cells_flagged"] == [] and d2["threshold"] == 0.4


def test_strengthen_reproducible_bytes(run: Run, tmp_path: Path) -> None:
    oracle = _oracle_report(tmp_path)
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    for out in (a, b):
        code, _, _ = run(
            [
                "learn",
                "strengthen",
                "--oracle",
                str(oracle),
                "--registered",
                "fixed",
                "--out",
                str(out),
            ]
        )
        assert code == 0
    assert a.read_bytes() == b.read_bytes()


# ---------------------------------------------------------------------------
# remeasure
# ---------------------------------------------------------------------------


def test_remeasure_text_json_and_out(run: Run, tmp_path: Path) -> None:
    code, out, err = run(["learn", "remeasure", "--apparatus", "2.1"])
    assert code == 0, err
    assert "apparatus 2.1" in out and "cells to renew: 1" in out and "nothing was sent" in out
    plan = tmp_path / "plan.json"
    _, d = _json(run, ["learn", "remeasure", "--apparatus", "2.1", "--out", str(plan)])
    assert d["schema"] == "crb.learn.remeasure.v1" and d["rows_stale"] == 3
    (cell,) = d["cells"]
    assert cell["label"] == "replay|bug.fix|M|python|claude_code|claude-sonnet-5|anthropic"
    assert cell["n_needed"] == 10 and cell["cost_known"]
    assert cell["est_cost_usd"] == pytest.approx(0.4 * 10)
    req = cell["requests"][0]
    assert req["repo"] == "click" and req["kind"] == "replay" and req["mode"] == "sighted"
    assert req["builder"] == "claude_code" and len(req["task_ids"]) == 3 and req["limit"] == 3
    assert cell["requests"][1]["limit"] == 7
    assert json.loads(plan.read_text(encoding="utf-8"))["cells"][0]["n_needed"] == 10


def test_remeasure_default_apparatus_is_the_instrument(run: Run) -> None:
    from crb.core.version import APPARATUS_VERSION

    _, d = _json(run, ["learn", "remeasure"])
    assert d["current_apparatus"] == APPARATUS_VERSION


def test_remeasure_policy_override(run: Run) -> None:
    _, d = _json(run, ["learn", "remeasure", "--apparatus", "2.1", "--policy-json", '{"min_n": 3}'])
    assert d["cells"][0]["n_needed"] == 3


# ---------------------------------------------------------------------------
# plumbing
# ---------------------------------------------------------------------------


def test_learn_without_subcommand_prints_help(run: Run) -> None:
    code, out, _ = run(["learn"])
    assert code == 2 and "refusals" in out and "strengthen" in out and "remeasure" in out


def test_explicit_path(run: Run, tmp_path: Path) -> None:
    other = tmp_path / "other.jsonl"
    JsonlLedger(other).append(_protocol(ERR_CURL, task_id="f" * 40))
    _, d = _json(run, ["learn", "refusals", "--path", str(other)])
    assert d["rows_total"] == 1 and d["rows_protocol"] == 1


def test_missing_ledger_is_empty_not_an_error(run: Run, tmp_path: Path) -> None:
    _, d = _json(run, ["learn", "remeasure", "--path", str(tmp_path / "none.jsonl")])
    assert d["rows_total"] == 0 and d["cells"] == []
