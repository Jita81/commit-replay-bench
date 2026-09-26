"""The ``crb`` CLI, driven in-process via ``main([...])`` against a tiny real git repo.

Covers every subcommand's happy path and the three exit codes:
``0`` ok / ``1`` verdict negative / ``2`` usage-or-harness error.

Navigation
----------
What it is:   The ``crb`` CLI's test suite — every subcommand's happy path and the three exit
              codes, driven in-process against a tiny real git repository.
What it does: Pins ``0`` ok / ``1`` verdict negative / ``2`` usage-or-harness error across
              ``config``, ``repo add | probe | import``, ``mine`` (idempotent, streams events,
              no gold), ``prep`` (blind hides the oracle), ``grade`` (unedited not clean, gold
              clean and ledgered, tampered oracle disqualified, blind overlay at grade time, a
              wrong worktree a harness error), ``ledger verify | stats | export | import`` (tamper
              detected), ``route``; that a forged false-Q1 row cannot even be read, that broken
              state files are harness errors, that an unexpected exception maps to exit 2 unless
              ``--debug``, and that the CLI never leaks the operator's environment into a test
              run.
How:          ``main([...])`` with ``--workdir`` supplied by the ``run`` fixture over
              ``fixtures.cli_repo``; session-scoped ``registered`` / ``mined`` states.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0008-stdlib-core-and-downward-layers.md
Works with:   src/crb/cli/main.py (under test), src/crb/cli/commands/repo.py,
              src/crb/cli/commands/mine.py, src/crb/cli/commands/grade.py and
              src/crb/cli/commands/ledger.py (the subcommands), tests/fixtures/cli_repo.py (the
              history), docs/OPERATOR.md (the operator's view of the same commands)
Tested by:    tests/test_cli.py
Touch when:   a subcommand or flag is added (a happy-path case and the exit code of its
              negative verdict; update docs/OPERATOR.md); never so that a verdict-negative exit
              becomes 0.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

# The fixture package layout (tests/fixtures/*, tests/__init__.py) is owned by other
# workstreams; put both directories on sys.path so these imports work either way.
_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE / "fixtures"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from cli_repo import CliRepo, apply_gold, make_repo  # noqa: E402

from crb.cli.main import main  # noqa: E402
from crb.core.ledger import JsonlLedger, false_q1_total  # noqa: E402
from crb.core.routing import ROUTES  # noqa: E402
from test_legacy import BENCH_ROWS, write_census  # noqa: E402

Run = Callable[[Sequence[str]], tuple[int, str, str]]


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> CliRepo:
    """The four-commit CLI fixture repository, built once for the module."""
    return make_repo(tmp_path_factory.mktemp("demo-repo"))


@pytest.fixture(scope="module")
def workdir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The ``--workdir`` every command runs against (module-scoped: later fixtures build on it)."""
    return tmp_path_factory.mktemp("crb-home") / ".crb"


@pytest.fixture
def run(workdir: Path, capsys: pytest.CaptureFixture[str]) -> Run:
    """``run(argv) -> (exit_code, stdout, stderr)`` with ``--workdir`` supplied."""

    def _run(argv: Sequence[str]) -> tuple[int, str, str]:
        capsys.readouterr()  # drop anything captured before this call
        full = list(argv) if "--workdir" in argv else [*argv, "--workdir", str(workdir)]
        code = main(full)
        out = capsys.readouterr()
        return code, out.out, out.err

    return _run


def run_json(run: Run, argv: Sequence[str]) -> tuple[int, dict[str, object]]:
    """``run(argv + ["--json"])`` with the stdout parsed — ``(exit_code, body)``."""
    code, out, _ = run([*argv, "--json"])
    return code, json.loads(out)


@pytest.fixture(scope="module")
def registered(demo: CliRepo, workdir: Path) -> CliRepo:
    """The demo repository registered as ``demo`` (``crb repo add``), once for the module."""
    code = main(
        [
            "repo",
            "add",
            "demo",
            "--path",
            str(demo.path),
            "--language",
            "py",
            "--src-prefix",
            "pkg/",
            "--test-prefix",
            "tests/",
            "--belt-scope",
            "tests/",
            "--probe",
            "tests/test_calc.py",
            "--runner-opt",
            f"python={sys.executable}",
            "--workdir",
            str(workdir),
        ]
    )
    assert code == 0
    return demo


@pytest.fixture(scope="module")
def mined(registered: CliRepo, workdir: Path) -> CliRepo:
    """``registered`` after ``crb mine demo --target 2`` — two tasks on file for the grade cases."""
    code = main(["mine", "demo", "--target", "2", "--workdir", str(workdir)])
    assert code == 0
    return registered


# ---------------------------------------------------------------------------
# usage + config
# ---------------------------------------------------------------------------


def test_no_command_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "usage: crb" in capsys.readouterr().out


def test_help_and_version_exit_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--help"]) == 0
    assert "exit codes" in capsys.readouterr().out
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.startswith("crb ")


def test_unknown_command_and_bare_groups_exit_two(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["frobnicate"]) == 2
    assert main(["repo"]) == 2
    assert main(["ledger"]) == 2
    assert main(["config"]) == 2
    capsys.readouterr()


def test_config_show(run: Run, workdir: Path) -> None:
    code, out, _ = run(["config", "show"])
    assert code == 0
    assert str(workdir) in out and "executor default   local" in out
    code, d = run_json(run, ["config", "show"])
    assert code == 0
    assert d["workdir"] == str(workdir.resolve())
    assert d["ledger"] == str(workdir.resolve() / "ledger.jsonl")
    assert d["workdir_source"] == "--workdir"
    assert d["executor"]["default"] == "local" and d["executor"]["docker"]["network"] == "none"
    assert d["apparatus_version"] and d["crb_version"]
    assert d["routing_policy"]["version"] == "routing.v1"


def test_workdir_resolution_env_and_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CRB_HOME", raising=False)
    assert main(["config", "show", "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["workdir"] == str((tmp_path / ".crb").resolve())
    assert d["workdir_source"].startswith("default")
    monkeypatch.setenv("CRB_HOME", str(tmp_path / "elsewhere"))
    assert main(["config", "show", "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["workdir"] == str((tmp_path / "elsewhere").resolve())
    assert d["workdir_source"] == "$CRB_HOME"


# ---------------------------------------------------------------------------
# repo
# ---------------------------------------------------------------------------


def test_repo_add_writes_config(registered: CliRepo, workdir: Path, run: Run) -> None:
    f = workdir / "repos" / "demo.json"
    assert f.is_file()
    d = json.loads(f.read_text())
    assert d["language"] == "python" and d["runner"] == "pytest"
    assert d["path"] == str(registered.path.resolve())
    assert d["belt_scope"] == ["tests/"] and d["probe"] == "tests/test_calc.py"
    assert d["runner_opts"] == {"python": sys.executable}
    code, out, _ = run(["repo", "list"])
    assert code == 0 and "demo" in out and "pytest" in out
    code, dl = run_json(run, ["repo", "list"])
    assert code == 0 and "demo" in [r["repo"] for r in dl["repos"]]  # type: ignore[index]


def test_repo_add_refuses_duplicate_unless_forced(registered: CliRepo, run: Run) -> None:
    base = ["repo", "add", "demo", "--path", str(registered.path), "--language", "python"]
    code, _, err = run(base)
    assert code == 2 and "already exists" in err
    code, d = run_json(
        run,
        [
            *base,
            "--force",
            "--src-prefix",
            "pkg/",
            "--test-prefix",
            "tests/",
            "--belt-scope",
            "tests/",
            "--probe",
            "tests/test_calc.py",
            "--runner-opt",
            f"python={sys.executable}",
        ],
    )
    assert code == 0 and d["repo"] == "demo"


def test_repo_add_usage_errors(tmp_path: Path, run: Run) -> None:
    not_git = tmp_path / "plain"
    not_git.mkdir()
    code, _, err = run(["repo", "add", "x", "--path", str(not_git), "--language", "py"])
    assert code == 2 and "not a git repository" in err
    code, _, err = run(["repo", "add", "x", "--path", str(tmp_path / "nope"), "--language", "py"])
    assert code == 2 and "not a directory" in err
    real = make_repo(tmp_path / "real").path
    code, _, err = run(["repo", "add", "x", "--path", str(real), "--language", "cobol"])
    assert code == 2 and "unknown language" in err
    code, _, err = run(["repo", "add", "Bad Name", "--path", str(real), "--language", "py"])
    assert code == 2 and "lowercase" in err
    code, _, err = run(
        ["repo", "add", "x", "--path", str(real), "--language", "py", "--runner-opt", "novalue"]
    )
    assert code == 2 and "KEY=VALUE" in err
    code, _, err = run(
        ["repo", "add", "x", "--path", str(real), "--language", "py", "--runner", "nope"]
    )
    assert code == 2


def test_repo_probe_green(registered: CliRepo, run: Run) -> None:
    code, d = run_json(run, ["repo", "probe", "demo"])
    assert code == 0
    assert d["green"] is True and d["returncode"] == 0 and d["runner"] == "pytest"
    assert d["executor"] == {"executor": "local"}
    code, out, _ = run(["repo", "probe", "demo"])
    assert code == 0 and "GREEN" in out


def test_repo_probe_reads_the_deployments_provider_and_names_its_refusal(
    registered: CliRepo, run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0019: the probe binds HEAD's dependency set from the deployment's provider, and
    a provisioning stop is one line with its fix (exit 2), never a traceback."""
    from crb.cli.commands import repo as repo_cmd
    from crb.core.deps import ProvisionRefused

    class _Off:
        def resolve(self, *a: object, **k: object) -> object:
            raise ProvisionRefused("PROVISION_DISABLED", "demo declares python dependencies")

    seen: list[str] = []
    monkeypatch.setattr(repo_cmd, "deps_provider", lambda ex: seen.append(ex.name) or _Off())
    code, _, err = run(["repo", "probe", "demo"])
    assert seen == ["local"] and code == 2
    assert "PROVISION_DISABLED: demo declares python dependencies" in err
    assert "CRB_PROVISION__ENABLED=true" in err and "Traceback" not in err


def test_repo_probe_without_probe_scope_is_usage_error(
    registered: CliRepo, run: Run, workdir: Path
) -> None:
    code, _d = run_json(
        run,
        [
            "repo",
            "add",
            "noprobe",
            "--path",
            str(registered.path),
            "--language",
            "py",
            "--runner-opt",
            f"python={sys.executable}",
        ],
    )
    assert code == 0
    code, _, err = run(["repo", "probe", "noprobe"])
    assert code == 2 and "no probe scope" in err
    (workdir / "repos" / "noprobe.json").unlink()


def test_repo_probe_unknown_repo(run: Run) -> None:
    code, _, err = run(["repo", "probe", "ghost"])
    assert code == 2 and "unknown repo" in err


def test_repo_docker_executor_fails_closed_without_image(registered: CliRepo, run: Run) -> None:
    code, _, err = run(["repo", "probe", "demo", "--executor", "docker"])
    assert code == 2 and "sandbox unavailable" in err


def test_repo_import_configs(tmp_path: Path, run: Run, workdir: Path) -> None:
    cfg = tmp_path / "configs.json"
    cfg.write_text(
        json.dumps(
            {
                "imp-a": {"lang": "go", "belt_scope": ["./..."]},
                "imp-b": {
                    "lang": "js",
                    "js_tool": "vitest",
                    "src_prefix": "lib/",
                    "test_prefix": "tests/",
                },
            }
        )
    )
    repos_dir = tmp_path / "repos"
    make_repo(repos_dir / "imp-a")
    code, d = run_json(run, ["repo", "import-configs", str(cfg), "--repos-dir", str(repos_dir)])
    assert code == 0
    imported = d["imported"]
    assert [r["repo"] for r in imported] == ["imp-a", "imp-b"]  # type: ignore[index]
    assert imported[0]["path"] == str((repos_dir / "imp-a").resolve())  # type: ignore[index]
    assert imported[1]["path"] == ""  # type: ignore[index]  # no clone present → config-only
    assert json.loads((workdir / "repos" / "imp-b.json").read_text())["runner"] == "vitest"
    code, d = run_json(run, ["repo", "import-configs", str(cfg)])
    assert code == 0 and d["imported"] == [] and d["skipped_existing"] == ["imp-a", "imp-b"]
    code, _, err = run(["mine", "imp-b"])
    assert code == 2 and "no clone path" in err
    code, _, err = run(["repo", "import-configs", str(tmp_path / "missing.json")])
    assert code == 2
    for name in ("imp-a", "imp-b"):
        (workdir / "repos" / f"{name}.json").unlink()


# ---------------------------------------------------------------------------
# mine
# ---------------------------------------------------------------------------


def test_mine_finds_replayable_commits(mined: CliRepo, workdir: Path) -> None:
    f = workdir / "tasks" / "demo.jsonl"
    tasks = [json.loads(ln) for ln in f.read_text().splitlines() if ln.strip()]
    assert {t["task_id"] for t in tasks} == {mined.add_task, mined.sub_task}
    for t in tasks:
        assert t["red_checked"] is True and t["gold_clean"] is True
        assert t["language"] == "python" and t["belt_scope"] == ["tests/"]
        assert t["capability_class"] == "bug.fix" and t["size"] == "XS"
    by_id = {t["task_id"]: t for t in tasks}
    assert by_id[mined.sub_task]["test_files"] == ["tests/test_sub.py"]
    assert by_id[mined.sub_task]["baseline_failing"]  # target RED at parent is in the baseline


def test_mine_is_idempotent_and_streams_events(mined: CliRepo, run: Run) -> None:
    code, out, err = run(["mine", "demo", "--events", "--json"])
    assert code == 0
    d = json.loads(out)
    assert d["found"] == 0 and d["examined"] == 0 and d["known_before"] == 2
    events = [json.loads(ln) for ln in err.splitlines() if ln.strip()]
    assert events and events[-1]["event"] == "mine.done"
    assert events[-1]["found"] == 0


def test_mine_text_output_and_no_gold(tmp_path: Path, run: Run, workdir: Path) -> None:
    other = make_repo(tmp_path / "other")
    code, _, _ = run(
        [
            "repo",
            "add",
            "other",
            "--path",
            str(other.path),
            "--language",
            "python",
            "--src-prefix",
            "pkg/",
            "--test-prefix",
            "tests/",
            "--runner-opt",
            f"python={sys.executable}",
        ]
    )
    assert code == 0
    code, out, _ = run(["mine", "other", "--target", "1", "--no-gold"])
    assert code == 0
    assert "found 1" in out and f"+ {other.sub_task[:10]}" in out
    tasks = [json.loads(ln) for ln in (workdir / "tasks" / "other.jsonl").read_text().splitlines()]
    assert len(tasks) == 1 and tasks[0]["gold_clean"] is None  # unjudged, never assumed


def test_mine_unknown_repo(run: Run) -> None:
    code, _, err = run(["mine", "ghost"])
    assert code == 2 and "unknown repo" in err


# ---------------------------------------------------------------------------
# prep + grade
# ---------------------------------------------------------------------------


def test_prep_creates_worktree_at_parent(mined: CliRepo, run: Run, tmp_path: Path) -> None:
    dest = tmp_path / "wt-prep"
    code, d = run_json(run, ["prep", "demo", mined.sub_task[:10], "--dest", str(dest)])
    assert code == 0
    assert d["parent"] == mined.add_task and d["worktree"] == str(dest.resolve())
    assert d["tests_overlaid"] == ["tests/test_sub.py"]
    assert (dest / "tests" / "test_sub.py").is_file()  # sighted: oracle visible
    assert "sub" not in (dest / "pkg" / "calc.py").read_text()  # source is the parent's
    code, _, err = run(["prep", "demo", mined.sub_task, "--dest", str(dest)])
    assert code == 2 and "already exists" in err
    code, out, _ = run(["prep", "demo", mined.sub_task, "--dest", str(dest), "--force"])
    assert code == 0 and "prepared" in out


def test_prep_blind_hides_the_oracle(mined: CliRepo, run: Run, tmp_path: Path) -> None:
    dest = tmp_path / "wt-blind"
    code, d = run_json(
        run, ["prep", "demo", mined.sub_task, "--dest", str(dest), "--mode", "blind"]
    )
    assert code == 0 and d["tests_overlaid"] == []
    assert not (dest / "tests" / "test_sub.py").exists()


def test_prep_task_resolution_errors(mined: CliRepo, run: Run, tmp_path: Path) -> None:
    code, _, err = run(["prep", "demo", "abc", "--dest", str(tmp_path / "x")])
    assert code == 2 and "at least 7" in err
    code, _, err = run(["prep", "demo", "0" * 40, "--dest", str(tmp_path / "x")])
    assert code == 2 and "no task" in err


def test_grade_unedited_worktree_is_not_clean(mined: CliRepo, run: Run, tmp_path: Path) -> None:
    dest = tmp_path / "wt-red"
    assert run(["prep", "demo", mined.sub_task, "--dest", str(dest)])[0] == 0
    code, d = run_json(run, ["grade", "demo", mined.sub_task, "--worktree", str(dest)])
    assert code == 1
    assert d["clean"] is False and d["target_green"] is False and d["tests_unmodified"] is True
    assert d["error"] == "" and d["disqualified"] is False
    assert "evidence_pack_hash" not in d  # no --ledger → nothing persisted
    code, out, _ = run(["grade", "demo", mined.sub_task, "--worktree", str(dest)])
    assert code == 1 and "NOT CLEAN" in out


def test_grade_gold_edit_is_clean_and_ledgered(
    mined: CliRepo, run: Run, tmp_path: Path, workdir: Path
) -> None:
    dest = tmp_path / "wt-clean"
    assert run(["prep", "demo", mined.sub_task, "--dest", str(dest)])[0] == 0
    apply_gold(dest, mined.sub_task, mined)
    code, d = run_json(
        run,
        [
            "grade",
            "demo",
            mined.sub_task,
            "--worktree",
            str(dest),
            "--ledger",
            "--builder",
            "human-gold",
            "--model",
            "gold",
            "--provider",
            "git",
            "--run-id",
            "t1",
            "--trial",
            "r1",
            "--actor",
            "pytest",
            "--events",
        ],
    )
    assert code == 0
    assert d["clean"] is True
    assert all(
        d[b] is True
        for b in ("tests_unmodified", "target_green", "no_new_failures", "source_changed")
    )
    assert d["changed_files"] == ["pkg/calc.py"] and d["diff"]["files"] == ["pkg/calc.py"]
    pack_path = Path(d["evidence_pack"])  # type: ignore[arg-type]
    assert pack_path.is_file() and pack_path.parent == workdir.resolve() / "evidence"
    pack = json.loads(pack_path.read_text())
    assert pack["pack_hash"] == d["evidence_pack_hash"]
    assert pack["builder"]["name"] == "human-gold" and pack["apparatus"]["runner"] == "pytest"
    assert pack["apparatus"]["executor"] == {"executor": "local"}
    ledger = JsonlLedger(workdir / "ledger.jsonl")
    rows = list(ledger.rows())
    assert ledger.verify() == len(rows) >= 1
    row = rows[-1]
    assert row.row_hash == d["row_hash"] and row.clean is True
    assert row.evidence_pack_hash == d["evidence_pack_hash"]
    assert row.builder == "human-gold" and row.model == "gold" and row.provider == "git"
    assert row.run_id == "t1" and row.trial == "r1" and row.actor == "pytest"
    assert row.belt_set == "v5" and row.provenance == "measured" and row.gold_clean is True
    assert false_q1_total(rows) == 0


def test_grade_text_output_mentions_ledger(mined: CliRepo, run: Run, tmp_path: Path) -> None:
    dest = tmp_path / "wt-text"
    assert run(["prep", "demo", mined.add_task, "--dest", str(dest)])[0] == 0
    apply_gold(dest, mined.add_task, mined)
    ledger = tmp_path / "side-ledger.jsonl"
    code, out, err = run(
        [
            "grade",
            "demo",
            mined.add_task,
            "--worktree",
            str(dest),
            "--ledger",
            str(ledger),
            "--events",
        ]
    )
    assert code == 0
    assert "CLEAN" in out and "ledgered" in out and str(ledger) in out
    assert JsonlLedger(ledger).verify() == 1
    events = [json.loads(ln) for ln in err.splitlines() if ln.strip()]
    assert {e["event"] for e in events} == {"grade.belt"}


def test_grade_tampered_oracle_is_disqualified(mined: CliRepo, run: Run, tmp_path: Path) -> None:
    dest = tmp_path / "wt-tamper"
    assert run(["prep", "demo", mined.sub_task, "--dest", str(dest)])[0] == 0
    apply_gold(dest, mined.sub_task, mined)
    (dest / "tests" / "test_sub.py").write_text("def test_sub():\n    assert True\n")
    code, d = run_json(run, ["grade", "demo", mined.sub_task, "--worktree", str(dest), "--ledger"])
    assert code == 1
    assert d["disqualified"] is True and d["clean"] is False and d["tests_unmodified"] is False
    assert d["tamper_files"] == ["tests/test_sub.py"]
    code, out, _ = run(["grade", "demo", mined.sub_task, "--worktree", str(dest)])
    assert code == 1 and "DISQUALIFIED" in out


def test_grade_blind_mode_overlays_oracle_at_grade_time(
    mined: CliRepo, run: Run, tmp_path: Path
) -> None:
    dest = tmp_path / "wt-blind-grade"
    assert run(["prep", "demo", mined.sub_task, "--dest", str(dest), "--mode", "blind"])[0] == 0
    apply_gold(dest, mined.sub_task, mined)
    code, d = run_json(
        run, ["grade", "demo", mined.sub_task, "--worktree", str(dest), "--mode", "blind"]
    )
    assert code == 0 and d["clean"] is True and d["mode"] == "blind"
    assert (dest / "tests" / "test_sub.py").is_file()


def test_grade_blind_builder_touching_tests_is_disqualified(
    mined: CliRepo, run: Run, tmp_path: Path
) -> None:
    dest = tmp_path / "wt-blind-tamper"
    assert run(["prep", "demo", mined.sub_task, "--dest", str(dest), "--mode", "blind"])[0] == 0
    apply_gold(dest, mined.sub_task, mined)
    (dest / "tests" / "test_sub.py").write_text("def test_sub():\n    assert True\n")
    code, d = run_json(
        run, ["grade", "demo", mined.sub_task, "--worktree", str(dest), "--mode", "blind"]
    )
    assert code == 1 and d["disqualified"] is True and "pre-overlay" in str(d["dq_reason"])


def test_grade_wrong_worktree_is_a_harness_error(mined: CliRepo, run: Run, tmp_path: Path) -> None:
    code, _, err = run(["grade", "demo", mined.sub_task, "--worktree", str(tmp_path / "nowhere")])
    assert code == 2 and "not a directory" in err
    plain = tmp_path / "plain"
    plain.mkdir()
    code, _, err = run(["grade", "demo", mined.sub_task, "--worktree", str(plain)])
    assert code == 2 and "not a git worktree" in err
    # the clone itself sits at HEAD (c3), not at the task's parent
    code, _, err = run(["grade", "demo", mined.sub_task, "--worktree", str(mined.path)])
    assert code == 2 and "not the task's parent" in err


# ---------------------------------------------------------------------------
# ledger
# ---------------------------------------------------------------------------


def test_ledger_verify_stats_export(
    mined: CliRepo, run: Run, workdir: Path, tmp_path: Path
) -> None:
    # the module ledger holds the rows written by the grade tests above
    code, d = run_json(run, ["ledger", "verify"])
    assert code == 0 and d["ok"] is True and d["chain_ok"] is True and d["false_q1"] == 0
    assert d["rows"] >= 1 and d["clean_without_pack"] == 0  # type: ignore[operator]
    code, out, _ = run(["ledger", "verify"])
    assert code == 0 and "chain OK" in out

    code, d = run_json(run, ["ledger", "stats"])
    assert code == 0 and d["by"] == ["capability_class", "size"]
    cells = d["cells"]
    assert cells and all(c["false_q1"] == 0 for c in cells)  # type: ignore[index,union-attr]
    assert d["method"]["ci"].startswith("Wilson")  # type: ignore[index]
    code, out, _ = run(["ledger", "stats", "--by", "class,size,model,belt_set"])
    assert code == 0 and "ci_low" in out and "Wilson" in out and "human-gold" not in out
    code, out, _ = run(["ledger", "stats", "--by", "model"])
    assert code == 0 and "gold" in out
    code, _, err = run(["ledger", "stats", "--by", "colour"])
    assert code == 2 and "unknown --by" in err

    code, out, _ = run(["ledger", "export"])
    assert code == 0
    lines = [json.loads(ln) for ln in out.splitlines() if ln.strip()]
    assert len(lines) == d["rows"]
    assert all(ln["schema"] == "crb.grade.v2" and ln["row_hash"] for ln in lines)
    out_file = tmp_path / "export.jsonl"
    code, d2 = run_json(run, ["ledger", "export", "--out", str(out_file)])
    assert code == 0 and d2["out"] == str(out_file)
    assert len(out_file.read_text().splitlines()) == len(lines)
    # --abstract: the allowlisted cell-level export (ADR-0007) — no ids, no code, no repo
    code, out, _ = run(["ledger", "export", "--abstract"])
    assert code == 0
    cells = [json.loads(ln) for ln in out.splitlines() if ln.strip()]
    assert cells and all("task_id" not in c and "row_hash" not in c for c in cells)
    assert all("n" in c and "capability_class" in c for c in cells)


def test_ledger_verify_detects_tampering(run: Run, tmp_path: Path, workdir: Path) -> None:
    src = workdir / "ledger.jsonl"
    copy = tmp_path / "tampered.jsonl"
    lines = src.read_text().splitlines()
    row = json.loads(lines[-1])
    row["actor"] = "mallory"  # a neutral field: the row still loads, the hash no longer matches
    lines[-1] = json.dumps(row, sort_keys=True)
    copy.write_text("\n".join(lines) + "\n")
    code, d = run_json(run, ["ledger", "verify", "--path", str(copy)])
    assert code == 1 and d["ok"] is False and d["chain_ok"] is False
    assert "row_hash mismatch" in str(d["error"])
    code, out, _ = run(["ledger", "verify", "--path", str(copy)])
    assert code == 1 and "BROKEN" in out
    # removing a row breaks the chain too (prev_hash of the next row no longer matches);
    # the precondition is asserted so the check runs even under ``-k`` (it used to be
    # guarded by ``if len(lines) > 1`` and could pass without checking anything)
    assert len(lines) > 1, "the ledger under test must hold more than one row"
    copy.write_text("\n".join(lines[1:]) + "\n")
    code, d = run_json(run, ["ledger", "verify", "--path", str(copy)])
    assert code == 1 and "prev_hash mismatch" in str(d["error"])


def test_ledger_empty_paths(run: Run, tmp_path: Path) -> None:
    empty = tmp_path / "empty.jsonl"
    code, d = run_json(run, ["ledger", "verify", "--path", str(empty)])
    assert code == 0 and d["rows"] == 0
    code, d = run_json(run, ["ledger", "stats", "--path", str(empty)])
    assert code == 0 and d["cells"] == []
    code, d = run_json(run, ["route", "--path", str(empty)])
    assert code == 0 and d["decisions"] == []


def test_ledger_import_census_synthetic(run: Run, tmp_path: Path) -> None:
    grades, state, configs = write_census(tmp_path / "census")
    home = tmp_path / "census-home"
    argv = [
        "ledger",
        "import-census",
        "--grades",
        str(grades),
        "--tasks-dir",
        str(state),
        "--configs",
        str(configs),
    ]
    code, out, err = run([*argv, "--workdir", str(home), "--events"])
    assert code == 0, err
    assert "imported 5" in out and "false-Q1 0" in out
    assert any(json.loads(ln)["event"] == "legacy.grade" for ln in err.splitlines() if ln.strip())
    assert (home / "repos" / "demo.json").is_file() and (home / "repos" / "gopkg.json").is_file()
    assert len((home / "tasks" / "demo.jsonl").read_text().splitlines()) == 2
    assert len(list((home / "evidence").glob("*.json"))) == 5
    ledger = JsonlLedger(home / "ledger.jsonl")
    assert ledger.verify() == 5
    assert {r.belt_set for r in ledger.rows()} == {"v3-legacy", "v4"}
    # idempotent
    code, d = run_json(run, [*argv, "--workdir", str(home)])
    assert code == 0
    assert d["grades_imported"] == 0 and d["grades_already_present"] == 5
    assert d["tasks_imported"] == 0 and d["configs_imported"] == 0
    assert d["chain_verified_rows"] == 5 and d["false_q1"] == 0
    # a config-only census repo cannot be mined or graded until a clone path is given
    code, _, err = run(["mine", "demo", "--workdir", str(home)])
    assert code == 2 and "no clone path" in err
    # --no-packs on a fresh workdir writes rows but no packs
    home2 = tmp_path / "census-home-2"
    code, d = run_json(run, [*argv, "--workdir", str(home2), "--no-packs"])
    assert code == 0 and d["packs_written"] == 0 and d["grades_imported"] == 5
    assert not (home2 / "evidence").exists()
    # bad paths are usage errors
    code, _, err = run([*argv[:-1], str(tmp_path / "missing.json"), "--workdir", str(home)])
    assert code == 2 and "--configs" in err
    code, _, err = run(
        ["ledger", "import-census", "--grades", str(tmp_path / "nope"), "--workdir", str(home)]
    )
    assert code == 2 and "--grades" in err


def test_ledger_import_aggregates(run: Run, tmp_path: Path) -> None:
    src = tmp_path / "benchmark_ledger.jsonl"
    src.write_text("".join(json.dumps(r) + "\n" for r in BENCH_ROWS))
    home = tmp_path / "agg-home"
    code, d = run_json(run, ["ledger", "import-aggregates", str(src), "--workdir", str(home)])
    assert code == 0 and d["written"] == 2 and d["untrusted"] == 1
    rows = [json.loads(ln) for ln in (home / "aggregates.jsonl").read_text().splitlines()]
    assert [r["schema"] for r in rows] == ["crb.aggregate.imported.v1"] * 2
    code, out, _ = run(["ledger", "import-aggregates", str(src), "--workdir", str(home)])
    assert code == 0 and "imported 0" in out and "reference-only" in out
    assert not (home / "ledger.jsonl").exists()  # aggregates never touch the grade ledger
    assert (
        run(["ledger", "import-aggregates", str(tmp_path / "nope"), "--workdir", str(home)])[0] == 2
    )


# ---------------------------------------------------------------------------
# route
# ---------------------------------------------------------------------------


def test_route_decisions(mined: CliRepo, run: Run, tmp_path: Path) -> None:
    code, d = run_json(run, ["route"])
    assert code == 0
    decisions = d["decisions"]
    assert decisions and all(x["route"] in ROUTES for x in decisions)  # type: ignore[index,union-attr]
    assert all(x["policy_version"] == "routing.v1" for x in decisions)  # type: ignore[index,union-attr]
    assert d["policy"]["min_n"] == 10  # type: ignore[index]
    code, out, _ = run(["route"])
    assert code == 0 and "calibrate" in out and "policy routing.v1" in out

    # a policy looser than the published rule must name itself — under the published
    # version string it is refused (every decision names the bar it cleared)
    code, _, err = run(["route", "--policy-json", '{"min_n": 1, "min_ci_low": 0.0}'])
    assert code == 2 and "cannot use version 'routing.v1'" in err and "min_n" in err
    code, d = run_json(
        run,
        [
            "route",
            "--policy-json",
            '{"min_n": 1, "min_ci_low": 0.0, "version": "routing.v1-calibration"}',
        ],
    )
    assert code == 0
    routes = {(x["cell"]["model"], x["route"]) for x in d["decisions"]}  # type: ignore[index,union-attr]
    assert ("gold", "deliver") in routes
    policy_file = tmp_path / "policy.json"
    policy_file.write_text(
        json.dumps(
            {"min_n": 1, "min_ci_low": 0.0, "granularize_sizes": ["XS"], "version": "routing.v1-xs"}
        )
    )
    code, d = run_json(run, ["route", "--policy-json", str(policy_file)])
    assert code == 0
    assert {x["route"] for x in d["decisions"] if x["cell"]["model"] == "gold"} == {"granularize"}  # type: ignore[index,union-attr]

    code, _, err = run(["route", "--policy-json", '{"min_zebra": 1}'])
    assert code == 2 and "unknown field" in err
    code, _, err = run(["route", "--policy-json", "{oops"])
    assert code == 2 and "not valid JSON" in err
    code, _, err = run(["route", "--policy-json", str(tmp_path / "nope.json")])
    assert code == 2


def test_forged_false_q1_row_cannot_even_be_read(run: Run, tmp_path: Path) -> None:
    """A false-Q1 row cannot be written through the ledger, so forge one on disk. The
    row-level invariant fires on LOAD, before routing could ever see it: exit 2."""
    from crb.core.evidence import canonical_json, sha256_text
    from crb.core.ledger import GENESIS_HASH

    forged = {
        "repo": "x",
        "task_id": "f" * 40,
        "clean": True,
        "tests_unmodified": True,
        "target_green": True,
        "no_new_failures": False,
        "source_changed": True,
        "capability_class": "bug.fix",
        "size": "XS",
        "language": "python",
        "builder": "b",
        "model": "m",
        "provider": "p",
        "evidence_pack_hash": "0" * 64,
        "row_id": "forged",
        "prev_hash": GENESIS_HASH,
    }
    forged["row_hash"] = sha256_text(canonical_json({**forged, "labels": {}}))
    path = tmp_path / "forged.jsonl"
    path.write_text(json.dumps(forged) + "\n")
    # GradeRow refuses to even load it: the invariant is enforced on construction
    code, _, err = run(["route", "--path", str(path)])
    assert code == 2 and "FalseQ1Violation" in err


# ---------------------------------------------------------------------------
# error mapping
# ---------------------------------------------------------------------------


def test_broken_state_files_are_harness_errors(run: Run, tmp_path: Path) -> None:
    bad = tmp_path / "repos"
    bad.mkdir()
    (bad / "broken.json").write_text("{not json")
    code, _, err = run(["repo", "probe", "broken", "--workdir", str(tmp_path)])
    assert code == 2 and "not valid JSON" in err
    (bad / "broken.json").write_text(json.dumps({"language": "python", "path": str(tmp_path)}))
    code, _, err = run(["mine", "broken", "--workdir", str(tmp_path)])
    assert code == 2 and "not a git repository" in err


def test_unexpected_exception_maps_to_exit_two_unless_debug(
    run: Run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    garbage = tmp_path / "garbage.jsonl"
    garbage.write_text("{not json\n")
    monkeypatch.delenv("CRB_DEBUG", raising=False)
    code, _, err = run(["ledger", "verify", "--path", str(garbage)])
    assert code == 2 and "JSONDecodeError" in err and "Traceback" not in err
    monkeypatch.setenv("CRB_DEBUG", "1")
    with pytest.raises(json.JSONDecodeError):
        run(["ledger", "verify", "--path", str(garbage)])


def test_cli_never_leaks_operator_env_into_test_runs(
    run: Run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The probe runs under the LocalExecutor's minimal env: a secret in the operator's
    environment must not reach the repository's tests (non-negotiable 4)."""
    clone = make_repo(tmp_path / "envrepo")
    (clone.path / "tests" / "test_env.py").write_text(
        "import os\n\n\ndef test_env():\n"
        "    assert 'SUPER_SECRET_TOKEN' not in os.environ\n"
        "    assert os.environ.get('CI') == '1'\n"
    )
    code, _, _ = run(
        [
            "repo",
            "add",
            "envrepo",
            "--path",
            str(clone.path),
            "--language",
            "py",
            "--probe",
            "tests/test_env.py",
            "--runner-opt",
            f"python={sys.executable}",
        ]
    )
    assert code == 0
    monkeypatch.setenv("SUPER_SECRET_TOKEN", "sk-live-abcdefghijklmnopqrstuvwxyz")
    assert "SUPER_SECRET_TOKEN" in os.environ
    code, d = run_json(run, ["repo", "probe", "envrepo"])
    assert code == 0 and d["green"] is True


# ---------------------------------------------------------------------------
# ADR-0019: qualification in the live posture; --adhoc never ledgers
# ---------------------------------------------------------------------------


def test_repo_qualify_records_each_task_in_the_live_posture(
    mined: CliRepo, run: Run, workdir: Path
) -> None:
    code, d = run_json(run, ["repo", "qualify", "demo", "--task", mined.sub_task])
    assert code == 0, d
    assert d["qualified"] == 1 and d["total"] == 1 and d["cost_usd"] == 0.0
    assert str(d["posture_class"]).startswith("local/inplace/")
    records = [
        json.loads(line)
        for line in (workdir / "qualifications" / "demo.jsonl").read_text().splitlines()
    ]
    assert records[-1]["task_id"] == mined.sub_task and records[-1]["state"] == "qualified"
    assert records[-1]["posture_id"] == d["posture_id"]


def test_grade_adhoc_never_appends_a_row(mined: CliRepo, run: Run, tmp_path: Path) -> None:
    dest = tmp_path / "wt-adhoc"
    assert run(["prep", "demo", mined.sub_task, "--dest", str(dest)])[0] == 0
    code, _, err = run(
        ["grade", "demo", mined.sub_task, "--worktree", str(dest), "--adhoc", "--ledger"]
    )
    assert code != 0 and "never appends a row" in err
    code, d = run_json(run, ["grade", "demo", mined.sub_task, "--worktree", str(dest), "--adhoc"])
    assert code == 1 and d["target_green"] is False
    assert d["blame_control"] == "unwitnessed"  # a quick look: no witness, so no row
