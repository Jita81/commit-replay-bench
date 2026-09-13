"""The builder contract: what a builder is told, what it may spend, what it returns.

A *builder* is the thing under measurement — a model plus a process (one-shot
edit blocks, an in-process tool loop, an agentic CLI) — that is handed a
:class:`~crb.core.workspace.Workspace` at the commit's parent and asked to
reproduce the commit's source change. The grader, not the builder, decides
whether it succeeded. Everything here is designed so a builder *cannot*
short-cut the grade:

* :class:`BuildBrief` carries the commit **message** and (in sighted mode) the
  visible target tests. It carries **no** ``src_files`` — the builder must locate
  the code itself — and in blind mode it carries no test paths at all (enforced
  in ``__post_init__``: a blind brief with test paths cannot be constructed).
* :class:`Budget` bounds turns, tool calls, tokens, dollars and wall clock; every
  adapter stops on the first cap hit and records *which* cap in
  ``BuildOutcome.stop_reason``.
* :class:`BuildOutcome` reports the builder's **own claim** (``done``,
  ``summary``) explicitly labelled untrusted, plus metered spend and a redacted
  transcript. It never carries a verdict — :func:`crb.core.grade.grade` does.
* :class:`TestFileGuard` and :class:`GitArchaeologyGuard` are the shared
  input-mistake-proofing every adapter applies: a write to a protected test path,
  a path outside the worktree, a ``.git/`` write, a ``git log``/``show``/…
  to recover the real patch, or a network fetch is refused *before* it happens
  (tool loops) or flagged after the fact (subprocess agents). The grader's belts
  remain the authority — these guards only stop honest mistakes early and turn
  dishonest ones into recorded protocol violations.

Every string that reaches an outcome passes through :mod:`crb.core.redact`.
"""

from __future__ import annotations

import contextlib
import posixpath
import re
import shlex
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from crb.core.evidence import BuilderRef
from crb.core.grade import MODE_BLIND, MODE_SIGHTED, MODES
from crb.core.redact import redact_and_cap
from crb.core.spec import Language, RepoConfig, TaskSpec
from crb.core.workspace import Workspace

EventFn = Callable[[str, Mapping[str, Any]], None]


def emit(on_event: EventFn | None, action: str, **payload: Any) -> None:
    """Fire a structured event if a sink was supplied (never raises into the loop)."""
    if on_event is None:
        return
    with contextlib.suppress(Exception):  # an observer must never break a build
        on_event(action, payload)


# ---------------------------------------------------------------------------
# Rules (the census wf_wave.js contract, adapted)
# ---------------------------------------------------------------------------

#: The protocol every builder is told. Violations are recorded and disqualify.
DEFAULT_RULES = """RULES (violations disqualify the run):
- NEVER modify, delete, or add any test files. Source files only.
- Work only inside the worktree you were given.
- Do not use git to look at other commits or history to recover the real change: no git log, git show, git reflog, git stash, git bisect, git checkout/switch of another revision, no git diff against another revision.
- NEVER consult external sources for this change: no fetching the upstream repository, no package-registry downloads, no web lookups of the project's history or PRs. Solving by finding the real commit's diff anywhere is a DISQUALIFYING protocol violation. Solve from the local code (and, when they are present, the failing tests) only.
- Keep the change minimal and idiomatic to the codebase; do not break neighbouring behaviour."""


# ---------------------------------------------------------------------------
# Brief
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BuildBrief:
    """What the builder is told. Deliberately does NOT carry the commit's source paths.

    Attributes
    ----------
    subject / message:
        The commit subject and (optionally longer) commit message — the human
        description of the change. This is the *only* description in blind mode.
    repo / language:
        Ledger keys, surfaced so prompts can say "a Python repository".
    mode:
        ``sighted`` — the target test files are overlaid in the worktree and
        listed in ``test_files``; the builder may read and run them but not edit
        them. ``blind`` — the held-out tests are NOT in the worktree and their
        paths are not disclosed; ``test_files`` and ``target_tests`` must be empty.
    test_files / target_tests:
        Sighted only: the visible, immutable oracle files and the runner scope.
    test_command:
        Sighted only: a human-readable command the builder can run to see the
        failures (agentic adapters run it through the injected runner instead).
    spec_text / spec_facts:
        Optional structured specification (structural facts only — never a diff,
        never a file list of the real patch). Empty by default: the bare-message
        floor is the measured baseline.
    rules:
        The protocol text (see :data:`DEFAULT_RULES`).
    config:
        The repo's layout (source/test prefixes, runner). Public structure, not
        the patch; the guards use ``config.is_test`` and the sighted test tool
        uses ``config.runner``. When omitted a minimal config is derived from
        ``repo`` + ``language`` (guards then protect only ``test_files``).
    """

    subject: str
    message: str
    repo: str
    language: str
    mode: str = MODE_SIGHTED
    test_files: tuple[str, ...] = ()
    target_tests: tuple[str, ...] = ()
    test_command: str = ""
    spec_text: str = ""
    spec_facts: tuple[str, ...] = ()
    rules: str = DEFAULT_RULES
    config: RepoConfig | None = None

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        for attr in ("test_files", "target_tests", "spec_facts"):
            object.__setattr__(self, attr, tuple(str(x) for x in getattr(self, attr)))
        if self.mode == MODE_BLIND and (self.test_files or self.target_tests or self.test_command):
            raise ValueError(
                "a blind brief must not disclose test paths or a test command — the oracle is held out"
            )
        if not self.subject.strip():
            raise ValueError("a brief needs a non-empty subject")
        object.__setattr__(self, "message", self.message or self.subject)

    def repo_config(self) -> RepoConfig:
        if self.config is not None:
            return self.config
        return RepoConfig(name=self.repo or "repo", language=Language.parse(self.language or "py"))

    @property
    def sighted(self) -> bool:
        return self.mode == MODE_SIGHTED

    @property
    def blind(self) -> bool:
        return self.mode == MODE_BLIND

    @classmethod
    def from_task(
        cls,
        task: TaskSpec,
        *,
        mode: str = MODE_SIGHTED,
        message: str = "",
        test_command: str = "",
        spec_text: str = "",
        spec_facts: Sequence[str] = (),
        rules: str = DEFAULT_RULES,
        config: RepoConfig | None = None,
    ) -> BuildBrief:
        """Derive a brief from a task. ``task.src_files`` is never copied over.

        In blind mode the test paths are dropped here, by construction, so an
        orchestrator cannot leak them by accident.
        """
        blind = mode == MODE_BLIND
        return cls(
            subject=task.subject,
            message=message or task.subject,
            repo=task.repo,
            language=task.language,
            mode=mode,
            test_files=() if blind else tuple(task.test_files),
            target_tests=() if blind else tuple(task.target_tests),
            test_command="" if blind else test_command,
            spec_text=spec_text,
            spec_facts=tuple(spec_facts),
            rules=rules,
            config=config,
        )

    def task_text(self, *, worktree: str = "") -> str:
        """The task statement in the census ``wf_wave.js`` shape (rules included)."""
        where = f" at: {worktree}" if worktree else ""
        lines = [
            f"You are completing a real code change in a git worktree{where}.",
            f"The repository ({self.repo}, {self.language}) previously had a commit titled: "
            f'"{self.subject}"',
        ]
        if self.message.strip() and self.message.strip() != self.subject.strip():
            lines += ["The full commit message was:", "", self.message.strip(), ""]
        if self.sighted:
            lines.append(
                "That commit's TEST changes are already applied in the worktree, but its "
                "SOURCE changes are missing — so the target tests currently FAIL. Your job: "
                "implement the source change so the tests pass."
            )
            lines.append(
                "Target test files (read them — they are the executable spec; never edit them):"
            )
            lines += [f"  - {t}" for t in self.test_files]
            if self.test_command:
                lines.append(f"Run the target tests with: {self.test_command}")
        else:
            lines.append(
                "That commit's SOURCE changes are missing from the worktree, and its tests are "
                "held out — you will be graded against tests you cannot see. Implement the "
                "change the commit message describes, completely and idiomatically."
            )
        if self.spec_text.strip():
            lines += [
                "",
                "Specification (structural facts about the change):",
                self.spec_text.strip(),
            ]
        if self.spec_facts:
            lines += ["", "Known facts:"] + [f"  - {f}" for f in self.spec_facts]
        lines += ["", self.rules]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "message": self.message,
            "repo": self.repo,
            "language": self.language,
            "mode": self.mode,
            "test_files": list(self.test_files),
            "target_tests": list(self.target_tests),
            "test_command": self.test_command,
            "spec_text": self.spec_text,
            "spec_facts": list(self.spec_facts),
            "rules": self.rules,
            "config": self.config.to_dict() if self.config else None,
        }


# ---------------------------------------------------------------------------
# Budget + escalation ladder
# ---------------------------------------------------------------------------

STOP_DONE = "done"
STOP_MAX_TURNS = "max_turns"
STOP_MAX_TOOL_CALLS = "max_tool_calls"
STOP_MAX_TOKENS = "max_tokens"
STOP_MAX_COST = "max_cost_usd"
STOP_WALL_CLOCK = "wall_clock"
STOP_MODEL_ERROR = "model_error"
STOP_NO_TOOL_CALL = "no_tool_call"
STOP_REASONS: tuple[str, ...] = (
    STOP_DONE,
    STOP_MAX_TURNS,
    STOP_MAX_TOOL_CALLS,
    STOP_MAX_TOKENS,
    STOP_MAX_COST,
    STOP_WALL_CLOCK,
    STOP_MODEL_ERROR,
    STOP_NO_TOOL_CALL,
)


@dataclass(frozen=True)
class Budget:
    """Hard caps for one build attempt. ``0`` means "no cap" for tokens/cost only;
    turns, tool calls and wall clock are always bounded (a loop with no bound is a bug)."""

    max_turns: int = 25
    max_tool_calls: int = 25
    max_tokens: int = 0
    max_cost_usd: float = 0.0
    wall_clock_s: int = 900

    def __post_init__(self) -> None:
        if self.max_turns <= 0:
            raise ValueError("max_turns must be positive")
        if self.max_tool_calls <= 0:
            raise ValueError("max_tool_calls must be positive")
        if self.wall_clock_s <= 0:
            raise ValueError("wall_clock_s must be positive")
        if self.max_tokens < 0 or self.max_cost_usd < 0:
            raise ValueError("max_tokens / max_cost_usd cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_turns": self.max_turns,
            "max_tool_calls": self.max_tool_calls,
            "max_tokens": self.max_tokens,
            "max_cost_usd": self.max_cost_usd,
            "wall_clock_s": self.wall_clock_s,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Budget:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass(frozen=True)
class Rung:
    """One (builder, model) step of an escalation ladder."""

    builder: str
    model: str
    provider: str = ""
    config: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.builder or not self.model:
            raise ValueError("a rung needs a builder name and a model id")
        object.__setattr__(self, "config", dict(self.config))

    @property
    def label(self) -> str:
        return f"{self.builder}:{self.model}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "builder": self.builder,
            "model": self.model,
            "provider": self.provider,
            "config": dict(self.config),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Rung:
        return cls(
            builder=str(d["builder"]),
            model=str(d["model"]),
            provider=str(d.get("provider", "")),
            config=dict(d.get("config") or {}),
        )


@dataclass(frozen=True)
class EscalationLadder:
    """Ordered rungs to try when a rung's grade is not clean.

    Consumed by the run orchestrator — a builder only ever sees one rung. Each
    rung's trial is graded and ledgered separately; the ladder does not change
    any verdict, it only decides what to try next.
    """

    rungs: tuple[Rung, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "rungs", tuple(self.rungs))
        if not self.rungs:
            raise ValueError("a ladder needs at least one rung")

    def __len__(self) -> int:
        return len(self.rungs)

    def __iter__(self) -> Iterator[Rung]:
        return iter(self.rungs)

    @property
    def first(self) -> Rung:
        return self.rungs[0]

    def next_after(self, rung: Rung) -> Rung | None:
        for i, r in enumerate(self.rungs):
            if r == rung:
                return self.rungs[i + 1] if i + 1 < len(self.rungs) else None
        raise ValueError(f"rung {rung.label} is not on this ladder")

    def to_dict(self) -> dict[str, Any]:
        return {"rungs": [r.to_dict() for r in self.rungs]}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> EscalationLadder:
        return cls(tuple(Rung.from_dict(r) for r in d.get("rungs", ())))


# ---------------------------------------------------------------------------
# Outcome
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BuildOutcome:
    """What a builder reports back. ``done`` and ``summary`` are the builder's OWN
    CLAIM and are untrusted: the grader decides. Everything else is metered."""

    builder: str
    model: str
    provider: str
    mode: str
    done: bool = False
    summary: str = ""
    turns: int = 0
    tool_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    attempts: int = 1
    stop_reason: str = ""
    errors: tuple[str, ...] = ()
    transcript: tuple[Mapping[str, Any], ...] = ()
    budget: Budget | None = None
    cost_known: bool = True
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if self.stop_reason and self.stop_reason not in STOP_REASONS:
            raise ValueError(f"stop_reason {self.stop_reason!r} not in {STOP_REASONS}")
        object.__setattr__(self, "summary", redact_and_cap(self.summary, max_chars=4000))
        object.__setattr__(
            self, "errors", tuple(redact_and_cap(e, max_chars=2000) for e in self.errors)
        )
        object.__setattr__(self, "transcript", tuple(dict(e) for e in self.transcript))
        object.__setattr__(self, "extra", dict(self.extra))

    @property
    def violated(self) -> bool:
        """Any recorded protocol violation (tamper, archaeology, network)."""
        return any(e.startswith(("tamper:", "archaeology:", "network:")) for e in self.errors)

    def builder_ref(self, *, transcript_ref: str = "") -> BuilderRef:
        """The evidence-pack view of this outcome (no transcript inline, ever)."""
        note = self.stop_reason
        if self.errors:
            note = (note + "; " if note else "") + f"{len(self.errors)} error(s)"
        if not self.cost_known:
            note = (note + "; " if note else "") + "cost unknown (no pricing for model)"
        return BuilderRef(
            name=self.builder,
            model=self.model,
            provider=self.provider,
            mode=self.mode,
            attempts=self.attempts,
            turns=self.turns,
            tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
            tokens_cached=self.tokens_cached,
            cost_usd=self.cost_usd,
            latency_s=self.latency_s,
            transcript_ref=transcript_ref,
            budget=self.budget.to_dict() if self.budget else {},
            note=note,
        )

    def to_dict(self, *, include_transcript: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "builder": self.builder,
            "model": self.model,
            "provider": self.provider,
            "mode": self.mode,
            "claim": {"done": self.done, "summary": self.summary, "trusted": False},
            "turns": self.turns,
            "tool_calls": self.tool_calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "tokens_cached": self.tokens_cached,
            "cost_usd": round(self.cost_usd, 6),
            "cost_known": self.cost_known,
            "latency_s": round(self.latency_s, 3),
            "attempts": self.attempts,
            "stop_reason": self.stop_reason,
            "errors": list(self.errors),
            "budget": self.budget.to_dict() if self.budget else None,
            "extra": dict(self.extra),
        }
        if include_transcript:
            d["transcript"] = [dict(e) for e in self.transcript]
        return d


# ---------------------------------------------------------------------------
# Builder protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Builder(Protocol):
    name: str
    model: str
    provider: str

    def build(
        self,
        workspace: Workspace,
        brief: BuildBrief,
        budget: Budget,
        *,
        on_event: EventFn | None = None,
    ) -> BuildOutcome: ...

    def describe(self) -> dict[str, Any]:
        """Apparatus-stamp description (no secrets)."""
        ...


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


class GuardRefused(PermissionError):
    """A guard refused an action. The message is safe to show to the model."""


def _norm_rel(rel: str) -> str:
    """Normalise a repo-relative path the way git would print it (``""`` for empty/``.``)."""
    if not rel or not rel.strip():
        return ""
    norm = posixpath.normpath(rel.replace("\\", "/").strip())
    return "" if norm == "." else norm


class TestFileGuard:
    """Refuse writes that would move the goalposts or escape the worktree.

    Refused, in every mode:

    * any path that is absolute, contains ``..`` after normalisation, or resolves
      (following symlinks) outside the worktree root;
    * any path with a ``.git`` component (the worktree's ``.git`` file points at
      the main repository — writing there, or reading its objects, is archaeology);
    * every path in ``protected`` (the task's target test files);
    * every path the repo config classifies as a test (``RepoConfig.is_test``).
      In blind mode this is the belt-0 rule (any pre-overlay test touch is a
      DQ); in sighted mode it is stricter than the grader requires, and kept so
      because the gold patch never touches a test — a builder never needs to.

    Reads are refused only for traversal and ``.git``.
    """

    def __init__(
        self,
        root: Path,
        config: RepoConfig,
        protected: Iterable[str] = (),
        *,
        mode: str = MODE_SIGHTED,
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.root = Path(root).resolve()
        self.config = config
        self.protected = frozenset(_norm_rel(p) for p in protected)
        self.mode = mode

    # --- path safety -------------------------------------------------------------
    def check_path(self, rel: str) -> str:
        """Traversal / ``.git`` / absolute checks. Returns a reason, or ``""`` if safe."""
        if not rel or not isinstance(rel, str) or not rel.strip():
            return "empty path"
        raw = rel.replace("\\", "/")
        if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
            return f"absolute paths are not allowed: {rel!r}"
        norm = _norm_rel(raw)
        parts = norm.split("/")
        if ".." in parts or norm == "..":
            return f"path escapes the worktree: {rel!r}"
        if ".git" in parts:
            return f"'.git' is off limits: {rel!r}"
        try:
            resolved = (self.root / norm).resolve()
        except OSError as e:
            return f"cannot resolve {rel!r}: {type(e).__name__}"
        if resolved != self.root and self.root not in resolved.parents:
            return f"path resolves outside the worktree: {rel!r}"
        return ""

    def check_read(self, rel: str) -> str:
        return self.check_path(rel)

    def is_protected(self, rel: str) -> bool:
        norm = _norm_rel(rel)
        return norm in self.protected or self.config.is_test(norm)

    def check_write(self, rel: str) -> str:
        """Returns a reason the write is refused, or ``""`` if allowed."""
        reason = self.check_path(rel)
        if reason:
            return reason
        norm = _norm_rel(rel)
        if norm in self.protected:
            return f"REFUSED: {norm} is a target test file and is immutable"
        if self.config.is_test(norm):
            return f"REFUSED: {norm} is a test file — test files may not be edited or added"
        return ""

    def resolve_read(self, rel: str) -> Path:
        reason = self.check_read(rel)
        if reason:
            raise GuardRefused(reason)
        return self.root / _norm_rel(rel)

    def resolve_write(self, rel: str) -> Path:
        reason = self.check_write(rel)
        if reason:
            raise GuardRefused(reason)
        return self.root / _norm_rel(rel)

    # --- post-hoc -----------------------------------------------------------------
    def source_changes(self, ws: Workspace) -> list[str]:
        """Touched worktree files that are NOT tests — what the builder actually changed.
        (In sighted mode the overlaid oracle differs from the parent; it never counts.)"""
        return sorted(f for f in ws.touched_files() if not self.is_protected(f))

    def tampered(self, ws: Workspace) -> list[str]:
        """Post-hoc belt: protected target tests that are not byte-identical to the
        commit's own version (sighted), any protected path present at all (blind —
        it must not exist before the oracle is overlaid), and any other touched
        test-classified file in either mode."""
        out: set[str] = set()
        for f in ws.touched_files():
            norm = _norm_rel(f)
            if norm in self.protected:
                if self.mode == MODE_BLIND:
                    out.add(f)
            elif self.config.is_test(norm):
                out.add(f)
        if self.mode == MODE_SIGHTED and self.protected:
            _, offending = ws.tests_byte_identical(sorted(self.protected))
            out.update(offending)
        return sorted(out)


#: git sub-commands a builder may run inside the worktree. Everything else is
#: refused: the worktree shares the main clone's object store, so ``log``,
#: ``show``, ``reflog``, ``cat-file``… would reveal the very commit under test.
GIT_ALLOWED: frozenset[str] = frozenset(
    {"status", "diff", "ls-files", "grep", "add", "version", "help", "check-ignore"}
)

_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")
_REF_RE = re.compile(r"(@\{|~|\^|^refs/|^origin/|^upstream/|^HEAD@)")

#: Executables that reach the network (or install from it). The real belt is the
#: sandbox's ``--network=none``; this guard just refuses the obvious ones early.
NETWORK_TOOLS: frozenset[str] = frozenset(
    {
        "curl",
        "wget",
        "ssh",
        "scp",
        "sftp",
        "rsync",
        "nc",
        "ncat",
        "netcat",
        "telnet",
        "ftp",
        "http",
        "https",
        "aria2c",
        "gh",
        "glab",
        "hub",
    }
)

_NETWORK_SUBCOMMANDS: dict[str, frozenset[str]] = {
    "pip": frozenset({"install", "download", "wheel"}),
    "pip3": frozenset({"install", "download", "wheel"}),
    "uv": frozenset({"pip", "add", "sync", "tool", "run"}),
    "npm": frozenset({"install", "i", "ci", "add", "update", "exec", "npx"}),
    "npx": frozenset(),
    "yarn": frozenset({"install", "add", "up", "dlx"}),
    "pnpm": frozenset({"install", "i", "add", "dlx", "update"}),
    "go": frozenset({"get", "install"}),
    "cargo": frozenset({"add", "fetch", "install", "update", "publish"}),
    "mvn": frozenset({"dependency:get", "dependency:resolve", "deploy"}),
    "gradle": frozenset({"dependencies", "publish"}),
    "gem": frozenset({"install", "fetch"}),
    "bundle": frozenset({"install", "update"}),
    "apt": frozenset({"install", "update"}),
    "apt-get": frozenset({"install", "update"}),
    "brew": frozenset({"install", "update", "upgrade"}),
    "conda": frozenset({"install", "update"}),
    "poetry": frozenset({"add", "install", "update"}),
}

_WRAPPERS: frozenset[str] = frozenset({"env", "sudo", "nohup", "time", "command", "exec", "nice"})
_SHELLS: frozenset[str] = frozenset({"sh", "bash", "zsh", "dash", "fish", "ksh"})


class GitArchaeologyGuard:
    """Refuse commands that recover the real patch or leave the sandbox.

    ``check(argv)`` inspects one argv; ``check_shell(command)`` splits a shell
    command line on ``&&``, ``||``, ``;`` and ``|`` and checks every segment
    (unwrapping ``env``/``sudo``/``time`` and ``sh -c``). Returns a reason string
    prefixed ``archaeology:`` or ``network:`` — or ``""`` when allowed.
    """

    def check(self, argv: Sequence[str]) -> str:
        args = [str(a) for a in argv]
        # strip leading VAR=value assignments and wrappers
        while args and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", args[0]):
            args = args[1:]
        while args and Path(args[0]).name in _WRAPPERS:
            args = args[1:]
            while args and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", args[0]):
                args = args[1:]
        if not args:
            return ""
        exe = Path(args[0]).name
        if exe in _SHELLS and len(args) >= 3 and args[1] in {"-c", "-lc", "-ec"}:
            return self.check_shell(args[2])
        if exe == "eval":
            return "archaeology: 'eval' is not allowed"
        if exe in NETWORK_TOOLS:
            return f"network: '{exe}' is not allowed (no network access)"
        if exe == "git" or exe.startswith("git-"):
            return self._check_git(args[1:] if exe == "git" else [exe[4:], *args[1:]])
        if exe in _NETWORK_SUBCOMMANDS:
            subs = _NETWORK_SUBCOMMANDS[exe]
            tail = [a for a in args[1:] if not a.startswith("-")]
            if not subs or (tail and tail[0] in subs):
                return f"network: '{' '.join(args[:2])}' installs from the network"
            if exe in {"pip", "pip3"} and any(a == "-r" for a in args):
                return "network: 'pip -r' installs from the network"
        if exe in {"python", "python3"} and "-m" in args:
            i = args.index("-m")
            if i + 1 < len(args) and args[i + 1] in {"pip", "ensurepip"}:
                return (
                    self.check(["pip", *args[i + 2 :]]) or "network: 'python -m pip' is not allowed"
                )
        return ""

    def check_shell(self, command: str) -> str:
        """Split a shell command line on ``&&`` ``||`` ``;`` ``|`` ``&`` and check every
        segment. Sub-shells and command substitution (``(``, ``$(``, backticks) are
        refused outright: they can hide anything."""
        lex = shlex.shlex(command, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        try:
            tokens = list(lex)
        except ValueError:
            return "archaeology: could not parse the command safely"
        segments: list[list[str]] = [[]]
        for tok in tokens:
            if tok in {"&&", "||", ";", ";;", "|", "&", "|&"}:
                segments.append([])
                continue
            if tok in {"(", ")", "`", "$"} or tok.startswith(("$(", "`")):
                return "archaeology: sub-shells / command substitution are not allowed"
            if tok.startswith(("<", ">")):
                continue  # redirections
            segments[-1].append(tok)
        for seg in segments:
            r = self.check(seg)
            if r:
                return r
        return ""

    def _check_git(self, args: list[str]) -> str:
        # skip global options: -C <p>, -c k=v, --git-dir=…, --no-pager…
        i = 0
        while i < len(args) and args[i].startswith("-"):
            if args[i] in {"-C", "-c", "--git-dir", "--work-tree"}:
                i += 2
            else:
                i += 1
        if i >= len(args):
            return ""
        sub = args[i]
        rest = args[i + 1 :]
        if sub not in GIT_ALLOWED:
            return f"archaeology: 'git {sub}' is not allowed (no history/other revisions)"
        if sub == "diff":
            positional = [a for a in rest if not a.startswith("-")]
            if "--" in rest:
                positional = [a for a in rest[: rest.index("--")] if not a.startswith("-")]
            for a in positional:
                if a == "HEAD":
                    continue
                if _SHA_RE.match(a) or _REF_RE.search(a) or a in {"--all"}:
                    return f"archaeology: 'git diff {a}' compares against another revision"
            if "--all" in rest:
                return "archaeology: 'git diff --all' is not allowed"
        if sub == "grep" and any(re.match(r"^[0-9a-f]{7,64}$", a) for a in rest):
            return "archaeology: 'git grep <revision>' is not allowed"
        return ""


__all__ = [
    "DEFAULT_RULES",
    "GIT_ALLOWED",
    "NETWORK_TOOLS",
    "STOP_DONE",
    "STOP_MAX_COST",
    "STOP_MAX_TOKENS",
    "STOP_MAX_TOOL_CALLS",
    "STOP_MAX_TURNS",
    "STOP_MODEL_ERROR",
    "STOP_NO_TOOL_CALL",
    "STOP_REASONS",
    "STOP_WALL_CLOCK",
    "Budget",
    "BuildBrief",
    "BuildOutcome",
    "Builder",
    "EscalationLadder",
    "EventFn",
    "GitArchaeologyGuard",
    "GuardRefused",
    "Rung",
    "TestFileGuard",
    "emit",
]
