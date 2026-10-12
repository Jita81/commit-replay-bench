"""A campaign's money ceiling, held by the product (G-957): the record, the tally, the rule.

Q-06: each campaign is approved with a stated maximum. Wave 3 is funded with a hard ceiling of
£80 in two stages (DL-371), and until now the only limit the product kept was a run's own
``max_cost_usd`` — per run, in dollars, a guard (G-938). A **campaign** is the approval as a
record: its name, its ceiling in pounds, the pounds released so far (a stage), the rate the
pounds convert to dollars at (stored as the operator gave it, never fetched) and the decision
that approved it, hashed into its id so an edited ceiling no longer verifies.

**The tally** is the Wave 3 registration's rule (docs/reviews/2026-10-09-wave-3-registration.md,
"The tally"), kept by the product instead of by hand:

* **spent** — for every run filed under the campaign, what its ledger rows cost plus each of
  its test author's ``author.attempt`` calls (an ``S1`` replay's author writes no row, P-775),
  plus each **unplaced** attempt: one built or reserved with no row of its run for its
  (commit, trial) once the attempt is settled — charged at its ``build.done`` cost, else at
  its reservation's hold (F8, ``crb.server.campaigns.unplaced_attempts``);
* **held** — for every run queued or running, its cap less what it has spent, plus the larger
  of the headroom it was admitted with and its headroom now;
* **headroom** — the dearest single attempt the campaign has seen, or
  :data:`HEADROOM_FIRST_USD` before the first priced one (a run capped at $0.10 once spent $5.00
  on its first attempt, P-261: a run's cap is a guard until G-938 bounds each call); for an
  ``S1`` run, plus its commits still to run times the dearest author call seen, or
  :data:`AUTHOR_CALL_FIRST_USD` before the first.

A run is admitted only while spent, held, its own cap and its own headroom together stay at or
under the **line** — the released pounds at the rate, never more than the ceiling. A cost the
tally cannot know (a row or an author call with ``cost_known`` false) and a run whose spend
passed its cap plus the headroom it was ADMITTED with (the ``campaign.admitted`` event's
``headroom_usd``, never the headroom now: the overshoot that passes it is itself the dearest
attempt the campaign has seen, so a line recomputed from it would always cover it) each stop
the campaign: nothing more is admitted. So does any unplaced attempt (``unplaced_spend``): the
registration stops on spend the tally cannot place against a run, so a lost sandbox, a kill or
a grade that raised costs its commit and stops the campaign until the operator has read why
(K4). The stops are read in that order — a cost not known, an overrun, unplaced spend — and
only then the line (``campaign_ceiling``).

**One live run per arm** (F87-2): a run is admitted only while no other run of the campaign on
the same repository and the same arm it asks for (``requested_arm``) is queued or running that
could attempt a commit it could (``runs_overlap``) — one of the same reading or either of none,
else one naming a commit it names or either naming none (a run replays only the commits it
names, ``task_ids``, and may replay any commit of the repository when it names none). So for
runs keyed on the same requested arm, two never attempt one commit while both are queued or
running, and the next run on a commit is admitted only after the last has finished: that
commit's rows on the arm reach the ledger in the order its runs were admitted — the order a
reading that takes each commit's first attempt reads them in. Two readings' runs naming
disjoint commits may be live together. The guarantee is the key's and the run status's, not
the worker's: docs/PREVENTION.md P-801 names its gaps (the arm a run asks for is not always
the arm its rows carry; a run without ``campaign_id`` is outside the key; a run abandoned past
``max_reclaims`` frees its arm while a hung worker may still append a row).

Navigation
----------
What it is:   The campaign record (``Campaign``: ceiling and released pounds, the rate, the
              decision, a content-hashed id) and the pure tally over its runs (``tally``).
What it does: Hashes a campaign into ``cmp_<24 hex>`` and verifies it; folds the releases into
              the line (never above the ceiling, never lowered); sums each run's rows and author
              calls and its unplaced attempts; holds each queued or running run's unspent cap
              plus its headroom (the larger of the admitted and the current); stops the
              campaign on a run whose spend passed its cap plus the headroom it was admitted
              with, and on a run with an unplaced attempt; answers whether one more run with a
              cap fits (``Tally.refusal``: ``campaign_cost_unknown``, ``campaign_overrun``,
              ``unplaced_spend``, ``campaign_ceiling``, or ``None``); keys a run by the arm it
              asks for (``requested_arm``), says whether two runs of one arm could attempt one
              commit (``runs_overlap``: one reading or either of none, else a commit both name
              or either naming none) and words the refusal of a second live run on one
              (``arm_in_flight``: ``campaign_arm_in_flight``).
How:          ``canonical_json`` + ``sha256_text`` over the record's body → ``tally`` takes the
              line and one ``MemberRun`` per run (the server reads them under the events write
              lock) → ``Tally.headroom`` → ``Tally.refusal``.
Layer:        core — docs/ARCHITECTURE.md#43-c4-level-3--crbcore-modules
ADRs:         docs/adr/0030-a-run-keeps-its-spend-cap.md (§3: a run's spend cap is a guard)
Works with:   src/crb/server/campaigns.py (reads the record, the releases and each run's spend
              from the store, its unplaced attempts with it),
              src/crb/server/routes/campaigns.py (registers, releases, serves),
              src/crb/server/routes/runs.py (``POST /runs`` admits a run under a campaign),
              src/crb/server/spend_cap.py (``Spend``: the rule a run's own cap sums by),
              src/crb/core/evidence.py (``canonical_json``, ``sha256_text``),
              src/crb/core/context_arm.py (``REPLAY_MODE``, ``LEARN_OFF``, ``MOD_LOOP``: the
              arm vocabulary a run's admission key is spelled in)
Tested by:    tests/test_campaign.py, tests/test_server_campaigns.py, tests/test_p792_reserved.py
Touch when:   never for a new repository; the registration's tally or stop rule changes (a
              decision first, then this module's refusals and
              docs/API.md#campaigns-a-campaigns-money-ceiling).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from crb.core.context_arm import BASE_A0, BASE_S1, BASE_S3, LEARN_OFF, MOD_LOOP, REPLAY_MODE
from crb.core.evidence import canonical_json, sha256_text

CAMPAIGN_SCHEMA = "crb.campaign.v1"
#: The events a campaign's trace (its id) holds: registered once, released per stage, and one
#: per run admitted under it, written in the same transaction as the run is queued.
CAMPAIGN_REGISTERED = "campaign.registered"
CAMPAIGN_RELEASED = "campaign.released"
CAMPAIGN_ADMITTED = "campaign.admitted"
CAMPAIGN_ID_PREFIX = "cmp_"

#: A run's headroom before the campaign has seen a priced attempt (P-261).
HEADROOM_FIRST_USD = 5.00
#: An ``S1`` run's headroom per commit still to run before a priced author call (ADR-0026 item
#: 13's upper assumption).
AUTHOR_CALL_FIRST_USD = 0.15
#: Cents are the ledger's precision; a sum of float costs may miss the line by less.
_EPSILON = 1e-9

#: 409 — the run's cap and headroom would pass what is left under the line.
REFUSAL_CEILING = "campaign_ceiling"
#: 409 — a run of the campaign has a cost the tally cannot know: the campaign is stopped.
REFUSAL_COST_UNKNOWN = "campaign_cost_unknown"
#: 409 — a run of the campaign spent past its cap plus its headroom: the campaign is stopped.
REFUSAL_OVERRUN = "campaign_overrun"
#: 409 — a run of the campaign has an attempt that spent with no row to place it against (its
#: run ended or was reclaimed first): the attempt is charged and the campaign is stopped (F8).
REFUSAL_UNPLACED = "unplaced_spend"
#: 409 — a campaign of that name is registered already.
REFUSAL_EXISTS = "campaign_exists"
#: 409 — a release that does not raise the line, or would pass the ceiling.
REFUSAL_RELEASE = "campaign_release_invalid"
#: 404 — no verified campaign has that id.
REFUSAL_UNKNOWN = "campaign_unknown"
#: 409 — a run of a reading that names a campaign is not filed under that campaign: the
#: reading's runs spend only under the ceiling its campaign holds (DL-382).
REFUSAL_REQUIRED = "campaign_required"
#: 422 — a run filed under a campaign names no ``max_cost_usd``: nothing could be held for it.
REFUSAL_CAP_REQUIRED = "campaign_cap_required"
#: 422 — an ``S1`` run under a campaign names neither ``task_ids`` nor ``limit``: its author's
#: headroom is per commit, so its commits must be counted.
REFUSAL_S1_UNBOUNDED = "campaign_s1_unbounded"
#: 409 — a run on the same arm that could attempt one of this run's commits (the same reading,
#: or a commit both name — ``runs_overlap``) is still queued or running under the campaign:
#: one live run per (campaign, arm) on a commit (F87-2).
REFUSAL_ARM_IN_FLIGHT = "campaign_arm_in_flight"
#: The key a factory build is admitted under: its rows name their own test author.
ARM_FACTORY = "factory"

#: The run statuses whose unspent cap is held.
_ACTIVE = frozenset({"queued", "running"})


class CampaignRefused(ValueError):
    """A campaign refusal: its stable ``code`` and a ``detail`` the API serves."""

    def __init__(self, message: str, *, code: str, detail: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.detail: dict[str, Any] = dict(detail or {})


def _usd(v: float) -> str:
    return f"${v:,.2f}"


def _gbp(v: float) -> str:
    return f"£{v:,.2f}"


@dataclass(frozen=True)
class Campaign:
    """One approved campaign — the ``campaign.registered`` event's payload."""

    name: str
    ceiling_gbp: float
    released_gbp: float
    rate_usd_per_gbp: float
    decision: str
    actor: str
    registered_at: str
    schema: str = CAMPAIGN_SCHEMA
    campaign_id: str = ""

    def __post_init__(self) -> None:
        if not self.campaign_id:
            digest = sha256_text(canonical_json(self.body()))[:24]
            object.__setattr__(self, "campaign_id", CAMPAIGN_ID_PREFIX + digest)

    def body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "name": self.name,
            "ceiling_gbp": self.ceiling_gbp,
            "released_gbp": self.released_gbp,
            "rate_usd_per_gbp": self.rate_usd_per_gbp,
            "decision": self.decision,
            "actor": self.actor,
            "registered_at": self.registered_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.body(), "campaign_id": self.campaign_id}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Campaign:
        return cls(
            name=str(d.get("name", "")),
            ceiling_gbp=float(d.get("ceiling_gbp", 0.0) or 0.0),
            released_gbp=float(d.get("released_gbp", 0.0) or 0.0),
            rate_usd_per_gbp=float(d.get("rate_usd_per_gbp", 0.0) or 0.0),
            decision=str(d.get("decision", "")),
            actor=str(d.get("actor", "")),
            registered_at=str(d.get("registered_at", "")),
            schema=str(d.get("schema", CAMPAIGN_SCHEMA)),
            campaign_id=str(d.get("campaign_id", "")),
        )

    def verify(self) -> bool:
        """The stored id is the one its body gives, and the body is a ceiling the tally can
        keep: a positive rate, and a release above nothing and within the ceiling."""
        fresh = replace(self, campaign_id="")
        return (
            fresh.campaign_id == self.campaign_id
            and self.rate_usd_per_gbp > 0
            and 0 < self.released_gbp <= self.ceiling_gbp
        )

    def usd(self, gbp: float) -> float:
        """Pounds in dollars at the campaign's own rate, to the cent."""
        return round(gbp * self.rate_usd_per_gbp, 2)

    def line_gbp(self, releases: Iterable[float] = ()) -> float:
        """The pounds released so far: the most any release named, never above the ceiling
        and never below the registration's own release."""
        return min(self.ceiling_gbp, max([self.released_gbp, *releases]))


def requested_arm(*, kind: str, mode: str, s1: bool, learning: str | None) -> str:
    """The arm a run filed under a campaign asks for — the key it is admitted under, one live
    run per key on a repository (F87-2): ``S1`` for the blind ``S1`` replay, else ``A0`` for a
    blind replay and ``S3`` for a sighted one (:data:`~crb.core.context_arm.REPLAY_MODE`), and
    :data:`ARM_FACTORY` for a factory build; then ``+L`` unless the run opts out of the loop
    (``learning: off``). It is what the run ASKS for, not a row's arm: whether ``+L`` reaches a
    row is the repository's switch when the run starts, and an ``S1`` row names its author."""
    if kind == ARM_FACTORY:
        base = ARM_FACTORY
    elif s1:
        base = BASE_S1
    elif mode == REPLAY_MODE[BASE_A0]:
        base = BASE_A0
    else:
        base = BASE_S3
    return base if learning == LEARN_OFF else base + MOD_LOOP


def runs_overlap(
    reading_id: str,
    other_reading_id: str,
    *,
    commits: frozenset[str] | None,
    other_commits: frozenset[str] | None,
) -> bool:
    """Whether two runs of one arm on one repository could attempt the same commit: when they
    are filed under the same reading or either under none (``""``); else when either names no
    commits (``None`` — it may replay any commit of the repository) or the commits they name
    share one. A run attempts only the commits it names (``task_ids``), and nothing binds
    those to its reading's pool, so two readings' runs are kept apart by what they name."""
    if not reading_id or not other_reading_id or reading_id == other_reading_id:
        return True
    return commits is None or other_commits is None or not commits.isdisjoint(other_commits)


def arm_in_flight(
    *, arm: str, repo: str, reading_id: str, run_id: str, status: str
) -> CampaignRefused:
    """The refusal of a second live run on one arm (F87-2): naming the run still live on it.
    The admission holds one per (campaign, repository, arm) where the two could attempt the
    same commit (:func:`runs_overlap`), so no two runs keyed on one arm attempt a commit
    while both are queued or running — a second attempt the reading could read in place of
    the first."""
    of = f"reading {reading_id} of {repo!r}" if reading_id else repr(repo)
    return CampaignRefused(
        f"campaign arm in flight: run {run_id} on {arm} of {of} is still {status} under this "
        "campaign — one live run per arm; post the next once it has finished — nothing was "
        "queued",
        code=REFUSAL_ARM_IN_FLIGHT,
        detail={
            "run_id": run_id,
            "status": status,
            "repo": repo,
            "reading_id": reading_id,
            "arm": arm,
        },
    )


def planned_commits(task_ids: Sequence[str], limit: int | None) -> int | None:
    """How many commits a run will replay: its named commits, at most its limit; ``None``
    when it names neither (the whole pool, which the tally cannot count)."""
    n: int | None = len(task_ids) if task_ids else None
    if limit is not None:
        n = limit if n is None else min(n, limit)
    return n


@dataclass(frozen=True)
class MemberRun:
    """One run filed under a campaign, as the store has it now: its admission (cap, arm,
    commits, the headroom held for it) and what it has spent — its rows, its test author's
    calls and its unplaced attempts apart."""

    run_id: str
    status: str
    cap_usd: float
    s1: bool = False
    commits: int = 0
    #: The headroom the run was admitted with (the ``campaign.admitted`` event's
    #: ``headroom_usd``) — the line its overrun is read against, fixed at admission.
    headroom_usd: float = 0.0
    commits_done: int = 0
    rows_usd: float = 0.0
    dearest_row_usd: float = 0.0
    rows_unknown: int = 0
    authoring_usd: float = 0.0
    dearest_author_usd: float = 0.0
    authors_unknown: int = 0
    #: The run's unplaced attempts (``crb.server.campaigns.unplaced_attempts``): settled with
    #: no row of the run for their commit and trial — their known costs, how many there are,
    #: and how many have a cost the tally cannot know.
    unrowed_usd: float = 0.0
    unrowed: int = 0
    unrowed_unknown: int = 0

    @property
    def spent_usd(self) -> float:
        return self.rows_usd + self.authoring_usd + self.unrowed_usd

    @property
    def active(self) -> bool:
        return self.status in _ACTIVE

    @property
    def unknown(self) -> int:
        return self.rows_unknown + self.authors_unknown + self.unrowed_unknown

    @property
    def commits_left(self) -> int:
        """The commits it has still to run: none once it has finished."""
        return max(0, self.commits - self.commits_done) if self.active else 0


@dataclass(frozen=True)
class Tally:
    """A campaign's money now: the line, what its runs spent (author calls apart), what is
    held for the runs still to finish, the dearest attempt and author call seen, and the runs
    that stop it (a cost not known, an overrun, an unplaced attempt)."""

    line_usd: float
    spent_usd: float
    authoring_usd: float
    held_usd: float
    dearest_attempt_usd: float | None
    dearest_author_usd: float | None
    unknown_runs: tuple[str, ...] = ()
    overrun_runs: tuple[str, ...] = ()
    unplaced_runs: tuple[str, ...] = ()

    @property
    def stopped(self) -> bool:
        """Whether the campaign is stopped: any run with a cost not known, an overrun or an
        unplaced attempt. A stopped campaign admits nothing."""
        return bool(self.unknown_runs or self.overrun_runs or self.unplaced_runs)

    @property
    def left_usd(self) -> float:
        return round(self.line_usd - self.spent_usd - self.held_usd, 6)

    def headroom(self, *, s1: bool, commits_left: int) -> float:
        """What a run may pass its cap by: the dearest attempt seen (or $5.00 before the
        first), and for an ``S1`` run its commits still to run times the dearest author call
        seen (or $0.15 before the first)."""
        attempt = self.dearest_attempt_usd
        out = HEADROOM_FIRST_USD if attempt is None else attempt
        if s1:
            call = self.dearest_author_usd
            out += max(0, commits_left) * (AUTHOR_CALL_FIRST_USD if call is None else call)
        return round(out, 6)

    def refusal(self, *, cap_usd: float, s1: bool, commits: int) -> CampaignRefused | None:
        """Why one more run with ``cap_usd`` (and, for ``S1``, ``commits`` commits) may not
        be admitted, or ``None``: a stopped campaign first — a cost not known, then an
        overrun, then unplaced spend — then the line."""
        if self.unknown_runs:
            return CampaignRefused(
                f"campaign stopped: {len(self.unknown_runs)} run(s) spent a cost the tally "
                "cannot know (cost_known false) — nothing more is admitted; nothing was queued",
                code=REFUSAL_COST_UNKNOWN,
                detail={"run_ids": list(self.unknown_runs)},
            )
        if self.overrun_runs:
            return CampaignRefused(
                f"campaign stopped: {len(self.overrun_runs)} run(s) spent past their cap plus "
                "their headroom — nothing more is admitted; nothing was queued",
                code=REFUSAL_OVERRUN,
                detail={"run_ids": list(self.overrun_runs)},
            )
        if self.unplaced_runs:
            return CampaignRefused(
                f"campaign stopped: {len(self.unplaced_runs)} run(s) spent on an attempt that "
                "ended with no row (its run ended or was reclaimed first) — the attempt is "
                "charged and nothing more is admitted; nothing was queued",
                code=REFUSAL_UNPLACED,
                detail={"run_ids": list(self.unplaced_runs)},
            )
        headroom = self.headroom(s1=s1, commits_left=commits)
        need = cap_usd + headroom
        if self.spent_usd + self.held_usd + need > self.line_usd + _EPSILON:
            return CampaignRefused(
                f"campaign ceiling: {_usd(self.spent_usd)} spent and {_usd(self.held_usd)} "
                f"held of the {_usd(self.line_usd)} line leave {_usd(max(0.0, self.left_usd))};"
                f" this run's cap {_usd(cap_usd)} plus its headroom {_usd(headroom)} would "
                "pass it — nothing was queued",
                code=REFUSAL_CEILING,
                detail={
                    **self.to_dict(),
                    "cap_usd": round(cap_usd, 6),
                    "headroom_usd": headroom,
                },
            )
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_usd": round(self.line_usd, 2),
            "spent_usd": round(self.spent_usd, 6),
            "authoring_usd": round(self.authoring_usd, 6),
            "held_usd": round(self.held_usd, 6),
            "left_usd": self.left_usd,
            "dearest_attempt_usd": self.dearest_attempt_usd,
            "dearest_author_call_usd": self.dearest_author_usd,
        }


def tally(line_usd: float, members: Sequence[MemberRun]) -> Tally:
    """The campaign's tally over its runs (the registration's rule; see the module). The
    dearest attempt is read from rows alone: an unplaced attempt stops the campaign, and a
    stopped campaign admits no run whose headroom it would set."""
    attempts = [m.dearest_row_usd for m in members if m.dearest_row_usd > 0]
    calls = [m.dearest_author_usd for m in members if m.dearest_author_usd > 0]
    base = Tally(
        line_usd=line_usd,
        spent_usd=sum(m.spent_usd for m in members),
        authoring_usd=sum(m.authoring_usd for m in members),
        held_usd=0.0,
        dearest_attempt_usd=max(attempts) if attempts else None,
        dearest_author_usd=max(calls) if calls else None,
    )
    held = 0.0
    overrun: list[str] = []
    for m in members:
        if m.active:
            held += max(0.0, m.cap_usd - m.spent_usd)
            held += max(m.headroom_usd, base.headroom(s1=m.s1, commits_left=m.commits_left))
        # A run overran when its spend passed what it was admitted to: its cap plus the
        # headroom held for it then (for an S1 run, all its commits' authoring). Never the
        # headroom now — the overshooting attempt is itself the dearest seen, so a line
        # recomputed from it would always cover it.
        if m.spent_usd > m.cap_usd + m.headroom_usd + _EPSILON:
            overrun.append(m.run_id)
    return replace(
        base,
        held_usd=held,
        unknown_runs=tuple(m.run_id for m in members if m.unknown),
        overrun_runs=tuple(overrun),
        unplaced_runs=tuple(m.run_id for m in members if m.unrowed),
    )


__all__ = [
    "ARM_FACTORY",
    "AUTHOR_CALL_FIRST_USD",
    "CAMPAIGN_ADMITTED",
    "CAMPAIGN_ID_PREFIX",
    "CAMPAIGN_REGISTERED",
    "CAMPAIGN_RELEASED",
    "CAMPAIGN_SCHEMA",
    "HEADROOM_FIRST_USD",
    "REFUSAL_ARM_IN_FLIGHT",
    "REFUSAL_CAP_REQUIRED",
    "REFUSAL_CEILING",
    "REFUSAL_COST_UNKNOWN",
    "REFUSAL_EXISTS",
    "REFUSAL_OVERRUN",
    "REFUSAL_RELEASE",
    "REFUSAL_REQUIRED",
    "REFUSAL_S1_UNBOUNDED",
    "REFUSAL_UNKNOWN",
    "REFUSAL_UNPLACED",
    "Campaign",
    "CampaignRefused",
    "MemberRun",
    "Tally",
    "arm_in_flight",
    "planned_commits",
    "requested_arm",
    "runs_overlap",
    "tally",
]
