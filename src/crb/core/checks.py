"""``RepoConfig.checks`` — the ONE per-repository switchboard for "clean means working".

Three mechanisms make a clean row mean working software by construction (ADR-0024):

* ``format_step`` — after the builder finishes and before the grade, the repository's OWN
  formatter rewrites the changed source files, so the graded patch is the formatted one
  (:mod:`crb.core.formatting`);
* ``finish_gate`` — the brief carries the repository's own check commands as a short
  checklist, and the attempt is not ``done`` until the harness re-runs them and they pass
  (one bounded repair turn when they do not) — the verify-repair lever;
* ``api_stable`` — belt 6 (:mod:`crb.core.api_surface`): the public API of the changed
  units is unchanged unless the maintainers' commit changes it the same way.

Each is OFF by default until a paired A/B measures it, and each can be switched on for ONE
run (``params.checks``) or for the REPOSITORY (``RepoConfig.checks``, written through
``PUT /repos/{name}``, whose diff is appended to the repository's audit trail). The run
beats the repository, the repository beats the default. Every row records the resolved
switches, where each came from and the configuration version it saw (the ``checks``
label). The format step and belt 6 change what the grader judges, so they make the row's
ARM (``off``, ``fmt``, ``api``, ``fmt,api``), and rows of two arms never share a cell
(``crb.core.ledger.rows_for_checks``; ADR-0024 §6).

This module is the surface the prevention loop writes: to switch a mechanism on for a
repository whose failure class recurs, it writes this block — nothing else.

The shape (every key optional)::

    checks:
      format_step: true            # run the repo's formatter before grading
      finish_gate: true            # checklist in the brief + verify + one repair turn
      api_stable: true             # belt 6
      finish_repair_turns: 1       # 0–3 bounded repair calls in the finish gate
      formatter: {command: [black, -q], exts: [.py]}   # declare, or {disabled: true}
      commands:                    # the repository's own extra check commands
        - {name: vet, argv: [go, vet, ./...]}
        - {name: test, argv: [go, test, ./...], blind_only: true, timeout: 900}

Navigation
----------
What it is:   The per-repository check configuration (``RepoChecks``), its per-run resolution
              (``resolve`` → ``ResolvedChecks``) and the declared check commands
              (``CheckCommand``) — the one surface the prevention loop switches.
What it does: Validates the ``checks`` block (unknown key or wrong type → ``ValueError`` at
              config time); resolves each switch run > repository > default OFF and names the
              source; hashes the block into a configuration version; renders the row label;
              names the arm a run's rows pool in and reads it back from a row's label.
How:          ``RepoChecks.from_config`` parses and validates; ``resolve`` overlays
              ``params.checks``; ``ResolvedChecks.label`` is what the adapter stamps on every
              attempt's row.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0024-working-by-construction.md
Works with:   src/crb/core/spec.py (``RepoConfig.checks`` holds the raw block and validates it
              here), src/crb/core/formatting.py (the format step), src/crb/core/api_surface.py
              (belt 6), src/crb/builders/adapter.py (applies the switches around the build),
              src/crb/server/worker.py (resolves the run against the repository),
              src/crb/server/schemas.py (the API shapes that write it)
Tested by:    tests/test_checks.py, tests/test_builders_finish_gate.py,
              tests/test_checks_pooling.py
Touch when:   onboarding a repository whose check commands the runner cannot derive — declare
              them under ``checks.commands`` (docs/OPERATOR.md); adding a switch needs a test
              here, a line in docs/adr/0024-working-by-construction.md and the row label.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

#: The three switches, in the order the row label names them.
SWITCHES: tuple[str, ...] = ("format_step", "finish_gate", "api_stable")
#: Short names used in the row label.
_SHORT: dict[str, str] = {"format_step": "fmt", "finish_gate": "gate", "api_stable": "api"}

SOURCE_RUN = "run"
SOURCE_REPO = "repo"
SOURCE_DEFAULT = "default"

#: The row label every attempt carries (hashed, like every label).
LABEL_CHECKS = "checks"

#: The ARM a row pools under — the switches that change what the GRADER judges: the format
#: step (the graded patch is the formatted one) and belt 6 (a sixth belt). Rows of two arms
#: never share a cell (ADR-0024 "Apparatus impact"; ``crb.core.ledger.rows_for_checks``). The
#: finish gate is not on the arm: it changes what the builder does before it says done, and the
#: belts, not the gate, decide clean — it pools like the budget profile and the playbook lines.
ARM_SWITCHES: tuple[str, ...] = ("format_step", "api_stable")
#: The arm of a row graded with neither switch on — every row written before the switchboard.
ARM_OFF = "off"
#: Every arm, in order; the words the ``checks`` read filter accepts.
ARMS: tuple[str, ...] = (ARM_OFF, "fmt", "api", "fmt,api")

_KEYS: frozenset[str] = frozenset({*SWITCHES, "commands", "formatter", "finish_repair_turns"})
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
MAX_COMMANDS = 8
MAX_REPAIR_TURNS = 3
DEFAULT_CHECK_TIMEOUT_S = 600


def arm_of(*, format_step: bool, api_stable: bool) -> str:
    """The arm a row graded under these switches pools in (:data:`ARMS`)."""
    on = [_SHORT[s] for s, v in (("format_step", format_step), ("api_stable", api_stable)) if v]
    return ",".join(on) or ARM_OFF


def arm_from_label(label: str, *, belt6_recorded: bool = False) -> str:
    """The arm a row's ``checks`` stamp names (``""`` — no stamp — is :data:`ARM_OFF`).
    ``belt6_recorded``: the row carries belt 6's own label, so belt 6 was on whatever the
    stamp says."""
    fields = dict(p.split("=", 1) for p in label.split(";") if "=" in p)

    def on(short: str) -> bool:
        return fields.get(short, "0").split(":", 1)[0] == "1"

    return arm_of(format_step=on("fmt"), api_stable=on("api") or belt6_recorded)


def _bool(value: Any, what: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"checks.{what} must be true or false, got {value!r}")
    return value


@dataclass(frozen=True)
class CheckCommand:
    """One of the repository's own check commands (``go vet ./...``, ``npm run
    lint:types``, the test suite). ``blind_only``: shown and enforced only for a blind
    attempt — a sighted brief already carries the target test command. The command runs
    in the worktree root; it must not need the network."""

    name: str
    argv: tuple[str, ...]
    blind_only: bool = False
    timeout: int = DEFAULT_CHECK_TIMEOUT_S

    def __post_init__(self) -> None:
        if not _NAME_RE.match(self.name):
            raise ValueError(f"checks.commands: name {self.name!r} must be [a-z0-9_-], ≤32")
        argv: Any = self.argv  # a caller may pass a str despite the annotation
        if isinstance(argv, str) or not argv:
            raise ValueError(f"checks.commands[{self.name}]: argv must be a non-empty list")
        object.__setattr__(self, "argv", tuple(str(a) for a in self.argv))
        if not 0 < int(self.timeout) <= 3600:
            raise ValueError(f"checks.commands[{self.name}]: timeout must be 1 to 3600 s")

    @property
    def display(self) -> str:
        """The command as the checklist shows it."""
        return " ".join(self.argv)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "argv": list(self.argv),
            "blind_only": self.blind_only,
            "timeout": self.timeout,
        }

    @classmethod
    def from_dict(cls, d: Any) -> CheckCommand:
        if not isinstance(d, Mapping):
            raise ValueError("checks.commands entries must be objects")
        unknown = set(d) - {"name", "argv", "blind_only", "timeout"}
        if unknown:
            raise ValueError(f"checks.commands: unknown key(s) {sorted(unknown)}")
        argv = d.get("argv")
        if isinstance(argv, str) or not isinstance(argv, (list, tuple)):
            raise ValueError("checks.commands: argv must be a list of strings, not a string")
        return cls(
            name=str(d.get("name", "")),
            argv=tuple(str(a) for a in argv),
            blind_only=_bool(d.get("blind_only", False), "commands.blind_only"),
            timeout=int(d.get("timeout", DEFAULT_CHECK_TIMEOUT_S)),
        )


@dataclass(frozen=True)
class RepoChecks:
    """The validated ``RepoConfig.checks`` block (every switch OFF by default)."""

    format_step: bool = False
    finish_gate: bool = False
    api_stable: bool = False
    commands: tuple[CheckCommand, ...] = ()
    formatter: Mapping[str, Any] = field(default_factory=dict)
    finish_repair_turns: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "commands", tuple(self.commands))
        object.__setattr__(self, "formatter", dict(self.formatter))
        if len(self.commands) > MAX_COMMANDS:
            raise ValueError(f"checks.commands: at most {MAX_COMMANDS} commands")
        names = [c.name for c in self.commands]
        if len(set(names)) != len(names):
            raise ValueError("checks.commands: names must be unique")
        if not 0 <= self.finish_repair_turns <= MAX_REPAIR_TURNS:
            raise ValueError(f"checks.finish_repair_turns must be 0 to {MAX_REPAIR_TURNS}")
        fmt = self.formatter
        if fmt and not fmt.get("disabled"):
            command = fmt.get("command")
            if isinstance(command, str) or not command:
                raise ValueError("checks.formatter.command must be a non-empty argv list")
            unknown = set(fmt) - {"command", "exts", "name", "disabled"}
            if unknown:
                raise ValueError(f"checks.formatter: unknown key(s) {sorted(unknown)}")

    @classmethod
    def from_config(cls, raw: Mapping[str, Any] | None) -> RepoChecks:
        """Parse ``RepoConfig.checks`` — ``None`` / ``{}`` is the all-OFF default; an
        unknown key or a wrong type is a configuration error (``ValueError``), never a
        silent default."""
        if not raw:
            return cls()
        if not isinstance(raw, Mapping):
            raise ValueError("checks must be an object")
        unknown = set(raw) - _KEYS
        if unknown:
            raise ValueError(f"checks: unknown key(s) {sorted(unknown)}; expected {sorted(_KEYS)}")
        commands = raw.get("commands") or []
        if not isinstance(commands, (list, tuple)):
            raise ValueError("checks.commands must be a list")
        formatter = raw.get("formatter") or {}
        if not isinstance(formatter, Mapping):
            raise ValueError("checks.formatter must be an object")
        turns = raw.get("finish_repair_turns", 1)
        if isinstance(turns, bool) or not isinstance(turns, int):
            raise ValueError("checks.finish_repair_turns must be an integer")
        return cls(
            format_step=_bool(raw.get("format_step", False), "format_step"),
            finish_gate=_bool(raw.get("finish_gate", False), "finish_gate"),
            api_stable=_bool(raw.get("api_stable", False), "api_stable"),
            commands=tuple(CheckCommand.from_dict(c) for c in commands),
            formatter=dict(formatter),
            finish_repair_turns=turns,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_step": self.format_step,
            "finish_gate": self.finish_gate,
            "api_stable": self.api_stable,
            "commands": [c.to_dict() for c in self.commands],
            "formatter": dict(self.formatter),
            "finish_repair_turns": self.finish_repair_turns,
        }

    @property
    def is_default(self) -> bool:
        return self == RepoChecks()

    @property
    def version(self) -> str:
        """The configuration version a row saw: 12 hex of the block's canonical hash,
        ``default`` for the all-OFF block (so a reader can group rows by it)."""
        if self.is_default:
            return "default"
        # the canonical form evidence.canonical_json uses (not imported: spec → checks
        # must not pull the grader in)
        body = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class ResolvedChecks:
    """The switches one run applies, each with where it came from."""

    format_step: bool = False
    finish_gate: bool = False
    api_stable: bool = False
    sources: Mapping[str, str] = field(
        default_factory=lambda: dict.fromkeys(SWITCHES, SOURCE_DEFAULT)
    )
    repo: RepoChecks = field(default_factory=RepoChecks)

    def __post_init__(self) -> None:
        object.__setattr__(self, "sources", dict(self.sources))

    @property
    def any_on(self) -> bool:
        return self.format_step or self.finish_gate or self.api_stable

    @property
    def arm(self) -> str:
        """The arm this run's rows pool in — the word :func:`arm_from_label` reads back."""
        return arm_of(format_step=self.format_step, api_stable=self.api_stable)

    def label(self) -> str:
        """``fmt=1:repo;gate=0:default;api=1:run;cfg=<version>`` — the ``checks`` row label."""
        parts = [
            f"{_SHORT[s]}={int(bool(getattr(self, s)))}:{self.sources.get(s, SOURCE_DEFAULT)}"
            for s in SWITCHES
        ]
        return ";".join([*parts, f"cfg={self.repo.version}"])

    def to_dict(self) -> dict[str, Any]:
        return {
            **{s: bool(getattr(self, s)) for s in SWITCHES},
            "sources": dict(self.sources),
            "config_version": self.repo.version,
        }


def resolve(repo: RepoChecks, run_params: Mapping[str, Any] | None) -> ResolvedChecks:
    """Overlay ``params.checks`` (``{format_step?, finish_gate?, api_stable?}``) on the
    repository's block: the run beats the repository, the repository beats OFF. An
    unknown key in the run's block is refused (``ValueError``)."""
    run = dict(run_params or {})
    unknown = set(run) - set(SWITCHES)
    if unknown:
        raise ValueError(f"params.checks: unknown key(s) {sorted(unknown)}")
    values: dict[str, bool] = {}
    sources: dict[str, str] = {}
    for s in SWITCHES:
        if s in run and run[s] is not None:
            values[s] = _bool(run[s], s)
            sources[s] = SOURCE_RUN
        elif getattr(repo, s):
            values[s] = True
            sources[s] = SOURCE_REPO
        else:
            values[s] = False
            sources[s] = SOURCE_DEFAULT
    return ResolvedChecks(**values, sources=sources, repo=repo)


__all__ = [
    "ARMS",
    "ARM_OFF",
    "ARM_SWITCHES",
    "LABEL_CHECKS",
    "SOURCE_DEFAULT",
    "SOURCE_REPO",
    "SOURCE_RUN",
    "SWITCHES",
    "CheckCommand",
    "RepoChecks",
    "ResolvedChecks",
    "arm_from_label",
    "arm_of",
    "resolve",
]
