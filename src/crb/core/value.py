"""The value scorecard — working changes per pound, blind, and whether the loop is learning.

The operator's two instructions (2026-09-25) are the contract this module measures: the
product must *produce working software*, and its *self-learning must get better the more data
goes through it* — where learning means a bug class is removed by a change to the process or
the context and then stops recurring. Every other number in the product answers "is the
instrument honest?"; these answer "is it worth running?".

What is measured, and the rule for each
---------------------------------------
* **Valid attempt** — a row that observed the builder: not an ``outage`` (the provider refused
  the call), not ``harness`` (the instrument failed), not ``disqualified`` (tamper), and not on
  a task whose own gold failed. ``n`` of every rate below.
* **Working** — clean on the belts, formatted and lint-clean by the repository's own tools,
  the public API unchanged unless the task asked, and a reviewer would merge it. A **review**
  answers that for the patch it read (``mergeable``); where no review exists the
  deterministic **proxy** answers it: clean ∧ belt 5 ``repo_lint_clean`` held ∧ belt 6
  ``api_stable`` did not fail. A clean patch whose belt 5 was not evaluated is *unknown* to
  the proxy and counted as not working (fail-closed) — the count of unknowns is served.
* **Clean → working precision** — reviews when at least
  :data:`MIN_REVIEWS_FOR_REVIEW_BASIS` answered ``mergeable`` in scope; else every
  repository's reviews in the same apparatus scope when there are that many
  (``review_pooled``); else the proxy. The basis is always named. Proxy-versus-review
  agreement is served so the proxy can be judged — on the 2026-09-25 baseline the proxy called
  nearly every clean patch working and the reviewers merged under a third, so a person's
  verdict from another repository outranks the proxy.
* **The north star** — working changes per pound, blind: the blind clean rate × the
  precision, times the blind valid attempts, over every pound spent on blind attempts
  (outage, harness and budget-stopped spend included — that money was spent). Its interval
  multiplies the two Wilson bounds (conservative; spend treated as known). The ledger records
  dollars; pounds use a fixed, stated conversion (:data:`DEFAULT_USD_PER_GBP`, a parameter).
* **Process loss** — rows and pounds lost to ``budget`` / ``protocol`` / ``harness`` /
  ``outage``: the attempts that produced nothing because of how we ran them.
* **The learning curve** — attempts (every row the provider did not refuse) in time order,
  cut into windows; a row *recurs* when its bug class was seen at an EARLIER attempt. Only
  prior data decides it, so appending rows can never change an earlier window. The class of a
  row, and each class's status (open / applied / closed / retired / escalated) and lever
  (process or context), come from the bug register behind :func:`default_register` — stream
  L's prevention register over the loop's own chain; ``source`` names it.
* **Prospective routing precision** — walk the rows in time order; before each row, route its
  cell (repository × mode × cell key) with the ONE routing rule from the rows before it only;
  of the rows attempted under a ``deliver`` decision, how many were clean (and working).
  Controls are not evaluated here (numeric clauses only) and the output says so.
* **One checks arm** (ADR-0024) — a row graded with the format step or belt 6 on answers a
  different question from one graded without, so the headline figures (the north star, the
  rates, precision, process loss and the per-repository roll-ups) read ONE arm: ``checks``,
  the ``off`` arm by default (the server passes a repository's own arm when the report is
  scoped to one). The cells and prospective routing are keyed by arm, so they read every arm
  side by side; the learning curve reads every arm on purpose — a lever the loop switches on
  is exactly the before/after it measures, and it counts bug classes, not clean verdicts.

Navigation
----------
What it is:   The value scorecard — pure functions from ledger rows and review verdicts to the
              north-star number (working changes per pound, blind), clean → working precision,
              the process-loss share, the learning curve and prospective routing precision.
What it does: Reduces rows (``ValueRow``, adapted from ``GradeRow`` or read from an export) and
              verdicts to a ``ValueReport`` whose every rate carries k, n and a Wilson
              interval, whose unmeasured figures are null, whose apparatus scope defaults to the
              current version (pooling is explicit and flagged), whose headline reads one checks
              arm (named in ``checks``) and whose cells never pool two, and whose time-ordered
              measures use only prior data. Never writes, never calls a model.
How:          ``select_rows`` (repo, apparatus) → the ``checks`` arm → ``north_star``
              (``Rate`` × ``precision``) → ``process_loss`` → ``learning_curve``
              (``BugRegister.class_of`` per attempt, windows, ``statuses`` → shares) →
              ``prospective_routing`` (running ``CellStats`` per cell → ``route``) → per-cell
              and per-repository roll-ups.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0003-one-routing-rule.md, docs/adr/0024-working-by-construction.md
              (the headline reads one checks arm)
Works with:   src/crb/core/ledger.py (the rows, the failure kinds, ``CellStats``),
              src/crb/core/review.py (the verdicts precision reads), src/crb/core/stats.py (the
              Wilson interval), src/crb/core/routing.py (the rule the prospective decisions
              replay), src/crb/server/routes/value.py (``GET /value``),
              scripts/value_baseline.py (the same report over an exported ledger),
              src/crb/core/prevention.py (the register behind the learning curve)
Tested by:    tests/test_value.py, tests/test_server_routes_value.py,
              tests/test_value_baseline_script.py, tests/test_checks_pooling.py
Touch when:   never for a new repository; the register's inputs change — change
              ``default_register`` only; a new belt that decides "working" joins
              ``proxy_working`` (and the docstring above); a new failure kind that is a process
              loss joins ``LOSS_KINDS``.
Claims:       The north star is an ESTIMATE (a product of two rates) and says so; the proxy is
              a proxy and says so (docs/EVIDENCE-AND-CLAIMS.md#3-every-number-carries-its-method).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from crb.core.checks import ARM_OFF, ARMS
from crb.core.ledger import (
    FAILURE_BUDGET,
    FAILURE_CLEAN,
    FAILURE_DISQUALIFIED,
    FAILURE_HARNESS,
    FAILURE_KINDS,
    FAILURE_OUTAGE,
    FAILURE_PROTOCOL,
    PROTOCOL_VIOLATION_PREFIX,
    CellKey,
    CellStats,
    GradeRow,
)
from crb.core.prevention import Mechanisms, PreventionRecord, PreventionRegister
from crb.core.review import ReviewRecord, latest_reviews
from crb.core.routing import DEFAULT_POLICY, ROUTE_DELIVER, ROUTES, RoutingPolicy, route
from crb.core.stats import Interval, mean, wilson_interval
from crb.core.version import APPARATUS_VERSION

VALUE_SCHEMA = "crb.value.v1"
#: Attempts per window of the learning curve.
DEFAULT_WINDOW = 50
#: Below this many reviews that answered ``mergeable`` in scope, precision reads the proxy.
MIN_REVIEWS_FOR_REVIEW_BASIS = 5
#: A fixed conversion, not a market rate: the ledger records dollars; the scorecard speaks
#: pounds. Every report carries the rate it used; a caller may pass another.
DEFAULT_USD_PER_GBP = 1.35
BASIS_REVIEW = "review"
#: Too few reviews in the scope but enough across every repository in the apparatus scope:
#: human verdicts from other repositories are a better estimate than a proxy the reviews show
#: to be optimistic (docs/reviews/2026-09-25-value-baseline.md).
BASIS_REVIEW_POOLED = "review_pooled"
BASIS_PROXY = "proxy"
BASIS_NONE = "none"
#: Where a report's review verdicts came from — served beside the figures they move.
REVIEWS_FROM_STORE = "store"
REVIEWS_FROM_EXPORT = "export"
REVIEWS_FROM_CALLER = "caller"
#: The failure kinds that are process losses — attempts that produced nothing because of
#: how they were run (turns/time, a refused command, the instrument, the provider).
LOSS_KINDS: tuple[str, ...] = (FAILURE_BUDGET, FAILURE_PROTOCOL, FAILURE_HARNESS, FAILURE_OUTAGE)
#: The kinds that are not valid observations of the builder.
NOT_VALID_KINDS: tuple[str, ...] = (FAILURE_OUTAGE, FAILURE_HARNESS, FAILURE_DISQUALIFIED)
#: A bug class's status in the register (stream L's vocabulary).
CLASS_STATUSES: tuple[str, ...] = ("open", "applied", "closed", "retired", "escalated")
#: The lever that removed a class: a change to the PROCESS or to the CONTEXT ("" = none yet).
LEVERS: tuple[str, ...] = ("process", "context", "")
#: Label a row carries for belt 6 until the belt is a field (stream W): "true" / "false".
LABEL_API_STABLE = "api_stable"


# --- the row --------------------------------------------------------------------------


@dataclass(frozen=True)
class ValueRow:
    """One graded attempt reduced to what the scorecard reads.

    Built from a :class:`~crb.core.ledger.GradeRow` (:func:`value_row_from_grade`) or from an
    exported ledger (``scripts/value_baseline.py``). ``failure_kind`` is the product's own
    rule's answer; ``detail`` is the short sub-class the stub register appends (the guard for a
    protocol refusal, the stop reason for a budget stop, the harness cause). ``grade`` keeps
    the full row so stream L's register can classify it however it needs.
    """

    row_hash: str
    repo: str
    task_id: str
    created: str
    capability_class: str
    size: str
    mode: str
    clean: bool
    failure_kind: str
    cost_usd: float = 0.0
    apparatus_version: str = APPARATUS_VERSION
    gold_clean: bool | None = None
    repo_lint_clean: bool | None = None
    api_stable: bool | None = None
    oracle_strength: float | None = None
    detail: str = ""
    process_step: str = "replay"
    trial: str = ""
    language: str = ""
    builder: str = ""
    model: str = ""
    provider: str = ""
    #: The ``checks`` arm the row was graded under (ADR-0024): a cell never pools two
    checks_arm: str = ARM_OFF
    grade: GradeRow | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.failure_kind not in FAILURE_KINDS:
            raise ValueError(f"{self.failure_kind!r} is not a failure kind ({FAILURE_KINDS})")
        if self.clean != (self.failure_kind == FAILURE_CLEAN):
            raise ValueError(f"failure_kind {self.failure_kind!r} contradicts clean={self.clean}")

    @property
    def eligible(self) -> bool:
        """The router's denominator (``GradeRow.eligible``): judged, and the call happened."""
        return self.failure_kind not in (FAILURE_OUTAGE, FAILURE_DISQUALIFIED) and (
            self.gold_clean is not False
        )

    @property
    def valid(self) -> bool:
        """An observation of the BUILDER: eligible and the instrument did not fail."""
        return self.eligible and self.failure_kind != FAILURE_HARNESS

    @property
    def attempted(self) -> bool:
        """Reached the builder — every row the provider did not refuse (the curve's x-axis)."""
        return self.failure_kind != FAILURE_OUTAGE

    @property
    def cell(self) -> CellKey:
        return CellKey(
            self.process_step,
            self.capability_class,
            self.size,
            self.language,
            self.builder,
            self.model,
            self.provider,
        )


def _bool_label(v: str | None) -> bool | None:
    return {"true": True, "false": False}.get((v or "").strip().lower())


def _detail(row: GradeRow, kind: str) -> str:
    """The sub-class the stub register appends — short, normalised, never free text."""
    if kind == FAILURE_PROTOCOL:
        text = row.error or row.labels.get("builder_error", "")
        rest = (
            text[len(PROTOCOL_VIOLATION_PREFIX) :]
            if text.startswith(PROTOCOL_VIOLATION_PREFIX)
            else ""
        )
        return rest.strip().split(":", 1)[0].strip().lower()[:32]
    if kind == FAILURE_BUDGET:
        return row.stop_reason
    if kind in (FAILURE_HARNESS, FAILURE_OUTAGE):
        return row.error.split(":", 1)[0].strip().lower()[:32]
    return ""


def value_row_from_grade(row: GradeRow) -> ValueRow:
    """Reduce a ledger row. Belt 6 (``api_stable``) is read from the row when the field
    exists, else from its label — ``None`` when neither recorded it."""
    kind = row.failure_kind
    api = getattr(row, "api_stable", None)
    if api is None:
        api = _bool_label(row.labels.get(LABEL_API_STABLE))
    return ValueRow(
        row_hash=row.row_hash,
        repo=row.repo,
        task_id=row.task_id,
        created=row.created,
        capability_class=row.capability_class,
        size=row.size,
        mode=row.mode,
        clean=row.clean,
        failure_kind=kind,
        cost_usd=row.cost_usd,
        apparatus_version=row.apparatus_version,
        gold_clean=row.gold_clean,
        repo_lint_clean=row.repo_lint_clean,
        api_stable=api,
        oracle_strength=row.oracle_strength,
        detail=_detail(row, kind),
        process_step=row.process_step,
        trial=row.trial,
        language=row.language,
        builder=row.builder,
        model=row.model,
        provider=row.provider,
        checks_arm=row.checks_arm,
        grade=row,
    )


def proxy_working(row: ValueRow) -> bool | None:
    """The deterministic proxy for "would be merged": ``True`` / ``False``, or ``None`` when
    the repository's own linter never judged the patch (unknown — the caller fails closed)."""
    if not row.clean or row.api_stable is False:
        return False
    if row.repo_lint_clean is None:
        return None
    return row.repo_lint_clean is True


# --- review verdicts ------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewVerdict:
    """A person's standing answer to "would a maintainer merge this?" for one graded patch.
    ``grade_row_hash`` joins it to its row; ``""`` = unjoined (an exported review file that
    names the task only), scoped by repository alone and counted as such."""

    grade_row_hash: str
    repo: str
    task_id: str
    grade_clean: bool
    mergeable: bool | None
    verdict: str = ""
    finding_kinds: tuple[str, ...] = ()


def verdicts_from_reviews(
    records: Iterable[ReviewRecord], rows_by_hash: Mapping[str, ValueRow]
) -> list[ReviewVerdict]:
    """The latest review per graded row (``latest_reviews``), joined to its row; a review of
    a row the scope does not hold is dropped (its grade is unknown here)."""
    out: list[ReviewVerdict] = []
    for h, rec in latest_reviews(records).items():
        row = rows_by_hash.get(h)
        if row is None:
            continue
        out.append(
            ReviewVerdict(
                grade_row_hash=h,
                repo=rec.repo,
                task_id=rec.task_id,
                grade_clean=row.clean,
                mergeable=rec.mergeable,
                verdict=rec.verdict,
                finding_kinds=tuple(sorted({f.kind for f in rec.findings})),
            )
        )
    return out


# --- a rate -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Rate:
    """``k`` of ``n`` with its Wilson 95% interval; unmeasured (``n == 0``) serialises null.
    ``n`` and ``k`` count ATTEMPTS; when the rows are known, ``n_tasks`` / ``k_tasks`` count
    the distinct tasks under them — repeat attempts on one ticket are not independent draws,
    so the interval is narrower than ``n_tasks`` tasks can support (docs/PREVENTION.md
    P-025)."""

    k: int
    n: int
    k_tasks: int | None = None
    n_tasks: int | None = None

    @property
    def point(self) -> float | None:
        return self.k / self.n if self.n else None

    @property
    def ci(self) -> Interval:
        return wilson_interval(self.k, self.n)

    def to_dict(self) -> dict[str, Any]:
        measured = self.n > 0
        out: dict[str, Any] = {
            "k": self.k,
            "n": self.n,
            "point": round(self.k / self.n, 4) if measured else None,
            "ci_low": round(self.ci.low, 4) if measured else None,
            "ci_high": round(self.ci.high, 4) if measured else None,
        }
        if self.n_tasks is not None:
            out["n_tasks"] = self.n_tasks
            out["k_tasks"] = self.k_tasks
        return out


def _tasks(rows: Iterable[ValueRow]) -> int:
    return len({(r.repo, r.task_id) for r in rows})


def _rate(rows: Iterable[ValueRow]) -> Rate:
    rs = [r for r in rows if r.valid]
    clean = [r for r in rs if r.clean]
    return Rate(len(clean), len(rs), k_tasks=_tasks(clean), n_tasks=_tasks(rs))


def _r(x: float | None, nd: int = 4) -> float | None:
    return None if x is None else round(x, nd)


# --- the register seam ------------------------------------------------------------------


@dataclass(frozen=True)
class ClassStatus:
    """One bug class's standing in the register: ``status`` ∈ :data:`CLASS_STATUSES`, the
    ``lever`` that removed (or is trying to remove) it ∈ :data:`LEVERS`."""

    signature: str
    repo: str
    status: str
    lever: str = ""

    def __post_init__(self) -> None:
        if self.status not in CLASS_STATUSES:
            raise ValueError(f"status {self.status!r} not in {CLASS_STATUSES}")
        if self.lever not in LEVERS:
            raise ValueError(f"lever {self.lever!r} not in {LEVERS}")


class BugRegister(Protocol):
    """THE SEAM to stream L (the prevention loop). ``class_of`` names a row's bug class
    (``None`` = working, no class); ``statuses`` gives every class's standing for the rows
    in scope. ``source`` names the implementation — shown next to every share it feeds."""

    source: str

    def class_of(self, row: ValueRow) -> str | None: ...

    def statuses(self, rows: Sequence[ValueRow]) -> Sequence[ClassStatus]: ...


def stub_signature(row: ValueRow) -> str | None:
    """The stub's class: the failure kind, plus its sub-class when one is known."""
    if row.clean:
        return None
    return f"{row.failure_kind}:{row.detail}" if row.detail else row.failure_kind


class KindRegister:
    """The stub behind the seam until stream L's register is wired: classes by failure kind
    (and sub-class) and reports every class ``open`` — it applies nothing, so it closes
    nothing, and ``source`` says it is a stub."""

    source = "stub:failure-kind"

    def class_of(self, row: ValueRow) -> str | None:
        return stub_signature(row)

    def statuses(self, rows: Sequence[ValueRow]) -> Sequence[ClassStatus]:
        seen: dict[tuple[str, str], ClassStatus] = {}
        for r in rows:
            sig = self.class_of(r)
            if sig is not None and r.attempted:
                seen.setdefault((r.repo, sig), ClassStatus(sig, r.repo, "open", ""))
        return [seen[k] for k in sorted(seen)]


def default_register(
    records: Iterable[PreventionRecord] = (),
    *,
    reviews: Iterable[ReviewRecord] = (),
    factory_events: Iterable[Mapping[str, Any]] = (),
    mechanisms: Mechanisms | None = None,
    packs: Callable[[str], Mapping[str, Any] | None] | None = None,
) -> BugRegister:
    """The register the server and the scripts use: stream L's prevention register
    (``crb.prevention.register.v1``) over the loop's chain ``records``, the standing
    ``reviews`` and the factory's outcome events. With no records every class is ``open``
    — nothing was applied, so nothing is closed. :class:`KindRegister` stays as the
    reference stub the tests compare against."""
    return LoopRegister(
        PreventionRegister(
            records,
            reviews=reviews,
            factory_events=factory_events,
            mechanisms=mechanisms,
            packs=packs,
        )
    )


class LoopRegister:
    """Stream L's register behind the seam. Each standing it reports is re-made as a
    :class:`ClassStatus`, so a status or lever outside the scorecard's vocabulary fails
    loudly here instead of skewing the closed or process shares."""

    def __init__(self, inner: PreventionRegister) -> None:
        self.inner = inner
        self.source = inner.source

    def class_of(self, row: ValueRow) -> str | None:
        return self.inner.class_of(row)

    def statuses(self, rows: Sequence[ValueRow]) -> Sequence[ClassStatus]:
        return [
            ClassStatus(s.signature, s.repo, s.status, s.lever) for s in self.inner.statuses(rows)
        ]


# --- precision and the north star -------------------------------------------------------


@dataclass(frozen=True)
class Precision:
    """Clean → working, by review and by proxy, and which one the north star used."""

    basis: str
    review: Rate
    review_unjoined: int
    review_by_verdict: dict[str, int]
    proxy: Rate
    proxy_unknown: int
    proxy_api_broken: int
    agreement: dict[str, int]

    @property
    def chosen(self) -> Rate:
        return self.review if self.basis in (BASIS_REVIEW, BASIS_REVIEW_POOLED) else self.proxy

    def to_dict(self) -> dict[str, Any]:
        return {
            "basis": self.basis,
            "min_reviews": MIN_REVIEWS_FOR_REVIEW_BASIS,
            "review": {
                **self.review.to_dict(),
                "unjoined": self.review_unjoined,
                "by_verdict": dict(sorted(self.review_by_verdict.items())),
            },
            "proxy": {
                **self.proxy.to_dict(),
                "unknown": self.proxy_unknown,
                "api_broken": self.proxy_api_broken,
                "rule": "clean ∧ repo_lint_clean held ∧ api_stable did not fail; "
                "an unlinted patch is unknown and counted as not working",
            },
            "agreement": dict(self.agreement),
        }


def _answers(verdicts: Iterable[ReviewVerdict]) -> list[ReviewVerdict]:
    """The verdicts that answered "would a maintainer merge this?" about a clean patch."""
    return [v for v in verdicts if v.grade_clean and v.mergeable is not None]


def precision(
    rows: Sequence[ValueRow],
    verdicts: Sequence[ReviewVerdict],
    pooled: Sequence[ReviewVerdict] = (),
) -> Precision:
    """Precision over the clean valid rows in scope and the verdicts in scope. The basis is,
    in order: the scope's reviews (at least :data:`MIN_REVIEWS_FOR_REVIEW_BASIS`); every
    repository's reviews in the same apparatus scope (``pooled``, the same bar); the proxy."""
    clean = [r for r in rows if r.valid and r.clean]
    answers = _answers(verdicts)
    pooled_answers = _answers(pooled)
    if len(answers) < MIN_REVIEWS_FOR_REVIEW_BASIS <= len(pooled_answers):
        chosen = pooled_answers
    else:
        chosen = answers
    review = Rate(sum(1 for v in chosen if v.mergeable), len(chosen))
    by_verdict: dict[str, int] = {}
    for v in chosen:
        by_verdict[v.verdict or "unstated"] = by_verdict.get(v.verdict or "unstated", 0) + 1
    proxies = [proxy_working(r) for r in clean]
    proxy = Rate(sum(1 for p in proxies if p is True), len(clean))
    by_hash = {r.row_hash: r for r in clean if r.row_hash}
    agree = {"n": 0, "both_working": 0, "proxy_only": 0, "review_only": 0, "neither": 0}
    for v in chosen:
        row = by_hash.get(v.grade_row_hash) if v.grade_row_hash else None
        if row is None:
            continue
        p, m = proxy_working(row) is True, bool(v.mergeable)
        agree["n"] += 1
        key = (
            "both_working" if p and m else "proxy_only" if p else "review_only" if m else "neither"
        )
        agree[key] += 1
    basis = (
        BASIS_REVIEW
        if len(answers) >= MIN_REVIEWS_FOR_REVIEW_BASIS
        else BASIS_REVIEW_POOLED
        if review.n >= MIN_REVIEWS_FOR_REVIEW_BASIS
        else BASIS_PROXY
        if proxy.n
        else BASIS_NONE
    )
    return Precision(
        basis=basis,
        review=review,
        review_unjoined=sum(1 for v in chosen if not v.grade_row_hash),
        review_by_verdict=by_verdict,
        proxy=proxy,
        proxy_unknown=sum(1 for p in proxies if p is None),
        proxy_api_broken=sum(1 for r in clean if r.api_stable is False),
        agreement=agree,
    )


@dataclass(frozen=True)
class NorthStar:
    """Working changes per pound, blind — an estimate: blind clean rate × precision."""

    n_attempts: int
    clean_rate: Rate
    precision: Precision
    spend_usd: float
    usd_per_gbp: float

    @property
    def spend_gbp(self) -> float:
        return self.spend_usd / self.usd_per_gbp

    def _working(self) -> tuple[float, float, float] | None:
        p = self.precision.chosen
        if not self.clean_rate.n or not p.n:
            return None
        c, q = self.clean_rate, p
        return (
            (c.k / c.n) * (q.k / q.n),
            c.ci.low * q.ci.low,
            c.ci.high * q.ci.high,
        )

    def to_dict(self) -> dict[str, Any]:
        w = self._working()
        n = self.clean_rate.n
        per_pound = None
        if w is not None and self.spend_usd > 0:
            per_pound = tuple(x * n / self.spend_gbp for x in w)
        return {
            "label": "working changes per pound, blind",
            "per_pound": _r(per_pound[0]) if per_pound else None,
            "per_pound_low": _r(per_pound[1]) if per_pound else None,
            "per_pound_high": _r(per_pound[2]) if per_pound else None,
            "working_rate": _r(w[0]) if w else None,
            "working_rate_low": _r(w[1]) if w else None,
            "working_rate_high": _r(w[2]) if w else None,
            "working_estimate": _r(w[0] * n, 2) if w else None,
            # the same estimate read the other way: pounds spent per working change
            "pounds_per_working": _r(1 / per_pound[0], 2) if per_pound and per_pound[0] else None,
            "pounds_per_working_low": _r(1 / per_pound[2], 2)
            if per_pound and per_pound[2]
            else None,
            "pounds_per_working_high": _r(1 / per_pound[1], 2)
            if per_pound and per_pound[1]
            else None,
            "n_attempts": self.n_attempts,
            "n_valid": n,
            # n counts attempts, not tasks: the tasks behind them say how independent they are
            "n_tasks": self.clean_rate.n_tasks,
            "clean": self.clean_rate.k,
            "clean_tasks": self.clean_rate.k_tasks,
            "clean_rate": self.clean_rate.to_dict(),
            "precision_basis": self.precision.basis,
            "precision": self.precision.chosen.to_dict(),
            "spend_usd": round(self.spend_usd, 2),
            "spend_gbp": round(self.spend_gbp, 2),
            "usd_per_gbp": self.usd_per_gbp,
            "method": (
                "blind clean rate (valid attempts; Wilson 95%) x clean→working precision "
                f"({self.precision.basis}; Wilson 95%) x blind valid attempts ÷ pounds spent on "
                "every blind attempt; interval = product of the two Wilson bounds, spend treated "
                "as known — an estimate, not a count, and not a 95% interval (its coverage is "
                "at least about 0.95² and its width is not calibrated); n counts attempts, and "
                "repeat attempts on one task (n_tasks) are not independent, so the bounds are "
                "narrower than the evidence supports"
            ),
        }


def north_star(
    rows: Sequence[ValueRow],
    verdicts: Sequence[ReviewVerdict],
    *,
    usd_per_gbp: float,
    pooled: Sequence[ReviewVerdict] = (),
) -> NorthStar:
    blind = [r for r in rows if r.mode == "blind"]
    return NorthStar(
        n_attempts=len(blind),
        clean_rate=_rate(blind),
        precision=precision(rows, verdicts, pooled),
        spend_usd=sum(r.cost_usd for r in blind),
        usd_per_gbp=usd_per_gbp,
    )


# --- process loss -----------------------------------------------------------------------


@dataclass(frozen=True)
class ProcessLoss:
    kinds: dict[str, tuple[int, float]]
    rows: int
    usd_total: float
    valid_failures: int
    usd_per_gbp: float

    def to_dict(self) -> dict[str, Any]:
        lost_rows = sum(k for k, _ in self.kinds.values())
        lost_usd = sum(u for _, u in self.kinds.values())
        bp = sum(self.kinds[k][0] for k in (FAILURE_BUDGET, FAILURE_PROTOCOL))
        return {
            "kinds": {
                k: {"rows": n, "usd": round(u, 2), "gbp": round(u / self.usd_per_gbp, 2)}
                for k, (n, u) in self.kinds.items()
            },
            "rows": lost_rows,
            "rows_share": _r(lost_rows / self.rows) if self.rows else None,
            "usd": round(lost_usd, 2),
            "gbp": round(lost_usd / self.usd_per_gbp, 2),
            "usd_share": _r(lost_usd / self.usd_total) if self.usd_total else None,
            "all_rows": self.rows,
            "all_usd": round(self.usd_total, 2),
            "valid_failures": self.valid_failures,
            "budget_protocol_share_of_valid_failures": (
                _r(bp / self.valid_failures) if self.valid_failures else None
            ),
        }


def process_loss(
    rows: Sequence[ValueRow], *, usd_per_gbp: float = DEFAULT_USD_PER_GBP
) -> ProcessLoss:
    """Rows and dollars per loss kind over ALL rows in scope (every row cost something)."""
    kinds: dict[str, tuple[int, float]] = dict.fromkeys(LOSS_KINDS, (0, 0.0))
    for r in rows:
        if r.failure_kind in kinds:
            n, u = kinds[r.failure_kind]
            kinds[r.failure_kind] = (n + 1, u + r.cost_usd)
    return ProcessLoss(
        kinds=kinds,
        rows=len(rows),
        usd_total=sum(r.cost_usd for r in rows),
        valid_failures=sum(1 for r in rows if r.valid and not r.clean),
        usd_per_gbp=usd_per_gbp,
    )


# --- the learning curve -----------------------------------------------------------------


def _ordered(rows: Iterable[ValueRow]) -> list[ValueRow]:
    """Time order; ties keep input order (the ledger's chain order)."""
    indexed = list(enumerate(rows))
    indexed.sort(key=lambda p: (p[1].created, p[0]))
    return [r for _, r in indexed]


@dataclass(frozen=True)
class LearningCurve:
    window: int
    attempts: int
    windows: list[dict[str, Any]]
    classes: list[dict[str, Any]]
    statuses: Sequence[ClassStatus]
    source: str

    def register_dict(self) -> dict[str, Any]:
        n = len(self.statuses)
        closed = [s for s in self.statuses if s.status == "closed"]
        by_process = sum(1 for s in closed if s.lever == "process")
        counts: dict[str, int] = dict.fromkeys(CLASS_STATUSES, 0)
        for s in self.statuses:
            counts[s.status] += 1
        return {
            "source": self.source,
            "n_classes": n,
            "by_status": counts,
            "closed": len(closed),
            "closed_share": _r(len(closed) / n) if n else None,
            "removed_by_process": by_process,
            "removed_by_process_share": _r(by_process / len(closed)) if closed else None,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "window": self.window,
            "attempts": self.attempts,
            "method": (
                "attempts = every row the provider did not refuse, in time order; a row "
                "recurs when its class was seen at an earlier attempt (prior data only)"
            ),
            "windows": self.windows,
            "classes": self.classes,
            "register": self.register_dict(),
        }


#: A bug class's identity on the curve: (repository, signature).
_ClassKey = tuple[str, str]


def learning_curve(
    rows: Iterable[ValueRow], *, window: int = DEFAULT_WINDOW, register: BugRegister | None = None
) -> LearningCurve:
    """Recurrence per window of cumulative attempts, per class and in total."""
    if window < 1:
        raise ValueError("window must be at least 1")
    reg = register if register is not None else default_register()
    attempts = [r for r in _ordered(rows) if r.attempted]
    # a class is per repository (the register's unit): the same refusal in two repositories
    # is two classes, each removed — or not — by that repository's own change
    first_seen: dict[_ClassKey, int] = {}
    occurrences: dict[_ClassKey, int] = {}
    n_windows = (len(attempts) + window - 1) // window
    per_class: dict[_ClassKey, list[int | None]] = {}
    windows: list[dict[str, Any]] = []
    for w in range(n_windows):
        chunk = attempts[w * window : (w + 1) * window]
        start = w * window + 1
        known_at_start = len(first_seen)
        recur = new = 0
        counts: dict[_ClassKey, int] = {}
        for i, r in enumerate(chunk):
            sig = reg.class_of(r)
            if sig is None:
                continue
            key = (r.repo, sig)
            occurrences[key] = occurrences.get(key, 0) + 1
            if key in first_seen:
                recur += 1
                counts[key] = counts.get(key, 0) + 1
            else:
                first_seen[key] = start + i
                new += 1
                per_class[key] = [None] * w
        for key, series in per_class.items():
            series.append(counts.get(key, 0))
        rate = Rate(recur, len(chunk))
        windows.append(
            {
                "index": w,
                "start": start,
                "end": start + len(chunk) - 1,
                "n": len(chunk),
                "partial": len(chunk) < window,
                "new": new,
                "recurrences": recur,
                "classes_known": known_at_start,
                "rate": rate.to_dict(),
            }
        )
    sizes = [w["n"] for w in windows]
    classes = [
        {
            "repo": key[0],
            "signature": key[1],
            "first_seen": first_seen[key],
            "occurrences": occurrences[key],
            "recurrences": occurrences[key] - 1,
            "counts": per_class[key],
            "rates": [
                None if c is None else round(c / sizes[i], 4) for i, c in enumerate(per_class[key])
            ],
        }
        for key in sorted(first_seen, key=lambda k: (first_seen[k], k))
    ]
    return LearningCurve(
        window=window,
        attempts=len(attempts),
        windows=windows,
        classes=classes,
        statuses=tuple(reg.statuses(attempts)),
        source=reg.source,
    )


# --- prospective routing ----------------------------------------------------------------


@dataclass
class _Running:
    n: int = 0
    clean: int = 0
    strengths: list[float] = field(default_factory=list)
    apparatus: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class RoutingPrecision:
    rows_scored: int
    decisions: dict[str, int]
    deliver: Rate
    deliver_working: Rate
    policy_version: str
    deliver_by_mode: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "controls": "not evaluated",
            "method": (
                "rows in time order; before each row its cell (repository x mode x cell key) is "
                "routed from the rows before it only; deliver = clean among the rows attempted "
                "under a deliver decision; deliver_working = the deterministic PROXY (clean, "
                "lint-clean, no public-API break) among the same rows — no review is read"
            ),
            "rows_scored": self.rows_scored,
            "decisions": dict(self.decisions),
            "deliver": self.deliver.to_dict(),
            "deliver_by_mode": dict(sorted(self.deliver_by_mode.items())),
            "deliver_working": self.deliver_working.to_dict(),
            # every served "working" rate names its basis beside it (docs/PREVENTION.md P-024)
            "deliver_working_basis": BASIS_PROXY,
        }


def prospective_routing(
    rows: Iterable[ValueRow], *, policy: RoutingPolicy = DEFAULT_POLICY
) -> RoutingPrecision:
    """Replay the routing rule forward in time; score every ``deliver`` on the row it let in."""
    running: dict[tuple[str, ...], _Running] = {}
    decisions: dict[str, int] = dict.fromkeys(ROUTES, 0)
    delivered: list[ValueRow] = []
    scored = 0
    for r in _ordered(rows):
        if not r.eligible:
            continue
        key = (r.repo, r.mode, r.checks_arm, *r.cell.to_tuple())
        st = running.setdefault(key, _Running())
        ci = wilson_interval(st.clean, st.n)
        stats = CellStats(
            cell=r.cell,
            n=st.n,
            clean=st.clean,
            disqualified=0,
            errors=0,
            false_q1=0,
            point=st.clean / st.n if st.n else 0.0,
            ci=ci,
            cost_usd_mean=0.0,
            latency_s_mean=0.0,
            oracle_strength_mean=mean(st.strengths) if st.strengths else None,
            apparatus_versions=tuple(sorted(st.apparatus)),
            checks_arm=r.checks_arm,
        )
        decision = route(stats, policy=policy)
        decisions[decision.route] += 1
        scored += 1
        if decision.route == ROUTE_DELIVER:
            delivered.append(r)
        st.n += 1
        st.clean += int(r.clean)
        if r.oracle_strength is not None:
            st.strengths.append(r.oracle_strength)
        st.apparatus.add(r.apparatus_version)
    by_mode: dict[str, int] = {}
    for r in delivered:
        by_mode[r.mode] = by_mode.get(r.mode, 0) + 1
    return RoutingPrecision(
        rows_scored=scored,
        decisions=decisions,
        deliver=Rate(sum(1 for r in delivered if r.clean), len(delivered)),
        deliver_working=Rate(sum(1 for r in delivered if proxy_working(r) is True), len(delivered)),
        policy_version=policy.version,
        deliver_by_mode=by_mode,
    )


# --- the report -------------------------------------------------------------------------


def select_rows(
    rows: Iterable[ValueRow], *, repo: str | None = None, apparatus: str = "current"
) -> list[ValueRow]:
    """Scope: one repository (``None`` = all) and one apparatus (``current`` = the running
    version, ``all`` = pooled on request — EVIDENCE-AND-CLAIMS §5: no claim blends versions)."""
    want = scope_label(apparatus)
    return [
        r
        for r in rows
        if (repo is None or r.repo == repo) and (apparatus == "all" or r.apparatus_version == want)
    ]


def scope_label(apparatus: str) -> str:
    """The apparatus a scope names: ``all``, or the version ``current`` resolves to."""
    if apparatus == "all":
        return "all"
    return APPARATUS_VERSION if apparatus in ("", "current") else apparatus


def _verdicts_in_scope(
    verdicts: Iterable[ReviewVerdict], rows: Sequence[ValueRow], repo: str | None
) -> list[ReviewVerdict]:
    hashes = {r.row_hash for r in rows if r.row_hash}
    return [
        v
        for v in verdicts
        if (v.grade_row_hash in hashes)
        or (not v.grade_row_hash and (repo is None or v.repo == repo))
    ]


@dataclass(frozen=True)
class ValueReport:
    repo: str | None
    apparatus: str
    rows: Sequence[ValueRow]
    north: NorthStar
    rates: dict[str, Any]
    precision: Precision
    loss: ProcessLoss
    curve: LearningCurve
    routing: RoutingPrecision
    cells: list[dict[str, Any]]
    repos: list[dict[str, Any]]
    usd_per_gbp: float
    reviews_source: str = REVIEWS_FROM_CALLER
    #: the one ``checks`` arm the headline figures read (ADR-0024)
    checks: str = ARM_OFF

    def to_dict(self) -> dict[str, Any]:
        versions = sorted({r.apparatus_version for r in self.rows})
        return {
            "schema": VALUE_SCHEMA,
            # where the verdicts behind the precision came from: two reports with the same
            # rows but different review sources are different figures (P-035)
            "reviews_source": self.reviews_source,
            "repo": self.repo,
            "apparatus": self.apparatus,
            "apparatus_versions": versions,
            "pooled": len(versions) > 1,
            # the headline (north star, rates, precision, loss, repos) reads this arm only;
            # the cells and the prospective routing are keyed by arm, the curve spans arms
            "checks": self.checks,
            "rows": len(self.rows),
            "usd_per_gbp": self.usd_per_gbp,
            "north_star": self.north.to_dict(),
            "rates": self.rates,
            "precision": self.precision.to_dict(),
            "process_loss": self.loss.to_dict(),
            "learning_curve": self.curve.to_dict(),
            "routing": self.routing.to_dict(),
            "cells": self.cells,
            "repos": self.repos,
        }


_SIZE_ORDER = {s: i for i, s in enumerate(("XS", "S", "M", "L", "XL"))}


def _cells(rows: Sequence[ValueRow], usd_per_gbp: float) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[ValueRow]] = {}
    for r in rows:
        groups.setdefault((r.capability_class, r.size, r.mode, r.checks_arm), []).append(r)
    out = []
    for (cls, size, mode, arm), rs in sorted(
        groups.items(),
        key=lambda kv: (kv[0][0], _SIZE_ORDER.get(kv[0][1], 9), kv[0][1], kv[0][2], kv[0][3]),
    ):
        rate = _rate(rs)
        usd = sum(r.cost_usd for r in rs)
        out.append(
            {
                "capability_class": cls,
                "size": size,
                "mode": mode,
                "checks": arm,
                "attempts": len(rs),
                "n_valid": rate.n,
                "clean": rate.to_dict(),
                "loss_rows": sum(1 for r in rs if r.failure_kind in LOSS_KINDS),
                "spend_usd": round(usd, 2),
                "spend_gbp": round(usd / usd_per_gbp, 2),
            }
        )
    return out


def value_report(
    rows: Iterable[ValueRow],
    verdicts: Iterable[ReviewVerdict],
    *,
    repo: str | None = None,
    apparatus: str = "current",
    register: BugRegister | None = None,
    window: int = DEFAULT_WINDOW,
    usd_per_gbp: float = DEFAULT_USD_PER_GBP,
    policy: RoutingPolicy = DEFAULT_POLICY,
    reviews_source: str = REVIEWS_FROM_CALLER,
    checks: str = ARM_OFF,
) -> ValueReport:
    """The scorecard over one scope. Pure: the same rows and verdicts give the same report.
    ``checks`` is the one arm the headline reads (ADR-0024 — never two); the cells and the
    prospective routing, keyed by arm, and the learning curve read every arm in scope."""
    if usd_per_gbp <= 0:
        raise ValueError("usd_per_gbp must be positive")
    if checks not in ARMS:
        raise ValueError(f"unknown checks arm {checks!r}; expected one of {ARMS}")
    all_rows = list(rows)
    all_verdicts = list(verdicts)
    every_arm = select_rows(all_rows, repo=repo, apparatus=apparatus)
    scoped = [r for r in every_arm if r.checks_arm == checks]
    vs = _verdicts_in_scope(all_verdicts, scoped, repo)
    # every repository's reviews in the same apparatus and arm scope: the fallback before
    # the proxy
    pooled_vs = _verdicts_in_scope(
        all_verdicts,
        [r for r in select_rows(all_rows, apparatus=apparatus) if r.checks_arm == checks],
        None,
    )
    sizes = sorted(
        {r.size for r in scoped if r.mode == "blind"}, key=lambda s: (_SIZE_ORDER.get(s, 9), s)
    )
    rates = {
        "all": _rate(scoped).to_dict(),
        "sighted": _rate(r for r in scoped if r.mode == "sighted").to_dict(),
        "blind": _rate(r for r in scoped if r.mode == "blind").to_dict(),
        "blind_by_size": {
            s: _rate(r for r in scoped if r.mode == "blind" and r.size == s).to_dict()
            for s in sizes
        },
    }
    repos: list[dict[str, Any]] = []
    if repo is None:
        for name in sorted({r.repo for r in scoped}):
            rs = [r for r in scoped if r.repo == name]
            ns = north_star(
                rs,
                _verdicts_in_scope(all_verdicts, rs, name),
                usd_per_gbp=usd_per_gbp,
                pooled=pooled_vs,
            )
            repos.append({"repo": name, "rows": len(rs), "north_star": ns.to_dict()})
    return ValueReport(
        repo=repo,
        apparatus=scope_label(apparatus),
        rows=scoped,
        north=north_star(scoped, vs, usd_per_gbp=usd_per_gbp, pooled=pooled_vs),
        rates=rates,
        precision=precision(scoped, vs, pooled_vs),
        loss=process_loss(scoped, usd_per_gbp=usd_per_gbp),
        curve=learning_curve(every_arm, window=window, register=register),
        routing=prospective_routing(every_arm, policy=policy),
        cells=_cells(every_arm, usd_per_gbp),
        repos=repos,
        usd_per_gbp=usd_per_gbp,
        reviews_source=reviews_source,
        checks=checks,
    )


__all__ = [
    "BASIS_NONE",
    "BASIS_PROXY",
    "BASIS_REVIEW",
    "BASIS_REVIEW_POOLED",
    "CLASS_STATUSES",
    "DEFAULT_USD_PER_GBP",
    "DEFAULT_WINDOW",
    "LEVERS",
    "LOSS_KINDS",
    "MIN_REVIEWS_FOR_REVIEW_BASIS",
    "REVIEWS_FROM_CALLER",
    "REVIEWS_FROM_EXPORT",
    "REVIEWS_FROM_STORE",
    "VALUE_SCHEMA",
    "BugRegister",
    "ClassStatus",
    "KindRegister",
    "LoopRegister",
    "Rate",
    "ReviewVerdict",
    "ValueReport",
    "ValueRow",
    "default_register",
    "learning_curve",
    "north_star",
    "precision",
    "process_loss",
    "prospective_routing",
    "proxy_working",
    "select_rows",
    "stub_signature",
    "value_report",
    "value_row_from_grade",
    "verdicts_from_reviews",
]
