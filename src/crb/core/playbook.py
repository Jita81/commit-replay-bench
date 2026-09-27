"""The playbook compiler — operating facts for a builder, from closed templates only.

The prevention loop (ADR-0020) reaches for a process lever first; a *playbook line* is the
advisory fallback: one operating fact about a repository, stated as a checklist line the
brief shows under "Operating notes for this repository". This module is the only place such
a line is written, and it is built so that nothing from a task can reach one:

* **Narrow inputs.** :func:`compile_playbook` takes :class:`PlaybookSignal` (a class
  signature, a template id, slot values and the ids of the tasks and rows that taught it)
  and :class:`RepoFacts` (the repository's configured check commands and tool names). It
  cannot take a row, a pack, a diff, a review or an error text — and this module imports
  nothing that holds one (``tests/test_playbook_leakage.py`` pins the imports).
* **Closed templates.** :data:`TEMPLATES` is the whole vocabulary of lines: a network
  refusal, a history refusal, format before finishing, a lint rule, keep the public API,
  finish with a source change. Each has a command-free variant used when a slot fails.
* **Checked slots.** A command head must be in :data:`VERB_ALLOWLIST`, a tool in
  :data:`TOOL_VOCAB`, a rule id must match :data:`RULE_RE`, and a command must match
  :data:`COMMAND_RE` and come from configuration. A slot that fails is dropped (the
  command-free variant is used), never repaired.
* **Held out by task.** :func:`held_out` keeps a line for task T only when at least two
  OTHER tasks taught it.
* **A leak gate.** :func:`leak_gate` drops a line whose slot values share a token of four
  or more characters with T's target tests, test files or source files. The fixed words of
  a template cannot come from a task and are not gated; only slot values can carry a
  task's words, so only they are compared.
* **A hard cap.** At most :data:`MAX_LINES` lines of :data:`MAX_LINE_CHARS` characters,
  :data:`MAX_CHARS` in all, one per signature.

Navigation
----------
What it is:   The playbook compiler — closed templates, checked slots, the held-out rule and
              the leak gate for the prevention loop's advisory lines (ADR-0020 §7).
What it does: Renders a line per class signal from a closed template whose slots pass a
              closed vocabulary; compiles at most seven lines under the character caps; keeps
              a line for task T only when two other tasks taught it; drops a line whose slot
              values share a token with T's test or source file names. Refuses anything that
              is not a signal or a repository fact.
How:          ``render_line`` (template → slot checks → command-free fallback → cap) →
              ``compile_playbook`` (rank by spend, one per signature, caps) → at injection
              ``held_out`` → ``leak_gate``.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0020-a-bug-is-closed-by-prevention.md,
              docs/adr/0008-stdlib-core-and-downward-layers.md
Works with:   src/crb/core/prevention.py (builds the signals and records the lines it
              applied), src/crb/builders/adapter.py (injects the lines, re-checks commands with
              the builder's shell guard), src/crb/builders/base.py (``BuildBrief.playbook`` —
              where the lines are rendered), tests/fixtures/shell_corpus.txt (the honest corpus
              every recommended command must belong to)
Tested by:    tests/test_playbook_leakage.py, tests/test_prevention_rule.py
Touch when:   never for a new repository; a new template needs an ADR-0020 amendment, a
              leakage test that plants a canary in its slots, and a template id the catalogue
              in src/crb/core/prevention.py names.
Claims:       A line is an operating fact, never evidence that a class stopped; only the
              prevention rule's measurement can say that (docs/LEARNING-LOOP.md §7,
              "Prevention — a bug is closed by a change that stops it recurring").
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

#: The caps (ADR-0020 §7): a checklist, never an essay.
MAX_LINES = 7
MAX_LINE_CHARS = 160
MAX_CHARS = 1000

#: The heading the brief renders the lines under.
HEADING = "Operating notes for this repository (a checklist):"

#: Signatures no template may ever serve: budget ("be quicker"), capability and review
#: defects ("be more careful") and factory outcomes — the essay that measured worse than a
#: checklist. fnmatch-style patterns.
NO_TEMPLATE: tuple[str, ...] = (
    "budget:*",
    "builder_red:target_red",
    "review:defect",
    "review:regression",
    "factory:*",
)

#: The command heads a line may name, exactly (a closed tuple; anything else takes the
#: command-free variant).
VERB_ALLOWLIST: tuple[str, ...] = (
    "pip install",
    "pip3 install",
    "pip download",
    "uv pip",
    "uv run",
    "uv sync",
    "uv add",
    "poetry install",
    "poetry add",
    "npm install",
    "npm ci",
    "npm i",
    "npx",
    "yarn add",
    "yarn install",
    "pnpm install",
    "pnpm add",
    "go get",
    "go mod",
    "go install",
    "cargo fetch",
    "cargo add",
    "cargo install",
    "curl",
    "wget",
    "git log",
    "git show",
    "git stash",
    "git blame",
    "git reflog",
    "git fetch",
    "git checkout",
    "git switch",
    "git diff",
    "git bisect",
)

#: The tool names a line may name (belt 5's plan tools, ``crb.core.lint``).
TOOL_VOCAB: tuple[str, ...] = (
    "gofmt",
    "ruff",
    "ruff-format",
    "eslint",
    "prettier",
    "standard",
    "tsc",
    "spotless",
    "checkstyle",
    "cargo-fmt",
    "clippy",
)

#: A rule id: the grammar of every linter the plan runs (``E501``, ``no-unused-vars``,
#: ``@typescript-eslint/no-explicit-any``, ``TS2345``, ``clippy::needless_return``,
#: ``LineLength``).
RULE_RE = re.compile(r"^[A-Za-z@][A-Za-z0-9@/_:.-]{0,63}$")
#: A command a line may recommend: configuration only, and no shell metacharacters.
COMMAND_RE = re.compile(r"^[A-Za-z0-9 ._/=:@+,-]{1,120}$")

#: The closed table: id → (text with slots, command-free variant, level rank for ordering).
#: Slots: ``{head}`` (a refused command head), ``{tool}``, ``{rule}``, ``{format_cmd}``,
#: ``{lint_cmd}``. The optional clauses are chosen by :func:`render_line`, never by format
#: tricks, so a failed slot can only ever shorten a line.
TEMPLATES: dict[str, dict[str, str]] = {
    "T-NET": {
        "full": "No network: `{head}` is refused and ends the attempt. Dependencies are "
        "installed; check your work with the test command above.",
        "free": "No network: installing or fetching anything is refused and ends the attempt. "
        "Dependencies are installed; check your work with the test command above.",
    },
    "T-ARCH": {
        "full": "Repository history is off limits: `{head}` ends the attempt. Work only from "
        "the files in the worktree.",
        "free": "Repository history is off limits: reading other commits ends the attempt. "
        "Work only from the files in the worktree.",
    },
    "T-FMT": {
        "full_cmd": "`{tool}` formats this repository: run `{format_cmd}` over the files you "
        "change before you finish.",
        "full": "`{tool}` formats this repository: run it over the files you change before "
        "you finish.",
        "free": "This repository's formatter checks every changed file: format the files you "
        "change before you finish.",
    },
    "T-LINT": {
        "full_cmd": "`{tool}` rejects `{rule}` here: fix it in the files you change, check with "
        "`{lint_cmd}` before you finish.",
        "full": "`{tool}` rejects `{rule}` here: fix it in the files you change before you finish.",
        "tool": "`{tool}` checks every changed file here: fix its findings in the files you "
        "change before you finish.",
        "free": "This repository's linter checks every changed file: fix its findings in the "
        "files you change before you finish.",
    },
    "T-API": {
        "free": "Keep exported names and signatures as they are unless the change asks for a "
        "new one.",
    },
    "T-CHANGE": {
        "free": "Finish only with a change to the source: an attempt with no source change fails.",
    },
}

#: Which slots each template reads (for :func:`slot_values` and the leak gate).
SLOT_RULES: dict[str, tuple[str, ...]] = {
    "T-NET": ("head",),
    "T-ARCH": ("head",),
    "T-FMT": ("tool", "format_cmd"),
    "T-LINT": ("tool", "rule", "lint_cmd"),
    "T-API": (),
    "T-CHANGE": (),
}

_SLOT_RE = re.compile(r"\{[a-z_]+\}")
_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_CAMEL_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")
#: The shortest token the leak gate compares (ADR-0020 §7: four or more characters).
LEAK_MIN = 4


@dataclass(frozen=True)
class RepoFacts:
    """What the repository's configuration says about its own checks: the commands (from
    configuration — stream W's ``checks.commands``, or the declared lint command) and the
    tool names its plan runs. Never read from a task."""

    test_cmd: str = ""
    lint_cmd: str = ""
    format_cmd: str = ""
    typecheck_cmd: str = ""
    tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlaybookSignal:
    """One class's facts for a line: the signature, the template, the slot values, and the
    tasks and rows that taught it (for the held-out rule and provenance). ``spend`` ranks."""

    template_id: str
    signature: str
    slots: Mapping[str, str] = field(default_factory=dict)
    taught_by_tasks: tuple[str, ...] = ()
    taught_by_rows: tuple[str, ...] = ()
    spend: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "slots", {str(k): str(v) for k, v in self.slots.items()})
        object.__setattr__(self, "taught_by_tasks", tuple(sorted(set(self.taught_by_tasks))))
        object.__setattr__(self, "taught_by_rows", tuple(self.taught_by_rows))


@dataclass(frozen=True)
class PlaybookLine:
    """One rendered line. ``commands`` are the commands the line RECOMMENDS (from
    configuration); the adapter checks each against the builder's own shell guard and
    drops the line if one is refused. ``slot_values`` are what the leak gate compares."""

    line_id: str
    template_id: str
    signature: str
    text: str
    taught_by_tasks: tuple[str, ...] = ()
    taught_by_rows: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    slot_values: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "template_id": self.template_id,
            "signature": self.signature,
            "text": self.text,
            "taught_by_tasks": list(self.taught_by_tasks),
            "taught_by_rows": list(self.taught_by_rows),
            "commands": list(self.commands),
            "slot_values": list(self.slot_values),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> PlaybookLine:
        return cls(
            line_id=str(d.get("line_id", "")),
            template_id=str(d.get("template_id", "")),
            signature=str(d.get("signature", "")),
            text=str(d.get("text", "")),
            taught_by_tasks=tuple(str(x) for x in d.get("taught_by_tasks", ()) or ()),
            taught_by_rows=tuple(str(x) for x in d.get("taught_by_rows", ()) or ()),
            commands=tuple(str(x) for x in d.get("commands", ()) or ()),
            slot_values=tuple(str(x) for x in d.get("slot_values", ()) or ()),
        )


@dataclass(frozen=True)
class Playbook:
    """The compiled lines, their digest and their total length."""

    lines: tuple[PlaybookLine, ...]
    sha256: str
    chars: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "lines": [ln.to_dict() for ln in self.lines],
            "sha256": self.sha256,
            "chars": self.chars,
            "max_lines": MAX_LINES,
            "max_chars": MAX_CHARS,
        }


def _fnmatch(name: str, pattern: str) -> bool:
    """``fnmatch`` without the import (``*`` only): the NO_TEMPLATE patterns are prefixes."""
    if pattern.endswith("*"):
        return name.startswith(pattern[:-1])
    return name == pattern


def has_template(signature: str) -> bool:
    """``False`` for a signature no template may serve (:data:`NO_TEMPLATE`)."""
    return not any(_fnmatch(signature, p) for p in NO_TEMPLATE)


def line_id_for(template_id: str, signature: str, text: str) -> str:
    """``sha256(template | signature | text)[:12]`` — stable across ticks."""
    return hashlib.sha256("\x1f".join((template_id, signature, text)).encode("utf-8")).hexdigest()[
        :12
    ]


def playbook_digest(texts: Sequence[str]) -> str:
    """The digest the row records as ``learn_playbook`` (``""`` for no line)."""
    if not texts:
        return ""
    return hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest()[:16]


def display_rule(tool: str, rule: str) -> str:
    """A rule id as its tool prints it (signatures are lower-cased; ruff and tsc codes are
    upper-case in their own output)."""
    if tool == "ruff" and re.fullmatch(r"[a-z]{1,4}\d{2,4}", rule):
        return rule.upper()
    if tool == "tsc" and re.fullmatch(r"ts\d{3,5}", rule):
        return rule.upper()
    return rule


def _ok_head(head: str) -> bool:
    return head in VERB_ALLOWLIST


def _ok_tool(tool: str) -> bool:
    return tool in TOOL_VOCAB


def _ok_rule(rule: str) -> bool:
    return rule not in ("", "*") and bool(RULE_RE.match(rule))


def _ok_command(cmd: str) -> bool:
    return bool(cmd) and bool(COMMAND_RE.match(cmd))


def render_line(signal: PlaybookSignal, facts: RepoFacts | None = None) -> PlaybookLine | None:
    """The line a signal renders, or ``None`` (unknown template, a signature no template
    serves, or a line that cannot fit the cap even command-free). Each slot is checked
    against its closed vocabulary; a slot that fails selects the next shorter variant."""
    facts = facts or RepoFacts()
    tpl = TEMPLATES.get(signal.template_id)
    if tpl is None or not has_template(signal.signature):
        return None
    s = signal.slots
    head, tool, rule = s.get("head", ""), s.get("tool", ""), s.get("rule", "")
    candidates: list[tuple[str, dict[str, str], tuple[str, ...]]] = []
    tid = signal.template_id
    if tid in ("T-NET", "T-ARCH"):
        if _ok_head(head):
            candidates.append(("full", {"head": head}, ()))
    elif tid == "T-FMT":
        if _ok_tool(tool):
            if _ok_command(facts.format_cmd):
                candidates.append(
                    (
                        "full_cmd",
                        {"tool": tool, "format_cmd": facts.format_cmd},
                        (facts.format_cmd,),
                    )
                )
            candidates.append(("full", {"tool": tool}, ()))
    elif tid == "T-LINT" and _ok_tool(tool):
        if _ok_rule(rule):
            shown = display_rule(tool, rule)
            if _ok_command(facts.lint_cmd):
                candidates.append(
                    (
                        "full_cmd",
                        {"tool": tool, "rule": shown, "lint_cmd": facts.lint_cmd},
                        (facts.lint_cmd,),
                    )
                )
            candidates.append(("full", {"tool": tool, "rule": shown}, ()))
        candidates.append(("tool", {"tool": tool}, ()))
    candidates.append(("free", {}, ()))
    for variant, values, commands in candidates:
        text = tpl.get(variant)
        if text is None:
            continue
        for k, v in values.items():
            text = text.replace("{" + k + "}", v)
        if _SLOT_RE.search(text) or len(text) > MAX_LINE_CHARS:
            continue
        return PlaybookLine(
            line_id=line_id_for(tid, signal.signature, text),
            template_id=tid,
            signature=signal.signature,
            text=text,
            taught_by_tasks=signal.taught_by_tasks,
            taught_by_rows=signal.taught_by_rows,
            commands=commands,
            slot_values=tuple(v for v in values.values() if v),
        )
    return None


def compile_playbook(signals: Iterable[PlaybookSignal], facts: RepoFacts | None = None) -> Playbook:
    """At most :data:`MAX_LINES` lines, one per signature, ranked by the spend of the class
    they address (then by signature, for determinism), each within :data:`MAX_LINE_CHARS`
    and all within :data:`MAX_CHARS`. Every template here is advisory, so rank by level is
    one level; spend orders within it."""
    ordered = sorted(signals, key=lambda sg: (-round(sg.spend, 6), sg.signature, sg.template_id))
    lines: list[PlaybookLine] = []
    seen: set[str] = set()
    chars = 0
    for sg in ordered:
        if sg.signature in seen or len(lines) >= MAX_LINES:
            continue
        line = render_line(sg, facts)
        if line is None or chars + len(line.text) > MAX_CHARS:
            continue
        seen.add(sg.signature)
        lines.append(line)
        chars += len(line.text)
    return Playbook(tuple(lines), playbook_digest([ln.text for ln in lines]), chars)


def held_out(
    lines: Iterable[PlaybookLine], task_id: str, *, min_other: int = 2
) -> tuple[list[PlaybookLine], list[str]]:
    """``(kept, dropped ids)``: a line reaches task T only when at least ``min_other``
    OTHER tasks taught it — so a line learned from T alone can never be injected into T."""
    kept: list[PlaybookLine] = []
    dropped: list[str] = []
    for ln in lines:
        others = {t for t in ln.taught_by_tasks if t != task_id}
        if len(others) >= min_other:
            kept.append(ln)
        else:
            dropped.append(ln.line_id)
    return kept, dropped


def tokens(text: str) -> set[str]:
    """Every word of ``text`` (split on non-alphanumerics and on camelCase), lower-cased,
    of at least :data:`LEAK_MIN` characters."""
    out: set[str] = set()
    for word in _WORD_RE.findall(text):
        if len(word) >= LEAK_MIN:
            out.add(word.lower())
        for part in _CAMEL_RE.findall(word):
            if len(part) >= LEAK_MIN:
                out.add(part.lower())
    return out


def leak_gate(
    lines: Iterable[PlaybookLine],
    *,
    target_tests: Sequence[str] = (),
    test_files: Sequence[str] = (),
    src_files: Sequence[str] = (),
) -> tuple[list[PlaybookLine], list[str]]:
    """``(kept, dropped ids)``: drop any line whose slot values share a token of four or
    more characters with T's target tests, test files or source files. The fixed words of
    a template are constants in this file and cannot come from a task; the slot values are
    the only path a task's words could take, so they are what is compared."""
    stems: set[str] = set()
    for name in (*target_tests, *test_files, *src_files):
        stems |= tokens(str(name))
    kept: list[PlaybookLine] = []
    dropped: list[str] = []
    for ln in lines:
        slot_tokens: set[str] = set()
        for v in (*ln.slot_values, *ln.commands):
            slot_tokens |= tokens(v)
        if slot_tokens & stems:
            dropped.append(ln.line_id)
        else:
            kept.append(ln)
    return kept, dropped


__all__ = [
    "COMMAND_RE",
    "HEADING",
    "MAX_CHARS",
    "MAX_LINES",
    "MAX_LINE_CHARS",
    "NO_TEMPLATE",
    "RULE_RE",
    "SLOT_RULES",
    "TEMPLATES",
    "TOOL_VOCAB",
    "VERB_ALLOWLIST",
    "Playbook",
    "PlaybookLine",
    "PlaybookSignal",
    "RepoFacts",
    "compile_playbook",
    "display_rule",
    "has_template",
    "held_out",
    "leak_gate",
    "line_id_for",
    "playbook_digest",
    "render_line",
    "tokens",
]
