"""Registered readings: the look rule, the seeded order, the hierarchy, one error budget per cell.

ADR-0026 items 2 to 5 (as they amend ADR-0025): a cell is licensed only by a **reading**
registered before its first attempt — the cell, the hierarchy of context arms it decides
between (richest first), any descriptive arms and their fixed counts, the rule, the share of
the cell's error budget it spends, the test author's model and the **frozen pool** of
qualified commits with its SHA-256. Only rows graded after registration count.

* **The seeded order** is normative: the pool is read in ascending
  ``sha256("crb.reading.v1|" + repo + "|" + canonical cell key + "|" + commit)`` — one order
  per cell, shared by every arm, so the arms are paired and no run incident reorders a look.
  The canonical cell key is :func:`canonical_cell_key` — the seven ``CELL_FIELDS`` values
  joined by ``|`` in ``CELL_FIELDS`` order.
* **Counting.** Within a reading a commit counts once, by its first observed attempt among
  rows graded after registration, at rung ``r1``; for a replayed arm only in the sealed
  posture (the builder in the sealed container, the tests in the docker sandbox); for ``S2``
  only on factory rows stamped as graded on held-out acceptance tests. Two commits of one
  change (a cherry-pick, a revert and its original — ``labels.change_id``) count once: the
  first in the seeded order. A commit with no observed attempt is ``pending`` and the look
  waits; a commit the instrument cannot grade (no observed attempt after the re-runs the
  reading allows, gold not clean, or belt 5 switched off by configuration) leaves the pool with
  its reason recorded, and the next commit in the order takes its place — an instrument
  failure is never a miss.
* **The look rule** (:data:`RULES`): an arm is read only at its looks. ``look.v1`` delivers at
  20 of the first 20, 29 of the first 30 or 38 of the first 40 clean, reads ``insufficient``
  at its third miss, ``undecided`` when the pool cannot reach the next look, and
  ``look_pending`` with the commits still needed otherwise. :func:`p_deliver` is the exact
  dynamic programme over Bernoulli draws that gives each rule's operating characteristic.
* **The hierarchy.** Arms are read in the registered order and reading stops at the first
  arm that does not deliver; the standard is the leanest certifying arm in the unbroken chain.
  ``S3`` alone is a ``ceiling``; only the ``S1`` family and ``S2`` certify; ``A0`` and
  ``A0+L`` are descriptive and spend nothing.
* **The budget.** One error budget per (repository, cell key, apparatus, class-set version),
  :data:`CELL_ERROR_BUDGET` unless the operator fixed another value; every registration spends
  its rule's P(deliver | 0.80) and is refused ``budget_spent`` when it would overspend.

Navigation
----------
What it is:   The reading — registration (``register`` → a ``Reading`` the caller writes as a
              ``reading.registered`` event), the seeded order, the look rule and its exact
              operating characteristic, the counting of first observed attempts per distinct
              change, the hierarchy that finds a cell's standard, and the per-cell budget.
What it does: Freezes a pool by a rule blind to outcomes (``pool_by_rule``; a hand-picked
              list is ``pool_not_blind``); refuses a registration over commits already graded
              under its arms at its apparatus (``pool_seen``), beyond the cell's budget
              (``budget_spent``) or outside the arm rules; evaluates each arm of a reading over
              the ledger's rows in the seeded order; stops the hierarchy at the first arm that
              does not deliver; names the standard, a ceiling or no proven standard, and the
              commits still needed.
How:          ``seeded_order`` sorts the pool by its SHA-256 preimage; ``arm_reading`` walks it,
              taking each commit's first observed ``r1`` attempt this deployment graded after
              registration on the reading's checks arm (never an imported row) →
              ``look_state`` applies the rule → ``evaluate`` reads the hierarchy →
              ``standard_of`` answers the factory's gate on one checks arm and posture class.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0026-the-context-standard.md (items 2 to 6),
              docs/adr/0025-routing-v2.md (items 1, 2 and 8 as ADR-0026 amends them)
Works with:   src/crb/core/context_arm.py (the arms a hierarchy names),
              src/crb/core/ledger.py (the rows; ``GradeRow.context_arm``, ``taxonomy``,
              ``change_id``, ``sealed``), src/crb/core/routing.py (routes a cell on its
              reading), src/crb/core/capability.py (serves every arm's reading),
              src/crb/core/signoff.py (a sign-off stamps the reading's id),
              src/crb/server/routes/readings.py (the events store and ``POST /readings``),
              src/crb/cli/commands/reading.py (``crb reading register``)
Tested by:    tests/test_reading.py, tests/test_routing_v2.py, tests/test_server_readings.py
Touch when:   never for a new repository; a rule is added (a row in ``RULES`` with its exact
              P(deliver | 0.80) — an ADR amending ADR-0026 item 5 first); the counting rule changes
              (an apparatus bump); the operator fixes another budget
              (``CRB_READING__CELL_ERROR_BUDGET``); never for a new repository.
Claims:       A reading bounds the chance of certifying a cell whose true first-attempt rate is
              0.80 by its rule's P(deliver | 0.80); it says nothing about correctness or
              working software (docs/EVIDENCE-AND-CLAIMS.md).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from crb.core.context_arm import BASE_S2, parse_arm
from crb.core.evidence import canonical_json, sha256_text, utc_now_iso
from crb.core.ledger import CELL_FIELDS, FAILURE_HARNESS, FAILURE_OUTAGE, LABEL_HELD_OUT
from crb.core.stats import Interval, wilson_interval

if TYPE_CHECKING:
    from crb.core.ledger import CellKey, GradeRow

READING_SCHEMA = "crb.reading.v1"
#: The event a registration is written as (stage ``system``).
READING_EVENT_ACTION = "reading.registered"
#: The prefix of the seeded order's preimage (ADR-0026 item 2).
SEED_PREFIX = "crb.reading.v1|"

#: The one rung a reading counts (ADR-0026 item 2): the first attempt of the ladder.
RUNG_R1 = "r1"

#: The rules a reading may register: look size → the misses allowed at that look.
RULE_LOOK_V1 = "look.v1"
RULE_LOOK_V1_STRICT = "look.v1-strict"
RULE_LOOK_V1_LATE = "look.v1-late"
RULES: Mapping[str, Mapping[int, int]] = {
    RULE_LOOK_V1: {20: 0, 30: 1, 40: 2},
    RULE_LOOK_V1_STRICT: {20: 0, 30: 0, 40: 1},
    RULE_LOOK_V1_LATE: {30: 0, 40: 1},
}
#: The rate a false certification is judged at (ADR-0026 item 3).
NULL_RATE = 0.80

#: One error budget per cell (ADR-0026 item 5; the operator's value — 2.5% is the stricter
#: choice). A deployment may tighten it through the environment, never loosen it.
CELL_ERROR_BUDGET = 0.05
BUDGET_ENV = "CRB_READING__CELL_ERROR_BUDGET"
#: A harness row is re-run before its look is read; after this many unobserved ``r1`` attempts
#: the commit leaves the pool (``harness``) instead of waiting for ever.
DEFAULT_MAX_RERUNS = 2

# --- arm states -----------------------------------------------------------------
STATE_DELIVER = "deliver"
STATE_INSUFFICIENT = "insufficient"
STATE_UNDECIDED = "undecided"
STATE_LOOK_PENDING = "look_pending"
STATE_DESCRIPTIVE = "descriptive"
#: A hierarchy arm that is never read because a richer arm did not deliver.
STATE_STOPPED = "stopped"
ARM_STATES: tuple[str, ...] = (
    STATE_DELIVER,
    STATE_INSUFFICIENT,
    STATE_UNDECIDED,
    STATE_LOOK_PENDING,
    STATE_DESCRIPTIVE,
    STATE_STOPPED,
)
# --- a reading's outcome (the cell's) -------------------------------------------
OUTCOME_STANDARD = "standard"
OUTCOME_CEILING = "ceiling"
OUTCOME_LOOK_PENDING = STATE_LOOK_PENDING
OUTCOME_INSUFFICIENT = STATE_INSUFFICIENT
OUTCOME_UNDECIDED = STATE_UNDECIDED

# --- why a commit left the pool --------------------------------------------------
LEFT_SAME_CHANGE = "same_change"
LEFT_HARNESS = "harness"
LEFT_GOLD = "gold_not_clean"
LEFT_LINT_DISABLED = "lint_disabled"
LEFT_UNOBSERVED = "unobserved"

# --- registration refusals ---------------------------------------------------------
REFUSAL_POOL_SEEN = "pool_seen"
REFUSAL_BUDGET_SPENT = "budget_spent"
REFUSAL_INVALID = "invalid_reading"
#: A pool named as a list the pool rule does not give (DL-097, P-320).
REFUSAL_POOL_NOT_BLIND = "pool_not_blind"
REFUSAL_CODES: tuple[str, ...] = (
    REFUSAL_POOL_SEEN,
    REFUSAL_BUDGET_SPENT,
    REFUSAL_INVALID,
    REFUSAL_POOL_NOT_BLIND,
)

# --- the pool rule (DL-097) --------------------------------------------------------------
#: Every qualified commit of the cell.
POOL_RULE_ALL = "all-qualified"
#: Every qualified commit of the cell authored at or after a date (``qualified-since:<iso>``).
POOL_RULE_SINCE = "qualified-since"


class ReadingRefused(ValueError):
    """A registration the rules refuse — ``code`` is one of :data:`REFUSAL_CODES`."""

    def __init__(self, message: str, *, code: str, detail: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.detail = dict(detail or {})


# ---------------------------------------------------------------------------
# The look rule
# ---------------------------------------------------------------------------


def rule_looks(rule: str) -> Mapping[int, int]:
    """The looks of ``rule`` (look size → misses allowed); refuses an unregistered rule."""
    if rule not in RULES:
        raise ValueError(f"unknown look rule {rule!r}; expected one of {sorted(RULES)}")
    return RULES[rule]


def p_deliver(rule: str, p: float, *, pool: int | None = None) -> float:
    """The exact probability that ``rule`` reads ``deliver`` when every commit is clean with
    probability ``p``, by dynamic programme over the draws (no sampling): the state is the
    misses so far; a path stops ``deliver`` at a look it meets and ``insufficient`` once its
    misses exceed the last look's allowance. ``pool`` defaults to the last look's size."""
    looks = rule_looks(rule)
    last_n = max(looks)
    last_m = looks[last_n]
    n_max = pool if pool is not None else last_n
    states: dict[int, float] = {0: 1.0}
    delivered = 0.0
    for n in range(1, n_max + 1):
        nxt: dict[int, float] = {}
        for misses, pr in states.items():
            for clean, q in ((True, p), (False, 1.0 - p)):
                m2 = misses + (0 if clean else 1)
                pr2 = pr * q
                if m2 > last_m:
                    continue  # insufficient
                if n in looks and m2 <= looks[n]:
                    delivered += pr2
                    continue
                nxt[m2] = nxt.get(m2, 0.0) + pr2
        states = nxt
    return delivered


def rule_spend(rule: str) -> float:
    """What a reading under ``rule`` spends of its cell's budget: P(deliver | 0.80)."""
    return p_deliver(rule, NULL_RATE)


@dataclass(frozen=True)
class LookState:
    """One arm's reading under a rule, from its outcomes in the seeded order."""

    state: str
    counted: int  # the commits read, in order, before the first pending one (or the decision)
    clean: int
    misses: int
    next_look: int | None  # the look the arm waits for (``None`` once decided)
    needed: int  # commits still to observe before that look can be read
    decided_at: int | None = None

    @property
    def ci(self) -> Interval:
        return wilson_interval(self.clean, self.counted)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "counted": self.counted,
            "clean": self.clean,
            "misses": self.misses,
            "ci_low": round(self.ci.low, 4),
            "ci_high": round(self.ci.high, 4),
            "next_look": self.next_look,
            "needed": self.needed,
            "decided_at": self.decided_at,
        }


def look_state(outcomes: Sequence[bool | None], rule: str) -> LookState:
    """Apply ``rule`` to ``outcomes`` — one entry per commit still in the pool, in the seeded
    order: ``True`` clean, ``False`` a miss, ``None`` pending (no observed attempt yet).

    The walk reads commits in order and stops at the first pending one, so a decision rests
    only on a contiguous prefix whose first attempts can never change. It stops
    ``insufficient`` at the miss that puts the last look out of reach and ``deliver`` at the
    first look it meets. Otherwise the next reachable look is ``look_pending`` with the
    commits among its first ``n`` still pending — or ``undecided`` when the pool holds fewer
    commits than that look needs.
    """
    looks = rule_looks(rule)
    last_m = looks[max(looks)]
    misses = clean = k = 0
    for o in outcomes:
        if o is None:
            break
        k += 1
        if o:
            clean += 1
        else:
            misses += 1
        if misses > last_m:
            return LookState(STATE_INSUFFICIENT, k, clean, misses, None, 0, decided_at=k)
        if k in looks and misses <= looks[k]:
            return LookState(STATE_DELIVER, k, clean, misses, None, 0, decided_at=k)
    reachable = [n for n in sorted(looks) if n > k and misses <= looks[n]]
    nxt = reachable[0]  # the last look stays reachable while misses ≤ its allowance
    if len(outcomes) < nxt:
        return LookState(STATE_UNDECIDED, k, clean, misses, nxt, nxt - len(outcomes), None)
    needed = sum(1 for o in outcomes[:nxt] if o is None)
    return LookState(STATE_LOOK_PENDING, k, clean, misses, nxt, needed, None)


# ---------------------------------------------------------------------------
# The seeded order
# ---------------------------------------------------------------------------


def canonical_cell_key(cell: CellKey | Mapping[str, str]) -> str:
    """The cell key the seeded order hashes: the seven ``CELL_FIELDS`` values joined by
    ``|`` in ``CELL_FIELDS`` order (``CellKey.label``)."""
    d = cell.to_dict() if hasattr(cell, "to_dict") else dict(cell)
    return "|".join(str(d.get(f, "")) for f in CELL_FIELDS)


def seed_of(repo: str, cell_key: str, commit: str) -> str:
    """``sha256("crb.reading.v1|" + repo + "|" + canonical cell key + "|" + commit)``."""
    preimage = SEED_PREFIX + repo + "|" + cell_key + "|" + commit
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()


def seeded_order(repo: str, cell_key: str, pool: Iterable[str]) -> list[str]:
    """The pool in ascending seed order (ADR-0026 item 2) — one order per cell."""
    return sorted(set(pool), key=lambda c: (seed_of(repo, cell_key, c), c))


# ---------------------------------------------------------------------------
# The reading record
# ---------------------------------------------------------------------------


def _parse_ts(ts: str) -> _dt.datetime | None:
    try:
        d = _dt.datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return d if d.tzinfo is not None else d.replace(tzinfo=_dt.UTC)


@dataclass(frozen=True)
class Reading:
    """One registered reading — the ``reading.registered`` event's payload."""

    repo: str
    cell: Mapping[str, str]
    apparatus: str
    taxonomy: str
    posture_class: str
    checks_arm: str
    hierarchy: tuple[str, ...]
    rule: str
    spend: float
    pool: tuple[str, ...]  # in the seeded order
    pool_sha256: str
    registered_at: str
    actor: str
    budget: float
    descriptive: tuple[tuple[str, int], ...] = ()
    author_model: str = ""
    changes: Mapping[str, str] = field(default_factory=dict)
    max_reruns: int = DEFAULT_MAX_RERUNS
    schema: str = READING_SCHEMA
    reading_id: str = ""
    #: The rule the pool was frozen by (:func:`pool_by_rule`); ``""`` for a pool a caller of
    #: the core supplied directly (tests, the in-code programme) — hashed when present.
    pool_rule: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "cell", dict(self.cell))
        object.__setattr__(self, "changes", dict(self.changes))
        object.__setattr__(self, "hierarchy", tuple(self.hierarchy))
        object.__setattr__(self, "pool", tuple(self.pool))
        object.__setattr__(
            self, "descriptive", tuple((str(a), int(n)) for a, n in self.descriptive)
        )
        if not self.reading_id:
            object.__setattr__(
                self, "reading_id", "rdg_" + sha256_text(canonical_json(self.body()))[:24]
            )

    @property
    def cell_key(self) -> str:
        return canonical_cell_key(self.cell)

    @property
    def budget_key(self) -> tuple[str, str, str, str]:
        """What one error budget is kept per (ADR-0026 item 5)."""
        return (self.repo, self.cell_key, self.apparatus, self.taxonomy)

    @property
    def arms(self) -> tuple[str, ...]:
        """Every arm the reading reads: the hierarchy, then the descriptive arms."""
        return (*self.hierarchy, *(a for a, _ in self.descriptive))

    @property
    def registered(self) -> _dt.datetime | None:
        return _parse_ts(self.registered_at)

    def body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "repo": self.repo,
            "cell": dict(self.cell),
            "apparatus": self.apparatus,
            "taxonomy": self.taxonomy,
            "posture_class": self.posture_class,
            "checks_arm": self.checks_arm,
            "hierarchy": list(self.hierarchy),
            "descriptive": [[a, n] for a, n in self.descriptive],
            "rule": self.rule,
            "spend": self.spend,
            "budget": self.budget,
            "author_model": self.author_model,
            "pool": list(self.pool),
            "pool_sha256": self.pool_sha256,
            "changes": dict(sorted(self.changes.items())),
            "max_reruns": self.max_reruns,
            "registered_at": self.registered_at,
            "actor": self.actor,
            **({"pool_rule": self.pool_rule} if self.pool_rule else {}),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.body(), "reading_id": self.reading_id}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Reading:
        return cls(
            repo=str(d.get("repo", "")),
            cell={str(k): str(v) for k, v in dict(d.get("cell") or {}).items()},
            apparatus=str(d.get("apparatus", "")),
            taxonomy=str(d.get("taxonomy", "")),
            posture_class=str(d.get("posture_class", "")),
            checks_arm=str(d.get("checks_arm", "")),
            hierarchy=tuple(str(a) for a in d.get("hierarchy") or ()),
            rule=str(d.get("rule", "")),
            spend=float(d.get("spend", 0.0) or 0.0),
            pool=tuple(str(c) for c in d.get("pool") or ()),
            pool_sha256=str(d.get("pool_sha256", "")),
            registered_at=str(d.get("registered_at", "")),
            actor=str(d.get("actor", "")),
            budget=float(d.get("budget", CELL_ERROR_BUDGET) or CELL_ERROR_BUDGET),
            descriptive=tuple((str(a), int(n)) for a, n in d.get("descriptive") or ()),
            author_model=str(d.get("author_model", "")),
            changes={str(k): str(v) for k, v in dict(d.get("changes") or {}).items()},
            max_reruns=int(d.get("max_reruns", DEFAULT_MAX_RERUNS) or 0),
            schema=str(d.get("schema", READING_SCHEMA)),
            reading_id=str(d.get("reading_id", "")),
            pool_rule=str(d.get("pool_rule", "") or ""),
        )

    def verify(self) -> bool:
        """The stored id and pool hash are the ones its body gives."""
        fresh = replace(self, reading_id="")
        return fresh.reading_id == self.reading_id and self.pool_sha256 == pool_digest(self.pool)


def pool_by_rule(authored: Mapping[str, str], *, since: str = "") -> tuple[list[str], str]:
    """The frozen pool of a reading and the rule that chose it (ADR-0026 item 2, DL-097):
    every qualified commit of the cell (``authored``: commit → its authored time), or every one
    authored at or after ``since`` — rules blind to any outcome. A hand-picked list is never a
    pool: a list chosen after grading could hold only the commits that passed (P-320)."""
    if not since.strip():
        return sorted(authored), POOL_RULE_ALL
    cut = _parse_ts(since)
    if cut is None:
        raise ReadingRefused(
            f"since {since!r} is not an ISO 8601 time — a pool starts at a date, e.g. "
            "2026-09-01T00:00:00+00:00",
            code=REFUSAL_INVALID,
        )
    pool = sorted(c for c, a in authored.items() if (t := _parse_ts(a)) is not None and t >= cut)
    return pool, f"{POOL_RULE_SINCE}:{cut.isoformat()}"


def refuse_unless_blind(given: Sequence[str], pool: Sequence[str], rule: str) -> None:
    """A caller that names the pool names the rule's own pool, or is refused
    ``pool_not_blind``: the commits a reading reads are never a choice made on outcomes."""
    if given and set(given) != set(pool):
        extra, missing = sorted(set(given) - set(pool)), sorted(set(pool) - set(given))
        raise ReadingRefused(
            f"a reading's pool is frozen by its rule ({rule}: {len(pool)} commit(s)), never "
            f"by a list — the list given adds {len(extra)} and leaves out {len(missing)} "
            "(ADR-0026 item 2): name a date with since, or leave the pool out",
            code=REFUSAL_POOL_NOT_BLIND,
            detail={"extra": extra[:20], "missing": missing[:20], "rule": rule},
        )


def pool_digest(pool: Sequence[str]) -> str:
    """SHA-256 of the frozen pool as canonical JSON, in the seeded order."""
    return sha256_text(canonical_json(list(pool)))


def cell_error_budget(env: Mapping[str, str] | None = None) -> float:
    """The per-cell budget in force: :data:`CELL_ERROR_BUDGET`, or a tighter value the
    operator set (``CRB_READING__CELL_ERROR_BUDGET``). A looser or malformed value is refused
    — a misconfigured budget is not a larger one."""
    source = os.environ if env is None else env
    raw = (source.get(BUDGET_ENV) or "").strip()
    if not raw:
        return CELL_ERROR_BUDGET
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{BUDGET_ENV}={raw!r} is not a number") from exc
    if not 0.0 < value <= CELL_ERROR_BUDGET:
        raise ValueError(
            f"{BUDGET_ENV}={value} is outside (0, {CELL_ERROR_BUDGET}]: a larger budget needs an "
            "ADR amending ADR-0026 item 5"
        )
    return value


def budget_spent(readings: Iterable[Reading], key: tuple[str, str, str, str]) -> float:
    """What the readings already registered on the cell ``key`` have spent."""
    return sum(r.spend for r in readings if r.budget_key == key)


def _validate(
    *,
    cell: Mapping[str, str],
    hierarchy: Sequence[str],
    descriptive: Sequence[tuple[str, int]],
    rule: str,
    pool: Sequence[str],
    author_model: str,
) -> str:
    """Why the shape of a registration is refused, or ``""``. Returns the author model too
    via the caller (the S1 arms name it)."""
    missing = [f for f in CELL_FIELDS if not cell.get(f) or cell.get(f) == "*"]
    if missing:
        return f"a reading names its full cell key; missing {missing}"
    if not hierarchy:
        return "a reading names at least one arm in its hierarchy"
    if rule not in RULES:
        return f"unknown rule {rule!r}; expected one of {sorted(RULES)}"
    if not pool:
        return "a reading freezes a non-empty pool of qualified commits"
    arms = [*hierarchy, *(a for a, _ in descriptive)]
    if len(set(arms)) != len(arms):
        return "an arm appears twice in the reading"
    parsed = [parse_arm(a) for a in hierarchy]
    for a in parsed:
        if a.descriptive:
            return f"{a.id} is descriptive: it runs beside a hierarchy, never in one"
    seen_certifying = False
    for a in parsed:
        if a.ceiling and seen_certifying:
            return "a ceiling arm (S3) is richer than any certifying arm: it comes first"
        seen_certifying = seen_certifying or a.certifies
    factory = cell.get("process_step") == "factory"
    if factory and any(a.base != BASE_S2 for a in parsed):
        return "a factory cell's reading reads the S2 arm only (ADR-0026 item 6)"
    if not factory and any(a.base == BASE_S2 for a in parsed):
        return "S2 certifies prospectively only, on the factory's cell"
    for d_arm, n in descriptive:
        if not parse_arm(d_arm).descriptive:
            return f"{d_arm} is not a descriptive arm (A0 or A0+L)"
        if n <= 0:
            return "a descriptive arm reads a fixed, positive number of commits"
    authors = {a.author for a in parsed if a.author}
    if len(authors) > 1:
        return f"a reading pins one test author; its hierarchy names {sorted(authors)}"
    if authors and author_model and authors != {author_model}:
        return f"the S1 arms name {sorted(authors)} but the reading pins {author_model!r}"
    return ""


def register(
    *,
    repo: str,
    cell: Mapping[str, str],
    hierarchy: Sequence[str],
    pool: Sequence[str],
    apparatus: str,
    taxonomy: str,
    posture_class: str,
    checks_arm: str,
    actor: str,
    existing: Iterable[Reading] = (),
    rows: Iterable[GradeRow] = (),
    rule: str = RULE_LOOK_V1,
    descriptive: Sequence[tuple[str, int]] = (),
    author_model: str = "",
    changes: Mapping[str, str] | None = None,
    budget: float | None = None,
    max_reruns: int = DEFAULT_MAX_RERUNS,
    now: str = "",
    pool_rule: str = "",
) -> Reading:
    """Register a reading, or raise :class:`ReadingRefused`.

    Refused ``pool_seen`` when any pool commit — or another commit of the same change — already
    has a graded row under an arm of the hierarchy at this apparatus, whatever class-set version
    graded it;
    ``budget_spent`` when the cell's spend plus this rule's P(deliver | 0.80) would exceed
    the budget; ``invalid_reading`` when the shape breaks item 1's or item 4's rules. The
    caller writes the returned reading as a ``reading.registered`` event before any attempt.
    """
    cell_d = {str(k): str(v) for k, v in cell.items()}
    hier = tuple(str(a).strip() for a in hierarchy)
    desc = tuple((str(a).strip(), int(n)) for a, n in descriptive)
    try:
        why = _validate(
            cell=cell_d,
            hierarchy=hier,
            descriptive=desc,
            rule=rule,
            pool=list(pool),
            author_model=author_model,
        )
    except ValueError as exc:
        why = str(exc)
    if why:
        raise ReadingRefused(why, code=REFUSAL_INVALID)
    authors = {parse_arm(a).author for a in hier if parse_arm(a).author}
    author = author_model or (next(iter(authors)) if authors else "")
    key = canonical_cell_key(cell_d)
    ordered = seeded_order(repo, key, pool)
    arms = set(hier)
    pool_set = set(ordered)
    pool_changes = {v for c, v in (changes or {}).items() if c in pool_set and v}
    seen = sorted(
        {
            r.task_id
            for r in rows
            if r.repo == repo
            and r.apparatus_version == apparatus
            and r.context_arm in arms
            and (r.task_id in pool_set or (r.change_id and r.change_id in pool_changes))
        }
    )
    if seen:
        raise ReadingRefused(
            f"{len(seen)} pool commit(s) already have a graded row under an arm of this reading "
            f"at apparatus {apparatus} — a reading counts only commits it has not seen "
            "(ADR-0026 item 2); register a pool of commits no arm has graded",
            code=REFUSAL_POOL_SEEN,
            detail={"commits": seen[:20], "n": len(seen)},
        )
    cap = cell_error_budget() if budget is None else budget
    spend = rule_spend(rule)
    prior = list(existing)
    budget_key = (repo, key, apparatus, taxonomy)
    spent = budget_spent(prior, budget_key)
    if spent + spend > cap + 1e-12:
        raise ReadingRefused(
            f"the cell's error budget is {cap:.2%}; {spent:.2%} is spent and {rule} would spend "
            f"{spend:.2%} more — no further reading can be registered on this cell at "
            f"apparatus {apparatus} and class-set version {taxonomy}",
            code=REFUSAL_BUDGET_SPENT,
            detail={"budget": cap, "spent": round(spent, 6), "spend": round(spend, 6)},
        )
    return Reading(
        repo=repo,
        cell=cell_d,
        apparatus=apparatus,
        taxonomy=taxonomy,
        posture_class=posture_class,
        checks_arm=checks_arm,
        hierarchy=hier,
        descriptive=desc,
        rule=rule,
        spend=spend,
        budget=cap,
        author_model=author,
        pool=tuple(ordered),
        pool_sha256=pool_digest(ordered),
        changes={c: v for c, v in (changes or {}).items() if c in set(ordered)},
        max_reruns=max_reruns,
        registered_at=now or utc_now_iso(),
        actor=actor,
        pool_rule=pool_rule,
    )


# ---------------------------------------------------------------------------
# Counting one arm
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommitReading:
    """One pool commit as an arm reads it."""

    commit: str
    change: str
    outcome: bool | None  # clean / miss / pending
    left: str = ""  # why it left the pool ("" = it did not)
    row_hash: str = ""  # the first observed attempt

    def to_dict(self) -> dict[str, Any]:
        return {
            "commit": self.commit,
            "change": self.change,
            "outcome": self.outcome,
            "left": self.left,
            "row_hash": self.row_hash,
        }


@dataclass(frozen=True)
class ArmReading:
    """One arm of a reading: its commits in the seeded order and its look state."""

    arm: str
    look: LookState
    commits: tuple[CommitReading, ...]
    descriptive: bool = False
    stopped_by: str = ""

    @property
    def state(self) -> str:
        if self.stopped_by:
            return STATE_STOPPED
        return STATE_DESCRIPTIVE if self.descriptive else self.look.state

    @property
    def counted_commits(self) -> tuple[str, ...]:
        """The commits the look read (the prefix), in order."""
        kept = [c for c in self.commits if not c.left]
        return tuple(c.commit for c in kept[: self.look.counted])

    @property
    def left(self) -> tuple[CommitReading, ...]:
        return tuple(c for c in self.commits if c.left)

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "state": self.state,
            "descriptive": self.descriptive,
            "stopped_by": self.stopped_by,
            **{k: v for k, v in self.look.to_dict().items() if k != "state"},
            "look_state": self.look.state,
            "left": [c.to_dict() for c in self.left],
            "counted_commits": list(self.counted_commits),
        }


def _counts_for(reading: Reading, arm: str, row: GradeRow) -> bool:
    """Is ``row`` one of the rows ``arm`` of ``reading`` may count (before first-attempt)?
    Its repository, cell, apparatus, class-set version, checks arm and context arm are the
    reading's; it is a rung ``r1`` attempt this deployment graded (never an imported row, whose
    labels were set elsewhere — P-321); it was graded strictly AFTER the registration (whole
    seconds, so a row of the same second does not count); and it was graded in the sealed
    posture class the reading names — or, for ``S2``, on held-out acceptance tests."""
    if (
        row.imported
        or row.repo != reading.repo
        or row.context_arm != arm
        or row.apparatus_version != reading.apparatus
        or row.taxonomy != reading.taxonomy
        or row.checks_arm != reading.checks_arm
        or row.cell.to_dict() != reading.cell
        or row.trial.strip().lower() != RUNG_R1
    ):
        return False
    registered = reading.registered
    created = _parse_ts(row.created)
    if registered is None or created is None or created <= registered:
        return False  # graded before (or as) the reading was registered: never counts
    if parse_arm(arm).prospective_only:
        return row.labels.get(LABEL_HELD_OUT) == "true"
    return row.posture_class == reading.posture_class and row.sealed


def arm_reading(
    reading: Reading, arm: str, rows: Sequence[GradeRow], *, limit: int = 0
) -> ArmReading:
    """Read ``arm`` of ``reading`` over ``rows`` (in LEDGER order).

    Each pool commit, in the seeded order, is read by its first observed ``r1`` attempt graded
    after registration: the first eligible row whose failure kind is not ``harness``. Two
    commits of one change count once (the first in the order). A commit without an observed
    attempt is pending; one the instrument cannot grade leaves the pool with its reason before
    its outcome is read. ``limit`` caps a descriptive arm at its fixed count."""
    by_commit: dict[str, list[GradeRow]] = {}
    pool = set(reading.pool)
    for r in rows:
        if r.task_id in pool and _counts_for(reading, arm, r):
            by_commit.setdefault(r.task_id, []).append(r)
    out: list[CommitReading] = []
    seen_changes: set[str] = set()
    for commit in reading.pool:
        rs = by_commit.get(commit, [])
        change = reading.changes.get(commit) or next(
            (r.change_id for r in rs if r.change_id), commit
        )
        if change in seen_changes:
            out.append(CommitReading(commit, change, None, LEFT_SAME_CHANGE))
            continue
        seen_changes.add(change)
        observed = None
        unobserved: list[str] = []
        for r in rs:
            if len(unobserved) > reading.max_reruns:
                break  # it has left the pool: a later row can never bring it back
            if r.gold_clean is False:
                unobserved = [LEFT_GOLD] * (reading.max_reruns + 1)
                break
            if r.failure_kind == FAILURE_OUTAGE:
                continue  # the call never happened: nothing observed, nothing spent
            if r.failure_kind == FAILURE_HARNESS:
                unobserved.append(LEFT_HARNESS)
                continue
            # an observed attempt — a disqualified one (the builder touched the oracle) is
            # the builder's miss, never the instrument's, so it is read, not re-run
            observed = r
            break
        if observed is not None:
            if observed.lint_reason == "disabled_by_config":
                out.append(
                    CommitReading(commit, change, None, LEFT_LINT_DISABLED, observed.row_hash)
                )
            else:
                clean = observed.clean and not observed.disqualified
                out.append(CommitReading(commit, change, clean, "", observed.row_hash))
        elif len(unobserved) > reading.max_reruns:
            out.append(CommitReading(commit, change, None, unobserved[-1]))
        else:
            out.append(CommitReading(commit, change, None))
    kept = [c.outcome for c in out if not c.left]
    if limit:
        kept = kept[:limit]
        descriptive_look = _descriptive_look(kept, limit)
        return ArmReading(arm, descriptive_look, tuple(out), descriptive=True)
    return ArmReading(arm, look_state(kept, reading.rule), tuple(out))


def _descriptive_look(outcomes: Sequence[bool | None], limit: int) -> LookState:
    """A descriptive arm's tally over its first ``limit`` commits: no look, no decision."""
    resolved = [o for o in outcomes if o is not None]
    clean = sum(1 for o in resolved if o)
    pending = sum(1 for o in outcomes if o is None) + max(0, limit - len(outcomes))
    return LookState(
        STATE_DESCRIPTIVE, len(resolved), clean, len(resolved) - clean, limit, pending, None
    )


# ---------------------------------------------------------------------------
# The hierarchy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReadingOutcome:
    """A reading evaluated: every arm, the delivering chain, and the cell's standard."""

    reading: Reading
    arms: Mapping[str, ArmReading]
    chain: tuple[str, ...]
    stopped_at: str
    standard: str
    state: str

    @property
    def ceiling(self) -> bool:
        return self.state == OUTCOME_CEILING

    @property
    def blocking(self) -> ArmReading | None:
        """The arm the cell waits on (``None`` once every hierarchy arm has delivered)."""
        return self.arms.get(self.stopped_at) if self.stopped_at else None

    @property
    def needed(self) -> int:
        """The commits still needed to the next look of the arm the cell waits on."""
        b = self.blocking
        return b.look.needed if b is not None and b.look.state == STATE_LOOK_PENDING else 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "reading_id": self.reading.reading_id,
            "rule": self.reading.rule,
            "hierarchy": list(self.reading.hierarchy),
            "state": self.state,
            "standard": self.standard or None,
            "ceiling": self.ceiling,
            "chain": list(self.chain),
            "stopped_at": self.stopped_at or None,
            "needed": self.needed,
            "spend": round(self.reading.spend, 6),
            "registered_at": self.reading.registered_at,
            "pool": len(self.reading.pool),
            "pool_sha256": self.reading.pool_sha256,
            "arms": [a.to_dict() for a in self.arms.values()],
        }


def evaluate(reading: Reading, rows: Iterable[GradeRow]) -> ReadingOutcome:
    """Read every arm of ``reading`` and its hierarchy (ADR-0026 item 4): stop at the first
    arm that does not deliver; the standard is the leanest certifying arm of the unbroken
    chain; ``S3`` alone is a ceiling."""
    rs = list(rows)
    arms: dict[str, ArmReading] = {}
    chain: list[str] = []
    stopped_at = ""
    for arm in reading.hierarchy:
        a = arm_reading(reading, arm, rs)
        if stopped_at:
            a = replace(a, stopped_by=stopped_at)
        elif a.look.state == STATE_DELIVER:
            chain.append(arm)
        else:
            stopped_at = arm
        arms[arm] = a
    for arm, n in reading.descriptive:
        arms[arm] = arm_reading(reading, arm, rs, limit=n)
    certifying = [a for a in chain if parse_arm(a).certifies]
    standard = certifying[-1] if certifying else ""
    if standard:
        state = OUTCOME_STANDARD
    elif not stopped_at:
        state = OUTCOME_CEILING
    else:
        blocked = arms[stopped_at].look.state
        if chain and blocked in (STATE_INSUFFICIENT, STATE_UNDECIDED):
            state = OUTCOME_CEILING
        else:
            state = blocked
    return ReadingOutcome(reading, arms, tuple(chain), stopped_at, standard, state)


@dataclass(frozen=True)
class Standard:
    """A cell's proven context (``standard_for``): the arm a ticket's build must carry, the
    reading that proved it, and whether it is only a ceiling (``S3`` alone — calibration
    builds only)."""

    repo: str
    cell: Mapping[str, str]
    arm: str
    reading_id: str
    taxonomy: str
    apparatus: str
    ceiling: bool = False

    @property
    def loop(self) -> bool:
        """The standard arm carries ``+L``: a factory brief carries the loop's overlay."""
        return parse_arm(self.arm).loop

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "cell": dict(self.cell),
            "arm": self.arm,
            "reading_id": self.reading_id,
            "taxonomy": self.taxonomy,
            "apparatus": self.apparatus,
            "ceiling": self.ceiling,
            "loop": self.loop,
        }


def latest_outcome(outcomes: Iterable[ReadingOutcome]) -> ReadingOutcome | None:
    """Of several readings of one cell, the one that speaks: a proven standard over a ceiling
    over one still reading, the latest registration breaking ties."""
    rank = {OUTCOME_STANDARD: 3, OUTCOME_CEILING: 2, OUTCOME_LOOK_PENDING: 1}
    best: ReadingOutcome | None = None
    for o in outcomes:
        if best is None or (rank.get(o.state, 0), o.reading.registered_at) >= (
            rank.get(best.state, 0),
            best.reading.registered_at,
        ):
            best = o
    return best


def outcomes_for_cell(
    readings: Iterable[Reading],
    rows: Sequence[GradeRow],
    *,
    repo: str,
    cell: Mapping[str, str],
    apparatus: str,
    taxonomy: str,
    checks_arm: str,
    posture_class: str,
) -> list[ReadingOutcome]:
    """Every reading registered on exactly this cell, apparatus, class-set version, checks arm
    and posture class — every scope field a reading counts its rows on (P-319)."""
    want = canonical_cell_key(cell)
    return [
        evaluate(r, rows)
        for r in readings
        if r.repo == repo
        and r.cell_key == want
        and r.apparatus == apparatus
        and r.taxonomy == taxonomy
        and r.checks_arm == checks_arm
        and r.posture_class == posture_class
    ]


def standard_of(
    readings: Iterable[Reading],
    rows: Sequence[GradeRow],
    *,
    repo: str,
    cell: Mapping[str, str],
    apparatus: str,
    taxonomy: str,
    checks_arm: str,
    posture_class: str,
) -> Standard | None:
    """The cell's proven standard (or its ceiling) on one checks arm and posture class, or
    ``None`` — no proven standard. Pure: the caller supplies the readings and the rows (the
    server's ``standard_for`` reads them)."""
    best = latest_outcome(
        outcomes_for_cell(
            readings,
            rows,
            repo=repo,
            cell=cell,
            apparatus=apparatus,
            taxonomy=taxonomy,
            checks_arm=checks_arm,
            posture_class=posture_class,
        )
    )
    if best is None or best.state not in (OUTCOME_STANDARD, OUTCOME_CEILING):
        return None
    arm = best.standard or (best.chain[-1] if best.chain else "")
    if not arm:
        return None
    return Standard(
        repo=repo,
        cell=dict(cell),
        arm=arm,
        reading_id=best.reading.reading_id,
        taxonomy=taxonomy,
        apparatus=apparatus,
        ceiling=best.state == OUTCOME_CEILING,
    )


# --- what one arm reads, for the router (ADR-0026 item 6) -----------------------------
VERDICT_UNREGISTERED = "reading_unregistered"
VERDICT_DESCRIPTIVE = "descriptive"
VERDICT_LOOK_PENDING = STATE_LOOK_PENDING
VERDICT_DELIVER = STATE_DELIVER
VERDICT_INSUFFICIENT = STATE_INSUFFICIENT
VERDICT_UNDECIDED = STATE_UNDECIDED
VERDICT_CEILING = OUTCOME_CEILING
#: The arm delivered and certifies, but the cell's standard is a leaner arm of the chain.
VERDICT_LEANER = "leaner_standard"


@dataclass(frozen=True)
class ArmVerdict:
    """What the router reads about ONE arm of a cell: the state of that arm in the reading
    that speaks for the cell (``state``), with its counts and the cell's standard."""

    arm: str
    state: str
    reading_id: str = ""
    rule: str = ""
    counted: int = 0
    clean: int = 0
    needed: int = 0
    next_look: int | None = None
    standard: str = ""
    #: The richer arm the hierarchy stopped at, when this arm was never read because of it.
    blocking: str = ""
    counted_commits: tuple[str, ...] = ()
    #: Commits of the pool still able to fill the next look (for ``undecided`` / ``mine``).
    pool_remaining: int = 0

    @property
    def ci(self) -> Interval:
        return wilson_interval(self.clean, self.counted)

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "state": self.state,
            "reading_id": self.reading_id or None,
            "rule": self.rule or None,
            "counted": self.counted,
            "clean": self.clean,
            "ci_low": round(self.ci.low, 4),
            "ci_high": round(self.ci.high, 4),
            "needed": self.needed,
            "next_look": self.next_look,
            "standard": self.standard or None,
            "blocking": self.blocking or None,
        }


def verdict_for(outcome: ReadingOutcome | None, arm: str) -> ArmVerdict:
    """The router's reading of ``arm`` (ADR-0026 items 4 and 6): unregistered when no reading
    names it; descriptive for ``A0`` / ``A0+L``; the blocking arm's state when the hierarchy
    stopped at a richer arm; ``ceiling`` for a delivering ``S3``; ``leaner_standard`` for a
    delivering certifying arm that is not the cell's standard; else the arm's own look state."""
    if outcome is None:
        return ArmVerdict(arm, VERDICT_UNREGISTERED)
    r = outcome.reading
    base: dict[str, Any] = {
        "reading_id": r.reading_id,
        "rule": r.rule,
        "standard": outcome.standard,
    }
    a = outcome.arms.get(arm)
    if a is None:
        return ArmVerdict(arm, VERDICT_UNREGISTERED, **base)
    kept = [c for c in a.commits if not c.left]
    common: dict[str, Any] = {
        **base,
        "counted": a.look.counted,
        "clean": a.look.clean,
        "counted_commits": a.counted_commits,
        "pool_remaining": len(kept),
    }
    if a.descriptive:
        return ArmVerdict(arm, VERDICT_DESCRIPTIVE, **common)
    if a.stopped_by:
        b = outcome.arms[a.stopped_by]
        return ArmVerdict(
            arm,
            b.look.state,
            needed=b.look.needed,
            next_look=b.look.next_look,
            blocking=a.stopped_by,
            **common,
        )
    if a.look.state == STATE_DELIVER:
        if parse_arm(arm).ceiling:
            return ArmVerdict(arm, VERDICT_CEILING, **common)
        if arm != outcome.standard:
            return ArmVerdict(arm, VERDICT_LEANER, **common)
        return ArmVerdict(arm, VERDICT_DELIVER, **common)
    return ArmVerdict(arm, a.look.state, needed=a.look.needed, next_look=a.look.next_look, **common)


def describe_rules() -> str:
    """The look rules as one sentence each, with their exact P(deliver | 0.80)."""
    parts = []
    for name, looks in RULES.items():
        at = ", ".join(f"{n - m}/{n}" for n, m in sorted(looks.items()))
        parts.append(f"{name} delivers at {at} (P(deliver | 0.80) = {rule_spend(name):.2%})")
    return "; ".join(parts)


__all__ = [
    "ARM_STATES",
    "CELL_ERROR_BUDGET",
    "LABEL_HELD_OUT",
    "POOL_RULE_ALL",
    "POOL_RULE_SINCE",
    "READING_EVENT_ACTION",
    "READING_SCHEMA",
    "REFUSAL_BUDGET_SPENT",
    "REFUSAL_POOL_NOT_BLIND",
    "REFUSAL_POOL_SEEN",
    "RULES",
    "RULE_LOOK_V1",
    "VERDICT_CEILING",
    "VERDICT_DELIVER",
    "VERDICT_DESCRIPTIVE",
    "VERDICT_INSUFFICIENT",
    "VERDICT_LEANER",
    "VERDICT_LOOK_PENDING",
    "VERDICT_UNDECIDED",
    "VERDICT_UNREGISTERED",
    "ArmReading",
    "ArmVerdict",
    "LookState",
    "Reading",
    "ReadingOutcome",
    "ReadingRefused",
    "Standard",
    "arm_reading",
    "budget_spent",
    "canonical_cell_key",
    "cell_error_budget",
    "evaluate",
    "latest_outcome",
    "look_state",
    "outcomes_for_cell",
    "p_deliver",
    "pool_by_rule",
    "pool_digest",
    "refuse_unless_blind",
    "register",
    "rule_spend",
    "seed_of",
    "seeded_order",
    "standard_of",
    "verdict_for",
]
