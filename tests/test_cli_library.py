"""``crb library`` — the miners from the command line, writing nothing.

Navigation
----------
What it is:   CLI tests of ``crb library miners`` and ``crb library mine`` over a fixture
              repository added with ``crb repo add``.
What it does: Pins that ``miners`` lists the registry; that ``mine`` pins the commit, prints
              every proposal with its miner, file and commit and says nothing was written; that
              ``--miner`` narrows the run; and that an unknown miner, a commit the clone lacks
              and an option passed as a commit exit 2; and that no output echoes a credential
              a refused draft carried.
How:          ``crb.cli.main.main([...])`` in-process with ``--workdir`` under ``tmp_path``;
              ``tests/fixtures/miner_repo.py`` builds the clone.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0026-the-context-standard.md (item 10)
Works with:   src/crb/cli/commands/library.py (the verbs under test), src/crb/core/miners.py (the
              run), tests/fixtures/miner_repo.py (the clone)
Tested by:    this file
Touch when:   never for a new repository; a ``crb library`` verb or flag changes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crb.cli.main import main
from fixtures.miner_repo import MinerRepo, commit, make_miner_repo


@pytest.fixture
def added(tmp_path: Path) -> tuple[MinerRepo, Path]:
    fx = make_miner_repo(tmp_path / "acme")
    wd = tmp_path / "wd"
    code = main(["repo", "add", "acme", "--path", str(fx.path), "--language", "python",
                 "--workdir", str(wd)])  # fmt: skip
    assert code == 0
    return fx, wd


def test_miners_lists_the_registry(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["library", "miners", "--json", "--workdir", str(tmp_path)]) == 0
    names = [m["name"] for m in json.loads(capsys.readouterr().out)["miners"]]
    assert names == ["adrs", "owners", "lint", "tests", "change-profile"]


def test_mine_prints_what_would_be_proposed_and_writes_nothing(
    added: tuple[MinerRepo, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    fx, wd = added
    capsys.readouterr()
    assert (
        main(["library", "mine", "acme", "--commit", "main", "--json", "--workdir", str(wd)]) == 0
    )
    run = json.loads(capsys.readouterr().out)
    assert run["commit"] == fx.sha and run["writes"].startswith("nothing")
    ids = {p["entry_id"]: p for p in run["proposals"]}
    adr = ids["decision/adr-0001-use-go-modules-for-every-command"]
    assert adr["miner"] == "adrs@1" and adr["entry"]["provenance"]["commit"] == fx.sha
    assert not (wd / "library").exists()
    # --miner narrows the run; the table says nothing was written
    assert main(["library", "mine", "acme", "--miner", "lint", "--workdir", str(wd)]) == 0
    out = capsys.readouterr().out
    assert "convention/ruff" in out and "decision/" not in out
    assert "Nothing was written" in out


@pytest.mark.parametrize(
    ("argv", "says"),
    [
        (["--miner", "nobody"], "no miner registered as nobody"),
        (["--commit", "0" * 40], "names no commit"),
        (["--commit=--upload-pack=x"], "never an option"),
    ],
)
def test_mine_refuses_what_it_cannot_run(
    added: tuple[MinerRepo, Path], capsys: pytest.CaptureFixture[str], argv: list[str], says: str
) -> None:
    _fx, wd = added
    capsys.readouterr()
    assert main(["library", "mine", "acme", *argv, "--workdir", str(wd)]) == 2
    assert says in capsys.readouterr().err


def test_mine_never_prints_a_credential_a_refused_draft_carried(
    added: tuple[MinerRepo, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    fx, wd = added
    key = "sk-proj-abcdefghijklmnopqrstuvwx1234"
    commit(fx.path, {f"docs/adr/0009-rotate-{key}.md": f"# 9. Rotate {key}\n\n"
                     "Status: accepted\n\n## Decision\n\nRotate it.\n"}, "adr 9")  # fmt: skip
    capsys.readouterr()
    for extra in (["--json"], []):
        argv = ["library", "mine", "acme", "--miner", "adrs", *extra, "--workdir", str(wd)]
        assert main(argv) == 0
        out = capsys.readouterr()
        assert key not in out.out and key not in out.err
