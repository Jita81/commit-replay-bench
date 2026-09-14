"""Belt 5 — ``repo_lint_clean``: the repository's OWN formatter/linter accepts the
files the builder changed.

Why a fifth belt
----------------
The four mechanical belts say whether the held-out tests accept a patch. They do
not say whether the *repository* would: a "clean" cobra patch was rejected by
``gofmt -l`` — cobra's ``.golangci.yml`` enables ``gofmt`` and its CI runs
``golangci-lint`` on every PR — so the patch could never have merged
(``docs/reviews/2026-09-13-critical-friend.md`` §3.2, action #2). "Clean" must
also mean "the repo's own definition of acceptable formatting/lint holds on the
changed files". That definition is the repository's, never ours: belt 5 runs the
linter the repository configures, or nothing.

The honest asymmetry (``None`` ≠ pass ≠ fail)
---------------------------------------------
* A :class:`LintPlan` is **detected** from the repository's own configuration (per
  language: :func:`go_plan`, :func:`python_plan`, :func:`js_plan`, :func:`jvm_plan`,
  :func:`rust_plan`, reached through ``BaseRunner.detect_lint``) or **declared** by the
  operator (``RepoConfig.lint``). With neither, the belt is **not evaluated**:
  ``repo_lint_clean=None``, ``lint_run=None``. That is never a pass (the row does
  not claim the repo's lint holds) and never a fail (the row is not penalised for a
  repo that enforces nothing). The ledger records which belts a row evaluated;
  the capability map shows how many rows of a cell carried belt 5.
* ``True`` — every step of the plan accepted the changed files.
* ``False`` — a step rejected them (the tool ran and reported findings), or a step
  **timed out** (a timeout is a failure, as for belts 2 and 3).
* A step that could not run at all (binary missing, launch error, an exit code the
  tool reserves for its own abnormal termination) is a **harness error**: the belt
  is ``False`` and :attr:`LintRun.error` is set, so the grade carries ``error`` and
  the row's ``failure_kind`` is ``harness`` — the instrument, not the model.

Only the CHANGED NON-TEST files are linted (``paths="changed"``); a tool that can
only run repo-wide (``mvn spotless:check``, ``cargo clippy``) runs with
``paths="all"`` and is declared as such. Pre-existing lint debt in a changed file
counts against the patch exactly as the repository's CI would count it against
the PR; a task whose maintainers' own patch fails belt 5 is not a fair lint
observation and belongs to the gold check (see ADR-0011, follow-ups).

Whole-project tools with per-file findings (``tsc``)
----------------------------------------------------
``tsc`` has no per-file mode once a repository uses project references, so it runs
whole-project — and a whole-project run reports every pre-existing type error in
the tree, not only the patch's. A tool that declares ``findings_re`` (a pattern with
a ``file`` group over its output, e.g. tsc's ``file(line,col): error TSxxxx``) has
its rejection ATTRIBUTED: the step counts findings in CHANGED files against
findings elsewhere, and rejects only when a changed file is named
(``LintStep.findings_changed`` / ``findings_other`` record both). Findings only in
unchanged files are the maintainers' debt, recorded on the run's ``note`` and never
the builder's. A rejection whose findings name no file at all (a global ``error
TS5083`` and the like) cannot be attributed and is a harness error — never a pass.
Attribution is per FILE, not per line: a pre-existing error in a file the builder
touched still counts, exactly as the repository's CI would count it on the PR.

Everything here is standard-library only and decides nothing about ``clean`` —
:mod:`crb.core.grade` folds :attr:`LintRun.ok` into the belts.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crb.core.execution import Command, ExecResult, Executor
from crb.core.redact import redact_and_cap

#: Wall clock for one lint step when neither the config nor the plan says otherwise.
DEFAULT_LINT_TIMEOUT_S = 600

#: Cap on the redacted tail one lint step keeps in the result.
LINT_TAIL_CHARS = 4000

#: Cap on the number of changed files one step is handed (a larger patch is linted
#: in one call anyway; the cap bounds the argv, not the verdict).
MAX_LINT_FILES = 200

PATHS_CHANGED = "changed"
PATHS_ALL = "all"
PATHS_MODES: tuple[str, ...] = (PATHS_CHANGED, PATHS_ALL)

#: Exit codes a shell reserves for "could not execute" — never a lint verdict.
_NOT_RUNNABLE_RCS: frozenset[int] = frozenset({126, 127})
#: The exit code a timed-out :class:`~crb.core.execution.LocalExecutor` reports.
_TIMEOUT_RC = 124


# ---------------------------------------------------------------------------
# The plan: which tools, over which files, and how to read their exit
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LintTool:
    """One linter invocation and how its exit is read.

    ``findings_rcs`` are the exit codes that mean "the tool ran and rejected the
    input" (``ruff`` 1, ``eslint`` 1, ``prettier --check`` 1, ``cargo clippy`` 101…).
    ``stdout_is_findings`` covers ``gofmt -l``, which exits 0 and *lists* the files
    it would reformat. Any other non-zero exit is the tool's own failure
    (``ruff`` 2 = internal error, ``eslint`` 2 = config error, 126/127 = not
    runnable) and reads as a harness error, never as a verdict.

    ``unrunnable_re`` closes the one gap an exit code leaves: a wrapper that exits
    with a *findings* code when the tool itself is missing — a rustup proxy answers
    ``cargo fmt`` with rc 1 and ``'cargo-fmt' is not installed for the toolchain``
    ``[measured 2026-09-14]``, which would otherwise read as "the patch is not
    formatted". Output matching the pattern is a harness error whatever the rc.

    ``findings_re`` (a pattern with a named ``file`` group, matched per output line)
    makes a whole-project tool's rejection attributable to the CHANGED files — see
    the module docstring. With ``paths="all"`` and ``exts`` set, the step is skipped
    when no changed file has one of the extensions (a type checker has nothing to say
    about a patch that touched no source it checks).
    """

    name: str
    argv: tuple[str, ...]
    paths: str = PATHS_CHANGED
    exts: tuple[str, ...] = ()
    findings_rcs: frozenset[int] = frozenset({1})
    stdout_is_findings: bool = False
    env: Mapping[str, str] = field(default_factory=dict)
    writable_paths: tuple[str, ...] = ()
    unrunnable_re: str = ""
    findings_re: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("a LintTool needs a name")
        if not self.argv:
            raise ValueError(f"lint tool {self.name!r}: argv must not be empty")
        if self.paths not in PATHS_MODES:
            raise ValueError(f"lint tool {self.name!r}: paths must be one of {PATHS_MODES}")
        object.__setattr__(self, "argv", tuple(str(a) for a in self.argv))
        object.__setattr__(self, "exts", tuple(str(e) for e in self.exts))
        object.__setattr__(self, "findings_rcs", frozenset(int(r) for r in self.findings_rcs))
        object.__setattr__(self, "env", dict(self.env))
        object.__setattr__(self, "writable_paths", tuple(str(p) for p in self.writable_paths))
        re.compile(self.unrunnable_re)  # a bad pattern is a configuration error, not a verdict
        if self.findings_re and "file" not in re.compile(self.findings_re).groupindex:
            raise ValueError(f"lint tool {self.name!r}: findings_re needs a named group 'file'")

    def files_for(self, changed: Iterable[str]) -> tuple[str, ...]:
        """The changed files this tool is handed (``paths="changed"`` only)."""
        if self.paths == PATHS_ALL:
            return ()
        out = [f for f in changed if not self.exts or f.endswith(self.exts)]
        return tuple(out[:MAX_LINT_FILES])

    def concerns(self, changed: Iterable[str]) -> bool:
        """Does this step have anything to say about ``changed``? ``paths="changed"``:
        iff it is handed a file; ``paths="all"``: unless ``exts`` is set and no changed
        file has one of them."""
        if self.paths == PATHS_CHANGED:
            return bool(self.files_for(changed))
        return not self.exts or any(f.endswith(self.exts) for f in changed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "argv": list(self.argv),
            "paths": self.paths,
            "exts": list(self.exts),
            "findings_rcs": sorted(self.findings_rcs),
            "stdout_is_findings": self.stdout_is_findings,
            "unrunnable_re": self.unrunnable_re,
            "findings_re": self.findings_re,
        }


@dataclass(frozen=True)
class LintPlan:
    """The steps belt 5 runs, and where the plan came from.

    ``detected`` names the evidence (``"gofmt"``, ``"ruff+ruff-format"``,
    ``"eslint+prettier"``, ``"standard"``, ``"spotless+checkstyle"``,
    ``"cargo-fmt+clippy"``, or ``"config"`` for an operator-declared command). It is
    recorded on the result so a reader knows *which* definition of acceptable was
    applied. ``timeout`` is the per-step wall clock.
    """

    tools: tuple[LintTool, ...]
    detected: str
    timeout: int = DEFAULT_LINT_TIMEOUT_S

    def __post_init__(self) -> None:
        object.__setattr__(self, "tools", tuple(self.tools))
        if not self.tools:
            raise ValueError("a LintPlan needs at least one tool")
        if not self.detected:
            raise ValueError("a LintPlan must say how it was detected")
        if self.timeout <= 0:
            raise ValueError("lint timeout must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "tools": [t.to_dict() for t in self.tools],
            "timeout": self.timeout,
        }


# ---------------------------------------------------------------------------
# The record: what ran and what it said (redacted, capped)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LintStep:
    """One lint command as it ran. ``verdict`` is ``True`` (accepted), ``False``
    (rejected or timed out) or ``None`` (could not run — see ``error``). The tail
    is redacted and capped at construction, like every other run record.

    ``findings_changed`` / ``findings_other`` are the attributed counts of a tool
    with ``findings_re`` (findings naming a changed file / any other file); both
    stay 0 for every other tool, so a reader can tell "no attribution" from "none
    found" by the tool's declaration, never by the numbers.
    """

    tool: str
    argv: tuple[str, ...]
    files: tuple[str, ...]
    rc: int
    verdict: bool | None
    tail: str = ""
    timed_out: bool = False
    duration_s: float = 0.0
    error: str = ""
    findings_changed: int = 0
    findings_other: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "argv", tuple(str(a) for a in self.argv))
        object.__setattr__(self, "files", tuple(str(f) for f in self.files))
        object.__setattr__(self, "tail", redact_and_cap(self.tail, max_chars=LINT_TAIL_CHARS))
        object.__setattr__(self, "error", redact_and_cap(self.error, max_chars=500))

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "argv": list(self.argv),
            "files": list(self.files),
            "rc": self.rc,
            "verdict": self.verdict,
            "tail": self.tail,
            "timed_out": self.timed_out,
            "duration_s": round(self.duration_s, 3),
            "error": self.error,
            "findings_changed": self.findings_changed,
            "findings_other": self.findings_other,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> LintStep:
        return cls(
            tool=str(d.get("tool", "")),
            argv=tuple(d.get("argv", ())),
            files=tuple(d.get("files", ())),
            rc=int(d.get("rc", 0)),
            verdict=d.get("verdict"),
            tail=str(d.get("tail", "")),
            timed_out=bool(d.get("timed_out", False)),
            duration_s=float(d.get("duration_s", 0.0)),
            error=str(d.get("error", "")),
            findings_changed=int(d.get("findings_changed", 0) or 0),
            findings_other=int(d.get("findings_other", 0) or 0),
        )


@dataclass(frozen=True)
class LintRun:
    """Belt 5's record on a :class:`~crb.core.grade.GradeResult`.

    ``ok`` is the belt value: ``True`` iff every step accepted; ``False`` if any
    step rejected, timed out or could not run; ``None`` only when no step ran
    (no lintable changed file for a ``paths="changed"`` plan — ``note`` says so).
    ``error`` is non-empty iff a step could not run (harness); it is what the
    grader lifts into ``GradeResult.error`` so the row fails closed as ``harness``.
    """

    detected: str
    steps: tuple[LintStep, ...] = ()
    ok: bool | None = None
    note: str = ""
    error: str = ""
    duration_s: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", tuple(self.steps))
        if self.ok is True and (self.error or any(s.verdict is not True for s in self.steps)):
            raise ValueError("a LintRun cannot be ok with a rejecting, failed or errored step")
        if self.error and self.ok is not False:
            raise ValueError("a LintRun with an error fails closed (ok=False)")

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "steps": [s.to_dict() for s in self.steps],
            "ok": self.ok,
            "note": self.note,
            "error": self.error,
            "duration_s": round(self.duration_s, 3),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> LintRun:
        return cls(
            detected=str(d.get("detected", "")),
            steps=tuple(LintStep.from_dict(s) for s in d.get("steps", ()) or ()),
            ok=d.get("ok"),
            note=str(d.get("note", "")),
            error=str(d.get("error", "")),
            duration_s=float(d.get("duration_s", 0.0)),
        )


# ---------------------------------------------------------------------------
# Running a plan
# ---------------------------------------------------------------------------


def _tail(text: str, n: int = 40) -> str:
    lines = text.strip().splitlines()
    return "\n".join(lines[-n:])


def _first_line(res: ExecResult) -> str:
    text = (res.stderr or res.stdout).strip()
    return text.splitlines()[0][:160] if text else ""


def _read_exit(tool: LintTool, res: ExecResult) -> tuple[bool | None, str]:
    """``(verdict, error)`` for one finished step — the ONE place an exit code is
    interpreted. Fail closed: anything the table does not name is not a pass."""
    if res.timed_out:
        return False, ""
    if res.cancelled:
        return None, "lint cancelled"
    if res.returncode in _NOT_RUNNABLE_RCS:
        return None, f"{tool.name}: not runnable (rc={res.returncode})"
    if tool.unrunnable_re and re.search(tool.unrunnable_re, res.combined):
        return None, f"{tool.name}: not runnable (rc={res.returncode}: {_first_line(res)})"
    if res.returncode == 0:
        if tool.stdout_is_findings and res.stdout.strip():
            return False, ""
        return True, ""
    if res.returncode in tool.findings_rcs:
        return False, ""
    return None, f"{tool.name}: tool failed (rc={res.returncode})"


def _norm_path(path: str, root: Path) -> str:
    """A finding's path as the changed-file list spells it: root-relative, POSIX,
    no leading ``./``; an absolute path under ``root`` is made relative to it."""
    p = path.strip().strip("'\"").replace("\\", "/")
    if p.startswith("/"):
        try:
            p = Path(p).resolve().relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            return p
    while p.startswith("./"):
        p = p[2:]
    return p


def attribute_findings(
    tool: LintTool, output: str, root: Path, changed_files: Sequence[str]
) -> tuple[int, int]:
    """``(in changed files, in other files)`` — how many findings of a rejecting
    ``findings_re`` tool name a CHANGED file versus any other file. Per FILE, per
    output line; a line the pattern does not match is not a finding."""
    pattern = re.compile(tool.findings_re)
    changed = {_norm_path(f, root) for f in changed_files}
    mine = other = 0
    for line in output.splitlines():
        m = pattern.search(line)
        if not m:
            continue
        if _norm_path(m.group("file"), root) in changed:
            mine += 1
        else:
            other += 1
    return mine, other


def run_plan(
    plan: LintPlan,
    executor: Executor,
    root: Path,
    changed_files: Sequence[str],
    *,
    timeout: int = 0,
) -> LintRun:
    """Run every step of ``plan`` in ``root`` over ``changed_files``; stop at the
    first step that does not accept (later steps cannot change the verdict).

    A launch error (``OSError``: the binary is missing on the host) is a harness
    error, recorded as rc 127 with the exception text — never a pass. A rejecting
    step with ``findings_re`` is attributed (module docstring): findings only in
    unchanged files leave the step accepted and put the counts on the run's note;
    findings naming no file at all are a harness error.
    """
    started = time.monotonic()
    t = timeout or plan.timeout
    steps: list[LintStep] = []
    notes: list[str] = []
    ran = 0
    for tool in plan.tools:
        files = tool.files_for(changed_files)
        if not tool.concerns(changed_files):
            continue
        ran += 1
        argv = (*tool.argv, *files)
        cmd = Command(
            argv,
            root,
            env=dict(tool.env),
            timeout=t,
            writable_paths=tool.writable_paths,
        )
        step_started = time.monotonic()
        try:
            res = executor.run(cmd)
        except OSError as exc:
            step = LintStep(
                tool.name,
                argv,
                files,
                127,
                None,
                f"{type(exc).__name__}: {exc}",
                False,
                time.monotonic() - step_started,
                f"{tool.name}: not runnable ({type(exc).__name__}: {exc})",
            )
            steps.append(step)
            break
        verdict, error = _read_exit(tool, res)
        rc = _TIMEOUT_RC if res.timed_out else res.returncode
        mine = other = 0
        if verdict is False and not res.timed_out and tool.findings_re:
            mine, other = attribute_findings(tool, res.combined, root, changed_files)
            if mine == 0 and other > 0:
                verdict = True  # the maintainers' debt in files the builder never touched
                notes.append(
                    f"{tool.name}: {other} pre-existing finding(s) in unchanged files, 0 in "
                    "changed files — not attributed to the patch"
                )
            elif mine == 0:
                verdict, error = (
                    None,
                    f"{tool.name}: rejected (rc={rc}) with no finding attributable to a file",
                )
        step = LintStep(
            tool.name,
            argv,
            files,
            rc,
            verdict,
            _tail(res.combined),
            res.timed_out,
            res.duration_s,
            error,
            mine,
            other,
        )
        steps.append(step)
        if verdict is not True:
            break
    duration = time.monotonic() - started
    if not ran:
        return LintRun(
            plan.detected,
            (),
            None,
            "no lintable changed file for the detected linter — belt 5 not evaluated",
            "",
            duration,
        )
    last = steps[-1]
    if last.error:
        return LintRun(plan.detected, tuple(steps), False, last.error, last.error, duration)
    if last.timed_out:
        return LintRun(plan.detected, tuple(steps), False, f"{last.tool} timed out", "", duration)
    if last.verdict is False:
        what = (
            f"{last.findings_changed} finding(s) in changed files"
            f" ({last.findings_other} elsewhere, not counted)"
            if last.findings_changed
            else f"{len(last.files) or 'the'} changed file(s)"
        )
        return LintRun(
            plan.detected,
            tuple(steps),
            False,
            f"{last.tool} rejected {what}",
            "",
            duration,
        )
    return LintRun(plan.detected, tuple(steps), True, "; ".join(notes), "", duration)


# ---------------------------------------------------------------------------
# Operator-declared plan (RepoConfig.lint)
# ---------------------------------------------------------------------------


def plan_from_config(lint: Mapping[str, Any] | None) -> LintPlan | None:
    """``RepoConfig.lint`` → a :class:`LintPlan`, or ``None`` when nothing is declared.

    Shape::

        {"command": ["ruff", "check"],       # argv; changed files appended when paths=changed
         "paths": "changed" | "all",          # default "changed"
         "exts": [".py"],                     # optional: which changed files (default: all)
         "findings_rc": [1],                  # optional: exit codes meaning "rejected"
         "stdout_is_findings": false,         # optional: gofmt -l style
         "unrunnable_re": "",                 # optional: output that means "tool missing"
         "findings_re": "",                   # optional: per-line pattern with a `file` group
                                              #   → rejection attributed to changed files
         "timeout": 600}                      # optional: seconds per step

    ``{"command": []}`` / ``{}`` / ``None`` all mean "not declared" (auto-detect applies).
    ``{"disabled": true}`` switches belt 5 OFF for the repo (``None``, recorded as such by
    the caller) — an explicit operator decision, never a default.
    """
    if not lint:
        return None
    if lint.get("disabled"):
        return None
    command = lint.get("command") or ()
    if isinstance(command, str):
        raise ValueError("RepoConfig.lint.command must be an argv list, not a string")
    argv = tuple(str(a) for a in command)
    if not argv:
        return None
    paths = str(lint.get("paths") or PATHS_CHANGED)
    tool = LintTool(
        name=str(lint.get("name") or "config"),
        argv=argv,
        paths=paths,
        exts=tuple(str(e) for e in (lint.get("exts") or ())),
        findings_rcs=frozenset(int(r) for r in (lint.get("findings_rc") or (1,))),
        stdout_is_findings=bool(lint.get("stdout_is_findings", False)),
        unrunnable_re=str(lint.get("unrunnable_re") or ""),
        findings_re=str(lint.get("findings_re") or ""),
    )
    return LintPlan((tool,), "config", int(lint.get("timeout") or DEFAULT_LINT_TIMEOUT_S))


def lint_disabled(lint: Mapping[str, Any] | None) -> bool:
    """``RepoConfig.lint = {"disabled": true}`` — the operator switched belt 5 off."""
    return lint is not None and bool(lint.get("disabled"))


# ---------------------------------------------------------------------------
# Per-language detection helpers (the runners call these from their lint hook)
# ---------------------------------------------------------------------------


def _read_text(p: Path, limit: int = 1_000_000) -> str:
    try:
        if p.stat().st_size > limit:
            return ""
        return p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _read_toml(p: Path) -> dict[str, Any]:
    try:
        data = tomllib.loads(_read_text(p))
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_json(p: Path) -> dict[str, Any]:
    try:
        data = json.loads(_read_text(p) or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _workflow_texts(root: Path) -> str:
    """Every CI workflow file the repository carries, concatenated (evidence only)."""
    out: list[str] = []
    for d in (root / ".github" / "workflows",):
        if d.is_dir():
            for p in sorted(d.iterdir()):
                if p.suffix in {".yml", ".yaml"}:
                    out.append(_read_text(p, 200_000))
    for name in (".gitlab-ci.yml", ".travis.yml", "Makefile"):
        p = root / name
        if p.is_file():
            out.append(_read_text(p, 200_000))
    return "\n".join(out)


# --- Go: gofmt -------------------------------------------------------------------


def go_plan(root: Path, gofmt: str) -> LintPlan | None:
    """``gofmt -l <changed .go files>``: any listed file ⇒ rejected.

    Detected whenever the repository is a Go module: ``gofmt`` is the formatter every
    Go toolchain ships and the one ``golangci-lint`` enables by default
    (cobra ``.golangci.yml`` → ``formatters.enable: [gofmt, goimports]``; ``Makefile
    fmt: test -z $(gofmt -l $(SRC))``). Vet/golangci-lint are declared explicitly
    (``RepoConfig.lint``), never assumed."""
    if not (Path(root) / "go.mod").is_file():
        return None
    tool = LintTool(
        "gofmt",
        (gofmt, "-l"),
        PATHS_CHANGED,
        (".go",),
        frozenset({2}),
        stdout_is_findings=True,
    )
    return LintPlan((tool,), "gofmt")


# --- Python: ruff -----------------------------------------------------------------

_PRECOMMIT_RUFF_CHECK = re.compile(r"^\s*-\s*id:\s*ruff(?:-check)?\s*$", re.M)
_PRECOMMIT_RUFF_FORMAT = re.compile(r"^\s*-\s*id:\s*ruff-format\s*$", re.M)


def python_ruff_evidence(root: Path) -> tuple[bool, bool]:
    """``(check, format)`` — does the repository configure ``ruff check`` /
    ``ruff format``? Evidence: ``[tool.ruff]`` in ``pyproject.toml`` or a
    ``ruff.toml`` / ``.ruff.toml`` (check); a ``ruff-format`` pre-commit hook or a
    ``[tool.ruff.format]`` table (format). click: ``pyproject.toml [tool.ruff]`` +
    ``.pre-commit-config.yaml`` hooks ``ruff-check`` and ``ruff-format``, run by
    ``.github/workflows/pre-commit.yaml`` on every PR."""
    root = Path(root)
    pyproject = _read_toml(root / "pyproject.toml")
    tool = pyproject.get("tool") if isinstance(pyproject.get("tool"), dict) else {}
    ruff_table = tool.get("ruff") if isinstance(tool, dict) else None
    has_ruff_toml = (root / "ruff.toml").is_file() or (root / ".ruff.toml").is_file()
    precommit = _read_text(root / ".pre-commit-config.yaml")
    check = (
        isinstance(ruff_table, dict)
        or has_ruff_toml
        or _PRECOMMIT_RUFF_CHECK.search(precommit) is not None
    )
    fmt = (
        isinstance(ruff_table, dict) and isinstance(ruff_table.get("format"), dict)
    ) or _PRECOMMIT_RUFF_FORMAT.search(precommit) is not None
    return check, fmt


_PRECOMMIT_RUFF_REPO = re.compile(
    r"repo:\s*https://github\.com/(?:astral-sh|charliermarsh)/ruff-pre-commit\s*\n\s*rev:\s*v?([0-9][\w.]*)",
    re.M,
)
_PEP508_RUFF = re.compile(r"^\s*ruff\s*(\[[^\]]*\])?\s*([=<>!~^][^;#]*)?", re.I)


def pinned_ruff_spec(root: Path) -> str:
    """The ruff VERSION the repository itself runs, as a pip requirement specifier
    (``==0.4.4``, ``>=0.2.0,<0.3.0``), or ``""`` when the repository does not say.

    Belt 5 must apply the repository's definition of acceptable, and that includes the
    linter's version: NHSDigital/mesh-client pins ``ruff ^0.2.0`` and its HEAD passes
    that; the host's ruff 0.16 rejected the maintainers' own patch and excluded two
    honest tasks (2026-09-14). Evidence, in order: a ``ruff-pre-commit`` hook's
    ``rev`` (exact), a PEP 508 pin anywhere in ``pyproject.toml`` dependency lists
    (``project.dependencies``, ``optional-dependencies``, ``dependency-groups``), a
    Poetry dev dependency (caret/tilde translated), ``requirements*.txt``."""
    pc = root / ".pre-commit-config.yaml"
    if pc.is_file():
        m = _PRECOMMIT_RUFF_REPO.search(pc.read_text(encoding="utf-8", errors="replace"))
        if m:
            return f"=={m.group(1)}"
    py = root / "pyproject.toml"
    if py.is_file():
        try:
            data = tomllib.loads(py.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            data = {}
        specs: list[str] = []
        project_tbl = data.get("project")
        project: dict[str, Any] = project_tbl if isinstance(project_tbl, dict) else {}
        opt = project.get("optional-dependencies")
        for value in [
            project.get("dependencies") or [],
            *((opt or {}).values() if isinstance(opt, dict) else ()),
        ]:
            specs += [v for v in value if isinstance(v, str)]
        for value in (data.get("dependency-groups") or {}).values():
            specs += [v for v in value if isinstance(v, str)]
        for spec in specs:
            m = _PEP508_RUFF.match(spec)
            if m and m.group(2):
                return m.group(2).strip()
        poetry = (
            (data.get("tool") or {}).get("poetry") if isinstance(data.get("tool"), dict) else None
        )
        if isinstance(poetry, dict):
            pools = [poetry.get("dev-dependencies") or {}, poetry.get("dependencies") or {}]
            for grp in (poetry.get("group") or {}).values():
                if isinstance(grp, dict):
                    pools.append(grp.get("dependencies") or {})
            for pool in pools:
                v = pool.get("ruff") if isinstance(pool, dict) else None
                if isinstance(v, dict):
                    v = v.get("version")
                if isinstance(v, str) and v.strip():
                    return _poetry_to_pep440(v.strip())
    for req in sorted(root.glob("requirements*.txt")):
        for line in req.read_text(encoding="utf-8", errors="replace").splitlines():
            m = _PEP508_RUFF.match(line)
            if m and m.group(2):
                return m.group(2).strip()
    return ""


def _poetry_to_pep440(spec: str) -> str:
    """Poetry's caret / tilde ranges as PEP 440: ``^0.2.0`` → ``>=0.2.0,<0.3.0``,
    ``~0.2.1`` → ``>=0.2.1,<0.3.0``; anything already PEP 440 passes through."""
    s = spec.replace(" ", "")
    if s.startswith("^") or s.startswith("~"):
        parts = s[1:].split(".")
        nums = [int(x) if x.isdigit() else 0 for x in parts]
        while len(nums) < 3:
            nums.append(0)
        lo = ".".join(str(n) for n in nums)
        if s.startswith("^"):
            if nums[0] > 0:
                hi = f"{nums[0] + 1}.0.0"
            elif nums[1] > 0:
                hi = f"0.{nums[1] + 1}.0"
            else:
                hi = f"0.0.{nums[2] + 1}"
        else:
            hi = f"{nums[0]}.{nums[1] + 1}.0"
        return f">={lo},<{hi}"
    if s == "*":
        return ""
    return s if s[0] in "=<>!~" else f"=={s}"


def python_plan(root: Path, ruff: str | None) -> LintPlan | None:
    """``ruff check <changed .py>`` (+ ``ruff format --check <changed .py>`` when the
    repository evidences ``ruff format``). ``ruff`` is the resolved binary (the
    repository's venv first, then the host); ``None`` ⇒ the plan cannot run and is
    not detected (the belt is not evaluated, and the note says why)."""
    check, fmt = python_ruff_evidence(root)
    if not check and not fmt:
        return None
    if not ruff:
        return None
    tools: list[LintTool] = []
    names: list[str] = []
    version = ruff_version(ruff)
    tag = f"ruff@{version}" if version else "ruff"
    if check:
        tools.append(LintTool("ruff", (ruff, "check", "--no-fix"), exts=(".py",)))
        names.append(tag)
    if fmt:
        tools.append(LintTool("ruff-format", (ruff, "format", "--check"), exts=(".py",)))
        names.append("ruff-format")
    return LintPlan(tuple(tools), "+".join(names))


def ruff_version(ruff: str) -> str:
    """``ruff --version`` → ``"0.2.2"`` (``""`` when it cannot be asked). Recorded in
    the plan's ``detected`` so a belt-5 verdict names the linter VERSION it applied."""
    try:
        out = subprocess.run(
            [ruff, "--version"], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    m = re.search(r"(\d+\.\d+\.\d+)", out.stdout or "")
    return m.group(1) if m else ""


# --- JavaScript / TypeScript: eslint, prettier, standard ------------------------------

_ESLINT_CONFIGS: tuple[str, ...] = (
    "eslint.config.js",
    "eslint.config.mjs",
    "eslint.config.cjs",
    "eslint.config.ts",
    "eslint.config.mts",
    "eslint.config.cts",
    ".eslintrc",
    ".eslintrc.js",
    ".eslintrc.cjs",
    ".eslintrc.json",
    ".eslintrc.yml",
    ".eslintrc.yaml",
)
_PRETTIER_CONFIGS: tuple[str, ...] = (
    ".prettierrc",
    ".prettierrc.json",
    ".prettierrc.yml",
    ".prettierrc.yaml",
    ".prettierrc.json5",
    ".prettierrc.js",
    ".prettierrc.cjs",
    ".prettierrc.mjs",
    ".prettierrc.toml",
    "prettier.config.js",
    "prettier.config.cjs",
    "prettier.config.mjs",
)
_JS_EXTS: tuple[str, ...] = (".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx")

#: tsc's per-diagnostic line (``--pretty false``): ``path(line,col): error TSnnnn: …``.
#: The path group stops at the first ``(``; tsc prints it relative to the cwd.
TSC_FINDINGS_RE = r"^(?P<file>[^\s(][^(\n]*?)\((?P<line>\d+),(?P<col>\d+)\): error TS\d+:"
#: tsc's exit codes that mean "diagnostics present" (1 = outputs skipped, 2 = outputs
#: generated); 3 / 4 (invalid project, reference cycle) are the tool's own failures.
_TSC_FINDINGS_RCS: frozenset[int] = frozenset({1, 2})
#: A tsc that could not write where a read-only sandbox mount sits (``--build`` writes
#: ``.tsbuildinfo``; TS5033 "Could not write file") is not a verdict about the patch.
_TSC_UNRUNNABLE_RE = r"error TS5033: Could not write file"
_TSC_TOKEN_RE = re.compile(r"(?:^|\s|&&|;)\s*(?:npx\s+|yarn\s+|pnpm\s+)?tsc(?=\s|$)")


def _script_argv(script: str) -> list[str]:
    """The argv of a ``package.json`` script verbatim (no shell operators honoured — a
    script that chains commands is not a single tool and yields ``[]``)."""
    if any(op in script for op in ("&&", "||", ";", "|", ">", "<", "$(", "`")):
        return []
    return script.split()


def tsc_evidence(root: Path, pkg: Mapping[str, Any]) -> tuple[str, list[str]] | None:
    """``(evidence, extra argv)`` when the repository gates on the TypeScript compiler,
    else ``None``. Evidence, in order:

    1. ``package.json scripts["lint:types"]`` invoking ``tsc`` — honoured verbatim
       (nhsuk-frontend / nhsuk-react-components: ``"lint:types": "tsc --build
       tsconfig.json --pretty"``, run by their CI's ``npm run lint:types`` / ``yarn
       lint``); ``tsconfig.json`` must exist;
    2. any other script invoking ``tsc`` (a ``typecheck``/``check-types``/``build``
       script) — ``--build`` is honoured when the script says so, else
       ``--noEmit -p tsconfig.json``;
    3. ``typescript`` among the devDependencies AND a CI workflow / Makefile line that
       runs ``tsc`` — the default argv.

    The evidence string is what ``lint_run.detected`` records (``tsc:lint:types``,
    ``tsc:script:<name>``, ``tsc:ci``)."""
    root = Path(root)
    if not (root / "tsconfig.json").is_file():
        return None
    scripts = pkg.get("scripts") if isinstance(pkg.get("scripts"), dict) else {}
    scripts = {str(k): str(v) for k, v in scripts.items()} if isinstance(scripts, dict) else {}
    lint_types = scripts.get("lint:types", "")
    if lint_types and _TSC_TOKEN_RE.search(lint_types):
        argv = _script_argv(lint_types)
        if argv and argv[0] in ("npx", "yarn", "pnpm"):
            argv = argv[1:]
        if argv and argv[0] == "tsc":
            return "tsc:lint:types", argv[1:]
        return "tsc:lint:types", ["--build", "tsconfig.json"]  # chained: the build form
    for name, script in sorted(scripts.items()):
        if name == "lint:types" or not _TSC_TOKEN_RE.search(script):
            continue
        if "--clean" in script:
            continue  # ``tsc --build --clean`` (a postclean hook) checks nothing
        build = "--build" in script.split() or "-b" in script.split()
        return (
            f"tsc:script:{name}",
            ["--build", "tsconfig.json"] if build else ["--noEmit", "-p", "tsconfig.json"],
        )
    dev = pkg.get("devDependencies") if isinstance(pkg.get("devDependencies"), dict) else {}
    if (
        isinstance(dev, dict)
        and "typescript" in dev
        and _TSC_TOKEN_RE.search(_workflow_texts(root))
    ):
        return "tsc:ci", ["--noEmit", "-p", "tsconfig.json"]
    return None


def js_plan(root: Path, bin_dir: Path | None) -> LintPlan | None:
    """The repository's JavaScript lint, in this order of evidence:

    1. **eslint** — an ESLint config file (flat or legacy) or ``package.json
       eslintConfig`` AND ``node_modules/.bin/eslint``; then
    2. **prettier --check** — a prettier config or ``package.json prettier`` AND the
       binary (both run when both are configured; eslint first);
    3. else **standard** — ``package.json scripts.lint`` starts with ``standard`` AND
       ``node_modules/.bin/standard`` (koa: ``"lint": "standard"``, CI ``npm run lint``);
    4. then **tsc** — appended whenever :func:`tsc_evidence` finds the repository gates
       on the type checker AND ``node_modules/.bin/tsc`` (``[measured 2026-09-14]`` 4
       of 10 clean NHS rows failed the repositories' own ``lint:types``; belt 5 never ran
       it). Whole-project (``paths="all"``; tsc has no per-file mode with project
       references), ``--pretty false`` appended so the findings parse, and the
       rejection ATTRIBUTED to the changed files by ``TSC_FINDINGS_RE`` — errors only in
       unchanged files are pre-existing debt, recorded, never the builder's.

    The binary alone is NOT evidence: koa carries ``node_modules/.bin/eslint`` only
    as a transitive dependency of ``standard`` and has no ESLint config — running
    ``eslint`` there would fail on "no configuration", a harness error dressed as a
    verdict. ``bin_dir`` is ``None`` under a sandbox (the image's PATH resolves the
    tools) — then only the config evidence is consulted."""
    root = Path(root)
    pkg = _read_json(root / "package.json")
    if not pkg and not (root / "package.json").is_file():
        return None

    def have(tool: str) -> bool:
        return bin_dir is None or (Path(bin_dir) / tool).exists()

    def binary(tool: str) -> str:
        return tool if bin_dir is None else str(Path(bin_dir) / tool)

    tools: list[LintTool] = []
    names: list[str] = []
    eslint_cfg = any((root / c).is_file() for c in _ESLINT_CONFIGS) or isinstance(
        pkg.get("eslintConfig"), dict
    )
    if eslint_cfg and have("eslint"):
        tools.append(
            LintTool(
                "eslint",
                (binary("eslint"),),
                exts=_JS_EXTS,
                findings_rcs=frozenset({1}),
                env={"NODE_ENV": "test"},
            )
        )
        names.append("eslint")
    prettier_cfg = any((root / c).is_file() for c in _PRETTIER_CONFIGS) or (
        "prettier" in pkg and pkg.get("prettier") is not None
    )
    if prettier_cfg and have("prettier"):
        tools.append(
            LintTool(
                "prettier",
                (binary("prettier"), "--check", "--log-level=warn"),
                exts=_JS_EXTS,
                findings_rcs=frozenset({1}),
            )
        )
        names.append("prettier")
    if not tools:
        scripts = pkg.get("scripts") if isinstance(pkg.get("scripts"), dict) else {}
        lint_script = str(scripts.get("lint", "")) if isinstance(scripts, dict) else ""
        if lint_script.split()[:1] == ["standard"] and have("standard"):
            tools.append(
                LintTool(
                    "standard",
                    (binary("standard"),),
                    exts=_JS_EXTS,
                    findings_rcs=frozenset({1}),
                )
            )
            names.append("standard")
    tsc = tsc_evidence(root, pkg)
    if tsc is not None and have("tsc"):
        evidence, extra = tsc
        tools.append(
            LintTool(
                "tsc",
                (binary("tsc"), *extra, "--pretty", "false"),
                PATHS_ALL,
                exts=_JS_EXTS,
                findings_rcs=_TSC_FINDINGS_RCS,
                unrunnable_re=_TSC_UNRUNNABLE_RE,
                findings_re=TSC_FINDINGS_RE,
            )
        )
        names.append(evidence)
    if not tools:
        return None
    return LintPlan(tuple(tools), "+".join(names))


# --- JVM: spotless / checkstyle -------------------------------------------------------


def jvm_plan(root: Path, mvn: str, flags: Sequence[str], env: Mapping[str, str]) -> LintPlan | None:
    """``mvn -o -q -B spotless:check`` when ``pom.xml`` declares
    ``spotless-maven-plugin`` (gson: ``check`` goal bound in the build);
    ``mvn -o -q -B checkstyle:check`` when it declares ``maven-checkstyle-plugin``
    (petclinic: ``check`` at ``validate``; commons-lang: ``checkstyle:check`` in the
    ``defaultGoal``). Both run when both are declared. Maven plugins are module-wide
    (``paths="all"``): the changed files cannot be passed, the module is checked."""
    pom = _read_text(Path(root) / "pom.xml", 5_000_000)
    if not pom:
        return None
    tools: list[LintTool] = []
    names: list[str] = []
    base = (mvn, "-o", "-q", "-B", *flags)
    if "spotless-maven-plugin" in pom:
        tools.append(
            LintTool(
                "spotless",
                (*base, "spotless:check"),
                PATHS_ALL,
                env=env,
                writable_paths=("target",),
            )
        )
        names.append("spotless")
    if "maven-checkstyle-plugin" in pom:
        tools.append(
            LintTool(
                "checkstyle",
                (*base, "checkstyle:check"),
                PATHS_ALL,
                env=env,
                writable_paths=("target",),
            )
        )
        names.append("checkstyle")
    if not tools:
        return None
    return LintPlan(tuple(tools), "+".join(names), DEFAULT_LINT_TIMEOUT_S)


# --- Rust: cargo fmt / clippy ----------------------------------------------------------

#: A rustup proxy's answer when the component is absent — exit 1, the findings code.
_RUSTUP_MISSING_RE = r"is not installed for the toolchain|error: no such command: `(?:fmt|clippy)`"


def rust_plan(root: Path, cargo: str, env: Mapping[str, str]) -> LintPlan | None:
    """``cargo fmt --check`` when the repository configures rustfmt
    (``rustfmt.toml`` / ``.rustfmt.toml``) or its CI runs ``cargo fmt`` (clap:
    ``ci.yml`` job ``rustfmt: cargo fmt --check``); ``cargo clippy --offline --
    -D warnings`` when it configures clippy (``clippy.toml`` / ``.clippy.toml``) or
    its CI runs clippy (clap: ``.clippy.toml`` + ``ci.yml`` job ``clippy``). Both are
    crate-wide (``paths="all"``)."""
    root = Path(root)
    if not (root / "Cargo.toml").is_file():
        return None
    ci = _workflow_texts(root)
    tools: list[LintTool] = []
    names: list[str] = []
    fmt_cfg = (root / "rustfmt.toml").is_file() or (root / ".rustfmt.toml").is_file()
    if fmt_cfg or "cargo fmt" in ci:
        tools.append(
            LintTool(
                "cargo-fmt",
                (cargo, "fmt", "--check"),
                PATHS_ALL,
                env=env,
                unrunnable_re=_RUSTUP_MISSING_RE,
            )
        )
        names.append("cargo-fmt")
    clippy_cfg = (root / "clippy.toml").is_file() or (root / ".clippy.toml").is_file()
    if clippy_cfg or "clippy" in ci:
        tools.append(
            LintTool(
                "clippy",
                (cargo, "clippy", "--offline", "--", "-D", "warnings"),
                PATHS_ALL,
                findings_rcs=frozenset({101}),
                env=env,
                writable_paths=("target",),
                unrunnable_re=_RUSTUP_MISSING_RE,
            )
        )
        names.append("clippy")
    if not tools:
        return None
    return LintPlan(tuple(tools), "+".join(names))


def which(name: str) -> str | None:
    """``shutil.which`` for the host resolution the runners do (kept here so the
    lint hooks have one import)."""
    return shutil.which(name)


__all__ = [
    "DEFAULT_LINT_TIMEOUT_S",
    "PATHS_ALL",
    "PATHS_CHANGED",
    "TSC_FINDINGS_RE",
    "LintPlan",
    "LintRun",
    "LintStep",
    "LintTool",
    "attribute_findings",
    "go_plan",
    "js_plan",
    "jvm_plan",
    "lint_disabled",
    "plan_from_config",
    "python_plan",
    "python_ruff_evidence",
    "run_plan",
    "rust_plan",
    "tsc_evidence",
    "which",
]
