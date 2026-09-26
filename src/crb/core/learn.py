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
* :func:`remeasure_plan` — every cell whose evidence is stamped with an OLDER
  apparatus than the current one, with the ``n`` the routing rule needs, the cost
  that implies (that cell's own mean row cost × n) and the exact ``POST /runs``
  bodies an operator can queue. It queues nothing.

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
              costs them and proposes corpus lines whose verdict is always ``unsure``;
              turns every oracle-held cell into ``test.add`` backlog items with structural
              facts from the ledger; lists every cell with stale-apparatus evidence, the
              rows it needs to clear the rule's bars and the ``POST /runs`` bodies that
              would renew it. Writes only what a named human decided (``apply_triage``)
              and queues nothing.
How:          ``triage_refusals`` (``parse_violations`` → ``normalise_reason`` /
              ``normalise_command`` → ``RefusalGroup``) → a decisions file → ``apply_triage``
              (validate all, then append with provenance); ``strengthening_backlog`` (cells
              with an oracle reason code × ``OracleTaskScore``) → ``StrengthenItem``;
              ``remeasure_plan`` (rows per full cell by apparatus version →
              ``rows_to_clear_bar`` → ``RunRequest``).
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules (the loop itself:
              docs/LEARNING-LOOP.md#2-what-crbcorelearn-adds)
ADRs:         docs/adr/0003-one-routing-rule.md
Works with:   src/crb/core/ledger.py (the rows, failure kinds and cell grouping),
              src/crb/core/capability.py (the cells and their reason codes),
              src/crb/core/routing.py (the reasons and thresholds the derivations key on),
              src/crb/cli/commands/learn.py (``crb learn refusals|strengthen|remeasure``),
              src/crb/server/routes/learn.py (the same derivations over the store),
              src/crb/builders/base.py (the guard reasons parsed here; the corpus tests in
              tests/test_builders_guard_corpus.py consume what ``apply_triage`` writes),
              src/crb/factory/backlog.py (the BacklogItem shape strengthening items mirror)
Tested by:    tests/test_learn.py, tests/test_cli_learn.py, tests/test_server_routes_learn.py
Touch when:   never for a new repository; a new guard prefix, a new routing reason code or a
              change to ``BacklogItem`` must be mirrored here (the core cannot import the
              builders or the factory — tests/test_learn.py pins the mirrors); the human
              steps are deliberate (docs/LEARNING-LOOP.md#3-what-still-needs-a-human-and-why-that-is-deliberate)
              — nothing in this module may accept, build or queue on its own; the writes
              belong to src/crb/server/routes/learn.py, behind a named person.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crb.core.capability import CapabilityCell, CapabilityMap
from crb.core.ledger import (
    CELL_FIELDS,
    FAILURE_PROTOCOL,
    PROTOCOL_VIOLATION_PREFIX,
    CellKey,
    GradeRow,
    group_by_cell,
)
from crb.core.redact import redact
from crb.core.routing import (
    DEFAULT_POLICY,
    REASON_CONTROLS_ESCAPES,
    REASON_CONTROLS_THIN,
    REASON_ORACLE_WEAK,
    RoutingPolicy,
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


def encode_corpus_line(command: str) -> str:
    """A command as one corpus line (``\\n`` for a newline; secrets redacted)."""
    return redact(command.replace("\r\n", "\n")).replace("\n", "\\n").strip()


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
                rows=tuple(sorted({r.row_hash or r.row_id for r, _ in members})),
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
    tail = f" — {note}" if note else ""
    return f"# learned {date} from {where} row {rows} ({verdict}→{who}){tail}"


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
        cmd = encode_corpus_line(d.command) if d.command else g.candidate_honest
        if not cmd:
            raise LearnError(f"decision {d.group_id}: no command to append (supply 'command')")
        if g.truncated and not d.command:
            raise LearnError(
                f"decision {d.group_id}: every recorded example was truncated by the "
                "recorder's cap; supply the full 'command'"
            )
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
            "reason_code": cell.reason_code,
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
            "reason_code": cell.reason_code,
            "route": cell.route,
            "oracle_strength": strength,
            "threshold": f"{threshold:.2f}",
            "slots": "structural",
            "n": str(cell.n),
        },
        registered=registered,
    )


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

    A cell is *oracle-held* when its decision's ``reason_code`` is one of
    :data:`STRENGTHEN_REASONS`. For each, one item per scored task that belongs to
    the cell AND is weak (strength < ``policy.min_oracle_strength``, or unscoreable,
    or has escaped mutants); a held cell with no per-task score gets ONE cell-level
    item so the flag is never dropped silently. ``since`` keeps only cells that
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
        if cell.decision is None or cell.reason_code not in STRENGTHEN_REASONS:
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
    could queue. ``task_ids`` re-measures the SAME tasks that carried the stale rows;
    ``limit`` caps the run at what the rule still needs. Never sent by this module."""

    repo: str
    kind: str
    mode: str
    builder: str
    model: str
    provider: str
    task_ids: tuple[str, ...]
    limit: int
    note: str = ""

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
        if self.note:
            body["note"] = self.note
        return body


@dataclass(frozen=True)
class RemeasureCell:
    """One full cell with stale evidence: how many rows are stale / current, how many
    more the rule needs, what that costs at the cell's own rate, and the requests."""

    cell: CellKey
    stale_versions: tuple[str, ...]
    n_stale: int
    n_current: int
    n_needed: int
    #: the MODE this cell is planned for (sighted / blind): the map never pools the two,
    #: so neither does the plan — one entry per (cell, mode)
    mode: str
    #: distinct tasks the stale rows name (what a request can ask for by id) and distinct
    #: tasks behind the current rows — `n` counts attempts; both are shown so an operator
    #: sees when "more rows" would mean "the same commits again"
    tasks_stale: int
    tasks_current: int
    #: stale task ids whose CURRENT label differs from this cell (their new rows would land
    #: elsewhere); left out of the requests, listed here
    relabelled: tuple[str, ...]
    cost_usd_mean: float
    latency_s_mean: float
    est_cost_usd: float
    est_minutes: float
    cost_known: bool
    repos: tuple[str, ...]
    requests: tuple[RunRequest, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell": self.cell.to_dict(),
            "label": self.cell.label,
            "stale_versions": list(self.stale_versions),
            "n_stale": self.n_stale,
            "n_current": self.n_current,
            "n_needed": self.n_needed,
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
        }


@dataclass(frozen=True)
class RemeasurePlan:
    """The re-measurement an apparatus bump implies: the cells to renew (with their
    requests), the cells whose fresh evidence already suffices, and the totals."""

    current_apparatus: str
    min_n: int
    policy_version: str
    cells: tuple[RemeasureCell, ...]
    up_to_date: tuple[str, ...]
    rows_total: int
    rows_stale: int

    @property
    def n_needed_total(self) -> int:
        """Rows to grade across every stale cell."""
        return sum(c.n_needed for c in self.cells)

    @property
    def est_cost_usd_total(self) -> float:
        """Sum of the per-cell estimates (cells with no known cost contribute 0)."""
        return sum(c.est_cost_usd for c in self.cells)

    @property
    def est_minutes_total(self) -> float:
        """Sum of the per-cell latency estimates, serial."""
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
            "summary": {
                "cells_stale": len(self.cells),
                "n_needed_total": self.n_needed_total,
                "est_cost_usd_total": round(self.est_cost_usd_total, 4),
                "est_minutes_total": round(self.est_minutes_total, 2),
                "cost_known_cells": sum(1 for c in self.cells if c.cost_known),
            },
            "note": (
                "requests are POST /runs bodies for an operator to queue; nothing here "
                "was sent (POST /learn/remeasure/queue sends one cell's, on an operator's "
                "instruction and with their identity on the runs). One entry per (cell, mode) — sighted and blind are never pooled. "
                "Costs are that cell's own mean row cost x rows needed x attempts per row "
                "(1 sighted; the ladder's rungs blind) — an estimate, unknown where no row "
                "recorded a cost. tasks_stale / tasks_current say how many DISTINCT commits "
                "stand behind the rows: more rows on the same commits is not more evidence."
            ),
        }


def rows_to_clear_bar(clean: int, n: int, policy: RoutingPolicy, *, cap: int = 200) -> int:
    """The smallest N ≥ ``policy.min_n`` at which a cell that keeps its OBSERVED clean
    rate would clear the routing rule's Wilson-lower bar — the number a re-measurement
    must reach, not just ``min_n``. Three cobra/koa cells sat at 10–11/10–11 clean on
    2.2 and still read ``calibrate: ci_low_below_bar`` (2026-09-15): at 100 % the
    lower bound reaches 0.80 only from n = 16. A cell with no rows yet plans for the
    rate 1.0 (the optimistic case: the honest minimum). A rate that can never clear
    the point bar returns ``min_n`` — more rows will not help, and the plan says so
    through the cell's ``point``."""
    rate = (clean / n) if n else 1.0
    if rate < policy.min_point:
        return policy.min_n
    for total in range(max(policy.min_n, 1), cap + 1):
        ok = round(rate * total)
        if ok / total >= policy.min_point and wilson_interval(ok, total).low >= policy.min_ci_low:
            return total
    return cap


def remeasure_plan(
    rows: Iterable[GradeRow],
    *,
    current_apparatus: str = APPARATUS_VERSION,
    policy: RoutingPolicy = DEFAULT_POLICY,
    task_labels: Mapping[str, tuple[str, str]] | None = None,
    blind_rungs: int = 3,
) -> RemeasurePlan:
    """Cells whose evidence predates ``current_apparatus``, and what it takes to renew it.

    Per full cell (the unit a run request targets): ``n_current`` counts eligible
    rows stamped with the current apparatus; a cell is in the plan when it has
    stale rows and ``n_current`` is below the rows needed to clear the rule's bars at the
    observed rate (:func:`rows_to_clear_bar`); ``n_needed`` is the difference.
    Cost is the cell's own mean over rows that recorded one (``cost_known``
    says whether any did). Requests are one per (repo, mode) naming the stale
    rows' task ids (oldest-first ordering is the worker's), capped by ``limit``;
    when the known tasks are fewer than needed a second request asks for the
    remainder by ``limit`` alone. Pure; deterministic; queues nothing.

    Three defects the second decider pass found (2026-09-15) are closed here: the plan
    groups by **(cell, mode)** like the map (a blended sighted+blind rate hid koa's
    sighted cell under ``up_to_date``); a blind request is priced at **``blind_rungs``
    attempts** per task (a blind ladder climbs 25 → 50 → 100 tool calls; the old estimate
    of $26.53 was $50–76 in the ledger); and with ``task_labels`` — each task's CURRENT
    ``(capability_class, size)`` — a stale task whose label moved is left out of the
    request (its new rows would land in another cell) and named in ``relabelled``.
    """
    rs = list(rows)
    cur = _version_key(current_apparatus)
    plan: list[RemeasureCell] = []
    fresh: list[str] = []
    stale_rows = 0
    by_mode: dict[str, list[GradeRow]] = {}
    for r in rs:
        by_mode.setdefault(r.mode, []).append(r)
    groups: list[tuple[str, tuple[str, ...], list[GradeRow]]] = []
    for mode_name in sorted(by_mode):
        for key, group in sorted(group_by_cell(by_mode[mode_name], key_fields=CELL_FIELDS).items()):
            groups.append((mode_name, key, group))
    for mode_name, key, group in groups:
        cell = CellKey(**dict(zip(CELL_FIELDS, key, strict=True)))
        # "stale" is by apparatus version, never by date: evidence expires when the
        # instrument changes (EVIDENCE-AND-CLAIMS §4), not when it gets old
        stale = [r for r in group if _version_key(r.apparatus_version) < cur]
        current = [r for r in group if _version_key(r.apparatus_version) >= cur]
        stale_rows += len(stale)
        n_current = sum(1 for r in current if r.eligible)
        if not stale:
            continue
        clean_current = sum(1 for r in current if r.eligible and r.clean)
        target = rows_to_clear_bar(clean_current, n_current, policy)
        if n_current >= target:
            fresh.append(f"{cell.label}|{mode_name}")
            continue
        n_needed = target - n_current
        costs = [r.cost_usd for r in group if r.cost_usd > 0 and r.cost_known]
        lats = [r.latency_s for r in group if r.latency_s > 0]
        cost_mean = mean(costs)
        lat_mean = mean(lats)
        # a blind request climbs the ladder: every needed row may cost up to `blind_rungs`
        # attempts (each an attempt row of its own) — price what will actually be written
        attempts_per_row = blind_rungs if mode_name == "blind" else 1
        relabelled: list[str] = []
        requests: list[RunRequest] = []
        by_repo: dict[str, list[str]] = {}
        for r in stale:
            if task_labels is not None and r.task_id in task_labels:
                now_cls, now_size = task_labels[r.task_id]
                if (now_cls, now_size) != (cell.capability_class, cell.size):
                    relabelled.append(r.task_id)
                    continue
            by_repo.setdefault(r.repo, []).append(r.task_id)
        mode = mode_name
        for repo, ids in sorted(by_repo.items()):
            task_ids = tuple(sorted(set(ids)))[:n_needed]
            kind = RUN_KIND_BY_MODE.get(mode, "replay")
            requests.append(
                RunRequest(
                    repo=repo,
                    kind=kind,
                    mode=mode,
                    builder=cell.builder,
                    model=cell.model,
                    provider=cell.provider,
                    task_ids=task_ids,
                    limit=min(n_needed, len(task_ids)),
                )
            )
            if len(task_ids) < n_needed:
                requests.append(
                    RunRequest(
                        repo=repo,
                        kind=kind,
                        mode=mode,
                        builder=cell.builder,
                        model=cell.model,
                        provider=cell.provider,
                        task_ids=(),
                        limit=n_needed - len(task_ids),
                        note=(
                            "the stale rows name fewer tasks than the rule needs; this asks "
                            "the worker for the remainder by limit (oldest gold-clean tasks "
                            "first — may overlap the task_ids request)"
                        ),
                    )
                )
        plan.append(
            RemeasureCell(
                cell=cell,
                stale_versions=tuple(sorted({r.apparatus_version for r in stale})),
                n_stale=len(stale),
                n_current=n_current,
                n_needed=n_needed,
                mode=mode_name,
                tasks_stale=len({r.task_id for r in stale if r.task_id}),
                tasks_current=len({r.task_id for r in current if r.eligible and r.task_id}),
                relabelled=tuple(sorted(set(relabelled))),
                cost_usd_mean=cost_mean,
                latency_s_mean=lat_mean,
                est_cost_usd=cost_mean * n_needed * attempts_per_row,
                est_minutes=lat_mean * n_needed * attempts_per_row / 60.0,
                cost_known=bool(costs),
                repos=tuple(sorted({r.repo for r in stale})),
                requests=tuple(requests),
            )
        )
    return RemeasurePlan(
        current_apparatus=current_apparatus,
        min_n=policy.min_n,
        policy_version=policy.version,
        cells=tuple(plan),
        up_to_date=tuple(fresh),
        rows_total=len(rs),
        rows_stale=stale_rows,
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
    lines = [
        f"# Re-measurement plan — apparatus {plan.current_apparatus}",
        "",
        f"stale rows: {plan.rows_stale}/{plan.rows_total} · cells to renew: {len(plan.cells)} · "
        f"n needed: {plan.n_needed_total} · est ${plan.est_cost_usd_total:.2f} · "
        f"est {plan.est_minutes_total:.0f} min · rule n≥{plan.min_n} ({plan.policy_version})",
        "",
        "| cell | mode | stale (tasks) | current (tasks) | needed | $/row | est $ | requests |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in plan.cells:
        per = f"{c.cost_usd_mean:.2f}" if c.cost_known else "?"
        est = f"{c.est_cost_usd:.2f}" if c.cost_known else "?"
        moved = f", {len(c.relabelled)} relabelled" if c.relabelled else ""
        lines.append(
            f"| {c.cell.label} | {c.mode} | {c.n_stale} ({','.join(c.stale_versions)}; "
            f"{c.tasks_stale} tasks{moved}) | {c.n_current} ({c.tasks_current} tasks) | "
            f"{c.n_needed} | {per} | {est} | {len(c.requests)} |"
        )
    if not plan.cells:
        lines.append("| _(nothing stale)_ | | | | | | | |")
    if plan.up_to_date:
        lines += ["", "already renewed: " + ", ".join(plan.up_to_date)]
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
    "REFUSALS_SCHEMA",
    "REMEASURE_SCHEMA",
    "STRENGTHEN_REASONS",
    "STRENGTHEN_SCHEMA",
    "VERDICTS",
    "VERDICT_HONEST",
    "VERDICT_REFUSE",
    "VERDICT_UNSURE",
    "EscapedMutant",
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
    "load_decisions",
    "load_oracle_scores",
    "normalise_command",
    "normalise_reason",
    "parse_violations",
    "remeasure_plan",
    "render_refusals",
    "render_remeasure",
    "render_strengthen",
    "row_violation_text",
    "strengthening_backlog",
    "triage_refusals",
]
