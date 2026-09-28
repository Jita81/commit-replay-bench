"""The learning half of the loop — three deterministic derivations from the ledger.

The *measurement* half of ``crb`` loops mechanically: run → grade → ledger → map →
route. The *learning* half — a refusal becoming a guard test, a weak oracle becoming
test-strengthening work, an apparatus bump becoming a re-measurement — used to
happen only through people reading the ledger (critical-friend review 2026-09-13,
§5 plays 04/06/07 and §8). This module makes those three derivations PRODUCT
BEHAVIOUR: pure, stdlib-only functions over the ledger as it is, whose output is
byte-identical for the same input, and which **never act**:

* :func:`triage_refusals` — every ``protocol`` row's attempted command(s), grouped by
  (guard reason, normalised command shape), costed, and turned into a *candidate*
  corpus line in the format of ``tests/fixtures/shell_corpus*.txt``. Every group's
  verdict is ``unsure`` until a human says ``honest`` or ``refuse``;
  :func:`apply_triage` appends only what a human decided, with provenance.
* :func:`strengthening_backlog` — every cell the routing rule holds back for a weak
  or escaped oracle (``oracle_weak`` / ``controls_escapes`` / ``controls_thin``)
  becomes a backlog item in the factory's frozen-backlog shape: "strengthen the
  target tests for <repo> <task>", listing the escaped mutants when the oracle run
  recorded them, else the count. Items are ``test.add`` with both STRUCTURAL slots
  filled from facts the ledger holds — never a value from the answer (the review's
  play-01 finding) — so the DoR gate accepts them as ``build``.
  :func:`guard_false_positives` folds the verdicts people recorded into the guard's
  false-positive rate per apparatus version and month — a bound while any row is undecided.
* :func:`remeasure_plan` — read from the registered readings (ADR-0026 item 2): each reading
  waiting on its look, with the commits it still needs in its seeded order, the ``POST /runs``
  body an operator can queue for them and its cost (that cell's own mean row cost × the
  commits requested); each cell with rows but no reading (``stale`` or ``thin``), offered
  registration and never a replay; each reading decided against its cell. It queues nothing.

Why the three human steps are deliberate, not missing: a loop that appended its own
refusals to its own guard corpus would launder a false positive into policy the
moment it happened (§5 play 04 asks for a *person* to read refusals); a
strengthening item pulled into a sprint by the product would spend a builder on an
oracle nobody reviewed (§5 play 03); a re-measurement queued by the product would
spend money without an operator's consent. Each derivation stops exactly where a
decision needs a name attached. **Where the name is attached is not this module's
business**: a named person decides on the host (``crb learn refusals --apply``) or on the
screen (the operator-gated ``POST /learn/{refusals/accept,strengthen/register,
remeasure/queue}``, which record the decision with the signed-in operator's identity).
Nothing here decides either way.

Navigation
----------
What it is:   The learning loop's three derivations — refusal triage, the oracle-strengthening
              backlog and the apparatus re-measurement plan — pure functions from the ledger
              and the capability map to proposals a human acts on.
What it does: Groups every ``protocol`` row's guard refusals by (reason, command shape),
              costs them and proposes corpus lines whose verdict is always ``unsure``; folds
              the recorded verdicts into the guard's false-positive rate per apparatus and
              month (undecided rows kept apart); turns every oracle-held cell into ``test.add``
              backlog items with structural facts from the ledger; lists every registered
              reading waiting on its look with the commits it still needs, the ``POST /runs``
              body that would grade them and what it costs, and every cell with rows but no
              reading as needing one registered first.
              Writes only what a named human decided (``apply_triage``, under a lock on the
              corpus directory; a supplied command only completes a cut example) and queues
              nothing.
How:          ``triage_refusals`` (``parse_violations`` → ``normalise_reason`` /
              ``normalise_command`` → ``RefusalGroup``) → a decisions file → ``apply_triage``
              (validate all, then append with provenance); ``guard_false_positives`` (the
              report's row stamps × the latest verdict per group → ``FalsePositivePeriod``);
              ``strengthening_backlog`` (cells with an oracle reason code ×
              ``OracleTaskScore``) → ``StrengthenItem``;
              ``remeasure_plan`` (each reading's outcome → the blocking arm's pending commits
              in the seeded order → ``RunRequest``; rows of a cell no reading covers →
              ``register``; ``first_attempts`` for their distinct commits).
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules (the loop itself:
              docs/LEARNING-LOOP.md#2-what-crbcorelearn-adds)
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/core/ledger.py (the rows, failure kinds and cell grouping),
              src/crb/core/reading.py (the readings the re-measurement plan reads),
              src/crb/core/context_arm.py (the mode a replay writes each arm in),
              src/crb/core/capability.py (the cells and their reason codes),
              src/crb/core/routing.py (the reasons and thresholds the derivations key on),
              src/crb/cli/commands/learn.py (``crb learn refusals|strengthen|remeasure``),
              src/crb/server/routes/learn.py (the same derivations over the store),
              src/crb/builders/base.py (the guard reasons parsed here; the corpus tests in
              tests/test_builders_guard_corpus.py consume what ``apply_triage`` writes),
              src/crb/factory/backlog.py (the BacklogItem shape strengthening items mirror)
Tested by:    tests/test_learn.py, tests/test_learn_remeasure.py, tests/test_cli_learn.py,
              tests/test_server_routes_learn.py
Touch when:   never for a new repository — a repository's rows, tasks and labels are read as
              they are; a new guard prefix, a new routing reason code or a
              change to ``BacklogItem`` must be mirrored here (the core cannot import the
              builders or the factory — tests/test_learn.py pins the mirrors); the human
              steps are deliberate (docs/LEARNING-LOOP.md#3-what-still-needs-a-human-and-why-that-is-deliberate)
              — nothing in this module may accept, build or queue on its own; the writes
              belong to src/crb/server/routes/learn.py, behind a named person.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import fcntl
import hashlib
import json
import os
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crb.core.capability import CapabilityCell, CapabilityMap
from crb.core.context_arm import BASE_S1, BASE_S2, REPLAY_MODE, parse_arm
from crb.core.ledger import (
    CELL_FIELDS,
    FAILURE_PROTOCOL,
    PROTOCOL_VIOLATION_PREFIX,
    CellKey,
    GradeRow,
    first_attempts,
    group_by_cell,
)
from crb.core.reading import (
    STATE_DELIVER,
    STATE_INSUFFICIENT,
    STATE_LOOK_PENDING,
    ReadingOutcome,
    latest_outcome,
    rule_looks,
    verdict_for,
)
from crb.core.redact import redact
from crb.core.routing import (
    DEFAULT_POLICY,
    REASON_CONTROLS_ESCAPES,
    REASON_CONTROLS_THIN,
    REASON_ORACLE_WEAK,
    RoutingPolicy,
)
from crb.core.routing import (
    NEXT_MINE as ROUTING_NEXT_MINE,
)
from crb.core.routing import (
    NEXT_NEW_READING as ROUTING_NEXT_NEW_READING,
)
from crb.core.routing import (
    NEXT_REGISTER as ROUTING_NEXT_REGISTER,
)
from crb.core.routing import (
    NEXT_REPLAY as ROUTING_NEXT_REPLAY,
)
from crb.core.stats import mean, wilson_interval
from crb.core.version import APPARATUS_VERSION

REFUSALS_SCHEMA = "crb.learn.refusals.v1"
DECISIONS_SCHEMA = "crb.learn.decisions.v1"
STRENGTHEN_SCHEMA = "crb.learn.strengthen.v1"
REMEASURE_SCHEMA = "crb.learn.remeasure.v1"

# --- verdict vocabulary (a human's, never the product's) -------------------------------
VERDICT_HONEST = "honest"
VERDICT_REFUSE = "refuse"
VERDICT_UNSURE = "unsure"
VERDICTS: tuple[str, ...] = (VERDICT_HONEST, VERDICT_REFUSE, VERDICT_UNSURE)

# --- guard reason prefixes (mirrors crb.builders.base; the core cannot import it) --------
PREFIX_ARCHAEOLOGY = "archaeology"
PREFIX_NETWORK = "network"
PREFIX_TAMPER = "tamper"
PREFIX_OTHER = "other"
GUARD_PREFIXES: tuple[str, ...] = (PREFIX_TAMPER, PREFIX_ARCHAEOLOGY, PREFIX_NETWORK)
#: The prefixes ``shell_corpus_refused.txt`` accepts (``tests/test_builders_guard_corpus.py``).
CORPUS_REFUSED_PREFIXES: tuple[str, ...] = (PREFIX_ARCHAEOLOGY, PREFIX_NETWORK)

#: Default corpus file names (relative to a fixtures directory).
CORPUS_HONEST_FILE = "shell_corpus.txt"
CORPUS_REFUSED_FILE = "shell_corpus_refused.txt"

#: The reasons the routing rule gives for "green cannot license auto-delivery because
#: of the ORACLE" — the ones test-strengthening work can move.
STRENGTHEN_REASONS: tuple[str, ...] = (
    REASON_ORACLE_WEAK,
    REASON_CONTROLS_ESCAPES,
    REASON_CONTROLS_THIN,
)

#: ``claude_code`` / ``openai_agent`` cut the attempted command at this many characters
#: before recording it; a fragment of exactly this length is probably truncated.
ATTEMPTED_CAP = 120

_ATTEMPTED = "(attempted: "
_SPLIT_RE = re.compile(r";\s+(?=(?:tamper|archaeology|network):)")
_ATTEMPTED_ANY_RE = re.compile(re.escape(_ATTEMPTED))


class LearnError(ValueError):
    """A derivation was asked to do something it must refuse (accept for a human, act…)."""


def _short_hash(*parts: str) -> str:
    """A stable 16-hex id from its parts (unit-separator joined, so ``("a b", "c")``
    and ``("a", "b c")`` differ) — group and item ids survive a re-run unchanged."""
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


def _version_key(v: str) -> tuple[int, ...]:
    """``"2.1"`` → ``(2, 1)``; non-numeric parts sort as 0 (``"v3-legacy"`` → ``(0,)``)."""
    out: list[int] = []
    for part in v.split("."):
        digits = re.match(r"\d+", part)
        out.append(int(digits.group(0)) if digits else 0)
    return tuple(out)


# ===========================================================================
# 1. Refusal triage
# ===========================================================================


@dataclass(frozen=True)
class Violation:
    """One guard refusal parsed from a row's ``protocol violation:`` text.

    ``prefix`` is the guard family (``archaeology`` / ``network`` / ``tamper``, or
    ``other`` for a free-text violation written by a reviewer); ``reason`` the
    guard's own sentence; ``command`` the attempted shell (``""`` when the text
    carried none); ``truncated`` when the recorder's 120-character cap, or the
    ledger's own field caps, cut the command — such a line is not a usable corpus
    line until a human completes it.
    """

    prefix: str
    reason: str
    command: str
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "prefix": self.prefix,
            "reason": self.reason,
            "command": self.command,
            "truncated": self.truncated,
        }


def _prefix_of(reason: str) -> str:
    """The guard family a reason belongs to, by its ``<prefix>:`` lead; ``other``
    for free text."""
    for p in GUARD_PREFIXES:
        if reason.startswith(p + ":"):
            return p
    return PREFIX_OTHER


def parse_violations(text: str) -> list[Violation]:
    """Parse ``protocol violation: <reason> (attempted: <cmd>)[; <reason> (attempted: …)]``.

    Tolerates what the ledger actually holds: the ``(attempted: …)`` fragment may be
    absent (a reviewer-written violation), the command may contain parentheses and
    quotes (a grep pattern), and the whole string may have been cut by the
    recorder's caps (``labels.builder_error`` keeps the first 300 characters,
    ``error`` the last 500). Pure; order preserved.
    """
    body = text.strip()
    if body.startswith(PROTOCOL_VIOLATION_PREFIX):
        body = body[len(PROTOCOL_VIOLATION_PREFIX) :].strip()
    if not body:
        return []
    out: list[Violation] = []
    for fragment in _SPLIT_RE.split(body):
        frag = fragment.strip()
        if not frag:
            continue
        idx = frag.find(_ATTEMPTED)
        if idx < 0:
            out.append(Violation(_prefix_of(frag), frag, "", False))
            continue
        reason = frag[:idx].strip()
        cmd = frag[idx + len(_ATTEMPTED) :]
        # no closing paren: the ledger's own field cap cut the text mid-command;
        # a closing paren at exactly the recorder's cap: probably cut by the recorder
        truncated = True
        if cmd.endswith(")"):
            cmd = cmd[:-1]
            truncated = len(cmd) >= ATTEMPTED_CAP
        out.append(Violation(_prefix_of(reason), reason, cmd, truncated))
    return out


_SHA_RE = re.compile(r"\b[0-9a-f]{7,64}\b")
_URL_RE = re.compile(r"[a-z][a-z0-9+.-]*://[^\s'\"]+")
_NUM_RE = re.compile(r"(?<![\w.&])\d+(?![\w.>])")  # keeps 2>&1 and 2> as redirections
_QUOTE_RE = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'")
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_EXT_RE = re.compile(r"^[\w.@+-]+\.[A-Za-z][A-Za-z0-9]{0,5}$")


def _norm_token(tok: str) -> str:
    """One shell token → its shape token (flags and verbs kept, paths ``<path>``)."""
    if not tok or tok.startswith("-"):
        return tok
    if "$(" in tok or "`" in tok or "${" in tok:
        return tok  # the substitution IS the shape (a $(pwd) false-positive class)
    if tok.startswith(("/", "./", "../", "~/")) or "/" in tok:
        return "<path>"
    if _EXT_RE.match(tok) and not tok.startswith("."):
        return "<path>"
    return tok


def normalise_command(command: str) -> str:
    """The *shape* of a shell command: quoted strings → ``"<str>"``, URLs → ``<url>``,
    shas → ``<sha>``, paths → ``<path>``, bare numbers → ``<n>``; a newline becomes
    the token ``\\n``; whitespace collapsed. Flags, verbs, pipes,
    redirections and command substitutions are kept — they are what a guard
    decides on. Deterministic."""
    text = command.replace("\r\n", "\n").replace("\n", " \\n ")
    text = _URL_RE.sub("<url>", text)
    text = _QUOTE_RE.sub(lambda m: m.group(0)[0] + "<str>" + m.group(0)[0], text)
    text = _SHA_RE.sub("<sha>", text)
    parts: list[str] = []
    for tok in text.split():
        m = _ASSIGN_RE.match(tok)
        if m:
            key = m.group(0)
            parts.append(key + _norm_token(tok[len(key) :]))
        else:
            parts.append(_norm_token(tok))
    return _NUM_RE.sub("<n>", " ".join(parts))


def normalise_reason(reason: str) -> str:
    """The guard's sentence with its variable parts placeholdered (same rules as
    :func:`normalise_command` inside the quotes the guard writes)."""
    text = _URL_RE.sub("<url>", reason)
    text = _SHA_RE.sub("<sha>", text)

    def _inner(m: re.Match[str]) -> str:
        q = m.group(0)[0]
        return q + normalise_command(m.group(0)[1:-1]) + q

    text = _QUOTE_RE.sub(_inner, text)
    return " ".join(text.split())


#: Every character ``str.splitlines`` ends a line at — the way the corpus files are read
#: (``_existing_lines``, ``tests/test_builders_guard_corpus.py``). Free text written into a
#: corpus file must carry none of them, or one decision writes lines nobody decided (P-161).
LINE_BREAKS = frozenset("\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029")
_LINE_BREAK_RE = re.compile("[" + re.escape("".join(sorted(LINE_BREAKS))) + "]")


def has_line_break(text: str) -> bool:
    """True when ``text`` would take more than one line of a corpus file."""
    return _LINE_BREAK_RE.search(text) is not None


def one_line(text: str) -> str:
    """Free text as one line of a corpus-file comment: every line break (and a CRLF pair)
    becomes one space, so a note or a name can never end the comment it is written into."""
    return _LINE_BREAK_RE.sub(" ", text.replace("\r\n", "\n"))


def encode_corpus_line(command: str) -> str:
    """A command as one corpus line (``\\n`` for a newline, a lone CR read as one; secrets
    redacted). Any other line break is written as its escape (``\\x0b``, ``\\u2028``) —
    the line stays one line and still says which character the command carried (P-161)."""
    text = redact(command.replace("\r\n", "\n").replace("\r", "\n")).replace("\n", "\\n")
    return _LINE_BREAK_RE.sub(
        lambda m: m.group().encode("unicode_escape").decode("ascii"), text
    ).strip()


@dataclass(frozen=True)
class RefusalGroup:
    """One (guard reason, command shape) class of refusal, with what it cost.

    ``candidate_honest`` / ``candidate_refused`` are the lines :func:`apply_triage`
    would append under each verdict; ``verdict`` is ALWAYS ``unsure`` in a report —
    the product never decides. ``truncated`` means no example command survived
    the recorder's caps whole, so a human must supply the full line.
    """

    group_id: str
    prefix: str
    reason: str
    shape: str
    n: int
    cost_usd: float
    minutes: float
    repos: tuple[str, ...]
    tasks: tuple[str, ...]
    rows: tuple[str, ...]
    examples: tuple[str, ...]
    truncated: bool
    candidate_honest: str
    candidate_refused: str
    verdict: str = VERDICT_UNSURE

    def __post_init__(self) -> None:
        if self.verdict != VERDICT_UNSURE:
            raise LearnError("a RefusalGroup in a report is always 'unsure'; a human decides")

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "prefix": self.prefix,
            "reason": self.reason,
            "shape": self.shape,
            "n": self.n,
            "cost_usd": round(self.cost_usd, 6),
            "minutes": round(self.minutes, 2),
            "repos": list(self.repos),
            "tasks": list(self.tasks),
            "rows": list(self.rows),
            "examples": list(self.examples),
            "truncated": self.truncated,
            "candidate_honest": self.candidate_honest,
            "candidate_refused": self.candidate_refused,
            "verdict": self.verdict,
        }


@dataclass(frozen=True)
class RefusalReport:
    """Every protocol row of a ledger, triaged into groups (most frequent first).

    ``rows_protocol`` / ``rows_total`` give the denominator the review asked for
    (§7.5: the instrument-caused share of rows); ``unparsed`` counts protocol rows
    whose text carried no parseable violation (they still count and cost).
    """

    groups: tuple[RefusalGroup, ...]
    rows_total: int
    rows_protocol: int
    cost_usd: float
    minutes: float
    unparsed: int
    apparatus_versions: tuple[str, ...]
    #: ``(apparatus_version, rows_total, rows_protocol)`` per apparatus — the share is
    #: never blended across versions in what is served (CodeRabbit on PR #6, 2026-09-16).
    by_apparatus: tuple[tuple[str, int, int], ...] = ()
    #: ``(row key, apparatus_version, created)`` of every protocol row, sorted — what
    #: :func:`guard_false_positives` dates each row by. Not served: the groups name the rows.
    row_stamps: tuple[tuple[str, str, str], ...] = field(default=(), repr=False, compare=False)

    @property
    def instrument_share(self) -> float:
        """The share of ALL rows the guards refused (review §7.5's denominator)."""
        return self.rows_protocol / self.rows_total if self.rows_total else 0.0

    def share_dict(self, protocol: int, total: int) -> dict[str, Any]:
        """One rate with its n and Wilson 95% interval — the only form a rate is served in."""
        ci = wilson_interval(protocol, total)
        return {
            "rows_total": total,
            "rows_protocol": protocol,
            "share": round(protocol / total, 4) if total else 0.0,
            "ci_low": round(ci.low, 4) if total else 0.0,
            "ci_high": round(ci.high, 4) if total else 1.0,
        }

    def get(self, group_id: str) -> RefusalGroup | None:
        """The group a decision names, or ``None`` (an unknown id is refused)."""
        for g in self.groups:
            if g.group_id == group_id:
                return g
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": REFUSALS_SCHEMA,
            "rows_total": self.rows_total,
            "rows_protocol": self.rows_protocol,
            "protocol_share": round(self.instrument_share, 4),
            # the rate WITH its interval, and per apparatus version (never blended)
            "share": self.share_dict(self.rows_protocol, self.rows_total),
            "by_apparatus": [
                {"apparatus_version": v, **self.share_dict(p, t)} for v, t, p in self.by_apparatus
            ],
            "cost_usd": round(self.cost_usd, 6),
            "minutes": round(self.minutes, 2),
            "unparsed": self.unparsed,
            "apparatus_versions": list(self.apparatus_versions),
            "verdicts": list(VERDICTS),
            "groups": [g.to_dict() for g in self.groups],
            "note": (
                "every verdict is 'unsure': this derivation never decides; a NAMED person "
                "does, and `apply_triage` appends their decision with provenance — from the "
                "host (`crb learn refusals --apply`) or from the screen "
                "(`POST /learn/refusals/accept`, recorded with the operator's identity)"
            ),
        }


def row_violation_text(row: GradeRow) -> str:
    """The most complete ``protocol violation:`` text a row carries (``labels.
    builder_error`` holds the first 300 chars, ``error`` the last 500 — whichever
    still starts with the prefix and is longer wins)."""
    candidates = [
        t
        for t in (row.error, str(row.labels.get("builder_error", "")))
        if t.startswith(PROTOCOL_VIOLATION_PREFIX)
    ]
    if not candidates:
        return ""
    return max(candidates, key=len)


def triage_refusals(rows: Iterable[GradeRow]) -> RefusalReport:
    """Group every ``protocol`` row's violations by (prefix, reason shape, command
    shape); count, cost and time them; propose one corpus line per group.

    Pure and deterministic: groups sort by (−n, prefix, reason, shape); every
    tuple inside a group is sorted. A row with several violations contributes to
    each group once (its cost is attributed to each — the row was lost to all of
    them — and reported once in the totals).
    """
    rs = list(rows)
    protocol = [r for r in rs if r.failure_kind == FAILURE_PROTOCOL]
    buckets: dict[tuple[str, str, str], list[tuple[GradeRow, Violation]]] = {}
    unparsed = 0
    for r in protocol:
        vs = parse_violations(row_violation_text(r))
        if not vs:
            unparsed += 1
            continue
        seen: set[tuple[str, str, str]] = set()
        for v in vs:
            key = (v.prefix, normalise_reason(v.reason), normalise_command(v.command))
            if key in seen:
                continue
            seen.add(key)
            buckets.setdefault(key, []).append((r, v))
    groups: list[RefusalGroup] = []
    for (prefix, reason, shape), members in buckets.items():
        # whole examples are preferred; a group that only has cut ones is marked so a
        # human supplies the full line rather than the product guessing the tail
        whole = sorted(
            {encode_corpus_line(v.command) for _, v in members if v.command and not v.truncated}
        )
        cut = sorted({encode_corpus_line(v.command) for _, v in members if v.truncated})
        examples = tuple((whole or cut)[:3])
        truncated = bool(cut) and not whole
        cand = examples[0] if examples else ""
        refused_prefix = prefix if prefix in CORPUS_REFUSED_PREFIXES else ""
        groups.append(
            RefusalGroup(
                group_id=_short_hash(prefix, reason, shape),
                prefix=prefix,
                reason=reason,
                shape=shape,
                n=len(members),
                cost_usd=sum(r.cost_usd for r, _ in members),
                minutes=sum(r.latency_s for r, _ in members) / 60.0,
                repos=tuple(sorted({r.repo for r, _ in members})),
                tasks=tuple(sorted({f"{r.repo}/{r.task_id[:10]}" for r, _ in members})),
                rows=tuple(sorted({_row_key(r) for r, _ in members})),
                examples=examples,
                truncated=truncated,
                candidate_honest=cand,
                candidate_refused=f"{cand}\t{refused_prefix}:" if cand and refused_prefix else "",
            )
        )
    groups.sort(key=lambda g: (-g.n, g.prefix, g.reason, g.shape))
    totals: dict[str, int] = {}
    protos: dict[str, int] = {}
    for r in rs:
        totals[r.apparatus_version] = totals.get(r.apparatus_version, 0) + 1
    for r in protocol:
        protos[r.apparatus_version] = protos.get(r.apparatus_version, 0) + 1
    return RefusalReport(
        groups=tuple(groups),
        rows_total=len(rs),
        rows_protocol=len(protocol),
        cost_usd=sum(r.cost_usd for r in protocol),
        minutes=sum(r.latency_s for r in protocol) / 60.0,
        unparsed=unparsed,
        apparatus_versions=tuple(sorted({r.apparatus_version for r in protocol})),
        by_apparatus=tuple((v, totals[v], protos.get(v, 0)) for v in sorted(totals)),
        row_stamps=tuple(sorted((_row_key(r), r.apparatus_version, r.created) for r in protocol)),
    )


def _row_key(row: GradeRow) -> str:
    """How a refusal group names a row: its chain hash, else its id (an unchained row)."""
    return row.row_hash or row.row_id


# --- the guard's false-positive rate, from the verdicts people recorded (G-536) ---------------


@dataclass(frozen=True)
class FalsePositivePeriod:
    """One apparatus version in one calendar month: its protocol rows split by what a person
    decided about the class each row fell into. ``honest`` rows are the guard's false
    positives; ``refuse`` rows it was right to refuse; ``undecided`` rows nobody has judged
    yet, and they are never counted as either verdict — the rate is a bound, not a point."""

    apparatus_version: str
    month: str
    rows_protocol: int
    honest: int
    refuse: int
    undecided: int

    @property
    def rate_low(self) -> float:
        """The false-positive rate if every undecided row turns out to be a right refusal."""
        return self.honest / self.rows_protocol if self.rows_protocol else 0.0

    @property
    def rate_high(self) -> float:
        """The false-positive rate if every undecided row turns out to be a false positive."""
        return (self.honest + self.undecided) / self.rows_protocol if self.rows_protocol else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "apparatus_version": self.apparatus_version,
            "month": self.month,
            "rows_protocol": self.rows_protocol,
            "honest": self.honest,
            "refuse": self.refuse,
            "undecided": self.undecided,
            "rate_low": round(self.rate_low, 4),
            "rate_high": round(self.rate_high, 4),
        }


@dataclass(frozen=True)
class FalsePositives:
    """The guard's false-positive rate over time: one :class:`FalsePositivePeriod` per
    (apparatus version, calendar month) of the protocol rows, versions in order and never
    blended, plus the totals across every period of the report."""

    periods: tuple[FalsePositivePeriod, ...]
    decided_groups: int
    undecided_groups: int
    #: undecided rows whose text named no class (``RefusalReport.unparsed``): no decision can
    #: ever reach them, so they keep the bound open whatever anyone decides
    unclassed: int = 0

    @property
    def rows_protocol(self) -> int:
        return sum(p.rows_protocol for p in self.periods)

    @property
    def honest(self) -> int:
        return sum(p.honest for p in self.periods)

    @property
    def refuse(self) -> int:
        return sum(p.refuse for p in self.periods)

    @property
    def undecided(self) -> int:
        return sum(p.undecided for p in self.periods)

    def to_dict(self) -> dict[str, Any]:
        return {
            "periods": [p.to_dict() for p in self.periods],
            "rows_protocol": self.rows_protocol,
            "honest": self.honest,
            "refuse": self.refuse,
            "undecided": self.undecided,
            "decided_groups": self.decided_groups,
            "undecided_groups": self.undecided_groups,
            "unclassed": self.unclassed,
            "note": (
                "a row is a false positive when a person decided its class honest (the guard "
                "was wrong), and a right refusal when they decided refuse; a row with several "
                "classes is a right refusal if any of them was decided refuse, and undecided "
                "while any is undecided. Undecided rows are never counted as either verdict, so "
                "the rate is served as a bound: honest ÷ protocol rows at least, (honest + "
                "undecided) ÷ protocol rows at most. Months are the month each row was graded."
            ),
        }


_MONTH_RE = re.compile(r"^\d{4}-\d{2}")


def _month_of(created: str) -> str:
    """``2026-09-14T…`` → ``2026-09``; a stamp that does not start with a date → ``unknown``."""
    m = _MONTH_RE.match(created or "")
    return m.group(0) if m else "unknown"


def guard_false_positives(
    report: RefusalReport, decisions: Iterable[Mapping[str, Any]]
) -> FalsePositives:
    """The guard's false-positive rate per apparatus version and calendar month, from the
    verdicts named people recorded (``learn.refusal.accepted``, oldest first; a later verdict
    on the same class replaces an earlier one).

    Pure and deterministic. A row's verdict is its classes' verdicts combined: ``refuse`` if
    any class was decided refuse (the guard was right to stop the row), else ``undecided`` if
    any class is undecided (or the row's text named no class), else ``honest`` — every class
    it fell into was decided a false positive. Nothing is inferred: an undecided row stays
    undecided and widens the bound instead of counting as either verdict."""
    verdict_of: dict[str, str] = {}
    for d in decisions:
        gid = str(d.get("group_id", "") or "")
        verdict = str(d.get("verdict", "") or "")
        if gid and verdict in (VERDICT_HONEST, VERDICT_REFUSE):
            verdict_of[gid] = verdict
    row_groups: dict[str, list[str]] = {}
    for g in report.groups:
        for key in g.rows:
            row_groups.setdefault(key, []).append(g.group_id)
    buckets: dict[tuple[str, str], list[int]] = {}
    unclassed = 0
    for key, version, created in report.row_stamps:
        verdicts = {verdict_of.get(gid, VERDICT_UNSURE) for gid in row_groups.get(key, ())}
        unclassed += not verdicts
        if VERDICT_REFUSE in verdicts:
            slot = 1
        elif not verdicts or VERDICT_UNSURE in verdicts:
            slot = 2
        else:
            slot = 0
        counts = buckets.setdefault((version, _month_of(created)), [0, 0, 0])
        counts[slot] += 1
    periods = tuple(
        FalsePositivePeriod(
            apparatus_version=version,
            month=month,
            rows_protocol=sum(c),
            honest=c[0],
            refuse=c[1],
            undecided=c[2],
        )
        for (version, month), c in sorted(
            buckets.items(), key=lambda kv: (_version_key(kv[0][0]), kv[0][0], kv[0][1])
        )
    )
    decided = sum(1 for g in report.groups if g.group_id in verdict_of)
    return FalsePositives(
        periods=periods,
        decided_groups=decided,
        undecided_groups=len(report.groups) - decided,
        unclassed=unclassed,
    )


# --- a human's decisions, applied ------------------------------------------------------


@dataclass(frozen=True)
class RefusalDecision:
    """One human verdict on one group. ``command`` overrides the candidate line (a
    truncated example completed by hand); ``prefix`` picks the refused-corpus label
    when the group's own prefix is not one the corpus takes (``tamper``/``other``)."""

    group_id: str
    verdict: str
    note: str = ""
    command: str = ""
    prefix: str = ""

    def __post_init__(self) -> None:
        if not self.group_id:
            raise LearnError("a decision needs a group_id")
        if self.verdict not in VERDICTS:
            raise LearnError(f"verdict {self.verdict!r} not in {VERDICTS}")
        if self.prefix and self.prefix not in CORPUS_REFUSED_PREFIXES:
            raise LearnError(f"prefix {self.prefix!r} not in {CORPUS_REFUSED_PREFIXES}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "verdict": self.verdict,
            "note": self.note,
            "command": self.command,
            "prefix": self.prefix,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> RefusalDecision:
        return cls(
            group_id=str(d.get("group_id", "")),
            verdict=str(d.get("verdict", "")),
            note=str(d.get("note", "") or ""),
            command=str(d.get("command", "") or ""),
            prefix=str(d.get("prefix", "") or ""),
        )


def load_decisions(d: Mapping[str, Any]) -> tuple[str, list[RefusalDecision]]:
    """``{"schema": …, "decided_by": <name>, "decisions": [...]}`` → (who, decisions).
    ``decided_by`` is REQUIRED: an accepted corpus line always carries a name."""
    if d.get("schema", DECISIONS_SCHEMA) != DECISIONS_SCHEMA:
        raise LearnError(f"decisions schema must be {DECISIONS_SCHEMA!r}")
    who = str(d.get("decided_by", "") or "").strip()
    if not who:
        raise LearnError("decisions need 'decided_by' — an accepted corpus line carries a name")
    items = d.get("decisions")
    if not isinstance(items, list):
        raise LearnError("decisions must be a list")
    return who, [RefusalDecision.from_dict(x) for x in items]


@dataclass(frozen=True)
class TriageApplied:
    """What :func:`apply_triage` wrote. ``skipped`` lists lines already present."""

    honest_added: tuple[str, ...]
    refused_added: tuple[str, ...]
    skipped: tuple[str, ...]
    unsure: tuple[str, ...]
    honest_path: str
    refused_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "honest_added": list(self.honest_added),
            "refused_added": list(self.refused_added),
            "skipped": list(self.skipped),
            "unsure": list(self.unsure),
            "honest_path": self.honest_path,
            "refused_path": self.refused_path,
        }


def _existing_lines(path: Path) -> set[str]:
    """The corpus lines already present (comments and blanks skipped)."""
    if not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def _provenance(group: RefusalGroup, *, verdict: str, who: str, date: str, note: str) -> str:
    """``# learned <date> from <repo>/<task> row <hash> (<verdict>→<who>) — <note>``."""
    where = ", ".join(group.tasks[:3]) + (" …" if len(group.tasks) > 3 else "")
    rows = ", ".join(h[:12] for h in group.rows[:3]) + (" …" if len(group.rows) > 3 else "")
    tail = f" — {one_line(note)}" if note else ""
    # the name and the note are free text inside a one-line comment (P-161)
    return f"# learned {date} from {where} row {rows} ({verdict}→{one_line(who)}){tail}"


def apply_triage(
    decisions: Sequence[RefusalDecision],
    report: RefusalReport,
    *,
    corpus_dir: str | Path,
    decided_by: str,
    date: str = "",
) -> TriageApplied:
    """Append the lines a human ACCEPTED to the corpora, each under a provenance comment.

    Validates every decision before writing anything (unknown group, truncated
    candidate without a supplied ``command``, a ``refuse`` on a prefix the refused
    corpus does not take), so a bad file changes nothing. ``unsure`` decisions are
    reported and never written. Idempotent: a line already present is skipped.
    The report's own verdicts are never consulted — only the decisions are.
    """
    who = decided_by.strip()
    if not who:
        raise LearnError("apply_triage needs decided_by")
    day = date or _dt.datetime.now(tz=_dt.UTC).date().isoformat()
    base = Path(corpus_dir)
    # what needs no file is refused before anything is touched, the directory included
    for d in decisions:
        g = report.get(d.group_id)
        if g is None:
            raise LearnError(f"decision {d.group_id}: no such group in the report")
        if d.verdict != VERDICT_UNSURE:
            _command_for(d, g)
    # the read, the other-corpus check and the append are one step: two deciders at once
    # (the HTTP write runs in a thread pool) must never both pass the check and put one
    # command in both corpora
    with _corpus_lock(base):
        return _apply_locked(decisions, report, base=base, who=who, day=day)


@contextlib.contextmanager
def _corpus_lock(base: Path) -> Iterator[None]:
    """An exclusive lock on the corpus directory for the length of one ``apply_triage``
    (``flock`` on the directory itself, so no lock file is left among the corpus files).
    Creating the directory is the only write it makes before a decision is validated."""
    base.mkdir(parents=True, exist_ok=True)
    fd = os.open(base, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)  # closing the descriptor releases the lock


def _command_for(d: RefusalDecision, g: RefusalGroup) -> str:
    """The corpus line a decision writes: the report's candidate, or — only for a class
    whose every recorded example was cut — the person's completion of that example. A
    ``command`` for a whole class, or one that does not continue a recorded cut example, is
    a different line from the one the rows refused, and is refused (a line nobody saw
    refused must never sit under the provenance of real rows)."""
    if not d.command:
        if g.truncated:
            raise LearnError(
                f"decision {d.group_id}: every recorded example was truncated by the "
                "recorder's cap; supply the full 'command'"
            )
        return g.candidate_honest
    if not g.truncated:
        raise LearnError(
            f"decision {d.group_id}: 'command' completes a class whose recorded examples were "
            "all truncated; this class is not truncated, so its line is the report's own"
        )
    cmd = encode_corpus_line(d.command)
    if not any(cmd.startswith(e) for e in g.examples if e):
        raise LearnError(
            f"decision {d.group_id}: 'command' must continue a recorded cut example "
            f"({', '.join(repr(e) for e in g.examples)}); it completes that line, never "
            "replaces it"
        )
    return cmd


def _apply_locked(
    decisions: Sequence[RefusalDecision],
    report: RefusalReport,
    *,
    base: Path,
    who: str,
    day: str,
) -> TriageApplied:
    """:func:`apply_triage`'s body, run under :func:`_corpus_lock`."""
    honest_path = base / CORPUS_HONEST_FILE
    refused_path = base / CORPUS_REFUSED_FILE
    honest_have = _existing_lines(honest_path)
    refused_have = {ln.partition("\t")[0] for ln in _existing_lines(refused_path)}
    # validate all first — nothing is written until every decision is sound
    planned: list[tuple[RefusalDecision, RefusalGroup, str]] = []
    unsure: list[str] = []
    for d in decisions:
        g = report.get(d.group_id)
        if g is None:
            raise LearnError(f"decision {d.group_id}: no such group in the report")
        if d.verdict == VERDICT_UNSURE:
            unsure.append(d.group_id)
            continue
        cmd = _command_for(d, g)
        if not cmd:
            raise LearnError(f"decision {d.group_id}: no command to append (supply 'command')")
        other = refused_have if d.verdict == VERDICT_HONEST else honest_have
        if cmd in other:
            raise LearnError(
                f"decision {d.group_id}: {cmd!r} is already in the OTHER corpus — a "
                "contradiction is moved by hand with a reason, never applied (the corpus rule: "
                "never weaken a refusal to make a line pass)"
            )
        if d.verdict == VERDICT_REFUSE:
            prefix = d.prefix or (g.prefix if g.prefix in CORPUS_REFUSED_PREFIXES else "")
            if not prefix:
                raise LearnError(
                    f"decision {d.group_id}: the refused corpus takes only "
                    f"{CORPUS_REFUSED_PREFIXES}; group prefix is {g.prefix!r} — supply 'prefix' "
                    "(a tamper is belt 1's, not the shell guard's)"
                )
            planned.append((d, g, f"{cmd}\t{prefix}:"))
        else:
            planned.append((d, g, cmd))
    honest_added: list[str] = []
    refused_added: list[str] = []
    skipped: list[str] = []
    for d, g, line in planned:
        cmd_only = line.partition("\t")[0]
        if cmd_only in honest_have or cmd_only in refused_have:
            skipped.append(line)
            continue
        block = (
            _provenance(g, verdict=d.verdict, who=who, date=day, note=d.note) + "\n" + line + "\n"
        )
        if d.verdict == VERDICT_HONEST:
            _append(honest_path, block)
            honest_have.add(cmd_only)
            honest_added.append(line)
        else:
            _append(refused_path, block)
            refused_have.add(cmd_only)
            refused_added.append(line)
    return TriageApplied(
        honest_added=tuple(honest_added),
        refused_added=tuple(refused_added),
        skipped=tuple(skipped),
        unsure=tuple(unsure),
        honest_path=str(honest_path),
        refused_path=str(refused_path),
    )


def _append(path: Path, block: str) -> None:
    """Append ``block`` on its own line (a corpus that lacks a final newline gets one)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    sep = "" if not existing or existing.endswith("\n") else "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(sep + block)


# ===========================================================================
# 2. Oracle-weak cells → strengthening backlog
# ===========================================================================

#: ``BacklogItem`` vocabulary mirrored from ``crb.factory.backlog`` (the core cannot
#: import the factory; ``tests/test_learn.py`` pins the mirror by round-tripping items
#: through ``BacklogItem.from_dict``).
BACKLOG_ITEM_KIND_CODE = "code"
BACKLOG_ITEM_LEVEL_L1 = "L1"
STRENGTHEN_CLASS = "test.add"
STRENGTHEN_ID_PREFIX = "strengthen-"


@dataclass(frozen=True)
class EscapedMutant:
    """One mutant the target tests did NOT kill, as the oracle run recorded it —
    the concrete thing a strengthening item asks a human to write a test for."""

    mutant_id: str
    op: str
    line: int
    path: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "mutant_id": self.mutant_id,
            "op": self.op,
            "line": self.line,
            "path": self.path,
            "description": self.description,
        }

    @property
    def label(self) -> str:
        """``path:line description`` — how the mutant is named in an item's text."""
        where = f"{self.path}:{self.line}" if self.path else f"line {self.line}"
        desc = self.description or self.op
        return f"{where} {desc}".strip()


@dataclass(frozen=True)
class OracleTaskScore:
    """One task's oracle score as the ledger/API carries it (``CommitOracleScore.
    to_dict()`` or an entry of ``to_report()["tasks"]``), reduced to what a
    strengthening item needs. ``escaped`` is the recorded list when the run kept
    it, else ``()`` with ``escaped_count`` still known."""

    task_id: str
    repo: str
    capability_class: str
    size: str
    strength: float | None
    total: int
    killed: int
    escaped_count: int
    escaped: tuple[EscapedMutant, ...]
    src_paths: tuple[str, ...]
    apparatus_version: str = ""

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> OracleTaskScore:
        """Tolerant of the three shapes the oracle emits (score dict, report entry,
        event payload); a score with no mutants is *unscoreable* (``strength=None``),
        never 0.0."""

        def _i(k: str, *alts: str) -> int:
            for key in (k, *alts):
                v = d.get(key)
                if isinstance(v, bool):
                    continue
                if isinstance(v, int | float):
                    return int(v)
            return 0

        raw = d.get("escaped_mutants")
        if not isinstance(raw, list):
            raw = [
                o
                for o in (d.get("outcomes") or [])
                if isinstance(o, Mapping)
                and (o.get("killed") is False or o.get("status") == "escaped")
            ]
        escaped = tuple(
            EscapedMutant(
                mutant_id=str(o.get("mutant_id", "")),
                op=str(o.get("op", "")),
                line=int(o.get("line", 0) or 0),
                path=str(o.get("path", "") or ""),
                description=str(o.get("description", "") or ""),
            )
            for o in raw
            if isinstance(o, Mapping)
        )
        total = _i("total", "mutants")
        killed = _i("killed")
        strength_raw = d.get("oracle_strength", d.get("strength"))
        strength = (
            float(strength_raw)
            if isinstance(strength_raw, int | float) and not isinstance(strength_raw, bool)
            else None
        )
        if total == 0:
            strength = None
        prov = d.get("provenance")
        apparatus = ""
        if isinstance(prov, Mapping):
            apparatus = str(prov.get("apparatus_version", "") or "")
        apparatus = apparatus or str(d.get("apparatus_version", "") or "")
        cell = str(d.get("cell", "") or "")
        cls_, _, size = cell.partition("/")
        return cls(
            task_id=str(d.get("task_id") or d.get("task") or ""),
            repo=str(d.get("repo", "") or ""),
            capability_class=str(d.get("capability_class") or cls_ or ""),
            size=str(d.get("size") or size or ""),
            strength=strength,
            total=total,
            killed=killed,
            escaped_count=_i("escaped") or (len(escaped) if escaped else max(0, total - killed)),
            escaped=escaped,
            src_paths=tuple(str(p) for p in (d.get("src_paths") or ())),
            apparatus_version=apparatus,
        )


def load_oracle_scores(obj: Any) -> list[OracleTaskScore]:
    """Accept a ``to_report()`` dict (``{"tasks": [...]}``), a list of per-task score
    dicts / ``oracle.score`` event payloads, or objects with ``to_dict()``."""
    if isinstance(obj, Mapping) and "tasks" in obj:
        obj = obj["tasks"]
    if isinstance(obj, Mapping):
        obj = [obj]
    out: list[OracleTaskScore] = []
    for item in obj or ():
        d = item.to_dict() if hasattr(item, "to_dict") else item
        if isinstance(d, Mapping):
            # an event envelope: the payload sits beside the task_id
            payload = d.get("payload")
            merged: dict[str, Any] = dict(payload) if isinstance(payload, Mapping) else dict(d)
            merged.setdefault("task_id", d.get("task_id", ""))
            s = OracleTaskScore.from_dict(merged)
            if s.task_id:
                out.append(s)
    out.sort(key=lambda s: (s.repo, s.capability_class, s.size, s.task_id))
    return out


def _task_in_cell(cell: CapabilityCell, score: OracleTaskScore) -> bool:
    """A scored task belongs to a cell when every PROJECTED field the score carries
    (class, size) matches; fields the score cannot carry (model, builder …) are
    not constraints — the strengthening work is the task's, whoever built it."""
    k = cell.key
    for f in cell.projection:
        want = getattr(k, f)
        if f == "capability_class" and score.capability_class and want != score.capability_class:
            return False
        if f == "size" and score.size and want != score.size:
            return False
    return True


@dataclass(frozen=True)
class StrengthenItem:
    """One backlog item in the factory's frozen-backlog shape (``BacklogItem``)."""

    id: str
    title: str
    description: str
    acceptance_criteria: tuple[str, ...]
    structural_facts: tuple[str, ...]
    labels: Mapping[str, str]
    registered: str
    kind: str = BACKLOG_ITEM_KIND_CODE
    capability_class: str = STRENGTHEN_CLASS
    size_estimate: str = "S"
    level: str = BACKLOG_ITEM_LEVEL_L1

    def __post_init__(self) -> None:
        object.__setattr__(self, "labels", dict(self.labels))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "kind": self.kind,
            "description": self.description,
            "acceptance_criteria": list(self.acceptance_criteria),
            "capability_class": self.capability_class,
            "size_estimate": self.size_estimate,
            "structural_facts": list(self.structural_facts),
            "depends_on": [],
            "level": self.level,
            "supersedes": "",
            "registered": self.registered,
            "labels": dict(self.labels),
        }


@dataclass(frozen=True)
class StrengthenBacklog:
    """Every strengthening item, with which cells were flagged and which of those had
    no per-task oracle score (and so got one cell-level item instead)."""

    items: tuple[StrengthenItem, ...]
    cells_flagged: tuple[str, ...]
    cells_without_scores: tuple[str, ...]
    threshold: float
    policy_version: str
    generated_at: str
    since: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": STRENGTHEN_SCHEMA,
            "generated_at": self.generated_at,
            "since": self.since,
            "threshold": self.threshold,
            "policy_version": self.policy_version,
            "cells_flagged": list(self.cells_flagged),
            "cells_without_scores": list(self.cells_without_scores),
            "items": [i.to_dict() for i in self.items],
            "note": (
                "items are proposals in the frozen-backlog shape; this derivation registers "
                "and builds nothing. A NAMED person pulls one into a sprint — "
                "`POST /learn/strengthen/register` registers the ones they choose (an "
                "evolution supersedes; the frozen record never mutates) and a factory run, "
                "queued separately, is what builds one"
            ),
        }

    def to_backlog_dict(self, *, repo: str = "") -> dict[str, Any]:
        """The ``Backlog.to_dict()`` shape (unfrozen) the factory can load and freeze."""
        return {
            "schema": "crb.backlog.v1",
            "repo": repo,
            "frozen_at": "",
            "backlog_hash": "",
            "items": [i.to_dict() for i in self.items],
            "evolutions": [],
            "evolutions_hash": "",
        }


def _fmt_strength(x: float | None) -> str:
    return "unscoreable" if x is None else f"{x:.2f}"


def _item_for_task(
    cell: CapabilityCell,
    score: OracleTaskScore,
    *,
    subject: str,
    threshold: float,
    registered: str,
) -> StrengthenItem:
    """One item per weak scored task: the escaped mutants become the acceptance
    criteria and the structural facts (subject under test, behaviour asserted) come
    from the ledger, so the DoR gate accepts the item without a value from the answer."""
    assert cell.decision is not None
    label = cell.label
    task_short = score.task_id[:10]
    who = f"{score.repo} {subject}" if subject else f"{score.repo} {task_short}"
    if score.escaped:
        mutants = "; ".join(m.label for m in score.escaped)
        escaped_text = f"mutants that escaped: {mutants}"
        asserted = "the target tests fail on each escaped mutant: " + "; ".join(
            m.label for m in score.escaped
        )
    else:
        escaped_text = (
            f"mutants that escaped: {score.escaped_count} of {score.total} "
            "(per-mutant diffs not recorded — re-run the oracle to list them)"
        )
        asserted = (
            f"the target tests kill the {score.escaped_count} mutant(s) that escaped "
            f"(of {score.total}); re-run the oracle for the per-mutant diffs"
        )
    subject_fact = "subject_under_test: " + (
        ", ".join(score.src_paths) if score.src_paths else f"the source changed by {task_short}"
    )
    strength = _fmt_strength(score.strength)
    return StrengthenItem(
        id=f"{STRENGTHEN_ID_PREFIX}{_short_hash(cell.key.label, score.repo, score.task_id)}",
        title=f"strengthen the target tests for {who}",
        description=(
            f"{escaped_text}. Cell {label} routes {cell.route} ({cell.reason_code}): "
            f"oracle strength {strength} for task {score.repo}/{task_short} "
            f"vs threshold {threshold:.2f}. {cell.reason}"
        ),
        acceptance_criteria=(
            "every listed escaped mutant is killed by the target tests (oracle re-run)",
            f"oracle strength for {score.repo}/{task_short} >= {threshold:.2f}",
            "only test files change (belt 1: the oracle is edited by a human, on purpose)",
        ),
        structural_facts=(subject_fact, "behaviour_asserted: " + asserted),
        labels={
            "source": "crb.core.learn",
            "cell": label,
            "reason_code": hold_reason(cell),
            "route": cell.route,
            "repo": score.repo,
            "task_id": score.task_id,
            "oracle_strength": strength,
            "threshold": f"{threshold:.2f}",
            "escaped": str(score.escaped_count),
            "mutants": str(score.total),
            "slots": "structural",
            "apparatus_version": score.apparatus_version,
        },
        registered=registered,
    )


def _item_for_cell(cell: CapabilityCell, *, threshold: float, registered: str) -> StrengthenItem:
    """The one item a held cell gets when no task of it has been scored: its first
    acceptance criterion is to run the oracle, so the flag is never dropped silently."""
    assert cell.stats is not None
    label = cell.label
    strength = _fmt_strength(cell.stats.oracle_strength_mean)
    return StrengthenItem(
        id=f"{STRENGTHEN_ID_PREFIX}{_short_hash(cell.key.label)}",
        title=f"strengthen the target tests for cell {label}",
        description=(
            f"mutants that escaped: not recorded per task for this cell (n={cell.n} rows, "
            f"mean oracle strength {strength} vs threshold {threshold:.2f}). Cell routes "
            f"{cell.route} ({cell.reason_code}): {cell.reason}. Run an 'oracle' run on the "
            "repo to list the escaped mutants per task."
        ),
        acceptance_criteria=(
            "an oracle run has scored every task in the cell",
            f"mean oracle strength for the cell >= {threshold:.2f}",
        ),
        structural_facts=(
            f"subject_under_test: the target tests of every task in cell {label}",
            "behaviour_asserted: the target tests kill the mutants the oracle run lists",
        ),
        labels={
            "source": "crb.core.learn",
            "cell": label,
            "reason_code": hold_reason(cell),
            "route": cell.route,
            "oracle_strength": strength,
            "threshold": f"{threshold:.2f}",
            "slots": "structural",
            "n": str(cell.n),
        },
        registered=registered,
    )


def _item_for_held_strong_cell(
    cell: CapabilityCell, *, threshold: float, registered: str
) -> StrengthenItem:
    """The one item a held cell gets when every scored task in it is strong: the routing
    rule holds it for its negative controls (an escape, or too few constructible), so the
    test work is to make the target tests refuse the cheat a control got through."""
    assert cell.stats is not None
    label = cell.label
    strength = _fmt_strength(cell.stats.oracle_strength_mean)
    return StrengthenItem(
        id=f"{STRENGTHEN_ID_PREFIX}{_short_hash(cell.key.label, 'controls')}",
        title=f"strengthen the target tests for cell {label}",
        description=(
            f"every scored task in cell {label} kills its mutants (mean oracle strength "
            f"{strength} vs threshold {threshold:.2f}), but the cell routes {cell.route} "
            f"({cell.reason_code}): {cell.reason}. A negative control the grader should refuse "
            "graded clean, so the target tests cannot tell an implementation from that cheat; "
            "the controls run on the repository lists which control escaped on which task."
        ),
        acceptance_criteria=(
            "a controls run on the repository reports 0 escapes for the tasks in the cell",
            f"mean oracle strength for the cell stays >= {threshold:.2f}",
            "only test files change (belt 1: the oracle is edited by a human, on purpose)",
        ),
        structural_facts=(
            f"subject_under_test: the target tests of every task in cell {label}",
            "behaviour_asserted: the target tests fail on the negative control that escaped",
        ),
        labels={
            "source": "crb.core.learn",
            "cell": label,
            "reason_code": hold_reason(cell),
            "route": cell.route,
            "oracle_strength": strength,
            "threshold": f"{threshold:.2f}",
            "slots": "structural",
            "n": str(cell.n),
        },
        registered=registered,
    )


def held_by_oracle(cell: CapabilityCell) -> bool:
    """Is the cell held by its oracle or its controls? routing.v2 lists EVERY clause a cell
    fails (``RouteDecision.shortfalls``), so a cell still waiting for its reading is flagged
    for strengthening work too — the oracle is measured before the commits are paid for."""
    d = cell.decision
    if d is None:
        return False
    return d.reason_code in STRENGTHEN_REASONS or any(
        s.code in STRENGTHEN_REASONS for s in d.shortfalls
    )


def oracle_by_task_of(
    scores: Iterable[OracleTaskScore | Mapping[str, Any]], *, apparatus: str = APPARATUS_VERSION
) -> dict[str, float]:
    """Each task's MINIMUM scoreable strength among ``scores`` — the CLI's twin of the
    server's per-task reduction (``crb.server.routes.oracle.oracle_by_task``), so ``crb learn
    strengthen`` routes the map on the same oracle the server does (ADR-0025 item 3: the rows'
    own column is never read). A score stamped with another apparatus is history and left out;
    an unstamped one (an export that carries no provenance) is read as the operator gave it."""
    out: dict[str, float] = {}
    for raw in scores:
        s = raw if isinstance(raw, OracleTaskScore) else OracleTaskScore.from_dict(raw)
        if s.strength is None or (s.apparatus_version and s.apparatus_version != apparatus):
            continue
        prior = out.get(s.task_id)
        out[s.task_id] = s.strength if prior is None else min(prior, s.strength)
    return out


def hold_reason(cell: CapabilityCell) -> str:
    """The oracle or controls clause that holds ``cell`` — its ``reason_code`` when that is one,
    else the first such shortfall — so an item names the work it is for, never a clause (the
    posture, a pending reading) no test can fix."""
    d = cell.decision
    if d is None or d.reason_code in STRENGTHEN_REASONS:
        return cell.reason_code
    return next((s.code for s in d.shortfalls if s.code in STRENGTHEN_REASONS), cell.reason_code)


def strengthening_backlog(
    cmap: CapabilityMap,
    oracle_scores: Iterable[OracleTaskScore | Mapping[str, Any]] = (),
    *,
    policy: RoutingPolicy = DEFAULT_POLICY,
    subjects: Mapping[str, str] | None = None,
    since: str = "",
    generated_at: str = "",
) -> StrengthenBacklog:
    """Turn every oracle-held cell of ``cmap`` into strengthening work.

    A cell is *oracle-held* when its decision's ``reason_code``, or any of its shortfalls, is
    one of :data:`STRENGTHEN_REASONS` (:func:`held_by_oracle`). For each, one item per scored
    task that belongs to the cell AND is weak (strength < ``policy.min_oracle_strength``, or
    unscoreable, or has escaped mutants); a held cell with no per-task score gets ONE cell-level
    item, and so does a held cell whose scored tasks are all strong (the controls hold it),
    so the flag is never dropped silently. ``since`` keeps only cells that
    carry evidence stamped with an apparatus ≥ ``since`` (and scores likewise, when
    stamped). ``generated_at`` is the ``registered`` stamp of every item — pass a
    fixed value for a byte-identical backlog. Item ids are ``sha(cell, repo, task)``
    so a re-run produces the same ids.
    """
    threshold = policy.min_oracle_strength
    when = generated_at or _dt.datetime.now(tz=_dt.UTC).isoformat(timespec="seconds")
    scores = [
        s if isinstance(s, OracleTaskScore) else OracleTaskScore.from_dict(s) for s in oracle_scores
    ]
    if since:
        floor = _version_key(since)
        scores = [
            s
            for s in scores
            if not s.apparatus_version or _version_key(s.apparatus_version) >= floor
        ]
    subj = dict(subjects or {})
    items: list[StrengthenItem] = []
    flagged: list[str] = []
    without: list[str] = []
    for cell in cmap.cells:
        if not held_by_oracle(cell):
            continue
        if since and cell.stats is not None:
            floor = _version_key(since)
            if not any(_version_key(v) >= floor for v in cell.stats.apparatus_versions):
                continue
        flagged.append(cell.label)
        matched = [s for s in scores if _task_in_cell(cell, s)]
        weak = [
            s
            for s in matched
            if s.strength is None or s.strength < threshold or s.escaped_count > 0
        ]
        if not matched:
            without.append(cell.label)
            items.append(_item_for_cell(cell, threshold=threshold, registered=when))
            continue
        for s in weak:
            items.append(
                _item_for_task(
                    cell,
                    s,
                    subject=subj.get(s.task_id, ""),
                    threshold=threshold,
                    registered=when,
                )
            )
        if not weak:
            # every scored task kills its mutants, yet the cell is held (a controls escape or
            # a thin control set): the work is the control, so the flag still becomes ONE item
            items.append(_item_for_held_strong_cell(cell, threshold=threshold, registered=when))
    items.sort(key=lambda i: (i.labels.get("cell", ""), i.labels.get("repo", ""), i.id))
    return StrengthenBacklog(
        items=tuple(items),
        cells_flagged=tuple(flagged),
        cells_without_scores=tuple(without),
        threshold=threshold,
        policy_version=policy.version,
        generated_at=when,
        since=since,
    )


# ===========================================================================
# 3. Apparatus change → re-measurement plan
# ===========================================================================

#: The ``kind`` a ``POST /runs`` body takes for each grade mode.
RUN_KIND_BY_MODE: Mapping[str, str] = {"sighted": "replay", "blind": "blind"}


@dataclass(frozen=True)
class RunRequest:
    """One ``POST /runs`` body (``crb.server.schemas.RunCreateRequest``) an operator
    could queue. ``task_ids`` names the commits a registered reading still needs before its
    next look; ``limit`` is their number. Never sent by this module."""

    repo: str
    kind: str
    mode: str
    builder: str
    model: str
    provider: str
    task_ids: tuple[str, ...]
    limit: int
    note: str = ""
    #: ``S1`` for a blind replay of the ``S1@<author>`` arm (``RunCreateRequest.arm``)
    arm: str = ""
    #: ``off`` opts the run out of the repository's loop switch, so its rows carry the arm
    #: the reading reads and not that arm ``+L`` (``RunCreateRequest.learning``)
    learning: str = ""

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "repo": self.repo,
            "kind": self.kind,
            "mode": self.mode,
            "builder": self.builder,
            "model": self.model,
            "provider": self.provider,
            "task_ids": list(self.task_ids),
            "limit": self.limit,
        }
        if self.arm:
            body["arm"] = self.arm
        if self.learning:
            body["learning"] = self.learning
        if self.note:
            body["note"] = self.note
        return body


#: Why a (cell, mode, arm) is in the plan. ``look_pending``: a reading registered at this
#: apparatus waits for first attempts — the only entry a top-up serves (ADR-0026 item 2).
#: ``stale`` / ``thin``: the cell has rows (older than the apparatus, or current) but no
#: reading at this apparatus, so none of them can count and the first act is to register one.
REASON_STALE = "stale"
REASON_THIN = "thin"
REASON_PENDING = "look_pending"
#: What an entry's next act is — the routing rule's own words (``crb.core.routing.NEXT_*``):
#: queue the reading's pending commits, register a reading first, or (``runs``) queue by hand
#: a run this plan cannot compose, because a replay it composed would write another arm.
NEXT_REPLAY = ROUTING_NEXT_REPLAY
NEXT_REGISTER = ROUTING_NEXT_REGISTER
NEXT_BY_HAND = "runs"
#: What an operator reads when a reading's pool is too small for its next look.
MINE_MORE = "mine more history"


@dataclass(frozen=True)
class RemeasureCell:
    """One entry of the plan: a (cell, mode, context arm) whose evidence cannot yet license it,
    why (``reason``), what to do next (``next_act``) and — for a registered reading waiting on
    its look — the commits it still needs, the runs that would grade them and their cost.

    ``n_current`` counts distinct commits, never attempts: for a reading, the commits its look
    has read (``ArmVerdict.counted`` — the number the Capability page shows); for a cell with no
    reading, the distinct changes with a first attempt at the running apparatus (information:
    none of them can count). ``n_needed`` is the reading's ``needed`` before its next look, or
    the rule's first look for a reading not yet registered."""

    cell: CellKey
    stale_versions: tuple[str, ...]
    n_stale: int
    n_current: int
    n_needed: int
    #: the MODE the arm is replayed in (sighted / blind): the map never pools the two
    mode: str
    tasks_stale: int
    tasks_current: int
    #: pending commits whose CURRENT label differs from this cell (their rows would land
    #: elsewhere); left out of the requests, listed here
    relabelled: tuple[str, ...]
    cost_usd_mean: float
    latency_s_mean: float
    est_cost_usd: float
    est_minutes: float
    cost_known: bool
    repos: tuple[str, ...]
    requests: tuple[RunRequest, ...]
    reason: str = REASON_PENDING
    #: the commits the requests ask for (the sum of their limits) — what the estimate prices
    n_requested: int = 0
    #: how many of ``n_needed`` no request asks for, and ``note`` says why
    short_by: int = 0
    note: str = ""
    #: ``replay`` (queue the requests), ``register`` (register a reading first) or ``runs``
    next_act: str = NEXT_REPLAY
    #: the context arm this entry is about: the reading's blocking arm, or the rows' own arm
    #: (``""`` for rows written before apparatus 2.4, which carry none)
    arm: str = ""
    reading_id: str = ""
    next_look: int | None = None

    @property
    def key(self) -> str:
        """``label|mode|arm`` — one entry per (cell, mode, arm), never two arms pooled."""
        return f"{self.cell.label}|{self.mode}|{self.arm}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell": self.cell.to_dict(),
            "label": self.cell.label,
            "key": self.key,
            "reason": self.reason,
            "next_act": self.next_act,
            "arm": self.arm,
            "reading_id": self.reading_id,
            "next_look": self.next_look,
            "stale_versions": list(self.stale_versions),
            "n_stale": self.n_stale,
            "n_current": self.n_current,
            "n_needed": self.n_needed,
            "n_requested": self.n_requested,
            "short_by": self.short_by,
            "mode": self.mode,
            "tasks_stale": self.tasks_stale,
            "tasks_current": self.tasks_current,
            "relabelled": list(self.relabelled),
            "cost_usd_mean": round(self.cost_usd_mean, 6),
            "latency_s_mean": round(self.latency_s_mean, 3),
            "est_cost_usd": round(self.est_cost_usd, 4),
            "est_minutes": round(self.est_minutes, 2),
            "cost_known": self.cost_known,
            "repos": list(self.repos),
            "requests": [r.to_dict() for r in self.requests],
            "note": self.note,
        }


@dataclass(frozen=True)
class CannotClear:
    """A cell whose registered reading has decided against it at this apparatus, so no
    further attempt on that reading can help: ``insufficient`` (its third miss — the look rule
    never re-reads it) or ``undecided`` (its pool is too small for the next look)."""

    label: str
    mode: str
    arm: str
    state: str
    reason: str
    next_act: str
    reading_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "mode": self.mode,
            "arm": self.arm,
            "state": self.state,
            "reason": self.reason,
            "next_act": self.next_act,
            "reading_id": self.reading_id,
        }


@dataclass(frozen=True)
class RemeasurePlan:
    """What the ledger and the registered readings imply: the entries to top up or register
    (with their requests), the readings that have delivered, the readings no further attempt
    can help, and the totals."""

    current_apparatus: str
    min_n: int
    policy_version: str
    cells: tuple[RemeasureCell, ...]
    #: ``label|arm`` of every cell whose reading at this apparatus has delivered (a standard,
    #: or the ceiling of an ``S3`` chain)
    up_to_date: tuple[str, ...]
    rows_total: int
    rows_stale: int
    cannot_clear: tuple[CannotClear, ...] = ()

    @property
    def pending(self) -> tuple[RemeasureCell, ...]:
        """The entries a top-up serves: registered readings waiting on their look."""
        return tuple(c for c in self.cells if c.reason == REASON_PENDING)

    @property
    def n_needed_total(self) -> int:
        """Commits the registered readings still need before their next looks."""
        return sum(c.n_needed for c in self.pending)

    @property
    def est_cost_usd_total(self) -> float:
        """Sum of the per-entry estimates (entries with no known cost contribute 0)."""
        return sum(c.est_cost_usd for c in self.cells)

    @property
    def est_minutes_total(self) -> float:
        """Sum of the per-entry latency estimates, serial."""
        return sum(c.est_minutes for c in self.cells)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": REMEASURE_SCHEMA,
            "current_apparatus": self.current_apparatus,
            "min_n": self.min_n,
            "policy_version": self.policy_version,
            "rows_total": self.rows_total,
            "rows_stale": self.rows_stale,
            "cells": [c.to_dict() for c in self.cells],
            "up_to_date": list(self.up_to_date),
            "cannot_clear": [x.to_dict() for x in self.cannot_clear],
            "summary": {
                "cells_pending": len(self.pending),
                "cells_stale": sum(1 for c in self.cells if c.reason == REASON_STALE),
                "cells_thin": sum(1 for c in self.cells if c.reason == REASON_THIN),
                "n_needed_total": self.n_needed_total,
                "n_requested_total": sum(c.n_requested for c in self.cells),
                "short_by_total": sum(c.short_by for c in self.pending),
                "est_cost_usd_total": round(self.est_cost_usd_total, 4),
                "est_minutes_total": round(self.est_minutes_total, 2),
                "cost_known_cells": sum(1 for c in self.pending if c.cost_known),
            },
            "note": (
                "requests are POST /runs bodies for an operator to queue; nothing here "
                "was sent (POST /learn/remeasure/queue sends one cell's, on an operator's "
                "instruction and with their identity on the runs). A cell is licensed only by "
                "a reading registered before its first attempt, and only rows graded after it "
                "count (ADR-0026 item 2), so a top-up asks only for the commits a registered "
                "reading still needs before its next look, in its seeded order; a cell with "
                "no reading at this apparatus (stale or thin) is offered registration, never a "
                "replay, because rows graded before a reading can never count and would make "
                "those commits unusable in one. One entry per (cell, mode, context arm) — never "
                "pooled. Costs are the cell's own mean row cost x the commits requested x up to "
                "the ladder's rungs for a blind cell (1 sighted) — an estimate, unknown where no "
                "row recorded a cost."
            ),
        }


def rows_to_clear_bar(clean: int, n: int, policy: RoutingPolicy, *, cap: int = 200) -> int:
    """The rule's FIRST look (20 distinct commits under ``look.v1``, ADR-0026 item 3): what a
    reading registered on a cell reads first — a reading is read only at its looks, so nothing
    short of the first can deliver, whatever the observed rate. (routing.v1 solved for the
    smallest n whose Wilson lower bound cleared 0.80 at the observed rate; the look rule
    replaced that bar.) ``clean`` and ``n`` are kept for the callers' shape; ``cap`` bounds a
    rule whose first look is larger."""
    del clean, n
    return min(*rule_looks(policy.rule), cap)


def _arm_request_blocker(
    arm: str, *, s1_author_model: str, posture: str, deployment_posture: str | None
) -> str:
    """Why a replay this plan composes could not write rows ``arm`` of a reading counts, or
    ``""`` when it can (P-602): ``S2`` is read on factory rows only; ``+facts`` / ``+library``
    are briefs a replay body cannot ask for; ``+L`` needs the repository's loop switch on,
    which a run can only opt out of; ``S1@<author>`` needs the deployment's test author to be
    that model; and every replayed arm counts only rows graded in the reading's posture."""
    a = parse_arm(arm)
    if a.base == BASE_S2:
        return (
            f"{arm} is read only on factory rows graded on held-out acceptance tests (ADR-0026 "
            "item 8): build this cell's tickets through the factory; a replay cannot write them"
        )
    if a.facts or a.library:
        return (
            f"{arm} carries structural facts or library entries a replay body cannot ask for: "
            "queue its runs from the Runs page with that brief"
        )
    if a.loop:
        return (
            f"{arm} counts only rows graded while the repository's loop switch is on, and a run "
            "can only opt out of it: queue its replay from the Runs page with the switch on"
        )
    if a.base == BASE_S1 and a.author != s1_author_model:
        told = s1_author_model or "not configured"
        return (
            f"{arm} counts only rows whose failing test {a.author} wrote; this deployment's "
            f"test author is {told}, so its rows would be another arm — queue a blind run with "
            f"arm S1 and test author {a.author} from the Runs page"
        )
    if deployment_posture is not None and deployment_posture != posture:
        return (
            f"the reading counts only rows graded in {posture}; this deployment grades in "
            f"{deployment_posture}, so a run here would write rows it can never count"
        )
    return ""


def _first_attempt_count(rows: Sequence[GradeRow]) -> int:
    """Distinct changes with a first attempt (``ledger.first_attempts``) — never attempts."""
    return len(first_attempts(rows))


def remeasure_plan(
    rows: Iterable[GradeRow],
    *,
    readings: Iterable[ReadingOutcome] = (),
    current_apparatus: str = APPARATUS_VERSION,
    policy: RoutingPolicy = DEFAULT_POLICY,
    task_labels: Mapping[str, tuple[str, str]] | None = None,
    gold_clean_tasks: Iterable[str] | None = None,
    blind_rungs: int = 3,
    s1_author_model: str = "",
    deployment_posture: str | None = None,
) -> RemeasurePlan:
    """What each cell needs before a reading at ``current_apparatus`` can license it.

    ``readings`` are the repository's registered readings, evaluated over the ledger
    (``ReadingBook.evaluate(...).outcomes``); the caller passes those of its own scope (checks
    arm, class-set version). Per cell the reading that speaks (``latest_outcome``) decides:

    * **waiting on its look** → a ``look_pending`` entry for the arm the hierarchy stopped at:
      ``n_current`` the commits its look has read, ``n_needed`` the commits still needed before
      the next look, and ONE request naming exactly those commits — the pool's first
      ``next_look`` in the seeded order with no observed first attempt graded after
      registration. A commit that is not gold-clean (``gold_clean_tasks``; the worker builds
      only those) or whose current label moved (``task_labels``) is left out and ``short_by``
      says so. No request at all when a replay could not write rows the reading counts
      (:func:`_arm_request_blocker` — ``next_act`` ``runs``).
    * **delivered** (a standard, or the ceiling of an ``S3`` chain) → ``up_to_date``.
    * **insufficient** or **undecided** → ``cannot_clear``, with the routing rule's words and
      next act (a new reading; mine further back).
    * **no reading at this apparatus** → one entry per (mode, context arm) of its rows,
      ``stale`` when all its rows predate the apparatus, else ``thin``, with ``next_act``
      ``register`` and no request: rows graded before a reading is registered never count, and
      a commit graded under an arm can no longer enter that arm's reading (``pool_seen``).

    Cost is the cell's own mean over rows of that mode that recorded one × the commits
    requested × ``blind_rungs`` for a blind request. Pure; deterministic; queues nothing.
    """
    rs = list(rows)
    cur = _version_key(current_apparatus)
    gold = frozenset(gold_clean_tasks) if gold_clean_tasks is not None else None
    first_look = min(rule_looks(policy.rule))
    stale_rows = sum(1 for r in rs if _version_key(r.apparatus_version) < cur)
    # the reading that speaks for each (repo, cell) at this apparatus
    by_cell: dict[tuple[str, str], list[ReadingOutcome]] = {}
    for o in readings:
        if o.reading.apparatus == current_apparatus:
            by_cell.setdefault((o.reading.repo, o.reading.cell_key), []).append(o)
    speaking = {k: latest_outcome(v) for k, v in by_cell.items()}
    plan: list[RemeasureCell] = []
    delivered: list[str] = []
    beyond: list[CannotClear] = []

    def costs_of(repo: str, cell_key: str, mode: str) -> tuple[list[float], list[float]]:
        same = [r for r in rs if r.repo == repo and r.cell.label == cell_key and r.mode == mode]
        return (
            [r.cost_usd for r in same if r.cost_known],
            [r.latency_s for r in same if r.latency_s > 0],
        )

    for (repo, _cell_key), outcome in sorted(speaking.items()):
        if outcome is None:
            continue
        reading = outcome.reading
        cell = CellKey(**{f: str(reading.cell.get(f, "")) for f in CELL_FIELDS})
        blocking = outcome.blocking
        if blocking is None or blocking.look.state == STATE_DELIVER:
            arm = outcome.standard or (outcome.chain[-1] if outcome.chain else "")
            delivered.append(f"{cell.label}|{arm}")
            continue
        arm = blocking.arm
        mode = REPLAY_MODE.get(parse_arm(arm).base, "")
        look = blocking.look
        if look.state != STATE_LOOK_PENDING:
            verdict = verdict_for(outcome, arm)
            if look.state == STATE_INSUFFICIENT:
                why = (
                    f"its reading read insufficient on {arm} at its third miss ({look.misses} "
                    f"of {look.counted} missed): the look rule never reads it again — a richer "
                    "arm in a new reading within the cell's budget, a split, or a person"
                )
                act = ROUTING_NEXT_NEW_READING
            else:
                why = (
                    f"its reading's pool ended before the look at {look.next_look} ("
                    f"{verdict.counted} read): {MINE_MORE} — new commits count here only in a "
                    f"new reading, once they are labelled {cell.capability_class} · "
                    f"{cell.size} and qualified"
                )
                act = ROUTING_NEXT_MINE
            beyond.append(
                CannotClear(cell.label, mode, arm, look.state, why, act, reading.reading_id)
            )
            continue
        kept = [c for c in blocking.commits if not c.left]
        pending = [c.commit for c in kept[: look.next_look or 0] if c.outcome is None]
        relabelled = [
            t
            for t in pending
            if task_labels is not None
            and t in task_labels
            and task_labels[t] != (cell.capability_class, cell.size)
        ]
        not_gold = [t for t in pending if gold is not None and t not in gold]
        askable = [t for t in pending if t not in relabelled and t not in not_gold]
        blocker = _arm_request_blocker(
            arm,
            s1_author_model=s1_author_model,
            posture=reading.posture_class,
            deployment_posture=deployment_posture,
        )
        requests: tuple[RunRequest, ...] = ()
        if askable and not blocker:
            requests = (
                RunRequest(
                    repo=repo,
                    kind=RUN_KIND_BY_MODE.get(mode, "replay"),
                    mode=mode,
                    builder=cell.builder,
                    model=cell.model,
                    provider=cell.provider,
                    task_ids=tuple(askable),
                    limit=len(askable),
                    arm=BASE_S1 if parse_arm(arm).base == BASE_S1 else "",
                    # a replay's rows carry +L when the repository's switch is on: the arm
                    # has none, so the run opts out and its rows are the arm the reading reads
                    learning="off",
                ),
            )
        n_requested = sum(r.limit for r in requests)
        notes: list[str] = []
        if blocker:
            notes.append(blocker)
        if not_gold:
            notes.append(
                f"{len(not_gold)} pending commit(s) are no longer gold-clean, and the worker "
                "builds only a gold-clean commit: re-qualify them, or the look waits"
            )
        if relabelled:
            notes.append(
                f"{len(relabelled)} pending commit(s) were relabelled out of this cell since "
                "the reading froze its pool, so their rows would land elsewhere"
            )
        costs, lats = costs_of(repo, cell.label, mode)
        cost_mean, lat_mean = mean(costs), mean(lats)
        per = blind_rungs if mode == "blind" else 1
        cell_rows = [r for r in rs if r.repo == repo and r.cell.label == cell.label]
        stale_here = [r for r in cell_rows if _version_key(r.apparatus_version) < cur]
        plan.append(
            RemeasureCell(
                cell=cell,
                stale_versions=tuple(sorted({r.apparatus_version for r in stale_here})),
                n_stale=len(stale_here),
                n_current=look.counted,
                n_needed=look.needed,
                mode=mode,
                tasks_stale=len({r.task_id for r in stale_here if r.task_id}),
                tasks_current=look.counted,
                relabelled=tuple(sorted(relabelled)),
                cost_usd_mean=cost_mean,
                latency_s_mean=lat_mean,
                est_cost_usd=cost_mean * n_requested * per,
                est_minutes=lat_mean * n_requested * per / 60.0,
                cost_known=bool(costs),
                repos=(repo,),
                requests=requests,
                reason=REASON_PENDING,
                n_requested=n_requested,
                short_by=look.needed - n_requested,
                note="; ".join(notes),
                next_act=NEXT_REPLAY if requests else NEXT_BY_HAND,
                arm=arm,
                reading_id=reading.reading_id,
                next_look=look.next_look,
            )
        )

    # cells with rows but no reading at this apparatus: register one first
    groups: dict[tuple[str, tuple[str, ...], str], list[GradeRow]] = {}
    for mode_name in sorted({r.mode for r in rs}):
        in_mode = [r for r in rs if r.mode == mode_name]
        for key, group in group_by_cell(in_mode, key_fields=CELL_FIELDS).items():
            for r in group:
                groups.setdefault((mode_name, key, r.context_arm), []).append(r)
    for (mode_name, key, arm), group in sorted(groups.items()):
        cell = CellKey(**dict(zip(CELL_FIELDS, key, strict=True)))
        repos = sorted({r.repo for r in group})
        if any((repo, cell.label) in speaking for repo in repos):
            continue  # the cell's reading speaks for it, whichever arm these rows are
        stale = [r for r in group if _version_key(r.apparatus_version) < cur]
        current = [r for r in group if _version_key(r.apparatus_version) >= cur]
        costs = [r.cost_usd for r in group if r.cost_known]
        lats = [r.latency_s for r in group if r.latency_s > 0]
        n_current = _first_attempt_count(current)
        reason = REASON_STALE if stale and not current else REASON_THIN
        plan.append(
            RemeasureCell(
                cell=cell,
                stale_versions=tuple(sorted({r.apparatus_version for r in stale})),
                n_stale=len(stale),
                n_current=n_current,
                n_needed=first_look,
                mode=mode_name,
                tasks_stale=len({r.task_id for r in stale if r.task_id}),
                tasks_current=n_current,
                relabelled=(),
                cost_usd_mean=mean(costs),
                latency_s_mean=mean(lats),
                est_cost_usd=0.0,
                est_minutes=0.0,
                cost_known=bool(costs),
                repos=tuple(repos),
                requests=(),
                reason=reason,
                n_requested=0,
                short_by=0,
                note=(
                    f"register a reading of this cell at apparatus {current_apparatus} first "
                    f"(crb reading register, or POST /readings): its first look reads "
                    f"{first_look} commits no arm of it has graded, and rows graded before a "
                    "reading is registered never count — so nothing is offered to replay until "
                    "one is"
                ),
                next_act=NEXT_REGISTER,
                arm=arm,
            )
        )
    plan.sort(key=lambda c: (c.cell.label, c.mode, c.arm))
    return RemeasurePlan(
        current_apparatus=current_apparatus,
        min_n=first_look,
        policy_version=policy.version,
        cells=tuple(plan),
        up_to_date=tuple(sorted(delivered)),
        rows_total=len(rs),
        rows_stale=stale_rows,
        cannot_clear=tuple(sorted(beyond, key=lambda x: (x.label, x.mode, x.arm))),
    )


# ===========================================================================
# Rendering (CLI text)
# ===========================================================================


def render_refusals(report: RefusalReport) -> str:
    """The triage as a markdown table, ending with how to write the decisions file."""
    lines = [
        "# Refusal triage",
        "",
        f"protocol rows: {report.rows_protocol}/{report.rows_total} "
        f"({report.instrument_share:.0%}) · ${report.cost_usd:.2f} · {report.minutes:.1f} min · "
        f"unparsed {report.unparsed} · apparatus {','.join(report.apparatus_versions) or '—'}",
        "",
        "| id | n | $ | min | prefix | reason | shape | verdict |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for g in report.groups:
        lines.append(
            f"| {g.group_id} | {g.n} | {g.cost_usd:.2f} | {g.minutes:.1f} | {g.prefix} | "
            f"{g.reason} | `{g.shape}` | {g.verdict}{' (truncated)' if g.truncated else ''} |"
        )
    if not report.groups:
        lines.append("| _(no protocol rows)_ | | | | | | | |")
    lines += [
        "",
        "every verdict is 'unsure' — write a decisions file "
        '({"decided_by": "<name>", "decisions": [{"group_id": …, "verdict": "honest"|"refuse"}]}) '
        "and run `crb learn refusals --apply <file>`",
    ]
    return "\n".join(lines)


def render_strengthen(backlog: StrengthenBacklog) -> str:
    """The backlog as a markdown table (id, title, cell, strength, escaped)."""
    lines = [
        "# Strengthening backlog (oracle-held cells → test work)",
        "",
        f"cells flagged: {len(backlog.cells_flagged)} · without per-task scores: "
        f"{len(backlog.cells_without_scores)} · items: {len(backlog.items)} · "
        f"threshold {backlog.threshold:.2f} · {backlog.policy_version}"
        + (f" · since {backlog.since}" if backlog.since else ""),
        "",
        "| id | title | cell | strength | escaped |",
        "|---|---|---|---|---|",
    ]
    for i in backlog.items:
        lines.append(
            f"| {i.id} | {i.title} | {i.labels.get('cell', '')} | "
            f"{i.labels.get('oracle_strength', '')} | {i.labels.get('escaped', '—')} |"
        )
    if not backlog.items:
        lines.append("| _(no oracle-held cells)_ | | | | |")
    lines += ["", "items are proposals; a human pulls one into a sprint — nothing is built here"]
    return "\n".join(lines)


def render_remeasure(plan: RemeasurePlan) -> str:
    """The plan as a markdown table, ``?`` where a cell's cost was never recorded."""
    register = sum(1 for c in plan.cells if c.next_act == NEXT_REGISTER)
    lines = [
        f"# Re-measurement and top-up plan — apparatus {plan.current_apparatus}",
        "",
        f"stale rows: {plan.rows_stale}/{plan.rows_total} · readings to top up: "
        f"{len(plan.pending)} · cells to register: {register} · commits needed: "
        f"{plan.n_needed_total} · est ${plan.est_cost_usd_total:.2f} · "
        f"est {plan.est_minutes_total:.0f} min · first look n={plan.min_n} "
        f"({plan.policy_version})",
        "",
        "| cell | mode | arm | reason | next | stale (tasks) | current commits | needed "
        "| requested | $/row | est $ |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in plan.cells:
        per = f"{c.cost_usd_mean:.2f}" if c.cost_known else "?"
        est = f"{c.est_cost_usd:.2f}" if c.cost_known else "?"
        moved = f", {len(c.relabelled)} relabelled" if c.relabelled else ""
        lines.append(
            f"| {c.cell.label} | {c.mode} | {c.arm or '—'} | {c.reason} | {c.next_act} | "
            f"{c.n_stale} ({','.join(c.stale_versions) or '—'}; {c.tasks_stale} tasks{moved}) | "
            f"{c.n_current} | {c.n_needed} | {c.n_requested} | {per} | {est} |"
        )
    if not plan.cells:
        lines.append("| _(nothing waits on a look or a registration)_ | | | | | | | | | | |")
    if plan.up_to_date:
        lines += ["", "delivered at this apparatus: " + ", ".join(plan.up_to_date)]
    for x in plan.cannot_clear:
        lines += ["", f"no top-up can help {x.label} ({x.arm}, {x.state}): {x.reason}"]
    lines += ["", "requests are POST /runs bodies for an operator to queue; nothing was sent"]
    return "\n".join(lines)


def dumps(obj: Mapping[str, Any]) -> str:
    """Canonical text of a report — the byte-identity tests compare this."""
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


__all__ = [
    "ATTEMPTED_CAP",
    "CORPUS_HONEST_FILE",
    "CORPUS_REFUSED_FILE",
    "CORPUS_REFUSED_PREFIXES",
    "DECISIONS_SCHEMA",
    "GUARD_PREFIXES",
    "LINE_BREAKS",
    "MINE_MORE",
    "NEXT_BY_HAND",
    "NEXT_REGISTER",
    "NEXT_REPLAY",
    "REASON_PENDING",
    "REASON_STALE",
    "REASON_THIN",
    "REFUSALS_SCHEMA",
    "REMEASURE_SCHEMA",
    "STRENGTHEN_REASONS",
    "STRENGTHEN_SCHEMA",
    "VERDICTS",
    "VERDICT_HONEST",
    "VERDICT_REFUSE",
    "VERDICT_UNSURE",
    "CannotClear",
    "EscapedMutant",
    "FalsePositivePeriod",
    "FalsePositives",
    "LearnError",
    "OracleTaskScore",
    "RefusalDecision",
    "RefusalGroup",
    "RefusalReport",
    "RemeasureCell",
    "RemeasurePlan",
    "RunRequest",
    "StrengthenBacklog",
    "StrengthenItem",
    "TriageApplied",
    "Violation",
    "apply_triage",
    "dumps",
    "encode_corpus_line",
    "guard_false_positives",
    "has_line_break",
    "load_decisions",
    "load_oracle_scores",
    "normalise_command",
    "normalise_reason",
    "one_line",
    "parse_violations",
    "remeasure_plan",
    "render_refusals",
    "render_remeasure",
    "render_strengthen",
    "row_violation_text",
    "rows_to_clear_bar",
    "strengthening_backlog",
    "triage_refusals",
]
