"""``crb learn {refusals,strengthen,remeasure}`` — round trips on a temp ledger.

Every command reads the ledger the way ``crb route`` does (``--path`` or
``<workdir>/ledger.jsonl``), prints a report (text or ``--json``), and never acts:
``refusals --apply`` is the ONE write, and it appends only what a named human
decided to the corpus files under ``--corpus-dir``.

Navigation
----------
What it is:   ``crb learn {refusals, strengthen, remeasure}``'s test suite — round trips on a
              temp ledger.
What it does: Pins that every command reads the ledger the way ``crb route`` does, prints text
              or ``--json`` and never acts — ``refusals --apply`` is the ONE write and appends
              only a named human's decisions; that ``strengthen`` accepts every server export
              shape (oracle scores, a controls report or a run body, a run's event-log page) and
              routes the cells as the server does; that ``remeasure`` defaults to the instrument's
              apparatus; that the score-action constants mirror the server's (the CLI cannot
              import it); reproducible bytes; and a missing ledger is empty, not an error.
How:          ``main([...])`` through a ``run`` fixture over a workdir holding a synthetic
              ``ledger.jsonl``.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0008-stdlib-core-and-downward-layers.md
Works with:   src/crb/cli/commands/learn.py (under test), src/crb/core/learn.py (the
              derivations), tests/test_learn.py (their own suite), tests/test_server_routes_learn.py
              (the same reports served), docs/LEARNING-LOOP.md (using it, §4)
Tested by:    tests/test_cli_learn.py
Touch when:   a server export shape changes (a loader case here — the CLI must read what the
              API writes); a learn subcommand is added.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from crb.cli.commands import CliError
from crb.cli.main import main
from crb.core.learn import CORPUS_HONEST_FILE, CORPUS_REFUSED_FILE
from crb.core.ledger import (
    FAILURE_PROTOCOL,
    LABEL_FAILURE_KIND,
    GradeRow,
    JsonlLedger,
    expected_belt_sets,
)
from crb.core.spec import TaskSpec
from crb.factory.backlog import Backlog
from fixtures.posture import posture_row

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
    # the belt set is what the stamped apparatus recorded (ledger invariant, review finding 4)
    base.setdefault("belt_set", expected_belt_sets(base["apparatus_version"], "measured")[0])
    return posture_row(**base)


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
    """A workdir holding the synthetic ``ledger.jsonl`` the three commands read (module-scoped)."""
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
    """``run(argv) -> (exit_code, stdout, stderr)`` with ``--workdir`` supplied."""

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
    _, d2 = _json(
        run,
        [
            "learn",
            "strengthen",
            "--policy-json",
            '{"min_oracle_strength": 0.4, "version": "routing.v1-weak"}',
        ],
    )
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
# strengthen: the server's exports as --oracle / --controls
# ---------------------------------------------------------------------------
#
# A ledger export is the rows alone; the per-task scores (oracle.score events) and
# the controls verdict (controls.report) live elsewhere in the store. The CLI takes
# them in the shapes the API exports them, and reads them the way the routes do.


def test_score_actions_mirror_the_server_routes() -> None:
    """The CLI cannot import the server package; the two constants must not drift. A hard
    import: the hermetic suite installs ``.[dev]`` which carries the server extra, so a
    missing ``fastapi`` is a broken environment, not a reason to skip the drift guard."""
    from crb.cli.commands.learn import ORACLE_SCORE_ACTIONS
    from crb.server.routes.oracle import SCORE_ACTIONS

    assert ORACLE_SCORE_ACTIONS == SCORE_ACTIONS


def _event(action: str, task_id: str, payload: dict[str, Any], **env: Any) -> dict[str, Any]:
    return {
        "event_id": "e1",
        "seq": 1,
        "stage": "oracle" if action.startswith("oracle") else "grade",
        "action": action,
        "task_id": task_id,
        "repo": "alpha",
        "trace_id": "run-1",
        "payload": payload,
        **env,
    }


def test_load_oracle_export_accepts_every_server_shape() -> None:
    from crb.cli.commands.learn import load_oracle_export

    score = {"capability_class": "bug.fix", "size": "S", "total": 8, "killed": 4, "strength": 0.5}
    # GET /oracle/{repo}: the top-level repo is carried onto every task's score
    got = load_oracle_export(
        {"repo": "alpha", "policy": {}, "tasks": [{"task_id": TASK_A, **score}]}
    )
    assert [(s.task_id, s.repo, s.strength, s.total, s.escaped_count) for s in got] == [
        (TASK_A, "alpha", 0.5, 8, 4)
    ]
    # a GET /runs/{id}/events/log page: only score actions are scores; the envelope's
    # task_id and repo sit beside the payload
    page = {
        "items": [
            _event("run.progress", "", {"done": 1}),
            _event("grade.belt", TASK_B, {"belt": "target_green", "value": True}),
            _event("oracle.score", TASK_A, {**score, "oracle_strength": 0.5}),
            _event("oracle.mutation.scored", TASK_B, {**score, "total": 0, "killed": 0}),
        ],
        "total": 4,
        "limit": 50,
        "offset": 0,
    }
    got = load_oracle_export(page)
    assert [(s.task_id, s.repo, s.strength) for s in got] == [
        (TASK_A, "alpha", 0.5),
        (TASK_B, "alpha", None),
    ]
    # the same events as JSON lines (a list), and a bare list of score dicts
    assert [s.task_id for s in load_oracle_export(page["items"])] == [TASK_A, TASK_B]
    assert [
        s.repo for s in load_oracle_export([{"task_id": TASK_A, "repo": "click", **score}])
    ] == ["click"]
    # a to_report() dict without a repo: scores keep their own (empty) repo
    assert load_oracle_export({"tasks": [{"task_id": TASK_A, **score}]})[0].repo == ""
    # a single score object
    assert load_oracle_export({"task_id": TASK_A, **score})[0].task_id == TASK_A
    # an EMPTY export is an honest empty list (no oracle run yet) …
    assert load_oracle_export({"repo": "alpha", "tasks": []}) == []
    assert load_oracle_export({"items": [], "total": 0, "limit": 50, "offset": 0}) == []
    assert load_oracle_export([]) == []
    # … but entries with no per-task score among them are the WRONG export: refused, never
    # a silent empty list (which would read every held cell as "without scores")
    for wrong in (
        [1, "x", None],
        {"n_rows": 14, "escapes": 1, "passed": True},  # the controls report
        {"items": [_event("grade.belt", TASK_A, {"belt": "target_green", "value": True})]},
    ):
        with pytest.raises(CliError, match="no per-task oracle score"):
            load_oracle_export(wrong)
    with pytest.raises(CliError, match="--oracle must be"):
        load_oracle_export("not a list")


def test_load_controls_export_reads_the_report_or_a_run_body() -> None:
    from crb.cli.commands.learn import load_controls_export

    report = {
        "schema": "crb.negative_controls.v1",
        "n_rows": 14,
        "escapes": 1,
        "not_constructible": 2,
        "skipped": 0,
        "passed": True,
        "run_id": "ctl-1",
        "reported_at": "2026-09-14T00:00:00+00:00",
        "verdict": {"state": "escaped"},
    }
    v = load_controls_export(report)
    assert v.measured and v.passed and v.escapes == 1 and v.total == 14 and v.constructible == 12
    assert v.run_id == "ctl-1" and v.created == "2026-09-14T00:00:00+00:00"
    run_body = {
        "id": "ctl-2",
        "kind": "controls",
        "finished": "2026-09-14T01:00:00+00:00",
        "counts": {"rows": 10, "escapes": 0, "not_constructible": 0, "skipped": 0, "passed": True},
    }
    v2 = load_controls_export(run_body)
    assert v2.measured and v2.escapes == 0 and v2.total == 10 and v2.run_id == "ctl-2"
    for bad in ({"escapes": 1}, {"counts": {"rows": 3}}, [], "x"):
        with pytest.raises(CliError, match="--controls must be"):
            load_controls_export(bad)


def test_strengthen_controls_flag_routes_the_cells_as_the_server_does(
    run: Run, tmp_path: Path
) -> None:
    """The fixture's stale M cell (n=3) is below min_n and the S cell is oracle-weak;
    a controls verdict with an escape holds EVERY measured cell — the S cell keeps
    its oracle_weak reason (it fires first), and the report is echoed back."""
    controls = tmp_path / "controls.json"
    controls.write_text(
        json.dumps({"n_rows": 14, "escapes": 1, "not_constructible": 0, "passed": True}),
        encoding="utf-8",
    )
    _, d = _json(run, ["learn", "strengthen", "--controls", str(controls)])
    assert d["controls"]["measured"] is True and d["controls"]["escapes"] == 1
    assert d["cells_flagged"] == ["bug.fix|S"]
    assert d["items"][0]["labels"]["reason_code"] == "oracle_weak"
    # without the flag the report is honestly absent from the output
    _, d2 = _json(run, ["learn", "strengthen"])
    assert d2["controls"] is None
    # a file that is not a controls report is refused, never read as "no controls"
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    code, _, err = run(["learn", "strengthen", "--controls", str(bad)])
    assert code == 2 and "--controls must be" in err  # a usage error, never the verdict's 1


def test_strengthen_oracle_accepts_a_run_events_log_page(run: Run, tmp_path: Path) -> None:
    """The oracle run's event log as `GET /runs/{id}/events/log` returns it: the
    grade/progress events are ignored, the score's escaped mutants reach the item."""
    page = {
        "items": [
            _event("run.progress", "", {"done": 1}),
            _event(
                "oracle.score",
                TASK_A,
                {
                    "repo": "click",
                    "src_paths": ["src/click/termui.py"],
                    "total": 4,
                    "killed": 2,
                    "oracle_strength": 0.5,
                    "escaped_mutants": [
                        {"mutant_id": "m1", "op": "flip", "line": 10, "path": "src/click/termui.py"}
                    ],
                },
                repo="click",
            ),
        ],
        "total": 2,
        "limit": 50,
        "offset": 0,
    }
    p = tmp_path / "events.json"
    p.write_text(json.dumps(page), encoding="utf-8")
    _, d = _json(run, ["learn", "strengthen", "--oracle", str(p), "--repo", "click"])
    assert d["cells_flagged"] == ["bug.fix|S"] and d["cells_without_scores"] == []
    (item,) = d["items"]
    assert item["labels"]["task_id"] == TASK_A and item["labels"]["repo"] == "click"
    assert "src/click/termui.py:10" in item["description"]


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
    assert (
        cell["n_needed"] == 16 and cell["cost_known"]
    )  # the Wilson minimum at rate 1.0, not min_n
    assert cell["est_cost_usd"] == pytest.approx(0.4 * 16)
    req = cell["requests"][0]
    assert req["repo"] == "click" and req["kind"] == "replay" and req["mode"] == "sighted"
    assert req["builder"] == "claude_code" and len(req["task_ids"]) == 3 and req["limit"] == 3
    assert cell["requests"][1]["limit"] == 13  # 16 needed − 3 named stale tasks
    assert json.loads(plan.read_text(encoding="utf-8"))["cells"][0]["n_needed"] == 16


def test_remeasure_default_apparatus_is_the_instrument(run: Run) -> None:
    from crb.core.version import APPARATUS_VERSION

    _, d = _json(run, ["learn", "remeasure"])
    assert d["current_apparatus"] == APPARATUS_VERSION


def test_remeasure_policy_override(run: Run) -> None:
    # min_n alone no longer sets the target: an unmeasured cell plans for the rows that
    # clear the Wilson bar at rate 1.0 (16 at ci_low 0.80). Relax that bar too and the
    # override shows through.
    _, d = _json(
        run,
        [
            "learn",
            "remeasure",
            "--apparatus",
            "2.1",
            "--policy-json",
            '{"min_n": 3, "min_ci_low": 0.0, "version": "routing.v1-small"}',
        ],
    )
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
