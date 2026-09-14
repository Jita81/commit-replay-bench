"""The builder contract: brief (no leakage), budget + ladder, outcome, and the two guards."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from crb.builders import base, builder_for_rung, builder_names, get_builder
from crb.builders import budget as bud
from crb.core.evidence import BuilderRef
from crb.core.spec import Language, RepoConfig

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
if str(_FIXTURES) not in sys.path:
    sys.path.insert(0, str(_FIXTURES))
from builders_repo import make_fixture  # noqa: E402

# ---------------------------------------------------------------------------
# Brief
# ---------------------------------------------------------------------------


def _cfg() -> RepoConfig:
    return RepoConfig(name="r", language=Language.PYTHON, src_prefix="pkg/", test_prefix="tests/")


def test_brief_never_carries_src_files_and_blind_drops_tests(tmp_path: Path) -> None:
    fx = make_fixture(tmp_path)
    sighted = base.BuildBrief.from_task(fx.task, mode="sighted", config=fx.config)
    assert sighted.test_files == ("tests/test_calc.py",)
    assert "src_files" not in sighted.to_dict()
    assert "pkg/calc.py" not in sighted.task_text()
    blind = base.BuildBrief.from_task(
        fx.task, mode="blind", config=fx.config, test_command="pytest x"
    )
    assert blind.test_files == () and blind.target_tests == () and blind.test_command == ""
    assert "test_calc" not in blind.task_text()
    assert "held out" in blind.task_text()


def test_blind_brief_with_test_paths_cannot_be_constructed() -> None:
    with pytest.raises(ValueError, match="blind"):
        base.BuildBrief("s", "m", "r", "python", mode="blind", test_files=("tests/t.py",))
    with pytest.raises(ValueError, match="blind"):
        base.BuildBrief("s", "m", "r", "python", mode="blind", test_command="pytest")
    with pytest.raises(ValueError):
        base.BuildBrief("s", "m", "r", "python", mode="sideways")
    with pytest.raises(ValueError, match="subject"):
        base.BuildBrief("  ", "m", "r", "python")


def test_brief_task_text_has_rules_and_message() -> None:
    b = base.BuildBrief("subj", "subj\n\nlong body", "r", "python", spec_facts=("adds a flag",))
    text = b.task_text(worktree="/wt")
    assert "/wt" in text and "long body" in text and "adds a flag" in text
    assert "DISQUALIFYING" in text  # the census rules are always attached
    assert b.repo_config().language is Language.PYTHON  # fallback config derives from language


# ---------------------------------------------------------------------------
# Budget, ladder, tracker
# ---------------------------------------------------------------------------


def test_budget_validation_and_roundtrip() -> None:
    b = base.Budget(
        max_turns=3, max_tool_calls=7, max_tokens=1000, max_cost_usd=0.5, wall_clock_s=60
    )
    assert base.Budget.from_dict(b.to_dict()) == b
    for bad in (
        {"max_turns": 0},
        {"max_tool_calls": 0},
        {"wall_clock_s": 0},
        {"max_cost_usd": -1},
        {"max_tokens": -1},
    ):
        with pytest.raises(ValueError):
            base.Budget(**bad)


def test_ladder_order_next_and_parse() -> None:
    ladder = bud.parse_ladder(
        "editblock:gpt-oss-120b@cerebras, claude_code:claude-sonnet-5@anthropic"
    )
    assert len(ladder) == 2
    assert ladder.first.label == "editblock:gpt-oss-120b"
    assert ladder.next_after(ladder.first) == ladder.rungs[1]
    assert ladder.next_after(ladder.rungs[1]) is None
    with pytest.raises(ValueError):
        ladder.next_after(base.Rung("x", "y"))
    assert base.EscalationLadder.from_dict(ladder.to_dict()) == ladder
    with pytest.raises(ValueError):
        base.EscalationLadder(())
    with pytest.raises(ValueError):
        bud.parse_rung("no-colon")
    assert [r.builder for r in bud.default_ladder()] == [
        "editblock",
        "openai_agent",
        "claude_code",
        "claude_code",
    ]


def test_budget_for_rung_overrides_only_budget_keys() -> None:
    base_budget = base.Budget()
    rung = base.Rung(
        "claude_code", "claude-opus-5", config={"wall_clock_s": 1800, "effort": "high"}
    )
    b = bud.budget_for_rung(rung, base_budget)
    assert b.wall_clock_s == 1800 and b.max_turns == base_budget.max_turns


def test_tracker_reports_the_cap_that_fired() -> None:
    clock = [0.0]
    meter = bud.CostMeter(bud.Pricing(1.0, 1.0), model="m")
    t = bud.BudgetTracker(
        base.Budget(
            max_turns=2, max_tool_calls=3, max_tokens=50, max_cost_usd=0.001, wall_clock_s=10
        ),
        meter,
        clock=lambda: clock[0],
    )
    assert t.exceeded() == ""
    t.note_turn()
    t.note_turn()
    assert t.exceeded() == base.STOP_MAX_TURNS
    t2 = bud.BudgetTracker(base.Budget(max_tool_calls=1), meter, clock=lambda: clock[0])
    t2.note_tool_call()
    assert t2.can_call_tool() == base.STOP_MAX_TOOL_CALLS
    meter.add(40, 20)  # 60 tokens > 50, cost 60e-6 < 0.001
    assert t.exceeded() == base.STOP_MAX_TOKENS
    meter.add(0, 2000)  # cost now > 0.001
    assert t.exceeded() == base.STOP_MAX_COST
    clock[0] = 11.0
    assert t.exceeded() == base.STOP_WALL_CLOCK  # wall clock outranks everything


def test_cost_meter_prefers_reported_cost_and_flags_unknown_pricing() -> None:
    m = bud.CostMeter(bud.Pricing(0.25, 0.69), model="gpt-oss-120b")
    m.add(1_000_000, 1_000_000)
    assert m.cost_usd == pytest.approx(0.94)
    m2 = bud.CostMeter(bud.Pricing(0.25, 0.69), model="x")
    m2.add(10, 10, cost_usd=0.5)
    assert m2.cost_usd == 0.5 and m2.cost_known
    with pytest.warns(UserWarning, match="UNKNOWN"):
        pr = bud.price_for("some-unknown-model")
    assert not pr.known
    m3 = bud.CostMeter(pr, model="some-unknown-model")
    m3.add(100, 100)
    assert m3.cost_usd == 0.0 and not m3.cost_known
    with pytest.warns(UserWarning):
        assert not bud.price_for("azure:gpt-4o").known
    assert bud.price_for("claude-opus-5").input_per_m == 5.0


def test_load_pricing_overlay_and_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "p.json"
    f.write_text('{"azure:gpt-4o": {"input_per_m": 2.5, "output_per_m": 10}}', encoding="utf-8")
    table = bud.load_pricing(f)
    assert table["azure:gpt-4o"].known and table["gpt-oss-120b"].input_per_m == 0.25
    assert bud.price_for("azure:gpt-4o", table).input_per_m == 2.5
    bad = tmp_path / "bad.json"
    bad.write_text("[1,2]", encoding="utf-8")
    with pytest.raises(ValueError):
        bud.load_pricing(bad)
    monkeypatch.setenv(bud.PRICING_ENV, str(f))
    assert bud.load_pricing()["azure:gpt-4o"].output_per_m == 10


# ---------------------------------------------------------------------------
# Outcome
# ---------------------------------------------------------------------------


def test_outcome_claim_is_labelled_untrusted_and_redacted() -> None:
    o = base.BuildOutcome(
        builder="b",
        model="m",
        provider="p",
        mode="sighted",
        done=True,
        summary="used key sk-live-abcdefghijklmnopqrstuvwxyz1234 to fix it",
        stop_reason=base.STOP_DONE,
        errors=("archaeology: git log",),
        budget=base.Budget(),
    )
    d = o.to_dict()
    assert d["claim"] == {"done": True, "summary": o.summary, "trusted": False}
    assert "sk-live" not in o.summary and "[REDACTED" in o.summary
    assert "transcript" not in d and "transcript" in o.to_dict(include_transcript=True)
    assert o.violated
    ref = o.builder_ref(transcript_ref="s3://x")
    assert (
        isinstance(ref, BuilderRef)
        and ref.transcript_ref == "s3://x"
        and ref.budget["max_turns"] == 25
    )
    assert "1 error(s)" in ref.note
    with pytest.raises(ValueError):
        base.BuildOutcome(builder="b", model="m", provider="p", mode="sighted", stop_reason="weird")


# ---------------------------------------------------------------------------
# TestFileGuard
# ---------------------------------------------------------------------------


def _guard(tmp_path: Path, mode: str) -> base.TestFileGuard:
    (tmp_path / "pkg").mkdir(exist_ok=True)
    (tmp_path / "tests").mkdir(exist_ok=True)
    return base.TestFileGuard(tmp_path, _cfg(), ["tests/test_target.py"], mode=mode)


@pytest.mark.parametrize("mode", ["sighted", "blind"])
def test_guard_refuses_protected_test_write_in_both_modes(tmp_path: Path, mode: str) -> None:
    g = _guard(tmp_path, mode)
    assert "immutable" in g.check_write("tests/test_target.py")
    assert "immutable" in g.check_write("./tests/../tests/test_target.py")
    assert g.check_write("pkg/mod.py") == ""
    with pytest.raises(base.GuardRefused):
        g.resolve_write("tests/test_target.py")
    assert g.resolve_write("pkg/mod.py") == tmp_path.resolve() / "pkg/mod.py"


def test_guard_blind_refuses_any_test_looking_path(tmp_path: Path) -> None:
    g = _guard(tmp_path, "blind")
    assert "test file" in g.check_write("tests/test_other.py")
    assert "test file" in g.check_write("tests/conftest.py")
    assert g.check_write("pkg/tests_helper.py") == ""  # not under the configured test prefix


def test_guard_sighted_also_refuses_other_tests(tmp_path: Path) -> None:
    g = _guard(tmp_path, "sighted")
    assert "test file" in g.check_write("tests/test_other.py")


def test_guard_refuses_traversal_absolute_and_git(tmp_path: Path) -> None:
    g = _guard(tmp_path, "sighted")
    assert "escapes" in g.check_write("../outside.py")
    assert "escapes" in g.check_write("pkg/../../outside.py")
    assert "absolute" in g.check_write("/etc/passwd")
    assert "absolute" in g.check_write(str(tmp_path / "pkg/x.py"))
    assert ".git" in g.check_write(".git/config")
    assert ".git" in g.check_read(".git/HEAD")
    assert ".git" in g.check_write("pkg/.git/x")
    assert "empty" in g.check_write("")
    assert g.check_read("pkg/mod.py") == ""


def test_guard_refuses_symlink_escape(tmp_path: Path) -> None:
    g = _guard(tmp_path, "sighted")
    outside = tmp_path.parent / "elsewhere"
    outside.mkdir(exist_ok=True)
    (tmp_path / "pkg" / "link").symlink_to(outside)
    assert "outside" in g.check_write("pkg/link/x.py")


def test_guard_tampered_post_hoc(tmp_path: Path) -> None:
    fx = make_fixture(tmp_path)
    ws = fx.workspace(tmp_path / "wt", mode="sighted")
    g = base.TestFileGuard(ws.root, fx.config, fx.task.test_files, mode="sighted")
    assert g.tampered(ws) == []
    (ws.root / "tests" / "test_calc.py").write_text("def test_add():\n    pass\n", encoding="utf-8")
    (ws.root / "tests" / "test_new.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    assert g.tampered(ws) == ["tests/test_calc.py", "tests/test_new.py"]
    ws.remove()


# ---------------------------------------------------------------------------
# GitArchaeologyGuard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["git", "log"],
        ["git", "log", "--oneline", "-5"],
        ["git", "show", "HEAD~1"],
        ["git", "show", "abc1234:pkg/calc.py"],
        ["git", "reflog"],
        ["git", "stash", "list"],
        ["git", "bisect", "start"],
        ["git", "checkout", "abc1234def"],
        ["git", "switch", "-"],
        ["git", "cat-file", "-p", "abc1234def"],
        ["git", "diff", "abc1234def"],
        ["git", "diff", "HEAD~1"],
        ["git", "diff", "HEAD@{1}"],
        ["git", "diff", "origin/main"],
        ["git", "-C", "/x", "log"],
        ["git", "--no-pager", "show"],
        ["env", "GIT_PAGER=cat", "git", "log"],
        ["sh", "-c", "git status && git log -1"],
        ["bash", "-c", "ls | git show"],
    ],
)
def test_archaeology_refused(argv: list[str]) -> None:
    assert base.GitArchaeologyGuard().check(argv).startswith("archaeology:")


@pytest.mark.parametrize(
    "argv",
    [
        ["git", "status"],
        ["git", "diff"],
        ["git", "diff", "HEAD"],
        ["git", "diff", "--", "pkg/calc.py"],
        ["git", "ls-files"],
        ["git", "grep", "-n", "def add"],
        ["python", "-m", "pytest", "tests/"],
        ["pytest", "-q"],
        ["go", "test", "./..."],
        ["pip", "freeze"],
        ["npm", "test"],
    ],
)
def test_allowed_commands(argv: list[str]) -> None:
    assert base.GitArchaeologyGuard().check(argv) == ""


@pytest.mark.parametrize(
    "argv",
    [
        ["curl", "https://example.com"],
        ["wget", "x"],
        ["pip", "install", "requests"],
        ["pip", "install", "-r", "req.txt"],
        ["python", "-m", "pip", "install", "x"],
        ["npm", "install"],
        ["npm", "i", "left-pad"],
        ["go", "get", "example.com/x"],
        ["cargo", "add", "serde"],
        ["gh", "pr", "view", "1"],
        ["uv", "pip", "install", "x"],
    ],
)
def test_network_refused(argv: list[str]) -> None:
    assert base.GitArchaeologyGuard().check(argv).startswith("network:")


def test_shell_splitting_and_substitution() -> None:
    g = base.GitArchaeologyGuard()
    assert g.check_shell("cd pkg; git log").startswith("archaeology:")
    assert g.check_shell("pytest -q || git show HEAD~1").startswith("archaeology:")
    assert g.check_shell("echo $(git log)").startswith("archaeology:")
    assert g.check_shell('echo "unterminated').startswith("archaeology:")
    assert g.check_shell("python -m pytest tests/test_x.py -q && git diff") == ""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_names_and_unknown() -> None:
    assert builder_names() == ("editblock", "openai_agent", "claude_code")
    with pytest.raises(ValueError, match="unknown builder"):
        get_builder("nope")
    b = get_builder("editblock", model="gpt-oss-120b", provider="cerebras")
    assert isinstance(b, base.Builder) and b.name == "editblock"
    c = builder_for_rung(
        base.Rung("claude_code", "claude-sonnet-5", "anthropic", {"wall_clock_s": 5})
    )
    assert c.name == "claude_code" and c.model == "claude-sonnet-5" and c.provider == "anthropic"
    o = builder_for_rung(base.Rung("openai_agent", "gpt-oss-120b", "cerebras"))
    assert o.provider == "cerebras"


def test_archaeology_guard_checks_substitutions_recursively() -> None:
    """$(pwd) / $(find …) are ordinary developer shell (koajs/koa builds were
    disqualified for them); only an inner violation is refused."""
    from crb.builders.base import GitArchaeologyGuard

    g = GitArchaeologyGuard()
    assert (
        g.check_shell(
            'NODE_PATH=$(pwd)/node_modules node --test $(find __tests__ -name "*.test.js")'
        )
        == ""
    )
    assert g.check_shell("echo `pwd`") == ""
    assert g.check_shell("(cd lib && node --test)") == ""
    assert "git log" in g.check_shell("echo $(git log -1)")
    assert "stash" in g.check_shell("git stash && npm test; git stash pop")
    assert "network" in g.check_shell("npx standard lib/request.js")
    assert g.check_shell("echo $(pwd").startswith("archaeology:")


def test_archaeology_guard_honours_shell_quoting() -> None:
    """Parentheses inside quotes are literal text, not sub-shells — a grep pattern
    like ``"preRun(ctx"`` refused an honest spf13/cobra build (2026-09-13). Only
    ``$( … )`` and backticks open a substitution inside double quotes; nothing does
    inside single quotes."""
    from crb.builders.base import GitArchaeologyGuard

    g = GitArchaeologyGuard()
    assert (
        g.check_shell(
            r'grep -n "func (c \*Command) Context\|c.ctx\b\|preRun(ctx" command.go | head -30'
        )
        == ""
    )
    assert g.check_shell("grep 'preRun(ctx' command.go") == ""
    assert g.check_shell('echo "a(b"') == ""
    assert g.check_shell('echo $(grep "a(b" f)') == ""
    assert "git show" in g.check_shell('cat "$(git show HEAD)"')
    assert "git diff" in g.check_shell('echo "`git diff HEAD~1`"')
    assert g.check_shell("echo 'unterminated").startswith("archaeology:")


# ---------------------------------------------------------------------------
# GitArchaeologyGuard — the 2026-09-13 corpus pass (each fix has a test on BOTH sides)
# ---------------------------------------------------------------------------


def _wt(tmp_path: Path) -> Path:
    """A worktree-shaped cwd: a local jest binary and a couple of source files."""
    (tmp_path / "node_modules" / ".bin").mkdir(parents=True)
    (tmp_path / "node_modules" / ".bin" / "jest").write_text("")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text("")
    return tmp_path


def test_guard_python_m_pip_read_only_forms_allowed() -> None:
    """``python -m pip list`` was refused by an ``or`` fall-through while ``pip list``
    passed — the exact command a builder runs after an ImportError."""
    g = base.GitArchaeologyGuard()
    for cmd in ("python -m pip list", "python3 -m pip show click", "python -m pip freeze | head"):
        assert g.check_shell(cmd) == "", cmd
    for cmd in (
        "python -m pip install x",
        "python3.12 -m pip install -U pip",
        "python -m ensurepip",
    ):
        assert g.check_shell(cmd).startswith("network:"), cmd
    assert "environment" in g.check_shell("pip uninstall -y click")
    assert g.check_shell("uv pip list") == "" and "network" in g.check_shell("uv pip install x")
    assert "network" in g.check_shell("uv run pytest") and "network" in g.check_shell("uvx ruff .")


def test_guard_heredoc_bodies_are_data_or_scanned(tmp_path: Path) -> None:
    """A quoted-tag body is data (an apostrophe in a comment refused honest builds);
    an unquoted-tag body still expands ``$( … )`` and is scanned for it; a body fed to
    a bare shell IS a script and is checked."""
    g = base.GitArchaeologyGuard(cwd=_wt(tmp_path))
    assert g.check_shell("cat <<'EOF' > /tmp/n.txt\nthis doesn't work\nEOF") == ""
    assert g.check_shell("cat <<'EOF' > x.py\nprint(\"(\")\n# it's\nEOF\nls") == ""
    assert g.check_shell("cat <<EOF > /tmp/e\nroot=$(pwd) it's fine\nEOF") == ""
    assert "git log" in g.check_shell("cat <<EOF\n$(git log -1)\nEOF")
    assert "git show" in g.check_shell("cat > /tmp/x <<EOF\n`git show HEAD~1`\nEOF")
    assert "git log" in g.check_shell("bash -s <<'EOF'\ngit log\nEOF")
    assert "network" in g.check_shell("sh <<'EOF'\ncurl https://x\nEOF")
    assert g.check_shell("python - <<'EOF'\nimport os\nEOF") == ""  # inline code: documented gap
    assert g.check_shell("cat << x") == ""  # no body, harmless
    assert g.check_shell("cat <<").startswith("archaeology:")  # no tag: fail closed


def test_guard_newline_redirection_and_group_bypasses_closed() -> None:
    """A newline separates commands like ``;``; a leading redirection or fd number does
    not hide the command; ``{ }``, ``if``, loops and function bodies are inspected."""
    g = base.GitArchaeologyGuard()
    for cmd in (
        "ls\ngit log",
        ">/dev/null git log",
        "2>/dev/null git show HEAD~1",
        "{ git log; }",
        "if true; then git log; fi",
        "while true; do git log; break; done",
        "f() { git log; }; f",
        "function f { git log; }",
        "alias g='git log'",
        "echo x | bash",
        "cat s.sh | sh",
        "$(which git) log",
        "$GIT log",
    ):
        assert g.check_shell(cmd).startswith("archaeology:"), cmd
    for cmd in (
        "ls\npwd",
        "go vet ./...\ngofmt -l .",
        "python -m pytest -q \\\n  -k slow",
        "{ echo a; go vet ./...; } 2>&1 | tail",
        "if [ -f go.mod ]; then echo go; fi",
        'for f in src/*.py; do wc -l "$f"; done',
        'case "$(uname)" in Darwin) echo mac;; *) echo other;; esac',
        "f() { ls; }; f",
        "alias ll='ls -la'",
        "(cd pkg && go test ./...)",
        "echo $((1 + 2))",
        "npm test &> /tmp/npm.log; grep -c ok /tmp/npm.log",
    ):
        assert g.check_shell(cmd) == "", cmd


def test_guard_wrappers_are_unwrapped() -> None:
    g = base.GitArchaeologyGuard()
    for cmd in (
        "env -i git log",
        "sudo -u root git log",
        "timeout -k 5 30 git log",
        "nice -n 10 git log",
        "stdbuf -oL git log",
        "watch -n1 git log",
        "xargs git log --",
        "echo x | xargs -I{} git show HEAD~1 -- {}",
        "find . -name '*.go' -exec git log -- {} \\;",
        "find . -execdir git log {} +",
        "bash -x -c 'git log'",
        "bash -euo pipefail -c 'git show HEAD~1'",
        "seq 1 | xargs -n1 curl https://x",
    ):
        assert g.check_shell(cmd).startswith(("archaeology:", "network:")), cmd
    for cmd in (
        "env -u PYTHONPATH python -m pytest -q",
        "timeout 120 python -m pytest tests -q",
        "git ls-files -z | xargs -0 grep -ln request",
        "find lib -name '*.js' -exec node --check {} \\;",
        "bash -euo pipefail -c 'go vet ./... && gofmt -l .'",
        "time go test ./...",
        "nohup go test ./... > /tmp/t.log 2>&1 &",
    ):
        assert g.check_shell(cmd) == "", cmd


def test_guard_git_working_tree_verbs(tmp_path: Path) -> None:
    """Working-tree-only verbs an honest builder needs (the old guard refused all of
    them): ``checkout``/``restore`` of PATHS, ``rev-parse`` of the layout, ``config``
    reads, ``apply``, ``mv``. Every revision-reaching form of the same verbs stays refused."""
    here = _wt(tmp_path)
    g = base.GitArchaeologyGuard(cwd=here)
    for cmd in (
        "git checkout -- src/x.py",
        "git checkout -- .",
        "git checkout HEAD -- src/x.py",
        "git checkout src/x.py",  # verified as a path against cwd
        "git restore -- src/x.py",
        "git restore --staged --worktree -- src/x.py",
        "git restore --source=HEAD -- src/x.py",
        "git rev-parse --show-toplevel",
        "git rev-parse --abbrev-ref HEAD",
        "git rev-parse --short HEAD",
        "git config --get user.name",
        "git config -l",
        "git config core.autocrlf",
        "git apply --check /tmp/p && git apply -R /tmp/p",
        "git mv src/x.py src/y.py",
        "git -C . status",
        "git -C src diff",
    ):
        assert g.check_shell(cmd) == "", cmd
    for cmd in (
        "git checkout main",
        "git checkout -",
        "git checkout -b fix",
        "git checkout --detach HEAD~1",
        "git checkout HEAD~1 -- src/x.py",
        "git checkout origin/main -- src/x.py",
        "git checkout nope.py",  # not a path in the worktree → cannot be verified
        "git restore --source=HEAD~1 -- src/x.py",
        "git restore -s abc1234def -- src/x.py",
        "git rev-parse main",
        "git rev-parse --git-dir",
        "git rev-parse HEAD~1",
        "git config user.email x@y",
        "git config --unset core.pager",
        "git config -e",
        "git reset -- src/x.py",
        "git switch -",
        "git blame src/x.py",
        "git -C /elsewhere status",
        "git -C .. diff HEAD",
        "git --git-dir=/x/.git diff",
    ):
        assert g.check_shell(cmd).startswith("archaeology:"), cmd
    # without a cwd, a bare positional after checkout cannot be verified → fail closed
    assert "cannot be verified" in base.GitArchaeologyGuard().check_shell("git checkout src/x.py")


def test_guard_git_diff_and_grep_reject_branch_names(tmp_path: Path) -> None:
    """``git diff main`` compared against the branch that holds the gold commit and
    passed the old guard (only shas and ``~``/``^``/``@{`` forms were caught)."""
    blind = base.GitArchaeologyGuard()
    for cmd in (
        "git diff main",
        "git diff master -- lib/",
        "git diff HEAD..main",
        "git diff HEAD...origin/main",
        "git diff FETCH_HEAD",
        "git diff @{u}",
        "git grep -n foo main",
        "git grep -n -e foo HEAD~1 -- src",
    ):
        assert "another revision" in blind.check_shell(cmd), cmd
    assert blind.check_shell("git diff src/x.py") == ""  # no cwd: not ref-like → allowed
    g = base.GitArchaeologyGuard(cwd=_wt(tmp_path))
    assert g.check_shell("git diff src/x.py") == ""
    assert g.check_shell("git diff HEAD --stat -- src/") == ""
    assert g.check_shell("git diff -S 'def add' -- src") == ""  # -S takes a value
    assert g.check_shell("git diff 'src/*.py'") == ""  # a glob can never be a ref
    assert g.check_shell("git grep -n -A 3 foo") == ""  # -A takes a value
    assert "a revision?" in g.check_shell("git diff feature/x")  # not a path in the worktree


def test_guard_git_network_verbs_are_labelled_network() -> None:
    """Refusal labels feed the instrument-vs-builder split the review asks for:
    ``git fetch`` is a network violation, not history reading."""
    g = base.GitArchaeologyGuard()
    for cmd in (
        "git fetch",
        "git pull --rebase",
        "git push",
        "git clone x",
        "git remote -v",
        "git lfs pull",
    ):
        assert g.check_shell(cmd).startswith("network: 'git"), cmd
    assert g.check_shell("git log").startswith("archaeology:")


def test_guard_git_dir_paths_refused_but_exclusions_allowed() -> None:
    g = base.GitArchaeologyGuard()
    for cmd in (
        "cat .git",
        "cat .git/HEAD",
        "ls -la .git/",
        "cat /Users/me/repo/.git/packed-refs",
        "find .git -name '*.pack'",
        "cd .git && ls",
    ):
        assert "'.git' is off limits" in g.check_shell(cmd), cmd
    for cmd in (
        "find . -name '*.py' -not -path './.git/*'",
        "find . -path ./.git -prune -o -name '*.go' -print",
        "grep -rn foo . --exclude-dir=.git",
        "rg -g '!.git' foo",
        "tree -I .git",
        "cat .gitignore .gitattributes",
        "ls .github/workflows",
    ):
        assert g.check_shell(cmd) == "", cmd


def test_guard_offline_flags_make_build_tools_honest() -> None:
    """``-o``/``--offline`` means "resolve from the local cache by construction", so the
    same goal is honest with the flag and refused without it. Installers are refused
    even with an offline flag: the rule is "never change the environment"."""
    g = base.GitArchaeologyGuard()
    assert g.check_shell("mvn -o -q dependency:tree") == ""
    assert "network" in g.check_shell("mvn -q dependency:tree")
    assert "network" in g.check_shell("./mvnw dependency:get -Dartifact=x")
    assert "network" in g.check_shell("mvn -o deploy")
    assert "network" in g.check_shell("mvn -U test")
    assert g.check_shell("./gradlew test --offline --tests 'X'") == ""
    assert "network" in g.check_shell("./gradlew dependencies")
    assert "network" in g.check_shell("./gradlew build --refresh-dependencies")
    assert g.check_shell("cargo update --offline") == ""
    assert "network" in g.check_shell("cargo update")
    assert "network" in g.check_shell("cargo install --offline --path .")
    assert "network" in g.check_shell("pip install --no-index --find-links w/ x")
    assert "network" in g.check_shell("npm install --offline")
    assert g.check_shell("GOPROXY=off go mod tidy") == ""
    assert "network" in g.check_shell("go mod tidy")
    assert "network" in g.check_shell("go run golang.org/x/example/hello@latest")
    assert "network" in g.check_shell("yarn") and g.check_shell("yarn test") == ""
    assert "network" in g.check_shell("yarn workspaces focus")
    assert "network" in g.check_shell("pnpm --filter x add lodash")
    assert g.check_shell("pnpm --filter x test") == ""
    assert "network" in g.check_shell("tox -e py312") and g.check_shell("tox --listenvs") == ""
    assert "network" in g.check_shell("pre-commit run --all-files")
    assert "network" in g.check_shell("docker run x") and "network" in g.check_shell(
        "open https://x"
    )


def test_guard_check_argv_accepts_cwd_and_tracks_cd(tmp_path: Path) -> None:
    """The argv API gained the same optional ``cwd`` (openai_agent passes none today);
    ``cd`` inside a command line moves the verification point, ``cd -`` loses it."""
    here = _wt(tmp_path)
    g = base.GitArchaeologyGuard()
    assert g.check(["npx", "jest"], cwd=here) == ""
    assert "network" in g.check(["npx", "jest"])
    g2 = base.GitArchaeologyGuard(cwd=here)
    assert g2.check(["npx", "jest"]) == ""
    (here / "sub" / "node_modules" / ".bin").mkdir(parents=True)
    (here / "sub" / "node_modules" / ".bin" / "tsc").write_text("")
    assert g2.check_shell("cd sub && npx tsc --noEmit") == ""
    assert "not in node_modules/.bin" in g2.check_shell("npx tsc --noEmit")
    assert "cannot be verified" in g2.check_shell("cd sub; cd -; npx tsc")


def test_guard_inline_code_is_scanned_not_parsed(tmp_path: Path) -> None:
    """2026-09-14 (A8's human-review exercises): the guard read only a segment's first
    word, so ``python -c "subprocess.run(['git','log'])"`` passed. Inline code is now
    scanned for git history/network verbs, ``.git`` paths and network tools — but NOT
    parsed as shell, so honest one-liners that mention ``git status`` stay honest."""
    g = base.GitArchaeologyGuard(cwd=tmp_path)
    for cmd in (
        "python -c \"import subprocess; subprocess.run(['git','log','-p'])\"",
        "python3 -c \"import os; os.system('git show HEAD~1')\"",
        "python -c \"import subprocess; subprocess.run(['git', 'diff', 'HEAD~1'])\"",
        "python -c \"import subprocess; subprocess.run(['git', 'diff', 'main'])\"",
        "python -c \"print(open('.git/HEAD').read())\"",
        'python -cimport\\ os\\;os.system\\(\\"git\\ log\\"\\)',
        "node -e \"require('child_process').execSync('git stash list')\"",
        "node --eval=\"require('child_process').execSync('git blame x')\"",
        "node -p \"require('fs').readFileSync('.git/HEAD')\"",
        "ruby -e 'system(\"git log -1\")'",
        "perl -e 'system(\"git reflog\")'",
        "php -r 'system(\"git show HEAD~1\");'",
        "python - <<'EOF'\nimport subprocess\nsubprocess.run(['git', 'log'])\nEOF",
        "node - <<'EOF'\nrequire('child_process').execSync('git reflog')\nEOF",
    ):
        assert g.check_shell(cmd).startswith("archaeology: inline"), cmd
    for cmd in (
        "python -c \"import subprocess; subprocess.run(['git','fetch'])\"",
        "python -c \"import subprocess; subprocess.run(['curl','https://x'])\"",
        "node -e \"require('child_process').execSync('gh pr view 1')\"",
    ):
        assert g.check_shell(cmd).startswith("network: inline"), cmd
    for cmd in (
        "python -c \"import subprocess; subprocess.run(['git', 'status', '--short'])\"",
        "python -c \"import subprocess; print(subprocess.check_output(['git','diff','--stat']))\"",
        "python -c \"import subprocess; subprocess.run(['git', 'diff', 'HEAD', '--', 'src'])\"",
        "python -c \"print(open('.gitignore').read())\"",
        "python -c \"import logging; logging.basicConfig(); print('log')\"",
        'python -c "import click; print(click.__file__)"',
        "python -m pytest -c pytest.ini -q",  # -m: never inline code
        "python script.py -c config.toml",  # a script's own -c is not python's
        "node -e \"console.log(require('child_process').execSync('git status').toString())\"",
        "node -p \"require('fs').readFileSync('.gitignore', 'utf8').length\"",
        "python - <<'EOF'\nimport subprocess\nsubprocess.run(['git', 'status'])\nEOF",
        "perl -e 'print \"hello\\n\"'",
    ):
        assert g.check_shell(cmd) == "", cmd


def test_guard_git_env_redirect_and_parallel() -> None:
    g = base.GitArchaeologyGuard()
    for cmd in (
        "GIT_DIR=/x/.git git diff HEAD",
        "GIT_DIR=/x git status",
        "GIT_WORK_TREE=/tmp/x git status",
        "GIT_OBJECT_DIRECTORY=/x/objects git diff",
        "export GIT_DIR=/x",
        "env GIT_DIR=/x git status",
        "git -c core.worktree=/x status",
        "parallel git log ::: a b",
    ):
        assert g.check_shell(cmd).startswith("archaeology:"), cmd
    assert "network" in g.check_shell("parallel -j2 curl ::: https://a https://b")
    assert g.check_shell("GIT_PAGER=cat git diff") == ""
    assert g.check_shell("export GIT_PAGER=cat; git diff --stat") == ""
    assert g.check_shell("parallel -j4 go vet ::: ./pkg ./cmd") == ""
