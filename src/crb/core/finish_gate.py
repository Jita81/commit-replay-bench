"""The finish gate — the repository's own checks as the builder's checklist, and the
harness re-running them before an attempt counts as done (verify-repair, in the attempt).

Why
---
In-attempt verify-repair was the strongest process lever in the programme that preceded
this product (+9 pp) **[hypothesis — carried over from that programme's lever ladder; not
yet measured under apparatus 2.2; the paired Phase B campaign measures it here]**. A blind
builder is told far less than a sighted one about how to check its own work, and clean
patches still fail review on formatting, lint and type checks the repository runs on every
pull request. The gate closes that loop inside the attempt: the brief lists the checks (a
short checklist, never an essay — a distilled checklist measurably beat an essay), and
``done`` is not accepted until the harness has re-run them and they pass, with one bounded
repair turn when they do not.

What the builder is told — and what it is never told
----------------------------------------------------
The checklist carries OPERATING facts only: the repository's formatter and linter over the
changed files (the belt-5 plan), the extra commands the repository declares
(``checks.commands``: ``go vet ./...``, ``npm run lint:types``) and, blind, the test harness
command without a scope. It never names a target test, a held-out test file or anything
derived from the gold; :func:`assert_no_oracle` refuses a checklist that would (a blind
brief that names the oracle is a leak, whatever built it).

Verdicts are the checks', never the model's: a declared command that already fails on the
untouched parent is recorded ``pre_existing`` and does not gate; a check that cannot run is
recorded as an error and does not gate either (the grade's own belts still judge). The gate
never decides ``clean``.

Navigation
----------
What it is:   The finish gate's core: the checklist (``checklist``), the leak guard
              (``assert_no_oracle``), the commands the repository evidences (``derived_commands``),
              the baseline of declared commands at the parent
              (``command_baseline``) and the verification run (``verify`` → ``GateRun``).
What it does: Turns the repository's belt-5 plan and declared check commands into numbered
              checklist lines; re-runs them after the build (the plan over the changed files,
              each declared command in the worktree) and reports which failed, which were
              already red at the parent and which could not run; renders the repair findings.
How:          ``checklist(plan, commands, test_command)`` → the brief's ``finish_checks``;
              ``command_baseline`` before the build; after it ``verify`` = ``run_plan`` +
              one ``Command`` per declared check → ``GateRun.passed`` / ``label`` /
              ``findings``.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0024-working-by-construction.md
Works with:   src/crb/core/checks.py (the ``finish_gate`` switch and declared commands),
              src/crb/core/lint.py (the plan the gate re-runs), src/crb/builders/adapter.py
              (brief → build → verify → repair), src/crb/builders/base.py (``finish_checks`` /
              ``gate_note`` on the brief), src/crb/core/execution.py (Command / Executor)
Tested by:    tests/test_finish_gate.py, tests/test_builders_finish_gate.py
Touch when:   onboarding a repository — declare its extra checks under ``checks.commands``
              (docs/OPERATOR.md), never here; changing what a builder is told is an
              opt-in arm and needs the row label and an A/B before it is a default.
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crb.core.checks import CheckCommand
from crb.core.execution import Command, Executor
from crb.core.lint import LintPlan, run_plan
from crb.core.redact import redact_and_cap

#: The most lines the checklist carries (a checklist, never an essay).
MAX_CHECKLIST_LINES = 8
#: Cap on the findings text handed to one repair call.
MAX_FINDINGS_CHARS = 4000

KIND_LINT = "lint"
KIND_COMMAND = "command"


class OracleLeak(ValueError):
    """A checklist line names the held-out oracle — refused before any builder call."""


def _tool_line(name: str, argv: Sequence[str], paths: str, exts: Sequence[str], gofmt: bool) -> str:
    cmd = " ".join(argv)
    if paths == "changed":
        what = f"<changed {'/'.join(exts)} files>" if exts else "<changed files>"
        line = f"{name}: {cmd} {what}"
    else:
        line = f"{name}: {cmd}"
    if gofmt:
        line += " — must print nothing"
    return line


def checklist(
    plan: LintPlan | None,
    commands: Sequence[CheckCommand],
    *,
    test_command: str = "",
) -> tuple[str, ...]:
    """The numbered checklist lines: the plan's steps (format / lint / type check), the
    declared commands, then ``test_command`` (blind: the harness command without a scope)
    — capped at :data:`MAX_CHECKLIST_LINES`."""
    lines: list[str] = []
    if plan is not None:
        for tool in plan.tools:
            lines.append(
                _tool_line(tool.name, tool.argv, tool.paths, tool.exts, tool.stdout_is_findings)
            )
    for c in commands:
        lines.append(f"{c.name}: {c.display}")
    if test_command:
        lines.append(f"tests: {test_command} <existing test files near your change>")
    return tuple(f"{i}. {line}" for i, line in enumerate(lines[:MAX_CHECKLIST_LINES], start=1))


_GOVET_RE = re.compile(r"^\s*-\s*govet\b|\bgo\s+vet\b", re.M)


def derived_commands(root: Path) -> tuple[CheckCommand, ...]:
    """Check commands the repository's OWN configuration evidences and the runner can run
    offline with the toolchain alone — today ``go vet ./...`` for a Go module whose
    ``.golangci.yml`` enables ``govet`` or whose Makefile / CI runs ``go vet`` (cobra:
    ``golangci-lint`` with ``govet`` on every pull request). A declared command of the same
    name replaces a derived one; nothing is derived without evidence."""
    root = Path(root)
    if not (root / "go.mod").is_file():
        return ()
    texts: list[str] = []
    for name in (".golangci.yml", ".golangci.yaml", "Makefile"):
        p = root / name
        if p.is_file():
            texts.append(p.read_text(encoding="utf-8", errors="replace"))
    wf = root / ".github" / "workflows"
    if wf.is_dir():
        texts += [
            p.read_text(encoding="utf-8", errors="replace")
            for p in sorted(wf.iterdir())
            if p.suffix in {".yml", ".yaml"}
        ]
    if any(_GOVET_RE.search(t) for t in texts):
        return (CheckCommand("vet", ("go", "vet", "./...")),)
    return ()


def merge_commands(
    derived: Sequence[CheckCommand], declared: Sequence[CheckCommand]
) -> tuple[CheckCommand, ...]:
    """Derived commands first, each replaced by a declared one of the same name; then the
    remaining declared commands."""
    by_name = {c.name: c for c in declared}
    out = [by_name.pop(c.name, c) for c in derived]
    return (*out, *(c for c in declared if c.name in by_name))


def assert_no_oracle(lines: Sequence[str], oracle: Sequence[str]) -> None:
    """Refuse a checklist that names any held-out test path or target scope (the leak
    guard — a blind builder must never learn the oracle from the gate)."""
    for item in oracle:
        needle = str(item).strip()
        if not needle or needle in {".", "./", "./..."}:
            continue
        for line in lines:
            if needle in line:
                raise OracleLeak(f"finish-gate checklist names the held-out oracle ({needle!r})")


@dataclass(frozen=True)
class GateResult:
    """One check as it ran after the build."""

    name: str
    kind: str
    ok: bool | None
    pre_existing: bool = False
    detail: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "detail", redact_and_cap(self.detail, max_chars=1500))
        object.__setattr__(self, "error", redact_and_cap(self.error, max_chars=300))

    @property
    def gates(self) -> bool:
        """Does this result hold the attempt back? Only a check that ran and failed on a
        tree where it passed at the parent."""
        return self.ok is False and not self.pre_existing

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "ok": self.ok,
            "pre_existing": self.pre_existing,
            "detail": self.detail,
            "error": self.error,
        }


@dataclass(frozen=True)
class GateRun:
    """The gate's verdict over one verification pass."""

    results: tuple[GateResult, ...] = ()
    duration_s: float = 0.0

    @property
    def passed(self) -> bool:
        return not any(r.gates for r in self.results)

    @property
    def failing(self) -> tuple[str, ...]:
        return tuple(r.name for r in self.results if r.gates)

    def label(self) -> str:
        """``pass`` / ``fail:<names>`` — with ``+pre:<names>`` / ``+err:<names>`` when
        some checks did not gate."""
        head = "pass" if self.passed else "fail:" + "+".join(self.failing)
        pre = [r.name for r in self.results if r.pre_existing and r.ok is False]
        err = [r.name for r in self.results if r.error]
        if pre:
            head += ";pre:" + "+".join(pre)
        if err:
            head += ";err:" + "+".join(err)
        return head

    def findings(self) -> str:
        """The failing checks' output, for the repair call's ``gate_note``."""
        parts = [f"[{r.name}]\n{r.detail}".rstrip() for r in self.results if r.gates]
        return "\n\n".join(parts)[-MAX_FINDINGS_CHARS:]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "results": [r.to_dict() for r in self.results],
            "duration_s": round(self.duration_s, 3),
        }


def _run_command(c: CheckCommand, executor: Executor, root: Path) -> GateResult:
    try:
        res = executor.run(Command(c.argv, root, timeout=c.timeout))
    except OSError as exc:
        return GateResult(c.name, KIND_COMMAND, None, error=f"{type(exc).__name__}: {exc}")
    if res.returncode in (126, 127):
        return GateResult(c.name, KIND_COMMAND, None, error=f"not runnable (rc={res.returncode})")
    tail = "\n".join(res.combined.strip().splitlines()[-40:])
    return GateResult(c.name, KIND_COMMAND, res.returncode == 0 and not res.timed_out, detail=tail)


def command_baseline(
    commands: Sequence[CheckCommand], executor: Executor, root: Path
) -> dict[str, bool | None]:
    """Each declared command's verdict on the untouched worktree (before the build), so
    a command that is already red is recorded ``pre_existing`` and never blamed on the
    builder."""
    return {c.name: _run_command(c, executor, Path(root)).ok for c in commands}


def verify(
    plan: LintPlan | None,
    commands: Sequence[CheckCommand],
    executor: Executor,
    root: Path,
    changed: Sequence[str],
    *,
    baseline: Mapping[str, bool | None] | None = None,
) -> GateRun:
    """Re-run the gate after the build: the plan over ``changed`` (the changed non-test
    files), then every declared command in the worktree."""
    started = time.monotonic()
    root = Path(root)
    results: list[GateResult] = []
    if plan is not None and changed:
        lint = run_plan(plan, executor, root, [f for f in changed if (root / f).is_file()])
        if lint.ok is not None or lint.error:
            detail = "\n".join(
                f"[{st.tool}] rc={st.rc}\n{st.tail}" for st in lint.steps if st.verdict is not True
            )
            results.append(
                GateResult(
                    KIND_LINT,
                    KIND_LINT,
                    None if lint.error else lint.ok,
                    detail=detail or lint.note,
                    error=lint.error,
                )
            )
    base = dict(baseline or {})
    for c in commands:
        r = _run_command(c, executor, root)
        if r.ok is False and base.get(c.name) is False:
            r = GateResult(r.name, r.kind, r.ok, True, r.detail, r.error)
        results.append(r)
    return GateRun(tuple(results), time.monotonic() - started)


__all__ = [
    "KIND_COMMAND",
    "KIND_LINT",
    "MAX_CHECKLIST_LINES",
    "GateResult",
    "GateRun",
    "OracleLeak",
    "assert_no_oracle",
    "checklist",
    "command_baseline",
    "derived_commands",
    "merge_commands",
    "verify",
]
