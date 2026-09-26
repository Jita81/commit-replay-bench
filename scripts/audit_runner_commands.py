#!/usr/bin/env python3
"""Audit what the runners produce for a repository against what the repository itself runs.

A clean row is only as good as the checks behind it: if the repository's CI runs a tool the
runner never derives, a patch the reviewer would reject can grade clean. This script reads a
checkout and prints, side by side:

* what the product derives — the belt-5 plan (``detected`` and every step's argv), the format
  step's formatters (or its named skip reason), the finish gate's derived commands, the test
  harness command without a scope;
* what the repository evidences — every line of its CI workflows, Makefile, ``package.json``
  scripts, ``tox`` / ``pyproject`` and pre-commit hooks that names a known check tool;
* the gaps — a tool the evidence names that no derived step covers.

It runs offline and executes nothing but ``<tool> --version`` probes the detectors already
make; it never installs anything and never touches a network.

    python scripts/audit_runner_commands.py <checkout> --language go [--runner go] [--json]

Navigation
----------
What it is:   The runner-command audit: derived checks versus the repository's own CI evidence,
              for one checkout.
What it does: Builds the ``RepoConfig`` for the checkout, asks the runner for its belt-5 plan,
              the format step for its formatters, the finish gate for its derived commands and
              the runner for its harness command; greps the repository's CI evidence for known
              tools; prints both and the tools the evidence names that nothing derived covers.
How:          ``get_runner(RepoConfig)`` → ``lint_plan`` / ``formatters_for`` /
              ``derived_commands`` / ``command(root, BARE)``; a regex per tool over the
              evidence files; a coverage table from tool → the step names that cover it.
Layer:        deploy — docs/ARCHITECTURE.md#7-cross-cutting-concepts
ADRs:         docs/adr/0024-working-by-construction.md, docs/adr/0011-repo-lint-belt.md
Works with:   src/crb/core/lint.py (the belt-5 detectors), src/crb/core/formatting.py (the format
              step), src/crb/core/finish_gate.py (derived commands), src/crb/core/runners/base.py
              (the harness command), docs/reviews/2026-09-25-runner-commands-audit.md (its output
              on the six live repositories)
Tested by:    tests/test_runner_audit.py
Touch when:   a runner or detector learns a new tool — add the tool's evidence pattern and the
              step names that cover it to ``TOOLS`` so the audit stops calling it a gap.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from crb.core.execution import LocalExecutor
from crb.core.finish_gate import derived_commands
from crb.core.formatting import formatters_for
from crb.core.runners import get_runner
from crb.core.runners.base import BARE
from crb.core.spec import Language, RepoConfig

#: tool → (evidence pattern, the plan/format/gate step names that cover it)
TOOLS: dict[str, tuple[str, tuple[str, ...]]] = {
    "gofmt": (r"\bgofmt\b|-\s*gofmt\b", ("gofmt",)),
    "goimports": (r"\bgoimports\b", ("goimports",)),
    "go vet": (r"\bgo\s+vet\b|-\s*govet\b", ("vet",)),
    "golangci-lint": (r"golangci-lint|golangci/golangci-lint-action", ("golangci-lint",)),
    "staticcheck": (r"-\s*staticcheck\b|\bstaticcheck\s", ("staticcheck",)),
    "ruff check": (r"\bruff(?:-check)?\b(?!-format|\s+format)", ("ruff",)),
    "ruff format": (r"ruff-format|ruff\s+format", ("ruff-format",)),
    "black": (r"\bblack\b", ("black",)),
    "mypy": (r"\bmypy\b", ("mypy", "typing")),
    "pyright": (r"\bpyright\b", ("pyright", "typing")),
    "eslint": (r"\beslint\b", ("eslint",)),
    "prettier": (r"\bprettier\b", ("prettier",)),
    "stylelint": (r"\bstylelint\b", ("stylelint",)),
    "standard": (r"(?:^|[\s\"'])standard(?:\s|$|\")", ("standard",)),
    "tsc": (r"\btsc\b", ("tsc",)),
    "codespell": (r"\bcodespell\b", ("codespell",)),
}

_EVIDENCE_FILES: tuple[str, ...] = (
    "Makefile",
    "package.json",
    "pyproject.toml",
    "tox.ini",
    "setup.cfg",
    ".pre-commit-config.yaml",
    ".golangci.yml",
    ".golangci.yaml",
)


def evidence(root: Path) -> dict[str, list[str]]:
    """``{tool: [file:line …]}`` — where the repository's own configuration names a tool."""
    files = [root / f for f in _EVIDENCE_FILES if (root / f).is_file()]
    wf = root / ".github" / "workflows"
    if wf.is_dir():
        files += sorted(p for p in wf.iterdir() if p.suffix in {".yml", ".yaml"})
    found: dict[str, list[str]] = {}
    for p in files:
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            for tool, (pattern, _) in TOOLS.items():
                if re.search(pattern, line):
                    found.setdefault(tool, []).append(f"{p.relative_to(root)}:{n}")
    return found


class _Provisioned(LocalExecutor):
    """The sandbox's view (``--assume-installed``): a checkout whose dependencies are not
    installed here is read as the provisioned image reads it — tools by bare name."""

    name = "docker"

    def tool(self, name: str, host_override: str | None = None) -> str:
        return name


def derived(root: Path, config: RepoConfig, *, provisioned: bool = False) -> dict[str, Any]:
    """What the product derives for ``root`` under ``config`` (no network, nothing written)."""
    ex = _Provisioned() if provisioned else LocalExecutor()
    runner = get_runner(config)
    plan = runner.lint_plan(root, ex)
    formatters, skipped = formatters_for(plan, root, config.checks.get("formatter"))
    try:
        harness = " ".join(runner.command(root, BARE, executor=ex, timeout=60).argv)
    except Exception as exc:  # the audit reports it; it does not fail on it
        harness = f"<error: {type(exc).__name__}: {exc}>"
    return {
        "belt5": {
            "detected": plan.detected if plan else None,
            "steps": [
                {"name": t.name, "argv": list(t.argv), "refuse": t.refuse} for t in plan.tools
            ]
            if plan
            else [],
        },
        "format_step": {"formatters": [f.name for f in formatters], "skipped": skipped},
        "finish_gate_derived": [c.display for c in derived_commands(root)],
        "harness_command": harness,
    }


def gaps(ev: dict[str, list[str]], out: dict[str, Any]) -> list[str]:
    """Tools the evidence names that no derived step covers."""
    names = {s["name"] for s in out["belt5"]["steps"]}
    names |= set(out["format_step"]["formatters"])
    names |= {
        d.split()[1] if d.startswith("go ") else d.split()[0] for d in out["finish_gate_derived"]
    }
    return sorted(t for t in ev if not set(TOOLS[t][1]) & names)


def audit(
    root: Path, language: str, runner: str = "", *, provisioned: bool = False
) -> dict[str, Any]:
    cfg = RepoConfig(
        name=root.name.lower()[:64] or "repo", language=Language.parse(language), runner=runner
    )
    ev = evidence(root)
    out = derived(root, cfg, provisioned=provisioned)
    return {"repo": root.name, "derived": out, "evidence": ev, "gaps": gaps(ev, out)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("checkout", type=Path)
    ap.add_argument("--language", required=True)
    ap.add_argument("--runner", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--assume-installed",
        action="store_true",
        help="read the checkout as the provisioned sandbox would (tools by bare name)",
    )
    a = ap.parse_args(argv)
    report = audit(a.checkout.resolve(), a.language, a.runner, provisioned=a.assume_installed)
    if a.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    d = report["derived"]
    print(f"# {report['repo']}")
    print(f"belt 5:        {d['belt5']['detected']}")
    for s in d["belt5"]["steps"]:
        print(
            f"  - {s['name']}: {' '.join(s['argv'])}"
            + (f"  [REFUSED: {s['refuse']}]" if s["refuse"] else "")
        )
    print(f"format step:   {d['format_step']['formatters'] or d['format_step']['skipped']}")
    print(f"finish gate:   {d['finish_gate_derived'] or '-'}")
    print(f"harness:       {d['harness_command']}")
    print(f"evidence:      {', '.join(sorted(report['evidence'])) or '-'}")
    print(f"gaps:          {', '.join(report['gaps']) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
