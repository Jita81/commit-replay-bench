"""crb.core.workspace — parent worktree + overlays + integrity on the fixture repo."""

from __future__ import annotations

from pathlib import Path

from crb.core.git import GitRepo
from crb.core.spec import Language, RepoConfig
from crb.core.workspace import DiffStats, Workspace, sha256_bytes
from fixtures import pyrepo as pr


def test_create_checks_out_the_parent(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    ws = Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws", config=pyrepo.config)
    try:
        assert ws.sha == pyrepo.feat_sha
        assert ws.parent == pyrepo.initial_sha
        assert GitRepo(ws.root).rev_parse() == pyrepo.initial_sha
        assert ws.read(pr.SRC) == pr.SRC_INITIAL
        assert ws.exists(pr.TEST_CALC)
        assert not ws.exists(pr.TEST_SUBTRACT)
        assert ws.relpath(ws.root / pr.SRC) == pr.SRC
    finally:
        ws.remove()


def test_create_replaces_an_existing_dest(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    dest = tmp_path / "ws"
    ws1 = Workspace.create(pyrepo.repo, pyrepo.feat_sha, dest)
    (ws1.root / "junk.txt").write_text("x")
    ws2 = Workspace.create(pyrepo.repo, pyrepo.docs_sha, dest)
    try:
        assert not (ws2.root / "junk.txt").exists()
        assert ws2.parent == pyrepo.feat_sha
        assert ws2.exists(pr.TEST_SUBTRACT)  # docs' parent is feat
    finally:
        ws2.remove()


def test_context_manager_removes_worktree(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    dest = tmp_path / "ws"
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, dest) as ws:
        assert ws.root.exists()
        assert str(dest) in pyrepo.repo.run("worktree", "list", check=True).stdout
    assert not dest.exists()
    assert str(dest) not in pyrepo.repo.run("worktree", "list", check=True).stdout


def test_overlay_tests_brings_the_red_target_in(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws") as ws:
        ws.overlay_tests([pr.TEST_SUBTRACT])
        assert ws.read(pr.TEST_SUBTRACT) == pr.TEST_SUBTRACT_SRC
        assert ws.read(pr.SRC) == pr.SRC_INITIAL  # sources untouched: target is RED
        ok, offending = ws.tests_byte_identical([pr.TEST_SUBTRACT])
        assert ok and offending == []


def test_overlay_sources_and_restore_from_parent(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws") as ws:
        ws.overlay_sources([pr.SRC])
        assert "def subtract" in ws.read(pr.SRC)
        ws.restore_from_parent([pr.SRC])
        assert ws.read(pr.SRC) == pr.SRC_INITIAL


def test_tests_byte_identical_detects_tamper(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws") as ws:
        ws.overlay_tests([pr.TEST_SUBTRACT])
        pr.apply_tamper(ws)
        ok, offending = ws.tests_byte_identical([pr.TEST_SUBTRACT])
        assert not ok
        assert offending == [pr.TEST_SUBTRACT]


def test_tests_byte_identical_whitespace_only_edit_is_tamper(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws") as ws:
        ws.overlay_tests([pr.TEST_SUBTRACT])
        p = ws.root / pr.TEST_SUBTRACT
        p.write_text(p.read_text() + "\n")
        ok, offending = ws.tests_byte_identical([pr.TEST_SUBTRACT])
        assert not ok and offending == [pr.TEST_SUBTRACT]


def test_tests_byte_identical_missing_file_is_offending(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws") as ws:
        # not overlaid at all → the hash compare (second line of defence) catches it
        ok, offending = ws.tests_byte_identical([pr.TEST_SUBTRACT])
        assert not ok and offending == [pr.TEST_SUBTRACT]
        assert ws.file_hash(pr.TEST_SUBTRACT) is None
        assert ws.commit_file_hash(pr.TEST_SUBTRACT) == sha256_bytes(pr.TEST_SUBTRACT_SRC.encode())
        assert ws.commit_file_hash("missing.py") is None
        assert ws.file_hash(pr.SRC) == sha256_bytes(pr.SRC_INITIAL.encode())


def test_touched_files_includes_untracked_and_modified(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws") as ws:
        assert ws.touched_files() == []
        ws.overlay_tests([pr.TEST_SUBTRACT])  # staged new file
        pr.apply_regression(ws)  # modified tracked file
        (ws.root / "src" / "calc" / "extra.py").write_text("X = 1\n")  # untracked
        assert ws.touched_files() == [pr.SRC, "src/calc/extra.py", pr.TEST_SUBTRACT]


def test_diff_stats_counts_and_excludes_tests(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws") as ws:
        ws.overlay_tests([pr.TEST_SUBTRACT])
        pr.apply_gold(ws)
        stats = ws.diff_stats(exclude=[pr.TEST_SUBTRACT])
        assert isinstance(stats, DiffStats)
        assert stats.files == (pr.SRC,)
        assert stats.additions == pr.FEAT_SRC_CHURN
        assert stats.deletions == 0
        assert len(stats.diff_sha256) == 64
        d = stats.to_dict()
        assert d["files"] == [pr.SRC] and d["additions"] == pr.FEAT_SRC_CHURN

        everything = ws.diff_stats()
        assert set(everything.files) == {pr.SRC, pr.TEST_SUBTRACT}
        assert everything.additions == pr.FEAT_SRC_CHURN + len(pr.TEST_SUBTRACT_SRC.splitlines())
        assert everything.diff_sha256 == stats.diff_sha256  # hash covers the full diff


def test_diff_stats_counts_deletions(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws") as ws:
        (ws.root / pr.SRC).write_text('"""A tiny calculator."""\n')
        stats = ws.diff_stats()
        assert stats.files == (pr.SRC,)
        assert stats.additions == 0
        assert stats.deletions == len(pr.SRC_INITIAL.splitlines()) - 1


def test_post_create_hooks_write_if_missing_and_symlink(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    shared = pyrepo.path / "shared-cache"
    shared.mkdir()
    (shared / "marker").write_text("m")
    absolute_target = tmp_path / "abs-target"
    absolute_target.mkdir()
    cfg = pr.default_config(
        runner_opts={
            "post_create": [
                {"write_if_missing": {"path": "conftest.py", "content": "# injected\n"}},
                {"write_if_missing": {"path": pr.SRC, "content": "MUST NOT OVERWRITE"}},
                {"write_if_missing": {"path": "no/such/dir/x.py", "content": "skipped"}},
                {"symlink": {"path": "cache", "target": "shared-cache"}},
                {"symlink": {"path": "abs", "target": str(absolute_target)}},
                {"symlink": {"path": "dangling", "target": "does-not-exist"}},
                {"unknown_hook": {}},
            ]
        }
    )
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws", config=cfg) as ws:
        assert ws.read("conftest.py") == "# injected\n"
        assert ws.read(pr.SRC) == pr.SRC_INITIAL
        assert not ws.exists("no/such/dir/x.py")
        assert (ws.root / "cache").is_symlink()
        assert (ws.root / "cache" / "marker").read_text() == "m"
        assert (ws.root / "abs").is_symlink()
        assert not (ws.root / "dangling").exists()


def test_post_create_can_be_disabled(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    cfg = pr.default_config(
        runner_opts={"post_create": [{"write_if_missing": {"path": "conftest.py", "content": "x"}}]}
    )
    with Workspace.create(
        pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws", config=cfg, post_create=False
    ) as ws:
        assert not ws.exists("conftest.py")


def test_javascript_workspace_links_node_modules(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    (pyrepo.path / "node_modules" / ".bin").mkdir(parents=True)
    js_cfg = RepoConfig(
        name="jsfixture", language=Language.JAVASCRIPT, runner="mocha", test_prefix="tests/"
    )
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws", config=js_cfg) as ws:
        link = ws.root / "node_modules"
        assert link.is_symlink()
        assert (link / ".bin").is_dir()


def test_javascript_workspace_without_node_modules_is_fine(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    js_cfg = RepoConfig(name="jsfixture", language=Language.JAVASCRIPT, test_prefix="tests/")
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws", config=js_cfg) as ws:
        assert not (ws.root / "node_modules").exists()
