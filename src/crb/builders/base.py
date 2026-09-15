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

Navigation
----------
What it is:   The builder contract — ``BuildBrief`` (what a builder is told), ``Budget`` and
              the ``EscalationLadder`` (what it may spend), ``BuildOutcome`` (what it reports,
              claim labelled untrusted), the ``Builder`` protocol, and the two guards every
              adapter shares: ``TestFileGuard`` (paths) and ``GitArchaeologyGuard`` (shell).
What it does: Makes the short-cuts non-constructible: a blind brief cannot carry test paths,
              a budget cannot be unbounded, an outcome cannot carry a verdict; refuses a test
              write, a ``.git`` write, a path outside the worktree, git history, the shared
              stash, the network and package installs before they happen (tool loops) or
              records them after the fact (subprocess agents). The belts stay the authority.
How:          Frozen dataclasses with ``__post_init__`` invariants → the guards: path
              normalisation + symlink resolution for ``TestFileGuard``; for the shell guard,
              heredoc stripping → substitution hoisting → newline splitting → ``shlex`` →
              per-segment unwrap (wrappers, assignments, keywords) → per-executable rules
              (git verbs, package managers, inline-code scan).
Layer:        builders — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0004-builder-registry-sighted-and-blind.md,
              docs/adr/0012-builder-in-a-sealed-container.md
Works with:   src/crb/builders/adapter.py (turns a ``Builder`` into the core's ``BuildFn``),
              src/crb/builders/openai_agent.py and src/crb/builders/claude_code.py (the
              adapters that apply the guards), src/crb/core/workspace.py (the tree a builder
              edits and ``tests_byte_identical`` behind ``TestFileGuard.tampered``),
              src/crb/core/evidence.py (``BuilderRef`` — the pack view of an outcome),
              src/crb/core/grade.py (the verdict this module never produces),
              tests/fixtures/shell_corpus.txt (the honest-shell corpus the guard must pass)
Tested by:    tests/test_builders_base.py, tests/test_builders_guard_corpus.py
Touch when:   never for a new repository; a guard false positive on honest shell is fixed
              here AND added as a corpus line (tests/fixtures/shell_corpus.txt) first; a new
              stop reason or outcome field changes ``BuilderRef`` in src/crb/core/evidence.py
              and the ledger row; a change to ``DEFAULT_RULES`` is a measurement change
              (docs/EVIDENCE-AND-CLAIMS.md).
Claims:       A guard refusal is a recorded protocol violation, not a verdict; a guard pass
              is not a licence — belt 1 re-checks every test byte post hoc
              (docs/EVIDENCE-AND-CLAIMS.md).
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
from crb.core.redact import redact_and_cap, redact_and_cap_head
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
- Do not use git to look at other commits or history to recover the real change: no git log, git show, git blame, git reflog, git bisect, git checkout/switch of another revision, no git diff against another revision. No git stash in any form: the stash stack is shared with other trials — to run the tests without your edits use `git diff > /tmp/mine.patch; git checkout -- <paths>` and `git apply /tmp/mine.patch` after.
- NEVER consult external sources for this change: no fetching the upstream repository, no package-registry downloads, no web lookups of the project's history or PRs. Solving by finding the real commit's diff anywhere is a DISQUALIFYING protocol violation. Solve from the local code (and, when they are present, the failing tests) only.
- The test environment is ALREADY PROVISIONED. NEVER install or upgrade packages (no pip/uv/npm/yarn/pnpm install, go get, cargo add, mvn dependency:*; npx only for binaries already in node_modules/.bin): if the tests cannot import the package, run them EXACTLY with the test command you were given — it sets the interpreter and PYTHONPATH/NODE_PATH for this worktree.
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
    #: The test HARNESS command without any target scope (interpreter, PYTHONPATH /
    #: NODE_PATH, runner binary and its fixed flags). Safe in blind mode: it discloses
    #: the provisioned environment, never which tests are held out. Without it a blind
    #: builder cannot import the package and reaches for `pip install` / `uv run`,
    #: which the no-network rule refuses — 6 of 8 NHS blind misses (2026-09-14).
    harness_command: str = ""
    spec_text: str = ""
    spec_facts: tuple[str, ...] = ()
    rules: str = DEFAULT_RULES
    config: RepoConfig | None = None
    #: Pre-flight repair (belt 5): the repository's own linter/formatter rejected the
    #: patch and the fixers could not clear it. Set on a SECOND, bounded build call: the
    #: builder is told the findings and asked to fix only those. Empty on a first build.
    repair_note: str = ""

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
        """The config the guards classify tests with — the attached one, else a minimal
        one derived from ``repo`` + ``language`` (then only ``test_files`` are protected)."""
        if self.config is not None:
            return self.config
        return RepoConfig(name=self.repo or "repo", language=Language.parse(self.language or "py"))

    @property
    def sighted(self) -> bool:
        """The target tests are in the worktree and listed (the census mode)."""
        return self.mode == MODE_SIGHTED

    @property
    def blind(self) -> bool:
        """The oracle is held out: no test paths, no test command."""
        return self.mode == MODE_BLIND

    @classmethod
    def from_task(
        cls,
        task: TaskSpec,
        *,
        mode: str = MODE_SIGHTED,
        message: str = "",
        test_command: str = "",
        harness_command: str = "",
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
            harness_command=harness_command,
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
            if self.harness_command:
                lines.append(
                    "The test environment is provisioned. Run any existing tests (or tests you "
                    f"write to check your work) with: {self.harness_command} <paths>"
                )
        if self.spec_text.strip():
            lines += [
                "",
                "Specification (structural facts about the change):",
                self.spec_text.strip(),
            ]
        if self.spec_facts:
            lines += ["", "Known facts:"] + [f"  - {f}" for f in self.spec_facts]
        if self.repair_note.strip():
            lines += [
                "",
                "REPAIR: your previous edits are in the worktree and the target tests pass, but "
                "the repository's OWN linter/formatter rejects the changed files. Fix ONLY these "
                "findings (no other changes, no new features, never touch tests):",
                self.repair_note.strip(),
            ]
        lines += ["", self.rules]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """The brief as recorded in a transcript / evidence pack (``harness_command`` is
        environment, not task, and is left out)."""
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
            **({"repair_note": self.repair_note} if self.repair_note else {}),
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
        """The caps as stored on an outcome / a ledger row."""
        return {
            "max_turns": self.max_turns,
            "max_tool_calls": self.max_tool_calls,
            "max_tokens": self.max_tokens,
            "max_cost_usd": self.max_cost_usd,
            "wall_clock_s": self.wall_clock_s,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Budget:
        """Inverse of :meth:`to_dict`; unknown keys are ignored, missing ones default."""
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
        """``builder:model`` — how a rung is named in notes and the UI."""
        return f"{self.builder}:{self.model}"

    def to_dict(self) -> dict[str, Any]:
        """The rung as stored in a run spec."""
        return {
            "builder": self.builder,
            "model": self.model,
            "provider": self.provider,
            "config": dict(self.config),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Rung:
        """Inverse of :meth:`to_dict` (``builder`` and ``model`` are required)."""
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
        """The rung every task starts on."""
        return self.rungs[0]

    def next_after(self, rung: Rung) -> Rung | None:
        """The rung to escalate to after ``rung``; ``None`` at the top; ``ValueError`` if
        ``rung`` is not on this ladder (an orchestrator bug, never silently the first)."""
        for i, r in enumerate(self.rungs):
            if r == rung:
                return self.rungs[i + 1] if i + 1 < len(self.rungs) else None
        raise ValueError(f"rung {rung.label} is not on this ladder")

    def to_dict(self) -> dict[str, Any]:
        """The ladder as stored in a run spec."""
        return {"rungs": [r.to_dict() for r in self.rungs]}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> EscalationLadder:
        """Inverse of :meth:`to_dict`; an empty ``rungs`` list is a ``ValueError``."""
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
            self, "errors", tuple(redact_and_cap_head(e, max_chars=2000) for e in self.errors)
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
        """The outcome as the worker stores it. The builder's claim is nested under
        ``claim`` with ``trusted: False`` so no reader can mistake it for a verdict; the
        transcript is opt-in (evidence packs reference it, never inline it)."""
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
    """What the registry hands out and the adapter wraps: ``build`` edits the workspace
    within ``budget`` and returns an outcome; ``describe`` is the apparatus stamp."""

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
    ) -> BuildOutcome:
        """Edit ``workspace`` as the brief asks, stopping on the first cap in ``budget``.
        Never raises for a model or protocol failure — it is recorded in the outcome."""
        ...

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
    * any path with a ``.git`` component — as written OR once resolved (a symlink
      ``gitlink -> .git`` reads the main clone's location and, written to, rewrites
      the worktree's gitdir pointer; independent review pass 2026-09-14, finding 6c).
      The worktree's ``.git`` file points at the main repository — writing there, or
      reading its objects, is archaeology;
    * every path in ``protected`` (the task's target test files);
    * every path the repo config classifies as a test (``RepoConfig.is_test``) — the
      path as written and the path it RESOLVES to (``t2 -> tests``: ``t2/test_x.py``
      is a test write). In blind mode this is the belt-0 rule (any pre-overlay test
      touch is a DQ); in sighted mode it is stricter than the grader requires, and
      kept so because the gold patch never touches a test — a builder never needs to.

    Reads are refused only for traversal and ``.git`` (as written or resolved).
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
        resolved_rel = self.resolved_rel(norm)
        if resolved_rel is None:
            return f"path resolves outside the worktree: {rel!r}"
        if ".git" in resolved_rel.split("/"):
            return f"'.git' is off limits: {rel!r} resolves to {resolved_rel!r}"
        return ""

    def resolved_rel(self, norm: str) -> str | None:
        """``norm`` with every symlink followed, as a worktree-relative POSIX path —
        ``""`` for the root itself, ``None`` when it resolves outside the worktree (or
        cannot be resolved)."""
        try:
            resolved = (self.root / norm).resolve()
        except (OSError, RuntimeError):
            return None
        if resolved == self.root:
            return ""
        if self.root not in resolved.parents:
            return None
        return resolved.relative_to(self.root).as_posix()

    def check_read(self, rel: str) -> str:
        """Reads are refused only for traversal and ``.git`` (tests may be read)."""
        return self.check_path(rel)

    def is_protected(self, rel: str) -> bool:
        """Is ``rel`` — as written, or as it resolves through symlinks — a target test
        file or a test-classified path?"""
        norm = _norm_rel(rel)
        if norm in self.protected or self.config.is_test(norm):
            return True
        resolved = self.resolved_rel(norm)
        if not resolved or resolved == norm:
            return False
        return resolved in self.protected or self.config.is_test(resolved)

    def check_write(self, rel: str) -> str:
        """Returns a reason the write is refused, or ``""`` if allowed. Classified on the
        path as written AND on what it resolves to (a symlinked directory into the
        test layout is the test layout)."""
        reason = self.check_path(rel)
        if reason:
            return reason
        norm = _norm_rel(rel)
        for candidate in (norm, self.resolved_rel(norm) or norm):
            if candidate in self.protected:
                return f"REFUSED: {candidate} is a target test file and is immutable"
            if self.config.is_test(candidate):
                return (
                    f"REFUSED: {candidate} is a test file — test files may not be edited or added"
                )
        return ""

    def resolve_read(self, rel: str) -> Path:
        """The absolute path for a permitted read, else :class:`GuardRefused`."""
        reason = self.check_read(rel)
        if reason:
            raise GuardRefused(reason)
        return self.root / _norm_rel(rel)

    def resolve_write(self, rel: str) -> Path:
        """The absolute path for a permitted write, else :class:`GuardRefused`."""
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


# ---------------------------------------------------------------------------
# Shell guard — vocabulary
# ---------------------------------------------------------------------------


def _words(text: str) -> frozenset[str]:
    """A whitespace-separated word list as a frozenset (keeps the vocabulary readable)."""
    return frozenset(text.split())


#: git sub-commands a builder may run inside the worktree. Several carry per-verb
#: rules in :class:`GitArchaeologyGuard` (``diff``/``grep`` may not name another
#: revision; ``checkout``/``restore`` only ever paths; ``rev-parse``/``config``
#: read-only). Everything else is refused: the worktree shares the main clone's
#: object store AND its stash stack, so ``log``, ``show``, ``reflog``, ``cat-file``,
#: ``stash``… would reveal the very commit under test or another trial's edits.
GIT_ALLOWED: frozenset[str] = _words(
    "status diff ls-files grep add version help check-ignore rev-parse config apply mv checkout "
    "restore"
)

#: git sub-commands that reach the network. Refused with the ``network:`` prefix
#: (not ``archaeology:``) so a refusal-rate split can tell "fetched upstream" from
#: "read history" — the review asks for instrument-vs-builder labelling.
_GIT_NETWORK: frozenset[str] = _words(
    "fetch pull push clone remote ls-remote submodule lfs request-pull send-email svn instaweb "
    "daemon"
)

_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")
_REF_RE = re.compile(r"(@\{|~|\^|\.\.|^refs/|^origin/|^upstream/|^remotes/|^tags/|^heads/|^HEAD@)")
#: Bare words that name a branch or symbolic ref far more often than a path. A
#: refname can never contain ``*``, ``?`` or ``[`` and never starts with ``:``, so
#: globs and pathspec magic are always paths.
_BRANCHISH: frozenset[str] = _words(
    "main master develop development dev trunk next release staging production prod stable canary @ "
    "FETCH_HEAD ORIG_HEAD MERGE_HEAD CHERRY_PICK_HEAD REBASE_HEAD AUTO_MERGE"
)

_GIT_VALUE_OPTS: dict[str, frozenset[str]] = {
    "diff": _words(
        "-S -G -O -l -U -I --unified --inter-hunk-context --word-diff-regex --diff-filter "
        "--src-prefix --dst-prefix --line-prefix --output --anchored --rotate-to --skip-to "
        "--find-object --ignore-matching-lines"
    ),
    "grep": _words("-e -f -A -B -C -m -O --max-depth --max-count --threads"),
    "checkout": frozenset({"--pathspec-from-file", "--conflict"}),
    "restore": frozenset({"--pathspec-from-file", "--conflict", "-s", "--source"}),
    "config": frozenset({"-f", "--file", "--type", "--default", "--blob"}),
}
_CHECKOUT_OK: frozenset[str] = _words(
    "-q --quiet -f --force -p --patch --ours --theirs -m --merge --overlay --no-overlay "
    "--ignore-skip-worktree-bits --progress --no-progress --recurse-submodules "
    "--no-recurse-submodules --pathspec-from-file --pathspec-file-nul --conflict"
)
_RESTORE_OK: frozenset[str] = _CHECKOUT_OK | frozenset(
    {"-W", "--worktree", "-S", "--staged", "--ignore-unmerged"}
)
_REV_PARSE_OK: frozenset[str] = _words(
    "--show-toplevel --show-prefix --show-cdup --is-inside-work-tree --is-inside-git-dir "
    "--is-bare-repository --is-shallow-repository --abbrev-ref --verify --short -q --quiet "
    "--symbolic-full-name --show-object-format --sq-quote --local-env-vars"
)
_CONFIG_READ: frozenset[str] = _words(
    "--get --get-all --get-regexp -l --list --get-urlmatch --get-color"
)
_CONFIG_WRITE: frozenset[str] = _words(
    "--add --unset --unset-all --replace-all --rename-section --remove-section -e --edit"
)

#: Executables that reach the network, leave the sandbox, or open a browser. The
#: real belt is the sandbox's ``--network=none``; this guard refuses the obvious
#: ones early so an honest mistake is a one-line refusal, not a lost build.
NETWORK_TOOLS: frozenset[str] = _words(
    "curl wget wget2 ssh scp sftp rsync nc ncat netcat socat telnet ftp http https xh httpie aria2c "
    "gh glab hub dig nslookup host ping traceroute mtr nmap whois lynx w3m links elinks xdg-open "
    "open docker podman nerdctl kubectl helm aws gcloud az rclone s3cmd gsutil uvx n pacman"
)

#: Package / toolchain managers → the sub-commands that install, fetch or mutate
#: the provisioned environment. Anything else they do (``list``, ``show``, ``run``,
#: ``test``…) is honest. The environment is ALREADY PROVISIONED; the rules say so.
_INSTALLERS: dict[str, frozenset[str]] = {
    "gem": frozenset({"install", "fetch", "update", "uninstall"}),
    "bundle": frozenset({"install", "update", "add", "remove"}),
    "bundler": frozenset({"install", "update", "add", "remove"}),
    "apt": _words("install update upgrade remove purge full-upgrade"),
    "apt-get": _words("install update upgrade remove purge dist-upgrade"),
    "aptitude": frozenset({"install", "update", "upgrade", "remove", "purge"}),
    "brew": _words("install update upgrade uninstall reinstall tap bundle"),
    "conda": _words("install update create remove uninstall env"),
    "mamba": _words("install update create remove uninstall env"),
    "micromamba": _words("install update create remove uninstall env"),
    "poetry": _words("add install update remove lock publish self"),
    "pipx": _words("install run runpip upgrade upgrade-all inject reinstall uninstall"),
    "pipenv": _words("install update sync lock uninstall upgrade"),
    "apk": frozenset({"add", "update", "upgrade", "del", "fetch"}),
    "dnf": frozenset({"install", "update", "upgrade", "remove", "makecache"}),
    "yum": frozenset({"install", "update", "upgrade", "remove", "makecache"}),
    "zypper": _words("install in update up remove rm refresh"),
    "snap": frozenset({"install", "refresh", "remove"}),
    "choco": frozenset({"install", "upgrade", "uninstall"}),
    "winget": frozenset({"install", "upgrade"}),
    "scoop": frozenset({"install", "update"}),
    "nvm": frozenset({"install", "upgrade"}),
    "pyenv": frozenset({"install", "update", "uninstall"}),
    "rustup": _words("update install toolchain target component self"),
    "sdk": frozenset({"install", "update", "selfupdate", "upgrade"}),
    "asdf": frozenset({"install", "plugin", "update"}),
    "volta": frozenset({"install", "fetch", "pin"}),
    "mise": _words("install i use u upgrade up self-update plugins"),
    "corepack": frozenset({"prepare", "use", "install", "up", "pack"}),
}
_PIP_REFUSED: frozenset[str] = _words("install download wheel index search uninstall")
_UV_PIP_OK: frozenset[str] = frozenset({"list", "freeze", "show", "tree", "check"})
_UV_OK: frozenset[str] = frozenset({"venv", "cache", "version", "help"})
_NPM_REFUSED: frozenset[str] = _words(
    "install i in ins inst insta instal isnt isnta isntal isntall add ci clean-install ic "
    "install-ci-test cit install-test it update up upgrade udpate uninstall un unlink remove rm r "
    "link ln dedupe ddp prune view v info show search s se find outdated audit publish unpublish "
    "deprecate dist-tag owner star stars unstar login logout adduser add-user whoami ping hook org "
    "team token access doctor create init innit fund docs home repo bugs issues diff edit profile "
    "sbom"
)
_YARN_REFUSED: frozenset[str] = _words(
    "install add remove up upgrade upgrade-interactive dlx link unlink import info npm set plugin "
    "dedupe outdated audit publish login logout global create init patch patch-commit"
)
_PNPM_REFUSED: frozenset[str] = _words(
    "install i add remove rm un uninstall update up upgrade link ln unlink dlx fetch import dedupe "
    "prune publish create init outdated audit setup self-update deploy patch patch-commit "
    "install-test it"
)
_PNPM_VALUE_OPTS: frozenset[str] = frozenset({"--filter", "-F", "-C", "--dir"})
_CARGO_ALWAYS: frozenset[str] = _words("install uninstall publish login logout owner yank search")
_CARGO_ONLINE: frozenset[str] = _words("add remove rm fetch update vendor generate-lockfile")
_MVN_VALUE_OPTS: frozenset[str] = _words(
    "-pl --projects -f --file -s --settings -gs --global-settings -t --toolchains -l --log-file -rf "
    "--resume-from -T --threads -b --builder"
)
_MVN_ONLINE_PREFIXES: tuple[str, ...] = (
    "dependency:",
    "archetype:",
    "versions:",
    "wrapper:",
    "release:",
    "scm:",
)
_GRADLE_VALUE_OPTS: frozenset[str] = _words(
    "--tests --project-dir -p -b --build-file -c --settings-file -g --gradle-user-home -I "
    "--init-script --console --max-workers --project-cache-dir"
)
_TOX_READONLY: frozenset[str] = _words(
    "-l --listenvs -a --listenvs-all --showconfig --version -h --help"
)
_NOX_READONLY: frozenset[str] = _words("-l --list --list-sessions --version -h --help")
_PRECOMMIT_READONLY: frozenset[str] = _words(
    "--version -V -h --help sample-config validate-config validate-manifest"
)

_PIP_RE = re.compile(r"^pip-?3?(\.\d+)?$")
_PYTHON_RE = re.compile(r"^(python|pypy)\d?(\.\d+)?$")
_ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")
#: ``__SUBST_k__`` stands for ``$( … )``/backticks (its output becomes text — as an
#: exe name that is a computed command), ``__GROUP_k__`` for a ``( … )`` sub-shell
#: (already checked; as a whole segment it runs nothing else).
_PLACEHOLDER_RE = re.compile(r"__(?:SUBST|GROUP)_(\d+)__")
_COMPUTED_RE = re.compile(r"__SUBST_\d+__")
_GROUP_RE = re.compile(r"^__GROUP_\d+__$")
_FUNCDEF_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*__GROUP_\d+__$")

#: Command prefixes that run *another* command: name → (options that take a value,
#: positionals to skip before the wrapped command — ``timeout DURATION cmd``).
_WRAPPERS: dict[str, tuple[frozenset[str], int]] = {
    "env": (_words("-u --unset -C --chdir -S --split-string"), 0),
    "sudo": (
        _words("-u --user -g --group -C -D --chdir -h --host -p -r -t -U"),
        0,
    ),
    "doas": (frozenset({"-u", "-C"}), 0),
    "nohup": (frozenset(), 0),
    "time": (frozenset({"-f", "--format", "-o", "--output"}), 0),
    "command": (frozenset(), 0),
    "builtin": (frozenset(), 0),
    "exec": (frozenset({"-a"}), 0),
    "nice": (frozenset({"-n", "--adjustment"}), 0),
    "ionice": (frozenset({"-c", "-n", "-p"}), 0),
    "stdbuf": (frozenset({"-i", "-o", "-e"}), 0),
    "unbuffer": (frozenset(), 0),
    "caffeinate": (frozenset({"-t", "-w"}), 0),
    "chronic": (frozenset(), 0),
    "timeout": (frozenset({"-k", "--kill-after", "-s", "--signal"}), 1),
    "watch": (frozenset({"-n", "--interval"}), 0),
    "parallel": (
        _words("-j --jobs -N -n --max-args -S --sshlogin --colsep --delay --results --tmpdir"),
        0,
    ),
    "xargs": (
        _words(
            "-I -i -n -L -l -P -d -s -E -a --max-args --max-procs --max-lines --max-chars "
            "--delimiter --eof --arg-file --replace --process-slot-var"
        ),
        0,
    ),
}
_SHELLS: frozenset[str] = _words("sh bash zsh dash fish ksh")
#: Environment variables that point git at ANOTHER repository / object store.
_GIT_ENV_REDIRECT: frozenset[str] = _words(
    "GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES "
    "GIT_INDEX_FILE GIT_NAMESPACE"
)
_EXPORTERS: frozenset[str] = _words("export declare typeset setenv")
#: Interpreters → the flags that carry INLINE CODE (``python -c``, ``node -e``). The code
#: string is scanned with :func:`_scan_code`; ``python -``/``node -`` read a heredoc, which
#: is scanned the same way.
_INLINE_FLAGS: dict[str, tuple[str, ...]] = {
    "python": ("-c",),
    "node": ("-e", "--eval", "-p", "--print"),
    "nodejs": ("-e", "--eval", "-p", "--print"),
    "deno": ("eval",),
    "bun": ("-e", "--eval", "-p", "--print"),
    "ruby": ("-e",),
    "perl": ("-e", "-E"),
    "php": ("-r",),
    "lua": ("-e",),
    "Rscript": ("-e",),
}
#: Inline-code scanning (2026-09-14, A8's human-review exercises): the guard used to
#: read only each segment's first word, so ``python -c "subprocess.run(['git','log'])"``
#: passed. Code is not parsed as shell (that would refuse honest one-liners); instead the
#: text is scanned for a git verb, a ``.git`` path or a network tool. Fail closed on a
#: ``git checkout``/``reset`` in code too — their argument forms cannot be verified there.
_CODE_SEP = r"[\s'\",\[\]()]*"
_CODE_GIT_HISTORY = re.compile(
    r"\bgit\b"
    + _CODE_SEP
    + r"(log|show|reflog|blame|stash|bisect|cat-file|rev-list|checkout|switch|worktree|"
    r"describe|branch|tag|shortlog|whatchanged|ls-tree|archive|format-patch|bundle|"
    r"name-rev|for-each-ref|cherry|notes|reset|revert|cherry-pick|rebase|merge|commit)\b"
)
_CODE_GIT_NETWORK = re.compile(
    r"\bgit\b" + _CODE_SEP + r"(fetch|pull|push|clone|remote|ls-remote|submodule|lfs)\b"
)
_CODE_GIT_DIFF_REV = re.compile(
    r"\bgit\b"
    + _CODE_SEP
    + r"diff\b[^\n;]*?(HEAD[~^@]|\b[0-9a-f]{7,40}\b|\b(main|master|develop)\b|origin/|\.\.)"
)
_CODE_GIT_DIR = re.compile(r"(^|[^\w.])\.git(/|['\"])")
_CODE_NET_TOOL = re.compile(
    r"\b(curl|wget|ssh|scp|sftp|rsync|ncat|netcat|telnet|aria2c)\b|\bgh\s+(pr|api|repo|issue)\b"
)
#: Shell keywords that precede a command in the same segment (``if git log; then``).
_KEYWORDS: frozenset[str] = _words("! if then else elif fi do done while until coproc")
#: Segments that are a loop/case HEADER, not a command (``for f in …``, ``case x in``).
_HEADERS: frozenset[str] = frozenset({"for", "case", "select", "esac", "in"})
_SEPARATORS: frozenset[str] = _words("&& || ; ;; | & |& ) { }")
_PIPES: frozenset[str] = frozenset({"|", "|&"})
#: Option names whose value is an EXCLUSION pattern — ``.git`` there is honest.
_PATH_EXCLUDE_OPTS: frozenset[str] = _words(
    "-path -ipath -wholename -iwholename -name -iname -regex -not ! -prune --exclude --exclude-dir "
    "--exclude-from -g --glob --iglob --ignore --ignore-dir --ignore-file -I -x --filter"
)


# ---------------------------------------------------------------------------
# Shell guard — parsing helpers (pure functions)
# ---------------------------------------------------------------------------


def _strip_heredocs(command: str) -> tuple[str, list[tuple[str, bool]]] | None:
    """Remove every here-document BODY from ``command`` (quote-aware, in the order
    the shell would read them) and return ``(rest, [(body, literal), …])``.

    ``literal`` is true for a quoted tag (``<<'EOF'``, ``<<"EOF"``, ``<<\\EOF``):
    the body is data and must not be parsed at all — an apostrophe in a Python
    comment written through ``cat <<'EOF' > repro.py`` refused an honest build
    (2026-09-13). For an unquoted tag the body still undergoes ``$( … )`` and
    backtick expansion, so the caller extracts those with
    :func:`_heredoc_body_inners`. ``None`` when a ``<<`` has no tag or an
    unterminated quoted tag (fail closed).
    """
    out: list[str] = []
    bodies: list[tuple[str, bool]] = []
    pending: list[tuple[str, bool, bool]] = []
    i, n = 0, len(command)
    quote = ""
    while i < n:
        ch = command[i]
        if quote == "'":
            if ch == "'":
                quote = ""
            out.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            out.append(command[i : i + 2])
            i += 2
            continue
        if ch == "'":
            quote = "'"
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            quote = "" if quote == '"' else '"'
            out.append(ch)
            i += 1
            continue
        if not quote and ch == "\n" and pending:
            out.append("\n")
            i += 1
            for tag, literal, strip_tabs in pending:
                lines: list[str] = []
                while i < n:
                    j = command.find("\n", i)
                    line = command[i:] if j < 0 else command[i:j]
                    i = n if j < 0 else j + 1
                    if (line.lstrip("\t") if strip_tabs else line) == tag:
                        break
                    lines.append(line)
                bodies.append(("\n".join(lines), literal))
            pending = []
            continue
        if (
            not quote
            and ch == "<"
            and command.startswith("<<", i)
            and not command.startswith("<<<", i)
            and (i == 0 or command[i - 1] != "<")
        ):
            j = i + 2
            strip_tabs = False
            if j < n and command[j] == "-":
                strip_tabs = True
                j += 1
            while j < n and command[j] in " \t":
                j += 1
            literal = False
            if j < n and command[j] in "'\"":
                q = command[j]
                k = command.find(q, j + 1)
                if k < 0:
                    return None
                tag, literal, j = command[j + 1 : k], True, k + 1
            else:
                if j < n and command[j] == "\\":
                    literal = True
                    j += 1
                k = j
                while k < n and not command[k].isspace() and command[k] not in ";|&<>()":
                    k += 1
                tag, j = command[j:k], k
            if not tag:
                return None
            out.append(command[i:j])
            pending.append((tag, literal, strip_tabs))
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out), bodies


def _heredoc_body_inners(body: str) -> list[str] | None:
    """``$( … )`` and backtick commands inside an UNQUOTED here-document body.
    Quotes are not special there (``it's $HOME`` is fine); only ``\\`` escapes."""
    inners: list[str] = []
    i, n = 0, len(body)
    while i < n:
        ch = body[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "`":
            j = body.find("`", i + 1)
            if j < 0:
                return None
            inners.append(body[i + 1 : j])
            i = j + 1
            continue
        if body.startswith("$(", i):
            end = _matching_paren(body, i + 2)
            if end < 0:
                return None
            inners.append(body[i + 2 : end])
            i = end + 1
            continue
        i += 1
    return inners


#: Private-use stand-ins for a QUOTED (or backslash-escaped) ``(`` / ``)`` / backtick.
#: :func:`_hoist_substitutions` emits them so that, after ``shlex`` has stripped the
#: quotes, a paren token can only ever be an UNQUOTED one — ``grep '('`` was refused as a
#: "stray sub-shell token" (independent review pass, 2026-09-14, finding 7) because
#: ``shlex`` returns ``(`` for both ``'('`` and a bare ``(``. Restored by
#: :func:`_unsentinel` once the token stream has been classified.
_LITERAL_PUNCT: dict[str, str] = {"(": "", ")": "", "`": ""}
_LITERAL_PUNCT_BACK: dict[str, str] = {v: k for k, v in _LITERAL_PUNCT.items()}
_LITERAL_PUNCT_RE = re.compile("[]")


def _unsentinel(token: str) -> str:
    """A token with its quoted-punctuation stand-ins turned back into the characters."""
    return _LITERAL_PUNCT_RE.sub(lambda m: _LITERAL_PUNCT_BACK[m.group(0)], token)


def _hoist_substitutions(command: str) -> tuple[str | None, list[str]]:
    """Replace every ``$( … )``, backtick and ``( … )`` sub-shell with a numbered
    placeholder ``__SUBST_k__`` and return the inner commands for recursive
    checking. ``None`` when unbalanced.

    Quoting is honoured the way ``sh`` does: inside single quotes nothing is special;
    inside double quotes only ``$( … )`` and backticks open a substitution, a bare
    ``(`` is literal (``grep "preRun(ctx"`` is an ordinary search, not a sub-shell);
    a backslash escapes the next character outside single quotes. Treating quoted
    parentheses as sub-shells refused an honest build on spf13/cobra.

    A quoted or escaped ``(`` / ``)`` / backtick is emitted as its :data:`_LITERAL_PUNCT`
    stand-in (the quotes themselves are kept), so the tokeniser downstream never sees a
    literal paren as punctuation — a lone ``'('`` argument is text, not a sub-shell."""
    inners: list[str] = []
    out: list[str] = []
    i, n = 0, len(command)
    quote = ""  # "", "'" or '"'
    while i < n:
        ch = command[i]
        if quote == "'":
            if ch == "'":
                quote = ""
            out.append(_LITERAL_PUNCT.get(ch, ch))
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            nxt = command[i + 1]
            out.append(ch + (_LITERAL_PUNCT.get(nxt, nxt) if not quote else nxt))
            i += 2
            continue
        if ch == "'" and not quote:
            quote = "'"
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            quote = "" if quote == '"' else '"'
            out.append(ch)
            i += 1
            continue
        if quote == '"' and ch in "()":
            out.append(_LITERAL_PUNCT[ch])  # literal inside double quotes
            i += 1
            continue
        if ch == "`":
            j = command.find("`", i + 1)
            if j < 0:
                return None, inners
            inners.append(command[i + 1 : j])
            out.append(f"__SUBST_{len(inners) - 1}__")
            i = j + 1
            continue
        is_dollar = ch == "$" and command.startswith("$(", i)
        if is_dollar or (ch == "(" and not quote):
            start = i + 2 if is_dollar else i + 1
            end = _matching_paren(command, start)
            if end < 0:
                return None, inners
            inners.append(command[start:end])
            kind = "SUBST" if is_dollar else "GROUP"  # a group is not a computed name
            out.append(f"__{kind}_{len(inners) - 1}__")
            i = end + 1
            continue
        out.append(ch)
        i += 1
    if quote:
        return None, inners
    return "".join(out), inners


def _matching_paren(command: str, start: int) -> int:
    """Index of the ``)`` closing the group opened just before ``start``; ``-1`` when
    unbalanced. Quoted text and backslash-escaped characters inside the group do not
    count toward nesting (``$(grep "a(b" f)`` closes at the final ``)``)."""
    depth, j, n = 1, start, len(command)
    quote = ""
    while j < n:
        ch = command[j]
        if quote == "'":
            if ch == "'":
                quote = ""
        elif quote == '"':
            # inside double quotes a single quote is LITERAL — treating it as an opener
            # lost the closing paren of `"$(node -e "console.log(require('x'))")"` and
            # refused an honest nhsuk-frontend build (2026-09-14)
            if ch == "\\":
                j += 1
            elif ch == '"':
                quote = ""
            elif ch == "(" and j > 0 and command[j - 1] == "$":
                depth += 1  # $( … ) inside double quotes still nests
            elif ch == ")" and depth > 1:
                depth -= 1
        elif ch == "\\":
            j += 1
        elif ch == "'":
            quote = "'"
        elif ch == '"':
            quote = '"'
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return -1


def _split_lines(flat: str) -> str | None:
    """Turn every UNQUOTED newline into a ``;`` separator and drop backslash-newline
    continuations. A newline separates commands exactly as ``;`` does — without
    this ``ls\\ngit log`` slipped past the guard as one ``ls`` segment. ``None`` on
    an unterminated quote."""
    out: list[str] = []
    i, n = 0, len(flat)
    quote = ""
    while i < n:
        ch = flat[i]
        if quote == "'":
            if ch == "'":
                quote = ""
            out.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            if flat[i + 1] == "\n":
                out.append(" ")
            else:
                out.append(flat[i : i + 2])
            i += 2
            continue
        if ch == "'" and not quote:
            quote = "'"
        elif ch == '"':
            quote = "" if quote == '"' else '"'
        elif not quote and ch in "\r\n":
            out.append(" ; ")
            i += 1
            continue
        out.append(ch)
        i += 1
    return None if quote else "".join(out)


def _unwrap(argv: Sequence[str]) -> tuple[list[str] | None, dict[str, str]]:
    """Strip leading ``VAR=value`` assignments (returned), shell keywords, function
    definitions and command WRAPPERS (``env``, ``sudo``, ``timeout 30``, ``xargs -n1``…)
    so the executable that actually runs is ``args[0]``. ``None`` for a loop/case
    header (``for f in …``), which runs nothing itself."""
    args = list(argv)
    assigns: dict[str, str] = {}
    while args:
        head = args[0]
        m = _ASSIGN_RE.match(head)
        if m:
            assigns[m.group(1)] = head[m.end() :]
            args = args[1:]
            continue
        if head in _HEADERS:
            return None, assigns
        if head in _KEYWORDS:
            args = args[1:]
            continue
        if head == "function":
            args = args[2:]
            continue
        if _FUNCDEF_RE.match(head):
            args = args[1:]
            continue
        name = Path(head).name
        if name in _WRAPPERS:
            value_opts, skip = _WRAPPERS[name]
            args = args[1:]
            while args and args[0].startswith("-"):
                if args[0] == "--":
                    args = args[1:]
                    break
                args = args[2:] if args[0] in value_opts else args[1:]
            args = args[skip:]
            continue
        break
    return args, assigns


def _positionals(args: Sequence[str], value_opts: frozenset[str] = frozenset()) -> list[str]:
    """Arguments that are not options (nor an option's value), stopping at ``--``.
    ``+nightly``-style toolchain selectors count as options."""
    out: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            break
        if a.startswith(("-", "+")) and a != "-":
            if a in value_opts:
                i += 1
        else:
            out.append(a)
        i += 1
    return out


def _git_args(
    rest: Sequence[str], value_opts: frozenset[str]
) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    """``(options as (name, value), positionals before --, tokens after --)``."""
    opts: list[tuple[str, str]] = []
    pos: list[str] = []
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--":
            return opts, pos, list(rest[i + 1 :])
        if a.startswith("-") and a != "-":
            name, eq, val = a.partition("=")
            if eq:
                opts.append((name, val))
            elif name in value_opts and i + 1 < len(rest):
                opts.append((name, rest[i + 1]))
                i += 1
            else:
                opts.append((a, ""))
        else:
            pos.append(a)
        i += 1
    return opts, pos, []


def _revisionish(a: str) -> bool:
    """Does ``a`` look like a revision rather than a path? Globs and pathspec magic
    can never be refnames."""
    if a == "HEAD" or a.startswith(":") or any(c in a for c in "*?["):
        return False
    return bool(_SHA_RE.match(a) or _REF_RE.search(a) or a in _BRANCHISH)


def _worktree_path(here: Path, a: str) -> bool:
    """Is ``a`` a path that exists under ``here`` (pathspec magic and globs count as paths)?"""
    if a == "." or a.startswith(":") or any(c in a for c in "*?["):
        return True
    try:
        return (here / a).exists()
    except (OSError, ValueError):
        return False


def _leaves_worktree(path: str) -> bool:
    """Absolute, home-relative or ``..``-climbing — a ``git -C`` target outside the tree."""
    p = path.replace("\\", "/")
    return p.startswith(("/", "~")) or bool(re.match(r"^[A-Za-z]:", p)) or ".." in p.split("/")


_PATTERN_COMMANDS: frozenset[str] = frozenset(
    {"grep", "egrep", "fgrep", "rg", "ag", "ack", "sed", "awk", "gawk", "perl"}
)
_REGEX_META = re.compile(r"[\\^$|()\[\]{}+]")


def _is_git_dir_path(a: str) -> bool:
    """A literal path naming ``.git`` or something under it. Regex-shaped text
    (``^\\.git``, ``\\.git/``) is a PATTERN, not a path — a grep filter that mentions
    ``.git`` refused an honest NHSDigital/mesh-client build (2026-09-14)."""
    if _REGEX_META.search(a):
        return False
    p = a.replace("\\", "/")
    return p == ".git" or p.startswith(".git/") or "/.git/" in p or p.endswith("/.git")


def _git_dir_arg(args: Sequence[str]) -> str:
    """A non-git command that names ``.git`` (or a path into one) is reading the
    repository's guts — ``cat .git`` alone reveals the main clone's location.
    For pattern-taking commands (grep, sed, awk …) the first positional argument is
    the pattern and is never a path (``grep -v .git``); later positionals still are."""
    exe = Path(args[0]).name if args else ""
    pattern_seen = exe not in _PATTERN_COMMANDS
    for i in range(1, len(args)):
        a = args[i]
        if a.startswith(("-", "!")):
            continue
        if args[i - 1] in _PATH_EXCLUDE_OPTS:
            continue
        if not pattern_seen:
            pattern_seen = True  # grep's pattern (or sed/awk's program)
            if args[i - 1] not in {"-e", "--regexp", "-f", "--file"}:
                continue
        if _is_git_dir_path(a):
            return f"archaeology: '.git' is off limits ({a})"
    return ""


#: Redirection operators whose next word is a FILE the shell opens (``2>&1`` and
#: ``<<<word`` are not: an fd and a here-string). ``>&`` / ``<&`` take an fd — or, with
#: a non-numeric word, a file (bash treats ``>&file`` as ``&>file``).
_FILE_REDIRECTS: frozenset[str] = frozenset({"<", ">", ">>", "<>", ">|", "&>", "&>>", ">>|"})
_FD_REDIRECTS: frozenset[str] = frozenset({">&", "<&"})
#: Commands whose positional arguments are paths they WRITE (copy / move / link / tee):
#: a target that resolves into ``.git`` — through a symlink or not — is off limits.
_WRITE_PATH_COMMANDS: frozenset[str] = _words("tee cp mv install ln")


def _resolves_into_git_dir(target: str, here: Path | None) -> bool:
    """Does ``target`` name ``.git`` (or a path under one) — literally, or once resolved
    against ``here`` with symlinks followed (``ln -s .git gitlink; … >> gitlink/info/
    exclude``)? Without a cwd only the literal form can be judged. The worktree's own
    ``.git`` is a FILE pointing at the main clone; ``Path.resolve`` (non-strict) keeps
    the ``.git`` component when a path leads through it, which is what is checked."""
    if not target or target.startswith(("-", "/dev/")):
        return False
    if _is_git_dir_path(target):
        return True
    if here is None or target.startswith("~") or _REGEX_META.search(target):
        return False
    try:
        p = Path(target) if target.startswith("/") else here / target
        resolved = p.resolve()
    except (OSError, RuntimeError, ValueError):
        return True  # cannot be resolved safely: fail closed
    return ".git" in resolved.parts


def _redirect_target(target: str, here: Path | None) -> str:
    """A redirection whose file resolves into ``.git`` is refused — ``echo conftest.py
    >> .git/info/exclude`` hid a poison file from the grader on the host posture
    (independent review pass, 2026-09-14, findings 1(a) / 6(a))."""
    if _resolves_into_git_dir(target, here):
        return f"archaeology: '.git' is off limits ({target})"
    return ""


def _write_target_arg(args: Sequence[str], here: Path | None) -> str:
    """``tee`` / ``cp`` / ``mv`` / ``install`` / ``ln`` positional paths and ``dd of=``
    that resolve into ``.git`` (literal paths are already caught by :func:`_git_dir_arg`;
    this adds symlink resolution against the cwd and the ``of=`` form)."""
    exe = Path(args[0]).name if args else ""
    if exe == "dd":
        for a in args[1:]:
            if a.startswith("of=") and _resolves_into_git_dir(a[3:], here):
                return f"archaeology: '.git' is off limits ({a})"
        return ""
    if exe not in _WRITE_PATH_COMMANDS:
        return ""
    for i in range(1, len(args)):
        a = args[i]
        if a.startswith("-") or args[i - 1] in _PATH_EXCLUDE_OPTS:
            continue
        if _resolves_into_git_dir(a, here):
            return f"archaeology: '.git' is off limits ({a})"
    return ""


def _inline_code(exe: str, args: Sequence[str], stdin: str | None) -> list[str]:
    """The code strings an interpreter invocation would execute: every ``-c``/``-e``
    value (separate or attached) plus a here-document when the script is stdin
    (``python -``, or no script argument at all)."""
    flags = _INLINE_FLAGS.get("python" if _PYTHON_RE.match(exe) else exe)
    if flags is None:
        return []
    code: list[str] = []
    i = 1
    positional = False
    while i < len(args):
        a = args[i]
        if a == "--":
            positional = positional or i + 1 < len(args)
            break
        if a in flags:
            if i + 1 < len(args):
                code.append(args[i + 1])
            i += 2
            continue
        attached = next((f for f in flags if len(f) == 2 and a.startswith(f) and len(a) > 2), "")
        if attached:
            code.append(a[2:])
        elif a.startswith("--") and "=" in a and a.split("=", 1)[0] in flags:
            code.append(a.split("=", 1)[1])
        elif a == "-m":
            return code  # a module run, never inline code
        elif a != "-" and not a.startswith("-"):
            positional = True
        i += 1
    if stdin is not None and not code and not positional:
        code.append(stdin)
    return code


def _scan_code(code: str, exe: str) -> str:
    """Refuse inline code that shells out to git history, reads ``.git`` or calls a
    network tool. Text scan, not a parse — see :data:`_CODE_GIT_HISTORY`."""
    m = _CODE_GIT_NETWORK.search(code)
    if m:
        return f"network: inline {exe} code runs 'git {m.group(1)}' (no network access)"
    m = _CODE_GIT_HISTORY.search(code)
    if m:
        return f"archaeology: inline {exe} code runs 'git {m.group(1)}' (history/other revisions)"
    if _CODE_GIT_DIFF_REV.search(code):
        return f"archaeology: inline {exe} code runs 'git diff' against another revision"
    if _CODE_GIT_DIR.search(code):
        return f"archaeology: inline {exe} code reads '.git'"
    m = _CODE_NET_TOOL.search(code)
    if m:
        return f"network: inline {exe} code runs '{m.group(0).split()[0]}' (no network access)"
    return ""


def _chdir(here: Path | None, target: str) -> Path | None:
    """Where the shell is after ``cd target``; ``None`` when unknown (home, ``-``)."""
    if here is None or target in {"", "-", "~"} or target.startswith("~"):
        return None
    t = Path(target)
    if t.is_absolute():
        return t
    return Path(posixpath.normpath((here / target).as_posix()))


# ---------------------------------------------------------------------------
# Shell guard
# ---------------------------------------------------------------------------


class GitArchaeologyGuard:
    """Refuse commands that recover the real patch, reach other revisions, leave
    the sandbox, or mutate the provisioned environment.

    ``check(argv)`` inspects one argv; ``check_shell(command)`` parses a shell
    command line — ``&&`` ``||`` ``;`` ``|`` ``&`` *and newlines* separate segments;
    ``$( … )``, backticks and ``( … )`` sub-shells are checked recursively; here-
    document bodies are data (quoted tag) or scanned for substitutions (unquoted
    tag); wrappers (``env``, ``sudo``, ``timeout``, ``xargs``, ``find -exec``,
    ``sh -c``, function bodies, ``alias`` values) are unwrapped to the command that
    actually runs. Returns ``""`` when allowed, else a reason prefixed
    ``archaeology:`` (history / other revisions / the shared stash stack / ``.git``
    / cannot be parsed safely) or ``network:`` (fetch / install / registry / cloud).

    ``cwd`` (constructor or per call) is the worktree the command runs in. With it
    the guard can *verify* instead of guess: ``npx <bin>`` is honest when
    ``node_modules/.bin/<bin>`` exists at the (``cd``-tracked) cwd or an ancestor
    up to the worktree root; ``git diff <word>`` / ``git checkout <word>`` are paths
    only if they exist. Without a cwd those forms fail closed — ``npx`` is refused,
    ``git diff <unknown word>`` is allowed only when it does not look like a ref.

    **Policy: ``git stash`` stays refused in every form (2026-09-13).** Measured on a
    throwaway clone: ``refs/stash`` lives in the common git dir, so it is shared by
    the main clone and EVERY ``git worktree add --detach`` task worktree —
    ``git stash list`` / ``show -p`` in one worktree printed another worktree's
    diff, and ``git stash pop`` there stole it (the first worktree's entry was
    gone). A stash from a concurrent trial of the *same task* is that trial's
    candidate solution; the operator's WIP is on the same stack. That is
    cross-trial contamination and destruction of another trial's work, not just
    "the agent's own loss", so no ``push``/``list``/``show``/``apply``/``pop``/
    ``drop`` subset is safe. The honest goal ("run the tests without my edits") has
    a working-tree-only idiom that reaches no shared state and is allowed:
    ``git diff > /tmp/mine.patch; git checkout -- <paths>; <tests>; git apply
    /tmp/mine.patch`` (or copy the file). The refusal message says so.

    **Policy: ``npx``.** Refused wholesale before (three honest koa builds).
    ``npx <name>`` never fetches when ``node_modules/.bin/<name>`` exists, so with a
    cwd it is allowed exactly then; ``--no-install``/``--no`` is offline by
    construction and allowed anywhere; ``-p``/``--package``/``-y``/``--yes``, a
    ``name@version``, a scoped ``@org/pkg``, ``--call`` and an unknown binary are
    refused. ``npm exec`` follows the same rule.

    **Not this guard's job: shell edits to test files** (``sed -i … foo_test.go``,
    ``> tests/x.py``, ``cp``, ``tee``). The shell guard is path-blind and cannot
    classify tests; belt 1 (:meth:`TestFileGuard.tampered` →
    :meth:`~crb.core.workspace.Workspace.tests_byte_identical`) catches every such
    edit post hoc, byte for byte, however it was made. Detecting them here would be
    unbounded (``python -c "open(…, 'w')"``) and advisory at best.

    **Inline code** (``python -c``, ``node -e``, ``ruby``/``perl``/``php -e``/``-r``,
    and a here-document fed to ``python -``) is *scanned*, not parsed as shell: the
    text is searched for a git history/network verb, a ``.git`` path or a network tool
    (:func:`_scan_code`). Parsing code as shell would refuse honest one-liners; the
    scan keeps ``subprocess.run(['git','status'])`` honest and refuses
    ``subprocess.run(['git','log'])``.

    **Known gaps (documented, not hidden):** script FILES (``bash script.sh``,
    ``source x.sh``, ``make``) and library-level network in code (``urllib``,
    ``requests``) are not inspected — the sandbox's ``--network=none`` is the belt
    for network, and history access from code is only closed for good by giving the
    builder a clone that does not *contain* the gold commit (the P5
    builder-in-container item). Without a cwd, ``git diff <branch-not-in-the-known-
    list>`` passes. None of these can mint a false pass (the belts still hold); they
    could contaminate a measurement by recovering the gold patch.

    History (false positives this guard has refused on honest builds, each now a
    corpus line in ``tests/fixtures/shell_corpus.txt``):

    * 2026-09-13 — ``$(pwd)``, ``$(find …)`` (koa): substitutions were refused
      wholesale; now hoisted and checked recursively.
    * 2026-09-13 — ``grep "preRun(ctx"`` (cobra): a quoted ``(`` was read as a
      sub-shell; parsing now honours quoting.
    * 2026-09-13 — ``pip install`` after ImportError (click ×8): the brief lacked the
      runner's env prefix (fixed in the adapter); ``python -m pip list/show`` was
      also refused by an ``or`` fall-through here.
    * 2026-09-13 — ``npx standard`` (koa): ``npx`` refused wholesale → cwd-verified
      local binaries.
    * 2026-09-13 — this corpus (414 honest lines): the old guard refused 45 —
      ``git rev-parse --show-toplevel``, ``git config --get``, ``git apply``,
      ``git mv``, ``git checkout -- <path>``, ``git restore -- <path>``,
      ``uv pip list``, ``npm exec -- jest``, ``case … esac``, and every heredoc
      whose body contained an apostrophe. All fixed; 14 bypass classes closed
      in the same pass (newline separator, leading redirection, ``{ }``/``if``
      groups, ``bash -x -c``, ``xargs``, ``find -exec``, ``env -i``, ``timeout``,
      ``git diff main``, ``git grep pat main``, bare ``yarn``, ``./mvnw
      dependency:*``, ``docker``, function definitions).
    * 2026-09-14 — A8's human-review exercises found the guard read only each
      segment's first word: ``python -c "subprocess.run(['git','log'])"``,
      ``GIT_DIR=… git diff``, ``parallel git log`` and ``git -c core.worktree=``
      passed. Closed by the inline-code scan, the ``GIT_*`` redirect rule and the
      ``parallel`` wrapper; the honest counterparts (``subprocess.run(['git',
      'status'])``, ``open('.gitignore')``) are corpus lines.
    * 2026-09-14 — the independent review pass: ``echo "a (b" | grep '('`` was
      refused as a stray sub-shell token (finding 7: the tokeniser strips the quotes;
      quoted punctuation is now a sentinel through tokenisation), and redirection
      targets were never inspected (finding 6a: ``>> .git/info/exclude`` hid a
      poison file from the grader — finding 1a). Every file-opening redirection,
      ``dd of=`` and tee/cp/mv/install/ln targets are now checked, symlinks followed
      when a cwd is known; :class:`TestFileGuard` classifies by what a path resolves
      to (finding 6c). Inline-code string concatenation (``'gi'+'t'``, finding 6b)
      and script files stay documented gaps: the sealed container is that belt.
    """

    def __init__(self, cwd: Path | str | None = None) -> None:
        self.cwd: Path | None = Path(cwd) if cwd is not None else None

    # --- public --------------------------------------------------------------------
    def check(self, argv: Sequence[str], *, cwd: Path | str | None = None) -> str:
        """Check one argv (already split). Returns a reason or ``""``."""
        return self._segment([str(a) for a in argv], self._here(cwd), stdin=None, piped=False)

    def check_shell(self, command: str, *, cwd: Path | str | None = None, _depth: int = 0) -> str:
        """Parse and check a shell command line (see the class docstring)."""
        if _depth > 4:
            return "archaeology: command substitution nested too deep to check"
        here = self._here(cwd)
        stripped = _strip_heredocs(command)
        if stripped is None:
            return "archaeology: could not parse the command safely (here-document tag)"
        rest, bodies = stripped
        body_inners: list[str] = []
        for body, literal in bodies:
            if literal:
                continue
            found = _heredoc_body_inners(body)
            if found is None:
                return "archaeology: could not parse the command safely (unbalanced substitution)"
            body_inners += found
        flat, inners = _hoist_substitutions(rest)
        if flat is None:
            return "archaeology: could not parse the command safely (unbalanced substitution)"
        for inner in body_inners:
            r = self.check_shell(inner, cwd=here, _depth=_depth + 1)
            if r:
                return r
        lined = _split_lines(flat)
        if lined is None:
            return "archaeology: could not parse the command safely (unterminated quote)"
        lex = shlex.shlex(lined, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        try:
            tokens = list(lex)
        except ValueError:
            return "archaeology: could not parse the command safely"

        segments: list[list[str]] = [[]]
        piped: list[bool] = [False]
        heredocs: list[int] = [0]
        redirects: list[list[str]] = [[]]  # file targets of `<` `>` `>>` … per segment
        checked: set[int] = set()
        skip_next = False
        file_target_next = False
        fd_target_next = False
        for idx, tok in enumerate(tokens):
            # every substitution is checked wherever it sits — as an argument, a
            # redirection target, an assignment value or an exe name
            for m in _PLACEHOLDER_RE.finditer(tok):
                k = int(m.group(1))
                if k < len(inners) and k not in checked:
                    checked.add(k)
                    r = self.check_shell(inners[k], cwd=here, _depth=_depth + 1)
                    if r:
                        return r
            if skip_next:
                skip_next = False
                word = _unsentinel(tok)
                if file_target_next or (fd_target_next and word != "-" and not word.isdigit()):
                    redirects[-1].append(word)  # a file the shell opens: checked below
                file_target_next = fd_target_next = False
                continue
            if tok in _SEPARATORS:
                segments.append([])
                piped.append(tok in _PIPES)
                heredocs.append(0)
                redirects.append([])
                continue
            # a quoted paren is a sentinel by now (finding 7); a bare one here escaped
            # the hoist and cannot be reasoned about
            if tok in {"(", "`", "$"}:
                return "archaeology: could not parse the command safely (stray sub-shell token)"
            if tok.startswith("<<") and not tok.startswith("<<<"):
                heredocs[-1] += 1
                skip_next = True  # the tag
                continue
            if tok.startswith(("<", ">")) or tok in {"&>", "&>>"}:
                skip_next = True  # the redirection target is not a command …
                file_target_next = tok in _FILE_REDIRECTS  # … but it may be a file
                fd_target_next = tok in _FD_REDIRECTS
                continue
            if tok.isdigit() and idx + 1 < len(tokens) and tokens[idx + 1].startswith(("<", ">")):
                continue  # a file descriptor: `2>/dev/null git log` still runs git log
            segments[-1].append(_unsentinel(tok))
        for k, inner in enumerate(inners):  # defensive: a placeholder can never vanish
            if k not in checked:
                r = self.check_shell(inner, cwd=here, _depth=_depth + 1)
                if r:
                    return r
        body_iter = iter(body for body, _ in bodies)
        for i, seg in enumerate(segments):
            stdin: str | None = None
            for _ in range(heredocs[i]):
                stdin = next(body_iter, None)
            for target in redirects[i]:
                r = _redirect_target(target, here)
                if r:
                    return r
            r = self._segment(seg, here, stdin=stdin, piped=piped[i], depth=_depth)
            if r:
                return r
            if seg and seg[0] in {"cd", "pushd"}:
                here = _chdir(here, seg[1] if len(seg) > 1 else "")
            elif seg and seg[0] == "popd":
                here = None
        return ""

    # --- one segment -----------------------------------------------------------------
    def _here(self, cwd: Path | str | None) -> Path | None:
        return Path(cwd) if cwd is not None else self.cwd

    def _segment(
        self,
        seg: Sequence[str],
        here: Path | None,
        *,
        stdin: str | None,
        piped: bool,
        depth: int = 0,
    ) -> str:
        """Check one pipeline segment: unwrap → ``GIT_*`` redirects → shells / ``eval`` /
        ``alias`` → network tools → git → ``.git`` paths and write targets → inline code →
        ``find -exec`` → package and build tools. First refusal wins."""
        args, assigns = _unwrap(seg)
        redirected = sorted(set(assigns) & _GIT_ENV_REDIRECT)
        if redirected:
            return f"archaeology: '{redirected[0]}=' points git at another repository"
        if not args:
            return ""
        head = args[0]
        if head in _EXPORTERS:
            for a in args[1:]:
                m = _ASSIGN_RE.match(a)
                if m and m.group(1) in _GIT_ENV_REDIRECT:
                    return f"archaeology: '{m.group(1)}=' points git at another repository"
            return ""
        if _GROUP_RE.match(head):
            return ""  # a `( … )` group — its contents were checked when hoisted
        if head.startswith("$") or _COMPUTED_RE.fullmatch(head):
            return (
                "archaeology: the command name is computed (a variable or substitution) and "
                "cannot be checked — run the program by name"
            )
        exe = Path(head).name
        if exe in _SHELLS:
            return self._shell_exe(args, here, stdin=stdin, piped=piped, depth=depth)
        if exe == "eval":
            return "archaeology: 'eval' is not allowed"
        if exe == "alias":
            for a in args[1:]:
                _, eq, val = a.partition("=")
                if eq:
                    r = self.check_shell(val, cwd=here, _depth=depth + 1)
                    if r:
                        return r
            return ""
        if exe in NETWORK_TOOLS:
            return f"network: '{exe}' is not allowed (no network access)"
        if exe == "git" or exe.startswith("git-"):
            return self._check_git(args[1:] if exe == "git" else [exe[4:], *args[1:]], here)
        r = _git_dir_arg(args) or _write_target_arg(args, here)
        if r:
            return r
        for code in _inline_code(exe, args, stdin):
            r = _scan_code(code, exe)
            if r:
                return r
        if exe == "find":
            return self._find_exec(args, here, depth)
        return self._tool(exe, args[1:], assigns, here, depth)

    def _shell_exe(
        self, args: list[str], here: Path | None, *, stdin: str | None, piped: bool, depth: int
    ) -> str:
        """``sh -c 'cmd'`` is checked; a here-document or pipe fed to a bare shell is
        a script and is checked or refused; a script FILE is a documented gap."""
        i, inline = 1, False
        while i < len(args) and args[i].startswith(("-", "+")) and args[i] != "--":
            f = args[i]
            if not f.startswith("--") and f[-1] in "oO":
                i += 2  # `-o pipefail` / `-euo pipefail`: the option name is the next token
                continue
            if not f.startswith("--") and "c" in f[1:]:
                inline = True
            i += 1
        if i < len(args) and args[i] == "--":
            i += 1
        if inline:
            if i >= len(args):
                return "archaeology: shell -c without a command string"
            return self.check_shell(args[i], cwd=here, _depth=depth + 1)
        if i < len(args):
            return ""  # a script file (documented gap)
        if stdin is not None:
            return self.check_shell(stdin, cwd=here, _depth=depth + 1)
        if piped:
            return "archaeology: piping a script into a shell cannot be checked"
        return ""

    def _find_exec(self, args: list[str], here: Path | None, depth: int) -> str:
        """Every ``-exec``/``-execdir``/``-ok`` command of a ``find`` is a segment of its own."""
        i = 1
        while i < len(args):
            if args[i] in {"-exec", "-execdir", "-ok", "-okdir"}:
                j = i + 1
                sub: list[str] = []
                while j < len(args) and args[j] not in {";", "+"}:
                    sub.append(args[j])
                    j += 1
                r = self._segment(sub, here, stdin=None, piped=False, depth=depth)
                if r:
                    return r
                i = j
            i += 1
        return ""

    # --- git -------------------------------------------------------------------------
    def _check_git(self, args: list[str], here: Path | None) -> str:
        """Global options that re-point git are refused; then the sub-command must be in
        ``GIT_ALLOWED`` (``stash`` gets its own message with the honest idiom), and the
        verbs with argument rules dispatch to their handler."""
        i = 0
        while i < len(args) and args[i].startswith("-"):
            a = args[i]
            if a.startswith(("--git-dir", "--work-tree")):
                return f"archaeology: 'git {a}' points git at another repository"
            if a in {"-C", "-c", "--namespace", "--exec-path", "--super-prefix", "--config-env"}:
                val = args[i + 1] if i + 1 < len(args) else ""
                if a == "-C" and _leaves_worktree(val):
                    return f"archaeology: 'git -C {val}' leaves the worktree"
                if a == "-c" and val.split("=", 1)[0] in {"core.worktree", "core.gitdir"}:
                    return f"archaeology: 'git -c {val}' points git at another repository"
                i += 2
            else:
                i += 1
        if i >= len(args):
            return ""
        sub, rest = args[i], args[i + 1 :]
        if sub in _GIT_NETWORK:
            return f"network: 'git {sub}' reaches the network (no network access)"
        if sub == "stash":
            return (
                "archaeology: 'git stash' is not allowed — the stash stack is shared with every "
                "other worktree of this clone (other trials, the operator). To test without your "
                "edits: git diff > /tmp/mine.patch; git checkout -- <paths>; run the tests; "
                "git apply /tmp/mine.patch"
            )
        if sub not in GIT_ALLOWED:
            return f"archaeology: 'git {sub}' is not allowed (no history/other revisions)"
        if sub == "diff":
            return self._git_diff(rest, here)
        if sub == "grep":
            return self._git_grep(rest, here)
        if sub == "checkout":
            return self._git_checkout(rest, here)
        if sub == "restore":
            return self._git_restore(rest)
        if sub == "rev-parse":
            return self._git_rev_parse(rest)
        if sub == "config":
            return self._git_config(rest)
        return ""

    @staticmethod
    def _revision_arg(verb: str, a: str, here: Path | None) -> str:
        """A positional of ``git diff``/``grep``: ``HEAD`` is fine, a ref-shaped word is
        refused, and with a cwd anything that is not an existing path is refused too."""
        if a == "HEAD":
            return ""
        if _revisionish(a):
            return f"archaeology: 'git {verb} {a}' compares against another revision"
        if here is not None and not _worktree_path(here, a):
            return f"archaeology: 'git {verb} {a}' is not a path in the worktree (a revision?)"
        return ""

    def _git_diff(self, rest: list[str], here: Path | None) -> str:
        """``git diff`` may compare only the working tree against HEAD/the index."""
        opts, pos, _ = _git_args(rest, _GIT_VALUE_OPTS["diff"])
        if any(n == "--all" for n, _ in opts):
            return "archaeology: 'git diff --all' is not allowed"
        for a in pos:
            r = self._revision_arg("diff", a, here)
            if r:
                return r
        return ""

    def _git_grep(self, rest: list[str], here: Path | None) -> str:
        """``git grep`` may not name a tree-ish; the first positional is the pattern unless
        ``-e``/``-f`` gave it."""
        opts, pos, _ = _git_args(rest, _GIT_VALUE_OPTS["grep"])
        explicit_pattern = any(n in {"-e", "-f"} for n, _ in opts)
        for a in pos if explicit_pattern else pos[1:]:
            r = self._revision_arg("grep", a, here)
            if r:
                return r
        return ""

    def _git_checkout(self, rest: list[str], here: Path | None) -> str:
        """Only ``git checkout [HEAD] -- <paths>`` (restore files); never a branch or
        revision. Without ``--`` a word must be a verifiable path."""
        opts, pos, _ = _git_args(rest, _GIT_VALUE_OPTS["checkout"])
        for n, _v in opts:
            if n not in _CHECKOUT_OK:
                return (
                    f"archaeology: 'git checkout {n}' switches branches/revisions — only "
                    "'git checkout [HEAD] -- <paths>' is allowed"
                )
        if "--" in rest:
            bad = [p for p in pos if p != "HEAD"] + pos[1:]
            if bad:
                return f"archaeology: 'git checkout {bad[0]}' names another revision"
            return ""
        for j, p in enumerate(pos):
            if p == "HEAD" and j == 0:
                continue
            if here is not None and not _revisionish(p) and _worktree_path(here, p):
                continue
            return (
                f"archaeology: 'git checkout {p}' cannot be verified as a path — use "
                "'git checkout -- <paths>'"
            )
        return ""

    def _git_restore(self, rest: list[str]) -> str:
        """``git restore`` only from HEAD (``--source`` of anything else is history)."""
        opts, _pos, _ = _git_args(rest, _GIT_VALUE_OPTS["restore"])
        for n, v in opts:
            if n in {"-s", "--source"}:
                if v != "HEAD":
                    return f"archaeology: 'git restore --source={v}' restores another revision"
            elif n not in _RESTORE_OK:
                return f"archaeology: 'git restore {n}' is not allowed"
        return ""

    def _git_rev_parse(self, rest: list[str]) -> str:
        """Layout queries (``--show-toplevel`` …) and ``HEAD`` only — never another rev."""
        opts, pos, after = _git_args(rest, frozenset())
        for n, _v in opts:
            if n not in _REV_PARSE_OK:
                return (
                    f"archaeology: 'git rev-parse {n}' reveals the repository layout or a revision"
                )
        for p in pos + after:
            if p != "HEAD":
                return f"archaeology: 'git rev-parse {p}' resolves another revision"
        return ""

    def _git_config(self, rest: list[str]) -> str:
        """Read-only: the clone's config is shared with every other worktree."""
        opts, pos, after = _git_args(rest, _GIT_VALUE_OPTS["config"])
        names = {n for n, _ in opts}
        if names & _CONFIG_WRITE or (
            pos and pos[0] in {"set", "unset", "edit", "rename-section", "remove-section"}
        ):
            return "archaeology: 'git config' may only read (--get/--list); writes change the shared clone config"
        if "--blob" in names:
            return "archaeology: 'git config --blob' reads another revision"
        if names & _CONFIG_READ or (pos and pos[0] in {"get", "list"}):
            return ""
        if len(pos) + len(after) <= 1:
            return ""
        return "archaeology: 'git config <key> <value>' writes the shared clone config"

    # --- package / build tools ---------------------------------------------------------
    def _tool(
        self,
        exe: str,
        args: list[str],
        assigns: Mapping[str, str],
        here: Path | None,
        depth: int,
    ) -> str:
        """Package and build tools: each manager's install/fetch/publish verbs are
        ``network:`` refusals; everything else they do is honest."""
        if _PIP_RE.match(exe):
            return self._pip(args)
        if _PYTHON_RE.match(exe):
            return self._python(args, assigns, here, depth)
        if exe == "uv":
            return self._uv(args)
        if exe == "npm":
            return self._npm(args, here, depth)
        if exe == "npx":
            return self._npx(args, here, depth, verb="npx")
        if exe == "yarn":
            return self._yarn(args)
        if exe == "pnpm":
            return self._pnpm(args)
        if exe == "go":
            return self._go(args, assigns)
        if exe == "cargo":
            return self._cargo(args)
        if exe in {"mvn", "mvnw"}:
            return self._mvn(exe, args)
        if exe in {"gradle", "gradlew"}:
            return self._gradle(exe, args)
        if exe == "tox":
            return (
                ""
                if set(args) & _TOX_READONLY
                else "network: 'tox' creates virtualenvs and installs into them"
            )
        if exe == "nox":
            return (
                ""
                if set(args) & _NOX_READONLY
                else "network: 'nox' creates virtualenvs and installs into them"
            )
        if exe == "pre-commit":
            pos = _positionals(args)
            if (
                not args
                or set(args) & _PRECOMMIT_READONLY
                or (pos and pos[0] in _PRECOMMIT_READONLY)
            ):
                return ""
            return "network: 'pre-commit' installs hook environments"
        if exe in _INSTALLERS:
            pos = _positionals(args)
            if pos and pos[0] in _INSTALLERS[exe]:
                return f"network: '{exe} {pos[0]}' installs from the network"
        return ""

    def _pip(self, args: list[str]) -> str:
        """``pip install/download/…/uninstall`` refused; ``list``/``show``/``freeze`` honest."""
        pos = _positionals(args)
        if pos and pos[0] in _PIP_REFUSED:
            what = (
                "modifies the provisioned environment"
                if pos[0] == "uninstall"
                else "installs from the network"
            )
            return f"network: 'pip {pos[0]}' {what}"
        return ""

    def _python(
        self, args: list[str], assigns: Mapping[str, str], here: Path | None, depth: int
    ) -> str:
        """``python -m pip/ensurepip/pipx/…`` is the tool it names (inline code was scanned
        by the caller)."""
        if "-m" not in args:
            return ""
        i = args.index("-m")
        if i + 1 >= len(args):
            return ""
        mod, rest = args[i + 1], args[i + 2 :]
        if mod == "pip":
            return self._pip(rest)
        if mod == "ensurepip":
            return "network: 'python -m ensurepip' installs pip"
        if mod in {"pipx", "pipenv", "poetry", "uv", "conda"}:
            return self._tool(mod, rest, assigns, here, depth)
        return ""

    def _uv(self, args: list[str]) -> str:
        """``uv pip list/show/…`` and ``uv venv/cache/version`` honest; ``uv run/sync/add``
        and ``uv pip install`` refused (they resolve from the network)."""
        pos = _positionals(args)
        if not pos:
            return ""
        sub = pos[0]
        if sub == "pip":
            if len(pos) < 2 or pos[1] in _UV_PIP_OK:
                return ""
            return f"network: 'uv pip {pos[1]}' installs or changes the provisioned environment"
        if sub in _UV_OK:
            return ""
        return f"network: 'uv {sub}' installs or syncs from the network"

    def _npm(self, args: list[str], here: Path | None, depth: int) -> str:
        """``npm run/test/ls`` honest; ``npm exec`` follows the ``npx`` rule; ``npm explore``
        checks the wrapped command; the install/registry/account verbs are refused."""
        pos = _positionals(args)
        if not pos:
            return ""
        sub = pos[0]
        if sub in {"exec", "x"}:
            return self._npx(args[args.index(sub) + 1 :], here, depth, verb="npm exec")
        if sub == "explore":
            if "--" in args:
                return self._segment(
                    args[args.index("--") + 1 :], here, stdin=None, piped=False, depth=depth
                )
            return ""
        if sub == "version":
            return "network: 'npm version <x>' bumps and tags the package" if len(pos) > 1 else ""
        if sub in _NPM_REFUSED:
            return f"network: 'npm {sub}' installs from the network"
        return ""

    def _npx(self, args: list[str], here: Path | None, depth: int, *, verb: str) -> str:
        """The ``npx`` policy from the class docstring: a bare binary name is honest only
        when it exists in ``node_modules/.bin`` at a known cwd (or ``--no-install``)."""
        i, no_install = 0, False
        while i < len(args):
            a = args[i]
            if a == "--":
                i += 1
                break
            if not a.startswith("-"):
                break
            name, eq, val = a.partition("=")
            if name in {"--no-install", "--no"}:
                no_install = True
            elif name in {"-p", "--package", "-y", "--yes", "--ignore-existing"}:
                return f"network: '{verb} {name}' may fetch a package from the registry"
            elif name in {"-c", "--call"}:
                cmd = val if eq else (args[i + 1] if i + 1 < len(args) else "")
                r = self.check_shell(cmd, cwd=here, _depth=depth + 1)
                return r or f"network: '{verb} --call' may install before running"
            i += 1
        if i >= len(args):
            return ""
        name = args[i]
        if "@" in name or "/" in name or name.startswith("."):
            return f"network: '{verb} {name}' names a package or version, not a binary in node_modules/.bin"
        if no_install:
            return ""
        if here is None:
            return (
                f"network: '{verb} {name}' cannot be verified against node_modules/.bin "
                "(no worktree cwd) — it may fetch from the registry"
            )
        if self._local_bin(here, name):
            return ""
        return f"network: '{verb} {name}' is not in node_modules/.bin — it would be fetched from the registry"

    def _local_bin(self, here: Path, name: str) -> bool:
        """``node_modules/.bin/<name>`` at ``here`` or an ancestor up to the worktree root
        (npm walks up the same way; monorepos hoist binaries to the root)."""
        root = self.cwd
        d = here
        for _ in range(64):
            try:
                if (d / "node_modules" / ".bin" / name).exists():
                    return True
            except (OSError, ValueError):
                return False
            at_root = d in (root, d.parent)
            if at_root or (root is not None and root not in d.parents):
                return False
            d = d.parent
        return False

    def _yarn(self, args: list[str]) -> str:
        """Bare ``yarn`` installs; ``workspace <x> <verb>`` unwraps to the verb."""
        pos = _positionals(args)
        if not pos:
            return (
                ""
                if any(a in {"-v", "--version", "-h", "--help"} for a in args)
                else "network: bare 'yarn' installs"
            )
        sub = pos[0]
        if sub == "workspace":
            sub = pos[2] if len(pos) > 2 else ""
        elif sub == "workspaces":
            sub = "focus" if len(pos) > 1 and pos[1] == "focus" else ""
        elif sub == "cache":
            sub = "cache clean" if len(pos) > 1 and pos[1] in {"clean", "clear"} else ""
        if sub in _YARN_REFUSED or sub in {"cache clean", "focus"}:
            return f"network: 'yarn {sub}' installs or changes the provisioned environment"
        return ""

    def _pnpm(self, args: list[str]) -> str:
        """The pnpm install/registry verbs and ``store prune`` are refused."""
        pos = _positionals(args, _PNPM_VALUE_OPTS)
        if not pos:
            return ""
        sub = pos[0]
        if sub == "store" and len(pos) > 1 and pos[1] == "prune":
            return "network: 'pnpm store prune' destroys the provisioned store"
        if sub in _PNPM_REFUSED:
            return f"network: 'pnpm {sub}' installs or changes the provisioned environment"
        return ""

    def _go(self, args: list[str], assigns: Mapping[str, str]) -> str:
        """``go get/install``, ``go mod download/tidy/vendor`` (unless ``GOPROXY=off``),
        ``pkg@version`` forms and cache/config writes are refused."""
        pos = _positionals(args)
        if not pos:
            return ""
        sub = pos[0]
        offline = assigns.get("GOPROXY") == "off" or "-mod=vendor" in assigns.get("GOFLAGS", "")
        if sub in {"get", "install"}:
            return f"network: 'go {sub}' installs from the network"
        if (
            sub == "mod"
            and len(pos) > 1
            and pos[1] in {"download", "tidy", "vendor"}
            and not offline
        ):
            return f"network: 'go mod {pos[1]}' fetches modules"
        if sub == "telemetry":
            return "network: 'go telemetry' is not allowed"
        if sub == "clean" and any(a in {"-modcache", "-cache"} for a in args):
            return "network: 'go clean -modcache/-cache' destroys the provisioned cache"
        if sub == "env" and "-w" in args:
            return "network: 'go env -w' writes persistent toolchain configuration"
        if sub in {"run", "build", "test", "list", "doc", "vet"} and any("@" in p for p in pos[1:]):
            return f"network: 'go {sub} pkg@version' fetches a module"
        return ""

    def _cargo(self, args: list[str]) -> str:
        """Registry verbs refused always; resolution verbs refused unless ``--offline``."""
        pos = _positionals(args)
        if not pos:
            return ""
        sub = pos[0]
        offline = "--offline" in args
        if sub in _CARGO_ALWAYS:
            return f"network: 'cargo {sub}' installs or reaches the registry"
        if sub in _CARGO_ONLINE and not offline:
            return f"network: 'cargo {sub}' fetches from the registry (add --offline to resolve locally)"
        return ""

    def _mvn(self, exe: str, args: list[str]) -> str:
        """``deploy`` and ``-U`` refused; ``dependency:*``-style goals refused unless ``-o``."""
        goals = _positionals(args, _MVN_VALUE_OPTS)
        offline = "-o" in args or "--offline" in args
        if any(g == "deploy" or g.startswith("deploy:") for g in goals):
            return f"network: '{exe} deploy' publishes to a remote repository"
        if "-U" in args or "--update-snapshots" in args:
            return f"network: '{exe} -U' forces remote resolution"
        if not offline:
            for g in goals:
                if g.startswith(_MVN_ONLINE_PREFIXES):
                    return f"network: '{exe} {g}' resolves from the network (use -o)"
        return ""

    def _gradle(self, exe: str, args: list[str]) -> str:
        """``publish*`` and lock/refresh flags refused; dependency tasks refused unless
        ``--offline``."""
        tasks = _positionals(args, _GRADLE_VALUE_OPTS)
        offline = "--offline" in args
        for flag in ("--refresh-dependencies", "--write-locks", "--update-locks"):
            if flag in args:
                return f"network: '{exe} {flag}' resolves from the network"
        for t in tasks:
            if t.startswith("publish"):
                return f"network: '{exe} {t}' publishes to a remote repository"
            if not offline and (
                t in {"dependencies", "wrapper", "init"} or t.startswith("dependency")
            ):
                return f"network: '{exe} {t}' resolves from the network (use --offline)"
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
