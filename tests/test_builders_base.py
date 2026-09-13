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
