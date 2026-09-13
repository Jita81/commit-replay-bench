"""``crb repo add --url`` (W3-B): clones now into ``<workdir>/repos/<name>``, records the
path, refuses policy-violating sources, and keeps ``--path`` + ``--url`` (informational)
working as before."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from crb.cli.main import main
from crb.core.git import LOCAL_CLONE_ENV, GitRepo
from fixtures import pyrepo as pr
from fixtures.remote import bare_remote

Run = Callable[[Sequence[str]], tuple[int, str, str]]


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    return tmp_path / ".crb"


@pytest.fixture
def run(workdir: Path, capsys: pytest.CaptureFixture[str]) -> Run:
    def _run(argv: Sequence[str]) -> tuple[int, str, str]:
        capsys.readouterr()
        code = main([*argv, "--workdir", str(workdir)])
        out = capsys.readouterr()
        return code, out.out, out.err

    return _run


@pytest.fixture
def remote(pyrepo: pr.PyRepo, tmp_path: Path) -> str:
    return bare_remote(pyrepo.path, tmp_path / "remote.git")


def test_add_by_url_clones_and_registers(
    run: Run, workdir: Path, remote: str, pyrepo: pr.PyRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(LOCAL_CLONE_ENV, "1")
    code, out, err = run(
        [
            "repo",
            "add",
            "demo",
            "--url",
            remote,
            "--language",
            "py",
            "--src-prefix",
            "src/",
            "--json",
        ]
    )
    assert code == 0, err
    doc = json.loads(out)
    dest = workdir / "repos" / "demo"
    assert doc["path"] == str(dest) and doc["cloned"] == {"url": remote, "head": pyrepo.docs_sha}
    assert doc["config"]["url"] == remote and doc["config"]["src_prefix"] == "src/"
    assert "cloning" in err and str(dest) in err
    assert GitRepo(dest).is_repo() and GitRepo(dest).rev_parse() == pyrepo.docs_sha
    saved = json.loads((workdir / "repos" / "demo.json").read_text(encoding="utf-8"))
    assert saved["path"] == str(dest) and saved["url"] == remote
    # the clone directory sits beside the config file and does not pollute `repo list`
    code, out, _ = run(["repo", "list", "--json"])
    assert code == 0 and [r["repo"] for r in json.loads(out)["repos"]] == ["demo"]
    # human output names the clone
    code, out, _ = run(["repo", "add", "demo2", "--url", remote, "--language", "py"])
    assert code == 0 and out.startswith("cloned ") and "registered demo2" in out


def test_add_by_url_refuses_local_sources_by_default(
    run: Run, workdir: Path, remote: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(LOCAL_CLONE_ENV, raising=False)
    code, _, err = run(["repo", "add", "demo", "--url", remote, "--language", "py"])
    assert code == 2 and "refused" in err and LOCAL_CLONE_ENV in err
    assert (
        not (workdir / "repos" / "demo").exists() and not (workdir / "repos" / "demo.json").exists()
    )
    code, _, err = run(["repo", "add", "demo", "--url", "/srv/repos/x", "--language", "py"])
    assert code == 2 and "not a git URL" in err
    code, _, err = run(
        ["repo", "add", "demo", "--url", "http://example.org/x.git", "--language", "py"]
    )
    assert code == 2 and "scheme 'http'" in err


def test_add_needs_path_or_url_and_checks_duplicates_before_cloning(
    run: Run, workdir: Path, remote: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, _, err = run(["repo", "add", "demo", "--language", "py"])
    assert code == 2 and "--path" in err and "--url" in err
    monkeypatch.setenv(LOCAL_CLONE_ENV, "1")
    assert run(["repo", "add", "demo", "--url", remote, "--language", "py"])[0] == 0
    code, _, err = run(["repo", "add", "demo", "--url", remote, "--language", "py"])
    assert code == 2 and "already exists" in err
    # --force re-registers; the existing clone is reused (idempotent), not re-cloned
    marker = workdir / "repos" / "demo" / "marker"
    marker.write_text("x", encoding="utf-8")
    code, out, _ = run(["repo", "add", "demo", "--url", remote, "--language", "py", "--force"])
    assert code == 0 and marker.exists() and out.startswith("cloned ")
    code, _, err = run(["repo", "add", "Bad Name", "--url", remote, "--language", "py"])
    assert code == 2 and "lowercase" in err


def test_path_plus_url_keeps_the_old_behaviour(
    run: Run, workdir: Path, pyrepo: pr.PyRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With ``--path`` the URL is informational: nothing is cloned, no policy check."""
    monkeypatch.delenv(LOCAL_CLONE_ENV, raising=False)
    code, out, _ = run(
        [
            "repo",
            "add",
            "demo",
            "--path",
            str(pyrepo.path),
            "--url",
            "https://github.com/example/demo",
            "--language",
            "py",
            "--json",
        ]
    )
    assert code == 0
    doc = json.loads(out)
    assert doc["path"] == str(pyrepo.path) and "cloned" not in doc
    assert doc["config"]["url"] == "https://github.com/example/demo"
    assert not (workdir / "repos" / "demo").exists()
