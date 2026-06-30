"""Assess whether we can reliably manufacture changes on an EXISTING repo.

Answers the operator's question — *"what do we need to know to reliably replicate
commits and update working code on this repo?"* — by reading its real git history.

The key insight: a repo's **own test suite is the held-out oracle**, and its
**historical commits are ground truth**. So "can we manufacture here?" is
measurable: a commit that touches BOTH source and tests is **verifiable** — we can
replay it (revert the source, regenerate against the commit's tests, require
RED-on-base → GREEN-on-patch). A commit that touches source but no test is
**generatable but not auto-verifiable** → it routes to Q2 (human review). That
verifiable fraction is the ceiling on this repo's auto-Q1 envelope.

Complexity is sized from **diff churn** (lines changed + files) — for a commit the
churn is a far stronger signal than the terse message. Calibration is cheap
(~$1.2–1.8/cell at n=20 for unit-test code, measured); the real cost of
manufacturability is the repo's *test coverage*, not inference.

Pure analysis: git history in, an assessment out. No LLM, no cost, no mutation.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass

#: measured $/cell to calibrate a unit-test code cell at n=20 (this repo's runs).
CELL_COST_LO, CELL_COST_HI = 1.2, 1.8
_SIZES = ("XS", "S", "M", "L", "XL")


def file_kind(path: str) -> str:
    """Classify a path as src / test / docs / config / other (repo-agnostic)."""
    fl = path.lower()
    if re.search(r"(^|/)tests?/", fl) or "/test_" in fl or fl.startswith("test_"):
        return "test"
    if fl.startswith("docs/") or fl.endswith((".rst", ".md")):
        return "docs"
    if fl.endswith((".toml", ".cfg", ".ini", ".yaml", ".yml")) or fl.startswith(".github/") or "setup" in fl:
        return "config"
    if fl.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".cs", ".rb")):
        return "src"
    return "other"


def churn_tier(loc: int, n_src_files: int) -> str:
    """Complexity tier from diff churn (tunable). Churn is the commit's real size
    signal — a one-line message is not."""
    if loc <= 10 and n_src_files <= 1:
        return "XS"
    if loc <= 40:
        return "S"
    if loc <= 120:
        return "M"
    if loc <= 300:
        return "L"
    return "XL"


@dataclass(frozen=True)
class CommitAssessment:
    subject: str
    has_src: bool
    has_test: bool
    src_loc: int
    complexity: str | None  # churn tier of the source change, None if no source

    @property
    def verifiable(self) -> bool:
        """Replayable with an oracle: touches source AND a test."""
        return self.has_src and self.has_test


@dataclass(frozen=True)
class RepoManufacturability:
    n_commits: int
    code_commits: int
    verifiable_commits: int
    unverifiable_commits: int
    noncode_commits: int
    complexity_dist: dict[str, int]  # verifiable commits by complexity tier
    cells: list[str]                 # distinct tiers to calibrate
    cost_lo: float
    cost_hi: float
    #: OPTIONAL coupling to the deterministic (class × size) change histogram
    #: (an optional repo-change-profile add-on). Default ``None``
    #: so the existing return contract is unchanged — populated only when
    #: :func:`assess_repo` is called with ``with_change_profile=True``. When present
    #: it carries, for the repo's ACTUAL change distribution, which (class × size)
    #: cells the factory would exercise (``repo_change_profile.RepoChangeProfile.to_dict``).
    change_profile: dict | None = None

    @property
    def verifiable_pct(self) -> float:
        return round(100 * self.verifiable_commits / self.n_commits, 1) if self.n_commits else 0.0

    @property
    def verifiable_pct_of_code(self) -> float:
        return round(100 * self.verifiable_commits / self.code_commits, 1) if self.code_commits else 0.0

    def to_dict(self) -> dict:
        out = {
            "n_commits": self.n_commits, "code_commits": self.code_commits,
            "verifiable_commits": self.verifiable_commits,
            "unverifiable_commits": self.unverifiable_commits,
            "noncode_commits": self.noncode_commits,
            "verifiable_pct": self.verifiable_pct,
            "verifiable_pct_of_code": self.verifiable_pct_of_code,
            "complexity_dist": dict(self.complexity_dist),
            "cells": list(self.cells), "cost_lo": self.cost_lo, "cost_hi": self.cost_hi,
        }
        if self.change_profile is not None:
            out["change_profile"] = self.change_profile
        return out


def assess_commit(subject: str, files: list[tuple[str, int]]) -> CommitAssessment:
    """Assess one commit from its (path, lines_changed) list."""
    kinds = {file_kind(f) for f, _ in files}
    src = [(f, n) for f, n in files if file_kind(f) == "src"]
    has_src = bool(src)
    loc = sum(n for _, n in src)
    cx = churn_tier(loc, len(src)) if has_src else None
    return CommitAssessment(subject, has_src, "test" in kinds, loc, cx)


def assess_commits(commits: Iterable[CommitAssessment]) -> RepoManufacturability:
    """Aggregate per-commit assessments into a repo manufacturability verdict."""
    commits = list(commits)
    n = len(commits)
    code = [c for c in commits if c.has_src]
    verif = [c for c in code if c.verifiable]
    dist: dict[str, int] = {}
    for c in verif:
        dist[c.complexity] = dist.get(c.complexity, 0) + 1
    cells = [t for t in _SIZES if dist.get(t)]
    return RepoManufacturability(
        n_commits=n, code_commits=len(code), verifiable_commits=len(verif),
        unverifiable_commits=len(code) - len(verif), noncode_commits=n - len(code),
        complexity_dist=dist, cells=cells,
        cost_lo=round(len(cells) * CELL_COST_LO, 1), cost_hi=round(len(cells) * CELL_COST_HI, 1),
    )


def _read_commits(repo_path: str, max_commits: int) -> list[CommitAssessment]:
    raw = subprocess.run(
        ["git", "-C", repo_path, "log", "--no-merges", f"-{max_commits}",
         "--numstat", "--pretty=format:@@@%s"],
        capture_output=True, text=True, check=True,
    ).stdout
    out: list[CommitAssessment] = []
    subj = None
    files: list[tuple[str, int]] = []
    for line in raw.splitlines():
        if line.startswith("@@@"):
            if subj is not None:
                out.append(assess_commit(subj, files))
            subj, files = line[3:], []
        elif line.strip() and subj is not None:
            p = line.split("\t")
            if len(p) == 3:
                add = int(p[0]) if p[0].isdigit() else 0
                rem = int(p[1]) if p[1].isdigit() else 0
                files.append((p[2], add + rem))
    if subj is not None:
        out.append(assess_commit(subj, files))
    return out


def attach_change_profile(
    m: RepoManufacturability, profile: object
) -> RepoManufacturability:
    """Return a copy of ``m`` with the deterministic (class × size) change histogram
    coupled in (``change_profile``), leaving every existing field untouched.

    ``profile`` is a :class:`repo_change_profile.RepoChangeProfile` (or anything with a
    ``to_dict()`` — or a plain dict). This is the pure coupling primitive:
    :func:`assess_repo` calls it when ``with_change_profile=True``; tests can call it
    with a tiny fake profile. The existing return contract is preserved — every prior
    field is copied verbatim and only the new optional ``change_profile`` slot is filled.
    """
    prof = profile.to_dict() if hasattr(profile, "to_dict") else profile
    return RepoManufacturability(
        n_commits=m.n_commits, code_commits=m.code_commits,
        verifiable_commits=m.verifiable_commits,
        unverifiable_commits=m.unverifiable_commits,
        noncode_commits=m.noncode_commits,
        complexity_dist=dict(m.complexity_dist), cells=list(m.cells),
        cost_lo=m.cost_lo, cost_hi=m.cost_hi,
        change_profile=prof,
    )


def assess_repo(
    repo_path: str,
    *,
    max_commits: int = 500,
    with_change_profile: bool = False,
) -> RepoManufacturability:
    """Read ``repo_path``'s git history and assess its manufacturability.

    When ``with_change_profile=True`` the result additionally carries the repo's
    deterministic (class × size) change histogram (:func:`repo_change_profile.profile_repo`),
    coupling the actual change distribution to the manufacturability verdict — i.e.
    which (class × complexity) cells this repo's real changes would exercise. This is
    PURELY ADDITIVE (the default ``False`` path is byte-identical to before) and stays
    deterministic/cost-free: no LLM, no network.
    """
    m = assess_commits(_read_commits(repo_path, max_commits))
    if not with_change_profile:
        return m
    try:
        from .repo_change_profile import profile_repo  # optional add-on, omitted from the OSS core
    except Exception:
        return None  # histogram add-on not bundled; core assessment is unaffected

    return attach_change_profile(m, profile_repo(repo_path, max_commits=max_commits))


def format_assessment(m: RepoManufacturability, *, name: str = "repo") -> str:
    lines = [
        f"# Manufacturability — {name} (last {m.n_commits} non-merge commits)",
        "",
        f"- code commits: {m.code_commits} ({100 * m.code_commits // m.n_commits if m.n_commits else 0}%)",
        f"- VERIFIABLE (src+test → replayable w/ oracle): {m.verifiable_commits} "
        f"= {m.verifiable_pct}% of all, {m.verifiable_pct_of_code}% of code  ← auto-Q1 eligible",
        f"- unverifiable code (no test): {m.unverifiable_commits} → routes to Q2 (the ceiling)",
        f"- non-code (docs/test/config): {m.noncode_commits}",
        "",
        "## Verifiable code commits by complexity (cells to calibrate)",
    ]
    for t in _SIZES:
        if m.complexity_dist.get(t):
            lines.append(f"- code-change/{t}: {m.complexity_dist[t]} commits")
    lines.append("")
    lines.append(
        f"Calibrate {len(m.cells)} cells (~${m.cost_lo:.0f}–{m.cost_hi:.0f}, n=20 each; "
        f"held-out oracle = each commit's own tests). Real ceiling: the "
        f"{100 - int(m.verifiable_pct_of_code)}% of code commits without tests."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    import argparse

    ap = argparse.ArgumentParser(description="Assess a repo's manufacturability from git history")
    ap.add_argument("repo_path")
    ap.add_argument("--max-commits", type=int, default=500)
    ap.add_argument("--name", default=None)
    args = ap.parse_args(argv)
    m = assess_repo(args.repo_path, max_commits=args.max_commits)
    print(format_assessment(m, name=args.name or args.repo_path))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
