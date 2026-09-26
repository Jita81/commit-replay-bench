"""The prevention loop — a bug class is closed by a change the attempts prove (ADR-0020).

The operator, 2026-09-25: *"We should be learning from a bug and then going back to update
our process or context to remove it moving forward."* This module is that loop's engine,
pure and standard-library only:

1. **What a class is** (:func:`signatures`, rule version :data:`SIGNATURE_RULES`): a
   deterministic ``family:sub[:detail]`` read from a row's hashed fields (and, for belt 5, the
   evidence pack's step tails; for a review, the standing verdict; for the factory, its
   outcome events). An ``outage`` row observed nothing and is never a class.
2. **The register** (:func:`build_register`): for each class of one repository, its evidence
   on first attempts, the lever the loop would choose and why, the change in force and its
   measurement, a status (:data:`STATUSES`) and one sentence saying what happens next. The
   function takes no filter: nothing can drop a row, a task or a class on the way in.
3. **The lever** (:func:`choose_lever`): the strongest the class admits — construction, gate,
   mistake-proofing, advisory — skipping what this build does not ship, what is on already,
   what the switch forbids, what the team set itself, what the loop retired and what a
   person reverted. A code lever is *proposed* for a person (dual track); a playbook line is
   the last resort, and only from a closed template (:mod:`crb.core.playbook`).
4. **The rule** (:data:`DECISION_RULE`, :func:`due_decisions`): the unit is a first attempt;
   the before window is frozen at application; exposure is read from the row's OWN labels;
   two looks only (decisive n from p0), a harm check, a closing window, reopen, displaced,
   inconclusive. Capability classes are measured but never decided.
5. **The chain** (:class:`PreventionRecord`): the loop's acts — ``switched``, ``applied``,
   ``decided``, ``reverted``, ``proposed``, ``registered``, ``linked`` — hash-chained,
   attributable and stamped with the rule versions; the only state there is.
6. **The tick** (:func:`tick`): pure — the records a tick would append, nothing when the
   switch is off, nothing new when run twice over the same state.
7. **The snapshot** (:func:`snapshot`): what one run is given — the overlay the loop's
   switches add under the team's own configuration, and the lines, held out by task and
   leak-gated at injection.

The one rule it keeps: **the loop changes how a change is made, never how it is judged.**
:func:`check_writable` refuses every configuration key outside :data:`WRITABLE`.

Navigation
----------
What it is:   The prevention loop's engine — class signatures, the lever catalogue, the
              register, the apply → measure → decide rule, the hash-chained record of the
              loop's acts, the tick and the per-run snapshot (ADR-0020).
What it does: Computes every class of a repository from its rows, reviews and factory
              events; picks the strongest admissible lever; decides keep / retire / harm /
              closed / reopened / displaced / inconclusive on the first attempts whose labels
              name the change, against a before window frozen when the change was applied;
              writes nothing but chained records, and refuses any grader key. Serves stream
              S's register seam (``PreventionRegister``).
How:          ``signatures`` (failure kind → family table) → ``build_register`` (per-class
              aggregates, stratum, key, actionable, folds of the chain → ``choose_lever`` →
              ``measure`` → status) → ``tick`` (``due_decisions`` → ``reverted`` → apply /
              propose with a frozen ``before_window``) → ``snapshot`` (``in_force`` → overlay
              + lines → labels).
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0020-a-bug-is-closed-by-prevention.md,
              docs/adr/0002-append-only-hash-chained-ledger.md,
              docs/adr/0008-stdlib-core-and-downward-layers.md
Works with:   src/crb/core/ledger.py (the rows, the failure rule the signatures sit on, the
              chain helpers), src/crb/core/learn.py (``parse_violations`` and
              ``normalise_command`` — the protocol signature), src/crb/core/playbook.py (the
              closed templates a line is rendered from), src/crb/core/review.py (the standing
              review a ``review:`` class reads), src/crb/server/prevention_state.py (the events
              store, the snapshot and the tick on a live stack), src/crb/builders/adapter.py
              (injects the lines and stamps the labels)
Tested by:    tests/test_prevention_signatures.py, tests/test_prevention_store.py,
              tests/test_prevention_rule.py, tests/test_prevention_gaming.py,
              tests/test_prevention_register_seam.py, tests/test_playbook_leakage.py,
              tests/test_worker_learning.py, tests/test_server_routes_prevention.py
Touch when:   never for a new repository; a new failure kind or a new belt needs a family
              row here and a bump of ``SIGNATURE_RULES`` (the golden fixture fails
              otherwise); a new process mechanism (stream W or K) enters ``WRITABLE`` and the
              catalogue only with an ADR-0020 amendment; a threshold change bumps
              ``DECISION_RULE``.
Claims:       A class reads ``closed`` only after a kept change and a zero run of
              ``max(20, decisive n)`` exposed first attempts with no displacement; a quiet
              class with no change on record is ``dormant`` and is never credited
              (docs/EVIDENCE-AND-CLAIMS.md#7-what-may-be-claimed).
"""

from __future__ import annotations

import datetime as _dt
import fnmatch
import hashlib
import json
import math
import os
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

from crb.core.evidence import canonical_json, sha256_text, utc_now_iso
from crb.core.learn import (
    PREFIX_OTHER,
    normalise_command,
    parse_violations,
    row_violation_text,
)
from crb.core.ledger import (
    BUDGET_STOP_REASONS,
    FAILURE_BUDGET,
    FAILURE_BUILDER_RED,
    FAILURE_CLEAN,
    FAILURE_DISQUALIFIED,
    FAILURE_HARNESS,
    FAILURE_LINT,
    FAILURE_OUTAGE,
    FAILURE_PROTOCOL,
    GENESIS_HASH,
    GradeRow,
    LedgerIntegrityError,
    jsonl_append_lock,
    jsonl_last_line,
    parse_apparatus_version,
)
from crb.core.lint import LINT_TAIL_CHARS
from crb.core.playbook import (
    MAX_CHARS,
    MAX_LINES,
    PlaybookLine,
    PlaybookSignal,
    RepoFacts,
    has_template,
    held_out,
    leak_gate,
    playbook_digest,
    render_line,
)
from crb.core.redact import redact
from crb.core.review import SEVERITY, ReviewRecord, latest_reviews
from crb.core.spend import is_escalated_trial
from crb.core.stats import wilson_interval
from crb.core.version import APPARATUS_VERSION

# ===========================================================================
# Vocabulary and thresholds
# ===========================================================================

#: What a class is. Changing any family rule below bumps this (the golden fixture in
#: tests/test_prevention_signatures.py fails otherwise).
SIGNATURE_RULES = "crb.prevention.sig.v1"
#: When a change is kept, retired or closed.
DECISION_RULE = "crb.prevention.rule.v1"
RECORD_SCHEMA = "crb.prevention.record.v1"
REGISTER_SCHEMA = "crb.prevention.register.v1"

#: The prevention hierarchy, strongest first (docs/PREVENTION.md uses the same words).
LEVELS: tuple[str, ...] = ("construction", "gate", "mistake-proofing", "advisory")
#: A mechanism that stops a class spending but never removes it (K's escalation rule, D's
#: pre-check). Containment never closes a class.
CONTAINMENT = "containment"
#: Stream S's five (``crb.core.value.CLASS_STATUSES`` — the merge pins the equality).
STATUSES: tuple[str, ...] = ("open", "applied", "closed", "retired", "escalated")
QUALIFIERS: tuple[str, ...] = (
    "watch",
    "dormant",
    "capability",
    "contained",
    "overridden",
    "suspended",
    "displaced",
    "reopened",
    "unproven",
    "unmeasurable",
)
FAMILIES: tuple[str, ...] = (
    "protocol",
    "budget",
    "harness",
    "lint",
    "format",
    "api",
    "builder_red",
    "disqualified",
    "review",
    "factory",
)
#: Classes whose only process lever is judged by value (stream S's working changes per
#: pound in the Phase B A/B), never by recurrence: routing holds them.
CAPABILITY_CLASSES: frozenset[str] = frozenset(
    {"builder_red:target_red", "review:defect", "review:regression"}
)
#: A belt-5 rejection whose every rejecting step is one of these is ``format:<tool>``.
#: Every formatter stream W's format step can write (``crb.core.formatting.FORMATTER_WRITE``
#: less ``standard``, a linter with a fix mode) is here; tests/test_value_wiring.py pins it.
FORMATTER_TOOLS: tuple[str, ...] = (
    "gofmt",
    "ruff-format",
    "prettier",
    "spotless",
    "cargo-fmt",
    "black",
)
#: The closed vocabulary of tools a ``harness:`` signature may name; anything else is
#: ``other`` (a signature never carries free text).
HARNESS_TOOLS: frozenset[str] = frozenset(
    {
        "jest",
        "mocha",
        "vitest",
        "ava",
        "tap",
        "npx",
        "node",
        "npm",
        "yarn",
        "pnpm",
        "pytest",
        "python",
        "python3",
        "pip",
        "pip3",
        "uv",
        "poetry",
        "tox",
        "nox",
        "go",
        "gofmt",
        "cargo",
        "rustc",
        "mvn",
        "gradle",
        "java",
        "ruff",
        "eslint",
        "prettier",
        "standard",
        "tsc",
        "spotless",
        "checkstyle",
        "clippy",
        "black",
        "git",
        "docker",
    }
)

AUTO_OFF = "off"
AUTO_CONTEXT = "context"
AUTO_CONFIG = "config"
AUTO_MODES: tuple[str, ...] = (AUTO_OFF, AUTO_CONTEXT, AUTO_CONFIG)

RECORD_KINDS: tuple[str, ...] = (
    "switched",
    "applied",
    "decided",
    "reverted",
    "proposed",
    "registered",
    "linked",
)

#: Stream D's pre-check prefix (``crb.builders.toolcheck.RUNNER_TOOL_MISSING``; the core
#: cannot import the builders — the merge adds the equality test).
RUNNER_TOOL_MISSING_PREFIX = "runner tool missing: "
#: Stream W's per-repository switchboard (``RepoConfig.checks``, ``crb.core.checks``).
W_SECTION = "checks"
#: Stream K's per-repository spend section (``RepoConfig.spend``, ``crb.core.spend``).
K_SECTION = "spend"

# --- the labels every row carries (hashed; ADR-0020 §8) -------------------------------
LABEL_LEARN = "learn"
LABEL_CHANGES = "learn_changes"
LABEL_OVERLAY = "learn_overlay"
LABEL_PLAYBOOK = "learn_playbook"
LABEL_LINES = "learn_lines"
LABEL_DROPPED = "learn_dropped"
#: Stream W's own label (the formatter step ran and what it changed).
LABEL_FORMAT_STEP = "format_step"
#: Stream W's belt-6 labels.
LABEL_API_STABLE = "api_stable"
LABEL_API_FINDINGS = "api_findings"

# --- thresholds (crb.prevention.rule.v1) ----------------------------------------------
ACTIONABLE_MIN_K = 2
ACTIONABLE_MIN_TASKS = 2
ACTIONABLE_MIN_N = 10
BEFORE_MAX = 100
ALPHA_LOOK = 0.025
ALPHA_HARM = 0.01
HARM_AT = 10
DECISIVE_MIN = 10
DECISIVE_MAX = 200
DETERMINISTIC_N = 3
CLOSE_MIN = 20
DISPLACEMENT = 0.05
MAX_CHANGE_IDS = 8
OUTAGE_SPIKE = 2.0
#: The outage share a spike is measured against when the before window had none.
OUTAGE_FLOOR = 0.05
#: How many evidence row hashes an entry serves (the total is always served).
REFS_MAX = 50


class NotWritable(ValueError):
    """The loop was asked to write a key outside :data:`WRITABLE` — a grader key, a runner,
    the lint plan, anything that would change how a change is judged."""

    code = "not_writable"


# ===========================================================================
# 1. Signatures — what a class is (crb.prevention.sig.v1)
# ===========================================================================

_PART_RE = re.compile(r"[^a-z0-9 _.+*/@:-]")
_TOKEN_RE = re.compile(r"^[a-z][a-z0-9._+-]{0,31}$")
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_PY_RE = re.compile(r"^(python|pypy)\d?(\.\d+)?$")
_SEPARATORS = frozenset({"&&", "||", ";", "|", "|&", "&", "\\n"})
_PREFIX_WORDS = frozenset({"sudo", "env", "nohup", "command", "exec", "time"})
#: Tools whose second word is a verb (``pip install``, ``go mod``, ``git log``); any other
#: command head keeps one word so an argument (a host, a package) never splits a class.
_SUBCOMMAND_TOOLS = frozenset(
    {
        "pip",
        "pip3",
        "pipx",
        "uv",
        "poetry",
        "conda",
        "npm",
        "npx",
        "yarn",
        "pnpm",
        "bun",
        "deno",
        "go",
        "cargo",
        "git",
        "mvn",
        "gradle",
        "docker",
        "apt",
        "apt-get",
        "brew",
        "gem",
        "bundle",
        "dotnet",
    }
)
_TIMEOUT_ARG_RE = re.compile(r"^(<n>|\d+(\.\d+)?[smhd]?)$")


def _part(text: str) -> str:
    """One signature part: lower-case ASCII, a closed character set, collapsed spaces."""
    s = text.encode("ascii", errors="ignore").decode("ascii").lower()
    s = _PART_RE.sub("-", s)
    s = " ".join(s.split()).strip(" -")
    return s or "-"


def make_signature(family: str, sub: str, detail: str | None = None) -> str:
    """``family:sub[:detail]``, lower-case ASCII, at most 96 characters."""
    parts = [family, _part(sub)]
    if detail:
        parts.append(_part(detail))
    return ":".join(parts)[:96]


def split_signature(signature: str) -> tuple[str, str, str]:
    """``(family, sub, detail)`` — the detail may itself hold colons (``clippy::x``)."""
    family, _, rest = signature.partition(":")
    sub, _, detail = rest.partition(":")
    return family, sub, detail


def command_head(command: str) -> str:
    """The first one or two word tokens of a refused command, after environment
    assignments, ``cd … &&``, ``sudo``, ``env`` and ``timeout <n>``; ``python -m <mod>``
    keeps three. Works on :func:`crb.core.learn.normalise_command`, so a path, a quoted
    string, a number, a URL or a sha is already a placeholder and stops the head, as does a
    flag. ``"-"`` when nothing is left."""
    text = normalise_command(command)
    segments: list[list[str]] = [[]]
    for tok in text.split():
        if tok in _SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(tok)
    for seg in segments:
        i = 0
        while i < len(seg):
            t = seg[i]
            if t == "cd":
                i += 2
            elif t in _PREFIX_WORDS or _ASSIGN_RE.match(t):
                i += 1
            elif t == "timeout":
                i += 2 if i + 1 < len(seg) and _TIMEOUT_ARG_RE.match(seg[i + 1]) else 1
            else:
                break
        rest = seg[i:]
        if not rest or not _TOKEN_RE.match(rest[0]):
            continue
        head = [rest[0]]
        if (
            _PY_RE.match(rest[0])
            and len(rest) >= 3
            and rest[1] == "-m"
            and _TOKEN_RE.match(rest[2])
        ):
            head += ["-m", rest[2]]
        elif rest[0] in _SUBCOMMAND_TOOLS and len(rest) >= 2 and _TOKEN_RE.match(rest[1]):
            head.append(rest[1])
        return " ".join(head)
    return "-"


def _tool(name: str) -> str:
    n = name.strip().strip("'\"`:,()").lower()
    return n if n in HARNESS_TOOLS else "other"


_CREDENTIAL_RE = re.compile(
    r"\b(api[ _-]?key|credential|credentials|access token|auth token)\b[^.\n]{0,60}?"
    r"\b(not set|missing|not configured|not found|absent|is empty|required)\b"
    r"|\bno (api[ _-]?key|credential|credentials)\b"
)
_NOT_FOUND_RE = re.compile(
    r"(?:^|[\s:'\"(`])([a-z][a-z0-9._+-]{0,31})['\"`]?:?\s+(?:command\s+)?not found"
    r"|(?:executable|command|binary|tool)\s+['\"`]?([a-z][a-z0-9._+-]{0,31})['\"`]?\s+(?:was\s+)?not found"
)
_ENV_NETWORK_RE = re.compile(
    r"\b(pip3?|npm|yarn|pnpm|go|cargo|mvn|gradle|uv|poetry)\b.*?"
    r"\b(could not resolve|resolve|unreachable|proxy|name resolution|temporary failure|"
    r"connection refused|network)"
)
_LINT_TOOL_RE = re.compile(r"^lint:\s*([a-z][a-z0-9._+-]*)")
_SANDBOX_RE = re.compile(r"\b(sandbox|docker|container)\b")
_TIMEOUT_RE = re.compile(r"time ?out|timed out")


def harness_cause(error: str) -> tuple[str, str]:
    """``(cause, tool)`` for a harness row, by ONE ordered table over the lower-cased error
    (first match wins; the fixture corpus tests/fixtures/prevention/harness_errors.txt pins
    it):

    1. stream D's pre-check, ``runner tool missing: <tool>`` → ``runner-tool-missing``
    2. a linter that could not run (``lint: …``, the grader's own prefix) → ``linter-unrunnable``
    3. an API key or credential not set → ``no-credential``
    4. ``<tool>: command not found`` / ``executable <tool> not found`` → ``runner-tool-missing``
    5. an installer with a resolve, proxy or network error → ``env-network``
    6. sandbox, docker or container → ``sandbox``
    7. a timeout → ``timeout``
    8. anything else → ``other``

    A tool outside :data:`HARNESS_TOOLS` is ``other``: the signature never carries free text.
    """
    e = error.strip().lower()
    if e.startswith(RUNNER_TOOL_MISSING_PREFIX):
        rest = e[len(RUNNER_TOOL_MISSING_PREFIX) :].split()
        return "runner-tool-missing", _tool(rest[0] if rest else "")
    if e.startswith("lint:"):
        m = _LINT_TOOL_RE.match(e)
        return "linter-unrunnable", _tool(m.group(1) if m else "")
    if _CREDENTIAL_RE.search(e):
        return "no-credential", ""
    m = _NOT_FOUND_RE.search(e)
    if m:
        return "runner-tool-missing", _tool(m.group(1) or m.group(2) or "")
    m = _ENV_NETWORK_RE.search(e)
    if m:
        return "env-network", _tool(m.group(1))
    if _SANDBOX_RE.search(e):
        return "sandbox", ""
    if _TIMEOUT_RE.search(e):
        return "timeout", ""
    return "other", ""


# --- belt 5 -----------------------------------------------------------------------------

_RULE_GRAMMAR = re.compile(r"^[A-Za-z@][A-Za-z0-9@/_:.-]{0,63}$")
#: ``path:line:col: `` — where a linter's concise output puts the location before the rule.
_LOC = r"[^\s:][^:\n]*:\d+:\d+:"
#: Each parser reads a rule id ONLY from the position its tool prints one: never anywhere a
#: message or a source snippet (the builder's own code) could put a rule-shaped word. ruff's
#: full output prints ``CODE message`` at the start of a line and quotes the code beneath it
#: in a numbered gutter; its concise output prints ``path:line:col: CODE message``
#: (docs/PREVENTION.md P-018).
_RULE_PARSERS: dict[str, tuple[re.Pattern[str], ...]] = {
    "ruff": (re.compile(rf"^(?:{_LOC} )?([A-Z]{{1,4}}\d{{2,4}})(?= |$)", re.M),),
    "eslint": (
        re.compile(
            r"^\s*\d+:\d+\s+(?:error|warning)\s+.+?\s{2,}(@?[a-z0-9-]+(?:/[a-z0-9-]+)?)\s*$",
            re.M,
        ),
    ),
    "standard": (
        re.compile(rf"^\s*{_LOC}\s.*\((@?[a-z0-9-]+(?:/[a-z0-9-]+)?)\)\s*$", re.M),
        re.compile(
            r"^\s*\d+:\d+\s+(?:error|warning)\s+.+?\s{2,}(@?[a-z0-9-]+(?:/[a-z0-9-]+)?)\s*$",
            re.M,
        ),
    ),
    "tsc": (
        re.compile(
            r"^(?:[^\s(][^(\n]*\(\d+,\d+\): |[^\s:][^:\n]*:\d+:\d+ - |)error (TS\d{3,5}):", re.M
        ),
    ),
    "clippy": (re.compile(r"^\s*= note: .*?#\[(?:warn|deny|forbid)\((clippy::[a-z_]+)\)\]", re.M),),
    "checkstyle": (re.compile(r"^\[(?:ERROR|WARN|WARNING)\] .*\[([A-Z][A-Za-z]+)\]\s*$", re.M),),
}
#: At most this many rule signatures from one row.
RULES_PER_ROW = 8


def _lint_steps(pack: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    """The belt-5 steps a pack recorded (``pack.grade.lint_run.steps``, as
    ``GradeResult.to_dict`` writes them); ``[]`` for anything else."""
    if not isinstance(pack, Mapping):
        return []
    grade = pack.get("grade")
    lint_run = grade.get("lint_run") if isinstance(grade, Mapping) else None
    steps = lint_run.get("steps") if isinstance(lint_run, Mapping) else None
    return [s for s in steps or () if isinstance(s, Mapping)]


def rule_ids(tool: str, tail: str) -> list[str]:
    """The rule ids a tool's step tail names, in order, deduplicated, grammar-checked —
    parsed by the tool's own output shape, never from a message's words."""
    out: list[str] = []
    text = tail or ""
    if len(text) >= LINT_TAIL_CHARS:
        # capped tail-first, so its first line may begin mid-line — inside a snippet
        text = text.split("\n", 1)[1] if "\n" in text else ""
    for pat in _RULE_PARSERS.get(tool, ()):
        for m in pat.finditer(text):
            rule = m.group(1)
            if _RULE_GRAMMAR.match(rule) and rule not in out:
                out.append(rule)
    return out[:RULES_PER_ROW]


def lint_signatures(pack: Mapping[str, Any] | None) -> tuple[str, ...]:
    """``format:<tool>`` when every rejecting step is a formatter; otherwise
    ``lint:<tool>:<rule>`` per rule the non-formatter steps name (``*`` when none parses).
    ``("lint:*",)`` when the pack is not there (an export, a missing pack)."""
    rejecting = [s for s in _lint_steps(pack) if s.get("verdict") is not True]
    if not rejecting:
        return ("lint:*",)
    tools = [str(s.get("tool", "")) for s in rejecting]
    if all(t in FORMATTER_TOOLS for t in tools):
        return tuple(dict.fromkeys(make_signature("format", t) for t in tools))
    out: list[str] = []
    for s in rejecting:
        tool = str(s.get("tool", ""))
        if tool in FORMATTER_TOOLS:
            continue
        rules = rule_ids(tool, str(s.get("tail", "")))
        for rule in rules or ["*"]:
            sig = make_signature("lint", tool or "*", rule)
            if sig not in out:
                out.append(sig)
    return tuple(out[:RULES_PER_ROW])


def api_signatures(labels: Mapping[str, str]) -> tuple[str, ...]:
    """The KIND of each belt-6 finding (``kind:unit:symbol;…``) — never the unit or the
    symbol; ``()`` when belt 6 held or did not run."""
    raw = str(labels.get(LABEL_API_FINDINGS, "") or "")
    kinds: list[str] = []
    for part in raw.split(";"):
        kind = part.strip().split(":", 1)[0].strip().lower()
        if kind in ("added", "removed", "changed") and kind not in kinds:
            kinds.append(kind)
    order = ("added", "removed", "changed")
    out = tuple(f"api:{k}" for k in order if k in kinds)
    if not out and str(labels.get(LABEL_API_STABLE, "")).lower() == "false":
        return ("api:*",)
    return out


def _builder_red_sub(row: GradeRow) -> str:
    if row.tests_unmodified is False:
        return "tests_modified"
    if row.source_changed is False:
        return "no_source_change"
    if row.no_new_failures is False:
        return "regression"
    if row.target_green is False:
        return "target_red"
    return "unknown"


_DQ_CODES: tuple[tuple[str, str], ...] = (
    ("worktree integrity", "worktree_integrity"),
    ("blind: builder modified test files", "blind_tests_modified"),
    ("test infrastructure modified", "test_infra_modified"),
    ("malformed oracle", "malformed_oracle"),
    ("non-target test files modified", "other_tests_modified"),
    ("target test file modified", "target_test_modified"),
)


def dq_code(reason: str) -> str:
    """A disqualification reason as its closed code (``other`` for anything unknown)."""
    r = reason.strip().lower()
    for prefix, code in _DQ_CODES:
        if r.startswith(prefix):
            return code
    return "other"


def blocked(row: GradeRow) -> bool:
    """A refusal before spend: stream D's pre-check stopped the replay before any builder
    call. Such a row still counts as an occurrence (it never closes a class)."""
    return row.error.lower().startswith(RUNNER_TOOL_MISSING_PREFIX)


def signatures(row: GradeRow, *, pack: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    """Every class a row shows, in source order, deduplicated; ``()`` for a clean row or an
    outage. Reads hashed row fields only (and, for belt 5, the pack's step tails)."""
    kind = row.failure_kind
    out: list[str] = []
    if kind in (FAILURE_CLEAN, FAILURE_OUTAGE):
        pass
    elif kind == FAILURE_PROTOCOL:
        for v in parse_violations(row_violation_text(row)) or []:
            prefix = v.prefix or PREFIX_OTHER
            out.append(make_signature("protocol", prefix, command_head(v.command)))
        if not out:
            out.append(make_signature("protocol", PREFIX_OTHER, "-"))
    elif kind == FAILURE_BUDGET:
        stop = row.stop_reason if row.stop_reason in BUDGET_STOP_REASONS else "unrecorded"
        out.append(make_signature("budget", stop))
    elif kind == FAILURE_HARNESS:
        cause, tool = harness_cause(row.error)
        out.append(make_signature("harness", cause, tool or None))
    elif kind == FAILURE_LINT:
        out.extend(lint_signatures(pack))
    elif kind == FAILURE_DISQUALIFIED:
        out.append(make_signature("disqualified", dq_code(row.dq_reason)))
    elif kind == FAILURE_BUILDER_RED:
        out.append(make_signature("builder_red", _builder_red_sub(row)))
    elif kind == "api":  # stream W's belt-6 kind (not in this build's FAILURE_KINDS yet)
        out.extend(api_signatures(row.labels) or ("api:*",))
    else:
        out.append(make_signature(kind or "unknown", "-"))
    if kind not in (FAILURE_OUTAGE, "api"):
        # belt 6 (stream W) can fail beside another kind; its classes are read from labels
        out.extend(api_signatures(row.labels) if not row.clean else ())
    return tuple(dict.fromkeys(out))


def pack_of(
    row: GradeRow, packs: Callable[[str], Mapping[str, Any] | None] | None
) -> Mapping[str, Any] | None:
    """The pack a row's signatures read — only a belt-5 row's, the one place a pack refines
    the class (``format:<tool>`` / ``lint:<tool>:<rule>``). Every register reads it here."""
    if packs is None or row.failure_kind != FAILURE_LINT or not row.evidence_pack_hash:
        return None
    return packs(row.evidence_pack_hash)


def primary_signature(row: GradeRow, *, pack: Mapping[str, Any] | None = None) -> str | None:
    """A row's first signature (its primary class), or ``None`` for a working row."""
    sigs = signatures(row, pack=pack)
    return sigs[0] if sigs else None


def review_signatures(record: ReviewRecord) -> tuple[str, ...]:
    """One ``review:<kind>`` per finding kind, most severe first; ``review:not_mergeable``
    for ``mergeable=False`` with no finding. Never the statement or a note."""
    kinds = {f.kind for f in record.findings}
    if not kinds and record.verdict in SEVERITY:
        kinds = {record.verdict}
    out = [f"review:{k}" for k in SEVERITY if k in kinds]
    if not out and record.mergeable is False:
        out.append("review:not_mergeable")
    return tuple(out)


#: Factory evidence kinds → the class they are (``crb.factory.evidence``'s literals; the
#: core cannot import the factory layer).
FACTORY_KINDS: dict[str, str] = {
    "delivery.closed": "factory:pr_closed",
    "red.refused": "factory:red_refused",
    "delivery.refused": "factory:delivery_refused",
}


def factory_signatures(events: Iterable[Mapping[str, Any]]) -> list[tuple[str, str, str, str]]:
    """``(item_id, signature, ref, created)`` for every factory outcome that is a class."""
    out: list[tuple[str, str, str, str]] = []
    for ev in events:
        sig = FACTORY_KINDS.get(str(ev.get("kind", "")))
        if sig is None:
            continue
        ref = str(ev.get("row_hash") or ev.get("event_id") or "")
        out.append((str(ev.get("item_id", "")), sig, ref, str(ev.get("created", ""))))
    return out


def is_first_attempt(trial: str) -> bool:
    """``r1`` (and ``""``, ``w1r1`` — anything that is not ``r2`` or later) is a first
    attempt: the complement of ``crb.core.spend.is_escalated_trial`` (stream K), so the loop
    and the escalation rule never disagree on what a retry is. A retry exists only after a
    failure, so counting it would credit the loop with K's escalation rule."""
    return not is_escalated_trial(trial)


def observable(row: GradeRow, family: str, *, reviewed: bool = False) -> bool:
    """Was the class's detector running on this row? Belt 5 for ``lint``/``format``,
    belt 6 for ``api``, a review for ``review``; ``factory`` has no row-level detector;
    every other family is observable on every attempt. Switching a detector on is never
    read as the class appearing."""
    if family in ("lint", "format"):
        return row.repo_lint_clean is not None
    if family == "api":
        return LABEL_API_STABLE in row.labels
    if family == "review":
        return reviewed
    return family != "factory"


def comparability_key(row: GradeRow) -> str:
    """``major.minor | builder family | model | signature rules`` — rows outside a change's
    key are shown, never pooled."""
    parsed = parse_apparatus_version(row.apparatus_version)
    app = f"{parsed[0]}.{parsed[1]}" if parsed else row.apparatus_version
    return f"{app}|{row.builder.split('+')[0]}|{row.model}|{SIGNATURE_RULES}"


def key_apparatus(key: str) -> str:
    return key.split("|", 1)[0]


# ===========================================================================
# 2. The lever catalogue and the one rule
# ===========================================================================


@dataclass(frozen=True)
class Lever:
    """One lever: ``family`` is ``config`` (a switch the loop throws), ``context`` (a
    playbook line), ``code`` (a filed item a person builds) or ``containment`` (shown, never
    chosen). ``admits`` are fnmatch patterns over signatures."""

    lever_id: str
    family: str
    level: str
    owner: str
    admits: tuple[str, ...]
    deterministic: bool = False
    scope: str = "repo"
    title: str = ""
    expected_effect: str = ""
    template_id: str = ""
    level_overrides: tuple[tuple[str, str], ...] = ()
    #: filed only when no other code lever admits the class — the end of every ladder
    fallback: bool = False

    def admits_sig(self, signature: str) -> bool:
        return any(fnmatch.fnmatchcase(signature, p) for p in self.admits)

    def level_for(self, signature: str) -> str:
        for pattern, level in self.level_overrides:
            if fnmatch.fnmatchcase(signature, pattern):
                return level
        return self.level

    def to_dict(self) -> dict[str, Any]:
        return {
            "lever_id": self.lever_id,
            "family": self.family,
            "level": self.level,
            "owner": self.owner,
            "admits": list(self.admits),
            "deterministic": self.deterministic,
            "scope": self.scope,
            "title": self.title,
        }


_INSTALLERS = (
    "protocol:network:pip*",
    "protocol:network:uv*",
    "protocol:network:poetry*",
    "protocol:network:conda*",
    "protocol:network:npm*",
    "protocol:network:npx*",
    "protocol:network:yarn*",
    "protocol:network:pnpm*",
    "protocol:network:go *",
    "protocol:network:cargo*",
    "protocol:network:mvn*",
    "protocol:network:gradle*",
)

#: THE catalogue — one closed table, in catalogue order (ties within a level go to the
#: earlier row).
LEVERS: tuple[Lever, ...] = (
    Lever(
        "format_step",
        "config",
        "construction",
        "W",
        ("format:*", "review:style"),
        deterministic=True,
        title="Run the repository's own formatter over the changed source files before grading",
        expected_effect="the patch is graded formatted, so a formatter rejection cannot recur",
    ),
    Lever(
        "finish_gate",
        "config",
        "gate",
        "W",
        (
            "lint:*",
            "format:*",
            "api:*",
            "builder_red:regression",
            "builder_red:no_source_change",
            "builder_red:target_red",
            "protocol:*",
            "review:style",
            "review:api_change",
        ),
        title="Give the builder the repository's own checks; done needs them to pass",
        expected_effect="the builder verifies and repairs inside the attempt",
        level_overrides=(("protocol:*", "mistake-proofing"),),
    ),
    Lever(
        "budget_calibrated",
        "config",
        "mistake-proofing",
        "K",
        ("budget:*",),
        title="Set the caps from the cell's clean completions (calibrated budget)",
        expected_effect="caps fit the work the cell's clean attempts needed",
    ),
    Lever(
        "line:T-NET",
        "context",
        "advisory",
        "L",
        ("protocol:network:*",),
        template_id="T-NET",
        title="Playbook: what the sandbox refuses, and to use the test command",
    ),
    Lever(
        "line:T-ARCH",
        "context",
        "advisory",
        "L",
        ("protocol:archaeology:*",),
        template_id="T-ARCH",
        title="Playbook: repository history is off limits",
    ),
    Lever(
        "line:T-FMT",
        "context",
        "advisory",
        "L",
        ("format:*",),
        template_id="T-FMT",
        title="Playbook: format the changed files before finishing",
    ),
    Lever(
        "line:T-LINT",
        "context",
        "advisory",
        "L",
        ("lint:*",),
        template_id="T-LINT",
        title="Playbook: the lint rule this repository rejects",
    ),
    Lever(
        "line:T-API",
        "context",
        "advisory",
        "L",
        ("api:*", "review:api_change"),
        template_id="T-API",
        title="Playbook: keep the public API",
    ),
    Lever(
        "line:T-CHANGE",
        "context",
        "advisory",
        "L",
        ("builder_red:no_source_change",),
        template_id="T-CHANGE",
        title="Playbook: finish only with a source change",
    ),
    Lever(
        "item:refused-call",
        "code",
        "construction",
        "product",
        ("protocol:*",),
        scope="product",
        title="Record a command the builder's own deny rule refused as a refused call, not a "
        "voided attempt (needs its own ADR and an apparatus bump)",
        expected_effect="one refused command no longer voids everything the builder did",
    ),
    Lever(
        "item:offline-deps",
        "code",
        "construction",
        "infra",
        _INSTALLERS,
        scope="infra",
        title="Provision the sandbox so dependency commands resolve without the network",
        expected_effect="the installer answers offline, so the refusal has nothing to refuse",
    ),
    Lever(
        "item:budget-handoff",
        "code",
        "construction",
        "product",
        ("budget:*",),
        scope="product",
        title="A builder near its budget runs the finish checks and stops with its best patch",
        expected_effect="a budget stop leaves a graded best patch instead of nothing",
    ),
    Lever(
        "item:belt6-on",
        "code",
        "gate",
        "operator",
        ("api:*", "review:api_change"),
        scope="operator",
        title="Switch belt 6 (api_stable) on for this repository — a grader key, a person's call",
        expected_effect="a public-API break is refused by the grade, not found in review",
    ),
    Lever(
        "item:lint-pin",
        "code",
        "mistake-proofing",
        "operator",
        ("harness:linter-unrunnable*",),
        scope="operator",
        title="Pin the repository's linter command and version in its configuration",
        expected_effect="belt 5 runs the linter the repository pins",
    ),
    Lever(
        "item:env-provision",
        "code",
        "construction",
        "infra",
        ("harness:runner-tool-missing*", "harness:env-network*"),
        scope="infra",
        title="Provision the missing tool in the repository's sandbox image",
        expected_effect="the runner finds its tools, so no attempt is spent on a missing one",
    ),
    Lever(
        "item:strengthen",
        "code",
        "gate",
        "L",
        ("review:defect", "review:regression", "factory:pr_closed"),
        scope="operator",
        title="Strengthen the target tests so the grade refuses what the review found "
        "(the strengthening report names the test.add items)",
        expected_effect="a defect a reviewer found is refused by the oracle next time",
    ),
    Lever(
        "item:prevent-class",
        "code",
        "gate",
        "product",
        ("*",),
        scope="product",
        fallback=True,
        title="Build the prevention this class needs: every lever the loop may apply was "
        "tried and the class still recurs (the evidence rows say where)",
        expected_effect="a person builds the gate or the construction the catalogue lacks",
    ),
    Lever(
        "item:credential-link",
        "code",
        "gate",
        "D",
        ("harness:no-credential",),
        scope="operator",
        title="Link the submit-time credential refusal (docs/PREVENTION.md P-003) so its "
        "exposure is measured from the link",
        expected_effect="a run with no credential is refused before any row is written",
    ),
    Lever(
        "precheck",
        "containment",
        CONTAINMENT,
        "D",
        ("harness:runner-tool-missing*",),
        title="Stream D's pre-check refuses the replay before any builder call",
    ),
    Lever(
        "escalation_rule",
        "containment",
        CONTAINMENT,
        "K",
        ("budget:*", "protocol:*"),
        title="Stream K's measured escalation rule stops retries that do not pay",
    ),
)
LEVER_BY_ID: dict[str, Lever] = {lv.lever_id: lv for lv in LEVERS}
_LEVER_INDEX: dict[str, int] = {lv.lever_id: i for i, lv in enumerate(LEVERS)}
_LEVEL_RANK: dict[str, int] = {lv: i for i, lv in enumerate(LEVELS)}


@dataclass(frozen=True)
class WritableSwitch:
    """One (section, key, value) the loop may write into its overlay — nothing else."""

    lever_id: str
    section: str
    key: str
    value: Any


#: THE allowlist (ADR-0020 §1). The merge sets the W section and keys to stream W's names.
WRITABLE: tuple[WritableSwitch, ...] = (
    WritableSwitch("format_step", W_SECTION, "format_step", True),
    WritableSwitch("finish_gate", W_SECTION, "finish_gate", True),
    WritableSwitch("budget_calibrated", K_SECTION, "budget_profile", "calibrated"),
)
WRITABLE_BY_LEVER: dict[str, WritableSwitch] = {w.lever_id: w for w in WRITABLE}
#: Keys the loop must never write — used by the tests; the guard itself is the allowlist.
FORBIDDEN_EXAMPLES: tuple[str, ...] = (
    "lint",
    "lint.disabled",
    "checks.api_stable",
    "runner",
    "runner_opts",
    "mining",
    "pool",
    "sandbox_image",
    "spend.escalation",
)


def check_writable(section: str, key: str, value: Any) -> None:
    """Refuse every (section, key, value) that is not a row of :data:`WRITABLE` — by name.
    The loop changes how a change is made, never how it is judged."""
    for w in WRITABLE:
        if (w.section, w.key) == (section, key):
            if value != w.value:
                raise NotWritable(
                    f"the loop may only set {section}.{key} = {w.value!r} (it never switches "
                    f"anything off), not {value!r}"
                )
            return
    name = f"{section}.{key}" if section else key
    raise NotWritable(
        f"{name!r} is not a key the prevention loop may write: it may only throw "
        f"{', '.join(f'{w.section}.{w.key}' for w in WRITABLE)} (ADR-0020 §1)"
    )


# ===========================================================================
# 3. Records and the chain
# ===========================================================================


def _redact_deep(v: Any) -> Any:
    if isinstance(v, str):
        return redact(v)
    if isinstance(v, Mapping):
        return {str(k): _redact_deep(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [_redact_deep(x) for x in v]
    return v


def _json_native(v: Any) -> Any:
    """Round-trip through canonical JSON so what is hashed is what a JSON column returns."""
    return json.loads(canonical_json(v))


def _rules() -> dict[str, str]:
    return {"signature": SIGNATURE_RULES, "decision": DECISION_RULE, "apparatus": APPARATUS_VERSION}


@dataclass(frozen=True)
class PreventionRecord:
    """One act of the loop (or of a person on it). Free text is redacted, and the payload
    made JSON-native, at construction — before any hash — so a store's second redaction is a
    no-op and the chain verifies after a round trip through a JSON column."""

    kind: str
    repo: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    actor: str = ""
    on_behalf_of: str = ""
    reason: str = ""
    created: str = field(default_factory=utc_now_iso)
    rules: Mapping[str, str] = field(default_factory=_rules)
    schema: str = RECORD_SCHEMA
    record_id: str = ""
    prev_hash: str = ""
    row_hash: str = ""

    def __post_init__(self) -> None:
        if self.kind not in RECORD_KINDS:
            raise ValueError(f"record kind {self.kind!r} not in {RECORD_KINDS}")
        object.__setattr__(self, "reason", redact(str(self.reason))[:1000])
        object.__setattr__(self, "payload", _json_native(_redact_deep(dict(self.payload))))
        object.__setattr__(self, "rules", {str(k): str(v) for k, v in self.rules.items()})
        if not self.record_id:
            rid = sha256_text(
                "\x1f".join((self.kind, self.repo, self.created, canonical_json(self.payload)))
            )[:16]
            object.__setattr__(self, "record_id", rid)

    def body(self) -> dict[str, Any]:
        """Every field but ``row_hash`` — what is hashed (``prev_hash`` included)."""
        return {
            "schema": self.schema,
            "kind": self.kind,
            "repo": self.repo,
            "record_id": self.record_id,
            "created": self.created,
            "actor": self.actor,
            "on_behalf_of": self.on_behalf_of,
            "reason": self.reason,
            "payload": dict(self.payload),
            "rules": dict(self.rules),
            "prev_hash": self.prev_hash,
        }

    def compute_hash(self) -> str:
        return sha256_text(canonical_json(self.body()))

    def chained(self, prev_hash: str) -> PreventionRecord:
        rec = replace(self, prev_hash=prev_hash, row_hash="")
        object.__setattr__(rec, "row_hash", rec.compute_hash())
        return rec

    def verify_hash(self) -> bool:
        return bool(self.row_hash) and self.row_hash == self.compute_hash()

    def to_dict(self) -> dict[str, Any]:
        d = self.body()
        d["row_hash"] = self.row_hash
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> PreventionRecord:
        return cls(
            kind=str(d.get("kind", "")),
            repo=str(d.get("repo", "")),
            payload=dict(d.get("payload") or {}),
            actor=str(d.get("actor", "")),
            on_behalf_of=str(d.get("on_behalf_of", "")),
            reason=str(d.get("reason", "")),
            created=str(d.get("created", "")),
            rules=dict(d.get("rules") or {}),
            schema=str(d.get("schema", RECORD_SCHEMA)),
            record_id=str(d.get("record_id", "")),
            prev_hash=str(d.get("prev_hash", "")),
            row_hash=str(d.get("row_hash", "")),
        )


def verify_records(records: Iterable[PreventionRecord]) -> int:
    """Walk the chain; the count, or :class:`LedgerIntegrityError` on any break."""
    prev = GENESIS_HASH
    n = 0
    for rec in records:
        if rec.prev_hash != prev:
            raise LedgerIntegrityError(
                f"prevention chain broken at record {n} ({rec.record_id}): prev_hash "
                f"{rec.prev_hash[:12]}… does not follow {prev[:12]}…"
            )
        if not rec.verify_hash():
            raise LedgerIntegrityError(
                f"prevention record {n} ({rec.record_id}) does not hash to its row_hash — "
                "it was edited after it was written"
            )
        prev = rec.row_hash
        n += 1
    return n


class PreventionStore(Protocol):
    """Where the chain lives: the server's events table, a JSONL file, or memory."""

    def append(self, record: PreventionRecord) -> PreventionRecord: ...

    def records(self) -> list[PreventionRecord]: ...


class MemoryPreventionStore:
    """The chain in memory (tests)."""

    def __init__(self) -> None:
        self._records: list[PreventionRecord] = []

    def append(self, record: PreventionRecord) -> PreventionRecord:
        prev = self._records[-1].row_hash if self._records else GENESIS_HASH
        rec = record.chained(prev)
        self._records.append(rec)
        return rec

    def records(self) -> list[PreventionRecord]:
        return list(self._records)


class JsonlPreventionStore:
    """The standard-library twin of the server's events store: one record per line,
    chained, appended under an OS lock and fsynced (``crb learn prevention``)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _last_hash(self) -> str:
        last = jsonl_last_line(self.path)
        if not last:
            return GENESIS_HASH
        h = str(json.loads(last).get("row_hash", ""))
        if not h:
            raise LedgerIntegrityError(f"last record in {self.path} has no row_hash")
        return h

    def append(self, record: PreventionRecord) -> PreventionRecord:
        with jsonl_append_lock(self.path):
            rec = record.chained(self._last_hash())
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec.to_dict(), sort_keys=True, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        return rec

    def records(self) -> list[PreventionRecord]:
        if not self.path.exists():
            return []
        out = [
            PreventionRecord.from_dict(json.loads(line))
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        verify_records(out)
        return out


# ===========================================================================
# 4. Folds over the chain
# ===========================================================================


@dataclass(frozen=True)
class SwitchState:
    """The repository's switch: the last ``switched`` record (``off`` when there is none)."""

    auto_apply: str = AUTO_OFF
    switched_by: str = ""
    switched_at: str = ""
    reason: str = ""
    record_id: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "auto_apply": self.auto_apply,
            "switched_by": self.switched_by,
            "switched_at": self.switched_at,
            "reason": self.reason,
            "record_id": self.record_id,
        }


def switch_state(records: Iterable[PreventionRecord]) -> SwitchState:
    state = SwitchState()
    for r in records:
        if r.kind == "switched":
            mode = str(r.payload.get("auto_apply", AUTO_OFF))
            state = SwitchState(
                mode if mode in AUTO_MODES else AUTO_OFF, r.actor, r.created, r.reason, r.record_id
            )
    return state


@dataclass(frozen=True)
class Change:
    """One applied change (or a person's link to a fix made outside the loop). ``before``
    is frozen per target signature at application; ``state`` is ``in_force``, ``retired``
    (the loop reverted it) or ``reverted`` (a person did)."""

    change_id: str
    lever_id: str
    family: str
    level: str
    targets: tuple[str, ...]
    stratum_mode: str
    key: str
    what: Mapping[str, Any]
    applied_at: str
    applied_by: str
    on_behalf_of: str
    before: Mapping[str, Mapping[str, Any]]
    state: str = "in_force"
    record_hash: str = ""
    by_label: bool = True

    @property
    def deterministic(self) -> bool:
        lv = LEVER_BY_ID.get(self.lever_id)
        return bool(lv and lv.deterministic)

    @property
    def lever_kind(self) -> str:
        return "context" if self.family == "context" else "process"

    def names(self, row: GradeRow) -> bool:
        """Does the row's own hashed label name this change? A link is named by time."""
        if not self.by_label:
            return True
        if self.family == "context":
            return str(self.what.get("line_id", "")) in _split_ids(row.labels.get(LABEL_LINES, ""))
        if self.change_id not in _split_ids(row.labels.get(LABEL_CHANGES, "")):
            return False
        return mechanism_ran(self.lever_id, row.labels)

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_id": self.change_id,
            "lever_id": self.lever_id,
            "family": self.family,
            "level": self.level,
            "targets": list(self.targets),
            "stratum_mode": self.stratum_mode,
            "key": self.key,
            "what": dict(self.what),
            "applied_at": self.applied_at,
            "applied_by": self.applied_by,
            "on_behalf_of": self.on_behalf_of,
            "before": {k: dict(v) for k, v in self.before.items()},
            "state": self.state,
            "record_hash": self.record_hash,
        }


def _split_ids(raw: str) -> list[str]:
    return [x for x in str(raw or "").split(",") if x]


def changes(records: Iterable[PreventionRecord]) -> dict[str, Change]:
    """Every change on the chain by id, in application order, with its state folded."""
    out: dict[str, Change] = {}
    for r in records:
        p = r.payload
        if r.kind == "applied":
            cid = str(p.get("change_id", ""))
            out[cid] = Change(
                change_id=cid,
                lever_id=str(p.get("lever_id", "")),
                family=str(p.get("family", "")),
                level=str(p.get("level", "")),
                targets=tuple(str(x) for x in p.get("targets", ()) or ()),
                stratum_mode=str((p.get("stratum") or {}).get("mode", "")),
                key=str(p.get("key", "")),
                what=dict(p.get("what") or {}),
                applied_at=r.created,
                applied_by=r.actor,
                on_behalf_of=r.on_behalf_of,
                before={str(k): dict(v) for k, v in (p.get("before") or {}).items()},
                record_hash=r.row_hash,
            )
        elif r.kind == "linked":
            cid = r.record_id
            out[cid] = Change(
                change_id=cid,
                lever_id="link",
                family="code",
                level="construction",
                targets=tuple(str(x) for x in p.get("targets", ()) or ()),
                stratum_mode=str((p.get("stratum") or {}).get("mode", "")),
                key=str(p.get("key", "")),
                what={
                    "ref": p.get("ref", ""),
                    "note": p.get("note", ""),
                    "served_commit": p.get("served_commit", ""),
                },
                applied_at=r.created,
                applied_by=r.actor,
                on_behalf_of=r.on_behalf_of,
                before={str(k): dict(v) for k, v in (p.get("before") or {}).items()},
                record_hash=r.row_hash,
                by_label=False,
            )
        elif r.kind == "reverted":
            cid = str(p.get("change_id", ""))
            if cid in out and out[cid].state == "in_force":
                state = "retired" if str(p.get("by", "")) == "loop" else "reverted"
                out[cid] = replace(out[cid], state=state)
    return out


def vetoes(records: Iterable[PreventionRecord]) -> frozenset[tuple[str, str]]:
    """``(signature, lever_id)`` a PERSON reverted — never re-applied by the loop."""
    recs = list(records)
    chs = changes(recs)
    out: set[tuple[str, str]] = set()
    for r in recs:
        if r.kind == "reverted" and bool(r.payload.get("veto")):
            ch = chs.get(str(r.payload.get("change_id", "")))
            if ch is not None:
                out |= {(sig, ch.lever_id) for sig in ch.targets}
    return frozenset(out)


def retired_levers(records: Iterable[PreventionRecord]) -> frozenset[tuple[str, str, str]]:
    """``(signature, lever_id, apparatus)`` the loop retired by measurement (retire or harm)."""
    recs = list(records)
    chs = changes(recs)
    out: set[tuple[str, str, str]] = set()
    for r in recs:
        if r.kind == "decided" and str(r.payload.get("verdict", "")) in ("retire", "harm"):
            ch = chs.get(str(r.payload.get("change_id", "")))
            if ch is not None:
                out.add(
                    (
                        str(r.payload.get("signature", "")),
                        ch.lever_id,
                        str(r.payload.get("apparatus", key_apparatus(ch.key))),
                    )
                )
    return frozenset(out)


@dataclass(frozen=True)
class Proposal:
    """A filed item: the class, the lever, its level and scope, what it is expected to do,
    the evidence — and, once an operator registered it, where it went."""

    item_id: str
    targets: tuple[str, ...]
    lever_id: str
    level: str
    scope: str
    kind: str
    title: str
    description: str
    expected_effect: str
    evidence_refs: tuple[str, ...]
    evidence_total: int
    proposed_at: str
    record_hash: str
    registered: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "targets": list(self.targets),
            "lever_id": self.lever_id,
            "level": self.level,
            "scope": self.scope,
            "kind": self.kind,
            "title": self.title,
            "description": self.description,
            "expected_effect": self.expected_effect,
            "evidence_refs": list(self.evidence_refs),
            "evidence_total": self.evidence_total,
            "proposed_at": self.proposed_at,
            "record_hash": self.record_hash,
            "registered": dict(self.registered) if self.registered else None,
        }


def proposals(records: Iterable[PreventionRecord]) -> dict[str, Proposal]:
    out: dict[str, Proposal] = {}
    for r in records:
        p = r.payload
        if r.kind == "proposed":
            iid = str(p.get("item_id", ""))
            out[iid] = Proposal(
                item_id=iid,
                targets=tuple(str(x) for x in p.get("targets", ()) or ()),
                lever_id=str(p.get("lever_id", "")),
                level=str(p.get("level", "")),
                scope=str(p.get("scope", "")),
                kind=str(p.get("kind", "")),
                title=str(p.get("title", "")),
                description=str(p.get("description", "")),
                expected_effect=str(p.get("expected_effect", "")),
                evidence_refs=tuple(str(x) for x in p.get("evidence_refs", ()) or ()),
                evidence_total=int(p.get("evidence_total", 0) or 0),
                proposed_at=r.created,
                record_hash=r.row_hash,
            )
        elif r.kind == "registered":
            iid = str(p.get("item_id", ""))
            if iid in out:
                out[iid] = replace(out[iid], registered={**dict(p), "by": r.actor, "at": r.created})
    return out


@dataclass(frozen=True)
class Link:
    """A person's link from classes to a fix made outside the loop (a merged PR, D's P-003)."""

    record_id: str
    targets: tuple[str, ...]
    ref: str
    note: str
    served_commit: str
    linked_at: str
    actor: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "targets": list(self.targets),
            "ref": self.ref,
            "note": self.note,
            "served_commit": self.served_commit,
            "linked_at": self.linked_at,
            "actor": self.actor,
        }


def links(records: Iterable[PreventionRecord]) -> list[Link]:
    return [
        Link(
            r.record_id,
            tuple(str(x) for x in r.payload.get("targets", ()) or ()),
            str(r.payload.get("ref", "")),
            str(r.payload.get("note", "")),
            str(r.payload.get("served_commit", "")),
            r.created,
            r.actor,
        )
        for r in records
        if r.kind == "linked"
    ]


def decisions_for(
    records: Iterable[PreventionRecord], change_id: str, signature: str
) -> list[Mapping[str, Any]]:
    """The ``decided`` payloads of one (change, class), oldest first."""
    return [
        r.payload
        for r in records
        if r.kind == "decided"
        and str(r.payload.get("change_id", "")) == change_id
        and str(r.payload.get("signature", "")) == signature
    ]


#: A switch's own row label, and the value that says the mechanism ran: a row whose label
#: says otherwise ran under something else (a run's own parameter won) and was never exposed
#: (docs/PREVENTION.md P-021).
_MECHANISM_LABELS: dict[str, tuple[str, str]] = {
    "budget_calibrated": ("budget_profile", "calibrated"),
    "format_step": ("checks", "fmt=1"),
    "finish_gate": ("checks", "gate=1"),
}


def mechanism_ran(lever_id: str, labels: Mapping[str, str]) -> bool:
    """Did the row run under the switch's mechanism? ``True`` when the row carries no label
    for it (a row written before the label existed); otherwise its own label decides."""
    spec = _MECHANISM_LABELS.get(lever_id)
    if spec is None:
        return True
    label, want = spec
    got = labels.get(label)
    if got is None:
        return True
    if label == "checks":  # ``fmt=1:repo;gate=0:default;api=1:run;cfg=<version>``
        return want in {part.split(":", 1)[0] for part in str(got).split(";")}
    return str(got) == want


def _switch_allows(switch: str, family: str) -> bool:
    if family == "context":
        return switch in (AUTO_CONTEXT, AUTO_CONFIG)
    if family == "config":
        return switch == AUTO_CONFIG
    return False


def _base_value(base_config: Mapping[str, Mapping[str, Any]] | None, section: str, key: str) -> Any:
    sec = (base_config or {}).get(section)
    if isinstance(sec, Mapping) and key in sec:
        return sec[key]
    return _MISSING


_MISSING = object()


def overridden(change: Change, *sources: Mapping[str, Mapping[str, Any]] | None) -> bool:
    """Has the team (or the run) set the key this change's switch writes? Then theirs wins."""
    w = WRITABLE_BY_LEVER.get(change.lever_id)
    if w is None:
        return False
    return any(_base_value(src, w.section, w.key) is not _MISSING for src in sources)


def run_overrides(run_params: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """A run's own settings as section → key → value: its mapping sections (``checks``) and
    every top-level parameter a switch writes (``budget_profile``, a plain value on
    ``POST /runs``). Either is the run's own choice, so it outranks the loop's switch."""
    p = run_params or {}
    out: dict[str, dict[str, Any]] = {k: dict(v) for k, v in p.items() if isinstance(v, Mapping)}
    for w in WRITABLE:
        v = p.get(w.key)
        if v is not None and not isinstance(v, Mapping):
            out.setdefault(w.section, {})[w.key] = v
    return out


def in_force(
    chs: Iterable[Change] | Mapping[str, Change],
    *,
    switch: str,
    base_config: Mapping[str, Mapping[str, Any]] | None = None,
    run_params: Mapping[str, Any] | None = None,
) -> tuple[Change, ...]:
    """The changes a run is given: ``off`` → none; ``context`` → lines; ``config`` → lines
    and switches, less any switch whose key the team's configuration or the run sets."""
    items = list(chs.values()) if isinstance(chs, Mapping) else list(chs)
    run_sections = run_overrides(run_params)
    out: list[Change] = []
    for ch in items:
        if ch.state != "in_force" or ch.family not in ("context", "config"):
            continue
        if not _switch_allows(switch, ch.family):
            continue
        if ch.family == "config" and overridden(ch, base_config, run_sections):
            continue
        out.append(ch)
    return tuple(out)


def overlay_of(chs: Iterable[Change]) -> dict[str, dict[str, Any]]:
    """The loop's overlay: section → key → value, from the config changes given."""
    out: dict[str, dict[str, Any]] = {}
    for ch in chs:
        w = WRITABLE_BY_LEVER.get(ch.lever_id)
        if ch.family != "config" or w is None:
            continue
        check_writable(w.section, w.key, w.value)
        out.setdefault(w.section, {})[w.key] = w.value
    return out


def _digest(parts: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


# ===========================================================================
# 5. Statistics and the rule (crb.prevention.rule.v1)
# ===========================================================================


def binom_cdf(k: int, n: int, p: float) -> float:
    """``P(X ≤ k)`` for ``X ~ Binomial(n, p)`` (exact, ``math.comb``)."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    return min(1.0, sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k + 1)))


def binom_sf(k: int, n: int, p: float) -> float:
    """``P(X ≥ k)`` (summed directly, so a tiny tail keeps its precision)."""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    return min(1.0, sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1)))


def decisive_n(p0: float, *, deterministic: bool = False) -> int:
    """``ceil(ln 0.025 / ln(1 − p0))`` clamped to 10–200 — the smallest n at which zero
    recurrences keep at the level each look tests; a lever whose effect the row records
    needs 3. Nudged up past any float rounding so zero at the first look always keeps."""
    if deterministic:
        return DETERMINISTIC_N
    if p0 <= 0:
        return DECISIVE_MAX
    if p0 >= 0.99:
        return DECISIVE_MIN
    n = math.ceil(math.log(ALPHA_LOOK) / math.log(1 - p0))
    while (1 - p0) ** n > ALPHA_LOOK and n < DECISIVE_MAX:
        n += 1
    return max(DECISIVE_MIN, min(DECISIVE_MAX, n))


def keep_bar(p0: float, n: int) -> int:
    """The most recurrences in the first ``n`` exposed attempts that still keep (``-1``: none)."""
    k = -1
    while k + 1 <= n and binom_cdf(k + 1, n, p0) <= ALPHA_LOOK:
        k += 1
    return k


def _ts(s: str) -> _dt.datetime:
    try:
        d = _dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return _dt.datetime.min.replace(tzinfo=_dt.UTC)
    return d if d.tzinfo else d.replace(tzinfo=_dt.UTC)


@dataclass(frozen=True)
class Measurement:
    """One (change, class) measured: the frozen before window, the exposed first attempts in
    order (and which recurred), what was shown but not counted, and the bar."""

    signature: str
    stratum_mode: str
    key: str
    before_k: int
    before_n: int
    before_digest: str
    p0: float
    decisive_n: int
    deterministic: bool
    flags: tuple[bool, ...]
    clean_flags: tuple[bool, ...]
    nonclean_flags: tuple[bool, ...]
    exposed_refs: tuple[str, ...]
    exposed_primary: tuple[str, ...]
    unexposed_n: int
    concurrent_k: int
    concurrent_n: int
    key_moved: int
    outage_share_before: float
    outage_k_after: int
    outage_n_after: int
    clean_before: float
    nonclean_before: float
    #: the before window's non-clean rate less the target's own rows — the displacement bar
    nontarget_before: float = 0.0
    #: comparable first attempts after the change that it never reached (an opt-out or a
    #: team override) on tasks no exposed attempt ran, and how many of them recurred
    withheld_k: int = 0
    withheld_n: int = 0

    @property
    def exposed_n(self) -> int:
        return len(self.flags)

    @property
    def exposed_k(self) -> int:
        return sum(self.flags)

    @property
    def closing_window(self) -> int:
        return max(CLOSE_MIN, self.decisive_n)

    @property
    def closing_zero_run(self) -> int:
        """Exposed attempts since the last recurrence."""
        run = 0
        for f in reversed(self.flags):
            if f:
                break
            run += 1
        return run

    @property
    def bar(self) -> str:
        if self.deterministic:
            return (
                f"keep at 0 of the first {self.decisive_n} exposed first attempts (the row "
                "records the lever's effect)"
            )
        k = keep_bar(self.p0, self.decisive_n)
        return (
            f"keep if P(X ≤ k | n = {self.decisive_n}, p0 = {self.p0:.3f}) ≤ {ALPHA_LOOK} — at "
            f"most {max(k, 0)} recurrence(s) in the first {self.decisive_n}; a second look at "
            f"{2 * self.decisive_n}"
        )

    def to_dict(self) -> dict[str, Any]:
        clean_ci = wilson_interval(sum(self.clean_flags), len(self.clean_flags))
        return {
            "signature": self.signature,
            "stratum_mode": self.stratum_mode,
            "key": self.key,
            "before": {
                "k": self.before_k,
                "n": self.before_n,
                "p0": round(self.p0, 4),
                "digest": self.before_digest,
                "clean_rate": round(self.clean_before, 4),
            },
            "exposed": {
                "k": self.exposed_k,
                "n": self.exposed_n,
                "clean_k": sum(self.clean_flags),
                "clean_ci_low": round(clean_ci.low, 4),
                "clean_ci_high": round(clean_ci.high, 4),
            },
            "unexposed_n": self.unexposed_n,
            "concurrent": {"k": self.concurrent_k, "n": self.concurrent_n},
            "withheld": {"k": self.withheld_k, "n": self.withheld_n},
            "not_comparable": self.key_moved,
            "decisive_n": self.decisive_n,
            "looks": [self.decisive_n, 2 * self.decisive_n],
            "closing_window": self.closing_window,
            "closing_zero_run": self.closing_zero_run,
            "bar": self.bar,
            "deterministic": self.deterministic,
        }


SigsFn = Callable[[GradeRow], tuple[str, ...]]


def _family(signature: str) -> str:
    return signature.split(":", 1)[0]


def before_window(
    rows: Sequence[GradeRow],
    signature: str,
    *,
    mode: str,
    key: str,
    at: str,
    sigs: SigsFn | None = None,
    reviewed: frozenset[str] = frozenset(),
    deterministic: bool = False,
) -> dict[str, Any]:
    """The frozen before window of one class: the stratum's last :data:`BEFORE_MAX`
    comparable, observable first attempts at or before ``at``. Rows arrive in ledger order."""
    sigs = sigs or signatures
    fam = _family(signature)
    cut = _ts(at)
    span = [
        r for r in rows if r.mode == mode and is_first_attempt(r.trial) and _ts(r.created) <= cut
    ]
    comparable = [
        r
        for r in span
        if r.failure_kind != FAILURE_OUTAGE
        and comparability_key(r) == key
        and observable(r, fam, reviewed=r.row_hash in reviewed)
    ]
    window = comparable[-BEFORE_MAX:]
    k0 = sum(1 for r in window if signature in sigs(r))
    n0 = len(window)
    clean_k = sum(1 for r in window if r.clean)
    other_k = sum(1 for r in window if not r.clean and signature not in sigs(r))
    first = window[0].created if window else ""
    in_span = [r for r in span if (not first or _ts(r.created) >= _ts(first))]
    outage = sum(1 for r in in_span if r.failure_kind == FAILURE_OUTAGE)
    p0 = k0 / n0 if n0 else 0.0
    return {
        "k0": k0,
        "n0": n0,
        "digest": _digest(r.row_hash for r in window),
        "first_ref": window[0].row_hash if window else "",
        "last_ref": window[-1].row_hash if window else "",
        "clean_k": clean_k,
        "clean_n": n0,
        "nonclean_k": n0 - clean_k,
        "nonclean_other_k": other_k,
        "outage_k": outage,
        "outage_n": len(in_span),
        "decisive_n": decisive_n(p0, deterministic=deterministic),
    }


def measure(
    change: Change,
    signature: str,
    rows: Sequence[GradeRow],
    *,
    key: str | None = None,
    stratum_mode: str | None = None,
    sigs: SigsFn | None = None,
    reviewed: frozenset[str] = frozenset(),
) -> Measurement:
    """Measure one class under one change: exposure is the stratum's first attempts after
    the change whose OWN labels name it (a link: every comparable first attempt after the
    link). The before window is the one frozen in the change — later rows never move it."""
    sigs = sigs or signatures
    key = key if key is not None else change.key
    mode = stratum_mode if stratum_mode is not None else change.stratum_mode
    fam = _family(signature)
    b = change.before.get(signature, {})
    k0, n0 = int(b.get("k0", 0) or 0), int(b.get("n0", 0) or 0)
    p0 = k0 / n0 if n0 else 0.0
    det = change.deterministic
    dn = int(b.get("decisive_n", 0) or 0) or decisive_n(p0, deterministic=det)
    applied = _ts(change.applied_at)
    flags: list[bool] = []
    clean_flags: list[bool] = []
    nonclean: list[bool] = []
    refs: list[str] = []
    prim: list[str] = []
    unexposed = conc_k = conc_n = moved = out_k = out_n = 0
    not_reached: list[tuple[str, bool]] = []
    exposed_tasks: set[str] = set()
    for r in rows:
        if r.mode != mode or not is_first_attempt(r.trial) or _ts(r.created) <= applied:
            continue
        named = change.names(r)
        if named:
            out_n += 1
        if r.failure_kind == FAILURE_OUTAGE:
            out_k += int(named)
            continue
        if not observable(r, fam, reviewed=r.row_hash in reviewed):
            continue
        comparable = comparability_key(r) == key
        s = sigs(r)
        if named:
            if not comparable:
                # the builder, the model or the apparatus moved under the change: shown,
                # never pooled, and the window reads inconclusive (a link never crosses it)
                moved += 1
                continue
            flags.append(signature in s)
            clean_flags.append(r.clean)
            nonclean.append(not r.clean)
            refs.append(r.row_hash)
            prim.append(s[0] if s else "")
            exposed_tasks.add(r.task_id)
        elif comparable:
            not_reached.append((r.task_id, signature in s))
            # a row from a run that opted out (or ran with the switch off) is the
            # concurrent comparison — for reading, never for deciding
            if r.labels.get(LABEL_LEARN, AUTO_OFF) == AUTO_OFF:
                conc_n += 1
                conc_k += int(signature in s)
            else:
                unexposed += 1
    clean_before = (int(b.get("clean_k", 0) or 0) / n0) if n0 else 0.0
    nonclean_before = (int(b.get("nonclean_k", 0) or 0) / n0) if n0 else 0.0
    if "nonclean_other_k" in b:
        nontarget_before = (int(b.get("nonclean_other_k", 0) or 0) / n0) if n0 else 0.0
    else:  # a change applied before the field existed: its target rows were all non-clean
        nontarget_before = max(0.0, nonclean_before - p0)
    withheld = [hit for task_id, hit in not_reached if task_id not in exposed_tasks]
    outage_before = (
        int(b.get("outage_k", 0) or 0) / int(b.get("outage_n", 0) or 1)
        if b.get("outage_n")
        else 0.0
    )
    return Measurement(
        signature=signature,
        stratum_mode=mode,
        key=key,
        before_k=k0,
        before_n=n0,
        before_digest=str(b.get("digest", "")),
        p0=p0,
        decisive_n=dn,
        deterministic=det,
        flags=tuple(flags),
        clean_flags=tuple(clean_flags),
        nonclean_flags=tuple(nonclean),
        exposed_refs=tuple(refs),
        exposed_primary=tuple(prim),
        unexposed_n=unexposed,
        concurrent_k=conc_k,
        concurrent_n=conc_n,
        key_moved=moved,
        outage_share_before=outage_before,
        outage_k_after=out_k,
        outage_n_after=out_n,
        clean_before=clean_before,
        nonclean_before=nonclean_before,
        nontarget_before=nontarget_before,
        withheld_k=sum(withheld),
        withheld_n=len(withheld),
    )


def _stats(m: Measurement, n: int) -> dict[str, Any]:
    k1 = sum(m.flags[:n])
    clean_k1 = sum(m.clean_flags[:n])
    return {
        "k1": k1,
        "n1": n,
        "p0": round(m.p0, 6),
        "p_keep": round(binom_cdf(k1, n, m.p0), 6),
        "p_harm": round(binom_sf(k1, n, m.p0), 6),
        "clean_k1": clean_k1,
        "bar": m.bar,
        "decisive_n": m.decisive_n,
        "exposed_digest": _digest(m.exposed_refs[:n]),
    }


def _harmful(m: Measurement, n: int) -> bool:
    k1 = sum(m.flags[:n])
    if m.p0 > 0 and binom_sf(k1, n, m.p0) <= ALPHA_HARM:
        return True
    upper = wilson_interval(sum(m.clean_flags[:n]), n).high
    return upper < m.clean_before


def _kept_at(m: Measurement, n: int) -> bool:
    k1 = sum(m.flags[:n])
    if m.deterministic:
        return k1 == 0
    return binom_cdf(k1, n, m.p0) <= ALPHA_LOOK


def _inconclusive(m: Measurement) -> str:
    if m.key_moved > 0:
        return "the comparability key moved inside the window (a new apparatus, builder or model)"
    if m.outage_n_after >= HARM_AT:
        after = m.outage_k_after / m.outage_n_after
        if after > OUTAGE_SPIKE * max(m.outage_share_before, OUTAGE_FLOOR):
            return f"the outage share more than doubled ({m.outage_share_before:.2f} → {after:.2f})"
    return ""


def _withheld(m: Measurement) -> str:
    """Why a keep or a close must wait: the class still recurs, at or above its before rate,
    on tasks the change never reached (runs opted out, or a team override) — so running the
    loop only where the class does not live can never close it (ADR-0020 §6.11;
    docs/PREVENTION.md P-020). An honest A/B runs the same tasks in both arms, so its control
    arm is never withheld."""
    if m.withheld_n < HARM_AT or not m.withheld_k:
        return ""
    rate = m.withheld_k / m.withheld_n
    if rate < m.p0:
        return ""
    return (
        f"the class recurs on {m.withheld_k} of {m.withheld_n} first attempts on tasks the "
        f"change never reached ({rate:.2f} ≥ p0 {m.p0:.2f})"
    )


def _successor(m: Measurement, start: int) -> str:
    counts: dict[str, int] = {}
    for p in m.exposed_primary[start:]:
        if p and p != m.signature:
            counts[p] = counts.get(p, 0) + 1
    if not counts:
        return ""
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def due_decisions(
    change: Change,
    signature: str,
    m: Measurement,
    done: Sequence[Mapping[str, Any]],
    *,
    capability: bool = False,
) -> list[dict[str, Any]]:
    """The ``decided`` payloads due now for one (change, class), in order — each look at
    most once. Nothing for a capability class (measured, never decided), nothing after a
    retirement or an inconclusive verdict."""
    base = {
        "change_id": change.change_id,
        "signature": signature,
        "apparatus": key_apparatus(change.key),
    }
    if capability or change.state != "in_force":
        return []
    verdicts = [str(d.get("verdict", "")) for d in done]
    looks = {str(d.get("look", "")) for d in done}
    if any(v in ("retire", "harm", "inconclusive") for v in verdicts):
        return []
    out: list[dict[str, Any]] = []
    why = _inconclusive(m)
    if why:
        return [
            {
                **base,
                **_stats(m, m.exposed_n),
                "look": "inconclusive",
                "verdict": "inconclusive",
                "why": why,
            }
        ]
    kept = "keep" in verdicts
    n1 = m.exposed_n
    dn = m.decisive_n
    if not kept:
        if n1 >= HARM_AT and "harm" not in looks and _harmful(m, HARM_AT):
            return [{**base, **_stats(m, HARM_AT), "look": "harm", "verdict": "harm"}]
        if n1 >= dn and "1" not in looks:
            if _harmful(m, dn):
                return [{**base, **_stats(m, dn), "look": "1", "verdict": "harm"}]
            verdict = "keep" if _kept_at(m, dn) else "continue"
            if verdict == "keep" and _withheld(m):
                return out
            out.append({**base, **_stats(m, dn), "look": "1", "verdict": verdict})
            kept = verdict == "keep"
        if not kept and n1 >= 2 * dn and "2" not in looks:
            if _harmful(m, 2 * dn):
                out.append({**base, **_stats(m, 2 * dn), "look": "2", "verdict": "harm"})
                return out
            verdict = "keep" if _kept_at(m, 2 * dn) else "retire"
            if verdict == "keep" and _withheld(m):
                return out
            out.append({**base, **_stats(m, 2 * dn), "look": "2", "verdict": verdict})
            kept = verdict == "keep"
            if not kept:
                return out
    if not kept:
        return out
    # --- after a keep: closed, displaced, reopened -----------------------------------------
    events = [d for d in done if str(d.get("verdict", "")) in ("closed", "reopened", "displaced")]
    events += [d for d in out if str(d.get("verdict", "")) in ("closed", "reopened", "displaced")]
    last_state = ""
    last_n = 0
    for d in events:
        if str(d.get("verdict")) in ("closed", "reopened"):
            last_state = str(d.get("verdict"))
            last_n = int(d.get("n1", 0) or 0)
    if last_state == "closed":
        later = [i for i, f in enumerate(m.flags) if f and i >= last_n]
        if later:
            first = later[0]
            out.append(
                {
                    **base,
                    **_stats(m, first + 1),
                    "look": "reopen",
                    "verdict": "reopened",
                    "row": m.exposed_refs[first],
                }
            )
        return out
    if _withheld(m):
        return out
    window = m.closing_window
    if n1 >= window and n1 > last_n and not any(m.flags[n1 - window : n1]):
        after_rate = sum(m.nonclean_flags[n1 - window : n1]) / window
        # the bar is the before window's NON-TARGET failure rate: the target's own share
        # must leave the non-clean rate, or the same attempts only fail as something else
        # (ADR-0020 §6.10; docs/PREVENTION.md P-019)
        if after_rate <= m.nontarget_before + DISPLACEMENT:
            out.append(
                {**base, **_stats(m, n1), "look": "close", "verdict": "closed", "window": window}
            )
        else:
            already = any(
                str(d.get("verdict")) == "displaced" and int(d.get("n1", 0) or 0) >= last_n
                for d in events
            )
            if not already:
                out.append(
                    {
                        **base,
                        **_stats(m, n1),
                        "look": "close",
                        "verdict": "displaced",
                        "window": window,
                        "successor": _successor(m, n1 - window),
                        "nonclean_after": round(after_rate, 4),
                        "nonclean_before": round(m.nonclean_before, 4),
                    }
                )
    return out


def decision_state(done: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The fold of one (change, class)'s decisions: kept / closed / reopened / displaced /
    retired / inconclusive, and the successor a displacement named."""
    st: dict[str, Any] = {
        "kept": False,
        "closed": False,
        "reopened": False,
        "displaced": False,
        "retired": False,
        "inconclusive": False,
        "successor": "",
        "looks": [],
    }
    for d in done:
        v = str(d.get("verdict", ""))
        st["looks"].append(str(d.get("look", "")))
        if v == "keep":
            st["kept"] = True
        elif v in ("retire", "harm"):
            st["retired"] = True
        elif v == "inconclusive":
            st["inconclusive"] = True
        elif v == "closed":
            st["closed"], st["reopened"], st["displaced"] = True, False, False
        elif v == "reopened":
            st["closed"], st["reopened"] = False, True
        elif v == "displaced":
            st["displaced"] = True
            st["successor"] = str(d.get("successor", ""))
    return st


# ===========================================================================
# 6. Choosing a lever
# ===========================================================================


@dataclass(frozen=True)
class Mechanisms:
    """THE merge seam for streams W and K: which process mechanisms this build ships, which
    are on by default, whether a budget cell can be calibrated, and the repository's own
    check commands. The empty default ships nothing; the server binds what this build ships
    (``crb.server.prevention_state.mechanisms``)."""

    shipped: frozenset[str] = frozenset()
    calibratable: Callable[[str, str], tuple[bool, str]] | None = None
    commands: Mapping[str, str] = field(default_factory=dict)
    on_by_default: frozenset[str] = frozenset()


@dataclass(frozen=True)
class LeverChoice:
    """The lever the loop would apply (``allowed`` says whether the switch lets it now), the
    levers it passed over and why, and the code items it would propose."""

    lever_id: str
    level: str
    family: str
    why: str
    passed_over: tuple[tuple[str, str, str], ...] = ()
    allowed: bool = False
    propose: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "lever_id": self.lever_id,
            "level": self.level,
            "family": self.family,
            "why": self.why,
            "allowed": self.allowed,
            "passed_over": [
                {"lever_id": a, "level": b, "why_not": c} for a, b, c in self.passed_over
            ],
            "propose": list(self.propose),
        }


def _ordered(signature: str) -> list[Lever]:
    admitted = [
        lv
        for lv in LEVERS
        if lv.family != "containment" and not lv.fallback and lv.admits_sig(signature)
    ]
    return sorted(
        admitted, key=lambda lv: (_LEVEL_RANK[lv.level_for(signature)], _LEVER_INDEX[lv.lever_id])
    )


def choose_lever(
    signature: str,
    *,
    apparatus: str = "",
    mechanisms: Mechanisms | None = None,
    switch: str = AUTO_OFF,
    vetoes: frozenset[tuple[str, str]] = frozenset(),
    retired: frozenset[tuple[str, str, str]] = frozenset(),
    base_config: Mapping[str, Mapping[str, Any]] | None = None,
    tried: frozenset[str] = frozenset(),
    proposed: frozenset[str] = frozenset(),
    size: str = "",
    mode: str = "",
    escalate: bool = False,
) -> LeverChoice:
    """Walk the catalogue from strongest to weakest (ADR-0020 §5) and return the lever the
    loop would apply, with every lever passed over and why; propose the strongest code items
    when a code lever is the strongest the class admits, or when nothing the loop may apply
    is left (escalation). ``proposed`` holds lever ids already filed for this class."""
    mech = mechanisms or Mechanisms()
    ordered = _ordered(signature)
    passed: list[tuple[str, str, str]] = []
    best: Lever | None = None
    best_allowed: Lever | None = None
    # a switch that failed escalates to the filed item, never down to a checklist line
    # (ADR-0020 §9; docs/PREVENTION.md P-023)
    config_retired = any(
        (signature, lv.lever_id, apparatus) in retired for lv in ordered if lv.family == "config"
    )
    for lv in ordered:
        level = lv.level_for(signature)
        if lv.family == "code":
            passed.append((lv.lever_id, level, "a filed item: code a person builds"))
            continue
        why_not = ""
        if lv.family == "context" and config_retired:
            why_not = "a process switch for this class was retired: escalate to the filed item"
        elif (signature, lv.lever_id) in vetoes:
            why_not = "a person reverted it for this class"
        elif (signature, lv.lever_id, apparatus) in retired:
            why_not = f"retired for this class under apparatus {apparatus}"
        elif lv.family == "config":
            w = WRITABLE_BY_LEVER[lv.lever_id]
            base = _base_value(base_config, w.section, w.key)
            if lv.lever_id not in mech.shipped:
                why_not = "this build does not ship it yet"
            elif lv.lever_id in mech.on_by_default or base == w.value:
                why_not = "already on for the repository"
            elif base is not _MISSING:
                why_not = f"the team set {w.section}.{w.key} itself"
            elif lv.lever_id in tried:
                why_not = "in force, and the class recurred under it"
            elif lv.lever_id == "budget_calibrated" and mech.calibratable is not None:
                ok, reason = mech.calibratable(mode, size)
                if not ok:
                    why_not = f"cannot calibrate: {reason}"
        elif lv.family == "context" and not has_template(signature):
            why_not = "no template may serve this class"
        if why_not:
            passed.append((lv.lever_id, level, why_not))
            continue
        if best is None:
            best = lv
        if _switch_allows(switch, lv.family):
            best_allowed = lv
            break
        passed.append((lv.lever_id, level, f"the switch is {switch}"))
    chosen = best_allowed or best
    code = [lv for lv in ordered if lv.family == "code" and (signature, lv.lever_id) not in vetoes]
    if (
        not code
        and (best is None or escalate)
        and signature not in CAPABILITY_CLASSES
        and _family(signature) != "factory"
    ):
        # no specific item admits the class and nothing the loop may apply is left (or the
        # change in force was reopened): the ladder still ends in a filed item
        code = [
            lv
            for lv in LEVERS
            if lv.fallback and lv.admits_sig(signature) and (signature, lv.lever_id) not in vetoes
        ]
    propose: tuple[str, ...] = ()
    if code:
        strongest_is_code = bool(ordered) and ordered[0].family == "code"
        if strongest_is_code or best_allowed is None or escalate:
            top = min(_LEVEL_RANK[lv.level_for(signature)] for lv in code)
            propose = tuple(
                lv.lever_id
                for lv in code
                if _LEVEL_RANK[lv.level_for(signature)] == top and lv.lever_id not in proposed
            )
            if not propose and (best_allowed is None or escalate):
                # the strongest were filed already: file the next level down
                rest = [lv for lv in code if lv.lever_id not in proposed]
                if rest:
                    nxt = min(_LEVEL_RANK[lv.level_for(signature)] for lv in rest)
                    propose = tuple(
                        lv.lever_id for lv in rest if _LEVEL_RANK[lv.level_for(signature)] == nxt
                    )
    if chosen is None:
        why = (
            "no lever the loop may apply admits this class"
            if not code
            else "only a filed item admits this class"
        )
        return LeverChoice("", "", "", why, tuple(passed), False, propose)
    level = chosen.level_for(signature)
    why = (
        f"the strongest admissible lever ({level})"
        if best_allowed is chosen
        else f"the strongest admissible lever ({level}); the switch is {switch}"
    )
    return LeverChoice(
        chosen.lever_id, level, chosen.family, why, tuple(passed), best_allowed is chosen, propose
    )


# ===========================================================================
# 7. The register
# ===========================================================================


@dataclass(frozen=True)
class RegisterEntry:
    """One class of one repository (ADR-0020 §3)."""

    repo: str
    signature: str
    family: str
    sub: str
    detail: str
    first_seen: str
    first_ref: str
    last_seen: str
    occurrences: int
    first_attempts: int
    blocked: int
    tasks: int
    runs: int
    cost_usd: float
    refs: tuple[str, ...]
    refs_total: int
    by_mode: Mapping[str, int]
    by_apparatus: Mapping[str, int]
    not_comparable: int
    stratum_mode: str
    key: str
    stratum_n: int
    stratum_k: int
    stratum_tasks: int
    actionable: bool
    why_not: str
    recommendation: LeverChoice
    change: Change | None
    proposals: tuple[Proposal, ...]
    measurement: Measurement | None
    status: str
    qualifiers: tuple[str, ...]
    lever_kind: str
    next: str
    history: tuple[Mapping[str, Any], ...]
    task_ids: tuple[str, ...] = ()
    dominant_size: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "signature": self.signature,
            "family": self.family,
            "sub": self.sub,
            "detail": self.detail,
            "first_seen": self.first_seen,
            "first_ref": self.first_ref,
            "last_seen": self.last_seen,
            "occurrences": self.occurrences,
            "first_attempts": self.first_attempts,
            "blocked": self.blocked,
            "tasks": self.tasks,
            "runs": self.runs,
            "cost_usd": round(self.cost_usd, 4),
            "refs": list(self.refs),
            "refs_total": self.refs_total,
            "by_mode": dict(self.by_mode),
            "by_apparatus": dict(self.by_apparatus),
            "not_comparable": self.not_comparable,
            "stratum": {
                "mode": self.stratum_mode,
                "key": self.key,
                "n": self.stratum_n,
                "k": self.stratum_k,
                "tasks": self.stratum_tasks,
            },
            "actionable": self.actionable,
            "why_not": self.why_not,
            "capability": self.signature in CAPABILITY_CLASSES,
            "recommendation": self.recommendation.to_dict(),
            "change": self.change.to_dict() if self.change else None,
            "proposals": [p.to_dict() for p in self.proposals],
            "measurement": self.measurement.to_dict() if self.measurement else None,
            "status": self.status,
            "qualifiers": list(self.qualifiers),
            "lever_kind": self.lever_kind,
            "next": self.next,
            "history": [dict(h) for h in self.history],
        }


@dataclass(frozen=True)
class _Index:
    """The rows of one repository in ledger order with their signatures (not served)."""

    rows: tuple[GradeRow, ...]
    sigs: Mapping[str, tuple[str, ...]]
    reviewed: frozenset[str]

    def of(self, row: GradeRow) -> tuple[str, ...]:
        return self.sigs.get(row.row_hash or row.row_id, ())


@dataclass(frozen=True)
class Register:
    """The register of one repository. ``to_dict`` is the served shape."""

    schema: str
    repo: str
    rules: Mapping[str, str]
    apparatus: str
    switch: SwitchState
    attempts: Mapping[str, int]
    counts: Mapping[str, int]
    share_closed: float | None
    share_closed_by_process: float | None
    overlay: Mapping[str, Mapping[str, Any]]
    playbook: tuple[PlaybookLine, ...]
    entries: tuple[RegisterEntry, ...]
    proposals: tuple[Proposal, ...]
    links: tuple[Link, ...]
    chain: Mapping[str, Any]
    index: _Index = field(repr=False, compare=False, default=_Index((), {}, frozenset()))
    records: tuple[PreventionRecord, ...] = field(repr=False, compare=False, default=())

    def entry(self, signature: str) -> RegisterEntry | None:
        return next((e for e in self.entries if e.signature == signature), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "repo": self.repo,
            "rules": dict(self.rules),
            "apparatus": self.apparatus,
            "switch": self.switch.to_dict(),
            "attempts": dict(self.attempts),
            "counts": dict(self.counts),
            "share_closed": None if self.share_closed is None else round(self.share_closed, 4),
            "share_closed_by_process": (
                None
                if self.share_closed_by_process is None
                else round(self.share_closed_by_process, 4)
            ),
            "overlay": {k: dict(v) for k, v in self.overlay.items()},
            "playbook": {
                "lines": [ln.to_dict() for ln in self.playbook],
                "chars": sum(len(ln.text) for ln in self.playbook),
                "max_lines": MAX_LINES,
                "max_chars": MAX_CHARS,
                "sha256": playbook_digest([ln.text for ln in self.playbook]),
            },
            "entries": [e.to_dict() for e in self.entries],
            "proposals": [p.to_dict() for p in self.proposals],
            "links": [ln.to_dict() for ln in self.links],
            "chain": dict(self.chain),
        }


def _row_key(r: GradeRow) -> str:
    return r.row_hash or r.row_id


def _history_for(
    sig: str, records: Sequence[PreventionRecord], chs: Mapping[str, Change]
) -> tuple[dict[str, Any], ...]:
    out: list[dict[str, Any]] = []
    for r in records:
        p = r.payload
        touches = False
        if r.kind in ("applied", "proposed", "linked"):
            touches = sig in (p.get("targets") or [])
        elif r.kind == "decided":
            touches = str(p.get("signature", "")) == sig
        elif r.kind == "reverted":
            ch = chs.get(str(p.get("change_id", "")))
            touches = bool(ch and sig in ch.targets)
        elif r.kind == "registered":
            touches = sig in (p.get("targets") or [])
        if touches:
            summary = str(
                p.get("verdict") or p.get("lever_id") or p.get("item_id") or p.get("ref") or ""
            )
            out.append(
                {
                    "kind": r.kind,
                    "record_id": r.record_id,
                    "row_hash": r.row_hash,
                    "created": r.created,
                    "actor": r.actor,
                    "on_behalf_of": r.on_behalf_of,
                    "summary": summary,
                }
            )
    return tuple(out)


def _tried(
    sig: str, rows: Sequence[GradeRow], idx: _Index, chs: Mapping[str, Change]
) -> frozenset[str]:
    """Switches in force for OTHER classes under whose exposure this class occurred."""
    out: set[str] = set()
    for ch in chs.values():
        if ch.state != "in_force" or ch.family != "config" or sig in ch.targets:
            continue
        at = _ts(ch.applied_at)
        for r in rows:
            if (
                _ts(r.created) > at
                and is_first_attempt(r.trial)
                and ch.names(r)
                and sig in idx.of(r)
            ):
                out.add(ch.lever_id)
                break
    return frozenset(out)


def _sentence(e: dict[str, Any]) -> str:
    """The one plain sentence of what happens next (``e`` holds the computed facts)."""
    status, q = e["status"], e["qualifiers"]
    m: Measurement | None = e["measurement"]
    rec: LeverChoice = e["recommendation"]
    switch = e["switch"]
    if status == "closed":
        return (
            f"Closed: none in the last {m.closing_window if m else CLOSE_MIN} exposed first attempts. "
            "Any exposed recurrence reopens it."
        )
    if status == "applied":
        if "capability" in q:
            return (
                "Measured, never decided by recurrence: the paired A/B judges this lever by "
                "working changes per pound, and routing holds the class."
            )
        if "unproven" in q:
            return "Inconclusive: the key or the outage share moved inside the window; the switch stays, marked unproven."
        if "suspended" in q:
            return f"Suspended: the switch is {switch}; switching back resumes the change."
        if m is None:
            return "Applied; waiting for the first exposed first attempt."
        if "reopened" in q:
            return (
                "Reopened by an exposed recurrence; the next stronger lever is filed for a person."
            )
        if "displaced" in q and e.get("successor"):
            return (
                f"Displaced: the attempts now fail as {e['successor']}; it is not counted closed."
            )
        n1, dn = m.exposed_n, m.decisive_n
        st = e.get("decision_state") or {}
        if st.get("kept"):
            need = max(0, m.closing_window - m.closing_zero_run)
            return f"Kept. Needs {need} more exposed first attempt(s) with no recurrence to close."
        if n1 < dn:
            return f"Needs {dn - n1} more exposed first attempt(s) before look 1 ({m.bar})."
        return f"Needs {2 * dn - n1} more exposed first attempt(s) before look 2 ({m.bar})."
    if status == "escalated":
        pending = [p for p in e["proposals"] if not p.registered]
        if pending:
            return (
                f'Waiting on a person: register the filed item "{pending[0].title}", or link a fix.'
            )
        return f"Waiting on a switch the loop may not throw ({rec.lever_id or 'none'}; the switch is {switch})."
    if status == "retired":
        return "Every lever the loop may apply was tried and retired; routing holds the class."
    # open
    if "watch" in q:
        return f"Watching: {e['why_not']}."
    if "dormant" in q:
        return "Quiet with no change on record: dormant, and never credited to the loop."
    if "capability" in q and not rec.lever_id:
        return "A capability class: routing holds it; no lever is admissible yet."
    if switch == AUTO_OFF:
        if rec.lever_id:
            return f"The loop would apply {rec.lever_id} ({rec.level}); the switch is off."
        return "No lever the loop may apply admits this class; the switch is off."
    if rec.lever_id and rec.allowed:
        return f"The next tick applies {rec.lever_id} ({rec.level})."
    return "No lever the loop may apply admits this class; routing holds it."


def build_register(
    rows: Iterable[GradeRow],
    reviews: Iterable[ReviewRecord] = (),
    factory_events: Iterable[Mapping[str, Any]] = (),
    records: Iterable[PreventionRecord] = (),
    *,
    repo: str,
    mechanisms: Mechanisms | None = None,
    base_config: Mapping[str, Mapping[str, Any]] | None = None,
    packs: Callable[[str], Mapping[str, Any] | None] | None = None,
) -> Register:
    """THE register of one repository — pure, byte-identical for the same input, and with
    no argument that can exclude a row, a task or a class. ``packs`` is read only for rows
    whose failure kind is ``lint`` (belt 5's step tails)."""
    mech = mechanisms or Mechanisms()
    recs = [r for r in records if r.repo == repo]
    ordered = sorted(
        ((i, r) for i, r in enumerate(rows) if r.repo == repo),
        key=lambda ir: (_ts(ir[1].created), ir[0]),
    )
    rs = tuple(r for _, r in ordered)
    standing = dict(latest_reviews(r for r in reviews if r.repo == repo))
    sig_map: dict[str, tuple[str, ...]] = {}
    for r in rs:
        s = signatures(r, pack=pack_of(r, packs))
        rev = standing.get(r.row_hash)
        if rev is not None:
            s = tuple(dict.fromkeys((*s, *review_signatures(rev))))
        sig_map[_row_key(r)] = s
    idx = _Index(rs, sig_map, frozenset(h for h in standing if h))
    sw = switch_state(recs)
    chs = changes(recs)
    vet = vetoes(recs)
    ret = retired_levers(recs)
    props = proposals(recs)
    lks = links(recs)

    # --- aggregate per class --------------------------------------------------------------
    agg: dict[str, dict[str, Any]] = {}

    def slot(sig: str) -> dict[str, Any]:
        return agg.setdefault(
            sig,
            {
                "rows": [],
                "first": [],
                "tasks": set(),
                "runs": set(),
                "cost": 0.0,
                "by_mode": {},
                "by_app": {},
                "blocked": 0,
                "sizes": {},
                "factory": [],
            },
        )

    for r in rs:
        for sig in idx.of(r):
            a = slot(sig)
            a["rows"].append(r)
            a["tasks"].add(r.task_id)
            a["runs"].add(r.run_id)
            a["cost"] += float(r.cost_usd or 0.0)
            a["by_mode"][r.mode] = a["by_mode"].get(r.mode, 0) + 1
            a["by_app"][r.apparatus_version] = a["by_app"].get(r.apparatus_version, 0) + 1
            a["sizes"][r.size] = a["sizes"].get(r.size, 0) + 1
            if is_first_attempt(r.trial):
                a["first"].append(r)
            if blocked(r):
                a["blocked"] += 1
    for item_id, sig, ref, created in factory_signatures(factory_events):
        a = slot(sig)
        a["factory"].append((item_id, ref, created))
        a["tasks"].add(item_id)

    # --- first attempts overall (the register's own denominator) ----------------------------
    firsts = [r for r in rs if is_first_attempt(r.trial) and r.failure_kind != FAILURE_OUTAGE]
    attempts = {
        "first_attempts": len(firsts),
        "blind": sum(1 for r in firsts if r.mode == "blind"),
        "sighted": sum(1 for r in firsts if r.mode != "blind"),
        "rows": len(rs),
        "outage": sum(1 for r in rs if r.failure_kind == FAILURE_OUTAGE),
    }

    entries: list[RegisterEntry] = []
    for sig in sorted(agg):
        a = agg[sig]
        fam, sub, detail = split_signature(sig)
        capability = sig in CAPABILITY_CLASSES
        first = a["first"]
        by_mode_first: dict[str, int] = {}
        for r in first:
            by_mode_first[r.mode] = by_mode_first.get(r.mode, 0) + 1
        if by_mode_first:
            stratum_mode = sorted(
                by_mode_first.items(), key=lambda kv: (-kv[1], 0 if kv[0] == "blind" else 1, kv[0])
            )[0][0]
        else:
            stratum_mode = "blind"
        strat_rows = [
            r
            for r in rs
            if r.mode == stratum_mode
            and is_first_attempt(r.trial)
            and r.failure_kind != FAILURE_OUTAGE
            and observable(r, fam, reviewed=r.row_hash in idx.reviewed)
        ]
        key = comparability_key(strat_rows[-1]) if strat_rows else ""
        cur = [r for r in strat_rows if comparability_key(r) == key]
        cur_k = [r for r in cur if sig in idx.of(r)]
        cur_tasks = len({r.task_id for r in cur_k})
        not_comparable = sum(1 for r in a["rows"] if key and comparability_key(r) != key)
        targeting = [ch for ch in chs.values() if sig in ch.targets]
        # quiet in the stratum's last CLOSE_MIN comparable first attempts with no change on
        # record: dormant — never actionable, so the loop can never be credited for a class
        # that stopped by itself (ADR-0020 §6.14)
        dormant = (
            not targeting
            and len(cur) >= CLOSE_MIN
            and bool(cur_k)
            and not any(sig in idx.of(r) for r in cur[-CLOSE_MIN:])
        )
        actionable = (
            len(cur_k) >= ACTIONABLE_MIN_K
            and cur_tasks >= ACTIONABLE_MIN_TASKS
            and len(cur) >= ACTIONABLE_MIN_N
            and fam != "factory"
            and not dormant
        )
        why_not = ""
        if not actionable:
            if fam == "factory":
                why_not = "a factory outcome has no row-level exposure to measure"
            elif dormant:
                why_not = (
                    f"quiet in the last {CLOSE_MIN} comparable {stratum_mode} first attempts "
                    "with no change on record"
                )
            else:
                why_not = (
                    f"{len(cur_k)} of {ACTIONABLE_MIN_K} occurrences on {cur_tasks} of "
                    f"{ACTIONABLE_MIN_TASKS} tasks in {len(cur)} comparable {stratum_mode} "
                    f"first attempts (at least {ACTIONABLE_MIN_N} needed)"
                )

        change = targeting[-1] if targeting else None
        in_force_ch = next((ch for ch in reversed(targeting) if ch.state == "in_force"), None)
        m = (
            measure(in_force_ch, sig, rs, sigs=idx.of, reviewed=idx.reviewed)
            if in_force_ch is not None
            else None
        )
        dstate = (
            decision_state(decisions_for(recs, in_force_ch.change_id, sig)) if in_force_ch else {}
        )
        sig_props = tuple(p for p in props.values() if sig in p.targets)
        proposed_levers = frozenset(p.lever_id for p in sig_props)
        apparatus = key_apparatus(key) if key else ""
        sizes = a["sizes"]
        dom_size = sorted(sizes.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if sizes else ""
        rec = choose_lever(
            sig,
            apparatus=apparatus,
            mechanisms=mech,
            switch=sw.auto_apply,
            vetoes=vet,
            retired=ret,
            base_config=base_config,
            tried=_tried(sig, rs, idx, chs),
            proposed=proposed_levers,
            size=dom_size,
            mode=stratum_mode,
            escalate=bool(dstate.get("reopened")),
        )

        qual: list[str] = []
        if capability:
            qual.append("capability")
        if a["blocked"]:
            qual.append("contained")
        if fam == "factory":
            qual.append("unmeasurable")
        if in_force_ch is not None:
            lever_kind = in_force_ch.lever_kind
            if dstate.get("inconclusive"):
                status = "applied"
                qual.append("unproven")
            elif dstate.get("closed") and not capability:
                status = "closed"
            else:
                status = "applied"
                if dstate.get("reopened"):
                    qual.append("reopened")
                if dstate.get("displaced"):
                    qual.append("displaced")
            if in_force_ch.family in ("context", "config") and not _switch_allows(
                sw.auto_apply, in_force_ch.family
            ):
                qual.append("suspended")
            if in_force_ch.family == "config" and overridden(in_force_ch, base_config):
                qual.append("overridden")
        else:
            lever_kind = ""
            had_change = bool(targeting)
            pending = [p for p in sig_props if not p.registered]
            if not had_change and not actionable:
                status = "open"
                if fam != "factory":
                    qual.append("dormant" if dormant else "watch")
            elif sw.auto_apply == AUTO_OFF:
                status = "open"
                if rec.lever_id:
                    qual.append("suspended")
            elif rec.lever_id and rec.allowed:
                status = "open"
            elif pending or (rec.lever_id and not rec.allowed):
                status = "escalated"
            elif had_change:
                status = "retired"
            else:
                status = "open"
        entry_facts = {
            "status": status,
            "qualifiers": qual,
            "measurement": m,
            "recommendation": rec,
            "switch": sw.auto_apply,
            "proposals": sig_props,
            "why_not": why_not,
            "decision_state": dstate,
            "successor": dstate.get("successor", ""),
        }
        refs = [r.row_hash for r in a["rows"] if r.row_hash] + [ref for _, ref, _ in a["factory"]]
        seen_times = [r.created for r in a["rows"]] + [c for _, _, c in a["factory"]]
        first_seen = min(seen_times, key=_ts) if seen_times else ""
        last_seen = max(seen_times, key=_ts) if seen_times else ""
        first_ref = (
            a["rows"][0].row_hash if a["rows"] else (a["factory"][0][1] if a["factory"] else "")
        )
        entries.append(
            RegisterEntry(
                repo=repo,
                signature=sig,
                family=fam,
                sub=sub,
                detail=detail,
                first_seen=first_seen,
                first_ref=first_ref,
                last_seen=last_seen,
                occurrences=len(a["rows"]) + len(a["factory"]),
                first_attempts=len(first),
                blocked=a["blocked"],
                tasks=len(a["tasks"]),
                runs=len({x for x in a["runs"] if x}),
                cost_usd=a["cost"],
                refs=tuple(refs[:REFS_MAX]),
                refs_total=len(refs),
                by_mode=dict(sorted(a["by_mode"].items())),
                by_apparatus=dict(sorted(a["by_app"].items())),
                not_comparable=not_comparable,
                stratum_mode=stratum_mode,
                key=key,
                stratum_n=len(cur),
                stratum_k=len(cur_k),
                stratum_tasks=cur_tasks,
                actionable=actionable,
                why_not=why_not,
                recommendation=rec,
                change=change,
                proposals=sig_props,
                measurement=m,
                status=status,
                qualifiers=tuple(dict.fromkeys(qual)),
                lever_kind=lever_kind,
                next=_sentence(entry_facts),
                history=_history_for(sig, recs, chs),
                task_ids=tuple(sorted(a["tasks"])),
                dominant_size=dom_size,
            )
        )
    entries.sort(key=lambda e: (-e.first_attempts, -e.occurrences, e.signature))
    counts = {s: sum(1 for e in entries if e.status == s) for s in STATUSES}
    closed = [e for e in entries if e.status == "closed"]
    share_closed = (len(closed) / len(entries)) if entries else None
    share_process = (
        sum(1 for e in closed if e.lever_kind == "process") / len(closed) if closed else None
    )
    live = in_force(chs, switch=sw.auto_apply, base_config=base_config)
    lines = tuple(PlaybookLine.from_dict(ch.what) for ch in live if ch.family == "context")
    chain = {"records": len(recs), "head": recs[-1].row_hash if recs else GENESIS_HASH}
    try:
        verify_records(recs)
        chain["verified"] = True
    except LedgerIntegrityError as exc:
        chain["verified"] = False
        chain["error"] = str(exc)
    return Register(
        schema=REGISTER_SCHEMA,
        repo=repo,
        rules=_rules(),
        apparatus=APPARATUS_VERSION,
        switch=sw,
        attempts=attempts,
        counts=counts,
        share_closed=share_closed,
        share_closed_by_process=share_process,
        overlay=overlay_of(live),
        playbook=lines,
        entries=tuple(entries),
        proposals=tuple(props.values()),
        links=tuple(lks),
        chain=chain,
        index=idx,
        records=tuple(recs),
    )


# ===========================================================================
# 8. The tick — what the loop would append now
# ===========================================================================


def item_id_for(repo: str, signature: str, lever_id: str) -> str:
    """``prevent-<sha12>`` — stable for (repo, class, lever)."""
    return "prevent-" + sha256_text("\x1f".join((repo, signature, lever_id)))[:12]


def change_id_for(repo: str, targets: Sequence[str], lever_id: str, created: str) -> str:
    return sha256_text("\x1f".join((repo, ",".join(sorted(targets)), lever_id, created)))[:16]


_ITEM_KIND = {"infra": "infra", "operator": "operator", "product": "product", "repo": "operator"}


def _signal_for(entry: RegisterEntry, template_id: str) -> PlaybookSignal:
    slots: dict[str, str] = {}
    if template_id in ("T-NET", "T-ARCH"):
        slots["head"] = entry.detail
    elif template_id == "T-FMT":
        slots["tool"] = entry.sub
    elif template_id == "T-LINT":
        slots["tool"] = entry.sub
        slots["rule"] = entry.detail
    return PlaybookSignal(
        template_id=template_id,
        signature=entry.signature,
        slots=slots,
        taught_by_tasks=entry.task_ids,
        taught_by_rows=entry.refs[:20],
        spend=entry.cost_usd,
    )


def _facts(mech: Mechanisms, facts: RepoFacts | None) -> RepoFacts:
    if facts is not None:
        return facts
    c = mech.commands
    return RepoFacts(
        test_cmd=str(c.get("test", "")),
        lint_cmd=str(c.get("lint", "")),
        format_cmd=str(c.get("format", "")),
        typecheck_cmd=str(c.get("typecheck", "")),
    )


def tick(
    register: Register,
    records: Iterable[PreventionRecord] | None = None,
    *,
    now: str = "",
    mechanisms: Mechanisms | None = None,
    base_config: Mapping[str, Mapping[str, Any]] | None = None,
    facts: RepoFacts | None = None,
    actor: str = "loop",
    on_behalf_of: str = "",
) -> list[PreventionRecord]:
    """The records one tick appends, pure: every due decision (and the loop's revert of a
    retired or harmful change, or of an inconclusive line), then, for each class with no
    change in force, the strongest lever the switch allows and the code items to file.
    Nothing when the switch is off; nothing new when run twice over the same state."""
    mech = mechanisms or Mechanisms()
    recs = list(records) if records is not None else list(register.records)
    recs = [r for r in recs if r.repo == register.repo]
    sw = switch_state(recs)
    if sw.auto_apply == AUTO_OFF:
        return []
    now = now or utc_now_iso()
    who = on_behalf_of or sw.switched_by
    repo = register.repo
    idx = register.index
    rows = idx.rows
    out: list[PreventionRecord] = []

    def rec(kind: str, payload: Mapping[str, Any], reason: str = "") -> PreventionRecord:
        r = PreventionRecord(
            kind, repo, payload, actor=actor, on_behalf_of=who, reason=reason, created=now
        )
        out.append(r)
        return r

    # --- 1. decisions ------------------------------------------------------------------------
    for ch in changes(recs).values():
        if ch.state != "in_force":
            continue
        for sig in ch.targets:
            m = measure(ch, sig, rows, sigs=idx.of, reviewed=idx.reviewed)
            done = decisions_for(recs, ch.change_id, sig)
            for payload in due_decisions(ch, sig, m, done, capability=sig in CAPABILITY_CLASSES):
                verdict = payload["verdict"]
                rec(
                    "decided",
                    payload,
                    reason=f"{verdict} at look {payload['look']}: {payload['k1']} of {payload['n1']} "
                    f"exposed first attempts recurred (p0 = {payload['p0']})",
                )
                if verdict in ("retire", "harm") or (
                    verdict == "inconclusive" and ch.family == "context"
                ):
                    rec(
                        "reverted",
                        {
                            "change_id": ch.change_id,
                            "by": "loop",
                            "veto": False,
                            "verdict": verdict,
                        },
                        reason=f"the loop {'withdrew' if verdict == 'inconclusive' else 'retired'} "
                        f"{ch.lever_id} for {sig}: {verdict}",
                    )
                    break

    # --- 2. apply and propose -------------------------------------------------------------------
    allrec = recs + out
    chs = changes(allrec)
    vet = vetoes(allrec)
    ret = retired_levers(allrec)
    props = proposals(allrec)
    live = in_force(chs, switch=sw.auto_apply, base_config=base_config)
    lines_live = [ch for ch in live if ch.family == "context"]
    line_chars = sum(len(str(ch.what.get("text", ""))) for ch in lines_live)
    the_facts = _facts(mech, facts)
    for entry in sorted(register.entries, key=lambda e: (-e.cost_usd, e.signature)):
        sig = entry.signature
        targeting = [ch for ch in chs.values() if sig in ch.targets]
        force = next((ch for ch in reversed(targeting) if ch.state == "in_force"), None)
        dstate = decision_state(decisions_for(allrec, force.change_id, sig)) if force else {}
        if force is not None and not dstate.get("reopened"):
            continue
        apparatus = key_apparatus(entry.key) if entry.key else ""
        proposed_levers = frozenset(p.lever_id for p in props.values() if sig in p.targets)
        choice = choose_lever(
            sig,
            apparatus=apparatus,
            mechanisms=mech,
            switch=sw.auto_apply,
            vetoes=vet,
            retired=ret,
            base_config=base_config,
            tried=_tried(sig, rows, idx, chs),
            proposed=proposed_levers,
            size=entry.dominant_size,
            mode=entry.stratum_mode,
            escalate=bool(dstate.get("reopened")),
        )
        eligible = entry.actionable or (
            choice.lever_id
            and LEVER_BY_ID[choice.lever_id].deterministic
            and entry.first_attempts > 0
            # a quiet class is never credited, deterministic lever or not (ADR-0020 §6.14)
            and "dormant" not in entry.qualifiers
        )
        if not eligible:
            continue
        for lever_id in choice.propose:
            lv = LEVER_BY_ID[lever_id]
            iid = item_id_for(repo, sig, lever_id)
            if iid in props:
                continue
            payload = {
                "item_id": iid,
                "targets": [sig],
                "lever_id": lever_id,
                "level": lv.level_for(sig),
                "scope": lv.scope,
                "kind": _ITEM_KIND.get(lv.scope, "operator"),
                "title": lv.title,
                "description": (
                    f"{sig} recurred on {entry.first_attempts} first attempt(s) over "
                    f"{entry.tasks} task(s) in {repo} (${entry.cost_usd:.2f}). {lv.expected_effect}."
                ),
                "expected_effect": lv.expected_effect,
                "evidence_refs": list(entry.refs[:10]),
                "evidence_total": entry.refs_total,
            }
            r = rec(
                "proposed", payload, reason=f"the strongest lever {sig} admits is code: {lever_id}"
            )
            props[iid] = proposals([r])[iid]
        if force is not None or not choice.lever_id or not choice.allowed or not entry.key:
            continue
        lv = LEVER_BY_ID[choice.lever_id]
        if lv.family == "config":
            w = WRITABLE_BY_LEVER[lv.lever_id]
            check_writable(w.section, w.key, w.value)
            what: dict[str, Any] = {"section": w.section, "key": w.key, "value": w.value}
        else:
            if len(lines_live) >= MAX_LINES:
                continue
            line = render_line(_signal_for(entry, lv.template_id), the_facts)
            if line is None or line_chars + len(line.text) > MAX_CHARS:
                continue
            what = line.to_dict()
        before = before_window(
            rows,
            sig,
            mode=entry.stratum_mode,
            key=entry.key,
            at=now,
            sigs=idx.of,
            reviewed=idx.reviewed,
            deterministic=lv.deterministic,
        )
        cid = change_id_for(repo, [sig], lv.lever_id, now)
        payload = {
            "change_id": cid,
            "lever_id": lv.lever_id,
            "family": lv.family,
            "level": lv.level_for(sig),
            "targets": [sig],
            "stratum": {"mode": entry.stratum_mode},
            "key": entry.key,
            "what": what,
            "before": {sig: before},
        }
        rec(
            "applied",
            payload,
            reason=f"{sig}: {before['k0']} of {before['n0']} {entry.stratum_mode} first attempts; "
            f"{choice.why}",
        )
        if lv.family == "context":
            lines_live.append(changes([out[-1]])[cid])
            line_chars += len(str(what.get("text", "")))
    return out


def link_record(
    register: Register,
    *,
    targets: Sequence[str],
    ref: str,
    note: str = "",
    served_commit: str = "",
    now: str = "",
    actor: str,
) -> PreventionRecord:
    """A person's link from classes to a fix made outside the loop. Its exposure starts at
    this record and never crosses the apparatus: the before window and the comparability key
    are frozen here, per target, from the current stratum."""
    now = now or utc_now_iso()
    idx = register.index
    before: dict[str, Any] = {}
    key = ""
    mode = ""
    for sig in targets:
        e = register.entry(sig)
        if e is None or not e.key:
            continue
        key = key or e.key
        mode = mode or e.stratum_mode
        before[sig] = before_window(
            idx.rows,
            sig,
            mode=e.stratum_mode,
            key=e.key,
            at=now,
            sigs=idx.of,
            reviewed=idx.reviewed,
        )
    return PreventionRecord(
        "linked",
        register.repo,
        {
            "targets": list(targets),
            "ref": ref,
            "note": note,
            "served_commit": served_commit,
            "stratum": {"mode": mode},
            "key": key,
            "before": before,
        },
        actor=actor,
        on_behalf_of=actor,
        reason=note,
        created=now,
    )


def verify_decisions(
    records: Iterable[PreventionRecord],
    rows: Iterable[GradeRow],
    *,
    sigs: SigsFn | None = None,
) -> list[str]:
    """Re-derive every ``decided`` record from the ledger: the exposed rows it read must all
    be there, in order, and give the same counts and verdict. A filtered ledger — a row
    dropped from the exposure — is refused by name. ``sigs`` defaults to the row-level
    rule; pass a register's (``Register.index.of``) for classes read from packs or reviews."""
    recs = list(records)
    rs = sorted(((i, r) for i, r in enumerate(rows)), key=lambda ir: (_ts(ir[1].created), ir[0]))
    ordered = [r for _, r in rs]
    chs = changes(recs)
    problems: list[str] = []
    for r in recs:
        if r.kind != "decided":
            continue
        p = r.payload
        ch = chs.get(str(p.get("change_id", "")))
        sig = str(p.get("signature", ""))
        if ch is None:
            problems.append(f"decision {r.record_id}: no applied change {p.get('change_id')}")
            continue
        repo_rows = [x for x in ordered if x.repo == r.repo]
        m = measure(ch, sig, repo_rows, sigs=sigs)
        n1 = int(p.get("n1", 0) or 0)
        if m.exposed_n < n1:
            problems.append(
                f"decision {r.record_id}: read {n1} exposed first attempts, the ledger holds "
                f"{m.exposed_n} — rows are missing (a filtered ledger)"
            )
            continue
        s = _stats(m, n1)
        if s["exposed_digest"] != p.get("exposed_digest"):
            problems.append(
                f"decision {r.record_id}: the exposed rows differ from the ones it read "
                "(a filtered or reordered ledger)"
            )
            continue
        if s["k1"] != p.get("k1"):
            problems.append(f"decision {r.record_id}: k1 {p.get('k1')} re-derives as {s['k1']}")
            continue
        look, verdict = str(p.get("look", "")), str(p.get("verdict", ""))
        if look in ("1", "2") and verdict in ("keep", "continue", "retire"):
            kept = _kept_at(m, n1)
            want = "keep" if kept else ("retire" if look == "2" else "continue")
            if want != verdict:
                problems.append(f"decision {r.record_id}: {verdict} re-derives as {want}")
    return problems


# ===========================================================================
# 9. The snapshot — what one run is given
# ===========================================================================


@dataclass(frozen=True)
class LearningSnapshot:
    """What the loop gives one run: the effective switch (after any opt-out), the changes in
    force, the overlay and the lines. Taken once when the run starts."""

    repo: str
    auto_apply: str = AUTO_OFF
    changes: tuple[Change, ...] = ()
    lines: tuple[PlaybookLine, ...] = ()
    overlay: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    opted_out: bool = False

    @property
    def overlay_digest(self) -> str:
        if not self.overlay:
            return ""
        return sha256_text(canonical_json({k: dict(v) for k, v in self.overlay.items()}))[:16]

    def config_section(self, section: str, base: Mapping[str, Any] | None) -> dict[str, Any]:
        """The overlay's keys for ``section`` under the team's own: base keys always win."""
        return {**dict(self.overlay.get(section, {})), **dict(base or {})}

    def lines_for(
        self,
        task_id: str,
        *,
        target_tests: Sequence[str] = (),
        test_files: Sequence[str] = (),
        src_files: Sequence[str] = (),
        refuses: Callable[[str], str] | None = None,
    ) -> tuple[list[str], list[str], list[str]]:
        """``(texts, line ids, dropped ids)`` for one task: held out by task, then the leak
        gate, then — when ``refuses`` is given (the builder's own shell guard) — any line
        recommending a command the guard refuses."""
        kept, dropped = held_out(self.lines, task_id)
        kept, leaked = leak_gate(
            kept, target_tests=target_tests, test_files=test_files, src_files=src_files
        )
        dropped += leaked
        final: list[PlaybookLine] = []
        for ln in kept:
            if refuses is not None and any(refuses(c) for c in ln.commands):
                dropped.append(ln.line_id)
            else:
                final.append(ln)
        return [ln.text for ln in final], [ln.line_id for ln in final], dropped

    def switch_change_ids(self) -> list[str]:
        return sorted(ch.change_id for ch in self.changes if ch.family == "config")

    def run_labels(self) -> dict[str, str]:
        """The labels every row of the run carries (hashed): the effective switch, the
        switch changes in force (≤ 8 ids, else the digest of the set) and the overlay."""
        out = {LABEL_LEARN: self.auto_apply}
        ids = self.switch_change_ids()
        if ids:
            out[LABEL_CHANGES] = (
                ",".join(ids) if len(ids) <= MAX_CHANGE_IDS else "set:" + _digest(ids)
            )
        if self.overlay_digest:
            out[LABEL_OVERLAY] = self.overlay_digest
        return out

    @staticmethod
    def task_labels(
        line_ids: Sequence[str], dropped_ids: Sequence[str], texts: Sequence[str]
    ) -> dict[str, str]:
        """The per-attempt labels: which lines the builder read, which were dropped, and the
        digest of what it read."""
        out: dict[str, str] = {}
        if line_ids:
            out[LABEL_LINES] = ",".join(line_ids)
            out[LABEL_PLAYBOOK] = playbook_digest(texts)
        if dropped_ids:
            out[LABEL_DROPPED] = ",".join(sorted(set(dropped_ids)))
        return out

    def apparatus(self) -> dict[str, Any]:
        """For the run's apparatus stamp (``extra.learning``)."""
        return {
            "auto_apply": self.auto_apply,
            "opted_out": self.opted_out,
            "changes": [ch.change_id for ch in self.changes],
            "overlay": {k: dict(v) for k, v in self.overlay.items()},
            "lines": [ln.line_id for ln in self.lines],
            "rules": _rules(),
        }


def empty_snapshot(repo: str, *, opted_out: bool = False) -> LearningSnapshot:
    """``learn: off`` — what a run gets when the loop is off, opted out or unreadable."""
    return LearningSnapshot(repo=repo, opted_out=opted_out)


def snapshot(
    records: Iterable[PreventionRecord],
    *,
    repo: str,
    params: Mapping[str, Any] | None = None,
    base_config: Mapping[str, Mapping[str, Any]] | None = None,
) -> LearningSnapshot:
    """The run's snapshot. ``params['learning'] == 'off'`` opts the run out (a run may opt
    out, never in); otherwise the repository's switch decides what is in force, and a key the
    team or the run sets is theirs."""
    p = dict(params or {})
    if str(p.get("learning") or "") == AUTO_OFF:
        return empty_snapshot(repo, opted_out=True)
    recs = [r for r in records if r.repo == repo]
    sw = switch_state(recs)
    if sw.auto_apply == AUTO_OFF:
        return empty_snapshot(repo)
    live = in_force(changes(recs), switch=sw.auto_apply, base_config=base_config, run_params=p)
    lines = tuple(PlaybookLine.from_dict(ch.what) for ch in live if ch.family == "context")
    return LearningSnapshot(
        repo=repo,
        auto_apply=sw.auto_apply,
        changes=live,
        lines=lines[:MAX_LINES],
        overlay=overlay_of(live),
    )


# ===========================================================================
# 10. Stream S's seam
# ===========================================================================


@dataclass(frozen=True)
class RegisterStatus:
    """One class's standing for the scorecard: ``status`` ∈ :data:`STATUSES`, ``lever`` ∈
    ``("process", "context", "")``."""

    signature: str
    repo: str
    status: str
    lever: str = ""


def _grade_of(row: Any) -> GradeRow | None:
    if isinstance(row, GradeRow):
        return row
    g = getattr(row, "grade", None)
    return g if isinstance(g, GradeRow) else None


class PreventionRegister:
    """Duck-types stream S's ``BugRegister`` (``crb.core.value``): ``class_of`` names a
    row's primary class, ``statuses`` gives each class's standing from this register. A row
    without its full ``GradeRow`` is classed at family level from its failure kind."""

    source = REGISTER_SCHEMA

    def __init__(
        self,
        records: Iterable[PreventionRecord] = (),
        *,
        reviews: Iterable[ReviewRecord] = (),
        factory_events: Iterable[Mapping[str, Any]] = (),
        mechanisms: Mechanisms | None = None,
        packs: Callable[[str], Mapping[str, Any] | None] | None = None,
    ) -> None:
        self.records = list(records)
        self.reviews = list(reviews)
        self.factory_events = list(factory_events)
        self.mechanisms = mechanisms or Mechanisms()
        #: the evidence packs, read exactly as the Learn page's register reads them — without
        #: them every belt-5 row would read ``lint:*`` here while Learn shows ``format:gofmt``
        #: closed (docs/PREVENTION.md P-022)
        self.packs = packs

    def class_of(self, row: Any) -> str | None:
        g = _grade_of(row)
        if g is not None:
            return primary_signature(g, pack=pack_of(g, self.packs))
        if getattr(row, "clean", False):
            return None
        kind = str(getattr(row, "failure_kind", "") or "")
        if not kind or kind == FAILURE_OUTAGE:
            return None
        detail = str(getattr(row, "detail", "") or "")
        return make_signature(kind, detail) if detail else make_signature(kind, "*")

    def statuses(self, rows: Sequence[Any]) -> list[RegisterStatus]:
        grades: dict[str, list[GradeRow]] = {}
        loose: dict[tuple[str, str], RegisterStatus] = {}
        for row in rows:
            g = _grade_of(row)
            if g is not None:
                grades.setdefault(g.repo, []).append(g)
                continue
            sig = self.class_of(row)
            repo = str(getattr(row, "repo", ""))
            if sig is not None:
                loose.setdefault((repo, sig), RegisterStatus(sig, repo, "open", ""))
        out: list[RegisterStatus] = []
        for repo in sorted(grades):
            reg = build_register(
                grades[repo],
                self.reviews,
                [e for e in self.factory_events if str(e.get("repo", repo)) == repo],
                self.records,
                repo=repo,
                mechanisms=self.mechanisms,
                packs=self.packs,
            )
            out.extend(
                RegisterStatus(e.signature, repo, e.status, e.lever_kind) for e in reg.entries
            )
        out.extend(loose[k] for k in sorted(loose))
        return out


__all__ = [
    "ACTIONABLE_MIN_K",
    "ACTIONABLE_MIN_N",
    "ACTIONABLE_MIN_TASKS",
    "ALPHA_HARM",
    "ALPHA_LOOK",
    "AUTO_CONFIG",
    "AUTO_CONTEXT",
    "AUTO_MODES",
    "AUTO_OFF",
    "BEFORE_MAX",
    "CAPABILITY_CLASSES",
    "CLOSE_MIN",
    "CONTAINMENT",
    "DECISION_RULE",
    "DECISIVE_MAX",
    "DECISIVE_MIN",
    "DETERMINISTIC_N",
    "DISPLACEMENT",
    "FAMILIES",
    "FORBIDDEN_EXAMPLES",
    "FORMATTER_TOOLS",
    "HARM_AT",
    "HARNESS_TOOLS",
    "K_SECTION",
    "LABEL_CHANGES",
    "LABEL_DROPPED",
    "LABEL_FORMAT_STEP",
    "LABEL_LEARN",
    "LABEL_LINES",
    "LABEL_OVERLAY",
    "LABEL_PLAYBOOK",
    "LEVELS",
    "LEVERS",
    "LEVER_BY_ID",
    "MAX_CHANGE_IDS",
    "QUALIFIERS",
    "RECORD_KINDS",
    "RECORD_SCHEMA",
    "REGISTER_SCHEMA",
    "RUNNER_TOOL_MISSING_PREFIX",
    "SIGNATURE_RULES",
    "STATUSES",
    "WRITABLE",
    "W_SECTION",
    "Change",
    "JsonlPreventionStore",
    "LearningSnapshot",
    "Lever",
    "LeverChoice",
    "Link",
    "Measurement",
    "Mechanisms",
    "MemoryPreventionStore",
    "NotWritable",
    "PreventionRecord",
    "PreventionRegister",
    "PreventionStore",
    "Proposal",
    "Register",
    "RegisterEntry",
    "RegisterStatus",
    "SwitchState",
    "WritableSwitch",
    "api_signatures",
    "before_window",
    "binom_cdf",
    "binom_sf",
    "blocked",
    "build_register",
    "changes",
    "check_writable",
    "choose_lever",
    "command_head",
    "comparability_key",
    "decision_state",
    "decisions_for",
    "decisive_n",
    "due_decisions",
    "empty_snapshot",
    "factory_signatures",
    "harness_cause",
    "in_force",
    "is_first_attempt",
    "item_id_for",
    "keep_bar",
    "link_record",
    "links",
    "lint_signatures",
    "make_signature",
    "measure",
    "observable",
    "overlay_of",
    "overridden",
    "primary_signature",
    "proposals",
    "retired_levers",
    "review_signatures",
    "rule_ids",
    "signatures",
    "snapshot",
    "split_signature",
    "switch_state",
    "tick",
    "verify_decisions",
    "verify_records",
    "vetoes",
]
