"""Scripted executors for the builder-side tool check (``build_fn_for(tool_check_executor=…)``).

A test that seals its builder with a stand-in session has no builder image to probe: it
injects one of these so the check runs without a daemon, and asserts on what it was handed.

Navigation
----------
What it is:   The test-only executors for the tool check ``attempt_of`` runs before any
              builder call.
What it does: ``ScriptedExecutor`` answers every command with one ``ExecResult`` (or raises)
              and records what it was handed; ``passing_check`` is a ``tool_check_executor``
              whose builder environment carries the tool.
How:          A dataclass satisfying the ``Executor`` protocol; no process is started.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   src/crb/builders/adapter.py (``build_fn_for(tool_check_executor=…)``),
              src/crb/builders/toolcheck.py (the check it answers),
              src/crb/core/execution.py (the ``Executor`` protocol and ``ExecResult`` it fakes)
Tested by:    tests/test_builders_tool_check.py, tests/test_builders_adapter.py
Touch when:   never for a new repository; the Executor protocol changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from crb.core.execution import Command, ExecResult


@dataclass
class ScriptedExecutor:
    """Answers every command with ``result`` (or raises ``raises``) and records each one."""

    result: ExecResult = field(default_factory=lambda: ExecResult(0, "pytest 8.4.0\n", ""))
    raises: BaseException | None = None
    name: str = "scripted"
    seen: list[Command] = field(default_factory=list)

    def run(self, cmd: Command) -> ExecResult:
        self.seen.append(cmd)
        if self.raises is not None:
            raise self.raises
        return self.result

    def tool(self, name: str, host_override: str | None = None) -> str:
        return host_override or name

    def describe(self) -> dict[str, Any]:
        return {"name": self.name}

    def posture_facts(self) -> dict[str, str]:
        return {}


def passing_check(_settings: Any, _ws: Any) -> ScriptedExecutor:
    """A ``tool_check_executor`` whose builder environment carries the tool."""
    return ScriptedExecutor()


__all__ = ["ScriptedExecutor", "passing_check"]
