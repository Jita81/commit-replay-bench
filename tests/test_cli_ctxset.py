"""``crb ctxset`` — store, show and compare context sets through the API (ADR-0050).

Navigation
----------
What it is:   The CLI suite for ``crb ctxset put|show|compare``.
What it does: Pins that ``put`` stores a set (then reports ``already stored``), that ``show``
              prints metadata and never an entry's text, that an API refusal is a one-line
              error naming the API's code (exit 2), that ``compare`` prints the ceiling banner
              first for a hindsight treatment and per side ``k/n`` with the Wilson interval,
              and that ``--json`` prints the API's JSON as-is.
How:          ``ctxset.api_factory`` swapped for a ``CrbApi`` over the seeded app's
              ``TestClient`` (tests/fixtures/server_seed.py), signed in as the operator.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0050-context-set-arms.md
Works with:   src/crb/cli/commands/ctxset.py (under test), src/crb/cli/main.py (the entry
              point the put, show and compare cases call), src/crb/server/routes/ctxsets.py
              (the routes the commands reach), tests/fixtures/ctx_rows.py (the set documents
              and rows),
              tests/fixtures/server_seed.py (the seeded app and its users)
Tested by:    tests/test_cli_ctxset.py
Touch when:   never for a new repository; the verb's output or the ``/ctxsets`` routes change.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from crb.cli.commands import ctxset as cmd
from crb.cli.main import main
from crb.core import ctx_compare as cc
from crb.core import ctxset
from crb.mcp.client import CrbApi
from crb.server.app import API_PREFIX
from crb.store.ledger import DbLedger
from crb.store.models import Run
from fixtures.ctx_rows import ctx_doc, side
from fixtures.server_seed import ALPHA, USER_PW, USERS, Env, make_env

SECRET = "The handler reads the flag before parsing; the fix moves the read."
CONTROL_RUN = "c" * 31 + "1"
TREAT_RUN = "c" * 31 + "2"


class _SharedApi(CrbApi):
    """A client over the test app that leaves the shared ``TestClient`` open."""

    def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _no_ambient_crb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("CRB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    with make_env(tmp_path, role=None) as e:
        api = _SharedApi(e.client, prefix=API_PREFIX, username=USERS["operator"], password=USER_PW)
        monkeypatch.setattr(cmd, "api_factory", lambda: api)
        yield e


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    capsys.readouterr()
    code = main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def _doc_file(env: Env, tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    tasks = [env.info.task(i).task_id for i in (1, 2, 3, 4)]
    doc = ctx_doc(tasks=tasks, repo=ALPHA, text=SECRET)
    path = tmp_path / "set.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path, doc


def test_put_then_show(env: Env, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path, doc = _doc_file(env, tmp_path)
    parsed = ctxset.parse(doc)
    code, out, _ = _run(["ctxset", "put", str(path)], capsys)
    assert code == 0 and out.splitlines()[0] == "stored"
    assert parsed.name in out and "measurement-only" in out
    code, out, _ = _run(["ctxset", "put", str(path)], capsys)
    assert code == 0 and out.splitlines()[0] == "already stored"
    code, out, _ = _run(["ctxset", "show", parsed.name], capsys)
    assert code == 0 and parsed.digest in out and SECRET not in out
    code, out, _ = _run(["ctxset", "show", parsed.name, "--json"], capsys)
    assert json.loads(out)["name"] == parsed.name


def test_refusal_is_a_one_line_error(
    env: Env, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(ctx_doc(tasks=["f" * 40], repo=ALPHA)), encoding="utf-8")
    code, _, err = _run(["ctxset", "put", str(path)], capsys)
    assert code == 2 and f"422 {ctxset.REASON_COVERAGE}" in err
    code, _, err = _run(["ctxset", "show", f"ctx.oracle.{'0' * 12}"], capsys)
    assert code == 2 and "404 not_found" in err


def test_compare_prints_the_banner_first(
    env: Env, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path, doc = _doc_file(env, tmp_path)
    assert _run(["ctxset", "put", str(path)], capsys)[0] == 0
    cset = ctxset.parse(doc)
    t = cset.task_ids
    with env.factory() as s:
        for rid in (CONTROL_RUN, TREAT_RUN):
            s.add(Run(id=rid, kind="replay", mode="blind", status="succeeded", repo=ALPHA))
        s.commit()
    control = dict.fromkeys(t, False) | {t[0]: True}
    DbLedger(env.factory).append_many(
        [
            *side(cset, control, role=ctxset.ROLE_CONTROL, run_id=CONTROL_RUN),
            *side(cset, dict.fromkeys(t, True), run_id=TREAT_RUN),
        ]
    )
    argv = ["ctxset", "compare", "--control", CONTROL_RUN, "--treatment", TREAT_RUN]
    code, out, _ = _run(argv, capsys)
    lines = out.splitlines()
    assert code == 0 and lines[0] == cc.CEILING_BANNER
    assert "k/n 1/4" in lines[1] and "Wilson [" in lines[1]
    assert "k/n 4/4" in lines[2] and cset.arm in lines[2]
    assert "b=3 c=0" in out and SECRET not in out
    code, out, _ = _run([*argv, "--json"], capsys)
    assert code == 0 and json.loads(out)["b"] == 3


def test_compare_lines_without_a_banner() -> None:
    side_ = {"k": 1, "n": 2, "point": 0.5, "ci_low": 0.1, "ci_high": 0.9}
    d = {
        "control_arm": "A0",
        "treatment_arm": "A0+library@ctx.mech.0123456789ab",
        "control": side_,
        "treatment": side_,
        "b": 0,
        "c": 0,
        "p": 1.0,
        "pending": ["x"],
        "dose_imbalance": True,
    }
    lines = cmd.compare_lines(d)
    assert lines[0].startswith("control")
    assert any(line.startswith("PENDING 1") for line in lines)
    assert any(line.startswith("dose_imbalance") for line in lines)


def test_cli_loads_and_runs_without_the_mcp_extra() -> None:
    """A base install has neither ``httpx`` nor ``mcp``: ``crb.cli.main`` must still import.

    ``crb ctxset`` reaches the API through ``crb.mcp.client``; a load-time import made every
    verb, ``crb --help`` included, fail before dispatch on a base install.
    """
    import subprocess
    import sys

    probe = (
        "import sys\n"
        "class _Block:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in ('httpx', 'mcp'):\n"
        "            raise ModuleNotFoundError(f'No module named {name!r}')\n"
        "        return None\n"
        "sys.meta_path.insert(0, _Block())\n"
        "import crb.cli.main\n"
        "from crb.cli.commands import ctxset\n"
        "try:\n"
        "    ctxset._call(lambda api: None)\n"
        "except Exception as e:\n"
        "    print(type(e).__name__, e)\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=120, check=False
    )
    assert done.returncode == 0, done.stderr
    assert "CliError" in done.stdout
    assert "[mcp]" in done.stdout
