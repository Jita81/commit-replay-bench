"""Runner registry: ``RepoConfig.runner`` → runner instance.

Navigation
----------
What it is:   The runner registry — the closed table from a ``RepoConfig.runner`` name to the
              class that drives that toolchain — and the package's public re-exports.
What it does: ``get_runner`` builds the configured runner (``ValueError`` for an unknown name,
              so a typo in a repo config fails at load, not mid-sweep); ``runner_names`` lists
              what the UI and CLI may offer.
How:          A module-level ``dict`` keyed by the config string; construction passes the
              ``RepoConfig`` through unchanged.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         none
Works with:   src/crb/core/runners/base.py (the contract every entry honours),
              src/crb/core/spec.py (``RepoConfig.runner`` is the key), src/crb/core/mine.py and
              src/crb/core/grade.py (the callers), src/crb/server/worker.py (binds ``env_dir``
              after construction)
Tested by:    tests/test_runners_parsers.py, tests/test_runners_setup.py
Touch when:   never for a new repository (pick a name from ``runner_names()`` in the repo
              config); adding a language runner means one new entry here plus its module, a
              runner test module of its own (as tests/test_runners_go.py is for Go) and a line
              in docs/OPERATOR.md.
"""

from __future__ import annotations

from crb.core.runners.base import (
    BARE,
    BaseRunner,
    SetupResult,
    SetupStep,
    TestRun,
    TestRunner,
    parse_pytest_failures,
    tail_of,
)
from crb.core.runners.cargo_runner import CargoRunner
from crb.core.runners.go_runner import GoRunner
from crb.core.runners.jvm_runner import MavenRunner
from crb.core.runners.node_runners import JestRunner, MochaRunner, NodeTestRunner, VitestRunner
from crb.core.runners.pytest_runner import PytestRunner
from crb.core.spec import RepoConfig

_REGISTRY: dict[str, type[BaseRunner]] = {
    "pytest": PytestRunner,
    "go": GoRunner,
    "node": NodeTestRunner,
    "vitest": VitestRunner,
    "jest": JestRunner,
    "mocha": MochaRunner,
    "maven": MavenRunner,
    "cargo": CargoRunner,
}


def get_runner(config: RepoConfig) -> BaseRunner:
    """The runner ``config.runner`` names, constructed on ``config``; ``ValueError`` otherwise."""
    try:
        cls = _REGISTRY[config.runner]
    except KeyError as e:
        raise ValueError(f"no runner registered for {config.runner!r}") from e
    return cls(config)


def runner_names() -> tuple[str, ...]:
    """Every registered name, in registry order (what a config may set ``runner`` to)."""
    return tuple(_REGISTRY)


__all__ = [
    "BARE",
    "BaseRunner",
    "CargoRunner",
    "GoRunner",
    "JestRunner",
    "MavenRunner",
    "MochaRunner",
    "NodeTestRunner",
    "PytestRunner",
    "SetupResult",
    "SetupStep",
    "TestRun",
    "TestRunner",
    "VitestRunner",
    "get_runner",
    "parse_pytest_failures",
    "runner_names",
    "tail_of",
]
