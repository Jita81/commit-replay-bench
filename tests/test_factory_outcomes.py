"""The merge outcome back as evidence (B-9 / F30) and evolutions on the record (F32).

Navigation
----------
What it is:   Unit tests for the factory's outcome sync and the evolutions registration,
              below the HTTP layer: ``FactoryEvidence.record_delivery_outcome`` (once per
              pull request), ``PullRequest.from_api`` (GitHub's shapes → merged / closed /
              open), ``sync_outcomes`` over a fake reader, the task view's ``outcome`` and
              supersession fields, the per-cell delivery counts the capability map serves,
              and ``FactoryHome.register_evolution``.
What it does: Pins that an outcome is recorded at most once per PR whatever the sync reads
              later (idempotent), that an open PR records nothing and a read failure is an
              entry in the report (never an exception), that ``merge_commit_sha`` is kept only
              for a merged PR (GitHub fills it for an open one too), that the task view shows
              the newest delivered PR's fate and a superseded item as ``superseded`` above its
              evolution, that counts are per (class × size) and sum over an unprojected key,
              and that an evolution is a history file + ``backlog.evolved`` + the active
              pointer, with the frozen hash unchanged.
How:          ``MemoryFactoryStore`` / a temporary ``FactoryHome``; a dict-backed reader
              stands in for GitHub.
Layer:        tests — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         docs/adr/0002-append-only-hash-chained-ledger.md, docs/adr/0014-github-app-is-the-connection.md
Works with:   src/crb/factory/evidence.py (the once-per-PR recorder), src/crb/server/github_app.py
              (``PullRequest``), src/crb/server/factory_state.py (``sync_outcomes``,
              ``delivery_counts``, ``register_evolution``, the task view),
              src/crb/factory/backlog.py (``evolve``, ``lineage``)
Tested by:    tests/test_factory_outcomes.py
Touch when:   an outcome field is added, the once-per-PR rule changes (an ADR), or the task
              view's supersession shape changes (docs/API.md first).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from crb.factory import evidence as fe
from crb.factory.backlog import KIND_CODE, BacklogFrozen, BacklogItem
from crb.factory.testfirst import AuthoredTest
from crb.server.factory_state import (
    STATUS_SUPERSEDED_WORD,
    FactoryHome,
    delivery_counts_matching,
    outcomes_pending,
    sync_outcomes,
)
from crb.server.github_app import PR_CLOSED, PR_MERGED, PR_OPEN, GitHubAppError, PullRequest

REPO = "calc"


def _item(item_id: str = "I-1", **over: Any) -> BacklogItem:
    base: dict[str, Any] = {
        "id": item_id,
        "title": "Add multiply to calc",
        "kind": KIND_CODE,
        "capability_class": "bug.fix",
        "size_estimate": "S",
        "structural_facts": (
            "reproduction: `from calc import multiply` raises ImportError",
            "expected_behaviour: calc exposes multiply(a: int, b: int) -> int",
        ),
    }
    base.update(over)
    return BacklogItem(**base)


def _delivery(item_id: str, number: int, **over: Any) -> dict[str, Any]:
    d = {
        "item_id": item_id,
        "branch": f"crb/{item_id}",
        "base": "main",
        "commit_sha": "a" * 40,
        "pr_url": f"https://github.invalid/acme/calc/pull/{number}",
        "pr_number": number,
        "pack_hash": "p" * 64,
        "body_sha256": "b" * 64,
        "created": "2026-09-19T00:00:00+00:00",
        "previous_commit_sha": "",
        "updated": False,
        "comment_error": "",
    }
    d.update(over)
    return d


#: GitHub's ``GET /repos/{o}/{n}/pulls/{k}`` shapes, trimmed to what the sync reads.
PR_OPEN_API: dict[str, Any] = {
    "number": 7,
    "html_url": "https://github.invalid/acme/calc/pull/7",
    "state": "open",
    "merged": False,
    "merged_at": None,
    "merge_commit_sha": "f" * 40,  # GitHub fills a TEST merge sha for an open PR
    "merged_by": None,
    "closed_at": None,
    "head": {"sha": "a" * 40},
}
PR_MERGED_API: dict[str, Any] = {
    **PR_OPEN_API,
    "state": "closed",
    "merged": True,
    "merged_at": "2026-09-19T17:02:11Z",
    "merge_commit_sha": "e0fefb2" + "0" * 33,
    "merged_by": {"login": "paul"},
    "closed_at": "2026-09-19T17:02:11Z",
}
PR_CLOSED_API: dict[str, Any] = {
    **PR_OPEN_API,
    "number": 8,
    "html_url": "https://github.invalid/acme/calc/pull/8",
    "state": "closed",
    "merged": False,
    "closed_at": "2026-09-20T09:00:00Z",
    "merge_commit_sha": None,
}


@pytest.fixture
def home(tmp_path: Path) -> FactoryHome:
    h = FactoryHome(tmp_path / "home", REPO)
    h.register_backlog([_item("I-1"), _item("I-2", size_estimate="M")], actor="tester")
    return h


# --- PullRequest shapes ----------------------------------------------------------------


def test_pull_request_reads_githubs_shapes_into_one_outcome_word() -> None:
    open_ = PullRequest.from_api(PR_OPEN_API)
    assert open_.outcome == PR_OPEN and open_.merged is False and open_.number == 7
    assert open_.merge_commit_sha == "", "an open PR's test-merge sha is not a merge sha"
    merged = PullRequest.from_api(PR_MERGED_API)
    assert merged.outcome == PR_MERGED and merged.merged_by == "paul"
    assert merged.merged_at == "2026-09-19T17:02:11Z"
    assert merged.merge_commit_sha.startswith("e0fefb2")
    closed = PullRequest.from_api(PR_CLOSED_API)
    assert closed.outcome == PR_CLOSED and closed.merged_by == "" and closed.merge_commit_sha == ""
    assert closed.closed_at == "2026-09-20T09:00:00Z"
    # GitHub Enterprise Server versions omit ``merged`` on list shapes: ``merged_at`` decides
    assert PullRequest.from_api({**PR_MERGED_API, "merged": None}).outcome == PR_MERGED
    assert PullRequest.from_api({}).outcome == PR_OPEN
    assert merged.to_dict()["outcome"] == PR_MERGED


# --- the evidence rule: once per pull request --------------------------------------------


def test_outcome_is_recorded_at_most_closed_then_merged_per_pull_request() -> None:
    """A merge is terminal and the same state is never re-appended; ``merged`` after
    ``closed`` IS a second row, because a person can reopen a closed pull request and
    merge it (verifier on feat/shippable, 2026-09-22: once-per-PR had left such a PR
    ``closed`` on the chain for ever)."""
    ev = fe.FactoryEvidence(fe.MemoryFactoryStore(), actor="sync", repo=REPO)
    ev.record_delivery(_delivery("I-1", 7))
    first, recorded = ev.record_delivery_outcome(
        "I-1",
        state=PR_MERGED,
        pr_number=7,
        pr_url="https://github.invalid/acme/calc/pull/7",
        merged_at="2026-09-19T17:02:11Z",
        merged_by="paul",
        merge_sha="e" * 40,
    )
    assert recorded is True and first.kind == fe.EV_DELIVERY_MERGED
    assert first.payload["merged_by"] == "paul" and first.payload["pr_number"] == 7
    # merged is terminal: the same state, or closed after it, appends nothing
    for state in (PR_MERGED, PR_CLOSED):
        again, recorded = ev.record_delivery_outcome("I-1", state=state, pr_number=7)
        assert recorded is False and again.event_id == first.event_id
    assert [e.kind for e in ev.events()] == [fe.EV_DELIVERY, fe.EV_DELIVERY_MERGED]
    # another PR of the same item is its own outcome; another item's PR too
    closed, recorded = ev.record_delivery_outcome("I-1", state=PR_CLOSED, pr_number=9)
    assert recorded is True
    assert ev.outcome_for("I-1", 9) is not None and ev.outcome_for("I-2", 7) is None
    # closed twice appends nothing; closed → merged (reopened and merged by a person) is
    # the one transition recorded, and the newest outcome is what a reader gets
    same, recorded = ev.record_delivery_outcome("I-1", state=PR_CLOSED, pr_number=9)
    assert recorded is False and same.event_id == closed.event_id
    merged, recorded = ev.record_delivery_outcome(
        "I-1", state=PR_MERGED, pr_number=9, merged_by="ada", merge_sha="f" * 40
    )
    assert recorded is True and merged.kind == fe.EV_DELIVERY_MERGED
    assert ev.outcome_for("I-1", 9) is not None
    assert ev.outcome_for("I-1", 9).event_id == merged.event_id  # type: ignore[union-attr]
    _, recorded = ev.record_delivery_outcome("I-1", state=PR_MERGED, pr_number=9)
    assert recorded is False, "a third row never follows a merge"
    with pytest.raises(ValueError, match="state must be one of"):
        ev.record_delivery_outcome("I-1", state="open", pr_number=11)
    assert ev.verify() == 4


# --- the sync ------------------------------------------------------------------------------


def test_outcomes_pending_is_everything_but_a_merge(home: FactoryHome) -> None:
    """The one predicate both callers and the sync share: no outcome → pending; closed →
    pending (a person can reopen and merge); merged → terminal, never read again."""
    ev = home.evidence(actor="worker")
    ev.record_delivery(_delivery("I-1", 7))
    ev.record_delivery(_delivery("I-2", 8))
    assert [(d.item_id, d.pr_number) for d in outcomes_pending(home)] == [("I-1", 7), ("I-2", 8)]
    ev.record_delivery_outcome("I-2", state=PR_CLOSED, pr_number=8)
    assert [(d.item_id, d.pr_number) for d in outcomes_pending(home)] == [("I-1", 7), ("I-2", 8)]
    ev.record_delivery_outcome("I-1", state=PR_MERGED, pr_number=7)
    assert [(d.item_id, d.pr_number) for d in outcomes_pending(home)] == [("I-2", 8)]
    ev.record_delivery_outcome("I-2", state=PR_MERGED, pr_number=8)
    assert outcomes_pending(home) == []


def test_sync_records_merged_and_closed_once_skips_open_and_reports_read_failures(
    home: FactoryHome,
) -> None:
    ev = home.evidence(actor="worker")
    ev.record_delivery(_delivery("I-1", 7))
    ev.record_delivery(_delivery("I-2", 8))
    ev.record_delivery(_delivery("I-2", 9, pr_url="https://github.invalid/acme/calc/pull/9"))
    answers: dict[int, Any] = {
        7: PullRequest.from_api(PR_OPEN_API),
        8: PullRequest.from_api(PR_CLOSED_API),
        9: GitHubAppError(403, "Resource not accessible by integration"),
    }
    reads: list[int] = []

    def read_pr(n: int) -> PullRequest:
        reads.append(n)
        a = answers[n]
        if isinstance(a, Exception):
            raise a
        return a  # type: ignore[no-any-return]

    r1 = sync_outcomes(home, read_pr, actor="operator:1", repository="acme/calc")
    assert r1.to_dict() == {
        "checked": 3,
        "merged": 0,
        "closed": 1,
        "open": 1,
        "errors": ["PR #9 (I-2): GitHub 403: Resource not accessible by integration"],
    }
    assert reads == [7, 8, 9]
    kinds = [(e.kind, e.item_id) for e in home.events() if e.kind.startswith("delivery.")]
    assert kinds[-1] == (fe.EV_DELIVERY_CLOSED, "I-2")
    closed = home.evidence().outcome_for("I-2", 8)
    assert closed is not None and closed.actor == "operator:1"
    assert (
        closed.payload["closed_at"] == "2026-09-20T09:00:00Z" and closed.payload["merge_sha"] == ""
    )
    # the next sync: #8 is read again (closed can still be reopened) but still closed, so
    # nothing is re-recorded; #7 merged meanwhile; #9 retried
    answers[7] = PullRequest.from_api(PR_MERGED_API)
    answers[9] = PullRequest.from_api({**PR_OPEN_API, "number": 9})
    reads.clear()
    r2 = sync_outcomes(home, read_pr, actor="worker", repository="acme/calc")
    assert reads == [7, 8, 9] and (r2.checked, r2.merged, r2.closed, r2.open) == (3, 1, 0, 1)
    merged = home.evidence().outcome_for("I-1", 7)
    assert merged is not None and merged.kind == fe.EV_DELIVERY_MERGED
    assert merged.payload["merged_by"] == "paul" and merged.payload["merge_sha"].startswith(
        "e0fefb2"
    )
    assert [e.kind for e in home.events() if e.kind == fe.EV_DELIVERY_CLOSED] == [
        fe.EV_DELIVERY_CLOSED
    ], "a closed PR read as still closed appends nothing"
    # a third sync: #7 (merged) is never read again; #8 was reopened and merged by a
    # person meanwhile — the one transition the chain records — and #9 is still open
    answers[8] = PullRequest.from_api({**PR_MERGED_API, "number": 8})
    reads.clear()
    n_before = len(home.events())
    r3 = sync_outcomes(home, read_pr, actor="worker", repository="acme/calc")
    assert reads == [8, 9] and (r3.checked, r3.merged, r3.closed, r3.open) == (2, 1, 0, 1)
    assert len(home.events()) == n_before + 1
    reopened = home.evidence().outcome_for("I-2", 8)
    assert reopened is not None and reopened.kind == fe.EV_DELIVERY_MERGED
    # a fourth sync with everything ended reads only what is still open, records nothing new
    reads.clear()
    n_before = len(home.events())
    r4 = sync_outcomes(home, read_pr, actor="worker", repository="acme/calc")
    assert reads == [9] and (r4.checked, r4.open) == (1, 1) and len(home.events()) == n_before
    assert home.evidence().verify() == n_before
    # the summary Home's task 8 reads: newest wins — two merged deliveries, none closed
    assert home.outcomes_summary() == {
        "delivered": 3,
        "merged": 2,
        "closed": 0,
        "open": 1,
        "last_synced": reopened.created,
    }


def test_task_view_carries_the_newest_pull_requests_outcome(home: FactoryHome) -> None:
    ev = home.evidence(actor="worker")
    by_id = {v.id: v for v in home.task_views()}
    assert by_id["I-1"].outcome is None and by_id["I-1"].to_dict()["outcome"] is None
    ev.record_delivery(_delivery("I-1", 7))
    (v,) = [v for v in home.task_views() if v.id == "I-1"]
    assert v.outcome is not None and v.outcome.to_dict() == {
        "state": PR_OPEN,
        "pr_number": 7,
        "pr_url": "https://github.invalid/acme/calc/pull/7",
        "merged_at": "",
        "merged_by": "",
        "merge_sha": "",
        "closed_at": "",
        "synced_at": "",
    }
    # a rework updates the SAME pull request; the outcome then lands on it
    ev.record_delivery_updated(
        _delivery("I-1", 7, commit_sha="c" * 40, previous_commit_sha="a" * 40, updated=True),
        rework=1,
        after_verdict="accept_with_edit",
    )
    merged_ev, _ = ev.record_delivery_outcome(
        "I-1",
        state=PR_MERGED,
        pr_number=7,
        merged_at="2026-09-19T17:02:11Z",
        merged_by="paul",
        merge_sha="e" * 40,
    )
    (v,) = [v for v in home.task_views() if v.id == "I-1"]
    assert v.outcome is not None and v.outcome.state == PR_MERGED
    assert v.outcome.merged_by == "paul" and v.outcome.synced_at == merged_ev.created
    assert v.outcome.merge_sha == "e" * 40 and v.pr_url == v.outcome.pr_url
    # a FRESH pull request later (the first closed, branch deleted): its outcome is its own
    ev.record_delivery(_delivery("I-1", 12, pr_url="https://github.invalid/acme/calc/pull/12"))
    (v,) = [v for v in home.task_views() if v.id == "I-1"]
    assert v.outcome is not None and (v.outcome.state, v.outcome.pr_number) == (PR_OPEN, 12)


def test_delivery_counts_are_per_cell_and_sum_over_an_unprojected_key(home: FactoryHome) -> None:
    ev = home.evidence(actor="worker")
    assert home.delivery_counts() == {}
    ev.record_delivery(_delivery("I-1", 7))
    ev.record_delivery(_delivery("I-1", 9, pr_url="https://github.invalid/acme/calc/pull/9"))
    ev.record_delivery(_delivery("I-2", 8))
    ev.record_delivery_outcome("I-1", state=PR_MERGED, pr_number=7, merged_by="paul")
    ev.record_delivery_outcome("I-2", state=PR_CLOSED, pr_number=8)
    counts = home.delivery_counts()
    s_cell, m_cell = counts[("bug.fix", "S")], counts[("bug.fix", "M")]
    assert (s_cell.n_delivered, s_cell.n_merged, s_cell.n_closed) == (2, 1, 0)
    assert (m_cell.n_delivered, m_cell.n_merged, m_cell.n_closed) == (1, 0, 1)
    assert delivery_counts_matching(counts, "bug.fix", "S") == (2, 1)
    assert delivery_counts_matching(counts, "bug.fix", "*") == (3, 1)
    assert delivery_counts_matching(counts, "*", "*") == (3, 1)
    assert delivery_counts_matching(counts, "backend.route.add", "*") == (0, 0)
    # a PR delivered twice (opened, then updated by a rework) is ONE delivery
    ev.record_delivery_updated(
        _delivery("I-1", 9, commit_sha="c" * 40, updated=True), rework=1, after_verdict="x"
    )
    assert home.delivery_counts()[("bug.fix", "S")].n_delivered == 2


# --- evolutions (F32) --------------------------------------------------------------------


def test_register_evolution_chains_onto_the_frozen_record_and_shows_the_chain(
    home: FactoryHome,
) -> None:
    frozen = home.load_backlog()
    assert frozen is not None
    ev = home.evidence(actor="worker")
    ev.record_item_outcome("I-1", status="oracle_needs_strengthening", error="weak oracle")
    v2 = _item("I-1-v2", title="Add multiply to calc (44 tests)", supersedes="I-1")
    evolved = home.register_evolution(v2, actor="operator:1")
    # the frozen hash never moves; the evolutions chain extends it; history is kept
    assert evolved.backlog_hash == frozen.backlog_hash and evolved.evolutions_hash
    assert evolved.verify(frozen.backlog_hash)
    assert (home.dir / f"backlog-{evolved.evolutions_hash[:16]}.json").exists()
    active = home.load_backlog()
    assert active is not None and active.to_dict() == evolved.to_dict()
    # active items keep registration order: the evolution follows the frozen items
    assert [e.id for e in active.ordered()] == ["I-2", "I-1-v2"]
    assert active.superseded_by() == {"I-1": "I-1-v2"}
    assert [i.id for i in active.lineage("I-1-v2")] == ["I-1", "I-1-v2"]
    last = home.events()[-1]
    assert last.kind == fe.EV_BACKLOG_EVOLVED and last.item_id == "I-1-v2"
    assert last.payload["supersedes"] == "I-1" and last.actor == "operator:1"
    assert last.payload["evolutions_hash"] == evolved.evolutions_hash
    # the task view: the superseded item reads ``superseded`` (its history intact) directly
    # above its evolution; the evolution says what it replaced
    views = home.task_views()
    assert [(v.id, v.status) for v in views] == [
        ("I-2", "pending"),
        ("I-1", STATUS_SUPERSEDED_WORD),
        ("I-1-v2", "pending"),
    ]
    assert views[1].superseded_by == "I-1-v2" and views[1].outcome_reason == "weak oracle"
    assert views[2].supersedes == "I-1" and views[2].superseded_by == ""
    assert views[1].to_dict()["superseded_by"] == "I-1-v2"
    # the frozen record never mutates: an existing id, or superseding twice, is refused
    with pytest.raises(BacklogFrozen, match="already exists"):
        home.register_evolution(_item("I-2", title="edit in place"), actor="x")
    with pytest.raises(BacklogFrozen, match="already superseded"):
        home.register_evolution(_item("I-1-v3", supersedes="I-1"), actor="x")
    # chain of three: supersede the latest; the lineage walks all the way back
    v3 = home.register_evolution(_item("I-1-v3", supersedes="I-1-v2"), actor="x")
    assert [i.id for i in v3.lineage("I-1-v3")] == ["I-1", "I-1-v2", "I-1-v3"]
    assert [(v.id, v.status) for v in home.task_views()][1:] == [
        ("I-1", STATUS_SUPERSEDED_WORD),
        ("I-1-v2", STATUS_SUPERSEDED_WORD),
        ("I-1-v3", "pending"),
    ]
    assert home.evidence().verify() == len(home.events())


def test_evolution_oracle_is_stored_beside_the_frozen_items(home: FactoryHome) -> None:
    home.save_authored(
        {"I-1": AuthoredTest("tests/test_m.py", "def test_m(): ...\n", "operator:1")}
    )
    home.register_evolution(_item("I-1-v2", supersedes="I-1"), actor="x")
    home.save_authored(
        {"I-1-v2": AuthoredTest("tests/test_m2.py", "def test_m2(): ...\n", "operator:1")},
        merge=True,
    )
    assert sorted(home.authored()) == ["I-1", "I-1-v2"]
    # without merge a save replaces (registration's contract), so the flag is what
    # keeps the superseded item's oracle on record
    home.save_authored({"I-9": AuthoredTest("t.py", "x\n", "operator:1")})
    assert sorted(home.authored()) == ["I-9"]


def test_register_evolution_needs_a_backlog(tmp_path: Path) -> None:
    with pytest.raises(LookupError, match="no backlog registered"):
        FactoryHome(tmp_path, "nothing").register_evolution(_item("I-1"), actor="x")
    assert replace(_item("I-1"), supersedes="").supersedes == ""


# --- PR #55 review: a pull request's fate is read only in the repository it went to ------


def test_the_sync_never_reads_a_pull_request_in_a_repository_the_row_was_relinked_to(
    home: FactoryHome,
) -> None:
    """The sync read each delivered pull request by NUMBER in the repository the row is
    linked to now. After a re-link it read pull request 7 of the new repository and
    recorded that stranger's merge or close as this item's outcome. The sync now names
    the repository it reads, and a delivery to another one is an error in the report —
    never read, never recorded."""
    ev = home.evidence(actor="worker")
    ev.record_delivery(_delivery("I-1", 7))
    reads: list[int] = []

    def read_pr(n: int) -> PullRequest:
        reads.append(n)
        return PullRequest.from_api(PR_MERGED_API)

    report = sync_outcomes(home, read_pr, actor="worker", repository="other/calc")
    assert reads == [] and (report.checked, report.merged, report.closed) == (1, 0, 0)
    (error,) = report.errors
    assert "acme/calc" in error and "other/calc" in error
    assert home.evidence().outcome_for("I-1", 7) is None
    # the repository it went to: read, and recorded
    again = sync_outcomes(home, read_pr, actor="worker", repository="Acme/Calc")
    assert reads == [7] and again.merged == 1 and again.errors == []
