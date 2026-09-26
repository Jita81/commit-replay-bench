"""The format step — the repository's OWN formatter over the changed source files, after
the builder and before the grade, so the graded patch is the formatted one.

Why
---
A formatter finding is the cheapest defect a reviewer can find and the most mechanical to
remove: one of three reviewed clean cobra patches failed ``gofmt -l``, and four of thirteen
reviewed clean patches were not mergeable for style or lint alone **[measured — n = 13
reviewed clean patches, method: human review records (the review store + the cobra
critical-friend review), apparatus 2.2]**. Asking a model to format by hand is advisory; the
repository's own formatter applied by the harness is correct by construction.

Rules
-----
* **Only the repository's formatter.** The formatters are the belt-5 plan's formatter steps
  (``gofmt``, ``ruff format``, ``black``, ``prettier``, ``standard``, ``cargo fmt`` —
  whatever the repository's own configuration evidences, :mod:`crb.core.lint`), black when
  the repository configures it and the plan could not resolve it, or the one it declares
  (``checks.formatter``). Never a formatter the repository does not
  use; when there is none the step is SKIPPED with a named reason, never guessed.
* **Only the changed source files.** Test files are the oracle's; unchanged files are the
  maintainers'.
* **Recorded.** What ran, which files it changed, or why it was skipped — on the row
  (``format_step`` label) and in the evidence pack; a formatter that fails leaves the file as
  it was and the record says so. The step never decides a verdict.

Navigation
----------
What it is:   The format step (``formatters_for`` → ``run_formatters`` → ``FormatRun``): which
              of the repository's own formatters apply, and running them in write mode over the
              changed non-test files.
What it does: Derives the formatters from the belt-5 plan, a black configuration or the
              declared ``checks.formatter``; runs each over the files with its extensions;
              records the files whose bytes changed; skips with a named reason when the
              repository configures no formatter. Never touches a test file.
How:          ``formatters_for(plan, root, declared)`` → ``(formatters, skip reason)`` →
              ``run_formatters`` hashes each file, runs ``Command``s through the executor with
              the worktree writable, hashes again → ``FormatRun.label``.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0021-working-by-construction.md, docs/adr/0011-repo-lint-belt.md
Works with:   src/crb/core/lint.py (the plan whose formatter steps are reused),
              src/crb/core/checks.py (the ``format_step`` switch and ``checks.formatter``),
              src/crb/builders/adapter.py (runs the step after the build),
              src/crb/core/execution.py (Command / Executor)
Tested by:    tests/test_formatting.py
Touch when:   onboarding a repository whose formatter the detectors miss — declare it under
              ``checks.formatter`` (docs/OPERATOR.md) before adding a detector here; a new
              formatter entry needs a fixture test with the real tool in tests/test_formatting.py.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crb.core.execution import Command, Executor
from crb.core.lint import PRETTIER_CONFIGS, LintPlan

#: The belt-5 tools that are FORMATTERS, and how each is spelt in write mode (appended to
#: the plan's own binary so the version is the one belt 5 applies). Linters with a fix
#: mode (``ruff check --fix``, ``eslint --fix``) are deliberately absent: a lint fix can
#: change behaviour; a formatter cannot.
FORMATTER_WRITE: dict[str, tuple[str, ...]] = {
    "gofmt": ("-w",),
    "ruff-format": ("format", "-q"),
    "prettier": ("--write", "--log-level=warn"),
    "cargo-fmt": ("fmt", "--"),
    "black": ("-q",),
    # koa formats with ``standard`` and nothing else — its own ``lint:fix`` script is
    # ``standard --fix``; standard's fixable rules are layout rules
    "standard": ("--fix",),
}

SKIP_DISABLED = "disabled"
SKIP_NO_FILES = "no_changed_source_files"
SKIP_NOT_CONFIGURED = "no_formatter_configured"
SKIP_NOT_INSTALLED = "formatter_not_installed"
#: The plan refuses the tool (a binary outside the repository's pin): never run it.
SKIP_REFUSED = "formatter_refused"
#: A formatter that cannot be held to the changed files — ``cargo fmt`` formats the whole
#: crate, test targets included — is skipped by name until a file-scoped call is built.
SKIP_NOT_FILE_SCOPED = "formatter_not_file_scoped"
NOT_FILE_SCOPED: frozenset[str] = frozenset({"cargo-fmt"})

DEFAULT_FORMAT_TIMEOUT_S = 300

_PRECOMMIT_BLACK = re.compile(r"^\s*-\s*id:\s*black(?:-jupyter)?\s*$", re.M)


@dataclass(frozen=True)
class Formatter:
    """One formatter in write mode: ``argv`` + the files with one of ``exts``."""

    name: str
    argv: tuple[str, ...]
    exts: tuple[str, ...] = ()

    def files_for(self, files: Sequence[str]) -> list[str]:
        return [f for f in files if not self.exts or f.endswith(self.exts)]


@dataclass(frozen=True)
class FormatRun:
    """What the step did. ``ran`` names the formatters that ran; ``changed`` the files
    whose bytes they changed; ``skipped`` the named reason nothing ran; ``errors`` a
    formatter that failed (its file left as the builder wrote it)."""

    ran: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()
    skipped: str = ""
    errors: tuple[str, ...] = ()

    def label(self) -> str:
        """``ran=gofmt;changed=2`` / ``skipped=no_formatter_configured`` (the row label)."""
        if self.skipped:
            return f"skipped={self.skipped}"
        parts = [f"ran={'+'.join(self.ran)}", f"changed={len(self.changed)}"]
        if self.errors:
            parts.append("errors=" + "+".join(self.errors))
        return ";".join(parts)[:200]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ran": list(self.ran),
            "changed": list(self.changed),
            "skipped": self.skipped,
            "errors": list(self.errors),
        }


def black_configured(root: Path) -> bool:
    """Does the repository configure black? ``[tool.black]`` in ``pyproject.toml`` or a
    ``black`` pre-commit hook."""
    root = Path(root)
    try:
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    tool = data.get("tool") if isinstance(data.get("tool"), dict) else {}
    if isinstance(tool, dict) and isinstance(tool.get("black"), dict):
        return True
    try:
        pc = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return _PRECOMMIT_BLACK.search(pc) is not None


def prettier_configured(root: Path) -> bool:
    """A prettier configuration file, or a ``prettier`` key in ``package.json``."""
    root = Path(root)
    if any((root / c).is_file() for c in PRETTIER_CONFIGS):
        return True
    try:
        pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(pkg, dict) and pkg.get("prettier") is not None


def formatters_for(
    plan: LintPlan | None,
    root: Path,
    declared: Mapping[str, Any] | None = None,
    *,
    black: str | None = None,
) -> tuple[list[Formatter], str]:
    """``(formatters, skip reason)`` for the repository at ``root``.

    ``declared`` (``checks.formatter``) wins: ``{disabled: true}`` → skipped
    ``disabled``; ``{command, exts}`` → that formatter. Else the plan's formatter steps,
    then black when configured (``black`` is the resolved binary; ``None`` → looked up on
    PATH). Nothing → ``no_formatter_configured``; configured but no binary →
    ``formatter_not_installed:<name>``."""
    decl = dict(declared or {})
    if decl.get("disabled"):
        return [], SKIP_DISABLED
    if decl.get("command"):
        argv = tuple(str(a) for a in decl["command"])
        exts = tuple(str(e) for e in (decl.get("exts") or ()))
        return [Formatter(str(decl.get("name") or "declared"), argv, exts)], ""
    out: list[Formatter] = []
    held: list[str] = []
    if plan is not None:
        for tool in plan.tools:
            write = FORMATTER_WRITE.get(tool.name)
            if write is None:
                continue
            if tool.refuse:
                # the same binary belt 5 refuses to judge with (docs/PREVENTION.md P-031)
                held.append(f"{SKIP_REFUSED}:{tool.name}")
                continue
            if tool.name in NOT_FILE_SCOPED:
                held.append(f"{SKIP_NOT_FILE_SCOPED}:{tool.name}")
                continue
            binary = tool.argv[0]
            out.append(Formatter(tool.name, (binary, *write), tool.exts))
    has_py_formatter = any(f.name in ("ruff-format", "black") for f in out) or any(
        h.endswith(":ruff-format") for h in held
    )
    if not has_py_formatter and black_configured(root):
        black_bin = black or shutil.which("black")
        if not black_bin:
            return out, "" if out else f"{SKIP_NOT_INSTALLED}:black"
        out.append(Formatter("black", (black_bin, "-q"), (".py", ".pyi")))
    if not out and held:
        return [], "+".join(held)[:120]
    if not out and prettier_configured(root):
        # configured but the plan could not resolve the binary (no node_modules/.bin)
        return [], f"{SKIP_NOT_INSTALLED}:prettier"
    if not out:
        return [], SKIP_NOT_CONFIGURED
    return out, ""


def _digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def run_formatters(
    formatters: Sequence[Formatter],
    executor: Executor,
    root: Path,
    files: Sequence[str],
    *,
    skipped: str = "",
    timeout: int = DEFAULT_FORMAT_TIMEOUT_S,
) -> FormatRun:
    """Run each formatter in write mode over its share of ``files`` (the changed non-test
    files that exist) and report which files changed. Never raises: a launch error or a
    non-zero exit is recorded in ``errors`` and the next formatter still runs."""
    if skipped:
        return FormatRun(skipped=skipped)
    root = Path(root)
    present = [f for f in files if (root / f).is_file()]
    if not present:
        return FormatRun(skipped=SKIP_NO_FILES)
    if not formatters:
        return FormatRun(skipped=SKIP_NOT_CONFIGURED)
    before = {f: _digest(root / f) for f in present}
    ran: list[str] = []
    errors: list[str] = []
    for fmt in formatters:
        mine = fmt.files_for(present)
        if not mine:
            continue
        ran.append(fmt.name)
        try:
            res = executor.run(
                Command((*fmt.argv, *mine), root, timeout=timeout, writable_paths=(".",))
            )
        except OSError as exc:
            errors.append(f"{fmt.name}:{type(exc).__name__}")
            continue
        if res.timed_out or res.returncode != 0:
            errors.append(f"{fmt.name}:rc={124 if res.timed_out else res.returncode}")
    if not ran:
        return FormatRun(skipped=SKIP_NOT_CONFIGURED)
    changed = tuple(f for f in present if _digest(root / f) != before[f])
    return FormatRun(tuple(ran), changed, "", tuple(errors))


__all__ = [
    "FORMATTER_WRITE",
    "SKIP_DISABLED",
    "SKIP_NOT_CONFIGURED",
    "SKIP_NOT_FILE_SCOPED",
    "SKIP_NOT_INSTALLED",
    "SKIP_NO_FILES",
    "SKIP_REFUSED",
    "FormatRun",
    "Formatter",
    "black_configured",
    "formatters_for",
    "prettier_configured",
    "run_formatters",
]
