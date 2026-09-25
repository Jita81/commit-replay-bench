"""The public pages say what the code does — the summary, the mining rule, the loop, the changelog.

Navigation
----------
What it is:   Drift tests between the public documentation and the behaviour it describes.
What it does: Pins that docs/SUMMARY.md exists, fits two pages, answers the six questions an
              assurance reader asks, states the two gaps the current evidence carries (no row
              on the sealed posture; ``deliver`` routes granted without a measured oracle
              strength) and is on the claims gate's allowlist; that README's "Start here"
              opens with it and sends nobody to an external artifact; that the mining rule
              README step 1 and EVIDENCE-AND-CLAIMS §6b state — the newest N non-merge
              commits, the stop after T tasks or C candidates, the standard pool's caps — is
              the rule ``crb.core.mine`` runs, and is tagged ``[hypothesis]`` where it says
              what the rule leaves out; that README's "What the product is" says the loop
              proposes and a named person acts, for as long as ``crb.core.learn`` has no path
              that accepts, registers or queues; and that the changelog's Unreleased section
              is one paragraph per pull request with the narrative in a dated wave report.
How:          Reads the Markdown as text; reads the mining defaults by running
              ``iter_candidates`` and ``mine`` against a fake repository and a patched
              ``qualify``, so no git, no sandbox and no model is involved.
Layer:        tests — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         none
Works with:   docs/SUMMARY.md (the customer summary), README.md (Start here, step 1, "What the
              product is"), docs/EVIDENCE-AND-CLAIMS.md (§6b, the domain of validity),
              src/crb/core/mine.py (the selection rule the pages state), src/crb/core/learn.py
              (the derivations the loop sentence describes), CHANGELOG.md (the frozen shape),
              scripts/claims_check.py (the allowlist the summary joins)
Tested by:    (this is a test file)
Touch when:   the miner's defaults change (update README step 1 and EVIDENCE-AND-CLAIMS §6b in
              the same change); ``crb.core.learn`` gains a path that acts (rewrite README's
              "What the product is" and this test together); a pull request adds its
              changelog paragraph.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

import crb.core.learn as learn
import crb.core.mine as mine_mod
from crb.core.spec import Language, RepoConfig

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
SUMMARY = ROOT / "docs" / "SUMMARY.md"
EVIDENCE = (ROOT / "docs" / "EVIDENCE-AND-CLAIMS.md").read_text(encoding="utf-8")
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """The body under the first heading that starts with ``heading``, up to the next heading
    of the same or a higher level."""
    m = re.search(rf"^(#+) {re.escape(heading)}.*$", text, re.M)
    assert m, f"no heading {heading!r}"
    level = len(m.group(1))
    rest = text[m.end() :]
    end = re.search(rf"^#{{1,{level}}} ", rest, re.M)
    return rest[: end.start()] if end else rest


def _claims_check() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "claims_check", ROOT / "scripts" / "claims_check.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["claims_check"] = mod
    spec.loader.exec_module(mod)
    return mod


# ─── E4: the two-page summary, first in "Start here" ─────────────────────────────────────


def test_the_summary_answers_an_assurance_reader_in_two_pages() -> None:
    assert SUMMARY.is_file(), "docs/SUMMARY.md is missing"
    text = SUMMARY.read_text(encoding="utf-8")
    words = len(re.findall(r"\w+", text))
    assert words <= 1500, f"{words} words is more than two pages"
    headings = [h.lower() for h in re.findall(r"^## (.+)$", text, re.M)]
    for question in (
        "what it is",
        "what it measures",
        "what it refuses to claim",
        "what it costs to onboard",
        "what the current evidence licenses",
        "open gaps",
    ):
        assert any(h.startswith(question) for h in headings), (question, headings)


def test_the_summary_states_the_two_gaps_the_evidence_carries() -> None:
    text = SUMMARY.read_text(encoding="utf-8")
    flat = " ".join(text.split())
    # no row has been measured on the sealed posture (assessment B3)
    assert re.search(r"no (ledger )?row .{0,80}sealed posture", flat, re.I), "sealed-posture gap"
    # deliver routes were granted without a measured oracle strength (assessment A2)
    assert re.search(r"deliver.{0,200}without a measured oracle strength", flat, re.I), "A2 gap"
    assert "[gap]" in text


def test_the_summary_is_on_the_claims_gate() -> None:
    assert "docs/SUMMARY.md" in _claims_check().ALLOWLIST


def test_start_here_opens_with_the_summary_and_sends_nobody_off_site() -> None:
    start = _section(README, "Start here")
    rows = [r for r in start.splitlines() if r.startswith("| **")]
    assert rows, "no rows in Start here"
    assert "docs/SUMMARY.md" in rows[0], rows[0]
    assert "claude.ai" not in start


# ─── B4: the mining rule is stated, and it is the rule the miner runs ────────────────────


class _FakeRepo:
    def __init__(self) -> None:
        self.n: int | None = None
        self.no_merges: bool | None = None

    def log_shas(self, n: int, *, ref: str = "HEAD", no_merges: bool = True) -> list[str]:
        self.n, self.no_merges = n, no_merges
        return []


def _stops(monkeypatch: pytest.MonkeyPatch, *, found: bool) -> int:
    """How many candidates ``mine`` qualifies before it stops, when each one is (or is not)
    a task — the defaults, read from the running code."""

    def candidates(*_a: Any, **_k: Any) -> Iterator[mine_mod.Candidate]:
        i = 0
        while True:
            i += 1
            yield mine_mod.Candidate(f"{i:040x}", ("a.py",), ("a.py",), ("test_a.py",))

    def qualify(_repo: Any, _config: Any, cand: mine_mod.Candidate, **_k: Any) -> Any:
        task: Any = object() if found else None
        return mine_mod.MineOutcome(cand.sha, task, "" if found else "x")

    monkeypatch.setattr(mine_mod, "iter_candidates", candidates)
    monkeypatch.setattr(mine_mod, "qualify", qualify)
    config = RepoConfig(name="p", language=Language.PYTHON)
    unused: Any = None  # qualify is patched: no git, no runner, no sandbox is touched
    outcomes = mine_mod.mine(unused, config, runner=unused, executor=unused, scratch=ROOT)
    return sum(1 for _ in outcomes)


def _walk_and_caps() -> tuple[int, mine_mod.PoolCaps]:
    """The history window ``iter_candidates`` asks git for, and the standard pool's caps."""
    repo: Any = _FakeRepo()
    config = RepoConfig(name="p", language=Language.PYTHON)
    list(mine_mod.iter_candidates(repo, config))
    assert repo.no_merges is True
    assert repo.n is not None
    return int(repo.n), mine_mod.pool_caps(config, mine_mod.POOL_STANDARD)


def test_the_stated_mining_rule_is_the_rule_the_miner_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    log_n, caps = _walk_and_caps()
    target = _stops(monkeypatch, found=True)
    cap = _stops(monkeypatch, found=False)
    step1 = " ".join(_section(README, "The instrument in six steps").split())
    s6b = " ".join(_section(EVIDENCE, "6b.").split())
    for where, text in (("README step 1", step1), ("EVIDENCE-AND-CLAIMS §6b", s6b)):
        assert f"newest {log_n:,} non-merge commits" in text, where
        assert f"{target} tasks" in text, where
        assert f"{cap:,} candidates" in text, where
        assert f"{caps.src_min}\u2013{caps.src_max} source files" in text, where
        assert "[hypothesis" in text, where


def test_the_selection_rule_names_what_it_leaves_out() -> None:
    step1 = " ".join(_section(README, "The instrument in six steps").split()).lower()
    for excluded in ("merge", "older", "without a test"):
        assert excluded in step1, excluded


# ─── C7: the loop proposes; a named person acts ──────────────────────────────────────────

#: The three write paths the assessment's G-532 names: accept a refusal line, register a
#: strengthening item, queue a re-measurement. None exists in crb.core.learn today.
ACTUATOR_PREFIXES = ("accept", "register", "queue", "enqueue", "submit", "schedule")


def test_readme_says_the_loop_proposes_while_learn_has_no_actuator() -> None:
    actuators = [
        name
        for name in dir(learn)
        if not name.startswith("_")
        and callable(getattr(learn, name))
        and name.lower().startswith(ACTUATOR_PREFIXES)
    ]
    assert actuators == [], (
        "crb.core.learn now acts — rewrite README 'What the product is' and this test together"
    )
    m = re.search(r"\*\*What the product is\*\*.*?(?=\n\n)", README, re.S)
    assert m, "README has no 'What the product is' paragraph"
    para = " ".join(m.group(0).split())
    assert "proposes" in para and "named person" in para, para
    assert "turns every refusal, review and re-measurement back into" not in para


# ─── E4: the changelog grows by one paragraph per pull request ───────────────────────────

PR_LINK = "https://github.com/Jita81/commit-replay-bench/pull"
MAX_WORDS = 120


def test_unreleased_is_one_paragraph_per_pull_request() -> None:
    unreleased = CHANGELOG.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]
    assert not re.search(r"^###", unreleased, re.M), "Unreleased carries a narrative heading"
    blocks = [b.strip() for b in re.split(r"\n\s*\n", unreleased) if b.strip()]
    intro, *entries = blocks
    assert "docs/reviews/" in intro, "the intro must point at the dated wave report"
    assert entries, "no entries"
    for entry in entries:
        assert entry.startswith("- "), entry[:80]
        assert "\n- " not in entry and "\n  - " not in entry, f"nested list: {entry[:80]}"
        assert PR_LINK in entry, f"no pull request link: {entry[:80]}"
        words = len(entry.split())
        assert words <= MAX_WORDS, f"{words} words: {entry[:80]}"


def test_the_moved_narrative_is_a_dated_wave_report() -> None:
    reports = sorted((ROOT / "docs" / "reviews").glob("*-wave-report*.md"))
    assert reports, "no dated wave report under docs/reviews/"
    text = reports[-1].read_text(encoding="utf-8")
    # the first and the last narrative sections the Unreleased block carried before the freeze
    assert "what the product writes on somebody else's ticket is counted" in text
    assert "the front end has a purpose: connect → results → decisions → factory" in text
