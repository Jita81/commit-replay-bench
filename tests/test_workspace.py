"""crb.core.workspace — parent worktree + overlays + integrity on the fixture repo."""

from __future__ import annotations

import shutil
from pathlib import Path

from crb.core.git import GitRepo
from crb.core.spec import Language, RepoConfig
from crb.core.workspace import (
    HARNESS_SYMLINK,
    DiffStats,
    Workspace,
    git_blob_oid,
    sha256_bytes,
)
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


def test_diff_stats_includes_untracked_new_files(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    """A change that only ADDS a file carried an empty diff (``git diff HEAD`` ignores
    untracked files) — human-review-guide exercise 4, 2026-09-14. The hash must cover it,
    and it must be deterministic across path order."""
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws") as ws:
        (ws.root / "src" / "calc" / "extra.py").write_text("X = 1\nY = 2\n", encoding="utf-8")
        stats = ws.diff_stats()
        assert stats.files == ("src/calc/extra.py",)
        assert stats.additions == 2 and stats.deletions == 0
        assert stats.diff_sha256 != ws.diff_stats(exclude=["src/calc/extra.py"]).files  # smoke
        empty = Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws2")
        try:
            assert empty.diff_stats().diff_sha256 != stats.diff_sha256
        finally:
            empty.remove()
        # exclude filters files/counts but the hash still covers the full diff
        ex = ws.diff_stats(exclude=["src/calc/extra.py"])
        assert ex.files == () and ex.additions == 0
        assert ex.diff_sha256 == stats.diff_sha256


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


# ---------------------------------------------------------------------------
# touched_files: every kind of change, ignore rules, harness-written files
# ---------------------------------------------------------------------------


def test_touched_files_reports_a_rename_as_delete_plus_add(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """git's rename detection would collapse `git mv pytest.ini x` into the new name
    only; the deleted path is a change too (a deleted config is an oracle edit)."""
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws") as ws:
        ws.repo.run("mv", "pytest.ini", "tests/pytest.ini", cwd=ws.root, check=True)
        assert ws.touched_files() == ["pytest.ini", "tests/pytest.ini"]


def test_touched_files_reports_deleted_and_staged_files(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws") as ws:
        (ws.root / "pytest.ini").unlink()
        (ws.root / "staged.py").write_text("S = 1\n")
        ws.repo.run("add", "staged.py", cwd=ws.root, check=True)
        (ws.root / "deep" / "er").mkdir(parents=True)
        (ws.root / "deep" / "er" / "new.py").write_text("N = 1\n")
        assert ws.touched_files() == ["deep/er/new.py", "pytest.ini", "staged.py"]


def _repo_with_gitignore(pyrepo: pr.PyRepo) -> str:
    """Commit a ``.gitignore`` (``build/``), then one more commit, so a trial of the
    latter has the ignore file AT ITS PARENT."""
    (pyrepo.path / ".gitignore").write_text("build/\n", encoding="utf-8")
    pr.git(pyrepo.path, "add", "-A")
    pr.git(pyrepo.path, "commit", "-q", "-m", "chore: ignore build/")
    return pyrepo.add_pyproject_commit()


def test_touched_files_honours_pre_existing_ignore_rules(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    sha = _repo_with_gitignore(pyrepo)
    with Workspace.create(pyrepo.repo, sha, tmp_path / "ws") as ws:
        (ws.root / "build").mkdir()
        (ws.root / "build" / "out.txt").write_text("x")
        assert ws.touched_files() == []
        # the builder appends a rule: the OLD rule is still honoured, the new one is not
        (ws.root / ".gitignore").write_text("build/\nconftest.py\n", encoding="utf-8")
        (ws.root / "conftest.py").write_text("# hidden\n")
        assert ws.touched_files() == [".gitignore", "conftest.py"]


def test_touched_files_pierces_builder_authored_ignore_rules(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """A new .gitignore (root or nested) cannot hide files; an ignored directory is
    expanded to the files beneath it."""
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws") as ws:
        pr.write_files(
            ws,
            [
                (".gitignore", "hidden/\n"),
                ("hidden/a.py", "A = 1\n"),
                ("hidden/sub/b.py", "B = 1\n"),
                ("tests/.gitignore", "pytest.ini\n"),
                ("tests/pytest.ini", "[pytest]\n"),
            ],
        )
        assert ws.repo.run("ls-files", "--others", "--exclude-standard", cwd=ws.root).lines == [
            ".gitignore",
            "tests/.gitignore",
        ]
        assert ws.touched_files() == [
            ".gitignore",
            "hidden/a.py",
            "hidden/sub/b.py",
            "tests/.gitignore",
            "tests/pytest.ini",
        ]


def test_touched_files_excludes_harness_written_files_until_edited(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    shared = pyrepo.path / "shared-cache"
    shared.mkdir()
    cfg = pr.default_config(
        runner_opts={
            "post_create": [
                {"write_if_missing": {"path": "conftest.py", "content": "# injected\n"}},
                {"symlink": {"path": "cache", "target": "shared-cache"}},
            ]
        }
    )
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws", config=cfg) as ws:
        assert set(ws.harness_files) == {"conftest.py", "cache"}
        assert ws.harness_files["cache"] == HARNESS_SYMLINK
        assert ws.harness_unchanged("conftest.py") and ws.harness_unchanged("cache")
        assert not ws.harness_unchanged("pytest.ini")
        assert ws.touched_files() == []
        (ws.root / "conftest.py").write_text("# injected\nimport calc\n")
        assert not ws.harness_unchanged("conftest.py")
        assert ws.touched_files() == ["conftest.py"]
        (ws.root / "cache").unlink()
        (ws.root / "cache").mkdir()
        assert not ws.harness_unchanged("cache")  # replaced by a real directory


def test_javascript_node_modules_link_is_harness_written(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    (pyrepo.path / "node_modules" / ".bin").mkdir(parents=True)
    js_cfg = RepoConfig(
        name="jsfixture", language=Language.JAVASCRIPT, runner="mocha", test_prefix="tests/"
    )
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws", config=js_cfg) as ws:
        assert ws.harness_files == {"node_modules": HARNESS_SYMLINK}
        assert "node_modules" not in ws.touched_files()


def test_parent_text(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws") as ws:
        assert ws.parent_text(pr.SRC) == pr.SRC_INITIAL
        assert ws.parent_text(pr.TEST_SUBTRACT) is None  # only exists at the commit


# ---------------------------------------------------------------------------
# The grader's view is independent of the builder's git (independent review pass,
# 2026-09-14, finding 1): info/exclude, a moved HEAD, index bits, a forged index —
# and the honest paths still read the same.
# ---------------------------------------------------------------------------


def _exclude_path(ws: Workspace) -> Path:
    rel = ws.repo.run(
        "rev-parse", "--path-format=absolute", "--git-path", "info/exclude", cwd=ws.root
    ).stdout.strip()
    return Path(rel)


def _others(ws: Workspace) -> list[str]:
    """git's own (exclude-honouring) view of untracked files — what the old code read."""
    return ws.repo.run("ls-files", "--others", "--exclude-standard", cwd=ws.root).lines


def test_touched_files_ignores_info_exclude_and_the_grader_restores_it(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """Sign-off finding 1(a): appending ``conftest.py`` to the worktree's
    ``info/exclude`` hid the poison from ``ls-files --exclude-standard``. The exclude
    file of a linked worktree is the MAIN CLONE's, so the line also hid it from every
    other worktree of the repo. The tree walk never reads the file; the pre-flight
    removes the builder's line and reports it."""
    with Workspace.create(
        pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws", config=pyrepo.config
    ) as ws:
        exclude = _exclude_path(ws)
        assert exclude == pyrepo.path / ".git" / "info" / "exclude"  # shared, not per-worktree
        baseline = ws.exclude_baseline
        assert baseline is not None
        (ws.root / "conftest.py").write_text("# poison\n")
        with exclude.open("a", encoding="utf-8") as fh:
            fh.write("conftest.py\n")
        assert "conftest.py" not in _others(ws)
        assert ws.touched_files() == ["conftest.py"]
        violations = ws.enforce_integrity()
        assert [v.kind for v in violations] == ["exclude_edited"]
        assert violations[0].files == (".git/info/exclude",)
        assert "conftest.py" in violations[0].detail
        assert violations[0].to_dict()["kind"] == "exclude_edited"
        assert exclude.read_text(encoding="utf-8").splitlines() == baseline
        assert ws.enforce_integrity() == []  # restored: nothing left to report
        assert ws.touched_files() == ["conftest.py"]


def test_touched_files_ignores_core_excludesfile(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    """``core.excludesFile`` is git config the builder can reach; the walk never asks."""
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws") as ws:
        global_ignore = tmp_path / "global-ignore"
        global_ignore.write_text("conftest.py\n", encoding="utf-8")
        pr.git(pyrepo.path, "config", "core.excludesFile", str(global_ignore))
        (ws.root / "conftest.py").write_text("# poison\n")
        assert "conftest.py" not in _others(ws)
        assert ws.touched_files() == ["conftest.py"]
        assert ws.enforce_integrity() == []


def test_a_bound_workspace_leaves_the_exclude_file_alone_but_still_sees_the_file(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """The CLI binds a Workspace to an existing worktree (no create-time baseline):
    the pre-flight cannot know what the file held, so it does not rewrite it — and
    the grader does not need it to, because the walk never reads it."""
    created = Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws", config=pyrepo.config)
    try:
        exclude = _exclude_path(created)
        with exclude.open("a", encoding="utf-8") as fh:
            fh.write("conftest.py\n")
        (created.root / "conftest.py").write_text("# poison\n")
        bound = Workspace(pyrepo.repo, created.root, sha=pyrepo.feat_sha, parent=pyrepo.initial_sha)
        assert bound.exclude_baseline is None
        assert bound.enforce_integrity() == []
        assert "conftest.py" in exclude.read_text(encoding="utf-8")
        assert bound.touched_files() == ["conftest.py"]
    finally:
        created.remove()


def test_restore_exclude_tolerates_a_concurrent_trials_harness_line(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """Two JS trials of one repo both append ``/node_modules`` to the shared file; the
    second's line is not the first's builder's doing. Membership is by line, not
    byte position."""
    (pyrepo.path / "node_modules" / ".bin").mkdir(parents=True)
    js_cfg = RepoConfig(
        name="jsfixture", language=Language.JAVASCRIPT, runner="mocha", test_prefix="tests/"
    )
    with (
        Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "a", config=js_cfg) as a,
        Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "b", config=js_cfg) as b,
    ):
        assert a.exclude_patterns == ["/node_modules"] and b.exclude_patterns == ["/node_modules"]
        assert _exclude_path(a).read_text(encoding="utf-8").count("/node_modules") == 2
        assert a.enforce_integrity() == [] and b.enforce_integrity() == []
        assert a.touched_files() == [] and b.touched_files() == []


def test_a_commit_inside_the_worktree_is_an_integrity_violation(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """Sign-off finding 1(b): staging and committing the poison inside the worktree
    moved HEAD so ``git diff HEAD`` saw nothing. The walk compares against the
    recorded parent by sha; the pre-flight reports the moved HEAD."""
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws") as ws:
        (ws.root / "conftest.py").write_text("# poison\n")
        pr.git(ws.root, "add", "-f", "conftest.py")
        pr.git(ws.root, "commit", "-q", "-m", "x")
        assert ws.repo.run("diff", "--name-only", "HEAD", cwd=ws.root).lines == []
        assert ws.touched_files() == ["conftest.py"]
        violations = ws.enforce_integrity()
        assert [v.kind for v in violations] == ["head_moved"]
        assert violations[0].files == (".git/HEAD",)
        assert ws.parent[:10] in violations[0].detail


def test_skip_worktree_and_assume_unchanged_are_integrity_violations(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """Sign-off finding 1(c): a tracked file flagged ``--skip-worktree`` or
    ``--assume-unchanged`` vanished from ``git diff``. The walk hashes the file; the
    pre-flight names the flagged path."""
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws") as ws:
        (ws.root / "pytest.ini").write_text("[pytest]\ntestpaths = nowhere\n", encoding="utf-8")
        for flag, undo in (
            ("--skip-worktree", "--no-skip-worktree"),
            ("--assume-unchanged", "--no-assume-unchanged"),
        ):
            ws.repo.run("update-index", flag, "pytest.ini", cwd=ws.root, check=True)
            assert ws.repo.run("diff", "--name-only", "HEAD", cwd=ws.root).lines == []
            assert ws.touched_files() == ["pytest.ini"]
            violations = ws.enforce_integrity()
            assert [v.kind for v in violations] == ["index_bits"], flag
            assert violations[0].files == ("pytest.ini",)
            ws.repo.run("update-index", undo, "pytest.ini", cwd=ws.root, check=True)
        assert ws.enforce_integrity() == []
        assert ws.touched_files() == ["pytest.ini"]


def test_a_redirected_gitdir_is_an_integrity_violation(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    """The worktree's ``.git`` file is a pointer; pointed at another repository whose
    HEAD happens to be the parent, git inside the worktree answers for that repo."""
    other = pr.build(tmp_path / "other")  # same fixture: the same shas exist there
    assert other.initial_sha == pyrepo.initial_sha
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws") as ws:
        (ws.root / ".git").write_text(f"gitdir: {other.path / '.git'}\n", encoding="utf-8")
        pr.git(other.path, "checkout", "-q", other.initial_sha)
        violations = ws.enforce_integrity()
        assert "foreign_gitdir" in [v.kind for v in violations]
        assert (".git",) in [v.files for v in violations]


def test_a_forged_index_cannot_hide_a_tracked_edit(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    """``update-index --cacheinfo`` re-points the index entry at the parent's blob
    while the file on disk is the poison; the walk hashes the bytes on disk."""
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws") as ws:
        oid = ws.repo.run("rev-parse", f"{ws.parent}:pytest.ini", check=True).stdout.strip()
        (ws.root / "pytest.ini").write_text("[pytest]\ntestpaths = nowhere\n", encoding="utf-8")
        ws.repo.run("add", "pytest.ini", cwd=ws.root, check=True)
        ws.repo.run(
            "update-index", "--cacheinfo", f"100644,{oid},pytest.ini", cwd=ws.root, check=True
        )
        assert ws.repo.run("diff", "--name-only", "--cached", "HEAD", cwd=ws.root).lines == []
        assert ws.touched_files() == ["pytest.ini"]


def test_a_self_hiding_gitignore_cannot_hide_itself_or_its_rules(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """A new ``.gitignore`` that lists ``.gitignore`` was invisible to the old
    ``ls-files``-based view, so its other rules were trusted as pre-existing."""
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws") as ws:
        pr.write_files(ws, [(".gitignore", ".gitignore\nconftest.py\n"), ("conftest.py", "# x\n")])
        assert _others(ws) == []
        assert ws.touched_files() == [".gitignore", "conftest.py"]


def test_touched_files_reports_type_changes_and_symlinks(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    """A tracked file replaced by a symlink (to poison elsewhere), a new symlink, and a
    tracked directory replaced by a symlink are all changes."""
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws") as ws:
        (ws.root / "poison.ini").write_text("[pytest]\n", encoding="utf-8")
        (ws.root / "pytest.ini").unlink()
        (ws.root / "pytest.ini").symlink_to("poison.ini")
        (ws.root / "link.py").symlink_to(pr.SRC)
        assert ws.touched_files() == ["link.py", "poison.ini", "pytest.ini"]
        (ws.root / "pytest.ini").unlink()
        ws.restore_from_parent(["pytest.ini"])
        (ws.root / "link.py").unlink()
        (ws.root / "poison.ini").unlink()
        assert ws.touched_files() == []
        # a tracked directory replaced by a symlink: every file under it is gone
        shutil.rmtree(ws.root / "tests")
        (ws.root / "tests").symlink_to("src")
        assert ws.touched_files() == ["tests", pr.TEST_CALC]


def test_touched_files_ignores_the_executable_bit(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws") as ws:
        p = ws.root / "pytest.ini"
        p.chmod(p.stat().st_mode | 0o111)
        assert ws.touched_files() == []


def test_touched_files_prunes_directories_ignored_by_the_parents_rules(
    pyrepo: pr.PyRepo, tmp_path: Path
) -> None:
    """A wholly-untracked directory the parent's ``.gitignore`` hides is not walked
    (``node_modules``, ``.venv``); a nested new ``.gitignore`` inside a walked
    directory cannot hide its siblings; a rule the builder wrote into the parent's
    file is not honoured even though the rest of that file is."""
    sha = _repo_with_gitignore(pyrepo)
    with Workspace.create(pyrepo.repo, sha, tmp_path / "ws") as ws:
        pr.write_files(
            ws,
            [
                ("build/deep/out.txt", "x"),
                ("build/.gitignore", "*\n"),
                ("vendor/.gitignore", "lib.py\n"),
                ("vendor/lib.py", "L = 1\n"),
            ],
        )
        assert ws.touched_files() == ["vendor/.gitignore", "vendor/lib.py"]
        (ws.root / ".gitignore").write_text("build/\nvendor/\n", encoding="utf-8")
        assert ws.touched_files() == [".gitignore", "vendor/.gitignore", "vendor/lib.py"]
        (ws.root / ".gitignore").unlink()  # deleting the parent's rules un-hides build/
        assert ws.touched_files() == [
            ".gitignore",
            "build/.gitignore",
            "build/deep/out.txt",
            "vendor/.gitignore",
            "vendor/lib.py",
        ]


def test_parent_tree_and_blob_oids(pyrepo: pr.PyRepo, tmp_path: Path) -> None:
    with Workspace.create(pyrepo.repo, pyrepo.feat_sha, tmp_path / "ws") as ws:
        tree = ws.parent_tree()
        assert set(tree) == {"pytest.ini", pr.SRC, pr.TEST_CALC}
        entry = tree["pytest.ini"]
        assert entry.mode == "100644" and entry.size == len(pr.PYTEST_INI)
        assert entry.oid == ws.repo.run("rev-parse", f"{ws.parent}:pytest.ini").stdout.strip()
        assert git_blob_oid(pr.PYTEST_INI.encode()) == entry.oid
        assert git_blob_oid(b"", algorithm="sha256") == (
            "473a0f4c3be8a93681a267e3b1e9a7dcda1185436fe141f7749120a303721813"
        )
