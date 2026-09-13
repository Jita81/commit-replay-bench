"""Runner registry: ``RepoConfig.runner`` → runner instance."""

from __future__ import annotations

from crb.core.runners.base import (
    BARE,
    BaseRunner,
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
    try:
        cls = _REGISTRY[config.runner]
    except KeyError as e:
        raise ValueError(f"no runner registered for {config.runner!r}") from e
    return cls(config)


def runner_names() -> tuple[str, ...]:
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
    "TestRun",
    "TestRunner",
    "VitestRunner",
    "get_runner",
    "parse_pytest_failures",
    "runner_names",
    "tail_of",
]
